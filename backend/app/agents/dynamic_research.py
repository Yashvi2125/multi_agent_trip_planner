"""Dynamic Research Agent: builds a `Destination` for a place that has no curated data.

It produces the SAME object the curated JSON files produce, so the planner, budget, validator and explainer
need no changes. The one rule that shapes everything here: never present an estimate as a fact.

  Researched (real data from a provider):  the geocoded place, the attractions and neighbourhoods (OpenStreetMap),
                                           opening hours where OpenStreetMap lists them, last year's observed
                                           weather (Open-Meteo archive).
  Estimated (labelled as such):            travel times (from distance), visit lengths, every price.

If a provider fails, that fact is simply missing and the plan says so; nothing is substituted silently."""
import logging
import math
import re
import threading
from dataclasses import dataclass
from typing import Literal

from pydantic import BaseModel, Field

from app.agents.llm import LLMClient, LLMError
from app.tools.base import (ClimateProvider, GeocodeProvider, GeoPoint, NearbyResult, PlacesProvider, Poi, Suburb,
                            ToolError, TTLCache, haversine_km)
from app.tools.curated import (Area, ChecklistTemplate, Climate, Destination, Place, StayOption, Transport)

log = logging.getLogger("wayfare.dynamic")

MAX_EXTENT_KM = 300      # a bigger bounding box than this is a country or region, not somewhere to plan day by day
MIN_PLACES = 6           # fewer real places than this and an honest plan isn't possible
MAX_AREAS = 6
CLUSTER_KM = 3.5
TIERS = ("budget", "mid", "premium")
# Used only when no price estimate could be obtained, and always labelled as generic in the output.
GENERIC_FOOD = {"budget": 800, "mid": 2000, "premium": 4500}
GENERIC_STAY = {"budget": (2000, 3500), "mid": (5000, 9000), "premium": (14000, 30000)}
GENERIC_TRANSPORT = 3000

Status = Literal["ok", "unrecognized", "too_broad", "insufficient", "unavailable"]


@dataclass
class DynamicOutcome:
    status: Status
    destination: Destination | None = None
    place_name: str = ""     # the recognised name, for user-facing messages


# ---------------------------------------------------------------- small pure helpers

def slug(text: str) -> str:
    s = re.sub(r"[^a-z0-9]+", "_", text.lower().encode("ascii", "ignore").decode()).strip("_")
    return s or "place"


def norm(text: str) -> str:
    return re.sub(r"\s+", " ", re.sub(r"[^\w\s]", " ", text.lower())).strip()


def classify(tags: dict) -> tuple[list[str], str, int, int] | None:
    """Map real map tags to (topics, kind, visit minutes, entry cost). Durations and costs here are rough
    category defaults (estimates); topics must come from the shared vocabulary the planner understands."""
    g = tags.get
    if g("amenity") == "nightclub":
        return ["nightlife"], "nightlife", 150, 800
    if g("tourism") in ("museum", "gallery"):
        return ["culture"], "sight", 120, 400
    if g("tourism") == "viewpoint":
        return ["nature"], "sight", 45, 0
    if g("tourism") in ("zoo", "aquarium"):
        return ["nature"], "activity", 180, 800
    if g("tourism") == "theme_park":
        return ["adventure"], "activity", 300, 2500
    if g("tourism") == "attraction" or g("historic"):
        return ["culture"], "sight", 75, 200
    if g("natural") == "beach":
        return ["beaches", "relaxation"], "sight", 150, 0
    if g("natural") == "waterfall":
        return ["nature"], "sight", 75, 0
    if g("natural") in ("peak", "volcano"):
        return ["nature", "adventure"], "activity", 240, 0
    if g("natural") in ("hot_spring", "cave_entrance"):
        return ["nature"], "sight", 90, 200
    if g("leisure") in ("park", "garden"):
        return ["nature", "relaxation"], "sight", 75, 0
    if g("leisure") == "nature_reserve":
        return ["nature"], "sight", 150, 100
    if g("amenity") == "place_of_worship":
        return ["culture"], "sight", 45, 0
    if g("amenity") == "marketplace":
        return ["shopping", "food"], "market", 90, 0
    if g("shop") == "mall":
        return ["shopping"], "market", 120, 0
    return None


