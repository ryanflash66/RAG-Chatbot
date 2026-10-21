"""OpenRouter chat completions over plain HTTP (httpx), free models only.

OpenRouter tries `models` in order and falls back to the next one when a model
is down or rate-limited; the response names the model that answered.

complete() waits for the whole answer; complete_stream() hands it over as it is
written (server-sent events), so the page can show the text while the model is
still writing (DAR-629). Both turn every failure into the same LLMErrors.
"""

import json
import logging
import ssl
from dataclasses import dataclass
from typing import Any, AsyncIterator, Dict, List, Optional, Sequence

import httpx

API_URL = "https://openrouter.ai/api/v1/chat/completions"
# Answers are a few sentences; a long one is cut off and reported as an error.
MAX_TOKENS = 1200
TIMEOUT_SECONDS = 50.0

log = logging.getLogger(__name__)

_tls: Optional[ssl.SSLContext] = None


def tls_context() -> ssl.SSLContext:
    """One TLS context for every call. Building one reads the CA bundle: 0.3 s per
    httpx client locally, on the event loop, which held the stream's "Writing the
    answer" step back that long. The model warm-up builds it ahead of the first question."""
    global _tls
    if _tls is None:
        _tls = httpx.create_ssl_context()
    return _tls


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


def _status_error(status: int, text: str) -> Optional[LLMError]:
    """The error a reply's HTTP status stands for; None for 200."""
    if status == 429:
        return _rate_limited(text[:2000])
    if status in (401, 402, 403):
        log.error("OpenRouter refused the request (%s): %s", status, text[:300])
        return LLMError(MISCONFIGURED, detail=text[:300])
    if status != 200:
        log.warning("OpenRouter error %s: %s", status, text[:300])
        return LLMError(UNAVAILABLE, detail=text[:300])
    return None


def _upstream_error(error: Any) -> LLMError:
    """The error for an `error` object in a reply.

    Errors from the upstream provider can arrive with HTTP 200, and once a
    stream has started they can only arrive as an event in it.
    """
    code = error.get("code") if isinstance(error, dict) else None
    log.warning("OpenRouter upstream error %s: %s", code, str(error)[:300])
    if code == 429:
        return _rate_limited(str(error))
    return LLMError(UNAVAILABLE, detail=str(error)[:300])


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

    def _body(self, messages: List[Dict[str, str]], models: Optional[Sequence[str]], stream: bool) -> Dict:
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
        if stream:
            body["stream"] = True
        return body

    def _headers(self) -> Dict[str, str]:
        return {"Authorization": f"Bearer {self._api_key}", "X-Title": "NCDOT cross-division Q&A demo"}

    def _http(self) -> httpx.AsyncClient:
        if self._transport is not None:  # tests: a mock transport, no TLS
            return httpx.AsyncClient(timeout=TIMEOUT_SECONDS, transport=self._transport)
        return httpx.AsyncClient(timeout=TIMEOUT_SECONDS, verify=tls_context())

    async def complete(self, messages: List[Dict[str, str]], models: Optional[Sequence[str]] = None) -> Completion:
        """Ask OpenRouter; `models` replaces the configured fallback list for this call."""
        try:
            async with self._http() as client:
                response = await client.post(API_URL, json=self._body(messages, models, stream=False),
                                             headers=self._headers())
        except httpx.HTTPError as exc:
            log.warning("OpenRouter request failed: %s", exc.__class__.__name__)
            raise LLMError(UNAVAILABLE, detail=str(exc)) from exc

        error = _status_error(response.status_code, response.text)
        if error:
            raise error
        try:
            data = response.json()
        except ValueError as exc:
            raise LLMError(UNAVAILABLE, detail=f"non-JSON response: {response.text[:300]}") from exc
        if not isinstance(data, dict):
            raise LLMError(UNAVAILABLE, detail=f"unexpected response: {str(data)[:300]}")
        if data.get("error"):
            raise _upstream_error(data["error"])
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

    def complete_stream(self, messages: List[Dict[str, str]],
                        models: Optional[Sequence[str]] = None) -> "CompletionStream":
        """Ask OpenRouter for the answer as it is written: `async for piece in` the result.

        The same request as complete(), with `stream: true`. Failures raise the
        same LLMErrors while iterating; afterwards the stream's `text` and
        `model` are what complete() would have returned.
        """
        return CompletionStream(self, messages, models)


