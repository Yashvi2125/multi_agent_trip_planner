from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, joinedload

from app.core.errors import AppError, Forbidden, NotFound
from app.models import Channel, MemberRole, Trip, TripMember, User
from app.schemas.trip import TripCreate
from app.services.trip_code import make_code


def create_trip(db: Session, creator: User, data: TripCreate) -> Trip:
    for _ in range(8):  # retry on the (rare) code collision; DB UNIQUE is the real guard
        trip = Trip(code=make_code(data.destination), creator_id=creator.id, **data.model_dump())
        trip.members.append(TripMember(user_id=creator.id, role=MemberRole.creator, joined_via=Channel.web))
        db.add(trip)
        try:
            db.commit()
            return trip
        except IntegrityError:
            db.rollback()
    raise AppError("code_generation_failed", "We couldn't create a trip code. Please try again.", 503)


def get_by_code(db: Session, code: str) -> Trip:
    trip = db.scalar(select(Trip).where(Trip.code == code.strip().upper()))
    if not trip:
        raise NotFound("That trip code doesn't match any trip. Double-check it with whoever invited you.")
    return trip


def join_trip(db: Session, user: User, code: str, via: Channel = Channel.web) -> tuple[Trip, bool]:
    """Returns (trip, newly_joined). Joining twice is harmless."""
    trip = get_by_code(db, code)
    if is_member(db, trip.id, user.id):
        return trip, False
    db.add(TripMember(trip_id=trip.id, user_id=user.id, joined_via=via))
    try:
        db.commit()
    except IntegrityError:  # two joins racing each other
        db.rollback()
        return trip, False
    return trip, True


def is_member(db: Session, trip_id: int, user_id: int) -> bool:
    return db.scalar(
        select(TripMember.id).where(TripMember.trip_id == trip_id, TripMember.user_id == user_id)
    ) is not None


def get_trip_for_member(db: Session, trip_id: int, user: User) -> Trip:
    trip = db.scalar(
        select(Trip).where(Trip.id == trip_id)
        .options(joinedload(Trip.members).joinedload(TripMember.user))
    )
    if not trip:
        raise NotFound("We couldn't find that trip.")
    if not any(m.user_id == user.id for m in trip.members):
        raise Forbidden()
    return trip


def list_user_trips(db: Session, user: User) -> list[Trip]:
    return list(db.scalars(
        select(Trip).join(TripMember, TripMember.trip_id == Trip.id)
        .where(TripMember.user_id == user.id).order_by(Trip.created_at.desc())
    ))


def member_counts(db: Session, trip_ids: list[int]) -> dict[int, int]:
    if not trip_ids:
        return {}
    rows = db.execute(
        select(TripMember.trip_id, func.count()).where(TripMember.trip_id.in_(trip_ids)).group_by(TripMember.trip_id)
    )
    return {tid: n for tid, n in rows}
