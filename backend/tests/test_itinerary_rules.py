"""Rules the rebuilt planner must hold that the original suite does not pin down directly.
Each of these was added after a deliberate-breakage check showed the suite would not notice the rule vanishing."""
from datetime import date
from decimal import Decimal

from app.agents.itinerary import (_fits, cheapest_transport, cost_lines, heuristic_draft, make_stay, materialize,
                                  plan_itinerary, schedule_stops)
from app.agents.profile import GroupProfile
from app.agents.research import research
from app.schemas.itinerary import DraftDay, DraftItem, ItineraryDraft
from app.tools.curated import find_destination
from tests.fakes import FakeLLM, FakeWeather

TODAY = date(2026, 10, 1)
DEC = (date(2026, 12, 10), date(2026, 12, 14))      # Thu 10 → Mon 14; 12 Dec is a Saturday


def bundle(dest="Goa", span=DEC):
    return research(dest, span[0], span[1], FakeWeather(), today=TODAY)


def profile(**kw):
    p = GroupProfile(members={1: "Rahul Mehta", 2: "Priya Shah", 3: "Aman Verma", 4: "Neha Rao"})
    for k, v in kw.items():
        setattr(p, k, v)
    return p


def ids(it):
    return [i.place_id for d in it.days for i in d.items]


# ---------- opening hours and the arrival day ----------

def test_fits_rejects_a_five_hour_outing_on_the_noon_arrival_day():
    goa = find_destination("goa")
    falls = goa.place("dudhsagar")
    assert not _fits(goa, DEC[0], [falls], arrival=True, anchor="east")     # 12:00 + 5h runs past the 16:30 closing
    assert _fits(goa, date(2026, 12, 11), [falls], arrival=False, anchor="east")


def test_materialize_drops_what_cannot_finish_before_closing_and_says_why():
    draft = ItineraryDraft(days=[DraftDay(items=[DraftItem(place_id="dudhsagar"), DraftItem(place_id="baga_beach")])])
    it, dropped = materialize(draft, bundle(), profile(), DEC[0], 5)
    assert ids(it) == ["baga_beach"]
    assert any("Dudhsagar" in d and "timing" in d and "16:30" in d for d in dropped)


def test_start_time_hint_is_a_floor_not_a_command():
    draft = ItineraryDraft(days=[DraftDay(items=[DraftItem(place_id="baga_beach", start_time="16:07")]),
                                 DraftDay(items=[DraftItem(place_id="baga_beach")]),
                                 DraftDay(items=[DraftItem(place_id="calangute_beach", start_time="not-a-time")])])
    it, _ = materialize(draft, bundle(), profile(), DEC[0], 5)
    assert it.days[0].items[0].start == "16:15"                              # rounded up to the 15-minute grid
    assert it.days[2].items[0].start == "09:00"                              # garbage hint ignored, no crash


def test_nothing_ends_after_the_day_limit_and_clubs_start_when_they_open():
    draft = ItineraryDraft(days=[DraftDay(), DraftDay(items=[DraftItem(place_id="titos_lane")])])
    it, _ = materialize(draft, bundle(), profile(), DEC[0], 5)
    club = it.days[1].items[0]
    assert club.start == "20:00" and club.end == "22:30"
    assert all(i.end <= "23:30" for d in it.days for i in d.items)


# ---------- the deterministic planner on its own ----------

def test_heuristic_draft_itself_limits_a_contested_topic():
    """Checked on the *draft*, so it cannot be rescued by materialize() quietly dropping extras."""
    p = profile(interests={1: {"culture": 5}, 3: {"culture": 4}}, dislikes={2: {"culture": 4}}, limited_topics={"culture"})
    b = bundle()
    draft = heuristic_draft(b, p, DEC[0], 5)
    culture = [i.place_id for d in draft.days for i in d.items if "culture" in b.destination.place(i.place_id).topics]
    assert len(culture) == 1


def test_weekday_only_market_is_placed_on_the_day_it_runs():
    p = profile(interests={1: {"shopping": 5}})
    it, _ = plan_itinerary(None, bundle(), p, DEC[0], 5, set(), None, None)
    day_of = {i.place_id: d.date for d in it.days for i in d.items}
    assert day_of["arpora_night_market"].weekday() == 5                      # Saturday


