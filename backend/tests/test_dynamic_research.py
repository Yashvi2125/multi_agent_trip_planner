"""Dynamic research: any destination can be planned, curated data still wins, and every failure degrades honestly."""
import re
from datetime import date
from decimal import Decimal
from types import SimpleNamespace

import httpx
import pytest

from app.agents import dynamic_research as dr
from app.agents.dynamic_research import (DestinationEstimates, PlaceEstimate, StayRange, TierInts, build_areas,
                                         build_places, classify, estimate_minutes, parse_hours, sane_costs, travel_matrix)
from app.core.database import SessionLocal
from app.graph.deps import Deps
from app.models import ItineraryVersion
from app.services import planner_gateway
from app.services.planner_runner import PlannerRunner
from app.tools import places as places_tool
from app.tools.base import ToolError
from app.tools.curated import find_destination
from app.tools.geocode import NominatimProvider
from app.tools.places import OverpassProvider
from app.tools.weather import OpenMeteoProvider
from tests.conftest import GOA, make_user
from tests.dynamic_fakes import (TOKYO_POIS, TOKYO_SUBURBS, FakeClimate, FakeGeo, FakePlaces, ResearchLLM, make_researcher)
from tests.fakes import FakeWeather
from tests.test_bali import World, place_ids_of


def install(monkeypatch, *, geo=None, places=None, climate=None, llm=None, dynamic=True, **kw):
    """Point the real planner at fake providers. dynamic=False models a server with no researcher configured."""
    researcher, geo, places, climate, llm = make_researcher(geo, places, climate, llm, **kw)
    deps = Deps(llm=llm, weather=FakeWeather(), geocoder=geo, today=lambda: date(2026, 10, 1),
                dynamic=researcher if dynamic else None)
    monkeypatch.setattr(planner_gateway, "planner", PlannerRunner(deps))
    return SimpleNamespace(dyn=researcher, geo=geo, places=places, climate=climate, llm=llm)


def versions(w: World) -> int:
    return w.saved_versions()


def estimate_calls(ctx) -> int:
    return sum(1 for name, _ in ctx.llm.calls if name == "DestinationEstimates")


# ---------------------------------------------------------------- 1-4. curated data still wins, research never runs

@pytest.mark.parametrize("destination,dest_id", [("Goa", "goa"), ("Jaipur", "jaipur"), ("Manali", "manali"), ("Bali", "bali")])
def test_curated_destinations_plan_exactly_as_before_and_never_trigger_research(client, monkeypatch, destination, dest_id):
    ctx = install(monkeypatch)
    w = World(client, destination)
    w.ask_for_plan()
    body = w.get("itinerary").json()["itinerary"]
    placed = [i["place_id"] for d in body["days"] for i in d["items"]]
    assert placed and set(placed) <= place_ids_of(dest_id)
    assert versions(w) == 1 and w.get("budget").status_code == 200
    assert ctx.geo.calls == [] and ctx.places.calls == [] and estimate_calls(ctx) == 0      # curated: no research at all


# ---------------------------------------------------------------- 5-6. unknown destination → research → saved plan

def test_unknown_destination_triggers_the_research_path(client, monkeypatch):
    ctx = install(monkeypatch)
    w = World(client, "Tokyo")
    w.ask_for_plan()
    assert ctx.geo.calls == ["Tokyo"] and len(ctx.places.calls) == 1 and ctx.climate.calls == 1
    assert estimate_calls(ctx) == 1


def test_researched_destination_produces_a_saved_plan_with_a_labelled_budget(client, monkeypatch):
    ctx = install(monkeypatch)
    w = World(client, "Tokyo")
    ai = w.ask_for_plan()
    plan = next(t for t in ai if "version 1 of the Tokyo plan" in t)

    body = w.get("itinerary").json()
    days = body["itinerary"]["days"]
    placed = [i["place_id"] for d in days for i in d["items"]]
    researched = {p.id for p in ctx.dyn.cached("Tokyo").places}
    assert body["version"] == 1 and len(days) == 5 and placed
    assert set(placed) <= researched and len(set(placed)) == len(placed)      # only places the map actually returned
    assert versions(w) == 1 and w.trip_row_version() == 1                     # persisted

    b = w.get("budget").json()
    assert Decimal(b["total"]) > 0 and Decimal(b["per_person"]) > 0 and b["status"] in {"within", "tight", "over"}
    assert Decimal(b["by_category"]["accommodation"]) > 0

    assert "researched Tokyo live" in plan and "estimates" in plan            # facts vs estimates, said plainly
    dest = ctx.dyn.cached("Tokyo")
    assert dest.source == "researched" and dest.cost_basis == "estimated"
    assert dest.provenance["places"].startswith("Researched") and dest.provenance["travel_times"].startswith("Estimated")
    assert dest.provenance["costs"].startswith("Estimated by AI")


