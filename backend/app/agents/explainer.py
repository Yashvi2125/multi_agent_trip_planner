"""Explainability. Code assembles the facts (why-notes recorded at planning time, who each item serves,
budget numbers, last diff, exclusions); the LLM only phrases them. Without an LLM, a deterministic answer is used."""
import re

from app.agents.llm import LLMClient, LLMError
from app.schemas.itinerary import Answer, Itinerary, ItineraryItem

SYSTEM = """You are the group's trip planner answering a question about the plan. Use ONLY the facts provided.
If the facts don't answer the question, say what you do know and suggest how to change the plan.
Be warm, concrete and brief (2-4 sentences). Never invent places, prices or reasons."""


_GENERIC = {"beach", "fort", "market", "temple", "palace", "museum", "valley", "road", "tour", "river", "cruise", "night", "hot", "springs", "clubs", "cafe", "falls", "bazaar", "hall"}


def _words(name: str) -> list[str]:
    return [w for w in re.findall(r"[a-z]+", name.lower()) if len(w) > 3 and w not in _GENERIC]


def _find_place(question: str, dest):
    q = question.lower()
    if dest is None:
        return None
    return next((p for p in dest.places if p.name.lower() in q or any(w in q for w in _words(p.name))), None)


def _find_item(question: str, it: Itinerary, dest=None) -> tuple[ItineraryItem, int] | None:
    q = question.lower()
    exact = next((p for p in (dest.places if dest else []) if p.name.lower() in q), None)
    if exact:   # a full place name was used: answer about that place only (in the plan or not)
        return next(((i, d.index) for d in it.days for i in d.items if i.place_id == exact.id), None)
    for day in it.days:
        for item in day.items:
            if item.name.lower() in q or item.place_id.replace("_", " ") in q or any(w in q for w in _words(item.name)):
                return item, day.index
    return None


def build_facts(question: str, it: Itinerary | None, budget: dict | None, change_summary: str | None,
                notes: list[str], excluded: list[str], dest=None, trimmed: list[str] | None = None) -> tuple[str, str]:
    """Returns (facts_text, deterministic_answer)."""
    if it is None:
        msg = "There's no itinerary yet. Tell me what everyone's after and say “@planner make the plan” when you're ready."
        return msg, msg
    q = question.lower()
    facts: list[str] = []
    exact_named = dest and next((p for p in dest.places if p.name.lower() in q), None)
    if (hit := _find_item(question, it, dest)):
        item, day = hit
        who = f" It's there for {', '.join(item.serves)}." if item.serves else ""
        travel = f" It's about {item.travel_min_from_prev} minutes from the previous stop." if item.travel_min_from_prev else ""
        base = f"{item.name} is on Day {day} at {item.start}. {item.why}{who}{travel}"
        facts.append(base)
        det = base
    elif (pl := exact_named or _find_place(question, dest)) is not None:   # asked about something that is NOT in the plan
        reason = next((e for e in excluded if pl.name in e), None)
        if reason:
            det = f"{pl.name} isn't in the plan. {reason}"
        elif pl.name in (trimmed or []):
            det = (f"{pl.name} isn't in the plan any more. It was one of the extras I trimmed to bring the cost down. "
                   f"If it matters to someone, tell me it's a must-have and I'll rebuild around it.")
        else:
            det = f"{pl.name} isn't in the plan right now. If someone wants it, tell me it's a must-have and I'll rebuild around it."
        facts.append(det)
    elif re.search(r"\b(hotel|stay|stays|accommodation|room)\b", q) and it.stay:
        det = it.stay.why
        facts.append(det)
    elif re.search(r"\b(moved|changed|change|different|updated|new version)\b", q) and change_summary:
        det = f"Here's what changed in the latest version: {change_summary}"
        facts.append(det)
    elif re.search(r"\b(budget|cost|spend|afford|cheap|expensive|split|per person)\b", q) and budget:
        det = (f"The plan comes to about ₹{int(float(budget['total'])):,} for the group, roughly "
               f"₹{int(float(budget['per_person'])):,} each.")
        facts.append(det)
    else:
        det = it.summary or "Here's the plan so far. Ask me about any stop and I'll tell you why it's there."
        facts.append(det)
    if budget:
        facts.append(f"Budget: total ₹{budget['total']}, per person ₹{budget['per_person']}, status {budget['status']}.")
    if change_summary:
        facts.append(f"Latest change: {change_summary}")
    facts.extend(notes)
    facts.extend(excluded)
    return "\n".join(facts), det


def explain(llm: LLMClient | None, question: str, it: Itinerary | None, budget: dict | None,
            change_summary: str | None, notes: list[str], excluded: list[str], dest=None,
            trimmed: list[str] | None = None) -> str:
    facts, deterministic = build_facts(question, it, budget, change_summary, notes, excluded, dest, trimmed)
    if llm is None or it is None:
        return deterministic
    try:
        return llm.structured(Answer, SYSTEM, f"Question: {question}\n\nFacts:\n{facts}").text.strip() or deterministic
    except LLMError:
        return deterministic
