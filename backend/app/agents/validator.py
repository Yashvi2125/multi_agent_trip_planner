"""Hard constraints are verified by CODE, never trusted to the LLM.

violations → block the plan (it breaks something the group said is non-negotiable).
warnings   → the plan is saved, but the group is told plainly (unmet must-have, dietary, someone left out…).
Being over budget is neither: the plan is saved and the responder says exactly how far over it is."""
from dataclasses import dataclass, field
from datetime import timedelta

from app.agents.itinerary import first_name, is_avoided, matches_topic, member_wants, required_places
from app.agents.profile import GroupProfile
from app.agents.research import ResearchBundle
from app.schemas.itinerary import Itinerary
from app.tools.curated import place_open_on


@dataclass
class ValidationReport:
    violations: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    coverage: dict[str, bool] = field(default_factory=dict)   # member name → at least one stop they wanted

    @property
    def ok(self) -> bool:
        return not self.violations


def validate(it: Itinerary, bundle: ResearchBundle, profile: GroupProfile, start, n_days: int,
             budget_status: str) -> ValidationReport:
    dest, rep = bundle.destination, ValidationReport()
    if len(it.days) != n_days:
        rep.violations.append(f"The plan has {len(it.days)} days but the trip is {n_days}.")

    planned = []
    for day in it.days:
        when = start + timedelta(days=day.index - 1) if start else None
        for item in day.items:
            p = dest.place(item.place_id)
            if p is None:
                rep.violations.append(f"{item.name} isn't a verified place in my data.")
            elif is_avoided(p, profile.avoids):
                rep.violations.append(f"{p.name} was ruled out by someone in the group.")
            elif when and not place_open_on(p, when):
                rep.violations.append(f"{p.name} isn't open on day {day.index}.")
            else:
                planned.append(p)
    for topic in sorted(profile.limited_topics):
        if sum(1 for p in planned if matches_topic(p, topic)) > 1:
            rep.violations.append(f"There's more than one {topic} stop, but the group agreed to keep it to one.")

    found, unmatched = required_places(bundle, profile)
    in_plan = {p.id for p in planned}
    for p in found:
        if p.id not in in_plan:
            rep.warnings.append(f"I couldn't fit {p.name} in, even though it's a must-have.")
    for text in unmatched:
        t = text.lower()
        reason = next((e.reason for e in bundle.excluded
                       if t in e.place.name.lower() or t.replace(" ", "_") in e.place.id), None)
        rep.warnings.append(f"{reason} I couldn't include it in this plan." if reason else
                            f"I don't have a verified place matching “{text}”, so I couldn't include it.")

    for diet in profile.dietary:
        rep.warnings.append(f"I've noted the dietary need ({diet}), but I can't check menus yet. "
                            f"Please confirm with each restaurant.")
    for uid, wants in sorted(profile.interests.items()):
        name = profile.members.get(uid)
        if not name:
            continue
        covered = any(member_wants(p, wants) > 0 for p in planned)
        rep.coverage[name] = covered
        if not covered:
            rep.warnings.append(f"Nothing in this plan matches what {first_name(name)} asked for "
                                f"({', '.join(sorted(wants))}) yet.")
    if budget_status == "tight":
        rep.warnings.append("The total is close to your budget, so a few price surprises could tip it over.")
    return rep
