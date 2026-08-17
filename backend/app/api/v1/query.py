"""
Plain-language querying — and now editing — over a sheet's data.

  POST /files/{file_id}/sheets/{sheet_id}/query          — ask or tell the bot something
  GET  /files/{file_id}/sheets/{sheet_id}/query/history   — past Q&A for this sheet

Two-tier engine covering five kinds of request: read, write (set a literal
or a relative increase/decrease), reorder (group rows by a column's
values), delete, and add_row. nlq.py / write_intent.py pattern-match a
fixed grammar of common phrasings for read/write/delete with zero latency
and zero external calls. Anything that doesn't match — including reorder
and add_row, which are inherently too free-form for a fixed grammar — goes
to ai_query.classify() when OPENROUTER_API_KEY is configured: the LLM
decides which of the five intents the message is and returns one
structured plan (never raw mutation SQL) — a read gets a sandboxed SELECT
(see query_runner.run_raw_sql); the other four get column/filter/value-
shaped plans that this module re-validates against the sheet's real schema
before ever touching data. Because the LLM is choosing the intent itself
on every unmatched message, adding a genuinely new capability later means
adding one more intent branch here and one more prompt section in
ai_query.py — the model doesn't need retraining or a new regex family for
every new phrasing of something already-supported.

Every one of the four mutating kinds is previewed, never applied
immediately: a plan is stashed server-side in Redis, keyed by (user,
sheet), for a short TTL, and only committed when the user replies "yes" in
the same chat. Commits write an audit CellEdit row per changed cell (or an
equivalent snapshot for row add/delete/reorder) and broadcast a WS event
so every connected client updates live — reusing the exact real-time path
manual grid edits already go through, so no new frontend UI was needed.
Every commit is undoable with a plain "undo" reply for a few minutes
afterward. Only admins/editors may confirm a write or undo one; viewers
get a permission message instead of a silent no-op.
"""

import json
import uuid
from datetime import datetime
from typing import Any, Optional

import structlog
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
from app.services.write_intent import apply_op, matches_filters, parse_delete_intent, parse_write_intent
from app.ws.manager import manager

router = APIRouter(tags=["query"])
log = structlog.get_logger()

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


def _describe_op(column: str, op: str, value: Any, *, past: bool = False) -> str:
    verbs = {
        "increase_by": "increase", "decrease_by": "decrease",
        "increase_by_percent": "increase", "decrease_by_percent": "decrease",
        "set": "set",
    }
    verb = verbs.get(op, "set")
    if past:
        verb = {"increase": "increased", "decrease": "decreased", "set": "set"}[verb]

    if op == "increase_by" or op == "decrease_by":
        return f'{verb} "{column}" by {_fmt(value)}'
    if op == "increase_by_percent" or op == "decrease_by_percent":
        return f'{verb} "{column}" by {value}%'
    return f'{verb} "{column}" to {_fmt(value)}'


async def _preview_write(
    db: AsyncSession,
    user: User,
    file_id: uuid.UUID,
    sheet_id: uuid.UUID,
    rows: list[dict],
    column: str,
    filters: list[Filter],
    value: Any,
    op: str,
    pending_key: str,
) -> QueryResponse:
    if user.role not in (UserRole.admin, UserRole.editor):
        return await _log_and_respond(
            db, user, file_id, sheet_id,
            "You don't have permission to edit this sheet — ask an editor or admin.",
        )

    matched = [r for r in rows if matches_filters(r, filters)]
    if op != "set":
        matched = [r for r in matched if apply_op(r.get(column), op, value) is not None]

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
        f'This will {_describe_op(column, op, value)} for {len(matched)} row'
        f'{"s" if len(matched) != 1 else ""} where {where_desc}. '
        'Reply "yes" to confirm, or say something else to cancel.'
    )

    plan = {"kind": "write", "column": column, "filters": _filters_to_json(filters), "value": value, "op": op}
    await redis_client.set(pending_key, json.dumps(plan), ex=PENDING_TTL_SECONDS)
    return await _log_and_respond(db, user, file_id, sheet_id, reply)


