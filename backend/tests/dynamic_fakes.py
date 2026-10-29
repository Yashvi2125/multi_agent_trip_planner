"""Fake providers shaped like the real ones (OpenStreetMap tags, Nominatim boxes, Open-Meteo months).
Shared by the backend tests and the frontend end-to-end server, so no test touches the network."""
import json

from app.agents.dynamic_research import (DestinationEstimates, DynamicResearcher, PlaceEstimate, StayRange, TierInts)
from app.agents.llm import LLMError
from app.tools.base import GeoPoint, MonthClimate, NearbyResult, Poi, Suburb, ToolError
from tests.fakes import FakeLLM

TOKYO = GeoPoint(35.6764, 139.6500, "Tokyo, Japan", "city", "Japan", "jp", 60.0)
SMALLVILLE = GeoPoint(40.0, -100.0, "Smallville, Nowhere", "town", "Nowhere", "nw", 8.0)
JAPAN = GeoPoint(36.2, 138.2, "Japan", "country", "Japan", "jp", 2900.0)
GEO = {"tokyo": TOKYO, "smallville": SMALLVILLE, "japan": JAPAN}


def poi(i: int, name: str, lat: float, lon: float, **tags) -> Poi:
    return Poi(f"node/{1000 + i}", name, lat, lon, tags, score=float(20 - i))


TOKYO_POIS = [
    poi(0, "Senso-ji", 35.7148, 139.7967, historic="temple", wikidata="Q1", opening_hours="06:00-17:00"),
    poi(1, "Meiji Shrine", 35.6764, 139.6993, historic="shrine", wikidata="Q2"),
    poi(2, "Tokyo Skytree", 35.7101, 139.8107, tourism="attraction", wikidata="Q3"),
    poi(3, "Ueno Park", 35.7156, 139.7745, leisure="park", wikidata="Q4"),
    poi(4, "Tokyo National Museum", 35.7188, 139.7765, tourism="museum", opening_hours="Tu-Su 09:30-17:00"),
    poi(5, "Shibuya Crossing", 35.6595, 139.7005, tourism="attraction"),
    poi(6, "Odaiba Seaside Park", 35.6299, 139.7752, natural="beach"),
    poi(7, "Tsukiji Outer Market", 35.6655, 139.7707, amenity="marketplace", wikidata="Q8"),
    poi(8, "teamLab Planets", 35.6490, 139.7897, tourism="gallery"),
    poi(9, "Imperial Palace East Gardens", 35.6852, 139.7528, historic="palace"),
    poi(10, "Shinjuku Gyoen", 35.6852, 139.7101, leisure="garden"),
    poi(11, "Roppongi nightclub", 35.6628, 139.7314, amenity="nightclub"),
    poi(12, "Tokyo Tower", 35.6586, 139.7454, tourism="attraction"),
    poi(13, "Mount Takao", 35.6253, 139.2437, natural="peak"),
]
TOKYO_SUBURBS = [Suburb("Asakusa", 35.7148, 139.7967), Suburb("Ueno", 35.7141, 139.7774),
                 Suburb("Shibuya", 35.6580, 139.7016), Suburb("Shinjuku", 35.6938, 139.7034),
                 Suburb("Odaiba", 35.6272, 139.7760), Suburb("Minato", 35.6586, 139.7454)]


class FakeGeo:
    def __init__(self, fail: bool = False):
        self.fail, self.calls = fail, []

    def geocode(self, q: str):
        self.calls.append(q)
        if self.fail:
            raise ToolError("geocoder down")
        return GEO.get(q.strip().lower())


class FakePlaces:
    def __init__(self, pois=None, suburbs=None, fail: bool = False):
        self.pois = TOKYO_POIS if pois is None else pois
        self.suburbs = TOKYO_SUBURBS if suburbs is None else suburbs
        self.fail, self.calls = fail, []

    def nearby(self, lat, lon, radius_m):
        self.calls.append((lat, lon, radius_m))
        if self.fail:
            raise ToolError("overpass down")
        return NearbyResult(list(self.pois), list(self.suburbs))


class LocationAwarePlaces(FakePlaces):
    """Tokyo gets a rich result; a tiny town (lat ~40) gets almost nothing: 'recognised but not enough data'."""

    def nearby(self, lat, lon, radius_m):
        self.pois = TOKYO_POIS[:3] if abs(lat - 40.0) < 1 else TOKYO_POIS
        return super().nearby(lat, lon, radius_m)


class FakeClimate:
    def __init__(self, fail: bool = False):
        self.fail, self.calls = fail, 0

    def monthly_climate(self, lat, lon):
        self.calls += 1
        if self.fail:
            raise ToolError("archive down")
        return [MonthClimate(m, 20.0 + m, 10.0 + m, m * 20.0) for m in range(1, 13)]    # December: 240 mm → heavy


def good_estimates(user: str) -> DestinationEstimates:
    ids = [p["id"] for p in json.loads(user)["places"]]
    return DestinationEstimates(
        food_per_person_day=TierInts(budget=1500, mid=3500, premium=8000),
        stay_nightly_budget=StayRange(low=3000, high=5500), stay_nightly_mid=StayRange(low=8000, high=14000),
        stay_nightly_premium=StayRange(low=25000, high=60000), local_transport_day=6000,
        places=[PlaceEstimate(id=i, duration_min=90, cost_pp=500) for i in ids], notes=["An IC card makes trains easy."])


class ResearchLLM(FakeLLM):
    """Answers the price-estimate request. estimates: 'ok' | None (model down) | callable(user) → object."""

    def __init__(self, table=None, estimates="ok"):
        super().__init__(table or {})
        self.estimates = estimates

    def structured(self, schema, system, user):
        if schema is DestinationEstimates:
            self.calls.append((schema.__name__, user))
            if self.estimates is None:
                raise LLMError("down")
            return good_estimates(user) if self.estimates == "ok" else self.estimates(user)
        return super().structured(schema, system, user)


def make_researcher(geo=None, places=None, climate=None, llm=None, **kw):
    geo, places, climate, llm = geo or FakeGeo(), places or FakePlaces(), climate or FakeClimate(), llm or ResearchLLM()
    return DynamicResearcher(geo, places, climate, llm, **kw), geo, places, climate, llm
