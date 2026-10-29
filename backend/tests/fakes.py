from datetime import date

from app.agents.llm import LLMError
from app.schemas.agents import ExtractionResult
from app.schemas.itinerary import Answer, ItineraryDraft
from app.tools.base import ToolError, WeatherDay


class FakeLLM:
    """Routes by schema. `table` maps message text → ExtractionResult payload. `draft` is a callable or
    ItineraryDraft payload for the itinerary agent (None → raise, forcing the fallback planner)."""

    def __init__(self, table: dict[str, dict] | None = None, draft=None, answer: str | None = None):
        self.table, self.draft, self.answer = table or {}, draft, answer
        self.calls: list[tuple[str, str]] = []

    def structured(self, schema, system, user):
        self.calls.append((schema.__name__, user))
        if user == "BOOM":
            raise LLMError("down")
        if schema is ExtractionResult:
            return schema.model_validate(self.table.get(user, {}))
        if schema is ItineraryDraft:
            if self.draft is None:
                raise LLMError("no draft configured")
            payload = self.draft(user) if callable(self.draft) else self.draft
            return schema.model_validate(payload)
        if schema is Answer:
            if self.answer is None:
                raise LLMError("no answer configured")
            return Answer(text=self.answer)
        raise LLMError("unknown schema")


class FakeWeather:
    def __init__(self, fail=False):
        self.fail = fail

    def forecast(self, lat, lon, start, end):
        if self.fail:
            raise ToolError("down")
        return [WeatherDay(start, "Clear", 32, 22, 5)]