async def _preview_reorder(
    db: AsyncSession,
    user: User,
    file_id: uuid.UUID,
    sheet_id: uuid.UUID,
    total_rows: int,
    column: str,
    priority_values: list[str],
    pending_key: str,
) -> QueryResponse:
    if user.role not in (UserRole.admin, UserRole.editor):
        return await _log_and_respond(
            db, user, file_id, sheet_id,
            "You don't have permission to edit this sheet — ask an editor or admin.",
        )

    if total_rows > MAX_WRITE_ROWS:
        return await _log_and_respond(
            db, user, file_id, sheet_id,
            f"This sheet has {total_rows} rows, which is more than I'll reorder in one go "
            f"(limit {MAX_WRITE_ROWS}).",
        )

    groups_desc = ", then ".join(f'"{v}"' for v in priority_values)
    reply = (
        f'This will move rows where "{column}" is {groups_desc} to the top (in that order), '
        "keeping everyone else in their current relative order below. "
        'Reply "yes" to confirm, or say something else to cancel.'
    )

    plan = {"kind": "reorder", "column": column, "priority_values": priority_values}
    await redis_client.set(pending_key, json.dumps(plan), ex=PENDING_TTL_SECONDS)
    return await _log_and_respond(db, user, file_id, sheet_id, reply)


def _reorder_rank(value: Any, priority_lookup: dict[str, int], fallback: int) -> int:
    key = str(value).strip().lower() if value is not None else ""
    return priority_lookup.get(key, fallback)


async def _commit_reorder(db: AsyncSession, user: User, sheet_id: uuid.UUID, plan: dict) -> str:
    column = plan["column"]
    priority_values: list[str] = plan["priority_values"]
    priority_lookup = {v.strip().lower(): i for i, v in enumerate(priority_values)}
    fallback_rank = len(priority_values)

    rows_result = await db.execute(
        select(SheetRow).where(SheetRow.sheet_id == sheet_id).order_by(SheetRow.row_index)
    )
    sheet_rows = rows_result.scalars().all()

    original_order = [str(sr.id) for sr in sheet_rows]
    reordered = sorted(
        sheet_rows,
        key=lambda sr: _reorder_rank(sr.data.get(column), priority_lookup, fallback_rank),
    )

    changed = 0
    for new_index, sr in enumerate(reordered):
        if sr.row_index != new_index:
            sr.row_index = new_index
            changed += 1

    if not changed:
        return "The rows are already in that order — nothing to change."

    await db.commit()
    await redis_client.set(
        _last_write_key(user.id, sheet_id),
        json.dumps({"kind": "reorder", "order": original_order}),
        ex=UNDO_TTL_SECONDS,
    )

    await manager.publish(str(sheet_id), {"type": "rows_reordered", "user_id": str(user.id)})

    groups_desc = ", then ".join(f'"{v}"' for v in priority_values)
    return (
        f'Done — moved rows where "{column}" is {groups_desc} to the top. '
        'Reply "undo" if you want to revert this.'
    )


async def _commit_write(db: AsyncSession, user: User, sheet_id: uuid.UUID, plan: dict) -> str:
    column = plan["column"]
    filters = _filters_from_json(plan["filters"])
    value = plan["value"]
    op = plan.get("op", "set")

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
        new_value = apply_op(old_value, op, value)
        if new_value is None or old_value == new_value:
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
    await redis_client.set(
        _last_write_key(user.id, sheet_id),
        json.dumps({"kind": "write", "entries": undo_batch}),
        ex=UNDO_TTL_SECONDS,
    )

    for sr in changed:
        await manager.publish(str(sheet_id), {
            "type": "cell_edit",
            "row_index": sr.row_index,
            "cells": [{"col_key": column, "value": sr.data.get(column)}],
            "user_id": str(user.id),
        })

    return (
        f'Done — {_describe_op(column, op, value, past=True)} '
        f'for {len(changed)} row{"s" if len(changed) != 1 else ""}. Reply "undo" if you want to revert this.'
    )


