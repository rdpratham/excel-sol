"""
Executes a ParsedQuery against a sheet's rows using an in-memory DuckDB
table. Column identifiers are always resolved against the sheet's real
column list before reaching SQL (see nlq._resolve_column), so they're
never raw user text; filter values go through parameter binding.
"""

from __future__ import annotations

from typing import Any

import duckdb
import pandas as pd

from app.services.nlq import Filter, ParsedQuery


def _coerce_dtypes(df: pd.DataFrame, columns_meta: list[dict]) -> pd.DataFrame:
    for col in columns_meta:
        name = col.get("name")
        if name not in df.columns:
            continue
        dtype = col.get("dtype")
        if dtype == "number":
            df[name] = pd.to_numeric(df[name], errors="coerce")
        elif dtype == "date":
            df[name] = pd.to_datetime(df[name], errors="coerce")
    return df


def _quote(identifier: str) -> str:
    return '"' + identifier.replace('"', '""') + '"'


def _build_where(filters: list[Filter]) -> tuple[str, list[Any]]:
    if not filters:
        return "", []
    clauses = []
    params: list[Any] = []
    for f in filters:
        col = _quote(f.column)
        clauses.append(f"{col} LIKE ?" if f.op == "LIKE" else f"{col} {f.op} ?")
        params.append(f.value)
    return " AND ".join(clauses), params


def run_query(parsed: ParsedQuery, rows: list[dict], columns_meta: list[dict]) -> dict:
    col_names = [c["name"] for c in columns_meta]
    df = pd.DataFrame(rows, columns=col_names) if rows else pd.DataFrame(columns=col_names)
    df = _coerce_dtypes(df, columns_meta)

    con = duckdb.connect()
    try:
        con.register("sheet", df)
        where_sql, params = _build_where(parsed.filters)

        if not parsed.select_all and parsed.agg is None and parsed.distinct:
            # "unique X" / "distinct X" — list the column's distinct values
            col = _quote(parsed.metric_col)
            sql = f"SELECT DISTINCT {col} FROM sheet"
            if where_sql:
                sql += f" WHERE {where_sql}"
            sql += f" ORDER BY {col} LIMIT {parsed.limit}"
        elif not parsed.select_all:
            select_parts = []
            if parsed.group_col:
                select_parts.append(_quote(parsed.group_col))
            if parsed.agg == "COUNT" and not parsed.metric_col:
                agg_expr = "COUNT(*)"
            elif parsed.agg == "COUNT" and parsed.distinct:
                agg_expr = f"COUNT(DISTINCT {_quote(parsed.metric_col)})"
            else:
                agg_expr = f"{parsed.agg}({_quote(parsed.metric_col)})"
            select_parts.append(f"{agg_expr} AS result")

            sql = f"SELECT {', '.join(select_parts)} FROM sheet"
            if where_sql:
                sql += f" WHERE {where_sql}"
            if parsed.group_col:
                sql += f" GROUP BY {_quote(parsed.group_col)} ORDER BY result DESC"
            sql += f" LIMIT {parsed.limit}"
        else:
            sql = "SELECT * FROM sheet"
            if where_sql:
                sql += f" WHERE {where_sql}"
            if parsed.sort_col:
                sql += f" ORDER BY {_quote(parsed.sort_col)} {'DESC' if parsed.sort_desc else 'ASC'}"
            sql += f" LIMIT {parsed.limit}"

        cur = con.execute(sql, params)
        out_columns = [d[0] for d in cur.description]
        out_rows = [dict(zip(out_columns, row)) for row in cur.fetchall()]
    finally:
        con.close()

    return {"sql": sql, "columns": out_columns, "rows": out_rows}
