from decimal import Decimal as D

import pytest

from app.core.money import format_inr
from app.services.budget_calc import CostLine, compute_budget, effective_cap, stay_cost


def lines():
    return [
        CostLine("accommodation", "Beach hotel, 4 nights", stay_cost(D(4500), 4, 4)),
        CostLine("food", "Meals", D(1200) * 5, per_person=True),
        CostLine("transport", "Scooters + cab", D(6000)),
        CostLine("activities", "Dudhsagar jeep", D(800), per_person=True),
        CostLine("activities", "Water sports", D(1500), per_person=True),
    ]


def test_stay_cost_shares_rooms():
    assert stay_cost(D(4500), 4, 4) == D(36000)   # 2 rooms
    assert stay_cost(D(4500), 4, 5) == D(54000)   # 3 rooms
    with pytest.raises(ValueError):
        stay_cost(D(1000), 2, 0)


def test_totals_and_split_are_exact():
    r = compute_budget(lines(), 4, D(60000))
    assert r.by_category["accommodation"] == 36000
    assert r.by_category["food"] == 24000 and r.by_category["activities"] == 9200
    assert r.total == 75200 and r.per_person == 18800
    assert r.status == "over" and r.over_by == 15200 and r.remaining == -15200


def test_within_tight_and_over_boundaries():
    l = [CostLine("food", "x", D(100))]
    assert compute_budget(l, 2, D(1000)).status == "within"
    assert compute_budget(l, 2, D(105)).status == "tight"
    assert compute_budget(l, 2, D(100)).status == "tight"   # exactly on budget is not over
    assert compute_budget(l, 2, D(99)).status == "over"


def test_no_budget_given():
    r = compute_budget(lines(), 4, None)
    assert r.status == "no_budget" and r.remaining is None and r.over_by == 0


def test_cut_candidates_discretionary_only_and_biggest_first():
    r = compute_budget(lines(), 4, D(60000))
    labels = [c.label for c in r.cut_candidates]
    assert labels[:2] == ["Water sports", "Dudhsagar jeep"]     # activities first, by size
    assert "Beach hotel, 4 nights" not in labels and "Scooters + cab" not in labels
    assert compute_budget(lines(), 4, D(500000)).cut_candidates == []


def test_effective_cap_takes_strictest():
    assert effective_cap(D(60000), [D(12000), D(20000)], 4) == 48000
    assert effective_cap(D(40000), [D(12000)], 4) == 40000
    assert effective_cap(None, [], 4) is None
    assert effective_cap(None, [D(9000)], 3) == 27000


def test_rejects_bad_input():
    with pytest.raises(ValueError):
        compute_budget([CostLine("food", "x", D(-1))], 2, None)
    with pytest.raises(ValueError):
        compute_budget([], 0, None)


def test_inr_format():
    assert [format_inr(x) for x in (950, 12000, 125000, 10000000, -4500)] == \
        ["₹950", "₹12,000", "₹1,25,000", "₹1,00,00,000", "-₹4,500"]
