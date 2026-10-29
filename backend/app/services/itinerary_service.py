from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import ItineraryVersion, Trip, TripStatus
from app.schemas.itinerary import Itinerary


def latest(db: Session, trip_id: int) -> ItineraryVersion | None:
    return db.scalar(select(ItineraryVersion).where(ItineraryVersion.trip_id == trip_id)
                     .order_by(ItineraryVersion.version.desc()).limit(1))


def get_version(db: Session, trip_id: int, version: int) -> ItineraryVersion | None:
    return db.scalar(select(ItineraryVersion).where(ItineraryVersion.trip_id == trip_id,
                                                    ItineraryVersion.version == version))


def list_versions(db: Session, trip_id: int) -> list[ItineraryVersion]:
    return list(db.scalars(select(ItineraryVersion).where(ItineraryVersion.trip_id == trip_id)
                           .order_by(ItineraryVersion.version)))


def _place_days(it: Itinerary | None) -> dict[str, tuple[int, str]]:
    return {i.place_id: (d.index, i.name) for d in (it.days if it else []) for i in d.items}


def diff_summary(old: Itinerary | None, new: Itinerary) -> str:
    """Deterministic, human-readable description of what changed. Powers 'why was this moved?'."""
    if old is None:
        return "First version of the plan."
    a, b = _place_days(old), _place_days(new)
    added = [b[k][1] for k in b if k not in a]
    removed = [a[k][1] for k in a if k not in b]
    moved = [f"{b[k][1]} from Day {a[k][0]} to Day {b[k][0]}" for k in b if k in a and a[k][0] != b[k][0]]
    parts = []
    if added:
        parts.append("Added " + ", ".join(added))
    if removed:
        parts.append("Removed " + ", ".join(removed))
    if moved:
        parts.append("Moved " + "; ".join(moved))
    if old.stay and new.stay and old.stay.tier != new.stay.tier:
        parts.append(f"Switched stays from {old.stay.tier} to {new.stay.tier}")
    return ". ".join(parts) + "." if parts else "Timings adjusted; the same places are included."


def save_version(db: Session, trip: Trip, it: Itinerary, budget: dict, change_summary: str,
                 action_id: int | None) -> ItineraryVersion:
    version = trip.current_itinerary_version + 1
    row = ItineraryVersion(trip_id=trip.id, version=version, created_by_action_id=action_id,
                           days=it.model_dump(mode="json"), budget_breakdown=budget, change_summary=change_summary)
    db.add(row)
    trip.current_itinerary_version = version
    trip.status = TripStatus.planned
    db.commit()
    return row


def itinerary_of(row: ItineraryVersion | None) -> Itinerary | None:
    """`days` column stores the whole Itinerary document (days + stay + tiers) as JSON."""
    return Itinerary.model_validate(row.days) if row else None
