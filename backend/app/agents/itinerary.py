"""Itinerary Agent.

The LLM *chooses and orders* places (by id, from the research bundle only) and says why.
Code owns everything that has to be correct: grounding, hard rules, opening hours, travel times,
scheduling, stays and costs. If the LLM is absent or returns nothing usable, a deterministic
planner builds the plan instead, so a plan always exists."""
import json
import logging
from datetime import date, timedelta
from decimal import Decimal
from math import ceil

from app.agents.llm import LLMClient, LLMError
from app.agents.profile import GroupProfile
from app.agents.research import ResearchBundle
from app.schemas.itinerary import (DraftDay, DraftItem, Itinerary, ItineraryDay, ItineraryDraft, ItineraryItem,
                                   StayChoice)
from app.services.budget_calc import CostLine, stay_cost
from app.services.topics import CANONICAL
from app.tools.curated import Destination, Place, place_open_on

log = logging.getLogger("wayfare.itinerary")

TIERS = ["budget", "mid", "premium"]
TIER_LABEL = {"budget": "Budget-friendly", "mid": "Mid-range", "premium": "Premium"}
ARRIVAL_START, DAY_START = 12 * 60, 9 * 60      # people arrive around noon on day 1
DAY_END, EVENING_END = 20 * 60, 23 * 60 + 30
BUFFER_MIN, MAX_STOPS = 15, 4
KIND_RANK = {"sight": 0, "activity": 0, "food": 1, "market": 2, "nightlife": 3}


# ---------------------------------------------------------------- small helpers

def hm(m: int) -> str:
    return f"{m // 60:02d}:{m % 60:02d}"


def to_min(s: str) -> int:
    h, m = s.split(":")
    return int(h) * 60 + int(m)


def _round_up(m: int, step: int = 15) -> int:
    return ceil(m / step) * step


def first_name(full: str | None) -> str:
    return (full or "").split()[0] if full else ""


def matches_topic(p: Place, topic: str) -> bool:
    """'nightlife' means clubs and bars. An evening market or a beach with beach bars is not nightlife."""
    if topic == "nightlife":
        return p.kind == "nightlife"
    return topic in p.topics


def is_avoided(p: Place, avoids: set[str]) -> bool:
    name = p.name.lower()
    return any(matches_topic(p, a) or (a not in CANONICAL and a in name) for a in avoids)


def member_wants(p: Place, weights: dict[str, int]) -> float:
    """How much one member wants this place: by topic (primary topic counts fully) or by naming it."""
    name = p.name.lower()
    s = 0.0
    for i, t in enumerate(p.topics):
        s += weights.get(t, 0) * (1.0 if i == 0 else 0.6)
    s += sum(w for t, w in weights.items() if t not in p.topics and t in name)
    return s


def score(p: Place, profile: GroupProfile) -> float:
    s = sum(member_wants(p, w) for w in profile.interests.values()) / 3
    s -= sum(member_wants(p, w) for w in profile.dislikes.values()) / 3
    if any(m.lower() in p.name.lower() for m in profile.must_include):
        s += 10
    return s


def serves(p: Place, profile: GroupProfile) -> list[str]:
    return [first_name(profile.members.get(u)) for u, w in sorted(profile.interests.items())
            if member_wants(p, w) > 0 and profile.members.get(u)]


# ---------------------------------------------------------------- must-haves

def required_places(bundle: ResearchBundle, profile: GroupProfile) -> tuple[list[Place], list[str]]:
    """Resolve must-haves to real, available places. A must-have that can't be met is *reported*,
    never silently swapped for something similar."""
    dest, avail = bundle.destination, {p.id for p in bundle.places}
    found: list[Place] = []
    unmatched: list[str] = []
    for text in profile.must_include:
        t = text.lower().strip()
        by_name = [p for p in dest.places if t in p.name.lower() or t.replace(" ", "_") in p.id]
        if by_name:
            hit = next((p for p in by_name if p.id in avail), None)
        elif t in CANONICAL:
            pool = [p for p in bundle.places if matches_topic(p, t) and not is_avoided(p, profile.avoids)]
            hit = max(pool, key=lambda p: (score(p, profile), p.id), default=None)
        else:
            hit = None
        if hit is None:
            unmatched.append(text)
        elif hit not in found:
            found.append(hit)
    return found, unmatched