_SPAN = re.compile(r"(\d{1,2}):(\d{2})\s*-\s*(\d{1,2}):(\d{2})")


def parse_hours(tag: str | None) -> tuple[str | None, str | None]:
    """A deliberately simple reading of OpenStreetMap's opening_hours: the widest daily window it lists.
    Anything unclear returns (None, None), meaning 'unknown', never a guess."""
    if not tag or "24/7" in tag:
        return None, None
    starts, ends = [], []
    for h1, m1, h2, m2 in _SPAN.findall(tag):
        a, b = int(h1) * 60 + int(m1), int(h2) * 60 + int(m2)
        if int(h1) > 23 or int(h2) > 24 or int(m1) > 59 or int(m2) > 59:
            return None, None
        starts.append(a)
        ends.append(b)
    if not starts:
        return None, None
    opens, closes = min(starts), max(ends)
    if closes <= opens:                      # runs past midnight, e.g. 18:00-02:00
        closes = 23 * 60 + 59
    closes = min(closes, 23 * 60 + 59)
    if closes - opens < 60:
        return None, None
    f = lambda m: f"{m // 60:02d}:{m % 60:02d}"
    return f(opens), f(closes)


def estimate_minutes(km: float) -> int:
    """Door-to-door minutes from straight-line distance. An ESTIMATE: road distance ~1.35x, city vs highway speed."""
    road = km * 1.35
    speed = 22 if road < 10 else 35 if road < 40 else 55
    return max(10, int(round((10 + road / speed * 60) / 5) * 5))


def rain_class(precip_mm: float) -> str:
    return "low" if precip_mm < 60 else "moderate" if precip_mm < 180 else "heavy"


# ---------------------------------------------------------------- places and areas

def build_places(pois: list[Poi]) -> list[tuple[Poi, Place]]:
    out, used = [], set()
    for poi in pois:
        cls = classify(poi.tags)
        if cls is None:
            continue
        topics, kind, minutes, cost = cls
        opens, closes = parse_hours(poi.tags.get("opening_hours"))
        pid = f"{slug(poi.name)[:36]}_{poi.osm_id.split('/')[-1][-6:]}"
        if pid in used:
            continue
        used.add(pid)
        label = next((poi.tags[k] for k in ("tourism", "historic", "natural", "leisure", "amenity", "shop")
                      if k in poi.tags), "place").replace("_", " ")
        hours_note = "Opening hours from OpenStreetMap." if opens else "Opening hours unknown, so check before you go."
        out.append((poi, Place(id=pid, name=poi.name, area="", lat=poi.lat, lon=poi.lon, topics=topics, kind=kind,
                               duration_min=minutes, cost_pp=cost, opens=opens, closes=closes, only_days=[],
                               closed_months=[], note=f"{label.capitalize()}. {hours_note}")))
    return out


def _nearest(lat: float, lon: float, centres: list[tuple[str, float, float]]) -> str:
    return min(centres, key=lambda c: haversine_km(lat, lon, c[1], c[2]))[0]


