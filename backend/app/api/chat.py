from fastapi import APIRouter, BackgroundTasks, Depends, Query
from sqlalchemy.orm import Session

from app.api.deps import current_user
from app.core.database import get_db
from app.core.rate_limit import rate_limit
from app.models import Channel, User
from app.schemas.trip import MessageIn, MessageOut
from app.services import chat_service, planner_gateway, trip_service
from app.services.event_hub import hub

router = APIRouter(prefix="/api/trips/{trip_id}/messages", tags=["chat"])


@router.get("", response_model=list[MessageOut])
def list_messages(
    trip_id: int, before: int | None = None, limit: int = Query(50, ge=1, le=100),
    user: User = Depends(current_user), db: Session = Depends(get_db),
):
    trip_service.get_trip_for_member(db, trip_id, user)
    return chat_service.history(db, trip_id, before, limit)


@router.post("", response_model=MessageOut, status_code=202, dependencies=[Depends(rate_limit(30, 60))])
def send_message(
    trip_id: int, body: MessageIn, bg: BackgroundTasks,
    user: User = Depends(current_user), db: Session = Depends(get_db),
):
    trip_service.get_trip_for_member(db, trip_id, user)
    msg = chat_service.post_user_message(db, trip_id, user, body.text, Channel.web)
    out = MessageOut.model_validate(msg)
    hub.publish_threadsafe(trip_id, {"type": "message.new", "data": out.model_dump(mode="json")})
    bg.add_task(planner_gateway.planner.handle, trip_id, msg.id)  # AI work never blocks the request
    return out
