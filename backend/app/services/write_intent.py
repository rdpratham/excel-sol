"""
Rule-based parser for natural-language *write* commands in the AI Assistant
chat — "change status from Pending to Active", "replace Old with New in
Company", "set price to 100 where category is Fruit", "increase price by
10% where category is Fruit". Reuses the same column-resolution and filter
grammar as nlq.py (read-only queries), so a "where ..." clause parses
identically on both sides.

Deliberately narrow: it only matches phrasings that name the target column
and the new value/amount explicitly. A vaguer instruction like "change the
Afresh company name to XYZ" (value before column, filter implied by an
example value rather than a named column) or "give the C-suite a raise"
(no explicit column/number) doesn't match any pattern here and is expected
to fall through to the LLM classifier (ai_query.classify) instead — this
module never guesses.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any

from app.services.nlq import Filter, QueryParseError, _parse_filters, _parse_value, _resolve_column

_CHANGE_FROM_TO_RE = re.compile(
    r"^change\s+(.+?)\s+from\s+(.+?)\s+to\s+(.+?)(?:\s+where\s+(.+))?$", re.I
)
_REPLACE_WITH_IN_RE = re.compile(
    r"^replace\s+(.+?)\s+with\s+(.+?)\s+in\s+(.+?)(?:\s+where\s+(.+))?$", re.I
)
_SET_WHERE_RE = re.compile(r"^set\s+(.+?)\s+to\s+(.+?)\s+where\s+(.+)$", re.I)
_UPDATE_WHERE_RE = re.compile(r"^update\s+(.+?)\s+to\s+(.+?)\s+where\s+(.+)$", re.I)
_INCREASE_BY_RE = re.compile(
    r"^increase\s+(.+?)\s+by\s+(\d+(?:\.\d+)?)\s*(%|percent)?(?:\s+where\s+(.+))?$", re.I
)
_DECREASE_BY_RE = re.compile(
    r"^decrease\s+(.+?)\s+by\s+(\d+(?:\.\d+)?)\s*(%|percent)?(?:\s+where\s+(.+))?$", re.I
)

# op: "set" — value is the literal to write.
#     "increase_by" / "decrease_by" — value is added/subtracted from the
#     current cell (numeric columns only).
#     "increase_by_percent" / "decrease_by_percent" — value is a percentage
#     applied to the current cell.
_RELATIVE_OPS = {"increase_by", "decrease_by", "increase_by_percent", "decrease_by_percent"}


@dataclass
class WriteIntent:
    column: str
    filters: list[Filter]
    value: Any
    op: str = "set"


def matches_filters(row_data: dict, filters: list[Filter]) -> bool:
    """Evaluates the same filter grammar nlq.py compiles to SQL, but directly
    against an in-memory row dict — used to preview/execute a write against
    real SheetRow data without a DuckDB round-trip."""
    for f in filters:
        value = row_data.get(f.column)

        if f.op == "LIKE":
            haystack = "" if value is None else str(value).lower()
            pattern = str(f.value).lower()
            if pattern.startswith("%") and pattern.endswith("%"):
                if pattern[1:-1] not in haystack:
                    return False
            elif pattern.endswith("%"):
                if not haystack.startswith(pattern[:-1]):
                    return False
            elif pattern.startswith("%"):
                if not haystack.endswith(pattern[1:]):
                    return False
            elif haystack != pattern:
                return False
            continue

        if value is None:
            return False

        try:
            a, b = float(value), float(f.value)
        except (TypeError, ValueError):
            a, b = str(value), str(f.value)

        if f.op == "=" and not a == b:
            return False
        if f.op == "!=" and not a != b:
            return False
        if f.op == ">" and not a > b:
            return False
        if f.op == "<" and not a < b:
            return False
        if f.op == ">=" and not a >= b:
            return False
        if f.op == "<=" and not a <= b:
            return False

    return True


def apply_op(current: Any, op: str, value: Any) -> Any | None:
    """Computes the new cell value for one row. For "set" this is just the
    literal value; for the relative ops it reads the current numeric value
    and applies the amount/percentage. Returns None when a relative op
    can't be applied (current value isn't numeric) — the caller treats that
    row as not eligible rather than erroring the whole command out."""
    if op == "set":
        return value

    try:
        current_num = float(current)
        amount = float(value)
    except (TypeError, ValueError):
        return None

    if op == "increase_by":
        result = current_num + amount
    elif op == "decrease_by":
        result = current_num - amount
    elif op == "increase_by_percent":
        result = current_num * (1 + amount / 100)
    elif op == "decrease_by_percent":
        result = current_num * (1 - amount / 100)
    else:
        return None

    return int(result) if result == int(result) else round(result, 2)


def parse_write_intent(text: str, columns: list[str]) -> WriteIntent | None:
    """Returns a WriteIntent if the text matches a supported write phrasing,
    or None if it doesn't (never raises for "doesn't match" — that's the
    caller's cue to try the read-only parser / LLM fallback next). Still
    raises QueryParseError for a phrasing that matches structurally but
    names a column that doesn't exist, so the user gets a helpful message
    instead of silently falling through."""
    q = text.strip()
    if not q:
        return None

    m = _CHANGE_FROM_TO_RE.match(q)
    if m:
        col_phrase, old_phrase, new_phrase, where_phrase = m.groups()
        column = _resolve_column(col_phrase, columns)
        filters = [Filter(column, "=", _parse_value(old_phrase))]
        filters.extend(_parse_filters(where_phrase, columns))
        return WriteIntent(column=column, filters=filters, value=_parse_value(new_phrase))

    m = _REPLACE_WITH_IN_RE.match(q)
    if m:
        old_phrase, new_phrase, col_phrase, where_phrase = m.groups()
        column = _resolve_column(col_phrase, columns)
        filters = [Filter(column, "=", _parse_value(old_phrase))]
        filters.extend(_parse_filters(where_phrase, columns))
        return WriteIntent(column=column, filters=filters, value=_parse_value(new_phrase))

    m = _SET_WHERE_RE.match(q)
    if m:
        col_phrase, new_phrase, where_phrase = m.groups()
        column = _resolve_column(col_phrase, columns)
        filters = _parse_filters(where_phrase, columns)
        return WriteIntent(column=column, filters=filters, value=_parse_value(new_phrase))

    m = _UPDATE_WHERE_RE.match(q)
    if m:
        col_phrase, new_phrase, where_phrase = m.groups()
        column = _resolve_column(col_phrase, columns)
        filters = _parse_filters(where_phrase, columns)
        return WriteIntent(column=column, filters=filters, value=_parse_value(new_phrase))

    m = _INCREASE_BY_RE.match(q)
    if m:
        col_phrase, amount, pct, where_phrase = m.groups()
        column = _resolve_column(col_phrase, columns)
        filters = _parse_filters(where_phrase, columns)
        op = "increase_by_percent" if pct else "increase_by"
        return WriteIntent(column=column, filters=filters, value=float(amount), op=op)

    m = _DECREASE_BY_RE.match(q)
    if m:
        col_phrase, amount, pct, where_phrase = m.groups()
        column = _resolve_column(col_phrase, columns)
        filters = _parse_filters(where_phrase, columns)
        op = "decrease_by_percent" if pct else "decrease_by"
        return WriteIntent(column=column, filters=filters, value=float(amount), op=op)

    return None
