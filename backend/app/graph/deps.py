from dataclasses import dataclass
from datetime import date
from typing import Callable

from app.agents.dynamic_research import DynamicResearcher
from app.agents.llm import GeminiClient, LLMClient
from app.core.config import get_settings
from app.tools.base import GeocodeProvider, WeatherProvider
from app.tools.geocode import NominatimProvider
from app.tools.places import OverpassProvider
from app.tools.weather import OpenMeteoProvider


@dataclass
class Deps:
    """Everything the graph needs from the outside world. Tests pass fakes; production passes real providers.
    llm=None means 'no model available': extraction is skipped and planning uses the rule-based fallback."""
    llm: LLMClient | None
    weather: WeatherProvider
    geocoder: GeocodeProvider | None = None
    today: Callable[[], date] = date.today
    auto_replan: bool = False
    dynamic: DynamicResearcher | None = None    # None = only curated destinations can be planned


def default_deps() -> Deps:
    s = get_settings()
    llm = GeminiClient() if s.gemini_api_key else None
    weather, geocoder = OpenMeteoProvider(), NominatimProvider()
    dynamic = (DynamicResearcher(geocoder, OverpassProvider(), climate=weather, llm=llm)
               if s.dynamic_research_enabled else None)
    return Deps(llm=llm, weather=weather, geocoder=geocoder, auto_replan=s.auto_replan, dynamic=dynamic)