# ---------------------------------------------------------------- scheduling (pure code)

Stop = tuple[Place, str, list[str], str | None]   # place, why, serves, start-time hint


EARLIEST_START = 7 * 60


def schedule_stops(dest: Destination, day: date | None, stops: list[Stop], arrival: bool = False,
                   anchor: str | None = None, day_no: int | None = None) -> tuple[list[ItineraryItem], list[str]]:
    """Turn ordered stops into timed items. Anything that can't be done properly is dropped *and reported*.
    arrival=True: people reach the destination around noon. anchor: the area the day starts in (e.g. the hotel);
    the drive to a first stop in a different area is then counted."""
    items: list[ItineraryItem] = []
    dropped: list[str] = []
    t, prev_area = (ARRIVAL_START if arrival else DAY_START), None
    where = f"day {day_no}" if day_no else "that day"
    for place, why, who, hint in stops:
        if day and not place_open_on(place, day):
            dropped.append(f"{place.name} isn't open on {day.day} {day:%b}.")
            continue
        travel = dest.minutes_between(prev_area, place.area) if prev_area else (
            dest.minutes_between(anchor, place.area) if anchor and anchor != place.area else 0)
        evening = bool(place.opens and to_min(place.opens) >= 18 * 60)
        limit = EVENING_END if evening else DAY_END
        if place.closes and not evening:
            limit = min(limit, to_min(place.closes))

        def timed(base: int) -> tuple[int, int]:
            st = base + (travel + BUFFER_MIN if prev_area else travel)
            if hint:
                st = max(st, to_min(hint))
            if place.opens:
                st = max(st, to_min(place.opens))
            st = _round_up(st)
            return st, st + place.duration_min

        start, end = timed(t)
        if end > limit and not prev_area and not arrival and place.opens:
            # A long excursion that opens early (e.g. Rohtang) can start the day earlier than usual
            early_start, early_end = timed(max(EARLIEST_START, to_min(place.opens)) - travel)
            if early_end <= limit:
                start, end = early_start, early_end
        if end > limit:
            dropped.append(f"{place.name}: the timing doesn't work on {where} (it would run past {hm(limit)}).")
            continue
        items.append(ItineraryItem(
            place_id=place.id, name=place.name, kind=place.kind, area=place.area, start=hm(start), end=hm(end),
            duration_min=place.duration_min, cost_pp=place.cost_pp, travel_min_from_prev=travel,
            why=why or place.note, serves=who, lat=place.lat, lon=place.lon))
        t, prev_area = end, place.area
    return items, dropped


def _fits(dest: Destination, day: date | None, places: list[Place], arrival: bool = False,
          anchor: str | None = None) -> bool:
    _, dropped = schedule_stops(dest, day, [(p, "", [], None) for p in places], arrival, anchor)
    return not dropped


def _order(p: Place) -> tuple:
    return KIND_RANK.get(p.kind, 1), p.opens or "00:00", p.id


def _dates(start: date | None, n_days: int) -> list[date | None]:
    return [start + timedelta(days=i) if start else None for i in range(n_days)]


def _area_name(dest: Destination, area_id: str) -> str:
    return next((a.name.split(" (")[0] for a in dest.areas if a.id == area_id), area_id)


def _day_title(dest: Destination, items: list[ItineraryItem]) -> str:
    if not items:
        return "Free day"
    first, last = _area_name(dest, items[0].area), _area_name(dest, items[-1].area)
    return first if first == last else f"{first}, then {last}"


# ---------------------------------------------------------------- stays, transport, costs

