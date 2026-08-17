"""
Row-level CRUD and xlsx export for a sheet.

Endpoints:
  PATCH  /files/{file_id}/sheets/{sheet_id}/rows/{row_index}  — edit cells
  POST   /files/{file_id}/sheets/{sheet_id}/rows              — append row
  DELETE /files/{file_id}/sheets/{sheet_id}/rows              — delete rows
  GET    /files/{file_id}/sheets/{sheet_id}/export            — download xlsx
"""

import io
import uuid
from typing import Any

import openpyxl
from fastapi import APIRouter, Depends, HTTPException, Query, status
from fastapi.responses import StreamingResponse
from pydantic import BaseModel
from sqlalchemy import delete, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import CurrentUser, get_db
from app.models.file import File, FileStatus
from app.models.sheet import CellEdit, Sheet, SheetRow
from app.ws.manager import manager

router = APIRouter(tags=["rows"])

# ── helpers ───────────────────────────────────────────────────────────────────


async def _get_file_and_sheet(
    file_id: uuid.UUID,
    sheet_id: uuid.UUID,
    user_id: uuid.UUID,
    db: AsyncSession,
) -> tuple[File, Sheet]:
    file_result = await db.execute(
        select(File).where(
            File.id == file_id,
            File.owner_id == user_id,
            File.deleted_at.is_(None),
        )
    )
    db_file = file_result.scalar_one_or_none()
    if db_file is None:
        raise HTTPException(404, detail={"code": "not_found", "message": "File not found"})

    sheet_result = await db.execute(
        select(Sheet).where(Sheet.id == sheet_id, Sheet.file_id == file_id)
    )
    sheet = sheet_result.scalar_one_or_none()
    if sheet is None:
        raise HTTPException(404, detail={"code": "not_found", "message": "Sheet not found"})

    return db_file, sheet


# ── PATCH /files/{file_id}/sheets/{sheet_id}/rows/{row_index} ─────────────────


class CellUpdate(BaseModel):
    col_key: str
    value: Any


class RowPatchRequest(BaseModel):
    cells: list[CellUpdate]


@router.patch("/files/{file_id}/sheets/{sheet_id}/rows/{row_index}", status_code=200)
async def patch_row(
    file_id: uuid.UUID,
    sheet_id: uuid.UUID,
    row_index: int,
    body: RowPatchRequest,
    user: CurrentUser,
    db: AsyncSession = Depends(get_db),
) -> dict:
    _, sheet = await _get_file_and_sheet(file_id, sheet_id, user.id, db)

    row_result = await db.execute(
        select(SheetRow).where(SheetRow.sheet_id == sheet_id, SheetRow.row_index == row_index)
    )
    row = row_result.scalar_one_or_none()
    if row is None:
        raise HTTPException(404, detail={"code": "not_found", "message": "Row not found"})

    old_data = dict(row.data)
    new_data = dict(row.data)

    audit_entries = []
    for cell in body.cells:
        old_val = old_data.get(cell.col_key)
        new_data[cell.col_key] = cell.value
        audit_entries.append(
            CellEdit(
                sheet_id=sheet_id,
                row_index=row_index,
                col_key=cell.col_key,
                old_value={"v": old_val},
                new_value={"v": cell.value},
                user_id=user.id,
            )
        )

    await db.execute(
        update(SheetRow).where(SheetRow.id == row.id).values(data=new_data)
    )
    db.add_all(audit_entries)
    await db.commit()

    await manager.publish(str(sheet_id), {
        "type": "cell_edit",
        "row_index": row_index,
        "cells": [{"col_key": c.col_key, "value": c.value} for c in body.cells],
        "user_id": str(user.id),
    })

    return {"row_index": row_index, "data": new_data}


# ── POST /files/{file_id}/sheets/{sheet_id}/rows ──────────────────────────────


class AppendRowRequest(BaseModel):
    data: dict[str, Any] = {}