def test_researched_plan_respects_hours_arrival_and_stays(client, monkeypatch):
    install(monkeypatch)
    w = World(client, "Tokyo")
    w.ask_for_plan()
    it = w.get("itinerary").json()["itinerary"]
    assert it["days"][0]["items"][0]["start"] >= "12:00"
    senso = next((i for d in it["days"] for i in d["items"] if i["name"] == "Senso-ji"), None)
    if senso:                                    # opening hours came from OpenStreetMap's "06:00-17:00"
        assert "06:00" <= senso["start"] and senso["end"] <= "17:00"
    assert it["stay"]["nights"] == 4 and it["stay"]["nightly_per_room"] > 0


def test_second_plan_for_the_same_destination_reuses_the_research(client, monkeypatch):
    ctx = install(monkeypatch)
    w = World(client, "Tokyo")
    w.ask_for_plan()
    assert client.post(f"/api/trips/{w.trip['id']}/regenerate", headers=w.h).status_code == 202   # the button path
    w.ask_for_plan()                                                                              # the @planner path
    assert len(ctx.geo.calls) == 1 and len(ctx.places.calls) == 1 and estimate_calls(ctx) == 1
    assert versions(w) >= 2


@pytest.mark.parametrize("spelling", ["tokyo", "TOKYO", "  Tokyo  "])
def test_free_text_spelling_is_forgiven(client, monkeypatch, spelling):
    install(monkeypatch)
    w = World(client, spelling)
    assert any("of the Tokyo plan" in t for t in w.ask_for_plan())


# ---------------------------------------------------------------- 7-8. not enough research, and the old behaviour

def test_insufficient_research_gives_the_helpful_fallback_and_saves_nothing(client, monkeypatch):
    install(monkeypatch, places=FakePlaces(pois=TOKYO_POIS[:3], suburbs=[]))
    w = World(client, "Smallville")
    ai = w.ask_for_plan()
    assert len(ai) == 1
    assert "I can recognize Smallville, but I couldn't gather enough reliable information" in ai[0]
    assert "add preferences in chat or try another destination" in ai[0]
    assert "Bali, Goa, Jaipur, Manali" in ai[0] and "Settings" in ai[0] and "preferences stay saved" in ai[0]
    assert w.get("itinerary").status_code == 404 and versions(w) == 0 and w.trip_row_version() == 0


def test_an_unrecognised_place_is_told_so_not_called_unsupported(client, monkeypatch):
    install(monkeypatch)
    w = World(client, "Atlantis")
    msg = w.ask_for_plan()[0]
    assert "couldn't find “Atlantis” on the map" in msg and "Check the spelling" in msg
    assert "Bali, Goa, Jaipur, Manali" in msg and "change the trip's destination in Settings" in msg
    assert "don't have detailed data" not in msg and versions(w) == 0


def test_a_whole_country_is_too_broad_to_plan_day_by_day(client, monkeypatch):
    ctx = install(monkeypatch)
    w = World(client, "Japan")
    msg = w.ask_for_plan()[0]
    assert "whole country or large region" in msg and "Pick a city or area inside it" in msg
    assert ctx.places.calls == [] and versions(w) == 0          # we didn't even try to research a country


def test_without_a_researcher_the_original_unsupported_behaviour_is_unchanged(client, monkeypatch):
    install(monkeypatch, dynamic=False)
    w = World(client, "Lisbon")
    msg = w.ask_for_plan()[0]
    assert "I can't research Lisbon on this server yet" in msg and "Bali, Goa, Jaipur, Manali" in msg
    assert "change the trip's destination in Settings" in msg and "preferences stay saved" in msg
    assert w.get("itinerary").status_code == 404 and versions(w) == 0