async def _preview_delete(
    db: AsyncSession,
    user: User,
    file_id: uuid.UUID,
    sheet_id: uuid.UUID,
    rows: list[dict],
    filters: list[Filter],
    pending_key: str,
) -> QueryResponse:
    if user.role not in (UserRole.admin, UserRole.editor):
        return await _log_and_respond(
            db, user, file_id, sheet_id,
            "You don't have permission to edit this sheet — ask an editor or admin.",
        )

    matched = [r for r in rows if matches_filters(r, filters)]
    if not matched:
        return await _log_and_respond(db, user, file_id, sheet_id, "No rows match that — nothing to delete.")

    if len(matched) > MAX_WRITE_ROWS:
        return await _log_and_respond(
            db, user, file_id, sheet_id,
            f"That would delete {len(matched)} rows, which is more than I'll do in one go "
            f"(limit {MAX_WRITE_ROWS}). Try narrowing it down with a more specific filter.",
        )

    where_desc = " and ".join(f"{f.column} {f.op} {_fmt(f.value)}" for f in filters)
    reply = (
        f'This will delete {len(matched)} row{"s" if len(matched) != 1 else ""} where {where_desc}. '
        'Reply "yes" to confirm, or say something else to cancel.'
    )

    plan = {"kind": "delete", "filters": _filters_to_json(filters)}
    await redis_client.set(pending_key, json.dumps(plan), ex=PENDING_TTL_SECONDS)
    return await _log_and_respond(db, user, file_id, sheet_id, reply)


async def _commit_delete(db: AsyncSession, user: User, sheet_id: uuid.UUID, plan: dict) -> str:
    filters = _filters_from_json(plan["filters"])

    rows_result = await db.execute(
        select(SheetRow).where(SheetRow.sheet_id == sheet_id).order_by(SheetRow.row_index)
    )
    sheet_rows = rows_result.scalars().all()

    to_delete = [sr for sr in sheet_rows if matches_filters(sr.data, filters)]
    if not to_delete:
        return "Nothing to delete — no matching rows found."

    deleted_snapshot = [{"row_index": sr.row_index, "data": sr.data} for sr in to_delete]
    delete_ids = {sr.id for sr in to_delete}
    remaining = [sr for sr in sheet_rows if sr.id not in delete_ids]

    for new_idx, sr in enumerate(remaining):
        if sr.row_index != new_idx:
            sr.row_index = new_idx
    for sr in to_delete:
        await db.delete(sr)

    sheet = await db.get(Sheet, sheet_id)
    sheet.row_count = len(remaining)
    db_file = (await db.execute(select(File).where(File.id == sheet.file_id))).scalar_one()
    db_file.total_rows = db_file.total_rows - len(to_delete)

    await db.commit()
    await redis_client.set(
        _last_write_key(user.id, sheet_id),
        json.dumps({"kind": "delete", "rows": deleted_snapshot}),
        ex=UNDO_TTL_SECONDS,
    )

    await manager.publish(str(sheet_id), {
        "type": "rows_deleted",
        "row_indexes": [d["row_index"] for d in deleted_snapshot],
        "remaining": len(remaining),
        "user_id": str(user.id),
    })

    return (
        f'Done — deleted {len(to_delete)} row{"s" if len(to_delete) != 1 else ""}. '
        'Reply "undo" if you want to restore them.'
    )


async def _preview_add_row(
    db: AsyncSession,
    user: User,
    file_id: uuid.UUID,
    sheet_id: uuid.UUID,
    data: dict[str, Any],
    pending_key: str,
) -> QueryResponse:
    if user.role not in (UserRole.admin, UserRole.editor):
        return await _log_and_respond(
            db, user, file_id, sheet_id,
            "You don't have permission to edit this sheet — ask an editor or admin.",
        )

    if not data:
        return await _log_and_respond(db, user, file_id, sheet_id, "I didn't catch any values for the new row.")

    desc = ", ".join(f"{k} = {_fmt(v)}" for k, v in data.items())
    reply = f'This will add a new row with {desc}. Reply "yes" to confirm, or say something else to cancel.'

    plan = {"kind": "add_row", "data": data}
    await redis_client.set(pending_key, json.dumps(plan), ex=PENDING_TTL_SECONDS)
    return await _log_and_respond(db, user, file_id, sheet_id, reply)


