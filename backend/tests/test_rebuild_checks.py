"""Pins behaviour of the rebuilt itinerary agent and validator that the inherited suites did not cover.
Each test here was written after a deliberate-breakage check showed the rule could vanish unnoticed."""
from datetime import date

from app.agents.itinerary import heuristic_draft, materialize, plan_itinerary
from app.agents.profile import GroupProfile
from app.agents.research import research
from app.agents.validator import validate
from app.schemas.itinerary import DraftDay, DraftItem, ItineraryDraft
from tests.fakes import FakeWeather

TODAY = date(2026, 10, 1)
DEC = (date(2026, 12, 10), date(2026, 12, 14))      # Thu → Mon


def bundle(dest="Goa", span=DEC):
    return research(dest, span[0], span[1], FakeWeather(), today=TODAY)


def profile(**kw):
    p = GroupProfile(members={1: "Rahul Mehta", 2: "Priya Shah"})
    for k, v in kw.items():
        setattr(p, k, v)
    return p


def planned(draft, p=None, span=DEC, n=5):
    return materialize(draft, bundle(span=span), p or profile(), span[0], n)[0]


def test_validator_flags_a_stop_placed_on_a_day_it_is_closed():
    it = planned(ItineraryDraft(days=[DraftDay(items=[DraftItem(place_id="baga_beach")])]))
    it.days[0].items[0].place_id = "anjuna_flea"            # Wednesday-only market, but day 1 is a Thursday
    rep = validate(it, bundle(), profile(), DEC[0], 5, "within")
    assert not rep.ok and any("isn't open on day 1" in v for v in rep.violations)


def test_validator_flags_wrong_day_count():
    it = planned(ItineraryDraft(days=[DraftDay(items=[DraftItem(place_id="baga_beach")])]), n=3)
    assert any("3 days but the trip is 5" in v for v in validate(it, bundle(), profile(), DEC[0], 5, "within").violations)


def test_validator_flags_a_second_stop_on_a_limited_topic():
    p = profile(limited_topics={"culture"})
    it = planned(ItineraryDraft(days=[DraftDay(items=[DraftItem(place_id="bom_jesus")]),
                                      DraftDay(items=[DraftItem(place_id="se_cathedral")])]))   # both culture, no limit applied
    rep = validate(it, bundle(), p, DEC[0], 5, "within")
    assert any("more than one culture stop" in v for v in rep.violations)


def test_clean_plan_has_no_violations_and_over_budget_is_not_a_violation():
    it = planned(ItineraryDraft(days=[DraftDay(items=[DraftItem(place_id="baga_beach")])]))
    assert validate(it, bundle(), profile(), DEC[0], 5, "within").ok
    assert validate(it, bundle(), profile(), DEC[0], 5, "over").ok     # saved and reported, never blocked


def test_planner_survives_days_it_cannot_fill():
    """Regression: filling an empty day used to crash (Place objects are not hashable)."""
    b = bundle()
    keep = {"baga_beach", "bom_jesus"}
    avoid = {p.id for p in b.places} - keep
    draft = heuristic_draft(b, profile(), DEC[0], 5, avoid)
    assert len(draft.days) == 5
    it, _ = plan_itinerary(None, b, profile(), DEC[0], 5, avoid, None, None)
    assert len(it.days) == 5 and set(it.place_ids()) <= keep


def test_long_early_opening_excursion_starts_early_but_never_on_arrival_day():
    span = (date(2026, 6, 10), date(2026, 6, 13))               # Rohtang is open in June
    b = bundle("Manali", span)
    it, dropped = plan_itinerary(None, b, profile(must_include=["rohtang"]), span[0], 4, set(), None, None)
    rohtang = next((d.index, i) for d in it.days for i in d.items if i.place_id == "rohtang_pass")
    assert rohtang[0] > 1 and rohtang[1].start == "07:00" and rohtang[1].end == "14:00"
    assert not any("timing" in d for d in dropped)
