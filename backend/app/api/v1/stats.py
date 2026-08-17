from fastapi import APIRouter, Depends
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.api.deps import CurrentUser, get_db
from app.models.file import File, FileStatus
from app.models.sheet import Sheet

router = APIRouter(tags=["stats"])


@router.get("/stats")
async def get_stats(
    user: CurrentUser,
    db: AsyncSession = Depends(get_db),
) -> dict:
    # Aggregate counts for all ready files owned by this user
    agg = await db.execute(
        select(
            func.count(File.id).label("total_files"),
            func.coalesce(func.sum(File.sheet_count), 0).label("total_sheets"),
            func.coalesce(func.sum(File.total_rows), 0).label("total_rows"),
            func.coalesce(func.sum(File.size_bytes), 0).label("storage_bytes"),
        ).where(
            File.owner_id == user.id,
            File.deleted_at.is_(None),
            File.status == FileStatus.ready,
        )
    )
    row = agg.one()

    # 5 most-recently uploaded files (any status except deleted)
    recent_result = await db.execute(
        select(File)
        .where(File.owner_id == user.id, File.deleted_at.is_(None))
        .options(selectinload(File.sheets))
        .order_by(File.created_at.desc())
        .limit(5)
    )
    recent_files = list(recent_result.scalars().all())

    return {
        "total_files": row.total_files,
        "total_sheets": int(row.total_sheets),
        "total_rows": int(row.total_rows),
        "storage_bytes": int(row.storage_bytes),
        "ai_queries_this_month": 0,
        "recent_files": [_file_to_dict(f) for f in recent_files],
    }


def _file_to_dict(f: File) -> dict:
    return {
        "id": str(f.id),
        "owner_id": str(f.owner_id),
        "original_filename": f.original_filename,
        "display_name": f.display_name,
        "size_bytes": f.size_bytes,
        "mime_type": f.mime_type,
        "status": f.status.value,
        "error_message": f.error_message,
        "sheet_count": f.sheet_count,
        "total_rows": f.total_rows,
        "created_at": f.created_at.isoformat(),
        "updated_at": f.updated_at.isoformat(),
        "sheets": [
            {
                "id": str(s.id),
                "file_id": str(s.file_id),
                "name": s.name,
                "sheet_index": s.sheet_index,
                "row_count": s.row_count,
                "col_count": s.col_count,
                "columns": s.columns or [],
                "created_at": s.created_at.isoformat(),
            }
            for s in (f.sheets or [])
        ],
    }
