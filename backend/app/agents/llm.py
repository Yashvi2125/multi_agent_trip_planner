import json
import logging
import time
from typing import Protocol, TypeVar

import httpx
from pydantic import BaseModel, ValidationError

from app.core.config import get_settings

log = logging.getLogger("wayfare.llm")
T = TypeVar("T", bound=BaseModel)


class LLMError(Exception):
    """Raised when the model is unreachable or keeps returning unusable output."""


class LLMClient(Protocol):
    def structured(self, schema: type[T], system: str, user: str) -> T: ...


class GeminiClient:
    """Minimal Gemini REST client with JSON-mode output, Pydantic validation and one repair retry.
    Uses plain httpx so the transport can be mocked in tests."""


    def __init__(self, api_key: str | None = None, model: str | None = None,
                 transport: httpx.BaseTransport | None = None):
        s = get_settings()
        self.api_key = api_key if api_key is not None else s.gemini_api_key
        self.model = model or s.gemini_model
        self.url = f"{s.gemini_base_url.rstrip('/')}/v1beta/models/{self.model}:generateContent"
        self._http = httpx.Client(timeout=s.llm_timeout_seconds, transport=transport)

    
    
    def _call(self, system: str, user: str) -> str:
        if not self.api_key:
            raise LLMError("No Gemini API key configured")

        body = {
            "systemInstruction": {"parts": [{"text": system}]},
            "contents": [{"role": "user", "parts": [{"text": user}]}],
            "generationConfig": {
                "temperature": 0,
                "responseMimeType": "application/json",
            },
        }

        retryable_statuses = {429, 500, 502, 503, 504}

        for attempt in range(3):
            try:
                r = self._http.post(
                    self.url,
                    json=body,
                    headers={"x-goog-api-key": self.api_key},
                )

                if r.status_code in retryable_statuses:
                    log.warning(
                        "Gemini temporarily unavailable: HTTP %s "
                        "(attempt %s/3)",
                        r.status_code,
                        attempt + 1,
                    )

                    if attempt < 2:
                        time.sleep(attempt + 1)
                        continue

                    raise LLMError(
                        f"Gemini unavailable after 3 attempts "
                        f"(HTTP {r.status_code})"
                    )

                if r.is_error:
                    log.error(
                        "Gemini HTTP error: status=%s, response=%s",
                        r.status_code,
                        r.text[:1000],
                    )

                r.raise_for_status()
                return r.json()["candidates"][0]["content"]["parts"][0]["text"]

            except httpx.TimeoutException as e:
                log.warning(
                    "Gemini timeout (attempt %s/3)", attempt + 1
                )
                if attempt < 2:
                    time.sleep(attempt + 1)
                    continue
                raise LLMError(
                    "Gemini request timed out after 3 attempts"
                ) from e

            except LLMError:
                raise

            except httpx.HTTPStatusError as e:
                raise LLMError(
                    f"Gemini returned HTTP {e.response.status_code}"
                ) from e

            except (httpx.HTTPError, KeyError, IndexError, ValueError) as e:
                raise LLMError(
                    f"Gemini request failed: {type(e).__name__}"
                ) from e

        raise LLMError("Gemini request failed after retries")


    def structured(self, schema: type[T], system: str, user: str) -> T:
        sys_full = f"{system}\n\nReply with JSON only, matching this JSON Schema:\n{json.dumps(schema.model_json_schema())}"
        prompt, last_err = user, ""
        for _ in range(2):  # original + one repair attempt
            text = self._call(sys_full, prompt)
            try:
                return schema.model_validate_json(text)
            except ValidationError as e:
                last_err = str(e)[:500]
                log.warning("LLM output failed validation: %s", last_err)
                prompt = f"{user}\n\nYour previous reply was invalid ({last_err}). Return corrected JSON only."
        raise LLMError("Model returned invalid structured output twice")
