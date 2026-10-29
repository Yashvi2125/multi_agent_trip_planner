from fastapi import APIRouter, BackgroundTasks, Depends
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.deps import current_user
from app.core.database import get_db
from app.core.errors import NotFound
from app.core.rate_limit import rate_limit
from app.models import Channel, Conflict, Constraint, Preference, TripMember, User
from app.schemas.planning import (ConflictOut, ConstraintOut, ExplainIn, ItineraryOut, PreferenceOut,
                                  PreferencesOut, VersionOut)
from app.schemas.trip import MessageOut
from app.services import chat_service, conflict_votes, itinerary_service, planner_gateway, trip_service
from app.services.event_hub import hub

router = APIRouter(prefix="/api/trips/{trip_id}", tags=["planning"])

NO_PLAN = "There's no itinerary yet. Tell the group what kind of trip you want, and the planner will build the first version."


@router.get("/itinerary", response_model=ItineraryOut)
def get_itinerary(trip_id: int, version: int | None = None, user: User = Depends(current_user),
                  db: Session = Depends(get_db)):
    trip_service.get_trip_for_member(db, trip_id, user)
    row = itinerary_service.get_version(db, trip_id, version) if version else itinerary_service.latest(db, trip_id)
    if not row:
        raise NotFound(NO_PLAN if not version else f"Version {version} doesn't exist for this trip.")
    return ItineraryOut(version=row.version, change_summary=row.change_summary, created_at=row.created_at,
                        itinerary=itinerary_service.itinerary_of(row), budget=row.budget_breakdown)


@router.get("/itinerary/versions", response_model=list[VersionOut])
def versions(trip_id: int, user: User = Depends(current_user), db: Session = Depends(get_db)):
    trip_service.get_trip_for_member(db, trip_id, user)
    return itinerary_service.list_versions(db, trip_id)


@router.get("/budget")
def budget(trip_id: int, user: User = Depends(current_user), db: Session = Depends(get_db)):
    trip_service.get_trip_for_member(db, trip_id, user)
    row = itinerary_service.latest(db, trip_id)
    if not row or not row.budget_breakdown:
        raise NotFound("There's no budget estimate yet. It appears once the first plan is built.")
    return {"version": row.version, **row.budget_breakdown}


@router.get("/conflicts", response_model=list[ConflictOut])
def conflicts(trip_id: int, user: User = Depends(current_user), db: Session = Depends(get_db)):
    trip_service.get_trip_for_member(db, trip_id, user)
    rows = list(db.scalars(select(Conflict).where(Conflict.trip_id == trip_id).order_by(Conflict.id.desc())))
    t = conflict_votes.tallies(db, [c.id for c in rows], user.id)
    out = []
    for c in rows:
        o = ConflictOut.model_validate(c)
        o.accept_votes, o.reject_votes, o.my_vote = t[c.id]["accept"], t[c.id]["reject"], t[c.id]["mine"]
        out.append(o)
    return out


@router.get("/preferences", response_model=PreferencesOut)
def preferences(trip_id: int, user: User = Depends(current_user), db: Session = Depends(get_db)):
    trip_service.get_trip_for_member(db, trip_id, user)
    names = {m.user_id: m.user.name for m in db.scalars(select(TripMember).where(TripMember.trip_id == trip_id))}
    prefs = db.scalars(select(Preference).where(Preference.trip_id == trip_id, Preference.active.is_(True)))
    cons = db.scalars(select(Constraint).where(Constraint.trip_id == trip_id, Constraint.active.is_(True)))
    return PreferencesOut(
        preferences=[PreferenceOut(user_id=p.user_id, user_name=names.get(p.user_id, "?"), category=p.category,
                                   value=p.value, weight=p.weight) for p in prefs],
        constraints=[ConstraintOut(user_id=c.user_id, user_name=names.get(c.user_id) if c.user_id else None,
                                   type=c.type.value, value=c.value) for c in cons])


def _post_and_run(db, bg, trip_id, user, text, command) -> MessageOut:
    """Triggers go through the normal chat path so the whole group sees who asked for what."""
    msg = chat_service.post_user_message(db, trip_id, user, text, Channel.web)
    out = MessageOut.model_validate(msg)
    hub.publish_threadsafe(trip_id, {"type": "message.new", "data": out.model_dump(mode="json")})
    bg.add_task(planner_gateway.planner.handle, trip_id, msg.id, command)
    return out


@router.post("/regenerate", response_model=MessageOut, status_code=202, dependencies=[Depends(rate_limit(10, 60))])
def regenerate(trip_id: int, bg: BackgroundTasks, user: User = Depends(current_user), db: Session = Depends(get_db)):
    trip_service.get_trip_for_member(db, trip_id, user)
    return _post_and_run(db, bg, trip_id, user, "Please update the plan.", "regenerate")


@router.post("/explain", response_model=MessageOut, status_code=202, dependencies=[Depends(rate_limit(20, 60))])
def explain(trip_id: int, body: ExplainIn, bg: BackgroundTasks, user: User = Depends(current_user),
            db: Session = Depends(get_db)):
    trip_service.get_trip_for_member(db, trip_id, user)
    return _post_and_run(db, bg, trip_id, user, body.question, "explain")
