from datetime import date
from decimal import Decimal

import pytest

from app.agents.itinerary import cost_lines, heuristic_draft, is_avoided, materialize, plan_itinerary
from app.agents.profile import GroupProfile
from app.agents.research import research
from app.agents.router import classify
from app.agents.validator import validate
from app.schemas.itinerary import DraftDay, DraftItem, ItineraryDraft
from app.services.budget_calc import compute_budget
from app.services.itinerary_service import diff_summary
from tests.fakes import FakeLLM, FakeWeather

TODAY = date(2026, 10, 1)
DEC = (date(2026, 12, 10), date(2026, 12, 14))


def bundle(dest="Goa", span=DEC):
    return research(dest, span[0], span[1], FakeWeather(), today=TODAY)


def profile(**kw):
    p = GroupProfile(members={1: "Rahul", 2: "Priya", 3: "Aman", 4: "Neha"})
    for k, v in kw.items():
        setattr(p, k, v)
    return p


def ids(it):
    return [i.place_id for d in it.days for i in d.items]


# ---------- grounding & scheduling ----------

def test_hallucinated_places_are_dropped_not_planned():
    draft = ItineraryDraft(days=[DraftDay(title="Day", items=[DraftItem(place_id="fort_aguada"),
                                                              DraftItem(place_id="eiffel_tower")])] * 1)
    it, dropped = materialize(draft, bundle(), profile(), DEC[0], 5)
    assert ids(it) == ["fort_aguada"] and any("eiffel_tower" in d for d in dropped)


def test_opening_hours_and_travel_time_enforced():
    draft = ItineraryDraft(days=[DraftDay(items=[DraftItem(place_id="fort_aguada", start_time="05:00"),
                                                 DraftItem(place_id="bom_jesus", start_time="10:00")])])
    it, _ = materialize(draft, bundle(), profile(), DEC[0], 5)
    a, b = it.days[0].items
    assert a.start >= "12:00"                      # arrival day starts at noon; fort opens 09:30
    assert b.start >= a.end and b.travel_min_from_prev == 40   # north → central, from the matrix


def test_closed_place_and_duplicate_dropped():
    b = bundle(span=(date(2026, 12, 10), date(2026, 12, 14)))
    draft = ItineraryDraft(days=[DraftDay(items=[DraftItem(place_id="anjuna_flea"), DraftItem(place_id="baga_beach"),
                                                 DraftItem(place_id="baga_beach")])])
    it, dropped = materialize(draft, b, profile(), date(2026, 12, 10), 5)   # 10 Dec 2026 is a Thursday; flea is Wed-only
    assert ids(it) == ["baga_beach"] and len(dropped) == 2


def test_unavailable_day_marks_items_optional_with_note():
    p = profile(unavailable={DEC[0]: [3, 4]})
    it, _ = materialize(heuristic_draft(bundle(), p, DEC[0], 5, set(), None), bundle(), p, DEC[0], 5)
    assert all(i.optional for i in it.days[0].items) and "Aman, Neha" in it.days[0].note
    assert not any(i.optional for i in it.days[1].items)


def test_avoided_topic_never_scheduled():
    p = profile(avoids={"nightlife"}, interests={1: {"nightlife": 5}})
    it, _ = plan_itinerary(None, bundle(), p, DEC[0], 5, set(), None, None)
    names = {i.place_id for i in ids and [x for d in it.days for x in d.items]}
    assert "titos_lane" not in names
    assert not any(is_avoided(next(pl for pl in bundle().places if pl.id == pid), p.avoids) for pid in ids(it))


# ---------- the fallback planner ----------

def test_no_preferences_still_gives_a_sensible_plan():
    it, _ = plan_itinerary(None, bundle(), profile(), DEC[0], 5, set(), None, None)
    assert it.used_fallback and len(it.days) == 5 and all(d.items for d in it.days)
    assert "titos_lane" not in ids(it)             # nobody asked for nightlife
    assert len(set(ids(it))) == len(ids(it))


def test_preferences_steer_the_plan_and_nobody_is_left_out():
    p = profile(interests={1: {"beaches": 5}, 2: {"culture": 4}, 3: {"nature": 5}, 4: {"food": 3}})
    it, _ = plan_itinerary(None, bundle(), p, DEC[0], 5, set(), None, None)
    assert "dudhsagar" in ids(it) and "palolem_beach" in ids(it) or "colva_beach" in ids(it)
    report = validate(it, bundle(), p, DEC[0], 5, "within")
    assert report.ok and all(report.coverage.values())


