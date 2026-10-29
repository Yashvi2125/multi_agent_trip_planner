from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.api.deps import current_user
from app.core.database import get_db
from app.models import Channel, Message, SenderType, User
from app.schemas.trip import JoinIn, MemberOut, MessageOut, TripCreate, TripDetail, TripOut
from app.services import trip_service
from app.services.event_hub import hub

router = APIRouter(prefix="/api/trips", tags=["trips"])


def _out(trip, count: int | None = None) -> TripOut:
    out = TripOut.model_validate(trip)
    out.member_count = count if count is not None else len(trip.members)
    return out


@router.post("", response_model=TripOut, status_code=201)
def create_trip(body: TripCreate, user: User = Depends(current_user), db: Session = Depends(get_db)):
    return _out(trip_service.create_trip(db, user, body))


@router.post("/join", response_model=TripOut)
def join_trip(body: JoinIn, user: User = Depends(current_user), db: Session = Depends(get_db)):
    trip, joined = trip_service.join_trip(db, user, body.code, Channel.web)
    if joined:
        note = Message(trip_id=trip.id, sender_type=SenderType.system, source=Channel.system,
                       text=f"{user.name} joined the trip.")
        db.add(note)
        db.commit()
        hub.publish_threadsafe(trip.id, {"type": "member.joined", "data": {"user_id": user.id, "name": user.name}})
        hub.publish_threadsafe(trip.id, {"type": "message.new",
                                         "data": MessageOut.model_validate(note).model_dump(mode="json")})
    return _out(trip, len(trip.members))


@router.get("", response_model=list[TripOut])
def my_trips(user: User = Depends(current_user), db: Session = Depends(get_db)):
    trips = trip_service.list_user_trips(db, user)
    counts = trip_service.member_counts(db, [t.id for t in trips])
    return [_out(t, counts.get(t.id, 0)) for t in trips]


@router.get("/{trip_id}", response_model=TripDetail)
def get_trip(trip_id: int, user: User = Depends(current_user), db: Session = Depends(get_db)):
    trip = trip_service.get_trip_for_member(db, trip_id, user)
    detail = TripDetail.model_validate(trip)
    detail.member_count = len(trip.members)
    detail.telegram_connected = trip.telegram_chat_id is not None
    return detail


@router.get("/{trip_id}/members", response_model=list[MemberOut])
def members(trip_id: int, user: User = Depends(current_user), db: Session = Depends(get_db)):
    return trip_service.get_trip_for_member(db, trip_id, user).members
