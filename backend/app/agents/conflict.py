"""Rule-based conflict detection. Pure functions over plain data: no DB, no LLM.
Rules find the disagreement; wording of the compromise is deterministic here and
can be polished by the LLM later without changing *what* is detected."""
from dataclasses import dataclass
from datetime import date
from decimal import Decimal

from app.core.money import format_inr


@dataclass(frozen=True)
class PrefView:
    user_id: int
    category: str  # interest | dislike | ...
    topic: str
    weight: int


@dataclass(frozen=True)
class BudgetView:
    user_id: int
    amount: Decimal


@dataclass(frozen=True)
class AvoidView:  # hard must_avoid
    user_id: int
    topic: str


@dataclass(frozen=True)
class UnavailableView:
    user_id: int
    day: date


@dataclass(frozen=True)
class ConflictCandidate:
    kind: str  # topic_clash | hard_vs_soft | budget_gap | date_clash
    key: str   # stable identity so re-runs don't create duplicates
    description: str
    involved: tuple[int, ...]
    compromise: str


def _d(d: date) -> str:
    return f"{d.day} {d:%b}"  # '%-d' is not portable to Windows


def _names(ids, names: dict[int, str]) -> str:
    parts = [names.get(i, "Someone") for i in sorted(set(ids))]
    return parts[0] if len(parts) == 1 else ", ".join(parts[:-1]) + f" and {parts[-1]}"


def detect(prefs: list[PrefView], budgets: list[BudgetView], avoids: list[AvoidView],
           unavailable: list[UnavailableView], names: dict[int, str], travelers: int,
           group_budget: Decimal | None, trip_start: date | None, trip_end: date | None) -> list[ConflictCandidate]:
    out: list[ConflictCandidate] = []

    # 1. Soft vs soft: someone wants it, someone would rather avoid it
    topics = {p.topic for p in prefs}
    hard_avoided = {a.topic for a in avoids}
    for t in sorted(topics - hard_avoided):
        likes = [p.user_id for p in prefs if p.topic == t and p.category == "interest"]
        dislikes = [p.user_id for p in prefs if p.topic == t and p.category == "dislike"]
        if likes and dislikes:
            who_l, who_d = _names(likes, names), _names(dislikes, names)
            out.append(ConflictCandidate(
                "topic_clash", f"topic_clash:{t}",
                f"{who_l} would like {t}, but {who_d} would rather skip it.",
                tuple(sorted(set(likes + dislikes))),
                f"Keep {t} to a single slot on one day and leave the other days free of it, "
                f"so {who_d} can opt out without the whole trip changing."))

    # 2. Soft want vs someone's hard "no": cannot be traded off, only worked around
    for a in avoids:
        likes = [p.user_id for p in prefs if p.topic == a.topic and p.category == "interest" and p.user_id != a.user_id]
        if likes:
            who_l = _names(likes, names)
            out.append(ConflictCandidate(
                "hard_vs_soft", f"hard_vs_soft:{a.topic}:{a.user_id}",
                f"{who_l} would like {a.topic}, but {names.get(a.user_id, 'someone')} has ruled it out completely.",
                tuple(sorted({a.user_id, *likes})),
                f"Leave {a.topic} out of the shared plan. {who_l} can still do it as an optional "
                f"free-time activity while {names.get(a.user_id, 'they')} does something else."))

    # 3. Personal budget ceiling below the per-head share of the group budget
    if group_budget and travelers:
        share = group_budget / travelers
        for b in budgets:
            if b.amount < share:
                out.append(ConflictCandidate(
                    "budget_gap", f"budget_gap:{b.user_id}",
                    f"{names.get(b.user_id, 'Someone')} can spend up to {format_inr(b.amount)}, but the group "
                    f"budget works out to {format_inr(share)} each.",
                    (b.user_id,),
                    f"Plan around {format_inr(b.amount)} per person ({format_inr(b.amount * travelers)} in total), "
                    f"or let the group agree to cover the difference."))

    # 4. Someone can't make a day that falls inside the trip
    for u in unavailable:
        if trip_start and trip_end and trip_start <= u.day <= trip_end:
            out.append(ConflictCandidate(
                "date_clash", f"date_clash:{u.user_id}:{u.day.isoformat()}",
                f"{names.get(u.user_id, 'Someone')} can't make {_d(u.day)}, which is during the trip.",
                (u.user_id,),
                f"Keep {_d(u.day)} light and optional, or shift the trip dates if most people prefer."))

    return out