def make_stay(dest: Destination, tier: str, home_area: str, nights: int, travelers: int,
              start: date | None) -> StayChoice:
    options = [s for s in dest.stay_options if s.tier == tier]
    if not options:   # this destination lacks that tier: use the nearest one it has
        for alt in sorted(TIERS, key=lambda x: abs(TIERS.index(x) - TIERS.index(tier))):
            options = [s for s in dest.stay_options if s.tier == alt]
            if options:
                tier = alt
                break
    pick = next((s for s in options if s.area == home_area), options[0])
    rate = (pick.nightly_low + pick.nightly_high) / 2
    if start and dest.is_peak(start.month):
        rate *= dest.peak_multiplier
    area = _area_name(dest, pick.area)
    return StayChoice(
        tier=tier, area=pick.area, area_name=area, nightly_per_room=int(round(rate / 10) * 10),
        rooms=ceil(travelers / 2), nights=nights,
        why=f"{TIER_LABEL[tier]} stays in {area}, close to most of the plan. {pick.note}.".replace("..", "."))


def _default_transport(dest: Destination) -> str:
    daily = [t for t in dest.transport if t.unit == "per_day_vehicle"]
    return next((t.id for t in daily if t.id == "cab_day"), (daily or dest.transport)[0].id)


def cheapest_transport(dest: Destination, travelers: int, n_days: int) -> str:
    daily = [t for t in dest.transport if t.unit == "per_day_vehicle"] or dest.transport
    return min(daily, key=lambda t: (t.cost_inr * n_days * ceil(travelers / t.capacity), t.id)).id


def cost_lines(it: Itinerary, dest: Destination, travelers: int) -> tuple[list[CostLine], dict[str, str]]:
    """Returns (cost lines, label → place_id) so the budget loop can name the places it trims."""
    n_days = len(it.days)
    lines: list[CostLine] = []
    if it.stay and it.stay.nights > 0:
        lines.append(CostLine("accommodation", f"{TIER_LABEL[it.stay.tier]} stay, {it.stay.nights} nights",
                              stay_cost(Decimal(it.stay.nightly_per_room), it.stay.nights, travelers)))
    lines.append(CostLine("food", f"Meals ({it.food_tier}), {n_days} days",
                          Decimal(dest.food_per_person_day[it.food_tier] * n_days), per_person=True))
    tid = it.transport_id or _default_transport(dest)
    t = next((x for x in dest.transport if x.id == tid), dest.transport[0])
    vehicles = ceil(travelers / t.capacity)
    per = n_days if t.unit == "per_day_vehicle" else 1
    lines.append(CostLine("transport", f"{t.mode}, {n_days} days" if per > 1 else t.mode,
                          Decimal(t.cost_inr * per * vehicles)))
    planned = {i.place_id for d in it.days for i in d.items}
    for extra in dest.transport:   # excursion cabs (e.g. Rohtang) are added only if the plan includes that trip
        if extra.unit == "per_trip_vehicle" and extra.id != tid and \
                any(pid.startswith(extra.id.split("_")[0]) for pid in planned):
            lines.append(CostLine("transport", extra.mode, Decimal(extra.cost_inr * ceil(travelers / extra.capacity))))
    label_map: dict[str, str] = {}
    for d in it.days:
        for i in d.items:
            if i.cost_pp > 0:
                lines.append(CostLine("food" if i.kind == "food" else "activities", i.name,
                                      Decimal(i.cost_pp), per_person=True))
                label_map[i.name] = i.place_id
    return lines, label_map


# ---------------------------------------------------------------- draft → real itinerary

