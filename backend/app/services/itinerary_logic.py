"""Deterministic planning logic. The LLM chooses *which* grounded places and why;
this module owns every fact (names, costs, times, travel) and every hard rule."""
from dataclasses import dataclass, field
from datetime import date, timedelta
from math import ceil

from app.schemas.itinerary import Day, DayDraft, Item, Itinerary, ItineraryDraft, Revision, StayChoice, StopDraft
from app.tools.curated import Destination, Place, place_open_on

DAY_START, LUNCH_AT, DINNER_AT, DAY_END = 9 * 60, 12 * 60 + 30, 19 * 60, 23 * 60 + 30
MAX_STOPS = 4
TIERS = ["budget", "mid", "premium"]
_KIND_ORDER = {"sight": 1, "activity": 1, "market": 2, "food": 2, "nightlife": 3}


def hm(minutes: int) -> str:
    return f"{minutes // 60:02d}:{minutes % 60:02d}"


def to_min(s: str) -> int:
    h, m = s.split(":")
    return int(h) * 60 + int(m)


def _round_up(m: int, step: int = 15) -> int:
    return ceil(m / step) * step


def trip_dates(start: date | None, end: date | None) -> list[date]:
    if not (start and end):
        return []
    return [start + timedelta(days=i) for i in range((end - start).days + 1)]


@dataclass
class Dropped:
    name: str
    reason: str


@dataclass
class ScheduleResult:
    itinerary: Itinerary
    dropped: list[Dropped] = field(default_factory=list)
    ungrounded: list[str] = field(default_factory=list)  # ids the model made up


def _meal(kind_label: str, start: int, mins: int, area: str | None, travel: int = 0) -> Item:
    return Item(kind="meal", name=kind_label, area=area, start=hm(start), end=hm(start + mins),
                travel_min=travel, why="Meal break. Food is covered by the daily food budget.")


def schedule_day(dest: Destination, day_date: date | None, stops: list[tuple[Place, str]],
                 dropped: list[Dropped]) -> list[Item]:
    t, prev_area, items = DAY_START, None, []
    lunch = dinner = False
    for place, why in stops:
        travel = dest.minutes_between(prev_area, place.area) if prev_area else 0
        start = t + travel
        if not lunch and place.kind != "food" and t < 14 * 60 + 30 and (t >= 12 * 60 or start > LUNCH_AT + 30):
            ls = max(t, LUNCH_AT)
            items.append(_meal("Lunch", ls, 60, prev_area))
            t, lunch = ls + 60, True
            start = t + travel
        if not dinner and place.kind != "food" and start >= DINNER_AT + 30 and t <= 20 * 60 + 30:
            ds = max(t, DINNER_AT)
            items.append(_meal("Dinner", ds, 75, prev_area))
            t, dinner = ds + 75, True
            start = t + travel
        if place.opens:
            start = max(start, to_min(place.opens))
        start = _round_up(start)
        end = start + place.duration_min
        if place.closes and end > to_min(place.closes):
            dropped.append(Dropped(place.name, f"it wouldn't fit before it closes at {place.closes}"))
            continue
        if end > DAY_END:
            dropped.append(Dropped(place.name, "the day was already full"))
            continue
        if place.kind == "food" and 11 * 60 + 30 <= start <= 15 * 60:
            lunch = True
        if place.kind == "food" and start >= 18 * 60 + 30:
            dinner = True  # a clubbing stop is not dinner, a restaurant is
        items.append(Item(kind=place.kind, name=place.name, place_id=place.id, area=place.area,
                          start=hm(start), end=hm(end), cost_pp=place.cost_pp, travel_min=travel,
                          why=why or place.note, lat=place.lat, lon=place.lon))
        t, prev_area = end, place.area
    if not dinner and items and t <= 20 * 60 + 30:
        ds = max(t, DINNER_AT)
        items.append(_meal("Dinner", ds, 75, prev_area))
    return items


