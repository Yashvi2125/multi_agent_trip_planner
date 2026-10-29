"""Holds the process-wide Telegram client (None when no bot token is configured)."""
from app.core.config import get_settings
from app.telegram.client import TelegramClient

client: TelegramClient | None = None
_built = False


def configure(c: TelegramClient | None) -> None:
    global client, _built
    client, _built = c, True


def get_client() -> TelegramClient | None:
    global client, _built
    if not _built:
        s = get_settings()
        client = TelegramClient(s.telegram_bot_token, s.telegram_api_base) if s.telegram_bot_token else None
        _built = True
    return client
