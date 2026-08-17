"""
Optional LLM fallback for the "Ask AI" query panel.

Only invoked when the free, deterministic rule-based parsers (nlq.py for
reads, write_intent.py for writes) can't match a message — most common
analytic questions (sums, filters, sorts, top-N, distinct counts) and
common write phrasings ("change X from A to B where ...") are answered by
those paths with zero latency and zero external calls. This module is the
escape hatch for genuinely open-ended phrasings, and is a no-op unless
OPENROUTER_API_KEY is set.

Design: the LLM either translates the message into a DuckDB SELECT
statement (read intent) or proposes a structured column/filters/new_value
plan (write intent) — it never gets to write raw SQL for a mutation. A
read SQL statement runs through a *sandboxed* DuckDB connection
(enable_external_access=False in query_runner.run_raw_sql) that has no
filesystem or network access. A write plan is never executed directly:
classify() re-validates every column name the model names against the
sheet's real schema (the same fuzzy matching nlq.py uses for reads), and
the caller (app.api.v1.query) is the only place that turns a validated
plan into an actual UPDATE — so even a wild or adversarial model response
can, at worst, propose a nonsense value for a real column, never touch
data outside the sheet or run arbitrary SQL.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from typing import Any

import httpx

from app.config import settings
from app.services.nlq import Filter, QueryParseError, _resolve_column

OPENROUTER_URL = "https://openrouter.ai/api/v1/chat/completions"

_SELECT_ONLY_RE = re.compile(r"^\s*select\b", re.I)
_VALID_OPS = {"=", "!=", ">", "<", ">=", "<="}


class AIQueryError(Exception):
    pass


@dataclass
class AISelectPlan:
    sql: str
    message: str


@dataclass
class AIWritePlan:
    column: str
    filters: list[Filter]
    value: Any
    message: str
    op: str = "set"


def is_available() -> bool:
    return bool(settings.OPENROUTER_API_KEY)


def _build_prompt(question: str, columns_meta: list[dict]) -> str:
    schema_desc = ", ".join(f'"{c["name"]}" ({c.get("dtype", "text")})' for c in columns_meta)
    return (
        'You are a data assistant. There is exactly one table available, named "sheet", '
        f"with these columns: {schema_desc}.\n\n"
        f'User message: "{question}"\n\n'
        "First decide whether this is a READ request (asking for information about the "
        'data) or a WRITE request (asking to change, update, set, or replace data in the '
        "sheet).\n\n"
        "Respond with ONLY a raw JSON object (no markdown fences, no extra text).\n\n"
        'If it is a READ request, use exactly these keys:\n'
        '  "intent": "read"\n'
        '  "sql": a single valid DuckDB SELECT statement against the "sheet" table that '
        'answers the question, always including a LIMIT clause of at most 1000, or null '
        "if the question can't be answered from this schema\n"
        '  "message": a short, friendly, one-sentence natural-language answer\n\n'
        'If it is a WRITE request, use exactly these keys:\n'
        '  "intent": "write"\n'
        '  "column": the exact name of the column to change (must be one of the columns '
        "listed above)\n"
        '  "filters": a list of {"column", "op", "value"} objects describing which rows to '
        'change (op is one of =, !=, >, <, >=, <=); use an empty list to mean every row\n'
        '  "write_op": one of "set" (replace with a literal value), "increase_by" / '
        '"decrease_by" (add/subtract a number from the current cell), or '
        '"increase_by_percent" / "decrease_by_percent" (e.g. give a 10% raise) — pick '
        'whichever matches the request; use "set" for anything that just names a new value\n'
        '  "value": for "set", the literal value to write; for the other write_ops, the '
        "number to add/subtract or the percentage\n"
        '  "message": a short, friendly, one-sentence description of the change, e.g. '
        '\'Setting "Company" to "XYZ" for rows where Company is "Afresh".\' or '
        '\'Increasing "Salary" by 10% for rows where Role is "C-suite".\'\n\n'
        "Never invent a column name that isn't in the list above. Never respond with SQL "
        "for a write request — writes are always column/filters/write_op/value, never raw "
        "SQL. If the request describes different changes for different groups of rows (e.g. "
        '"give C-suite a 10% raise and everyone else 5%"), only describe ONE of the two '
        "groups in this reply and say in \"message\" that the other group needs a separate "
        "follow-up command — never invent a way to encode two different amounts in one plan."
    )


def _extract_json(text: str) -> dict:
    # Models sometimes wrap JSON in a markdown fence despite instructions not to
    cleaned = re.sub(r"^```(?:json)?\s*|\s*```$", "", text.strip(), flags=re.I).strip()
    try:
        return json.loads(cleaned)
    except json.JSONDecodeError:
        raise AIQueryError("AI returned a response I couldn't parse — try rephrasing.")


def _validate_read(parsed: dict) -> AISelectPlan:
    sql = parsed.get("sql")
    message = parsed.get("message") or "Here's what I found."

    if not sql:
        raise AIQueryError(message)

    stripped = sql.strip().rstrip(";")
    if not _SELECT_ONLY_RE.match(stripped) or ";" in stripped:
        raise AIQueryError("The AI's answer wasn't a safe read-only query — try rephrasing.")

    return AISelectPlan(sql=stripped, message=message)


def _validate_write(parsed: dict, column_names: list[str]) -> AIWritePlan:
    message = parsed.get("message") or "Here's the change I'd make."

    col_raw = parsed.get("column")
    if not col_raw:
        raise AIQueryError(message)
    try:
        column = _resolve_column(str(col_raw), column_names)
    except QueryParseError as e:
        raise AIQueryError(str(e))

    # Accept "value" (current schema) and fall back to the older "new_value"
    # key in case the model doesn't follow the prompt exactly.
    value = parsed.get("value", parsed.get("new_value"))
    if value is None:
        raise AIQueryError(message)

    write_op = parsed.get("write_op") or parsed.get("op") or "set"
    if write_op not in {"set", "increase_by", "decrease_by", "increase_by_percent", "decrease_by_percent"}:
        write_op = "set"

    filters: list[Filter] = []
    for raw_filter in parsed.get("filters") or []:
        if not isinstance(raw_filter, dict) or not raw_filter.get("column"):
            continue
        try:
            filter_col = _resolve_column(str(raw_filter["column"]), column_names)
        except QueryParseError as e:
            raise AIQueryError(str(e))
        op = raw_filter.get("op") if raw_filter.get("op") in _VALID_OPS else "="
        filters.append(Filter(filter_col, op, raw_filter.get("value")))

    return AIWritePlan(column=column, filters=filters, value=value, message=message, op=write_op)


async def classify(question: str, columns_meta: list[dict]) -> AISelectPlan | AIWritePlan:
    """Sends the message to the LLM and returns either a read plan (SQL to
    run) or a write plan (structured column/filters/new_value, never raw
    SQL). Raises AIQueryError if unavailable, unparseable, or unsafe."""
    if not settings.OPENROUTER_API_KEY:
        raise AIQueryError("AI query isn't configured for this deployment.")

    column_names = [c["name"] for c in columns_meta]
    prompt = _build_prompt(question, columns_meta)

    try:
        async with httpx.AsyncClient(timeout=20.0) as client:
            resp = await client.post(
                OPENROUTER_URL,
                headers={"Authorization": f"Bearer {settings.OPENROUTER_API_KEY}"},
                json={
                    "model": settings.OPENROUTER_MODEL,
                    "messages": [{"role": "user", "content": prompt}],
                },
            )
    except httpx.HTTPError:
        raise AIQueryError("Couldn't reach the AI service — please try again.")

    if resp.status_code == 429:
        raise AIQueryError("The AI is rate-limited right now (free tier) — please wait a few seconds and try again.")
    if resp.status_code != 200:
        raise AIQueryError(f"AI request failed (HTTP {resp.status_code}).")

    try:
        text = resp.json()["choices"][0]["message"]["content"]
    except (KeyError, IndexError, ValueError):
        raise AIQueryError("AI returned an unexpected response.")

    parsed = _extract_json(text)
    if parsed.get("intent") == "write":
        return _validate_write(parsed, column_names)
    return _validate_read(parsed)