class CompletionStream:
    """One streamed answer. Iterating it yields the answer's text in pieces.

    `model` names the model that is answering (OpenRouter may have fallen back
    from the first one) from its first event on; `text` is the whole answer,
    stripped, once the iteration has finished.
    """

    def __init__(self, client: OpenRouterClient, messages: List[Dict[str, str]], models: Optional[Sequence[str]]):
        self._client = client
        self._messages = messages
        self._models = models
        self.model = (list(models) if models else client.models)[0]
        self.text = ""

    def __aiter__(self) -> AsyncIterator[str]:
        return self._pieces()

    async def _pieces(self) -> AsyncIterator[str]:
        client = self._client
        written: List[str] = []
        try:
            async with client._http() as http:
                body = client._body(self._messages, self._models, stream=True)
                async with http.stream("POST", API_URL, json=body, headers=client._headers()) as response:
                    if response.status_code != 200:
                        # Errors before the first token come back as an ordinary JSON reply.
                        await response.aread()
                        raise _status_error(response.status_code, response.text) or LLMError(UNAVAILABLE)
                    async for data in _sse_data(response.aiter_lines()):
                        if data == "[DONE]":
                            break
                        piece = self._read(data)
                        if piece:
                            written.append(piece)
                            yield piece
        except httpx.HTTPError as exc:
            log.warning("OpenRouter stream failed: %s", exc.__class__.__name__)
            raise LLMError(UNAVAILABLE, detail=str(exc)) from exc
        self.text = "".join(written).strip()
        if not self.text:
            raise LLMError(UNAVAILABLE, detail="empty answer")

    def _read(self, data: str) -> str:
        """The answer text in one event; raises the LLMError an error event stands for."""
        try:
            event = json.loads(data)
        except ValueError as exc:
            raise LLMError(UNAVAILABLE, detail=f"non-JSON event: {data[:300]}") from exc
        if not isinstance(event, dict):
            raise LLMError(UNAVAILABLE, detail=f"unexpected event: {data[:300]}")
        if event.get("error"):
            raise _upstream_error(event["error"])
        if event.get("model"):
            self.model = event["model"]
        choices = event.get("choices") or []  # the closing usage event has none
        if not isinstance(choices, list) or (choices and not isinstance(choices[0], dict)):
            raise LLMError(UNAVAILABLE, detail=f"unexpected event: {data[:300]}")
        if not choices:
            return ""
        choice = choices[0]
        if choice.get("finish_reason") == "length":
            raise LLMError(TOO_LONG, detail="answer cut off at max_tokens")
        if choice.get("finish_reason") == "error":
            raise LLMError(UNAVAILABLE, detail=f"stream ended with an error: {data[:300]}")
        delta = choice.get("delta")
        # The answer's content only: reasoning, if a provider sends it, is never shown.
        return (delta.get("content") or "") if isinstance(delta, dict) else ""


async def _sse_data(lines: AsyncIterator[str]) -> AsyncIterator[str]:
    """The data of each server-sent event, skipping comments such as ": OPENROUTER PROCESSING".

    OpenRouter sends those comments while a model starts up, to keep the
    connection open. An event's data may span several "data:" lines, joined
    with newlines; a blank line ends the event.
    """
    data: List[str] = []
    async for line in lines:
        if not line:
            if data:
                yield "\n".join(data)
                data = []
        elif line.startswith("data:"):
            value = line[5:]
            data.append(value[1:] if value.startswith(" ") else value)
    if data:
        yield "\n".join(data)