async def _commit_add_row(db: AsyncSession, user: User, sheet_id: uuid.UUID, plan: dict) -> str:
    data = plan["data"]

    sheet = await db.get(Sheet, sheet_id)
    new_index = sheet.row_count
    new_row = SheetRow(sheet_id=sheet_id, row_index=new_index, data=data)
    db.add(new_row)
    sheet.row_count = new_index + 1
    db_file = (await db.execute(select(File).where(File.id == sheet.file_id))).scalar_one()
    db_file.total_rows = db_file.total_rows + 1

    await db.flush()
    await redis_client.set(
        _last_write_key(user.id, sheet_id),
        json.dumps({"kind": "add_row", "row_id": str(new_row.id)}),
        ex=UNDO_TTL_SECONDS,
    )
    await db.commit()

    await manager.publish(str(sheet_id), {
        "type": "row_added", "row_index": new_index, "data": data, "user_id": str(user.id),
    })

    return 'Done — added a new row. Reply "undo" if you want to remove it.'


COMMIT_HANDLERS = {
    "write": _commit_write,
    "reorder": _commit_reorder,
    "delete": _commit_delete,
    "add_row": _commit_add_row,
}


async def _undo_write(db: AsyncSession, user: User, sheet_id: uuid.UUID, batch: dict) -> str:
    entries = batch["entries"]
    row_ids = [uuid.UUID(entry["row_id"]) for entry in entries]
    rows_result = await db.execute(select(SheetRow).where(SheetRow.id.in_(row_ids)))
    rows_by_id = {sr.id: sr for sr in rows_result.scalars().all()}

    reverted: list[tuple[SheetRow, str, Any]] = []
    for entry in entries:
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
        return "Couldn't undo — those rows no longer exist."

    await db.commit()
    for sr, column, old_value in reverted:
        await manager.publish(str(sheet_id), {
            "type": "cell_edit",
            "row_index": sr.row_index,
            "cells": [{"col_key": column, "value": old_value}],
            "user_id": str(user.id),
        })

    column_name = reverted[0][1]
    return (
        f'Undone — reverted "{column_name}" back to its previous value for '
        f'{len(reverted)} row{"s" if len(reverted) != 1 else ""}.'
    )


async def _undo_reorder(db: AsyncSession, user: User, sheet_id: uuid.UUID, batch: dict) -> str:
    order: list[str] = batch["order"]
    rows_result = await db.execute(select(SheetRow).where(SheetRow.sheet_id == sheet_id))
    rows_by_id = {str(sr.id): sr for sr in rows_result.scalars().all()}

    changed = 0
    for new_index, row_id in enumerate(order):
        sr = rows_by_id.get(row_id)
        if sr is not None and sr.row_index != new_index:
            sr.row_index = new_index
            changed += 1

    if not changed:
        return "Couldn't undo — the rows have already changed since then."

    await db.commit()
    await manager.publish(str(sheet_id), {"type": "rows_reordered", "user_id": str(user.id)})
    return "Undone — restored the previous row order."


async def _undo_delete(db: AsyncSession, user: User, sheet_id: uuid.UUID, batch: dict) -> str:
    entries = batch["rows"]

    rows_result = await db.execute(
        select(SheetRow).where(SheetRow.sheet_id == sheet_id).order_by(SheetRow.row_index)
    )
    next_index = len(rows_result.scalars().all())

    for entry in entries:
        db.add(SheetRow(sheet_id=sheet_id, row_index=next_index, data=entry["data"]))
        next_index += 1

    sheet = await db.get(Sheet, sheet_id)
    sheet.row_count = next_index
    db_file = (await db.execute(select(File).where(File.id == sheet.file_id))).scalar_one()
    db_file.total_rows = db_file.total_rows + len(entries)

    await db.commit()
    await manager.publish(str(sheet_id), {"type": "row_added", "row_index": next_index - 1, "user_id": str(user.id)})

    return (
        f'Restored {len(entries)} deleted row{"s" if len(entries) != 1 else ""} '
        "(added back at the end of the sheet)."
    )


