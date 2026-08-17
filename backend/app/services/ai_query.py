"""
Optional LLM fallback for the "Ask AI" query panel.

Only invoked when the free, deterministic rule-based parser (nlq.py) can't
match a question — most common analytic questions (sums, filters, sorts,
top-N, distinct counts) are answered by that path with zero latency and
zero external calls. This module is the escape hatch for genuinely
open-ended questions, and is a no-op unless OPENROUTER_API_KEY is set.

Design: the LLM only ever translates the question into a DuckDB SELECT
statement against the sheet's own data — it never sees or touches
anything else, and the statement is executed through a *sandboxed*
DuckDB connection (enable_external_access=False in query_runner.run_raw_sql)
that has no filesystem or network access, so even a wild or adversarial
model response can't read files or reach out — worst case it's a SQL
error surfaced back to the user like any other bad query.
"""

from __future__ import annotations

import json
import re

import httpx

from app.config import settings

OPENROUTER_URL = "https://openrouter.ai/api/v1/chat/completions"

_SELECT_ONLY_RE = re.compile(r"^\s*select\b", re.I)


class AIQueryError(Exception):
    pass


def is_available() -> bool:
    return bool(settings.OPENROUTER_API_KEY)


def _build_prompt(question: str, columns_meta: list[dict]) -> str:
    schema_desc = ", ".join(f'"{c["name"]}" ({c.get("dtype", "text")})' for c in columns_meta)
    return (
        'You are a data analyst. There is exactly one table available, named "sheet", '
        f"with these columns: {schema_desc}.\n\n"
        f'User question: "{question}"\n\n'
        "Respond with ONLY a raw JSON object (no markdown fences, no extra text) with "
        "exactly these two keys:\n"
        '  "sql": a single valid DuckDB SELECT statement against the "sheet" table that '
        'answers the question, always including a LIMIT clause of at most 1000, or null '
        "if the question can't be answered from this schema\n"
        '  "message": a short, friendly, one-sentence natural-language answer or '
        "explanation of what the query does\n"
        "Only ever use SELECT — never modify data, never reference any table besides "
        '"sheet", never reference a column not listed above.'
    )


def _extract_json(text: str) -> dict:
    # Models sometimes wrap JSON in a markdown fence despite instructions not to
    cleaned = re.sub(r"^```(?:json)?\s*|\s*```$", "", text.strip(), flags=re.I).strip()
    try:
        return json.loads(cleaned)
    except json.JSONDecodeError:
        raise AIQueryError("AI returned a response I couldn't parse — try rephrasing.")


def _validate_sql(parsed: dict) -> tuple[str, str]:
    sql = parsed.get("sql")
    message = parsed.get("message") or "Here's what I found."

    if not sql:
        raise AIQueryError(message)

    stripped = sql.strip().rstrip(";")
    if not _SELECT_ONLY_RE.match(stripped) or ";" in stripped:
        raise AIQueryError("The AI's answer wasn't a safe read-only query — try rephrasing.")

    return stripped, message


async def generate_sql(question: str, columns_meta: list[dict]) -> tuple[str, str]:
    """Returns (sql, message). Raises AIQueryError if unavailable or unsafe."""
    if not settings.OPENROUTER_API_KEY:
        raise AIQueryError("AI query isn't configured for this deployment.")

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

    if resp.status_code != 200:
        raise AIQueryError(f"AI request failed (HTTP {resp.status_code}).")

    try:
        text = resp.json()["choices"][0]["message"]["content"]
    except (KeyError, IndexError, ValueError):
        raise AIQueryError("AI returned an unexpected response.")

    parsed = _extract_json(text)
    return _validate_sql(parsed)
