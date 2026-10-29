from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import Conflict, ConflictStatus, Constraint, ConstraintType, Preference, Trip, TripMember
from app.services.budget_calc import effective_cap


@dataclass
class GroupProfile:
    members: dict[int, str]
    interests: dict[int, dict[str, int]] = field(default_factory=dict)  # user → topic → weight
    dislikes: dict[int, dict[str, int]] = field(default_factory=dict)
    avoids: set[str] = field(default_factory=set)                       # hard "no" topics
    unavailable: dict[date, list[int]] = field(default_factory=dict)
    cap: Decimal | None = None
    limited_topics: set[str] = field(default_factory=set)               # open clashes: at most one slot
    dietary: list[str] = field(default_factory=list)
    must_include: list[str] = field(default_factory=list)

    @property
    def travelers(self) -> int:
        return max(len(self.members), 1)


def load_profile(db: Session, trip: Trip) -> GroupProfile:
    members = {m.user_id: m.user.name for m in db.scalars(select(TripMember).where(TripMember.trip_id == trip.id))}
    p = GroupProfile(members=members)
    for pref in db.scalars(select(Preference).where(Preference.trip_id == trip.id, Preference.active.is_(True))):
        bucket = p.interests if pref.category == "interest" else p.dislikes if pref.category == "dislike" else None
        if bucket is not None:
            bucket.setdefault(pref.user_id, {})[pref.value] = pref.weight
    caps: list[Decimal] = []
    for c in db.scalars(select(Constraint).where(Constraint.trip_id == trip.id, Constraint.active.is_(True))):
        if c.type is ConstraintType.must_avoid:
            p.avoids.add(c.value["text"])
        elif c.type is ConstraintType.unavailable_day and c.user_id:
            for d in c.value["dates"]:
                p.unavailable.setdefault(date.fromisoformat(d), []).append(c.user_id)
        elif c.type is ConstraintType.max_budget and c.user_id:
            caps.append(Decimal(c.value["amount"]))
        elif c.type is ConstraintType.must_include:
            p.must_include.append(c.value["text"])
        elif c.type is ConstraintType.dietary:
            p.dietary.append(c.value["text"])
    p.cap = effective_cap(trip.group_budget, caps, p.travelers)
    for c in db.scalars(select(Conflict).where(Conflict.trip_id == trip.id, Conflict.status == ConflictStatus.open,
                                                Conflict.kind == "topic_clash")):
        p.limited_topics.add(c.key.split(":", 1)[1])
    return p
