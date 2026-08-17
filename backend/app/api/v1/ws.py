"""
Real-time sheet collaboration over WebSocket.

  WS /ws/sheets/{sheet_id}?token=<jwt>

Auth is via a query-string JWT (browsers can't set custom headers on the
WebSocket handshake). The endpoint re-validates the same access token used
for REST calls and checks the caller owns the file the sheet belongs to.

This socket is receive-light: the only inbound message type is `cursor`
(ephemeral, not persisted). Actual writes still go through the existing
REST endpoints in rows.py, which publish the resulting event on this
sheet's channel after commit — so a socket message is always the
broadcast of something that has already been durably saved.
"""

import json
import uuid

import structlog
from fastapi import APIRouter, Query, WebSocket, WebSocketDisconnect, status
from jose import JWTError
from sqlalchemy import select

from app.core.security import decode_access_token
from app.database import AsyncSessionLocal
from app.models.file import File
from app.models.sheet import Sheet
from app.models.user import User
from app.ws.manager import manager

router = APIRouter(tags=["ws"])
log = structlog.get_logger()

USER_COLORS = [
    "#ef4444", "#f97316", "#eab308", "#22c55e",
    "#06b6d4", "#3b82f6", "#8b5cf6", "#ec4899",
]


async def _authenticate(token: str) -> User | None:
    try:
        payload = decode_access_token(token)
        user_id = uuid.UUID(payload["sub"])
    except (JWTError, KeyError, ValueError):
        return None
    async with AsyncSessionLocal() as db:
        result = await db.execute(select(User).where(User.id == user_id, User.is_active == True))
        return result.scalar_one_or_none()


async def _authorize_sheet(user_id: uuid.UUID, sheet_id: uuid.UUID) -> Sheet | None:
    async with AsyncSessionLocal() as db:
        result = await db.execute(
            select(Sheet)
            .join(File, File.id == Sheet.file_id)
            .where(
                Sheet.id == sheet_id,
                File.owner_id == user_id,
                File.deleted_at.is_(None),
            )
        )
        return result.scalar_one_or_none()


@router.websocket("/ws/sheets/{sheet_id}")
async def sheet_socket(websocket: WebSocket, sheet_id: uuid.UUID, token: str = Query(...)) -> None:
    from app.config import settings

    origin = websocket.headers.get("origin")
    if origin is not None and origin != settings.FRONTEND_ORIGIN:
        await websocket.close(code=status.WS_1008_POLICY_VIOLATION)
        return

    user = await _authenticate(token)
    if user is None:
        await websocket.close(code=status.WS_1008_POLICY_VIOLATION)
        return

    sheet = await _authorize_sheet(user.id, sheet_id)
    if sheet is None:
        await websocket.close(code=status.WS_1008_POLICY_VIOLATION)
        return

    await websocket.accept()

    connection_id = uuid.uuid4()
    sheet_key = str(sheet_id)
    color = USER_COLORS[user.id.int % len(USER_COLORS)]
    user_info = {
        "connection_id": str(connection_id),
        "user_id": str(user.id),
        "email": user.email,
        "full_name": user.full_name,
        "color": color,
    }

    await manager.connect(sheet_key, connection_id, websocket, user_info)
    await websocket.send_text(json.dumps({
        "type": "presence_state",
        "users": manager.presence(sheet_key),
        "self": user_info,
    }))

    try:
        while True:
            raw = await websocket.receive_text()
            try:
                msg = json.loads(raw)
            except json.JSONDecodeError:
                continue

            if msg.get("type") == "cursor":
                await manager.publish(sheet_key, {
                    "type": "cursor",
                    "connection_id": str(connection_id),
                    "user_id": str(user.id),
                    "row": msg.get("row"),
                    "col": msg.get("col"),
                })
    except WebSocketDisconnect:
        pass
    except Exception:
        log.exception("ws_session_error", sheet_id=sheet_key)
    finally:
        left = await manager.disconnect(sheet_key, connection_id)
        if left:
            await manager.publish(sheet_key, {
                "type": "presence_leave",
                "connection_id": str(connection_id),
            })
