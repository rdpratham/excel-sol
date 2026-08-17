"""
Rule-based plain-language query parser.

No LLM, no external API calls — a fixed set of regex patterns maps common
analytic phrasings ("average price by category", "top 5 by revenue",
"show rows where status is active") onto a small structured query object,
which query_runner.py then turns into DuckDB SQL. Anything outside the
supported grammar returns a QueryParseError with example phrasings rather
than a guess.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from difflib import get_close_matches
from typing import Any, Optional

AGG_WORDS = r"sum|total|average|avg|mean|count|max|maximum|highest|min|minimum|lowest"

AGG_MAP = {
    "sum": "SUM", "total": "SUM",
    "average": "AVG", "avg": "AVG", "mean": "AVG",
    "count": "COUNT",
    "max": "MAX", "maximum": "MAX", "highest": "MAX",
    "min": "MIN", "minimum": "MIN", "lowest": "MIN",
}

# Ordered longest/most-specific phrase first so e.g. "at least" wins over "least"
OP_PATTERNS: list[tuple[str, str]] = [
    (r"greater than or equal to|at least|>=", ">="),
    (r"less than or equal to|at most|<=", "<="),
    (r"not equal to|is not|!=|<>", "!="),
    (r"greater than|>", ">"),
    (r"less than|<", "<"),
    (r"equal(?:s)? to|equals|is|==|=", "="),
]

_CONTAINS_RE = re.compile(r"^\s*(.+?)\s+contains\s+(.+)$", re.I)
_STARTS_RE = re.compile(r"^\s*(.+?)\s+starts with\s+(.+)$", re.I)
_ENDS_RE = re.compile(r"^\s*(.+?)\s+ends with\s+(.+)$", re.I)

_GROUP_AGG_RE = re.compile(
    rf"^(?:what(?:'s| is)?\s+the\s+)?({AGG_WORDS})\s*(?:of\s+)?(.*?)\s+by\s+(.+?)(?:\s+where\s+(.+))?$",
    re.I,
)
_AGG_RE = re.compile(
    rf"^(?:what(?:'s| is)?\s+the\s+)?({AGG_WORDS})\s*(?:of\s+)?(.*?)(?:\s+where\s+(.+))?$",
    re.I,
)
_UNIQUE_COUNT_RE = re.compile(
    r"^(?:how many|count(?:\s+of)?|number of)\s+(?:unique|distinct|different)\s+"
    r"(.+?)(?:\s+are there|\s+are\s+there)?(?:\s+where\s+(.+))?$",
    re.I,
)
_UNIQUE_LIST_RE = re.compile(
    r"^(?:unique|distinct)\s+(.+?)(?:\s+values?)?(?:\s+where\s+(.+))?$", re.I,
)
_TOPN_RE = re.compile(r"^top\s+(\d+)\s*(?:.*?\s+)?by\s+(.+)$", re.I)
_SORT_RE = re.compile(r"^(?:sort|order)(?:ed)?\s+by\s+(.+?)(?:\s+(asc|ascending|desc|descending))?$", re.I)
_FILTER_RE = re.compile(r"^(?:show|find|list|get)\s+(?:me\s+)?(?:all\s+)?(?:rows|records)?\s*where\s+(.+)$", re.I)
_BARE_WHERE_RE = re.compile(r"^where\s+(.+)$", re.I)

_FILLER_METRICS = {"", "rows", "records", "all", "them", "it"}


class QueryParseError(Exception):
    pass


@dataclass
class Filter:
    column: str
    op: str  # =, !=, >, <, >=, <=, LIKE
    value: Any


@dataclass
class ParsedQuery:
    select_all: bool = True
    agg: Optional[str] = None  # SUM / AVG / COUNT / MAX / MIN
    metric_col: Optional[str] = None
    group_col: Optional[str] = None
    filters: list[Filter] = field(default_factory=list)
    sort_col: Optional[str] = None
    sort_desc: bool = False
    distinct: bool = False  # COUNT(DISTINCT col) or SELECT DISTINCT col
    limit: int = 500


def _normalize(s: str) -> str:
    return re.sub(r"[^a-z0-9]", "", s.lower())


def _resolve_column(phrase: str, columns: list[str]) -> str:
    phrase_clean = phrase.strip().strip("'\"")
    if not phrase_clean:
        raise QueryParseError("Which column did you mean? Try naming it explicitly.")

    for c in columns:
        if c.lower() == phrase_clean.lower():
            return c

    norm_target = _normalize(phrase_clean)
    norm_map = {_normalize(c): c for c in columns}
    if norm_target in norm_map:
        return norm_map[norm_target]

    close = get_close_matches(norm_target, norm_map.keys(), n=1, cutoff=0.6)
    if close:
        return norm_map[close[0]]

    raise QueryParseError(
        f'I couldn\'t find a column called "{phrase_clean}". '
        f"Available columns: {', '.join(columns)}"
    )


def _parse_value(raw: str) -> Any:
    v = raw.strip().strip("'\"")
    if re.fullmatch(r"-?\d+", v):
        return int(v)
    if re.fullmatch(r"-?\d+\.\d+", v):
        return float(v)
    return v


def _split_conditions(clause: str) -> list[str]:
    return re.split(r"\s+and\s+", clause.strip(), flags=re.I)


def _strip_quotes(s: str) -> str:
    return s.strip().strip("'\"")


def _parse_condition(clause: str, columns: list[str]) -> Filter:
    m = _CONTAINS_RE.match(clause)
    if m:
        return Filter(_resolve_column(m.group(1), columns), "LIKE", f"%{_strip_quotes(m.group(2))}%")
    m = _STARTS_RE.match(clause)
    if m:
        return Filter(_resolve_column(m.group(1), columns), "LIKE", f"{_strip_quotes(m.group(2))}%")
    m = _ENDS_RE.match(clause)
    if m:
        return Filter(_resolve_column(m.group(1), columns), "LIKE", f"%{_strip_quotes(m.group(2))}")

    for pattern, op in OP_PATTERNS:
        m = re.match(rf"^\s*(.+?)\s+(?:{pattern})\s+(.+)$", clause, re.I)
        if m:
            return Filter(_resolve_column(m.group(1), columns), op, _parse_value(m.group(2)))

    raise QueryParseError(
        f'I couldn\'t understand the condition "{clause.strip()}". '
        f'Try e.g. "status is Active" or "price greater than 100".'
    )


def _parse_filters(where_phrase: str | None, columns: list[str]) -> list[Filter]:
    if not where_phrase:
        return []
    return [_parse_condition(c, columns) for c in _split_conditions(where_phrase)]


def parse_query(text: str, columns: list[str]) -> ParsedQuery:
    if not columns:
        raise QueryParseError("This sheet has no columns to query yet.")

    q = text.strip()
    if not q:
        raise QueryParseError('Type a question about your data, e.g. "average price by category".')

    # Top N by <column>
    m = _TOPN_RE.match(q)
    if m:
        n, sort_phrase = m.groups()
        sort_col = _resolve_column(sort_phrase, columns)
        return ParsedQuery(sort_col=sort_col, sort_desc=True, limit=min(int(n), 5000))

    # "how many unique X [are there]", "count distinct X", "number of unique X"
    m = _UNIQUE_COUNT_RE.match(q)
    if m:
        col_phrase, where_phrase = m.groups()
        col = _resolve_column(col_phrase, columns)
        filters = _parse_filters(where_phrase, columns)
        return ParsedQuery(select_all=False, agg="COUNT", metric_col=col, distinct=True, filters=filters, limit=1)

    # "unique X", "distinct X [values]" — lists the distinct values themselves
    m = _UNIQUE_LIST_RE.match(q)
    if m:
        col_phrase, where_phrase = m.groups()
        col = _resolve_column(col_phrase, columns)
        filters = _parse_filters(where_phrase, columns)
        return ParsedQuery(
            select_all=False, agg=None, metric_col=col, distinct=True,
            filters=filters, sort_col=col, limit=1000,
        )

    # Aggregate with GROUP BY, optional WHERE
    m = _GROUP_AGG_RE.match(q)
    if m:
        agg_word, metric_phrase, group_phrase, where_phrase = m.groups()
        agg = AGG_MAP[agg_word.lower()]
        group_col = _resolve_column(group_phrase, columns)
        metric_phrase = (metric_phrase or "").strip()
        metric_col = None
        if metric_phrase.lower() not in _FILLER_METRICS:
            metric_col = _resolve_column(metric_phrase, columns)
        elif agg != "COUNT":
            raise QueryParseError(f'Say which column to {agg_word}, e.g. "{agg_word} of sales by region".')
        filters = _parse_filters(where_phrase, columns)
        return ParsedQuery(
            select_all=False, agg=agg, metric_col=metric_col, group_col=group_col,
            filters=filters, limit=5000,
        )

    # Plain aggregate, optional WHERE
    m = _AGG_RE.match(q)
    if m:
        agg_word, metric_phrase, where_phrase = m.groups()
        agg = AGG_MAP[agg_word.lower()]
        metric_phrase = (metric_phrase or "").strip()
        metric_col = None
        if metric_phrase.lower() not in _FILLER_METRICS:
            metric_col = _resolve_column(metric_phrase, columns)
        elif agg != "COUNT":
            raise QueryParseError(f'Say which column to {agg_word}, e.g. "{agg_word} of sales".')
        filters = _parse_filters(where_phrase, columns)
        return ParsedQuery(select_all=False, agg=agg, metric_col=metric_col, filters=filters, limit=1)

    # Sort
    m = _SORT_RE.match(q)
    if m:
        col_phrase, direction = m.groups()
        sort_col = _resolve_column(col_phrase, columns)
        desc = bool(direction and direction.lower().startswith("desc"))
        return ParsedQuery(sort_col=sort_col, sort_desc=desc, limit=500)

    # "show/find/list rows where ..."
    m = _FILTER_RE.match(q)
    if m:
        return ParsedQuery(filters=_parse_filters(m.group(1), columns), limit=1000)

    # Bare "where ..."
    m = _BARE_WHERE_RE.match(q)
    if m:
        return ParsedQuery(filters=_parse_filters(m.group(1), columns), limit=1000)

    raise QueryParseError(
        "I didn't recognise that pattern. Try things like: "
        '"average price by category", "show rows where status is Active", '
        '"top 5 by revenue", or "sort by date descending".'
    )
