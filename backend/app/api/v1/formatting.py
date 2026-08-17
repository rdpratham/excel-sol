"""
Excel-ribbon-style formatting: column number format/alignment, per-cell
style overrides (bold/italic/colors/alignment), and column insert/delete.

Column-level format/align lives on sheet.columns (cheap — one JSON field
covers an entire column regardless of row count). Per-cell overrides live
in the sparse sheet.cell_styles map, keyed "{row_index}:{col_key}", so
formatting a handful of cells doesn't touch the other thousands of rows.
"""

import uuid
from typing import Any, Optional

import sqlalchemy as sa
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import CurrentUser, get_db
from app.models.file import File
from app.models.sheet import Sheet
from app.ws.manager import manager

router = APIRouter(tags=["formatting"])

ALLOWED_NUMBER_FORMATS = {"general", "number", "currency", "percent"}
ALLOWED_ALIGN = {"left", "center", "right"}


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


# ── PATCH .../columns/{col_key}/format ────────────────────────────────────────


class ColumnFormatRequest(BaseModel):
    number_format: Optional[str] = None
    align: Optional[str] = None


@router.patch("/files/{file_id}/sheets/{sheet_id}/columns/{col_key}/format")
async def update_column_format(
    file_id: uuid.UUID,
    sheet_id: uuid.UUID,
    col_key: str,
    body: ColumnFormatRequest,
    user: CurrentUser,
    db: AsyncSession = Depends(get_db),
) -> dict:
    if body.number_format is not None and body.number_format not in ALLOWED_NUMBER_FORMATS:
        raise HTTPException(400, detail={"code": "invalid_format", "message": f"number_format must be one of {sorted(ALLOWED_NUMBER_FORMATS)}"})
    if body.align is not None and body.align not in ALLOWED_ALIGN:
        raise HTTPException(400, detail={"code": "invalid_align", "message": f"align must be one of {sorted(ALLOWED_ALIGN)}"})

    _, sheet = await _get_file_and_sheet(file_id, sheet_id, user.id, db)
    columns = [dict(c) for c in (sheet.columns or [])]
    idx = next((i for i, c in enumerate(columns) if c["name"] == col_key), None)
    if idx is None:
        raise HTTPException(404, detail={"code": "not_found", "message": f'Column "{col_key}" not found'})

    if body.number_format is not None:
        columns[idx]["format"] = body.number_format
    if body.align is not None:
        columns[idx]["align"] = body.align

    await db.execute(update(Sheet).where(Sheet.id == sheet_id).values(columns=columns))
    await db.commit()

    await manager.publish(str(sheet_id), {
        "type": "column_format", "col_key": col_key,
        "format": columns[idx].get("format"), "align": columns[idx].get("align"),
        "user_id": str(user.id),
    })
    return {"columns": columns}


# ── PATCH .../cell-style ───────────────────────────────────────────────────────


class CellRef(BaseModel):
    row_index: int
    col_key: str


class CellStyleUpdate(BaseModel):
    bold: Optional[bool] = None
    italic: Optional[bool] = None
    font_color: Optional[str] = None
    bg_color: Optional[str] = None
    align: Optional[str] = None


class CellStyleRequest(BaseModel):
    cells: list[CellRef]
    style: CellStyleUpdate


