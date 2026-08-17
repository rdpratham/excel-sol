"""
Plain-language querying — and now editing — over a sheet's data.

  POST /files/{file_id}/sheets/{sheet_id}/query          — ask or tell the bot something
  GET  /files/{file_id}/sheets/{sheet_id}/query/history   — past Q&A for this sheet

Two-tier engine for both reads and writes: nlq.py / write_intent.py
pattern-match a fixed grammar of common phrasings ("average price by
category", "change status from Pending to Active where region is East")
with zero latency and zero external calls. When a message doesn't match
either grammar and OPENROUTER_API_KEY is configured, it falls back to
ai_query.py, which asks a free-tier LLM (via OpenRouter) to classify the
message as a read (translated to a SELECT, run through the sandboxed
DuckDB engine — see query_runner.run_raw_sql) or a write (translated to a
structured column/filters/new_value plan, re-validated against the real
schema — the model never gets to write raw mutation SQL).

Writes are never applied immediately. Every write — rule-based or
AI-classified — produces a preview ("this will change N rows...") that's
stashed server-side in Redis, keyed by (user, sheet), for a short TTL. The
user confirms by replying "yes" in the same chat, which is the only thing
that actually commits the UPDATE, writes an audit CellEdit row per changed
row, and broadcasts a `cell_edit` WS event per row so every connected
client updates live — reusing the exact same real-time path row edits from
the grid already go through. Only admins/editors may confirm a write;
viewers get a permission message instead of a silent no-op.
"""

import json
import uuid
from datetime import datetime
from typing import Any, Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import CurrentUser, get_db
from app.core.redis import redis_client
from app.models.audit import ChatMessage, ChatRole
from app.models.file import File
from app.models.sheet import CellEdit, Sheet, SheetRow
from app.models.user import User, UserRole
from app.services import ai_query
from app.services.nlq import Filter, ParsedQuery, QueryParseError, parse_query
from app.services.query_runner import run_query, run_raw_sql
from app.services.write_intent import matches_filters, parse_write_intent
from app.ws.manager import manager

router = APIRouter(tags=["query"])

MAX_WRITE_ROWS = 5000
PENDING_TTL_SECONDS = 120
UNDO_TTL_SECONDS = 600
CONFIRM_WORDS = {"yes", "y", "confirm", "confirmed", "proceed", "do it", "go ahead", "ok", "okay", "sure", "yep"}
CANCEL_WORDS = {"no", "n", "cancel", "stop", "nevermind", "never mind", "don't"}
UNDO_WORDS = {"undo", "undo that", "undo it", "revert", "revert that", "revert it"}


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


def _fmt(v: Any) -> str:
    return f'"{v}"' if isinstance(v, str) else str(v)


def _pending_key(user_id: uuid.UUID, sheet_id: uuid.UUID) -> str:
    return f"pending_write:{user_id}:{sheet_id}"


def _last_write_key(user_id: uuid.UUID, sheet_id: uuid.UUID) -> str:
    return f"last_write:{user_id}:{sheet_id}"


def _filters_to_json(filters: list[Filter]) -> list[dict]:
    return [{"column": f.column, "op": f.op, "value": f.value} for f in filters]


def _filters_from_json(raw: list[dict]) -> list[Filter]:
    return [Filter(f["column"], f["op"], f["value"]) for f in raw]


async def _log_and_respond(
    db: AsyncSession,
    user: User,
    file_id: uuid.UUID,
    sheet_id: uuid.UUID,
    reply: str,
    *,
    sql: Optional[str] = None,
    columns: Optional[list[str]] = None,
    rows: Optional[list[dict]] = None,
) -> QueryResponse:
    db.add(ChatMessage(
        user_id=user.id, file_id=file_id, sheet_id=sheet_id,
        role=ChatRole.assistant, content=reply,
        sql_executed=sql,
        result_preview={"columns": columns or [], "rows": (rows or [])[:20]} if rows is not None else None,
    ))
    await db.commit()
    return QueryResponse(message=reply, sql=sql, columns=columns or [], rows=rows or [])


async def _preview_write(
    db: AsyncSession,
    user: User,
    file_id: uuid.UUID,
    sheet_id: uuid.UUID,
    rows: list[dict],
    column: str,
    filters: list[Filter],
    new_value: Any,
    pending_key: str,
) -> QueryResponse:
    if user.role not in (UserRole.admin, UserRole.editor):
        return await _log_and_respond(
            db, user, file_id, sheet_id,
            "You don't have permission to edit this sheet — ask an editor or admin.",
        )

    matched = [r for r in rows if matches_filters(r, filters)]
    if not matched:
        return await _log_and_respond(db, user, file_id, sheet_id, "No rows match that — nothing to change.")

    if len(matched) > MAX_WRITE_ROWS:
        return await _log_and_respond(
            db, user, file_id, sheet_id,
            f"That would change {len(matched)} rows, which is more than I'll do in one go "
            f"(limit {MAX_WRITE_ROWS}). Try narrowing it down with a more specific filter.",
        )

    where_desc = " and ".join(f"{f.column} {f.op} {_fmt(f.value)}" for f in filters) if filters else "every row"
    reply = (
        f'This will set "{column}" to {_fmt(new_value)} for {len(matched)} row'
        f'{"s" if len(matched) != 1 else ""} where {where_desc}. '
        'Reply "yes" to confirm, or say something else to cancel.'
    )

    plan = {"column": column, "filters": _filters_to_json(filters), "new_value": new_value}
    await redis_client.set(pending_key, json.dumps(plan), ex=PENDING_TTL_SECONDS)
    return await _log_and_respond(db, user, file_id, sheet_id, reply)


async def _commit_write(db: AsyncSession, user: User, sheet_id: uuid.UUID, plan: dict) -> str:
    column = plan["column"]
    filters = _filters_from_json(plan["filters"])
    new_value = plan["new_value"]

    rows_result = await db.execute(
        select(SheetRow).where(SheetRow.sheet_id == sheet_id).order_by(SheetRow.row_index)
    )
    sheet_rows = rows_result.scalars().all()

    changed: list[SheetRow] = []
    undo_batch: list[dict] = []
    for sr in sheet_rows:
        if not matches_filters(sr.data, filters):
            continue
        old_value = sr.data.get(column)
        if old_value == new_value:
            continue
        new_data = dict(sr.data)
        new_data[column] = new_value
        sr.data = new_data
        sr.updated_by = user.id
        db.add(CellEdit(
            sheet_id=sheet_id, row_index=sr.row_index, col_key=column,
            old_value={"v": old_value}, new_value={"v": new_value}, user_id=user.id,
        ))
        changed.append(sr)
        undo_batch.append({"row_id": str(sr.id), "column": column, "old_value": old_value})

    if not changed:
        return "Nothing changed — those rows already have that value."

    await db.commit()
    await redis_client.set(_last_write_key(user.id, sheet_id), json.dumps(undo_batch), ex=UNDO_TTL_SECONDS)

    for sr in changed:
        await manager.publish(str(sheet_id), {
            "type": "cell_edit",
            "row_index": sr.row_index,
            "cells": [{"col_key": column, "value": new_value}],
            "user_id": str(user.id),
        })

    return (
        f'Done — updated "{column}" to {_fmt(new_value)} for {len(changed)} row{"s" if len(changed) != 1 else ""}. '
        'Reply "undo" if you want to revert this.'
    )