def build_areas(items: list[tuple[Poi, Place]], suburbs: list[Suburb]) -> tuple[list[Area], dict[str, str], str]:
    """Group places into areas. Prefer real neighbourhoods; otherwise cluster by location.
    Returns (areas, place_id -> area_id, how)."""
    places = [p for _, p in items]
    centres: list[tuple[str, float, float, str]] = []     # (id, lat, lon, name)
    how = "neighbourhoods"
    if len(suburbs) >= 2:
        seen = set()
        cands = []
        for s in suburbs:
            sid = slug(s.name)
            if sid not in seen:
                seen.add(sid)
                cands.append((sid, s.lat, s.lon, s.name))
        counts: dict[str, int] = {}
        for p in places:
            sid = _nearest(p.lat, p.lon, [(c[0], c[1], c[2]) for c in cands])
            counts[sid] = counts.get(sid, 0) + 1
        keep = sorted(counts, key=lambda k: (-counts[k], k))[:MAX_AREAS]
        centres = [c for c in cands if c[0] in keep]
    if len(centres) < 2:
        how = "clusters"
        centres = []
        for p in places:                                    # places arrive best-documented first
            near = min(centres, key=lambda c: haversine_km(p.lat, p.lon, c[1], c[2]), default=None)
            if near is None or (haversine_km(p.lat, p.lon, near[1], near[2]) > CLUSTER_KM and len(centres) < MAX_AREAS):
                centres.append((f"area_{len(centres) + 1}", p.lat, p.lon, f"Around {p.name}"))
    assign = {p.id: _nearest(p.lat, p.lon, [(c[0], c[1], c[2]) for c in centres]) for p in places}
    names = {c[0]: c[3] for c in centres}
    areas = []
    for aid in sorted(set(assign.values())):                # drop areas nothing was assigned to
        members = [p for p in places if assign[p.id] == aid]
        areas.append(Area(id=aid, name=names[aid], lat=sum(m.lat for m in members) / len(members),
                          lon=sum(m.lon for m in members) / len(members)))
    return areas, assign, how


def travel_matrix(areas: list[Area]) -> list[tuple[str, str, int]]:
    rows = [(a.id, a.id, 15) for a in areas]
    for i, a in enumerate(areas):
        for b in areas[i + 1:]:
            rows.append((a.id, b.id, estimate_minutes(haversine_km(a.lat, a.lon, b.lat, b.lon))))
    return rows


# ---------------------------------------------------------------- cost estimates (AI, validated, else generic)

class TierInts(BaseModel):
    budget: int
    mid: int
    premium: int


class StayRange(BaseModel):
    low: int
    high: int


class PlaceEstimate(BaseModel):
    id: str
    duration_min: int | None = None
    cost_pp: int | None = None


class DestinationEstimates(BaseModel):
    food_per_person_day: TierInts
    stay_nightly_budget: StayRange
    stay_nightly_mid: StayRange
    stay_nightly_premium: StayRange
    local_transport_day: int
    places: list[PlaceEstimate] = Field(default_factory=list)
    notes: list[str] = Field(default_factory=list, max_length=3)


ESTIMATE_SYSTEM = """You estimate typical traveller prices for one destination. Reply in Indian rupees (INR), whole numbers.
These are ESTIMATES for a normal-season visit; do not claim precision.
- food_per_person_day: three meals per person per day for budget / mid / premium eating.
- stay_nightly_budget / _mid / _premium: price range (low, high) for one double room per night.
- local_transport_day: a private taxi or ride-hail for a full day, one 4-seat vehicle.
- places: for EACH id listed (and only those): duration_min (typical visit) and cost_pp (typical entry/ticket price per person, 0 if free).
- notes: up to three short practical tips specific to the destination. Omit anything you are unsure of.
Never invent places or ids."""


def _ordered(d: dict[str, int], lo: int, hi: int) -> bool:
    v = [d[t] for t in TIERS]
    return all(lo <= x <= hi for x in v) and v == sorted(v)


def sane_costs(est: DestinationEstimates | None):
    """Validate AI numbers. Returns (food, stays, transport, per-place) with None for anything implausible,
    so a hallucinated value is dropped rather than trusted."""
    if est is None:
        return None, None, None, {}
    food = {t: getattr(est.food_per_person_day, t) for t in TIERS}
    food = food if _ordered(food, 150, 25000) else None
    stays = {"budget": est.stay_nightly_budget, "mid": est.stay_nightly_mid, "premium": est.stay_nightly_premium}
    stays = ({t: (r.low, r.high) for t, r in stays.items()}
             if all(300 <= r.low < r.high <= 300000 for r in stays.values())
             and [stays[t].low for t in TIERS] == sorted(stays[t].low for t in TIERS) else None)
    transport = est.local_transport_day if 200 <= est.local_transport_day <= 30000 else None
    per_place = {p.id: p for p in est.places
                 if (p.duration_min is None or 15 <= p.duration_min <= 600) and (p.cost_pp is None or 0 <= p.cost_pp <= 50000)}
    return food, stays, transport, per_place


# ---------------------------------------------------------------- the researcher

def _checklist(name: str) -> list[ChecklistTemplate]:
    rows = [(f"Check visa and entry rules for {name} (they change often)", "document"),
            ("Passport valid for 6+ months for every traveller", "document"),
            ("Travel insurance", "document"), ("Book accommodation", "booking"),
            (f"Book travel to {name}", "booking"), ("Download offline maps", "packing"),
            ("Check the weather forecast before you pack", "packing")]
    return [ChecklistTemplate(label=l, category=c) for l, c in rows]


def sources_note(dest: Destination) -> str:
    """The plain-language 'what is fact and what is my estimate' statement shown to the group."""
    p = dest.provenance
    facts = ["the places"] + (["the neighbourhoods"] if p.get("areas", "").startswith("Researched") else []) + \
            (["last year's observed weather"] if p.get("climate", "").startswith("Researched") else [])
    text = (f"I researched {dest.name} live rather than using hand-checked data. From real sources "
            f"({', '.join(facts)}), plus opening hours where OpenStreetMap lists them. "
            f"Travel times, visit lengths and all prices are my own estimates, so treat the budget as a guide.")
    if dest.cost_basis == "generic":
        text += (f" I couldn't estimate local prices for {dest.name}, so costs use a rough all-destination average "
                 f"and could be far off.")
    return text


class DynamicResearcher:
    """Turns an unknown destination into a Destination using real providers. Results are cached because a research
    run makes several external calls; a second plan for the same place costs nothing."""

    def __init__(self, geocoder: GeocodeProvider, places: PlacesProvider, climate: ClimateProvider | None = None,
                 llm: LLMClient | None = None, min_places: int = MIN_PLACES):
        self.geocoder, self.places, self.climate, self.llm, self.min_places = geocoder, places, climate, llm, min_places
        self._ok = TTLCache(24 * 3600)
        self._not_ok = TTLCache(300)         # remember failures briefly so a retry loop can't hammer free APIs
        self._lock = threading.Lock()

    def cached(self, query: str) -> Destination | None:
        out = self._ok.get(norm(query))
        return out.destination if out else None

    def research(self, query: str) -> DynamicOutcome:
        key = norm(query)
        with self._lock:                      # concurrent plans for one place share a single research run
            out = self._ok.get(key) or self._not_ok.get(key)
            if out is None:
                out = self._run(query)
                (self._ok if out.status == "ok" else self._not_ok).set(key, out)
            return out

    def _run(self, query: str) -> DynamicOutcome:
        try:
            pt = self.geocoder.geocode(query)
        except ToolError:
            return DynamicOutcome("unavailable")
        if pt is None:
            return DynamicOutcome("unrecognized")
        name = (pt.label.split(",")[0].strip() or query.strip())
        too_big = (pt.extent_km is not None and pt.extent_km > MAX_EXTENT_KM) or \
                  (pt.extent_km is None and pt.kind in ("country", "continent", "ocean", "sea"))
        if too_big:
            return DynamicOutcome("too_broad", place_name=name)
        radius = int(min(max((pt.extent_km or 20) * 500, 6000), 20000))
        try:
            nearby = self.places.nearby(pt.lat, pt.lon, radius)
        except ToolError:
            return DynamicOutcome("unavailable", place_name=name)
        items = build_places(nearby.pois)
        if len(items) < self.min_places:
            log.info("research for %s found only %d usable places", name, len(items))
            return DynamicOutcome("insufficient", place_name=name)
        return DynamicOutcome("ok", self._assemble(query, name, pt, nearby, items), name)

    def _estimates(self, name: str, pt: GeoPoint, items: list[tuple[Poi, Place]]) -> DestinationEstimates | None:
        if self.llm is None:
            return None
        import json
        payload = {"destination": name, "country": pt.country,
                   "places": [{"id": p.id, "name": p.name, "category": p.note.split(".")[0]} for _, p in items[:40]]}
        try:
            return self.llm.structured(DestinationEstimates, ESTIMATE_SYSTEM, json.dumps(payload, ensure_ascii=False))
        except LLMError:
            log.warning("price estimation unavailable; using the generic baseline")
            return None

    def _assemble(self, query: str, name: str, pt: GeoPoint, nearby: NearbyResult,
                  items: list[tuple[Poi, Place]]) -> Destination:
        areas, assign, how = build_areas(items, nearby.suburbs)
        est_raw = self._estimates(name, pt, items)
        food, stays, transport, per_place = sane_costs(est_raw)
        generic = food is None or stays is None or transport is None
        food = food or GENERIC_FOOD
        stays = stays or GENERIC_STAY
        transport = transport or GENERIC_TRANSPORT

        places: list[Place] = []
        for _, p in items:
            e = per_place.get(p.id)
            updates = {"area": assign[p.id]}
            if e and e.duration_min is not None:
                updates["duration_min"] = e.duration_min
            if e and e.cost_pp is not None:
                updates["cost_pp"] = e.cost_pp
            places.append(p.model_copy(update=updates))

        density: dict[str, int] = {}
        for p in places:
            density[p.area] = density.get(p.area, 0) + 1
        home = max(density, key=lambda k: (density[k], k))
        stay_options = [StayOption(tier=t, area=home, nightly_low=stays[t][0], nightly_high=stays[t][1],
                                   note="Estimate for a double room") for t in TIERS]

        climate, climate_src = [], "Unavailable: couldn't fetch observed weather"
        if self.climate is not None:
            try:
                climate = [Climate(month=m.month, hi=int(round(m.hi)), lo=int(round(m.lo)), rain=rain_class(m.precip_mm))
                           for m in self.climate.monthly_climate(pt.lat, pt.lon)]
                climate_src = "Researched: Open-Meteo observations for each month of last year (one year, not a long-term average)"
            except (ToolError, ValueError):
                climate = []

        notes = ["Costs and timings are estimates, not quotes. Verify before booking."]
        if est_raw and est_raw.notes:
            notes.append("AI-written planning tips (unverified): " + " ".join(n.strip() for n in est_raw.notes))
        cost_src = ("Generic baseline: not specific to this destination" if generic
                    else "Estimated by AI for this destination")
        return Destination(
            id=f"researched_{slug(name)}", name=name, aliases=sorted({norm(query), norm(name)}),
            country=pt.country, lat=pt.lat, lon=pt.lon, peak_months=[], peak_multiplier=1.0, notes=" ".join(notes),
            areas=areas, places=places, travel_minutes=travel_matrix(areas), stay_options=stay_options,
            food_per_person_day=dict(food),
            transport=[Transport(id="cab_day", mode="Local taxi or ride-hailing (full-day estimate)", cost_inr=transport,
                                 unit="per_day_vehicle", capacity=4, note="Estimate")],
            climate=climate, checklist=_checklist(name), source="researched",
            cost_basis="generic" if generic else "estimated",
            provenance={
                "places": "Researched: OpenStreetMap (Overpass), ranked by how well documented each place is",
                "hours": "Researched where OpenStreetMap lists them; otherwise unknown",
                "areas": ("Researched: OpenStreetMap neighbourhoods" if how == "neighbourhoods"
                          else "Estimated: places grouped by location"),
                "travel_times": "Estimated from straight-line distance",
                "visit_lengths": "Estimated by category" + ("" if not per_place else " and AI"),
                "climate": climate_src, "costs": cost_src})
