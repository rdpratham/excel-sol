import asyncio
import json
import uuid
from typing import Any

import structlog
from fastapi import WebSocket

from app.core.redis import redis_client

log = structlog.get_logger()


class ConnectionManager:
    """Tracks live WebSocket connections per sheet and relays messages via Redis pub/sub.

    Publishing through Redis (instead of just iterating local sockets) means
    an edit made via a REST request lands on every connected client without
    the request handler needing any reference to the in-memory socket pool,
    and it keeps this correct if the API is ever scaled beyond one instance.
    Presence itself is tracked in-process only — Render's free tier runs a
    single worker, so this is exact for the current deployment; a multi-
    instance setup would need presence moved into Redis too.
    """

    def __init__(self) -> None:
        self._rooms: dict[str, dict[uuid.UUID, dict[str, Any]]] = {}
        self._pubsub_tasks: dict[str, asyncio.Task] = {}

    @staticmethod
    def _channel(sheet_id: str) -> str:
        return f"sheet:{sheet_id}"

    async def connect(
        self, sheet_id: str, connection_id: uuid.UUID, ws: WebSocket, user_info: dict
    ) -> None:
        room = self._rooms.setdefault(sheet_id, {})
        room[connection_id] = {"ws": ws, "user": user_info}

        if sheet_id not in self._pubsub_tasks:
            self._pubsub_tasks[sheet_id] = asyncio.create_task(self._listen(sheet_id))

        await self.publish(sheet_id, {"type": "presence_join", "user": user_info})

    async def disconnect(self, sheet_id: str, connection_id: uuid.UUID) -> dict | None:
        room = self._rooms.get(sheet_id)
        if not room or connection_id not in room:
            return None

        info = room.pop(connection_id)
        if not room:
            self._rooms.pop(sheet_id, None)
            task = self._pubsub_tasks.pop(sheet_id, None)
            if task:
                task.cancel()
        return info["user"]

    def presence(self, sheet_id: str) -> list[dict]:
        room = self._rooms.get(sheet_id, {})
        return [c["user"] for c in room.values()]

    async def publish(self, sheet_id: str, message: dict) -> None:
        try:
            await redis_client.publish(self._channel(sheet_id), json.dumps(message))
        except Exception:
            log.exception("ws_publish_failed", sheet_id=sheet_id)

    async def _listen(self, sheet_id: str) -> None:
        pubsub = redis_client.pubsub()
        channel = self._channel(sheet_id)
        try:
            await pubsub.subscribe(channel)
            async for message in pubsub.listen():
                if message.get("type") != "message":
                    continue
                room = self._rooms.get(sheet_id)
                if not room:
                    continue
                data = message["data"]
                dead: list[uuid.UUID] = []
                for conn_id, info in room.items():
                    try:
                        await info["ws"].send_text(data)
                    except Exception:
                        dead.append(conn_id)
                for conn_id in dead:
                    room.pop(conn_id, None)
        except asyncio.CancelledError:
            pass
        except Exception:
            log.exception("ws_listen_failed", sheet_id=sheet_id)
        finally:
            try:
                await pubsub.unsubscribe(channel)
                await pubsub.close()
            except Exception:
                pass


manager = ConnectionManager()