async def _handle_undo(db: AsyncSession, user: User, file_id: uuid.UUID, sheet_id: uuid.UUID) -> QueryResponse:
    if user.role not in (UserRole.admin, UserRole.editor):
        return await _log_and_respond(db, user, file_id, sheet_id, "You don't have permission to edit this sheet.")

    key = _last_write_key(user.id, sheet_id)
    raw = await redis_client.get(key)
    if not raw:
        return await _log_and_respond(db, user, file_id, sheet_id, "There's nothing to undo.")

    await redis_client.delete(key)
    batch = json.loads(raw)

    row_ids = [uuid.UUID(entry["row_id"]) for entry in batch]
    rows_result = await db.execute(select(SheetRow).where(SheetRow.id.in_(row_ids)))
    rows_by_id = {sr.id: sr for sr in rows_result.scalars().all()}

    reverted: list[tuple[SheetRow, str, Any]] = []
    for entry in batch:
        sr = rows_by_id.get(uuid.UUID(entry["row_id"]))
        if sr is None:
            continue
        column = entry["column"]
        old_value = entry["old_value"]
        current_value = sr.data.get(column)
        new_data = dict(sr.data)
        new_data[column] = old_value
        sr.data = new_data
        sr.updated_by = user.id
        db.add(CellEdit(
            sheet_id=sheet_id, row_index=sr.row_index, col_key=column,
            old_value={"v": current_value}, new_value={"v": old_value}, user_id=user.id,
        ))
        reverted.append((sr, column, old_value))

    if not reverted:
        return await _log_and_respond(db, user, file_id, sheet_id, "Couldn't undo — those rows no longer exist.")

    await db.commit()

    for sr, column, old_value in reverted:
        await manager.publish(str(sheet_id), {
            "type": "cell_edit",
            "row_index": sr.row_index,
            "cells": [{"col_key": column, "value": old_value}],
            "user_id": str(user.id),
        })

    column_name = reverted[0][1]
    return await _log_and_respond(
        db, user, file_id, sheet_id,
        f'Undone — reverted "{column_name}" back to its previous value for '
        f'{len(reverted)} row{"s" if len(reverted) != 1 else ""}.',
    )


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

    text = body.query.strip()
    lowered = text.lower()
    pending_key = _pending_key(user.id, sheet_id)

    # Reverting the last committed write (independent of any pending preview)
    if lowered in UNDO_WORDS:
        return await _handle_undo(db, user, file_id, sheet_id)

    # Confirming or cancelling a previously-previewed write
    if lowered in CONFIRM_WORDS:
        pending_raw = await redis_client.get(pending_key)
        if not pending_raw:
            return await _log_and_respond(
                db, user, file_id, sheet_id,
                "There's no pending change to confirm — ask me to change something first.",
            )
        if user.role not in (UserRole.admin, UserRole.editor):
            return await _log_and_respond(db, user, file_id, sheet_id, "You don't have permission to edit this sheet.")
        plan = json.loads(pending_raw)
        await redis_client.delete(pending_key)
        reply = await _commit_write(db, user, sheet_id, plan)
        return await _log_and_respond(db, user, file_id, sheet_id, reply)

    if lowered in CANCEL_WORDS:
        await redis_client.delete(pending_key)
        return await _log_and_respond(db, user, file_id, sheet_id, "Okay, cancelled.")

    # Any other message invalidates a stale pending plan
    await redis_client.delete(pending_key)

    rows_result = await db.execute(
        select(SheetRow.data).where(SheetRow.sheet_id == sheet_id).order_by(SheetRow.row_index)
    )
    rows = [r[0] for r in rows_result.all()]

    try:
        write_intent = parse_write_intent(text, column_names)
    except QueryParseError:
        write_intent = None

    if write_intent is not None:
        return await _preview_write(
            db, user, file_id, sheet_id, rows,
            write_intent.column, write_intent.filters, write_intent.new_value, pending_key,
        )

    try:
        parsed = parse_query(text, column_names)
        result = run_query(parsed, rows, columns_meta)
        reply = _describe_result(parsed, result)
        return await _log_and_respond(
            db, user, file_id, sheet_id, reply,
            sql=result["sql"], columns=result["columns"], rows=result["rows"],
        )
    except QueryParseError as rule_based_error:
        if not ai_query.is_available():
            return await _log_and_respond(db, user, file_id, sheet_id, str(rule_based_error))

        try:
            plan = await ai_query.classify(text, columns_meta)
        except ai_query.AIQueryError as e:
            return await _log_and_respond(db, user, file_id, sheet_id, str(e))

        if isinstance(plan, ai_query.AIWritePlan):
            return await _preview_write(
                db, user, file_id, sheet_id, rows,
                plan.column, plan.filters, plan.new_value, pending_key,
            )

        try:
            result = run_raw_sql(plan.sql, rows, columns_meta)
        except Exception:
            return await _log_and_respond(
                db, user, file_id, sheet_id,
                "The AI's query couldn't run against this sheet — try rephrasing.",
            )
        return await _log_and_respond(
            db, user, file_id, sheet_id, plan.message,
            sql=result["sql"], columns=result["columns"], rows=result["rows"],
        )


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
