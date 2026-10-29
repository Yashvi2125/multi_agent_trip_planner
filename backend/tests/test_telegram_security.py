"""The webhook is an unauthenticated public URL, so the secret check must not fail open outside development."""
import httpx
import pytest

from app.core.config import get_settings
from app.telegram import service
from app.telegram.client import TelegramClient

HEADER = "x-telegram-bot-api-secret-token"
BODY = {"update_id": 1}


@pytest.fixture()
def settings(monkeypatch):
    s = get_settings()
    api = httpx.MockTransport(lambda r: httpx.Response(200, json={"ok": True, "result": {}}))
    service.configure(TelegramClient("111:AAA", transport=api))
    monkeypatch.setattr(s, "telegram_webhook_secret", "", raising=False)
    yield s
    service.configure(None)
    service._built = False


def test_no_secret_outside_development_is_refused(client, settings, monkeypatch):
    monkeypatch.setattr(settings, "environment", "production", raising=False)
    r = client.post("/api/telegram/webhook", json=BODY)
    assert r.status_code == 403 and "secret" in r.json()["error"]["message"]


def test_no_secret_in_development_still_works_for_local_setups(client, settings):
    assert settings.environment == "development"
    assert client.post("/api/telegram/webhook", json=BODY).status_code == 200


def test_with_a_secret_wrong_or_missing_header_is_refused_and_right_one_passes(client, settings, monkeypatch):
    monkeypatch.setattr(settings, "environment", "production", raising=False)
    monkeypatch.setattr(settings, "telegram_webhook_secret", "s3cret-value", raising=False)
    assert client.post("/api/telegram/webhook", json=BODY).status_code == 403
    assert client.post("/api/telegram/webhook", json=BODY, headers={HEADER: "nope"}).status_code == 403
    assert client.post("/api/telegram/webhook", json=BODY, headers={HEADER: "s3cret-value"}).status_code == 200
