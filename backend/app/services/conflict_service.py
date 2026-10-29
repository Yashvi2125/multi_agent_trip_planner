from datetime import date, datetime, timezone
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.agents import conflict as rules
from app.models import Conflict, ConflictStatus, Constraint, ConstraintType, Preference, Trip, TripMember


def sync_conflicts(db: Session, trip: Trip) -> tuple[list[Conflict], list[Conflict]]:
    """Re-run detection against current state. Returns (newly_opened, auto_resolved).
    A conflict resolves itself when a member changes their mind; closed ones never reopen."""
    members = list(db.scalars(select(TripMember).where(TripMember.trip_id == trip.id)))
    names = {m.user_id: m.user.name for m in members}

    prefs = [rules.PrefView(p.user_id, p.category, p.value, p.weight) for p in db.scalars(
        select(Preference).where(Preference.trip_id == trip.id, Preference.active.is_(True)))]
    cons = list(db.scalars(select(Constraint).where(Constraint.trip_id == trip.id, Constraint.active.is_(True))))
    budgets = [rules.BudgetView(c.user_id, Decimal(c.value["amount"]))
               for c in cons if c.type is ConstraintType.max_budget and c.user_id]
    avoids = [rules.AvoidView(c.user_id, c.value["text"])
              for c in cons if c.type is ConstraintType.must_avoid and c.user_id]
    unavailable = [rules.UnavailableView(c.user_id, date.fromisoformat(d))
                   for c in cons if c.type is ConstraintType.unavailable_day and c.user_id
                   for d in c.value["dates"]]

    found = {c.key: c for c in rules.detect(
        prefs, budgets, avoids, unavailable, names, len(members),
        trip.group_budget, trip.start_date, trip.end_date)}

    rows = list(db.scalars(select(Conflict).where(Conflict.trip_id == trip.id)))
    open_by_key = {r.key: r for r in rows if r.status is ConflictStatus.open}
    closed_keys = {r.key for r in rows if r.status in (ConflictStatus.accepted, ConflictStatus.dismissed)}

    opened: list[Conflict] = []
    for key, cand in found.items():
        if key in open_by_key or key in closed_keys:
            continue
        row = Conflict(trip_id=trip.id, kind=cand.kind, key=key, description=cand.description,
                       involved_user_ids=list(cand.involved), proposed_compromise=cand.compromise)
        db.add(row)
        opened.append(row)

    resolved: list[Conflict] = []
    for key, row in open_by_key.items():
        if key not in found:
            row.status = ConflictStatus.resolved
            row.resolved_at = datetime.now(timezone.utc)
            resolved.append(row)
    db.commit()
    return opened, resolved
