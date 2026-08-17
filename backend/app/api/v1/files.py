import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from fastapi import APIRouter, HTTPException, Query, UploadFile, status
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.orm import selectinload

from app.api.deps import CurrentUser, get_db
from app.config import settings
from app.models.file import File, FileStatus
from app.models.sheet import Sheet
from app.services.file_processor import SUPPORTED_EXTENSIONS, process_file

from fastapi import Depends
from sqlalchemy.ext.asyncio import AsyncSession

router = APIRouter(prefix="/files", tags=["files"])

ALLOWED_MIME = {
    "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    "application/vnd.ms-excel.sheet.macroEnabled.12",
    "text/csv",
    "application/csv",
    "text/plain",
    "application/octet-stream",
}

# ── Response schemas ──────────────────────────────────────────────────────────

class SheetOut(BaseModel):
    id: uuid.UUID
    file_id: uuid.UUID
    name: str
    sheet_index: int
    row_count: int
    col_count: int
    columns: list
    created_at: datetime

    model_config = {"from_attributes": True}


class FileOut(BaseModel):
    id: uuid.UUID
    owner_id: uuid.UUID
    original_filename: str
    display_name: str
    size_bytes: int
    mime_type: str
    status: FileStatus
    error_message: Optional[str]
    sheet_count: int
    total_rows: int
    created_at: datetime
    updated_at: datetime
    sheets: list[SheetOut]

    model_config = {"from_attributes": True}


# ── Endpoints ─────────────────────────────────────────────────────────────────

@router.post("/upload", response_model=FileOut, status_code=status.HTTP_201_CREATED)
async def upload_file(
    file: UploadFile,
    user: CurrentUser,
    db: AsyncSession = Depends(get_db),
) -> File:
    # ── Validate extension ────────────────────────────────────────────────────
    filename = file.filename or "upload"
    ext = Path(filename).suffix.lower()
    if ext not in SUPPORTED_EXTENSIONS:
        raise HTTPException(
            status_code=status.HTTP_415_UNSUPPORTED_MEDIA_TYPE,
            detail={
                "code": "unsupported_file_type",
                "message": f"Supported types: .xlsx, .xlsm, .csv — got {ext!r}",
            },
        )

    # ── Read + validate size ──────────────────────────────────────────────────
    content = await file.read()
    max_bytes = settings.MAX_UPLOAD_MB * 1024 * 1024
    if len(content) > max_bytes:
        raise HTTPException(
            status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
            detail={
                "code": "file_too_large",
                "message": f"Maximum file size is {settings.MAX_UPLOAD_MB} MB",
            },
        )

    # ── Create file record ────────────────────────────────────────────────────
    db_file = File(
        owner_id=user.id,
        original_filename=filename,
        display_name=Path(filename).stem,
        size_bytes=len(content),
        mime_type=file.content_type or "application/octet-stream",
        status=FileStatus.uploading,
        storage_key="",
    )
    db.add(db_file)
    await db.commit()
    await db.refresh(db_file)

    # ── Process (parse + insert sheets/rows) ──────────────────────────────────
    db_file = await process_file(content, filename, db_file, db)

    if db_file.status == FileStatus.failed:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail={
                "code": "processing_failed",
                "message": db_file.error_message or "File could not be processed",
            },
        )

    return db_file


@router.get("", response_model=list[FileOut])
async def list_files(
    user: CurrentUser,
    db: AsyncSession = Depends(get_db),
) -> list[File]:
    result = await db.execute(
        select(File)
        .where(File.owner_id == user.id, File.deleted_at.is_(None))
        .options(selectinload(File.sheets))
        .order_by(File.created_at.desc())
    )
    return list(result.scalars().all())


@router.get("/{file_id}", response_model=FileOut)
async def get_file(
    file_id: uuid.UUID,
    user: CurrentUser,
    db: AsyncSession = Depends(get_db),
) -> File:
    result = await db.execute(
        select(File)
        .where(File.id == file_id, File.owner_id == user.id, File.deleted_at.is_(None))
        .options(selectinload(File.sheets))
    )
    f = result.scalar_one_or_none()
    if f is None:
        raise HTTPException(status_code=404, detail={"code": "not_found", "message": "File not found"})
    return f


@router.delete("/{file_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_file(
    file_id: uuid.UUID,
    user: CurrentUser,
    db: AsyncSession = Depends(get_db),
) -> None:
    result = await db.execute(
        select(File).where(File.id == file_id, File.owner_id == user.id, File.deleted_at.is_(None))
    )
    f = result.scalar_one_or_none()
    if f is None:
        raise HTTPException(status_code=404, detail={"code": "not_found", "message": "File not found"})
    f.deleted_at = datetime.now(timezone.utc)
    await db.commit()