# ---------------------------------------------------------------- 8b. providers fail: degrade, never crash

@pytest.mark.parametrize("kw", [{"geo": FakeGeo(fail=True)}, {"places": FakePlaces(fail=True)}])
def test_provider_outage_gets_a_calm_message_and_no_crash(client, monkeypatch, kw):
    install(monkeypatch, **kw)
    w = World(client, "Tokyo")
    msg = w.ask_for_plan()[0]
    assert "couldn't reach the map and research services" in msg and "Try again in a few minutes" in msg
    assert versions(w) == 0


def test_outage_is_not_cached_forever(client, monkeypatch):
    places = FakePlaces(fail=True)
    ctx = install(monkeypatch, places=places)
    w = World(client, "Tokyo")
    w.ask_for_plan()
    places.fail = False
    ctx.dyn._not_ok._data.clear()                                # what time does after the short failure memory
    assert any("of the Tokyo plan" in t for t in w.ask_for_plan())


def test_price_estimates_unavailable_falls_back_to_a_generic_labelled_baseline(client, monkeypatch):
    ctx = install(monkeypatch, llm=ResearchLLM(estimates=None))
    w = World(client, "Tokyo")
    plan = next(t for t in w.ask_for_plan() if "version 1" in t)
    assert "rough all-destination average" in plan and "could be far off" in plan
    assert ctx.dyn.cached("Tokyo").cost_basis == "generic"
    assert w.get("budget").status_code == 200 and versions(w) == 1


def test_implausible_ai_prices_are_dropped_not_trusted(client, monkeypatch):
    def nonsense(user):
        return DestinationEstimates(food_per_person_day=TierInts(budget=9000, mid=100, premium=1),
                                    stay_nightly_budget=StayRange(low=5, high=2), stay_nightly_mid=StayRange(low=1, high=2),
                                    stay_nightly_premium=StayRange(low=1, high=2), local_transport_day=99999999)
    ctx = install(monkeypatch, llm=ResearchLLM(estimates=nonsense))
    World(client, "Tokyo").ask_for_plan()
    d = ctx.dyn.cached("Tokyo")
    assert d.cost_basis == "generic" and d.food_per_person_day == dr.GENERIC_FOOD


def test_missing_climate_still_plans_and_says_there_is_no_typical_weather(client, monkeypatch):
    ctx = install(monkeypatch, climate=FakeClimate(fail=True))
    w = World(client, "Tokyo")
    plan = next(t for t in w.ask_for_plan() if "version 1" in t)
    assert not ctx.dyn.cached("Tokyo").has_climate()
    assert "couldn't find typical conditions for Tokyo" in plan and versions(w) == 1


def test_researched_wet_season_note_is_worded_as_last_years_observation(client, monkeypatch):
    install(monkeypatch)
    plan = next(t for t in World(client, "Tokyo").ask_for_plan() if "version 1" in t)
    assert "December was very wet in Tokyo last year" in plan


# ---------------------------------------------------------------- 10 + 12. @planner, preferences and conflicts on researched data

def test_preferences_and_conflicts_work_on_a_researched_destination(client, monkeypatch):
    llm = ResearchLLM(table={
        "I love temples and shrines": {"preferences": [{"category": "interest", "topic": "temples", "weight": 5}]},
        "No temples for me, thanks": {"constraints": [{"type": "must_avoid", "text": "temples"}]}})
    ctx = install(monkeypatch, llm=llm)
    w = World(client, "Tokyo")
    for who, text in ((w.h, "I love temples and shrines"), (w.h2, "No temples for me, thanks")):
        client.post(f"/api/trips/{w.trip['id']}/messages", json={"text": text}, headers=who)
    ai = w.ask_for_plan()
    assert any("has ruled it out completely" in t for t in ai)                     # a conflict was raised, not hidden
    topics = {p.id: p.topics for p in ctx.dyn.cached("Tokyo").places}
    placed = [i["place_id"] for d in w.get("itinerary").json()["itinerary"]["days"] for i in d["items"]]
    assert placed and not any("culture" in topics[p] for p in placed)              # the hard "no" was honoured


