from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import ChecklistItem, Trip
from app.tools.curated import find_destination

GENERIC = [("Government photo ID for every traveller", "document"), ("Book accommodation", "booking"),
           ("Book travel to the destination", "booking"), ("Download offline maps", "packing")]


def ensure_checklist(db: Session, trip: Trip) -> list[ChecklistItem]:
    """First read seeds the list from the destination's curated template (or a generic one)."""
    rows = list(db.scalars(select(ChecklistItem).where(ChecklistItem.trip_id == trip.id).order_by(ChecklistItem.id)))
    if rows:
        return rows
    dest = find_destination(trip.destination)
    seed = [(c.label, c.category) for c in dest.checklist] if dest else GENERIC
    rows = [ChecklistItem(trip_id=trip.id, label=l, category=c) for l, c in seed]
    db.add_all(rows)
    db.commit()
    return rows
