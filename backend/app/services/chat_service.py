from sqlalchemy import select
from sqlalchemy.orm import Session, joinedload

from app.models import Channel, Message, SenderType, User


def post_user_message(db: Session, trip_id: int, user: User, text: str, source: Channel = Channel.web) -> Message:
    msg = Message(trip_id=trip_id, sender_user_id=user.id, sender_type=SenderType.user, source=source, text=text)
    db.add(msg)
    db.commit()
    msg.sender = user
    return msg


def history(db: Session, trip_id: int, before: int | None = None, limit: int = 50) -> list[Message]:
    q = select(Message).where(Message.trip_id == trip_id).options(joinedload(Message.sender))
    if before:
        q = q.where(Message.id < before)
    rows = list(db.scalars(q.order_by(Message.id.desc()).limit(limit)))
    return rows[::-1]  # oldest → newest for display