def _stay(dest: Destination, tier: str, area_hint: str, nights: int, travelers: int, why: str,
          start: date | None) -> StayChoice:
    options = [s for s in dest.stay_options if s.tier == tier]
    if not options:  # destination lacks this tier: fall back to the nearest one it has
        for alt in sorted(TIERS, key=lambda x: abs(TIERS.index(x) - TIERS.index(tier))):
            options = [s for s in dest.stay_options if s.tier == alt]
            if options:
                tier = alt
                break
    pick = next((s for s in options if s.area == area_hint), options[0])
    rate = (pick.nightly_low + pick.nightly_high) / 2
    if start and dest.is_peak(start.month):
        rate *= dest.peak_multiplier
    return StayChoice(tier=tier, area=pick.area, nightly_rate=int(round(rate, -1)),
                      rooms=ceil(travelers / 2), nights=nights, why=why or pick.note)


def ground_and_schedule(draft: ItineraryDraft, dest: Destination, available_ids: set[str],
                        start: date | None, end: date | None, travelers: int,
                        avoid_topics: set[str], revision: Revision | None = None) -> ScheduleResult:
    """Turn an LLM draft into a real itinerary: reject invented places, enforce hard rules, add times."""
    dates = trip_dates(start, end) or [None] * max(len(draft.days), 1)
    rev = revision or Revision()
    res = ScheduleResult(itinerary=Itinerary(days=[]))
    used: set[str] = set()
    for i, d in enumerate(dates):
        draft_day = draft.days[i] if i < len(draft.days) else None
        stops: list[tuple[Place, str]] = []
        for s in (draft_day.stops if draft_day else []):
            p = dest.place(s.place_id)
            if p is None or s.place_id not in available_ids:
                res.ungrounded.append(s.place_id)
            elif s.place_id in used:
                continue
            elif s.place_id in rev.drop_place_ids:
                continue
            elif avoid_topics & set(p.topics):
                res.dropped.append(Dropped(p.name, "someone in the group ruled that out"))
            elif d and not place_open_on(p, d):
                res.dropped.append(Dropped(p.name, "it isn't open that day"))
            elif len(stops) < MAX_STOPS:
                stops.append((p, s.why))
                used.add(p.id)
        items = schedule_day(dest, d, stops, res.dropped)
        res.itinerary.days.append(Day(day_number=i + 1, date=d, title=(draft_day.title if draft_day else "") or f"Day {i + 1}", items=items))
    nights = max(len(dates) - 1, 0)
    tier = rev.stay_tier or draft.stay_tier
    res.itinerary.stay = _stay(dest, tier, draft.stay_area, nights, travelers, draft.stay_why, start)
    res.itinerary.food_tier = rev.food_tier or draft.food_tier
    return res


# ---------- deterministic fallback planner (also the "no preferences" planner) ----------

def place_score(p: Place, interests: dict[int, dict[str, int]], dislikes: dict[int, dict[str, int]]) -> float:
    s = 0.0
    for member in interests.values():
        s += sum(w for t, w in member.items() if t in p.topics) / 3
    for member in dislikes.values():
        s -= sum(w for t, w in member.items() if t in p.topics) / 3
    return s


def _order(p: Place, anchor: str | None = None) -> tuple:
    return (_KIND_ORDER.get(p.kind, 1), 0 if p.area == anchor else 1, p.opens or "00:00")


