import uuid

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import CurrentUser, get_db
from app.models.file import File, FileStatus
from app.models.sheet import Sheet, SheetRow

router = APIRouter(tags=["sheets"])


@router.get("/files/{file_id}/sheets/{sheet_id}/rows")
async def get_rows(
    file_id: uuid.UUID,
    sheet_id: uuid.UUID,
    user: CurrentUser,
    db: AsyncSession = Depends(get_db),
    page: int = Query(1, ge=1),
    page_size: int = Query(100, ge=1, le=1000),
) -> dict:
    # Verify file ownership
    file_result = await db.execute(
        select(File).where(
            File.id == file_id,
            File.owner_id == user.id,
            File.deleted_at.is_(None),
        )
    )
    db_file = file_result.scalar_one_or_none()
    if db_file is None:
        raise HTTPException(status_code=404, detail={"code": "not_found", "message": "File not found"})

    # Verify sheet belongs to file
    sheet_result = await db.execute(
        select(Sheet).where(Sheet.id == sheet_id, Sheet.file_id == file_id)
    )
    sheet = sheet_result.scalar_one_or_none()
    if sheet is None:
        raise HTTPException(status_code=404, detail={"code": "not_found", "message": "Sheet not found"})

    offset = (page - 1) * page_size
    rows_result = await db.execute(
        select(SheetRow)
        .where(SheetRow.sheet_id == sheet_id)
        .order_by(SheetRow.row_index)
        .offset(offset)
        .limit(page_size)
    )
    rows = rows_result.scalars().all()

    return {
        "columns": sheet.columns or [],
        "rows": [r.data for r in rows],
        "total": sheet.row_count,
        "page": page,
        "page_size": page_size,
        "total_pages": max(1, -(-sheet.row_count // page_size)),  # ceiling division
    }
