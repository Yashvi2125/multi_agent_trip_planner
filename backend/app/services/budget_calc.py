"""All money maths lives here, in plain Decimal arithmetic. The LLM never calculates totals."""
from dataclasses import dataclass, field
from decimal import ROUND_HALF_UP, Decimal
from math import ceil
from typing import Literal

Category = Literal["accommodation", "food", "transport", "activities", "other"]
CATEGORIES: tuple[Category, ...] = ("accommodation", "food", "transport", "activities", "other")
# What the feedback loop may trim first, in order. Accommodation/transport are structural.
DISCRETIONARY_ORDER: tuple[Category, ...] = ("activities", "food", "other")
TIGHT_THRESHOLD = Decimal("0.90")


def _q(x: Decimal) -> Decimal:
    return x.quantize(Decimal("1"), rounding=ROUND_HALF_UP)


@dataclass(frozen=True)
class CostLine:
    category: Category
    label: str
    amount: Decimal
    per_person: bool = False  # True → amount is per traveler; False → amount is for the whole group
    ref: str | None = None    # place id this line came from, so the feedback loop can drop it

    def total(self, travelers: int) -> Decimal:
        return self.amount * travelers if self.per_person else self.amount


@dataclass
class BudgetResult:
    travelers: int
    total: Decimal
    per_person: Decimal
    by_category: dict[str, Decimal]
    cap: Decimal | None
    remaining: Decimal | None
    over_by: Decimal
    status: Literal["within", "tight", "over", "no_budget"]
    cut_candidates: list[CostLine] = field(default_factory=list)


def stay_cost(nightly_room_rate: Decimal, nights: int, travelers: int, occupancy: int = 2) -> Decimal:
    """Rooms are shared (default two per room), so 5 people need 3 rooms."""
    if travelers < 1 or nights < 0 or occupancy < 1:
        raise ValueError("travelers/occupancy must be ≥ 1 and nights ≥ 0")
    return nightly_room_rate * nights * ceil(travelers / occupancy)


def effective_cap(group_budget: Decimal | None, personal_caps: list[Decimal], travelers: int) -> Decimal | None:
    """Hard constraints combine by taking the strictest: group budget, or lowest personal cap × travelers."""
    caps = []
    if group_budget is not None:
        caps.append(group_budget)
    if personal_caps:
        caps.append(min(personal_caps) * travelers)
    return min(caps) if caps else None


def compute_budget(lines: list[CostLine], travelers: int, cap: Decimal | None) -> BudgetResult:
    if travelers < 1:
        raise ValueError("travelers must be ≥ 1")
    if any(l.amount < 0 for l in lines):
        raise ValueError("cost lines can't be negative")
    by_cat = {c: Decimal(0) for c in CATEGORIES}
    for l in lines:
        by_cat[l.category] += l.total(travelers)
    total = sum(by_cat.values(), Decimal(0))
    per_person = _q(total / travelers)

    if cap is None:
        status, remaining, over = "no_budget", None, Decimal(0)
    else:
        remaining, over = cap - total, max(total - cap, Decimal(0))
        status = "over" if total > cap else ("tight" if total >= cap * TIGHT_THRESHOLD else "within")

    cuts: list[CostLine] = []
    if status == "over":
        rank = {c: i for i, c in enumerate(DISCRETIONARY_ORDER)}
        cuts = sorted((l for l in lines if l.category in rank),
                      key=lambda l: (rank[l.category], -l.total(travelers)))
    return BudgetResult(travelers, _q(total), per_person, {k: _q(v) for k, v in by_cat.items()},
                        cap, None if remaining is None else _q(remaining), _q(over), status, cuts)
