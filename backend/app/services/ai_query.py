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


@dataclass
class AIReorderPlan:
    column: str
    priority_values: list[str]
    message: str


@dataclass
class AIDeletePlan:
    filters: list[Filter]
    message: str


@dataclass
class AIAddRowPlan:
    data: dict[str, Any]
    message: str


def is_available() -> bool:
    return bool(settings.OPENROUTER_API_KEY)


def _build_prompt(question: str, columns_meta: list[dict]) -> str:
    schema_desc = ", ".join(f'"{c["name"]}" ({c.get("dtype", "text")})' for c in columns_meta)
    return (
        'You are a data assistant. There is exactly one table available, named "sheet", '
        f"with these columns: {schema_desc}.\n\n"
        f'User message: "{question}"\n\n'
        "First decide which one of these five intents the message is:\n"
        "  read — asking for information about the data\n"
        "  write — asking to change, update, set, or replace values already in the sheet\n"
        '  reorder — asking to physically move/rearrange rows (e.g. "put C-suite people at '
        'the top, then Directors") based on which group a row belongs to, not a plain '
        "ascending/descending sort\n"
        "  delete — asking to remove rows that match some condition\n"
        "  add_row — asking to add a brand-new row with specific values\n\n"
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
        'If it is a REORDER request, use exactly these keys:\n'
        '  "intent": "reorder"\n'
        '  "column": the exact column name whose values determine the grouping (must be one '
        "of the columns listed above)\n"
        '  "priority_values": an ordered list of that column\'s values, from what should '
        'appear at the top to what comes next (e.g. ["C-suite", "Director"]); rows whose '
        "value isn't in this list keep their current relative order and are placed after "
        "every listed group\n"
        '  "message": a short, friendly, one-sentence description, e.g. \'Moving rows where '
        'Role is "C-suite" to the top, then "Director".\'\n\n'
        'If it is a DELETE request, use exactly these keys:\n'
        '  "intent": "delete"\n'
        '  "filters": a non-empty list of {"column", "op", "value"} objects describing which '
        "rows to delete (op is one of =, !=, >, <, >=, <=) — always require at least one real "
        "filter; if the user's message doesn't give you one, set \"filters\" to an empty list "
        'and use "message" to ask them which rows they mean instead of guessing\n'
        '  "message": a short, friendly, one-sentence description, e.g. \'Deleting rows where '
        'Status is "Cancelled".\'\n\n'
        'If it is an ADD_ROW request, use exactly these keys:\n'
        '  "intent": "add_row"\n'
        '  "data": an object mapping column name to value for the new row (only use column '
        "names from the list above; omit columns the user didn't specify a value for)\n"
        '  "message": a short, friendly, one-sentence description, e.g. \'Adding a new row '
        "with Name \\\"Jane\\\" and Status \\\"Active\\\".'\n\n"
        "Never invent a column name that isn't in the list above. Never respond with SQL for "
        "a write, reorder, delete, or add_row request — those are always expressed with the "
        "structured fields described above, never raw SQL. If the request describes different "
        'changes for different groups of rows (e.g. "give C-suite a 10% raise and everyone '
        'else 5%"), only describe ONE of the two groups in this reply and say in "message" '
        "that the other group needs a separate follow-up command — never invent a way to "
        "encode two different amounts in one plan."
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


def _validate_reorder(parsed: dict, column_names: list[str]) -> AIReorderPlan:
    message = parsed.get("message") or "Here's how I'd reorder the rows."

    col_raw = parsed.get("column")
    if not col_raw:
        raise AIQueryError(message)
    try:
        column = _resolve_column(str(col_raw), column_names)
    except QueryParseError as e:
        raise AIQueryError(str(e))

    priority_values = [str(v) for v in (parsed.get("priority_values") or []) if v is not None]
    if not priority_values:
        raise AIQueryError("The AI didn't say which values should come first — try rephrasing.")

    return AIReorderPlan(column=column, priority_values=priority_values, message=message)


def _validate_delete(parsed: dict, column_names: list[str]) -> AIDeletePlan:
    message = parsed.get("message") or "Here's what I'd delete."

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

    if not filters:
        raise AIQueryError(message)

    return AIDeletePlan(filters=filters, message=message)


def _validate_add_row(parsed: dict, column_names: list[str]) -> AIAddRowPlan:
    message = parsed.get("message") or "Here's the row I'd add."

    raw_data = parsed.get("data")
    if not isinstance(raw_data, dict) or not raw_data:
        raise AIQueryError(message)

    data: dict[str, Any] = {}
    for col_raw, value in raw_data.items():
        try:
            column = _resolve_column(str(col_raw), column_names)
        except QueryParseError as e:
            raise AIQueryError(str(e))
        data[column] = value

    return AIAddRowPlan(data=data, message=message)


async def classify(
    question: str, columns_meta: list[dict]
) -> AISelectPlan | AIWritePlan | AIReorderPlan | AIDeletePlan | AIAddRowPlan:
    """Sends the message to the LLM and returns a read plan (SQL to run), a
    write plan (column/filters/op/value), a reorder plan
    (column/priority_values), a delete plan (filters), or an add_row plan
    (data) — never raw SQL for a mutation. Raises AIQueryError if
    unavailable, unparseable, or unsafe."""
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
    intent = parsed.get("intent")
    if intent == "write":
        return _validate_write(parsed, column_names)
    if intent == "reorder":
        return _validate_reorder(parsed, column_names)
    if intent == "delete":
        return _validate_delete(parsed, column_names)
    if intent == "add_row":
        return _validate_add_row(parsed, column_names)
    return _validate_read(parsed)