@router.patch("/files/{file_id}/sheets/{sheet_id}/cell-style")
async def update_cell_style(
    file_id: uuid.UUID,
    sheet_id: uuid.UUID,
    body: CellStyleRequest,
    user: CurrentUser,
    db: AsyncSession = Depends(get_db),
) -> dict:
    if body.style.align is not None and body.style.align not in ALLOWED_ALIGN:
        raise HTTPException(400, detail={"code": "invalid_align", "message": f"align must be one of {sorted(ALLOWED_ALIGN)}"})
    if len(body.cells) > 5000:
        raise HTTPException(400, detail={"code": "too_many_cells", "message": "Select 5000 cells or fewer at a time"})

    _, sheet = await _get_file_and_sheet(file_id, sheet_id, user.id, db)
    styles: dict[str, dict[str, Any]] = dict(sheet.cell_styles or {})
    patch = body.style.model_dump(exclude_unset=True)

    for ref in body.cells:
        key = f"{ref.row_index}:{ref.col_key}"
        merged = dict(styles.get(key, {}))
        for k, v in patch.items():
            if v is None:
                merged.pop(k, None)
            else:
                merged[k] = v
        if merged:
            styles[key] = merged
        else:
            styles.pop(key, None)

    await db.execute(update(Sheet).where(Sheet.id == sheet_id).values(cell_styles=styles))
    await db.commit()

    await manager.publish(str(sheet_id), {
        "type": "cell_style",
        "cells": [ref.model_dump() for ref in body.cells],
        "style": patch,
        "user_id": str(user.id),
    })
    return {"cell_styles": styles}


# ── POST .../columns (insert) ─────────────────────────────────────────────────


class AddColumnRequest(BaseModel):
    name: str
    dtype: str = "text"
    position: Optional[int] = None


@router.post("/files/{file_id}/sheets/{sheet_id}/columns", status_code=201)
async def add_column(
    file_id: uuid.UUID,
    sheet_id: uuid.UUID,
    body: AddColumnRequest,
    user: CurrentUser,
    db: AsyncSession = Depends(get_db),
) -> dict:
    name = body.name.strip()
    if not name:
        raise HTTPException(400, detail={"code": "invalid_name", "message": "Column name is required"})

    _, sheet = await _get_file_and_sheet(file_id, sheet_id, user.id, db)
    columns = [dict(c) for c in (sheet.columns or [])]
    if any(c["name"] == name for c in columns):
        raise HTTPException(409, detail={"code": "duplicate_column", "message": f'Column "{name}" already exists'})

    position = len(columns) if body.position is None else max(0, min(body.position, len(columns)))
    columns.insert(position, {"name": name, "dtype": body.dtype, "index": position, "width": 150})
    for i, c in enumerate(columns):
        c["index"] = i

    await db.execute(update(Sheet).where(Sheet.id == sheet_id).values(columns=columns, col_count=len(columns)))
    await db.commit()

    await manager.publish(str(sheet_id), {"type": "columns_changed", "columns": columns, "user_id": str(user.id)})
    return {"columns": columns}


# ── DELETE .../columns/{col_key} ──────────────────────────────────────────────


@router.delete("/files/{file_id}/sheets/{sheet_id}/columns/{col_key}")
async def delete_column(
    file_id: uuid.UUID,
    sheet_id: uuid.UUID,
    col_key: str,
    user: CurrentUser,
    db: AsyncSession = Depends(get_db),
) -> dict:
    _, sheet = await _get_file_and_sheet(file_id, sheet_id, user.id, db)
    columns = [dict(c) for c in (sheet.columns or [])]
    if not any(c["name"] == col_key for c in columns):
        raise HTTPException(404, detail={"code": "not_found", "message": f'Column "{col_key}" not found'})

    columns = [c for c in columns if c["name"] != col_key]
    for i, c in enumerate(columns):
        c["index"] = i

    cell_styles = {k: v for k, v in (sheet.cell_styles or {}).items() if not k.endswith(f":{col_key}")}

    # Strip the key from every row's JSONB in one statement rather than a Python loop.
    await db.execute(
        sa.text("UPDATE sheet_rows SET data = data - :col_key::text WHERE sheet_id = :sheet_id"),
        {"col_key": col_key, "sheet_id": str(sheet_id)},
    )
    await db.execute(
        update(Sheet).where(Sheet.id == sheet_id).values(columns=columns, col_count=len(columns), cell_styles=cell_styles)
    )
    await db.commit()

    await manager.publish(str(sheet_id), {"type": "columns_changed", "columns": columns, "user_id": str(user.id)})
    return {"columns": columns}
