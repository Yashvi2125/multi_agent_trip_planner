"""Turns an itinerary into cost lines, and decides how to trim when over budget."""
from decimal import Decimal
from math import ceil

from app.schemas.itinerary import Itinerary, Revision
from app.services.budget_calc import BudgetResult, CostLine
from app.services.itinerary_logic import TIERS
from app.tools.curated import Destination


def build_cost_lines(it: Itinerary, dest: Destination, travelers: int) -> list[CostLine]:
    lines: list[CostLine] = []
    if it.stay and it.stay.nights > 0:
        s = it.stay
        lines.append(CostLine("accommodation", f"{s.tier.title()} stay, {s.nights} nights, {s.rooms} rooms",
                              Decimal(s.nightly_rate * s.rooms * s.nights)))
    days = len(it.days)
    lines.append(CostLine("food", f"Meals ({it.food_tier}), {days} days",
                          Decimal(dest.food_per_person_day[it.food_tier] * days), per_person=True))
    active = sum(1 for d in it.days if any(i.place_id for i in d.items))
    cab = next((t for t in dest.transport if t.id == "cab_day"), dest.transport[0])
    lines.append(CostLine("transport", f"{cab.mode}, {active} days",
                          Decimal(cab.cost_inr * ceil(travelers / cab.capacity) * active)))
    for d in it.days:
        for i in d.items:
            # Restaurants are covered by the daily food line, so they add nothing here
            if i.place_id and i.cost_pp > 0 and i.kind != "food":
                lines.append(CostLine("other" if i.kind == "market" else "activities", i.name,
                                      Decimal(i.cost_pp), per_person=True, ref=i.place_id))
    return lines


def _lower(tier: str) -> str | None:
    i = TIERS.index(tier)
    return TIERS[i - 1] if i > 0 else None


def next_revision(result: BudgetResult, it: Itinerary, dest: Destination, travelers: int,
                  protected_topics: set[str], previous: Revision | None = None) -> Revision | None:
    """Cheapest way back under budget: drop discretionary activities first (never ones the group
    insisted on), then step the stay down a tier, then food. None means nothing left to try."""
    if result.status != "over":
        return None
    prev = previous or Revision()
    need, saved, drops = result.over_by, Decimal(0), []
    for c in result.cut_candidates:
        place = dest.place(c.ref) if c.ref else None
        if not place or (protected_topics & set(place.topics)):
            continue
        drops.append(c.ref)
        saved += c.total(travelers)
        if saved >= need:
            break
    rev = Revision(drop_place_ids=sorted(set(prev.drop_place_ids) | set(drops)),
                   stay_tier=prev.stay_tier, food_tier=prev.food_tier)
    if saved < need:
        stay_tier = rev.stay_tier or (it.stay.tier if it.stay else "budget")
        food_tier = rev.food_tier or it.food_tier
        if it.stay and _lower(stay_tier):
            rev.stay_tier = _lower(stay_tier)
        elif _lower(food_tier):
            rev.food_tier = _lower(food_tier)
    changed = (set(rev.drop_place_ids) != set(prev.drop_place_ids)
               or rev.stay_tier != prev.stay_tier or rev.food_tier != prev.food_tier)
    return rev if changed else None
