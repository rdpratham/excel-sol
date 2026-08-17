from fastapi import APIRouter

from app.api.v1 import admin, auth, files, rows, sheets, stats

router = APIRouter()
router.include_router(auth.router)
router.include_router(admin.router)
router.include_router(files.router)
router.include_router(sheets.router)
router.include_router(rows.router)
router.include_router(stats.router)