def test_a_must_have_by_name_is_planned_on_a_researched_destination(client, monkeypatch):
    llm = ResearchLLM(table={"We absolutely must visit Mount Takao": {"constraints": [{"type": "must_include", "text": "Mount Takao"}]}})
    install(monkeypatch, llm=llm)
    w = World(client, "Tokyo")
    client.post(f"/api/trips/{w.trip['id']}/messages", json={"text": "We absolutely must visit Mount Takao"}, headers=w.h)
    w.ask_for_plan()
    names = [i["name"] for d in w.get("itinerary").json()["itinerary"]["days"] for i in d["items"]]
    assert "Mount Takao" in names


# ---------------------------------------------------------------- weather endpoint: never starts a research run

def test_weather_for_a_researched_trip_does_not_trigger_research_until_planned(client, monkeypatch):
    ctx = install(monkeypatch)
    w = World(client, "Tokyo")
    r = w.get("weather")
    assert r.status_code == 200 and r.json()["supported"] is True
    assert ctx.places.calls == [] and estimate_calls(ctx) == 0 and ctx.geo.calls == ["Tokyo"]     # geocode only
    w.ask_for_plan()
    after = w.get("weather").json()
    assert after["source"] == "climatology" and len(after["days"]) == 5                           # now from observed data


# ---------------------------------------------------------------- /api/destinations/lookup

def lookup(client, h, q):
    return client.get("/api/destinations/lookup", params={"q": q}, headers=h)


def test_lookup_reports_what_will_happen_without_blocking_anything(client, monkeypatch):
    install(monkeypatch)
    h, *_ = make_user(client)
    assert lookup(client, h, "Goa").json() == {"query": "Goa", "status": "curated", "name": "Goa", "country": "India"}
    assert lookup(client, h, "Tokyo").json() == {"query": "Tokyo", "status": "found", "name": "Tokyo", "country": "Japan"}
    assert lookup(client, h, "Atlantis").json()["status"] == "not_found"
    assert lookup(client, h, "Japan").json()["status"] == "too_broad"
    assert client.get("/api/destinations/lookup", params={"q": "T"}, headers=h).status_code == 422
    assert client.get("/api/destinations/lookup", params={"q": "Tokyo"}).status_code == 401


def test_lookup_degrades_when_the_map_is_down_or_research_is_off(client, monkeypatch):
    h, *_ = make_user(client)
    install(monkeypatch, geo=FakeGeo(fail=True))
    assert lookup(client, h, "Tokyo").json()["status"] == "unavailable"
    install(monkeypatch, dynamic=False)
    assert lookup(client, h, "Tokyo").json()["status"] == "unchecked"


def test_destinations_endpoint_is_only_a_suggestion_list_and_trips_need_no_curated_data(client):
    h, *_ = make_user(client)
    names = {d["name"] for d in client.get("/api/destinations").json()}
    r = client.post("/api/trips", json={**GOA, "name": "Tokyo", "destination": "Tokyo"}, headers=h)
    assert "Tokyo" not in names and r.status_code == 201 and r.json()["code"].startswith("TOK-")


# ---------------------------------------------------------------- pure pieces

def test_hours_are_read_only_when_clear():
    assert parse_hours("06:00-17:00") == ("06:00", "17:00")
    assert parse_hours("Mo-Fr 10:00-18:00; Sa,Su 10:00-20:00") == ("10:00", "20:00")
    assert parse_hours("18:00-02:00") == ("18:00", "23:59")          # past midnight
    for unclear in (None, "", "24/7", "by appointment", "sunrise-sunset", "25:00-26:00", "10:00-10:30"):
        assert parse_hours(unclear) == (None, None), unclear         # unknown stays unknown, never guessed


def test_osm_tags_map_to_the_planners_topics_and_unrelated_things_are_ignored():
    assert classify({"amenity": "nightclub"})[1] == "nightlife"
    assert classify({"tourism": "museum"})[0] == ["culture"] and classify({"natural": "beach"})[0][0] == "beaches"
    assert classify({"shop": "bakery"}) is None and classify({"name": "x"}) is None
    from app.services.topics import CANONICAL
    for tags in ({"tourism": "zoo"}, {"leisure": "park"}, {"amenity": "marketplace"}, {"natural": "peak"}):
        assert set(classify(tags)[0]) <= set(CANONICAL)


