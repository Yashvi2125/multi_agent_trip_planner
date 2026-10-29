from fastapi import APIRouter, WebSocket, WebSocketDisconnect

from app.core import database
from app.core.security import decode_access_token
from app.models import User
from app.services import trip_service
from app.services.event_hub import hub

router = APIRouter()


@router.websocket("/ws/trips/{trip_id}")
async def trip_socket(ws: WebSocket, trip_id: int, token: str = ""):
    user_id = decode_access_token(token)
    allowed = False
    if user_id:
        with database.SessionLocal() as db:
            allowed = db.get(User, user_id) is not None and trip_service.is_member(db, trip_id, user_id)
    if not allowed:
        await ws.close(code=4401)
        return
    await ws.accept()
    await hub.connect(trip_id, ws)
    # Only now is this socket guaranteed to receive events. Clients wait for "ready" and then refetch recent
    # messages, so nothing published during connect/reconnect is lost.
    await ws.send_json({"type": "ready", "data": {}})
    try:
        while True:
            await ws.receive_text()  # clients only listen; sends go through REST so they're validated + persisted
    except WebSocketDisconnect:
        pass
    finally:
        hub.disconnect(trip_id, ws)