def test_contested_topic_limited_to_one_slot():
    """Culture has many candidates in Goa, so without the limit it would dominate every day."""
    free = profile(interests={1: {"culture": 5}, 3: {"culture": 4}})
    capped = profile(interests={1: {"culture": 5}, 3: {"culture": 4}}, dislikes={2: {"culture": 4}},
                     limited_topics={"culture"})
    count = lambda it: sum(1 for pid in ids(it) if next(p for p in bundle().places if p.id == pid).topics[0] == "culture")
    it_free, _ = plan_itinerary(None, bundle(), free, DEC[0], 5, set(), None, None)
    it_cap, _ = plan_itinerary(None, bundle(), capped, DEC[0], 5, set(), None, None)
    assert count(it_free) > 1 and count(it_cap) == 1


def test_night_market_is_not_treated_as_nightlife():
    p = profile(avoids={"nightlife"}, interests={1: {"shopping": 5}})
    it, _ = plan_itinerary(None, bundle(), p, DEC[0], 5, set(), None, None)
    assert "titos_lane" not in ids(it)          # clubs are out
    assert "arpora_night_market" in ids(it)     # an evening market is a different thing


def test_monsoon_plan_excludes_closed_attractions():
    span = (date(2026, 7, 10), date(2026, 7, 13))
    p = profile(interests={1: {"nature": 5, "adventure": 5}})
    it, _ = plan_itinerary(None, bundle(span=span), p, span[0], 4, set(), None, None)
    assert not {"dudhsagar", "water_sports"} & set(ids(it))


def test_llm_draft_used_when_valid_and_fallback_when_not():
    good = ItineraryDraft(days=[DraftDay(title="North", items=[DraftItem(place_id="baga_beach", why="For Rahul.")])] * 5,
                          stay_tier="mid", food_tier="mid")
    it, _ = plan_itinerary(FakeLLM(draft=good.model_dump()), bundle(), profile(), DEC[0], 5, set(), None, None)
    assert not it.used_fallback and it.days[0].items[0].why == "For Rahul."
    junk = ItineraryDraft(days=[DraftDay(items=[DraftItem(place_id="nowhere")])])
    it2, _ = plan_itinerary(FakeLLM(draft=junk.model_dump()), bundle(), profile(), DEC[0], 5, set(), None, None)
    assert it2.used_fallback and ids(it2)
    it3, _ = plan_itinerary(FakeLLM(draft=None), bundle(), profile(), DEC[0], 5, set(), None, None)
    assert it3.used_fallback


def test_budget_levers_are_binding_on_llm_drafts():
    d = ItineraryDraft(days=[DraftDay(items=[DraftItem(place_id="baga_beach")])] * 5, stay_tier="premium",
                       food_tier="premium", transport_id="cab_day")
    it, _ = plan_itinerary(FakeLLM(draft=d.model_dump()), bundle(), profile(), DEC[0], 5, set(), "budget", None,
                           "budget", "scooter")
    assert (it.stay.tier, it.food_tier, it.transport_id) == ("budget", "budget", "scooter")


# ---------- costs ----------

def test_cost_lines_math_for_four_people_in_peak_season():
    d = bundle().destination
    it, _ = plan_itinerary(None, bundle(), profile(), DEC[0], 5, set(), "mid", None)
    lines, label_map = cost_lines(it, d, 4)
    r = compute_budget(lines, 4, Decimal(60000))
    assert it.stay.nightly_per_room == 7200 and it.stay.rooms == 2 and it.stay.nights == 4   # 4,500 × 1.6 peak
    assert r.by_category["accommodation"] == 57600
    assert r.by_category["food"] >= 1500 * 5 * 4
    assert all(pid in {p.id for p in d.places} for pid in label_map.values())


# ---------- validator ----------

def test_validator_catches_what_the_llm_got_wrong():
    p = profile(avoids={"nightlife"})
    it, _ = materialize(ItineraryDraft(days=[DraftDay(items=[DraftItem(place_id="baga_beach")])]), bundle(), profile(), DEC[0], 5)
    it.days[0].items[0].place_id = "titos_lane"       # tamper after the fact
    rep = validate(it, bundle(), p, DEC[0], 5, "within")
    assert not rep.ok and any("ruled out" in v for v in rep.violations)
    it.days[0].items[0].place_id = "made_up"
    assert any("verified" in v for v in validate(it, bundle(), p, DEC[0], 5, "within").violations)