def test_places_get_safe_unique_ids_and_hours_notes():
    built = [p for _, p in build_places(TOKYO_POIS)]
    assert len(built) == 14 and len({p.id for p in built}) == 14
    assert all(re.fullmatch(r"[a-z0-9_]+", p.id) for p in built)
    senso = next(p for p in built if p.name == "Senso-ji")
    assert (senso.opens, senso.closes) == ("06:00", "17:00") and "from OpenStreetMap" in senso.note
    assert "unknown" in next(p for p in built if p.name == "Meiji Shrine").note


def test_areas_come_from_real_neighbourhoods_or_fall_back_to_clusters():
    items = build_places(TOKYO_POIS)
    areas, assign, how = build_areas(items, TOKYO_SUBURBS)
    assert how == "neighbourhoods" and 2 <= len(areas) <= dr.MAX_AREAS
    assert set(assign.values()) == {a.id for a in areas} and {a.name for a in areas} <= {s.name for s in TOKYO_SUBURBS}
    areas2, assign2, how2 = build_areas(items, [])
    assert how2 == "clusters" and all(a.name.startswith("Around ") for a in areas2) and len(assign2) == 14


def test_travel_times_cover_every_pair_and_grow_with_distance():
    researcher, *_ = make_researcher()
    d = researcher.research("Tokyo").destination
    for a in d.areas:
        for b in d.areas:
            assert d.minutes_between(a.id, b.id) >= 10
    assert estimate_minutes(1) < estimate_minutes(10) < estimate_minutes(60) < estimate_minutes(300)
    assert all(m % 5 == 0 for _, _, m in travel_matrix(d.areas) if m != 15)


def test_cost_sanity_rules():
    from tests.dynamic_fakes import good_estimates
    import json
    ok = good_estimates(json.dumps({"places": [{"id": "a"}]}))
    food, stays, transport, per_place = sane_costs(ok)
    assert food["mid"] == 3500 and stays["mid"] == (8000, 14000) and transport == 6000 and "a" in per_place
    assert sane_costs(None) == (None, None, None, {})
    bad = ok.model_copy(update={"places": [PlaceEstimate(id="x", duration_min=5000, cost_pp=-3)]})
    assert sane_costs(bad)[3] == {}                                   # implausible per-place numbers are discarded


# ---------------------------------------------------------------- real providers, mocked HTTP

OVERPASS = {"elements": [
    {"type": "node", "id": 1, "lat": 35.71, "lon": 139.79, "tags": {"name": "Senso-ji", "historic": "temple", "wikidata": "Q1"}},
    {"type": "way", "id": 2, "center": {"lat": 35.72, "lon": 139.77}, "tags": {"name": "Ueno Park", "leisure": "park", "wikidata": "Q4", "name:en": "Ueno Park"}},
    {"type": "node", "id": 3, "lat": 35.71, "lon": 139.79, "tags": {"name": "senso-ji", "historic": "temple"}},       # duplicate, less documented
    {"type": "node", "id": 4, "lat": 35.0, "lon": 139.0, "tags": {"historic": "ruins"}},                              # no name
    {"type": "node", "id": 5, "tags": {"name": "No Coordinates", "tourism": "museum"}},
    {"type": "node", "id": 6, "lat": 35.71, "lon": 139.79, "tags": {"name": "Asakusa", "place": "suburb"}},
]}


def test_overpass_parsing_keeps_real_named_places_only():
    r = places_tool.parse(OVERPASS)
    assert [p.name for p in r.pois] == ["Senso-ji", "Ueno Park"]            # nameless, coordinate-less and duplicate dropped
    assert [s.name for s in r.suburbs] == ["Asakusa"]
    assert next(p for p in r.pois if p.name == "Ueno Park").lat == 35.72      # centre used for areas/ways


def test_overpass_asks_for_notable_places_first_and_widens_only_for_small_places():
    seen = []

    def handler(req: httpx.Request):
        seen.append(req.content.decode())
        return httpx.Response(200, json=OVERPASS)                       # only 2 places: a "small town"

    p = OverpassProvider(transport=httpx.MockTransport(handler))
    assert len(p.nearby(35.6764, 139.65, 15000).pois) == 2 and p.nearby(35.6764, 139.65, 15000)
    assert len(seen) == 2                                              # notable first, then widened; the repeat was cached
    assert ("around%3A15000" in seen[0]) or ("around:15000" in seen[0])    # the search radius is bounded
    assert seen[0].count("wikidata") > seen[1].count("wikidata")          # the second query dropped the notability filter


