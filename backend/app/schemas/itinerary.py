"""Itinerary documents.

Two families, deliberately separate:
  * Draft*  – what the LLM is allowed to produce: *choices* (place ids, order, a reason). Never times or prices.
  * Itinerary* – the real plan: every fact (times, travel, costs) is filled in by code from curated data.
"""
import datetime as dt
import re

from pydantic import BaseModel, Field, field_validator

_HHMM = re.compile(r"^\d{1,2}:\d{2}$")


# ---------------------------------------------------------------- the real plan

class StayChoice(BaseModel):
    tier: str                     # budget | mid | premium
    area: str
    area_name: str = ""
    nightly_per_room: int
    rooms: int
    nights: int
    why: str = ""


class ItineraryItem(BaseModel):
    place_id: str
    name: str
    kind: str = "sight"
    area: str = ""
    start: str                    # "HH:MM"
    end: str
    duration_min: int = 0
    cost_pp: int = 0
    travel_min_from_prev: int = 0
    why: str = ""
    serves: list[str] = Field(default_factory=list)   # first names of members this stop is for
    optional: bool = False        # e.g. someone can't make that day
    lat: float | None = None
    lon: float | None = None


class ItineraryDay(BaseModel):
    index: int                    # 1-based
    date: dt.date | None = None
    title: str = ""
    note: str = ""
    items: list[ItineraryItem] = Field(default_factory=list)


class Itinerary(BaseModel):
    destination: str
    days: list[ItineraryDay]
    stay: StayChoice | None = None
    food_tier: str = "mid"
    transport_id: str | None = None
    used_fallback: bool = False   # True when the rule-based planner built it (no/invalid LLM output)
    summary: str = ""

    def place_ids(self) -> list[str]:
        return [i.place_id for d in self.days for i in d.items]


# ---------------------------------------------------------------- what the LLM may produce

class DraftItem(BaseModel):
    place_id: str
    why: str = Field(default="", max_length=300)
    start_time: str | None = None  # a hint only; the scheduler has the final say

    @field_validator("start_time")
    @classmethod
    def lenient_time(cls, v: str | None) -> str | None:
        return v if v and _HHMM.match(v.strip()) else None


class DraftDay(BaseModel):
    title: str = Field(default="", max_length=80)
    items: list[DraftItem] = Field(default_factory=list)


class ItineraryDraft(BaseModel):
    days: list[DraftDay]
    stay_tier: str = "mid"
    food_tier: str = "mid"
    transport_id: str | None = None


class Answer(BaseModel):
    text: str
