import math
import time
from dataclasses import dataclass, field
from datetime import date
from typing import Callable, Protocol

import httpx

from app.core.config import get_settings

USER_AGENT = "Wayfare-college-project/0.1 (contact: set-in-env)"


class ToolError(Exception):
    """An external tool failed. Callers degrade gracefully instead of crashing the plan."""


@dataclass(frozen=True)
class GeoPoint:
    lat: float
    lon: float
    label: str
    kind: str = ""                 # what the map says it is (city, island, country…); informational
    country: str = ""
    country_code: str = ""
    extent_km: float | None = None  # diagonal of its bounding box; used to spot "a whole country"


def haversine_km(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    p1, p2 = math.radians(lat1), math.radians(lat2)
    a = math.sin((p2 - p1) / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(math.radians(lon2 - lon1) / 2) ** 2
    return 6371.0 * 2 * math.asin(math.sqrt(a))


@dataclass(frozen=True)
class Poi:
    """A real place from a map database. `tags` are the raw source tags; nothing here is invented."""
    osm_id: str
    name: str
    lat: float
    lon: float
    tags: dict = field(default_factory=dict, hash=False, compare=False)
    score: float = 0.0             # how well documented/notable it is (a ranking signal, not a rating)


@dataclass(frozen=True)
class Suburb:
    name: str
    lat: float
    lon: float


@dataclass
class NearbyResult:
    pois: list[Poi] = field(default_factory=list)
    suburbs: list[Suburb] = field(default_factory=list)


@dataclass(frozen=True)
class MonthClimate:
    month: int
    hi: float
    lo: float
    precip_mm: float


@dataclass(frozen=True)
class WeatherDay:
    day: date
    summary: str
    temp_max: float
    temp_min: float
    rain_chance: int | None  # percent


class WeatherProvider(Protocol):
    def forecast(self, lat: float, lon: float, start: date, end: date) -> list[WeatherDay]: ...


class GeocodeProvider(Protocol):
    def geocode(self, query: str) -> GeoPoint | None: ...


class PlacesProvider(Protocol):
    def nearby(self, lat: float, lon: float, radius_m: int) -> NearbyResult: ...


class ClimateProvider(Protocol):
    def monthly_climate(self, lat: float, lon: float) -> list[MonthClimate]: ...


def http_client(transport: httpx.BaseTransport | None = None, timeout: float | None = None) -> httpx.Client:
    return httpx.Client(timeout=timeout or get_settings().tool_timeout_seconds, transport=transport,
                        headers={"User-Agent": USER_AGENT})


class TTLCache:
    """Tiny in-memory cache so repeated plan runs don't hammer free APIs."""

    def __init__(self, ttl_seconds: float, clock: Callable[[], float] = time.monotonic):
        self.ttl, self.clock, self._data = ttl_seconds, clock, {}

    def get(self, key):
        hit = self._data.get(key)
        if hit and self.clock() - hit[0] < self.ttl:
            return hit[1]
        self._data.pop(key, None)
        return None

    def set(self, key, value):
        self._data[key] = (self.clock(), value)