async def _undo_add_row(db: AsyncSession, user: User, sheet_id: uuid.UUID, batch: dict) -> str:
    row = await db.get(SheetRow, uuid.UUID(batch["row_id"]))
    if row is None:
        return "Couldn't undo — that row no longer exists."

    await db.delete(row)

    rows_result = await db.execute(
        select(SheetRow).where(SheetRow.sheet_id == sheet_id).order_by(SheetRow.row_index)
    )
    remaining = rows_result.scalars().all()
    for new_idx, sr in enumerate(remaining):
        if sr.row_index != new_idx:
            sr.row_index = new_idx

    sheet = await db.get(Sheet, sheet_id)
    sheet.row_count = len(remaining)
    db_file = (await db.execute(select(File).where(File.id == sheet.file_id))).scalar_one()
    db_file.total_rows = db_file.total_rows - 1

    await db.commit()
    await manager.publish(str(sheet_id), {
        "type": "rows_deleted", "row_indexes": [], "remaining": len(remaining), "user_id": str(user.id),
    })

    return "Undone — removed the row I added."


UNDO_HANDLERS = {
    "write": _undo_write,
    "reorder": _undo_reorder,
    "delete": _undo_delete,
    "add_row": _undo_add_row,
}


async def _handle_undo(db: AsyncSession, user: User, file_id: uuid.UUID, sheet_id: uuid.UUID) -> QueryResponse:
    if user.role not in (UserRole.admin, UserRole.editor):
        return await _log_and_respond(db, user, file_id, sheet_id, "You don't have permission to edit this sheet.")

    key = _last_write_key(user.id, sheet_id)
    raw = await redis_client.get(key)
    if not raw:
        return await _log_and_respond(db, user, file_id, sheet_id, "There's nothing to undo.")

    await redis_client.delete(key)
    batch = json.loads(raw)
    handler = UNDO_HANDLERS.get(batch.get("kind", "write"))
    if handler is None:
        return await _log_and_respond(db, user, file_id, sheet_id, "There's nothing to undo.")

    reply = await handler(db, user, sheet_id, batch)
    return await _log_and_respond(db, user, file_id, sheet_id, reply)


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
        handler = COMMIT_HANDLERS.get(plan.get("kind", "write"))
        reply = await handler(db, user, sheet_id, plan) if handler else "Something went wrong — try again."
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
            write_intent.column, write_intent.filters, write_intent.value, write_intent.op, pending_key,
        )

    try:
        delete_intent = parse_delete_intent(text, column_names)
    except QueryParseError:
        delete_intent = None

    if delete_intent is not None:
        return await _preview_delete(db, user, file_id, sheet_id, rows, delete_intent.filters, pending_key)

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
                plan.column, plan.filters, plan.value, plan.op, pending_key,
            )

        if isinstance(plan, ai_query.AIReorderPlan):
            return await _preview_reorder(
                db, user, file_id, sheet_id, len(rows),
                plan.column, plan.priority_values, pending_key,
            )

        if isinstance(plan, ai_query.AIDeletePlan):
            return await _preview_delete(db, user, file_id, sheet_id, rows, plan.filters, pending_key)

        if isinstance(plan, ai_query.AIAddRowPlan):
            return await _preview_add_row(db, user, file_id, sheet_id, plan.data, pending_key)

        try:
            result = run_raw_sql(plan.sql, rows, columns_meta)
        except Exception as e:
            log.warning("ai_read_sql_failed", sql=plan.sql, error=str(e))
            return await _log_and_respond(
                db, user, file_id, sheet_id,
                "The AI's query couldn't run against this sheet — try rephrasing, "
                "or be more specific about which column and rows you mean.",
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
