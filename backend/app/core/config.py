from functools import lru_cache
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
    env_file=Path(__file__).resolve().parents[3] / ".env",
    extra="ignore",
)

    app_name: str = "Wayfare"
    environment: str = "development"
    database_url: str = "postgresql+psycopg://wayfare:wayfare@localhost:5432/wayfare"
    jwt_secret: str = "change-me-in-env"
    jwt_algorithm: str = "HS256"
    jwt_expire_minutes: int = 60 * 24 * 7
    cors_origins: str = "http://localhost:5173"
    rate_limit_enabled: bool = True
    bcrypt_rounds: int = 12
    gemini_api_key: str = ""
    gemini_base_url: str = "https://generativelanguage.googleapis.com"
    gemini_model: str = "gemini-2.0-flash"  # configurable; check Google AI Studio for current names
    llm_timeout_seconds: float = 90.0
    tool_timeout_seconds: float = 8.0
    overpass_timeout_seconds: float = 40.0
    dynamic_research_enabled: bool = True   # research destinations that have no curated data
    auto_replan: bool = False        # re-plan automatically when preferences change after a plan exists
    checkpointer: str = "memory"     # memory | postgres
    max_trip_days: int = 14
    telegram_bot_token: str = ""
    telegram_bot_username: str = ""        # without the @; used to turn "@YourBot" into "@planner"
    telegram_webhook_secret: str = ""
    telegram_mode: str = "off"             # off | webhook | polling
    telegram_api_base: str = "https://api.telegram.org"
    public_web_url: str = "http://localhost:5173"   # used for links the bot sends
    planner_mode: str = "graph"  # "graph" (LangGraph) or "stub" (echo only, used by chat tests)

    @property
    def cors_origin_list(self) -> list[str]:
        return [o.strip() for o in self.cors_origins.split(",") if o.strip()]


@lru_cache
def get_settings() -> Settings:
    return Settings()

