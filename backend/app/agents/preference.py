from datetime import date

from app.agents.llm import LLMClient
from app.schemas.agents import ExtractionResult

SYSTEM = """You extract travel preferences from one message in a group chat planning a trip.

Return:
- preferences (soft, "would be nice"): category is one of interest | dislike | style | food | stay.
  Use "dislike" for things the person wants to avoid but could tolerate. weight 1-5 (5 = strongly stated).
  Use short, general topics like: nightlife, beaches, adventure, culture, food, relaxation, nature, shopping, cafes.
- constraints (hard, non-negotiable): max_budget (amount in rupees; applies_to_group=true only if the
  message is about the whole group's budget), dietary, accessibility, unavailable_day (ISO dates),
  must_include, must_avoid. Only use must_avoid / must_include when the person is firm
  ("I can't", "must", "no way", "allergic"); otherwise it is a soft preference.

Rules: never invent anything not in the message. Small talk, questions and logistics produce empty lists.
Today's date is {today}. The trip is to {destination}."""


def extract_preferences(llm: LLMClient, text: str, destination: str, today: date | None = None) -> ExtractionResult:
    system = SYSTEM.format(today=(today or date.today()).isoformat(), destination=destination)
    return llm.structured(ExtractionResult, system, text)