@router.post("/files/{file_id}/sheets/{sheet_id}/rows", status_code=201)
async def append_row(
    file_id: uuid.UUID,
    sheet_id: uuid.UUID,
    body: AppendRowRequest,
    user: CurrentUser,
    db: AsyncSession = Depends(get_db),
) -> dict:
    _, sheet = await _get_file_and_sheet(file_id, sheet_id, user.id, db)

    new_index = sheet.row_count
    new_row = SheetRow(sheet_id=sheet_id, row_index=new_index, data=body.data)
    db.add(new_row)

    await db.execute(
        update(Sheet).where(Sheet.id == sheet_id).values(row_count=Sheet.row_count + 1)
    )
    await db.execute(
        update(File).where(File.id == file_id).values(total_rows=File.total_rows + 1)
    )
    await db.commit()

    await manager.publish(str(sheet_id), {
        "type": "row_added",
        "row_index": new_index,
        "data": body.data,
        "user_id": str(user.id),
    })

    return {"row_index": new_index, "data": body.data}


# ── DELETE /files/{file_id}/sheets/{sheet_id}/rows ────────────────────────────


class DeleteRowsRequest(BaseModel):
    row_indexes: list[int]


@router.delete("/files/{file_id}/sheets/{sheet_id}/rows", status_code=200)
async def delete_rows(
    file_id: uuid.UUID,
    sheet_id: uuid.UUID,
    body: DeleteRowsRequest,
    user: CurrentUser,
    db: AsyncSession = Depends(get_db),
) -> dict:
    _, sheet = await _get_file_and_sheet(file_id, sheet_id, user.id, db)

    to_delete = set(body.row_indexes)
    await db.execute(
        delete(SheetRow).where(
            SheetRow.sheet_id == sheet_id,
            SheetRow.row_index.in_(list(to_delete)),
        )
    )

    # Re-index remaining rows to fill gaps
    remaining_result = await db.execute(
        select(SheetRow)
        .where(SheetRow.sheet_id == sheet_id)
        .order_by(SheetRow.row_index)
    )
    remaining = remaining_result.scalars().all()
    for new_idx, row in enumerate(remaining):
        if row.row_index != new_idx:
            await db.execute(
                update(SheetRow).where(SheetRow.id == row.id).values(row_index=new_idx)
            )

    new_count = len(remaining)
    delta = sheet.row_count - new_count
    await db.execute(update(Sheet).where(Sheet.id == sheet_id).values(row_count=new_count))
    await db.execute(
        update(File).where(File.id == file_id).values(total_rows=File.total_rows - delta)
    )
    await db.commit()

    await manager.publish(str(sheet_id), {
        "type": "rows_deleted",
        "row_indexes": sorted(to_delete),
        "remaining": new_count,
        "user_id": str(user.id),
    })

    return {"deleted": len(to_delete), "remaining": new_count}


# ── GET /files/{file_id}/sheets/{sheet_id}/export ────────────────────────────


@router.get("/files/{file_id}/sheets/{sheet_id}/export")
async def export_sheet(
    file_id: uuid.UUID,
    sheet_id: uuid.UUID,
    user: CurrentUser,
    db: AsyncSession = Depends(get_db),
) -> StreamingResponse:
    db_file, sheet = await _get_file_and_sheet(file_id, sheet_id, user.id, db)

    rows_result = await db.execute(
        select(SheetRow)
        .where(SheetRow.sheet_id == sheet_id)
        .order_by(SheetRow.row_index)
    )
    rows = rows_result.scalars().all()

    columns = sheet.columns or []
    col_names = [c["name"] for c in columns]

    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = sheet.name[:31]  # Excel sheet name limit

    # Header row
    ws.append(col_names)

    # Data rows
    for row in rows:
        ws.append([row.data.get(c) for c in col_names])

    buf = io.BytesIO()
    wb.save(buf)
    buf.seek(0)

    safe_name = db_file.display_name.replace(" ", "_")
    filename = f"{safe_name}_{sheet.name}.xlsx"

    return StreamingResponse(
        buf,
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )
