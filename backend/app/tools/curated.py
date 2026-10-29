"""Typed access to curated destination data. This is the reliable backbone: it works offline,
and every place the Itinerary Agent may use must come from here (or a verified live source)."""
import json
import re
from datetime import date
from functools import lru_cache
from pathlib import Path

from pydantic import BaseModel, Field

DATA_DIR = Path(__file__).resolve().parent.parent / "data" / "curated"


class Area(BaseModel):
    id: str
    name: str
    lat: float
    lon: float


class Place(BaseModel):
    id: str
    name: str
    area: str
    lat: float
    lon: float
    topics: list[str]
    kind: str  # sight | activity | food | market | nightlife
    duration_min: int
    cost_pp: int
    opens: str | None = None
    closes: str | None = None
    only_days: list[int] = Field(default_factory=list)   # Monday=0; empty = any day
    closed_months: list[int] = Field(default_factory=list)
    note: str = ""


class StayOption(BaseModel):
    tier: str
    area: str
    nightly_low: int
    nightly_high: int
    note: str = ""


class Transport(BaseModel):
    id: str
    mode: str
    cost_inr: int
    unit: str  # per_day_vehicle | per_trip_vehicle
    capacity: int
    note: str = ""


class Climate(BaseModel):
    month: int
    hi: int
    lo: int
    rain: str  # low | moderate | heavy


class ChecklistTemplate(BaseModel):
    label: str
    category: str


class Destination(BaseModel):
    id: str
    name: str
    aliases: list[str]
    country: str
    lat: float
    lon: float
    peak_months: list[int]
    peak_multiplier: float
    notes: str
    areas: list[Area]
    places: list[Place]
    travel_minutes: list[tuple[str, str, int]]
    stay_options: list[StayOption]
    food_per_person_day: dict[str, int]
    transport: list[Transport]
    climate: list[Climate]
    checklist: list[ChecklistTemplate]
    source: str = "curated"        # curated | researched
    cost_basis: str = "curated"    # curated | estimated | generic
    provenance: dict[str, str] = Field(default_factory=dict)   # which facts were researched vs estimated

    def has_climate(self) -> bool:
        return len(self.climate) == 12

    @classmethod
    def stub(cls, name: str, lat: float, lon: float) -> "Destination":
        """A bare location (no places or costs): enough for a weather forecast, nothing more."""
        return cls(id=f"stub-{name.lower()}", name=name, aliases=[], country="", lat=lat, lon=lon, peak_months=[],
                   peak_multiplier=1.0, notes="", areas=[], places=[], travel_minutes=[], stay_options=[],
                   food_per_person_day={}, transport=[], climate=[], checklist=[], source="researched")

    def place(self, place_id: str) -> Place | None:
        return next((p for p in self.places if p.id == place_id), None)

    def minutes_between(self, a: str, b: str) -> int:
        for x, y, m in self.travel_minutes:
            if (x, y) in ((a, b), (b, a)):
                return m
        raise KeyError(f"No travel time for {a} ↔ {b}")

    def climate_for(self, month: int) -> Climate:
        return next(c for c in self.climate if c.month == month)

    def is_peak(self, month: int) -> bool:
        return month in self.peak_months


def place_open_on(p: Place, day: date) -> bool:
    if day.month in p.closed_months:
        return False
    return not p.only_days or day.weekday() in p.only_days


def _norm(s: str) -> str:
    return re.sub(r"[^a-z ]", "", s.lower()).strip()


@lru_cache
def _all() -> dict[str, Destination]:
    return {d.id: d for d in (Destination.model_validate(json.loads(f.read_text(encoding="utf-8")))
                              for f in sorted(DATA_DIR.glob("*.json")))}


def supported_destinations() -> list[str]:
    return [d.name for d in _all().values()]


def find_destination(name: str) -> Destination | None:
    n = _norm(name)
    if not n:
        return None
    for d in _all().values():
        if n in d.aliases or any(a in n.split() or a == n for a in d.aliases):
            return d
    return None
