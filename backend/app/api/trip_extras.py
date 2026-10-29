"""Trip settings, weather, checklist and conflict voting: the pieces the web UI needs beyond chat + plan."""
from dataclasses import asdict

from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.agents.research import research, resolve_destination
from app.api.deps import current_user
from app.api.trips import _out
from app.core.database import get_db
from app.core.errors import AppError, Forbidden, NotFound
from app.models import ChecklistItem, Channel, Message, MemberRole, SenderType, User, Vote
from app.schemas.planning import (ChecklistIn, ChecklistOut, ChecklistPatch, ConflictOut, TripUpdate, VoteIn)
from app.schemas.trip import MessageOut, TripOut
from app.services import checklist_service, conflict_votes, planner_gateway, trip_service
from app.services.event_hub import hub
from app.tools.base import ToolError
from app.tools.curated import Destination

router = APIRouter(prefix="/api/trips/{trip_id}", tags=["trip"])


@router.patch("", response_model=TripOut)
def update_trip(trip_id: int, body: TripUpdate, user: User = Depends(current_user), db: Session = Depends(get_db)):
    trip = trip_service.get_trip_for_member(db, trip_id, user)
    me = next(m for m in trip.members if m.user_id == user.id)
    if me.role is not MemberRole.creator:
        raise Forbidden("Only the person who created the trip can change these details.")
    changes = body.model_dump(exclude_unset=True)
    start, end = changes.get("start_date", trip.start_date), changes.get("end_date", trip.end_date)
    if start and end and end < start:
        raise AppError("invalid_input", "The trip can't end before it starts.", 422)
    if "destination" in changes and trip.current_itinerary_version:
        raise AppError("destination_locked", "The destination can't change once a plan exists. "
                       "Start a new trip for a different place.", 409)
    for k, v in changes.items():
        if v is not None or k in ("start_date", "end_date", "group_budget"):
            setattr(trip, k, v)
    note = None
    if changes:
        what = ", ".join(k.replace("_", " ") for k in changes)
        note = Message(trip_id=trip.id, sender_type=SenderType.system, source=Channel.system,
                       text=f"{user.name} updated the trip ({what})."
                            + (" Say “@planner update the plan” to refresh the itinerary."
                               if trip.current_itinerary_version else ""))
        db.add(note)
    db.commit()
    hub.publish_threadsafe(trip.id, {"type": "trip.updated", "data": {"id": trip.id, "fields": list(changes)}})
    if note:
        hub.publish_threadsafe(trip.id, {"type": "message.new",
                                         "data": MessageOut.model_validate(note).model_dump(mode="json")})
    return _out(trip)


@router.get("/weather")
def weather(trip_id: int, user: User = Depends(current_user), db: Session = Depends(get_db)):
    trip = trip_service.get_trip_for_member(db, trip_id, user)
    deps = getattr(planner_gateway.planner, "deps", None)
    if deps is None:
        from app.graph.deps import default_deps
        deps = default_deps()
    dest = resolve_destination(trip.destination, getattr(deps, "dynamic", None))
    if dest is None and deps.geocoder is not None:   # a forecast only needs coordinates, not a full research run
        try:
            pt = deps.geocoder.geocode(trip.destination)
        except ToolError:
            pt = None
        if pt is not None:
            dest = Destination.stub(pt.label.split(",")[0].strip() or trip.destination, pt.lat, pt.lon)
    b = research(trip.destination, trip.start_date, trip.end_date, deps.weather, None, deps.today(), resolved=dest)
    return {"supported": b.supported, "source": b.weather_source, "notes": b.notes,
            "days": [{"date": d.day.isoformat(), "summary": d.summary, "temp_max": d.temp_max,
                      "temp_min": d.temp_min, "rain_chance": d.rain_chance} for d in b.weather]}


@router.get("/checklist", response_model=list[ChecklistOut])
def checklist(trip_id: int, user: User = Depends(current_user), db: Session = Depends(get_db)):
    trip = trip_service.get_trip_for_member(db, trip_id, user)
    return checklist_service.ensure_checklist(db, trip)


@router.post("/checklist", response_model=ChecklistOut, status_code=201)
def add_checklist_item(trip_id: int, body: ChecklistIn, user: User = Depends(current_user), db: Session = Depends(get_db)):
    trip = trip_service.get_trip_for_member(db, trip_id, user)
    checklist_service.ensure_checklist(db, trip)
    row = ChecklistItem(trip_id=trip_id, label=body.label.strip(), category=body.category)
    db.add(row)
    db.commit()
    hub.publish_threadsafe(trip_id, {"type": "checklist.updated", "data": {"id": row.id}})
    return row


@router.patch("/checklist/{item_id}", response_model=ChecklistOut)
def toggle_checklist(trip_id: int, item_id: int, body: ChecklistPatch, user: User = Depends(current_user),
                     db: Session = Depends(get_db)):
    trip_service.get_trip_for_member(db, trip_id, user)
    row = db.get(ChecklistItem, item_id)
    if not row or row.trip_id != trip_id:
        raise NotFound("We couldn't find that checklist item.")
    row.done, row.done_by = body.done, (user.id if body.done else None)
    db.commit()
    hub.publish_threadsafe(trip_id, {"type": "checklist.updated", "data": {"id": row.id, "done": row.done}})
    return row


@router.post("/conflicts/{conflict_id}/vote", response_model=ConflictOut)
def vote(trip_id: int, conflict_id: int, body: VoteIn, user: User = Depends(current_user), db: Session = Depends(get_db)):
    trip_service.get_trip_for_member(db, trip_id, user)
    conflict, t = conflict_votes.cast_vote(db, trip_id, conflict_id, user, Vote(body.vote))
    out = ConflictOut.model_validate(conflict)
    out.accept_votes, out.reject_votes, out.my_vote = t["accept"], t["reject"], body.vote
    return out
