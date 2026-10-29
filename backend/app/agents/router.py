"""Intent router. Deliberately rule-based: deterministic, free, testable, and it decides whether the
AI speaks at all. Group chats are mostly humans talking to each other; the planner must not butt in."""
import re
from typing import Literal

Intent = Literal["chat", "plan", "explain"]

PLAN_VERBS = r"(generate|create|make|build|plan|update|redo|regenerate|refresh|revise|rework|re-?plan|go ahead)"
PLAN_NOUNS = r"(itinerary|plan|trip|schedule|it)"
QUESTION_START = re.compile(r"^(@planner[,:]?\s*)?(why|how come|what|which|when|where|who|how|is|are|can|could|should|does|do|will|would)\b", re.I)
POLITE_REQUEST = re.compile(r"^(can|could|would|will)\s+(you|we|u)\b", re.I)
MENTION = re.compile(r"@planner\b[,:]?\s*", re.I)


def addressed_to_planner(text: str, replying_to_ai: bool = False) -> bool:
    t = text.strip().lower()
    return replying_to_ai or "@planner" in t or t.startswith("planner")


def classify(text: str, addressed: bool, command: str | None = None) -> Intent:
    if command in ("itinerary_generate", "regenerate"):
        return "plan"
    if command in ("explain", "budget", "show_itinerary"):
        return "explain"
    if not addressed:
        return "chat"
    t = MENTION.sub("", text.strip()).strip().lower()
    if re.search(rf"\b{PLAN_VERBS}\b.*\b{PLAN_NOUNS}\b", t) or re.search(r"\b(let'?s|lets) (plan|go)\b", t):
        if POLITE_REQUEST.match(t) or not QUESTION_START.match(t):
            return "plan"
    if QUESTION_START.match(t) or "?" in t:
        return "explain"
    return "chat"
