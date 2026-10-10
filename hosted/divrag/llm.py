"""OpenRouter chat completions over plain HTTP (httpx), free models only.

OpenRouter tries `models` in order and falls back to the next one when a model
is down or rate-limited; the response names the model that answered.
"""

import logging
from dataclasses import dataclass
from typing import Dict, List, Sequence

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
UNAVAILABLE = "The AI service didn't respond. Please try again in a moment."
TOO_LONG = "The answer ran too long. Please try a narrower question."
MISCONFIGURED = "The demo's AI service isn't configured correctly. Please let the demo owner know."


@dataclass(frozen=True)
class Completion:
    text: str
    model: str


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

    async def complete(self, messages: List[Dict[str, str]]) -> Completion:
        body = {
            "models": self.models,
            "messages": messages,
            "temperature": self.temperature,
            "max_tokens": MAX_TOKENS,
            # Reasoning off by default: with it on, Nemotron 3 Ultra took up to a
            # minute on multi-part questions and could spend the whole token
            # budget reasoning, returning its notes instead of an answer.
            "reasoning": {"enabled": False} if self.reasoning == "off" else {"effort": self.reasoning, "exclude": True},
        }
        headers = {"Authorization": f"Bearer {self._api_key}", "X-Title": "NCDOT cross-division Q&A demo"}
        try:
            async with httpx.AsyncClient(timeout=TIMEOUT_SECONDS, transport=self._transport) as client:
                response = await client.post(API_URL, json=body, headers=headers)
        except httpx.HTTPError as exc:
            log.warning("OpenRouter request failed: %s", exc.__class__.__name__)
            raise LLMError(UNAVAILABLE, detail=str(exc)) from exc

        if response.status_code == 429:
            raise LLMError(BUSY, status=429, detail=response.text[:300])
        if response.status_code in (401, 402, 403):
            log.error("OpenRouter refused the request (%s): %s", response.status_code, response.text[:300])
            raise LLMError(MISCONFIGURED, detail=response.text[:300])
        if response.status_code != 200:
            log.warning("OpenRouter error %s: %s", response.status_code, response.text[:300])
            raise LLMError(UNAVAILABLE, detail=response.text[:300])

        data = response.json()
        # Errors from the upstream provider can arrive with HTTP 200.
        if data.get("error"):
            code = data["error"].get("code")
            log.warning("OpenRouter upstream error %s: %s", code, str(data["error"])[:300])
            raise LLMError(BUSY if code == 429 else UNAVAILABLE, status=429 if code == 429 else 503)
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
