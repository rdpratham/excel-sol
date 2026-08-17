from fastapi import APIRouter

from app.api.v1 import admin, auth, files, formatting, query, rows, sheets, stats

router = APIRouter()
router.include_router(auth.router)
router.include_router(admin.router)
router.include_router(files.router)
router.include_router(sheets.router)
router.include_router(rows.router)
router.include_router(formatting.router)
router.include_router(query.router)
router.include_router(stats.router)
