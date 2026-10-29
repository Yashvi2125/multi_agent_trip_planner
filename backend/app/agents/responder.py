"""Turns the finished graph state into what the planner actually says. Plain, warm, short.
Silence is a valid output: unaddressed chatter with nothing to report produces no messages."""
from app.core.money import format_inr

HELP_TEXT = ("I read along while you plan and keep track of what everyone wants. Ask me to \"make the plan\", "
             "\"why did you pick Fort Aguada?\", or \"how's the budget?\". I'll speak up if two people want "
             "different things.")


def _humanise_pref(item: str) -> str:
    cat, topic = item.split(":", 1)
    return {"interest": f"likes {topic}", "dislike": f"isn't keen on {topic}", "style": f"prefers a {topic} style",
            "food": f"food: {topic}", "stay": f"stay: {topic}"}.get(cat, topic)


def _humanise_constraint(item: str) -> str:
    ctype, value = item.split(":", 1)
    return {"max_budget": "a spending limit", "dietary": "a dietary requirement", "must_avoid": "something to avoid",
            "must_include": "a must-have", "unavailable_day": "a day they can't do",
            "accessibility": "an accessibility need"}.get(ctype, ctype)


def budget_sentence(b: dict) -> str:
    base = f"About {format_inr(b['total'])} in total, roughly {format_inr(b['per_person'])} each."
    if b["status"] == "over":
        return (f"{base} That's {format_inr(b['over_by'])} over your {format_inr(b['cap'])} limit even after trimming, "
                f"so you'd need to raise the budget, shorten the trip, or pick a cheaper base.")
    if b["status"] == "tight":
        return f"{base} That's right at the limit ({format_inr(b['remaining'])} to spare)."
    if b["status"] == "within":
        return f"{base} That leaves {format_inr(b['remaining'])} of your {format_inr(b['cap'])} budget."
    return f"{base} No budget has been set yet, so I couldn't check it against a limit."


def summarise_plan(it: dict) -> str:
    lines = []
    for d in it["days"]:
        stops = [i["name"] for i in d["items"] if i.get("place_id")]
        lines.append(f"Day {d['day_number']}, {d['title']}: " + (", ".join(stops) if stops else "nothing planned yet"))
    return "\n".join(lines)


def compose(s: dict) -> list[str]:
    out: list[str] = []
    intent, addressed = s.get("intent", "chat"), s.get("addressed", False)
    outcome = s.get("outcome") or {}

    for c in s.get("conflicts_opened", []):
        out.append(f"I noticed a clash. {c['description']} One way through: {c['compromise']} Let me know if that works for everyone.")
    for c in s.get("conflicts_resolved", []):
        out.append(f"Good news, this one looks sorted now: {c['description']}")

    if intent == "help":
        out.append(HELP_TEXT)
    elif intent == "why":
        out.append(s.get("explanation") or "I'm not sure what to explain yet.")
    elif intent == "status":
        if s.get("itinerary") and s["itinerary"]["days"]:
            out.append(f"Version {s.get('itinerary_version', 1)} of the plan:\n{summarise_plan(s['itinerary'])}")
            if s.get("budget"):
                out.append(budget_sentence(s["budget"]))
        else:
            out.append("There's no plan yet. Tell me what you're all hoping for, then ask me to make the plan.")
    elif s.get("plan_blocked") == "dates":
        out.append("I need the trip dates before I can plan anything. What are the start and end dates?")
    elif s.get("plan_blocked") == "unsupported":
        out.extend((s.get("research") or {}).get("notes", [])[:2])
    elif s.get("plan_saved"):
        it = s["itinerary"]
        stops = sum(1 for d in it["days"] for i in d["items"] if i.get("place_id"))
        if s.get("is_replan"):
            out.append(f"I've updated the plan with the new preferences. {s.get('change_summary', '')}".strip())
        else:
            out.append(f"Here's the first version of the {s['destination']} plan: {len(it['days'])} days and {stops} stops.")
        out.append(budget_sentence(s["budget"]))
        missing = [n for uid, n in s.get("uncovered", {}).items()]
        if missing:
            out.append(f"I couldn't fit something for {', '.join(missing)} yet. Tell me more about what they'd enjoy.")
        if not s.get("preferences"):
            out.append("Nobody's shared preferences yet, so this is a balanced first draft you can steer.")
        if s.get("planned_by") == "rules":
            out.append("I couldn't reach my language model just now, so I built this with simple rules. It's valid, just less tailored.")
        out.extend((s.get("research") or {}).get("notes", []))
        if s.get("violations_unfixed"):
            out.extend(s["violations_unfixed"])
    elif addressed and intent == "chat":
        if s.get("extraction_failed"):
            out.append("I couldn't process that message properly. Could you try rephrasing it?")
        else:
            added = [_humanise_pref(x) for x in outcome.get("added_preferences", [])]
            added += [_humanise_constraint(x) for x in outcome.get("added_constraints", [])]
            if added:
                out.append("Got it, I've noted that: " + "; ".join(added) + ".")
            elif not out:
                out.append("I'm here. Tell me what you're hoping for and I'll keep track.")
    return out
