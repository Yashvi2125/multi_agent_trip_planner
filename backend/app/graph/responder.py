"""Turns graph state into what the Planner actually says. Pure function: easy to test, easy to re-voice.
Principle: speak only when there is something worth saying."""
from decimal import Decimal

from app.core.money import format_inr
from app.schemas.agents import ExtractedConstraint
from app.schemas.itinerary import Itinerary


def describe_constraint(c: ExtractedConstraint) -> str:
    if c.type == "max_budget":
        return (f"a group budget of {format_inr(c.amount)}" if c.applies_to_group
                else f"your limit of {format_inr(c.amount)} per person")
    if c.type == "must_avoid":
        return f"no {c.text}, ruled out for the whole plan"
    if c.type == "must_include":
        return f"{c.text} as a must-have"
    if c.type == "dietary":
        return f"the dietary need: {c.text}"
    if c.type == "accessibility":
        return f"the accessibility need: {c.text}"
    days = ", ".join(f"{d.day} {d:%b}" for d in c.dates)
    return f"that you can't make {days}"


def _budget_sentence(b: dict, trimmed: list[str]) -> str:
    total, cap, status = Decimal(b["total"]), b.get("cap"), b["status"]
    if status == "no_budget" or cap is None:
        return "There's no budget limit set yet, so I haven't checked it against anything."
    cap = Decimal(cap)
    if status == "within":
        return f"That's comfortably inside your {format_inr(cap)} budget."
    if status == "tight":
        return f"That just fits your {format_inr(cap)} budget, with very little room to spare."
    over = Decimal(b["over_by"])
    return (f"That's {format_inr(over)} over your {format_inr(cap)} budget, and I couldn't close the gap. "
            f"Raising the budget by {format_inr(over)}, or shortening the trip, would sort it.")


def _trim_sentence(trimmed: list[str]) -> str:
    if not trimmed:
        return ""
    return "To get the cost down I made these changes: " + ", ".join(trimmed) + ". Tell me if any of those matter and I'll rework it."


def _plan_message(s: dict, it: Itinerary, trip_name: str) -> str:
    b = s["budget"]
    head = (f"Here's version {s['version']} of the {it.destination} plan: {len(it.days)} days, "
            f"about {format_inr(Decimal(b['per_person']))} each ({format_inr(Decimal(b['total']))} for the group). "
            f"{_budget_sentence(b, s['trimmed'])}")
    if (t := _trim_sentence(s["trimmed"])):
        head += " " + t
    days = []
    for d in it.days:
        if d.items:
            names = ", ".join(i.name + (" (optional)" if i.optional else "") for i in d.items)
            days.append(f"Day {d.index} · {d.title}: {names}")
        else:
            days.append(f"Day {d.index} · Free day: nothing scheduled, so it's open for rest or something spontaneous")
    parts = [head, "\n".join(days)]
    if s["version"] and s["version"] > 1 and s.get("change_summary"):
        parts.append(f"What changed: {s['change_summary']}")
    extra = list(s["notes"]) + list(s["warnings"])
    if s["used_fallback"]:
        extra.append("I built this without my language model today, so the choices are rule-based and a bit plainer than usual.")
    parts.extend(extra)
    parts.append("Ask me “why” about any stop, or tell me what to change.")
    return "\n\n".join(parts)


BLOCKED = {
    "no_dates": "I need your trip dates before I can build a plan. When are you going?",
    "too_long": "That's a long trip! I can plan up to two weeks at a time. Could you shorten the dates?",
}


def compose(s: dict, it: Itinerary | None, first_name: str, topics_open: set[str]) -> list[dict]:
    out: list[dict] = []
    say = lambda text, **meta: out.append({"text": text, "meta": meta})  # noqa: E731

    if s["intent"] == "explain":
        say(s["answer"] or "I'm not sure yet. Tell me more about what you'd like to know.")
        return out

    if s["hard_acks"]:
        say(f"Got it, {first_name}. I've noted {'; '.join(s['hard_acks'])}.")

    if s["new_conflicts"]:
        body = "\n\n".join(f"{c['description']} {c['compromise']}" for c in s["new_conflicts"])
        say(f"I noticed something the group should settle.\n\n{body}\n\nDoes that work for everyone?",
            conflict_ids=[c["id"] for c in s["new_conflicts"]])
    if s["resolved_conflicts"]:
        say("Thanks, that sorts out the earlier disagreement." if len(s["resolved_conflicts"]) == 1
            else "Thanks, that sorts out those earlier disagreements.", resolved=[c["id"] for c in s["resolved_conflicts"]])

    if s["plan_request"]:
        if s["blocked"] == "unsupported":
            say(" ".join(s["notes"]))
        elif s["blocked"] in BLOCKED:
            say(BLOCKED[s["blocked"]])
        elif s["violations"]:
            say("I couldn't build a plan that respects everything you've asked for: "
                + " ".join(s["violations"]) + " Could you relax one of those or adjust the dates?")
        elif it and s["version"]:
            say(_plan_message(s, it, ""), version=s["version"])
    elif s["stale"] and s["addressed"] is not None:
        say("Noted. The current plan doesn't include that yet. Say “@planner update the plan” whenever you're ready.")

    if not out and s["addressed"]:
        say("I'm here. Tell me what everyone's after and I'll build the first version of the plan."
            if not s["has_itinerary"] else
            "I'm here. Ask me why for any stop, or say “update the plan” to fold in new preferences.")
    return out
