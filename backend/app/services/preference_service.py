from dataclasses import dataclass, field

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import Constraint, ConstraintType, Preference, Trip
from app.schemas.agents import ExtractedConstraint, ExtractionResult
from app.services.topics import normalize_topic

OPPOSITE = {"interest": "dislike", "dislike": "interest"}


@dataclass
class ApplyOutcome:
    added_preferences: list[str] = field(default_factory=list)
    added_constraints: list[str] = field(default_factory=list)
    changed_mind: list[str] = field(default_factory=list)
    new_constraints: list[ExtractedConstraint] = field(default_factory=list)

    @property
    def empty(self) -> bool:
        return not (self.added_preferences or self.added_constraints)


def _constraint_value(c: ExtractedConstraint) -> dict:
    if c.type == "max_budget":
        return {"amount": str(c.amount)}
    if c.type == "unavailable_day":
        return {"dates": [d.isoformat() for d in c.dates]}
    if c.type == "must_avoid":
        return {"text": normalize_topic(c.text or "")}
    if c.type == "must_include":
        return {"text": (c.text or "").strip().lower()}   # keep place names intact ("dudhsagar")
    return {"text": (c.text or "").strip()}


def apply_extraction(db: Session, trip: Trip, user_id: int, message_id: int | None,
                     result: ExtractionResult) -> ApplyOutcome:
    out = ApplyOutcome()
    active = list(db.scalars(select(Preference).where(
        Preference.trip_id == trip.id, Preference.user_id == user_id, Preference.active.is_(True))))

    for p in result.preferences:
        topic = normalize_topic(p.topic)
        if any(a.category == p.category and a.value == topic for a in active):
            continue  # already known
        if p.category in OPPOSITE:  # a member changing their mind replaces their earlier stance
            for a in active:
                if a.category == OPPOSITE[p.category] and a.value == topic:
                    a.active = False
                    out.changed_mind.append(topic)
        pref = Preference(trip_id=trip.id, user_id=user_id, category=p.category, value=topic,
                          weight=p.weight, source_message_id=message_id)
        db.add(pref)
        active.append(pref)
        out.added_preferences.append(f"{p.category}:{topic}")

    for c in result.constraints:
        ctype = ConstraintType(c.type)
        owner = None if (c.type == "max_budget" and c.applies_to_group) else user_id
        value = _constraint_value(c)
        existing = list(db.scalars(select(Constraint).where(
            Constraint.trip_id == trip.id, Constraint.type == ctype,
            Constraint.user_id.is_(None) if owner is None else Constraint.user_id == owner,
            Constraint.active.is_(True))))
        if ctype is ConstraintType.max_budget:
            for e in existing:  # latest budget statement wins
                e.active = False
            if c.applies_to_group:
                trip.group_budget = c.amount
        elif any(e.value == value for e in existing):
            continue
        db.add(Constraint(trip_id=trip.id, user_id=owner, type=ctype, value=value, source_message_id=message_id))
        out.added_constraints.append(f"{c.type}:{value}")
        out.new_constraints.append(c)

    db.commit()
    return out
