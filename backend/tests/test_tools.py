import json
from datetime import date

import httpx
import pytest

from app.agents.research import research
from app.tools import curated
from app.tools.base import GeoPoint, ToolError, TTLCache, WeatherDay
from app.tools.geocode import NominatimProvider
from app.tools.weather import OpenMeteoProvider, within_forecast_range
from app.services.topics import CANONICAL

TODAY = date(2026, 10, 1)
DEST_IDS = ["goa", "jaipur", "manali", "bali"]


# ---------- curated data integrity ----------

@pytest.mark.parametrize("did", DEST_IDS)
def test_curated_data_is_internally_consistent(did):
    d = curated._all()[did]
    area_ids = {a.id for a in d.areas}
    assert len(d.places) >= 10
    assert len({p.id for p in d.places}) == len(d.places)
    for p in d.places:
        assert p.area in area_ids, p.id
        assert set(p.topics) <= set(CANONICAL), (p.id, p.topics)
        assert p.duration_min > 0 and p.cost_pp >= 0
        assert (p.opens is None) == (p.closes is None), p.id
        if p.opens:
            assert p.opens < p.closes, p.id
        assert all(0 <= x <= 6 for x in p.only_days) and all(1 <= m <= 12 for m in p.closed_months)
        assert abs(p.lat - d.lat) < 1.0 and abs(p.lon - d.lon) < 1.0, f"{p.id} is far from {d.name}"
    for a in area_ids:                           # every pair of areas has a travel time
        for b in area_ids:
            assert d.minutes_between(a, b) > 0
    assert sorted(c.month for c in d.climate) == list(range(1, 13))
    assert all(c.hi > c.lo for c in d.climate)
    assert {"budget", "mid", "premium"} <= set(d.food_per_person_day)
    assert {"budget", "mid"} <= {s.tier for s in d.stay_options}   # stays: at least budget and mid per destination
    assert all(s.nightly_low < s.nightly_high and s.area in area_ids for s in d.stay_options)
    assert d.checklist and d.transport


def test_every_destination_covers_a_range_of_topics():
    for d in curated._all().values():
        covered = {t for p in d.places for t in p.topics}
        assert {"culture", "food"} <= covered, d.name
        assert len(covered) >= 5, d.name


def test_destination_lookup_by_alias():
    assert curated.find_destination("North Goa").id == "goa"
    assert curated.find_destination("  JAIPUR ").id == "jaipur"
    assert curated.find_destination("Himachal Pradesh").id == "manali"
    assert curated.find_destination("Pune") is None and curated.find_destination("") is None


def test_seasonal_and_weekday_rules():
    goa = curated.find_destination("goa")
    falls, flea = goa.place("dudhsagar"), goa.place("anjuna_flea")
    assert curated.place_open_on(falls, date(2026, 12, 12)) and not curated.place_open_on(falls, date(2026, 7, 12))
    assert curated.place_open_on(flea, date(2026, 12, 9)) and not curated.place_open_on(flea, date(2026, 12, 10))  # Wed only


# ---------- providers (mocked HTTP, no network) ----------

def meteo_payload(n=2):
    return {"daily": {"time": [f"2026-10-0{i + 5}" for i in range(n)], "weather_code": [0, 63][:n],
                      "temperature_2m_max": [33.1, 30.0][:n], "temperature_2m_min": [24.0, 23.5][:n],
                      "precipitation_probability_max": [5, 80][:n]}}


def test_open_meteo_parses_and_caches():
    calls = []

    def h(req):
        calls.append(req.url.params)
        return httpx.Response(200, json=meteo_payload())

    p = OpenMeteoProvider(transport=httpx.MockTransport(h))
    days = p.forecast(15.5, 73.8, date(2026, 10, 5), date(2026, 10, 6))
    assert [d.summary for d in days] == ["Clear", "Rain"] and days[1].rain_chance == 80
    assert calls[0]["start_date"] == "2026-10-05" and "weather_code" in calls[0]["daily"]
    p.forecast(15.5, 73.8, date(2026, 10, 5), date(2026, 10, 6))
    assert len(calls) == 1                                   # second call served from cache


@pytest.mark.parametrize("resp", [
    httpx.Response(400, json={"reason": "out of range"}),
    httpx.Response(200, json={"nope": 1}),
    httpx.Response(200, text="<html>"),
])
def test_open_meteo_failures_raise_tool_error(resp):
    p = OpenMeteoProvider(transport=httpx.MockTransport(lambda r: resp))
    with pytest.raises(ToolError):
        p.forecast(1, 1, date(2026, 10, 5), date(2026, 10, 6))