def materialize(draft: ItineraryDraft, bundle: ResearchBundle, profile: GroupProfile, start: date | None,
                n_days: int, avoid_ids: set[str] | frozenset[str] = frozenset(), stay_tier: str | None = None,
                food_tier: str | None = None, transport_id: str | None = None) -> tuple[Itinerary, list[str]]:
    """Ground a draft in real data and make it real: reject invented places, enforce hard rules, add times."""
    dest = bundle.destination
    avail = {p.id: p for p in bundle.places}
    dates = _dates(start, n_days)
    dropped: list[str] = []
    used: set[str] = set()
    days: list[ItineraryDay] = []
    for i, day in enumerate(dates):
        dd = draft.days[i] if i < len(draft.days) else DraftDay()
        stops: list[Stop] = []
        for it in dd.items:
            p = avail.get(it.place_id)
            if p is None:
                dropped.append(f"{it.place_id}: not a place I can verify, so I left it out.")
            elif p.id in used:
                dropped.append(f"{p.name} was already planned on an earlier day.")
            elif p.id in avoid_ids:
                continue          # a deliberate budget trim is a decision, not a failure to report
            elif is_avoided(p, profile.avoids):
                dropped.append(f"{p.name} was left out because someone ruled that out.")
            elif any(matches_topic(p, t) and any(matches_topic(avail[u], t) for u in used)
                     for t in profile.limited_topics):
                dropped.append(f"{p.name} was left out: the group agreed to keep that to a single slot.")
            elif len(stops) >= MAX_STOPS:
                dropped.append(f"{p.name} was left out: day {i + 1} was already full.")
            else:
                stops.append((p, it.why.strip(), serves(p, profile), it.start_time))
                used.add(p.id)
        items, drops = schedule_stops(dest, day, stops, arrival=(i == 0 and n_days > 1), day_no=i + 1)
        dropped += drops
        note = ""
        if day and (absent := profile.unavailable.get(day)):
            names = ", ".join(first_name(profile.members.get(u)) for u in absent)
            note = f"{names} can't make this day, so everything today is optional."
            for item in items:
                item.optional = True
        days.append(ItineraryDay(index=i + 1, date=day, title=dd.title.strip() or _day_title(dest, items),
                                 note=note, items=items))
    all_items = [i for d in days for i in d.items]
    tier = stay_tier or draft.stay_tier or "mid"
    tier = tier if tier in TIERS else "mid"
    food = food_tier or draft.food_tier or "mid"
    food = food if food in TIERS else "mid"
    counts: dict[str, int] = {}
    for i_ in all_items:
        counts[i_.area] = counts.get(i_.area, 0) + 1
    home = max(counts, key=counts.get) if counts else dest.areas[0].id
    stay = make_stay(dest, tier, home, max(n_days - 1, 0), profile.travelers, start)
    it = Itinerary(destination=dest.name, days=days, stay=stay, food_tier=food,
                   transport_id=transport_id or draft.transport_id or _default_transport(dest),
                   summary=f"{n_days} days in {dest.name}: {len(all_items)} stops, {TIER_LABEL[stay.tier].lower()} "
                           f"stays in {stay.area_name}.")
    return it, dropped


# ---------------------------------------------------------------- deterministic planner

def _arrival(i: int, n_days: int) -> bool:
    return i == 0 and n_days > 1          # a one-day trip has no "arrive around noon" rule


def _feasible_days(dest: Destination, p: Place, dates: list[date | None]) -> list[int]:
    return [i for i, d in enumerate(dates) if _fits(dest, d, [p], _arrival(i, len(dates)))]


