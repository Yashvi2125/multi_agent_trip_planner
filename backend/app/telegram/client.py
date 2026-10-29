"""Minimal Telegram Bot API client. Plain httpx so tests can swap the transport; no framework needed."""
import logging
from typing import Any

import httpx

log = logging.getLogger("wayfare.telegram")
MAX_TEXT = 4096


class TelegramError(Exception):
    pass


class TelegramClient:
    def __init__(self, token: str, base: str = "https://api.telegram.org", transport: httpx.BaseTransport | None = None,
                 timeout: float = 10.0):
        self.token = token
        self._url = f"{base.rstrip('/')}/bot{token}/"
        self._http = httpx.Client(timeout=timeout, transport=transport)

    @property
    def bot_id(self) -> int | None:
        head = self.token.split(":", 1)[0]
        return int(head) if head.isdigit() else None

    def call(self, method: str, **params: Any) -> Any:
        try:
            r = self._http.post(self._url + method, json={k: v for k, v in params.items() if v is not None})
            body = r.json()
        except (httpx.HTTPError, ValueError) as e:
            raise TelegramError(f"{method} failed: {type(e).__name__}") from e
        if not body.get("ok"):
            raise TelegramError(f"{method} rejected: {body.get('description', r.status_code)}")
        return body.get("result")

    def send_message(self, chat_id: int, text: str, reply_markup: dict | None = None) -> Any:
        return self.call("sendMessage", chat_id=chat_id, text=text[:MAX_TEXT], reply_markup=reply_markup,
                         disable_web_page_preview=True)

    def answer_callback(self, callback_id: str, text: str) -> Any:
        return self.call("answerCallbackQuery", callback_query_id=callback_id, text=text[:200])

    def send_typing(self, chat_id: int) -> Any:
        return self.call("sendChatAction", chat_id=chat_id, action="typing")

    def get_updates(self, offset: int | None, timeout: int = 25) -> list[dict]:
        return self.call("getUpdates", offset=offset, timeout=timeout, allowed_updates=["message", "callback_query"]) or []

    def set_webhook(self, url: str, secret: str) -> Any:
        return self.call("setWebhook", url=url, secret_token=secret or None,
                         allowed_updates=["message", "callback_query"])