def test_overpass_does_not_widen_when_there_are_enough_notable_places():
    many = {"elements": [{"type": "node", "id": i, "lat": 35.0 + i / 1000, "lon": 139.0,
                          "tags": {"name": f"Landmark {i}", "tourism": "attraction", "wikidata": f"Q{i}"}} for i in range(20)]}
    seen = []
    p = OverpassProvider(transport=httpx.MockTransport(lambda r: (seen.append(1), httpx.Response(200, json=many))[1]))
    assert len(p.nearby(35.0, 139.0, 10000).pois) == 20 and len(seen) == 1


def test_overpass_failures_become_tool_errors():
    for resp in (httpx.Response(504), httpx.Response(200, text="<html>busy</html>")):
        with pytest.raises(ToolError):
            OverpassProvider(transport=httpx.MockTransport(lambda r, resp=resp: resp)).nearby(1, 1, 5000)


def test_open_meteo_archive_becomes_twelve_months_of_observed_climate():
    year = date.today().year - 1
    days = [date.fromordinal(date(year, 1, 1).toordinal() + i) for i in range(365)]
    payload = {"daily": {"time": [d.isoformat() for d in days], "temperature_2m_max": [30.0] * 365,
                         "temperature_2m_min": [20.0] * 365, "precipitation_sum": [5.0] * 365}}
    p = OpenMeteoProvider(transport=httpx.MockTransport(lambda r: httpx.Response(200, json=payload)))
    months = p.monthly_climate(35.7, 139.7)
    assert [m.month for m in months] == list(range(1, 13)) and months[0].hi == 30.0 and months[0].precip_mm == 155.0
    short = {"daily": {k: v[:100] for k, v in payload["daily"].items()}}
    with pytest.raises(ToolError):
        OpenMeteoProvider(transport=httpx.MockTransport(lambda r: httpx.Response(200, json=short))).monthly_climate(1, 1)


def test_nominatim_now_reports_country_and_how_big_the_place_is():
    row = {"lat": "35.68", "lon": "139.76", "display_name": "Tokyo, Japan", "addresstype": "city",
           "boundingbox": ["35.5", "35.8", "139.4", "139.9"], "address": {"country": "Japan", "country_code": "jp"}}
    g = NominatimProvider(transport=httpx.MockTransport(lambda r: httpx.Response(200, json=[row])))
    pt = g.geocode("Tokyo")
    assert pt.country == "Japan" and pt.kind == "city" and 40 < pt.extent_km < 90
    bare = NominatimProvider(transport=httpx.MockTransport(lambda r: httpx.Response(200, json=[{"lat": "1", "lon": "2"}])))
    assert bare.geocode("Somewhere").extent_km is None                 # missing fields tolerated


def test_curated_lookup_is_unchanged_by_the_new_fields():
    d = find_destination("Goa")
    assert d.source == "curated" and d.cost_basis == "curated" and d.has_climate() and d.provenance == {}


# ---------------------------------------------------------------- 11. Telegram planning on a researched destination

from tests.test_telegram import GROUP, bot, post, update, wait_for, web_trip  # noqa: E402,F401  (reuse the Telegram harness)


def test_telegram_planning_works_for_a_researched_destination(client, bot, monkeypatch):
    install(monkeypatch)
    h, u, tok, t = web_trip(client, body={**GOA, "name": "Tokyo trip", "destination": "Tokyo"})
    post(client, update(f"/join {t['code']}", user=7, name="Priya Shah"))
    post(client, update("@WayfareBot make the itinerary", user=7, name="Priya Shah"))
    assert wait_for(lambda: any("version 1 of the Tokyo plan" in x for x in bot.texts(GROUP)))
    assert client.get(f"/api/trips/{t['id']}/itinerary", headers=h).json()["itinerary"]["destination"] == "Tokyo"
    post(client, update("/itinerary", user=7, name="Priya Shah"))
    post(client, update("/budget", user=7, name="Priya Shah"))
    assert wait_for(lambda: sum("Tokyo" in x for x in bot.texts(GROUP)) >= 2)
    assert wait_for(lambda: any("₹" in x for x in bot.texts(GROUP)[-3:]))        # /budget answered from the estimate