def heuristic_draft(bundle: ResearchBundle, profile: GroupProfile, start: date | None, n_days: int,
                    avoid_ids: set[str] | frozenset[str] = frozenset(), stay_tier: str | None = None,
                    previous: Itinerary | None = None, food_tier: str | None = None) -> ItineraryDraft:
    """Fair, grounded and deterministic: must-haves first, then everyone's favourite, then best overall."""
    dest, dates = bundle.destination, _dates(start, n_days)
    want_nightlife = any("nightlife" in w for w in profile.interests.values()) or "nightlife" in profile.must_include
    kept = set(previous.place_ids()) if previous else set()
    variety = {"culture": 0.6, "nature": 0.5, "food": 0.3, "beaches": 0.3}

    def rank(p: Place) -> float:
        s = score(p, profile) + (0.4 if p.id in kept else 0)
        if not profile.interests:
            s += sum(variety.get(t, 0.1) for t in p.topics)
        return s

    cands = [p for p in bundle.places if p.id not in avoid_ids and not is_avoided(p, profile.avoids)
             and (want_nightlife or p.kind != "nightlife")]
    feasible = {p.id: _feasible_days(dest, p, dates) for p in cands}
    cands = [p for p in cands if feasible[p.id]]
    limited = profile.limited_topics
    chosen: list[Place] = []

    def can_add(p: Place) -> bool:
        return p not in chosen and not any(matches_topic(p, t) and any(matches_topic(c, t) for c in chosen)
                                           for t in limited)

    required, _ = required_places(bundle, profile)
    for p in required:
        if p in cands and can_add(p):
            chosen.append(p)
    for uid, w in sorted(profile.interests.items()):                     # fairness: everyone gets their pick
        if any(member_wants(c, w) > 0 for c in chosen):
            continue
        mine = sorted((p for p in cands if can_add(p) and member_wants(p, w) > 0),
                      key=lambda p: (-member_wants(p, w), -rank(p), p.id))
        if mine:
            chosen.append(mine[0])
    for p in sorted(cands, key=lambda p: (-rank(p), p.id)):
        if len(chosen) >= min(len(cands), n_days * 3):
            break
        if can_add(p) and rank(p) > -0.5:
            chosen.append(p)

    buckets: list[list[Place]] = [[] for _ in range(n_days)]

    def place_in(p: Place, allowed: list[int]) -> bool:
        options = [i for i in allowed if len(buckets[i]) < MAX_STOPS
                   and _fits(dest, dates[i], sorted(buckets[i] + [p], key=_order), _arrival(i, n_days))]
        if not options:
            return False
        best = min(options, key=lambda i: (0 if any(q.area == p.area for q in buckets[i]) else 1, len(buckets[i]), i))
        buckets[best].append(p)
        return True

    for p in sorted(chosen, key=lambda p: (len(feasible[p.id]), -rank(p), p.id)):   # most constrained first
        place_in(p, feasible[p.id])
    for i in range(n_days):                                                         # no empty days if avoidable
        if buckets[i]:
            continue
        taken = {q.id for b in buckets for q in b}
        pool = [p for p in sorted(cands, key=lambda p: (-rank(p), p.id))
                if p.id not in taken and i in feasible[p.id]
                and not any(matches_topic(p, t) and any(matches_topic(c, t) for b in buckets for c in b) for t in limited)]
        if pool and place_in(pool[0], [i]):
            continue
        donor = max(range(n_days), key=lambda j: len(buckets[j]))
        for q in list(buckets[donor]):
            if len(buckets[donor]) > 1 and i in feasible[q.id] and _fits(dest, dates[i], [q], _arrival(i, n_days)):
                buckets[donor].remove(q)
                buckets[i].append(q)
                break

    def why(p: Place) -> str:
        if p in required:
            return "A must-have for the group."
        names = serves(p, profile)
        return f"Picked for {', '.join(names)}: it matches what they said they'd enjoy." if names \
            else (p.note or "A well-loved stop in the area.")

    days = [DraftDay(items=[DraftItem(place_id=p.id, why=why(p)) for p in sorted(b, key=_order)]) for b in buckets]
    return ItineraryDraft(days=days, stay_tier=stay_tier or "mid", food_tier=food_tier or "mid")


# ---------------------------------------------------------------- LLM planner

SYSTEM = """You plan a group trip itinerary. Choose and order places for each day.
Hard rules:
- Use ONLY place ids from "candidates". Never invent places.
- Exactly the days listed. 2-4 places per day, grouped by area to limit travel. Day 1 starts around noon.
- Never schedule a place on a day it is not open (see only_days: Monday=0) or that it cannot fit before it closes.
- Topics in "limit_once" are contested in the group: include at most ONE place with that topic in the whole trip.
- Always include every id in "must_include". Never include anything matching "avoid_topics".
- Give every member at least one place that matches their interests where possible.
- Order each day: sights and activities first, then food and markets, evening venues last.
- "why" is one friendly sentence on why this place suits THIS group. Do not output times or prices.
Also choose stay_tier and food_tier (budget | mid | premium) that fit the budget note."""