def heuristic_draft(dest: Destination, available: list[Place], interests: dict[int, dict[str, int]],
                    dislikes: dict[int, dict[str, int]], day_dates: list[date | None], avoid_topics: set[str],
                    stay_tier: str = "mid", food_tier: str = "mid") -> ItineraryDraft:
    pool = [p for p in available if not (avoid_topics & set(p.topics))]
    # With no stated preferences, favour variety: culture and nature sights first.
    base = {"culture": 0.6, "nature": 0.5, "food": 0.3, "beaches": 0.3}

    def score(p: Place) -> float:
        s = place_score(p, interests, dislikes)
        if not interests:
            s += sum(base.get(t, 0.1) for t in p.topics)
        return s

    # Guarantee each member their favourite place first, so nobody is left out
    must: list[Place] = []
    for topics in interests.values():
        mine = sorted((p for p in pool if p not in must and set(topics) & set(p.topics)),
                      key=lambda p: -sum(w for t, w in topics.items() if t in p.topics))
        if mine:
            must.append(mine[0])
    remaining = must + sorted((p for p in pool if p not in must), key=lambda p: -score(p))

    days: list[DayDraft] = []
    for n, d in enumerate(day_dates):
        candidates = [p for p in remaining if not d or place_open_on(p, d)]
        if not candidates:
            days.append(DayDraft(title=f"Day {n + 1}"))
            continue
        anchor = candidates[0].area
        near = sorted(candidates, key=lambda p: (0 if p.area == anchor else dest.minutes_between(anchor, p.area),
                                                 candidates.index(p)))
        chosen: list[Place] = []
        for p in near:
            if len(chosen) >= MAX_STOPS:
                break
            trial = sorted(chosen + [p], key=lambda q: _order(q, anchor))
            dropped: list[Dropped] = []
            schedule_day(dest, d, [(q, "") for q in trial], dropped)
            if not dropped:  # only accept stops that genuinely fit opening hours and the day
                chosen = trial
        for p in chosen:
            remaining.remove(p)
        area_name = next((a.name.split(" (")[0] for a in dest.areas if a.id == anchor), "")
        days.append(DayDraft(title=area_name or f"Day {n + 1}",
                             stops=[StopDraft(place_id=p.id, why=_why(p, interests, dislikes)) for p in chosen]))
    return ItineraryDraft(days=days, stay_tier=stay_tier, food_tier=food_tier, stay_area=_first_area(dest, days),
                          stay_why="Close to the first day's plans and typical of the group's budget tier.")


def _first_area(dest: Destination, days: list[DayDraft]) -> str:
    first = next((s.place_id for d in days for s in d.stops), None)
    place = dest.place(first) if first else None
    return place.area if place else ""


def _why(p: Place, interests, dislikes) -> str:
    wanted = sorted({t for m in interests.values() for t in m if t in p.topics})
    return f"Matches the group's interest in {', '.join(wanted)}." if wanted else (p.note or "A well-regarded stop in the area.")


# ---------- coverage + diff ----------

def preference_coverage(it: Itinerary, interests: dict[int, dict[str, int]], dest: Destination) -> dict[int, list[str]]:
    """For each member, which of their interests appear somewhere in the plan."""
    topics: set[str] = set()
    for d in it.days:
        for item in d.items:
            if item.place_id and (p := dest.place(item.place_id)):
                topics.update(p.topics)
    return {uid: sorted(set(t) & topics) for uid, t in interests.items()}


def _places_by_day(it: Itinerary) -> dict[str, tuple[int, str]]:
    return {i.place_id: (d.day_number, i.name) for d in it.days for i in d.items if i.place_id}


def diff_itineraries(old: Itinerary | None, new: Itinerary) -> str:
    if old is None:
        return "First version of the plan."
    a, b = _places_by_day(old), _places_by_day(new)
    added = [b[k][1] for k in b if k not in a]
    removed = [a[k][1] for k in a if k not in b]
    moved = [f"{b[k][1]} (Day {a[k][0]} → Day {b[k][0]})" for k in b if k in a and a[k][0] != b[k][0]]
    parts = []
    if added:
        parts.append("Added " + ", ".join(added))
    if removed:
        parts.append("Removed " + ", ".join(removed))
    if moved:
        parts.append("Moved " + ", ".join(moved))
    if old.stay and new.stay and old.stay.tier != new.stay.tier:
        parts.append(f"Stay changed from {old.stay.tier} to {new.stay.tier}")
    return ". ".join(parts) + "." if parts else "No changes to the stops."