def test_validator_warns_on_dietary_and_uncovered_members():
    p = profile(interests={1: {"shopping": 5}}, dietary=["vegetarian"])
    d = ItineraryDraft(days=[DraftDay(items=[DraftItem(place_id="bom_jesus")])])
    it, _ = materialize(d, bundle(), p, DEC[0], 5)
    rep = validate(it, bundle(), p, DEC[0], 5, "tight")
    assert rep.ok and any("vegetarian" in w for w in rep.warnings) and any("Rahul" in w for w in rep.warnings)
    assert any("close to your budget" in w for w in rep.warnings)


# ---------- diff & router ----------

def test_diff_summary_describes_changes():
    p = profile()
    a, _ = materialize(ItineraryDraft(days=[DraftDay(items=[DraftItem(place_id="baga_beach")]),
                                            DraftDay(items=[DraftItem(place_id="bom_jesus")])]), bundle(), p, DEC[0], 5)
    b, _ = materialize(ItineraryDraft(days=[DraftDay(items=[DraftItem(place_id="bom_jesus")]),
                                            DraftDay(items=[DraftItem(place_id="dudhsagar")])]), bundle(), p, DEC[0], 5)
    assert diff_summary(None, a) == "First version of the plan."
    s = diff_summary(a, b)
    assert "Added Dudhsagar Falls" in s and "Removed Baga Beach" in s and "Bom Jesus" in s and "Day 2 to Day 1" in s


@pytest.mark.parametrize("text,addr,expected", [
    ("we should go to the beach", False, "chat"),
    ("make the itinerary", False, "chat"),                       # humans talking; planner stays quiet
    ("@planner make the itinerary", True, "plan"),
    ("@planner please update the plan", True, "plan"),
    ("@Planner can you regenerate it?", True, "plan"),
    ("@planner why is Fort Aguada on day 1?", True, "explain"),
    ("@planner how much will this cost?", True, "explain"),
    ("@planner we want to add Dudhsagar", True, "chat"),
    ("@planner can we afford this?", True, "explain"),
])
def test_router(text, addr, expected):
    assert classify(text, addr) == expected


def test_router_commands_override():
    assert classify("", False, "itinerary_generate") == "plan"
    assert classify("", False, "budget") == "explain"


# ---------- regressions found by running realistic scenarios ----------

def test_long_outing_is_never_put_on_the_arrival_day_and_nothing_is_silently_lost():
    """Dudhsagar takes 5h and closes 16:30: it can't start after noon. It used to be chosen for day 1,
    dropped at scheduling time, and never retried."""
    p = profile(interests={3: {"nature": 5, "adventure": 4}})
    it, dropped = plan_itinerary(None, bundle(), p, DEC[0], 5, set(), None, None)
    day_of = {i.place_id: d.index for d in it.days for i in d.items}
    assert "dudhsagar" in day_of and day_of["dudhsagar"] > 1
    assert not any("timing" in d for d in dropped)


def test_must_have_that_is_closed_is_reported_never_substituted():
    from app.agents.itinerary import required_places
    july = bundle(span=(date(2026, 7, 10), date(2026, 7, 13)))
    found, unmatched = required_places(july, profile(must_include=["dudhsagar"]))
    assert found == [] and unmatched == ["dudhsagar"]       # not swapped for some other "nature" place
    dec_found, _ = required_places(bundle(), profile(must_include=["dudhsagar"]))
    assert [p.id for p in dec_found] == ["dudhsagar"]


def test_must_have_by_topic_picks_best_scoring_place():
    from app.agents.itinerary import required_places
    p = profile(must_include=["shopping"], interests={1: {"shopping": 5}})
    found, _ = required_places(bundle(), p)
    assert found and found[0].topics[0] == "shopping"


def test_must_have_is_injected_even_if_the_llm_ignores_it():
    p = profile(must_include=["dudhsagar"])
    d = ItineraryDraft(days=[DraftDay(items=[DraftItem(place_id="baga_beach")])] * 5)
    it, _ = plan_itinerary(FakeLLM(draft=d.model_dump()), bundle(), p, DEC[0], 5, set(), None, None)
    assert "dudhsagar" in ids(it) and not it.used_fallback