def _llm_draft(llm: LLMClient, bundle: ResearchBundle, profile: GroupProfile, start: date | None, n_days: int,
               avoid_ids: set[str], previous: Itinerary | None, required: list[Place]) -> ItineraryDraft:
    dest, dates = bundle.destination, _dates(start, n_days)
    cands = [p for p in bundle.places if p.id not in avoid_ids and not is_avoided(p, profile.avoids)]
    ctx = {
        "days": [{"day": i + 1, "date": d.isoformat() if d else None, "weekday": d.strftime("%A") if d else None}
                 for i, d in enumerate(dates)],
        "candidates": [{"id": p.id, "name": p.name, "area": p.area, "kind": p.kind, "topics": p.topics,
                        "minutes": p.duration_min, "cost_pp": p.cost_pp, "opens": p.opens, "closes": p.closes,
                        "only_days": p.only_days} for p in cands],
        "members": {first_name(n): {"interests": profile.interests.get(u, {}), "dislikes": profile.dislikes.get(u, {})}
                    for u, n in profile.members.items()},
        "avoid_topics": sorted(profile.avoids), "limit_once": sorted(profile.limited_topics),
        "must_include": [p.id for p in required],
        "unavailable": {d.isoformat(): [first_name(profile.members.get(u)) for u in us]
                        for d, us in profile.unavailable.items()},
        "budget_note": None if profile.cap is None else f"Group cap ₹{profile.cap} for {profile.travelers} people.",
        "current_plan": None if previous is None else [[i.place_id for i in d.items] for d in previous.days],
    }
    return llm.structured(ItineraryDraft, SYSTEM, json.dumps(ctx, ensure_ascii=False))


def _inject_required(draft: ItineraryDraft, bundle: ResearchBundle, required: list[Place],
                     dates: list[date | None]) -> ItineraryDraft:
    """The model may ignore a must-have. Put it in on the emptiest day where it actually works."""
    dest = bundle.destination
    days = [d.model_copy(deep=True) for d in draft.days[:len(dates)]]
    days += [DraftDay() for _ in range(len(dates) - len(days))]
    planned = {i.place_id for d in days for i in d.items}
    for p in required:
        if p.id in planned:
            continue
        for i in sorted(_feasible_days(dest, p, dates), key=lambda i: (len(days[i].items), i)):
            if len(days[i].items) < MAX_STOPS:
                days[i].items.append(DraftItem(place_id=p.id, why="A must-have for the group."))
                break
    return draft.model_copy(update={"days": days})


def plan_itinerary(llm: LLMClient | None, bundle: ResearchBundle, profile: GroupProfile, start: date | None,
                   n_days: int, avoid_ids: set[str], stay_tier: str | None, previous: Itinerary | None,
                   food_tier: str | None = None, transport_id: str | None = None) -> tuple[Itinerary, list[str]]:
    """Returns (itinerary, dropped). `stay_tier`/`food_tier`/`transport_id` are the budget loop's levers
    and are binding even if the model chose differently."""
    required, _ = required_places(bundle, profile)
    avoid = set(avoid_ids) - {p.id for p in required}      # a must-have is never trimmed
    dates = _dates(start, n_days)
    levers = dict(stay_tier=stay_tier, food_tier=food_tier, transport_id=transport_id)
    if llm is not None:
        try:
            draft = _llm_draft(llm, bundle, profile, start, n_days, avoid, previous, required)
            draft = _inject_required(draft, bundle, required, dates)
            it, dropped = materialize(draft, bundle, profile, start, n_days, avoid, **levers)
            if it.place_ids():
                return it, dropped
            log.warning("LLM draft had no usable places; using the rule-based planner")
        except LLMError:
            log.warning("LLM unavailable; using the rule-based planner")
    draft = heuristic_draft(bundle, profile, start, n_days, avoid, stay_tier, previous, food_tier)
    it, dropped = materialize(draft, bundle, profile, start, n_days, avoid, **levers)
    it.used_fallback = True
    return it, dropped
