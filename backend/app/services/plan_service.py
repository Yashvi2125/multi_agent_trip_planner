from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import ChecklistItem, ItineraryVersion, Trip, TripStatus
from app.tools.curated import Destination


def latest_versions(db: Session, trip_id: int, n: int = 2) -> list[ItineraryVersion]:
    return list(db.scalars(select(ItineraryVersion).where(ItineraryVersion.trip_id == trip_id)
                           .order_by(ItineraryVersion.version.desc()).limit(n)))


def save_version(db: Session, trip: Trip, itinerary: dict, budget: dict, meta: dict,
                 change_summary: str, action_id: int | None, dest: Destination | None) -> int:
    version = trip.current_itinerary_version + 1
    db.add(ItineraryVersion(trip_id=trip.id, version=version, created_by_action_id=action_id,
                            days=itinerary["days"], budget_breakdown=budget, meta={**meta, "stay": itinerary.get("stay"),
                            "food_tier": itinerary.get("food_tier")}, change_summary=change_summary))
    trip.current_itinerary_version = version
    trip.status = TripStatus.planned
    if dest and not db.scalar(select(ChecklistItem.id).where(ChecklistItem.trip_id == trip.id)):
        for c in dest.checklist:  # seeded once, from the destination's template
            db.add(ChecklistItem(trip_id=trip.id, label=c.label, category=c.category))
    db.commit()
    return version