def test_budget_cuts_are_honoured_by_both_planners():
    cut = {"water_sports", "dudhsagar"}
    p = profile(interests={1: {"adventure": 5}})
    fallback, _ = plan_itinerary(None, bundle(), p, DEC[0], 5, cut, None, None)
    draft = ItineraryDraft(days=[DraftDay(items=[DraftItem(place_id="water_sports"), DraftItem(place_id="baga_beach")])] * 5)
    llm_plan, dropped = plan_itinerary(FakeLLM(draft=draft.model_dump()), bundle(), p, DEC[0], 5, cut, None, None)
    assert not cut & set(ids(fallback)) and not cut & set(ids(llm_plan))
    assert not any("water" in d.lower() for d in dropped)                     # a deliberate trim is not reported as a failure


def test_must_have_injected_into_an_llm_plan_avoids_the_arrival_day():
    p = profile(must_include=["dudhsagar"])
    draft = ItineraryDraft(days=[DraftDay(items=[DraftItem(place_id="baga_beach")])] * 5)
    it, dropped = plan_itinerary(FakeLLM(draft=draft.model_dump()), bundle(), p, DEC[0], 5, set(), None, None)
    day = next(d.index for d in it.days for i in d.items if i.place_id == "dudhsagar")
    assert day > 1 and not any("timing" in d for d in dropped)


def test_no_club_unless_someone_wants_one_and_never_if_ruled_out():
    none, _ = plan_itinerary(None, bundle(), profile(), DEC[0], 5, set(), None, None)
    wanted, _ = plan_itinerary(None, bundle(), profile(interests={1: {"nightlife": 5}}), DEC[0], 5, set(), None, None)
    banned, _ = plan_itinerary(None, bundle(), profile(interests={1: {"nightlife": 5}}, avoids={"nightlife"}), DEC[0], 5, set(), None, None)
    assert "titos_lane" not in ids(none) and "titos_lane" in ids(wanted) and "titos_lane" not in ids(banned)


# ---------- stay, transport, cost ----------

def test_one_day_trip_has_no_stay_cost():
    b = bundle(span=(DEC[0], DEC[0]))
    it, _ = plan_itinerary(None, b, profile(), DEC[0], 1, set(), None, None)
    lines, _ = cost_lines(it, b.destination, 4)
    assert it.stay.nights == 0 and not any(l.category == "accommodation" for l in lines)
    assert it.days[0].items and it.days[0].items[0].start == "09:00"          # no arrival-noon rule for a day trip


def test_stay_rate_uses_peak_season_only_in_peak_months():
    goa = find_destination("goa")
    assert make_stay(goa, "mid", "north", 5, 4, date(2026, 12, 10)).nightly_per_room == 7200    # 4,500 × 1.6
    assert make_stay(goa, "mid", "north", 5, 4, date(2026, 10, 10)).nightly_per_room == 4500
    assert make_stay(goa, "mid", "north", 5, 5, date(2026, 10, 10)).rooms == 3                   # five people, three rooms


def test_cheapest_transport_ignores_trip_add_ons():
    assert cheapest_transport(find_destination("goa"), 4, 5) == "scooter"
    assert cheapest_transport(find_destination("manali"), 4, 5) == "cab_day"   # rohtang_cab is a day-trip add-on, not local transport


def test_manali_rohtang_cab_only_priced_when_the_plan_goes_there():
    span = (date(2026, 6, 10), date(2026, 6, 13))                              # Rohtang is open in June
    b = bundle("Manali", span)
    with_it, _ = plan_itinerary(None, b, profile(must_include=["rohtang"]), span[0], 4, set(), None, None)
    without, _ = plan_itinerary(None, b, profile(), span[0], 4, {"rohtang_pass"}, None, None)
    has = lambda it: any(l.label.startswith("Rohtang day trip") for l in cost_lines(it, b.destination, 4)[0])
    assert "rohtang_pass" in ids(with_it) and has(with_it) and not has(without)


def test_every_cost_line_is_a_real_decimal_and_matches_the_plan():
    b = bundle()
    it, _ = plan_itinerary(None, b, profile(interests={3: {"adventure": 5}}), DEC[0], 5, set(), None, None)
    lines, labels = cost_lines(it, b.destination, 4)
    paid = {i.name for d in it.days for i in d.items if i.cost_pp > 0}
    assert paid == set(labels) and all(isinstance(l.amount, Decimal) and l.amount >= 0 for l in lines)
