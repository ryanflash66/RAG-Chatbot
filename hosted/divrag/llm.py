"""OpenRouter chat completions over plain HTTP (httpx), free models only.

OpenRouter tries `models` in order and falls back to the next one when a model
is down or rate-limited; the response names the model that answered.
"""

import logging
from dataclasses import dataclass
from typing import Dict, List, Optional, Sequence

import httpx

API_URL = "https://openrouter.ai/api/v1/chat/completions"
# Answers are a few sentences; a long one is cut off and reported as an error.
MAX_TOKENS = 1200
TIMEOUT_SECONDS = 50.0

log = logging.getLogger(__name__)


class LLMError(Exception):
    """The model could not answer. `user_message` is safe to show in the browser."""

    def __init__(self, user_message: str, status: int = 503, detail: str = ""):
        super().__init__(detail or user_message)
        self.user_message = user_message
        self.status = status


BUSY = "The free AI model is busy right now (rate limit reached). Please wait a minute and try again."
DAILY_LIMIT = "The demo has reached today's free usage limit. Please try again tomorrow."
TOO_SLOW = "That took too long to answer. Please ask again."
UNAVAILABLE = "The AI service didn't respond. Please try again in a moment."
TOO_LONG = "The answer ran too long. Please try a narrower question."
MISCONFIGURED = "The demo's AI service isn't configured correctly. Please let the demo owner know."


@dataclass(frozen=True)
class Completion:
    text: str
    model: str


# OpenRouter's docs show only the generic 429 body; the daily cap on free models
# arrives as "Rate limit exceeded: free-models-per-day ..." in the message, so
# match the message and metadata text rather than one exact field.
_DAILY_MARKERS = ("free-models-per-day", "per-day", "per day")


def _rate_limited(detail: str) -> LLMError:
    """BUSY for a per-minute limit, DAILY_LIMIT when the free daily cap is spent."""
    daily = any(marker in detail.lower() for marker in _DAILY_MARKERS)
    return LLMError(DAILY_LIMIT if daily else BUSY, status=429, detail=detail[:300])


class OpenRouterClient:
    def __init__(self, api_key: str, models: Sequence[str], temperature: float = 0.1,
                 reasoning: str = "off", transport: "httpx.AsyncBaseTransport | None" = None):
        if not models:
            raise ValueError("at least one model is required")
        self._api_key = api_key
        self.models = list(models)
        self.temperature = temperature
        self.reasoning = reasoning
        self._transport = transport

    def retry_models(self, used: str) -> List[str]:
        """The models for a second attempt after `used` answered: the ones after it, or `used` again if it was the last."""
        if used in self.models:
            return self.models[self.models.index(used) + 1:] or [used]
        return self.models[1:] or self.models

    async def complete(self, messages: List[Dict[str, str]], models: Optional[Sequence[str]] = None) -> Completion:
        """Ask OpenRouter; `models` replaces the configured fallback list for this call."""
        body = {
            "models": list(models) if models else self.models,
            "messages": messages,
            "temperature": self.temperature,
            "max_tokens": MAX_TOKENS,
            # Reasoning off by default: with it on, Nemotron 3 Ultra took up to a
            # minute on multi-part questions and could spend the whole token
            # budget reasoning, returning its notes instead of an answer.
            "reasoning": {"enabled": False} if self.reasoning == "off" else {"effort": self.reasoning, "exclude": True},
            # Defence in depth behind the ":free" model check: never route to a priced endpoint.
            "provider": {"max_price": {"prompt": 0, "completion": 0}},
        }
        headers = {"Authorization": f"Bearer {self._api_key}", "X-Title": "NCDOT cross-division Q&A demo"}
        try:
            async with httpx.AsyncClient(timeout=TIMEOUT_SECONDS, transport=self._transport) as client:
                response = await client.post(API_URL, json=body, headers=headers)
        except httpx.HTTPError as exc:
            log.warning("OpenRouter request failed: %s", exc.__class__.__name__)
            raise LLMError(UNAVAILABLE, detail=str(exc)) from exc

        if response.status_code == 429:
            raise _rate_limited(response.text[:2000])
        if response.status_code in (401, 402, 403):
            log.error("OpenRouter refused the request (%s): %s", response.status_code, response.text[:300])
            raise LLMError(MISCONFIGURED, detail=response.text[:300])
        if response.status_code != 200:
            log.warning("OpenRouter error %s: %s", response.status_code, response.text[:300])
            raise LLMError(UNAVAILABLE, detail=response.text[:300])

        try:
            data = response.json()
        except ValueError as exc:
            raise LLMError(UNAVAILABLE, detail=f"non-JSON response: {response.text[:300]}") from exc
        if not isinstance(data, dict):
            raise LLMError(UNAVAILABLE, detail=f"unexpected response: {str(data)[:300]}")
        # Errors from the upstream provider can arrive with HTTP 200.
        if data.get("error"):
            error = data["error"]
            code = error.get("code") if isinstance(error, dict) else None
            log.warning("OpenRouter upstream error %s: %s", code, str(error)[:300])
            if code == 429:
                raise _rate_limited(str(error))
            raise LLMError(UNAVAILABLE, detail=str(error)[:300])
        try:
            choice = data["choices"][0]
            text = choice["message"].get("content") or ""
        except (KeyError, IndexError, TypeError) as exc:
            raise LLMError(UNAVAILABLE, detail=str(data)[:300]) from exc
        if choice.get("finish_reason") == "length":
            raise LLMError(TOO_LONG, detail="answer cut off at max_tokens")
        if not text.strip():
            raise LLMError(UNAVAILABLE, detail="empty answer")
        return Completion(text=text.strip(), model=data.get("model") or self.models[0])