def test_open_meteo_network_error():
    def boom(req):
        raise httpx.ConnectError("offline")
    with pytest.raises(ToolError):
        OpenMeteoProvider(transport=httpx.MockTransport(boom)).forecast(1, 1, TODAY, TODAY)


def test_forecast_horizon():
    assert within_forecast_range(date(2026, 10, 5), date(2026, 10, 9), TODAY)
    assert not within_forecast_range(date(2026, 12, 10), date(2026, 12, 14), TODAY)
    assert not within_forecast_range(date(2026, 9, 28), date(2026, 10, 2), TODAY)  # already started


def test_nominatim_parses_sends_user_agent_and_caches_misses():
    seen = []

    def h(req):
        seen.append(req)
        return httpx.Response(200, json=[{"lat": "15.49", "lon": "73.83", "display_name": "Panaji, Goa, India"}]
                              if "Panaji" in str(req.url) else [])

    g = NominatimProvider(transport=httpx.MockTransport(h))
    pt = g.geocode("Panaji")
    assert (pt.lat, pt.lon) == (15.49, 73.83) and "Wayfare" in seen[0].headers["user-agent"]
    assert g.geocode("Nowhereville") is None and g.geocode("Nowhereville") is None
    assert len(seen) == 2                                    # miss cached too
    assert g.geocode("   ") is None and len(seen) == 2


def test_nominatim_error():
    g = NominatimProvider(transport=httpx.MockTransport(lambda r: httpx.Response(503)))
    with pytest.raises(ToolError):
        g.geocode("Goa")


def test_ttl_cache_expires():
    t = [0.0]
    c = TTLCache(10, clock=lambda: t[0])
    c.set("k", 1)
    assert c.get("k") == 1
    t[0] = 11
    assert c.get("k") is None


# ---------- research agent ----------

class FakeWeather:
    def __init__(self, fail=False):
        self.fail, self.calls = fail, 0

    def forecast(self, lat, lon, start, end):
        self.calls += 1
        if self.fail:
            raise ToolError("down")
        return [WeatherDay(start, "Clear", 32, 22, 5)]


class FakeGeo:
    def geocode(self, q):
        return GeoPoint(18.5, 73.8, "Pune, Maharashtra, India")


def test_december_goa_uses_climatology_and_flags_peak():
    w = FakeWeather()
    b = research("Goa", date(2026, 12, 10), date(2026, 12, 14), w, today=TODAY)
    assert b.supported and b.weather_source == "climatology" and w.calls == 0
    assert len(b.weather) == 5 and not b.degraded
    assert any("too far out" in n for n in b.notes) and any("peak season" in n for n in b.notes)
    assert "dudhsagar" in {p.id for p in b.places}


def test_near_trip_uses_live_forecast():
    b = research("Goa", date(2026, 10, 5), date(2026, 10, 6), FakeWeather(), today=TODAY)
    assert b.weather_source == "live" and not b.degraded


def test_weather_failure_degrades_with_honest_note():
    b = research("Goa", date(2026, 10, 5), date(2026, 10, 7), FakeWeather(fail=True), today=TODAY)
    assert b.degraded and b.weather_source == "climatology" and len(b.weather) == 3
    assert any("couldn't reach the weather service" in n for n in b.notes)


def test_monsoon_trip_excludes_closed_places_with_reasons():
    b = research("Goa", date(2026, 7, 10), date(2026, 7, 13), FakeWeather(), today=TODAY)
    assert {"dudhsagar", "water_sports"} <= {e.place.id for e in b.excluded}
    assert "dudhsagar" not in {p.id for p in b.places}
    assert any("monsoon" in n for n in b.notes)


def test_manali_winter_excludes_rohtang():
    b = research("Manali", date(2026, 12, 20), date(2026, 12, 23), FakeWeather(), today=TODAY)
    assert "rohtang_pass" in {e.place.id for e in b.excluded}


def test_unsupported_destination_is_clear_not_a_crash():
    b = research("Pune", date(2026, 12, 1), date(2026, 12, 3), FakeWeather(), FakeGeo(), today=TODAY)
    assert not b.supported and b.degraded and not b.places
    assert "Goa, Jaipur, Manali" in b.notes[0] and "found it on the map" in b.notes[1]


def test_missing_dates_still_returns_places():
    b = research("Jaipur", None, None, FakeWeather(), today=TODAY)
    assert b.supported and len(b.places) == 14 and b.weather == []
    assert any("dates aren't set" in n for n in b.notes)
