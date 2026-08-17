"""
Plain-language querying over a sheet's data.

  POST /files/{file_id}/sheets/{sheet_id}/query          — ask a question
  GET  /files/{file_id}/sheets/{sheet_id}/query/history   — past Q&A for this sheet

Two-tier engine: nlq.py pattern-matches a fixed grammar of common analytic
phrasings (sums, filters, sorts, top-N, distinct counts) with zero latency
and zero external calls. When a question doesn't match that grammar and
OPENROUTER_API_KEY is configured, it falls back to ai_query.py, which asks
a free-tier LLM (Llama via OpenRouter) to translate the question into a
SELECT statement and runs it through the same DuckDB engine (sandboxed —
see query_runner.run_raw_sql). Without a key, unmatched questions just get
the rule-based parser's error message with example phrasings, same as
before.
"""

import uuid
from datetime import datetime
from typing import Any, Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import CurrentUser, get_db
from app.models.audit import ChatMessage, ChatRole
from app.models.file import File
from app.models.sheet import Sheet, SheetRow
from app.services import ai_query
from app.services.nlq import ParsedQuery, QueryParseError, parse_query
from app.services.query_runner import run_query, run_raw_sql

router = APIRouter(tags=["query"])


class QueryRequest(BaseModel):
    query: str


class QueryResponse(BaseModel):
    message: str
    sql: Optional[str]
    columns: list[str]
    rows: list[dict[str, Any]]


class HistoryEntry(BaseModel):
    id: uuid.UUID
    role: str
    content: str
    sql_executed: Optional[str]
    result_preview: Optional[dict]
    created_at: datetime

    model_config = {"from_attributes": True}


async def _get_file_and_sheet(file_id: uuid.UUID, sheet_id: uuid.UUID, user_id: uuid.UUID, db: AsyncSession):
    file_result = await db.execute(
        select(File).where(File.id == file_id, File.owner_id == user_id, File.deleted_at.is_(None))
    )
    db_file = file_result.scalar_one_or_none()
    if db_file is None:
        raise HTTPException(404, detail={"code": "not_found", "message": "File not found"})

    sheet_result = await db.execute(select(Sheet).where(Sheet.id == sheet_id, Sheet.file_id == file_id))
    sheet = sheet_result.scalar_one_or_none()
    if sheet is None:
        raise HTTPException(404, detail={"code": "not_found", "message": "Sheet not found"})

    return db_file, sheet


def _describe_result(parsed: ParsedQuery, result: dict) -> str:
    n = len(result["rows"])
    if parsed.select_all:
        return f"Found {n} row{'s' if n != 1 else ''}."
    if parsed.agg is None and parsed.distinct:
        return f"Found {n} unique value{'s' if n != 1 else ''} for {parsed.metric_col}."
    parts = [("count of distinct" if parsed.distinct else parsed.agg.lower())]  # type: ignore[union-attr]
    if parsed.metric_col:
        parts.append(f"of {parsed.metric_col}")
    if parsed.group_col:
        parts.append(f"grouped by {parsed.group_col}")
    return f"Computed {' '.join(parts)} — {n} row{'s' if n != 1 else ''}."


@router.post("/files/{file_id}/sheets/{sheet_id}/query", response_model=QueryResponse)
async def query_sheet(
    file_id: uuid.UUID,
    sheet_id: uuid.UUID,
    body: QueryRequest,
    user: CurrentUser,
    db: AsyncSession = Depends(get_db),
) -> QueryResponse:
    _, sheet = await _get_file_and_sheet(file_id, sheet_id, user.id, db)
    columns_meta = sheet.columns or []
    column_names = [c["name"] for c in columns_meta]

    db.add(ChatMessage(user_id=user.id, file_id=file_id, sheet_id=sheet_id, role=ChatRole.user, content=body.query))

    rows_result = await db.execute(
        select(SheetRow.data).where(SheetRow.sheet_id == sheet_id).order_by(SheetRow.row_index)
    )
    rows = [r[0] for r in rows_result.all()]

    try:
        parsed = parse_query(body.query, column_names)
        result = run_query(parsed, rows, columns_meta)
        reply = _describe_result(parsed, result)
    except QueryParseError as rule_based_error:
        if not ai_query.is_available():
            db.add(ChatMessage(
                user_id=user.id, file_id=file_id, sheet_id=sheet_id,
                role=ChatRole.assistant, content=str(rule_based_error),
            ))
            await db.commit()
            return QueryResponse(message=str(rule_based_error), sql=None, columns=[], rows=[])

        try:
            sql, ai_message = await ai_query.generate_sql(body.query, columns_meta)
            result = run_raw_sql(sql, rows, columns_meta)
            reply = ai_message
        except ai_query.AIQueryError as e:
            db.add(ChatMessage(
                user_id=user.id, file_id=file_id, sheet_id=sheet_id,
                role=ChatRole.assistant, content=str(e),
            ))
            await db.commit()
            return QueryResponse(message=str(e), sql=None, columns=[], rows=[])

    db.add(ChatMessage(
        user_id=user.id, file_id=file_id, sheet_id=sheet_id,
        role=ChatRole.assistant, content=reply,
        sql_executed=result["sql"],
        result_preview={"columns": result["columns"], "rows": result["rows"][:20]},
    ))
    await db.commit()

    return QueryResponse(message=reply, sql=result["sql"], columns=result["columns"], rows=result["rows"])


@router.get("/files/{file_id}/sheets/{sheet_id}/query/history", response_model=list[HistoryEntry])
async def query_history(
    file_id: uuid.UUID,
    sheet_id: uuid.UUID,
    user: CurrentUser,
    db: AsyncSession = Depends(get_db),
    limit: int = Query(50, ge=1, le=200),
) -> list[HistoryEntry]:
    await _get_file_and_sheet(file_id, sheet_id, user.id, db)

    result = await db.execute(
        select(ChatMessage)
        .where(ChatMessage.file_id == file_id, ChatMessage.sheet_id == sheet_id, ChatMessage.user_id == user.id)
        .order_by(ChatMessage.created_at.desc())
        .limit(limit)
    )
    messages = list(reversed(result.scalars().all()))
    return [
        HistoryEntry(
            id=m.id, role=m.role.value, content=m.content,
            sql_executed=m.sql_executed, result_preview=m.result_preview,
            created_at=m.created_at,
        )
        for m in messages
    ]
