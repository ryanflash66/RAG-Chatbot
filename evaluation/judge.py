"""The LLM judge: one call per question that returns the verdicts all four RAGAS metrics need.

RAGAS makes several LLM calls per metric (statement extraction, then one
verdict pass per metric). On a free model with a daily request cap that is
too many, so one prompt asks for every verdict at once, worded after RAGAS's
own prompts, and metrics.py turns the verdicts into scores:

    answer_statements     -> faithfulness       (RAGAS: statement extraction + NLI verdicts)
    generated_questions,
    noncommittal          -> answer relevancy   (RAGAS: question generation, strictness 3)
    passage_verdicts      -> context precision  (RAGAS: "useful in arriving at the answer")
    reference_statements  -> context recall     (RAGAS: "can be attributed to the context")

ChatClient talks to any OpenAI-compatible chat completions endpoint, so the
judge can be a free OpenRouter model (the default), a local Ollama model, or
the OpenAI API when that arrives (DAR-637): --judge-base-url and --judge-models
in run_ragas.py. On OpenRouter only ":free" models are accepted, and the
request also carries a zero max price, as the hosted app's client does.
"""

import json
import re
from typing import Any, Dict, List, Optional, Sequence

import httpx

# The hosted client's error mapping, so a 429 means BUSY or DAILY_LIMIT here exactly as in the app.
from divrag.llm import MISCONFIGURED, TOO_LONG, UNAVAILABLE, Completion, LLMError, _status_error, _upstream_error

OPENROUTER_URL = "https://openrouter.ai/api/v1"
FREE_SUFFIX = ":free"
# The verdicts for a long answer and seven passages run to about 1,500 tokens;
# reasoning models spend more before them.
JUDGE_MAX_TOKENS = 8000
TIMEOUT_SECONDS = 300.0


def is_openrouter(base_url: str) -> bool:
    return "openrouter.ai" in base_url


class JudgeError(Exception):
    """The judge's reply could not be read as the verdicts."""


class ChatClient:
    """An OpenAI-compatible chat client with the same complete() as divrag's OpenRouterClient.

    It stands in for OpenRouterClient where the hosted Answerer or the judge
    should talk to another endpoint (a local model, OpenAI). Failures raise
    the hosted app's LLMErrors, so a 429 is BUSY or DAILY_LIMIT the same way.
    """

    def __init__(self, base_url: str, api_key: str, models: Sequence[str], temperature: float = 0.0,
                 max_tokens: int = 1200, json_mode: bool = False, reasoning: Optional[str] = None,
                 transport: Optional[httpx.AsyncBaseTransport] = None):
        if not models:
            raise ValueError("at least one model is required")
        self.base_url = base_url.rstrip("/")
        self.models = list(models)
        if is_openrouter(self.base_url):
            paid = [m for m in self.models if not m.endswith(FREE_SUFFIX)]
            if paid:
                raise ValueError(f"Only free OpenRouter models (ending in {FREE_SUFFIX!r}) are allowed; got {paid}")
        self._api_key = api_key
        self.temperature = temperature
        self.max_tokens = max_tokens
        self.json_mode = json_mode
        # Reasoning effort for reasoning models ("low", "medium", "high"); None leaves the model's default.
        # gpt-oss:20b at its default spent all 6,000 tokens reasoning on B1's verdicts.
        self.reasoning = reasoning
        self._transport = transport

    def retry_models(self, used: str) -> List[str]:
        if used in self.models:
            return self.models[self.models.index(used) + 1:] or [used]
        return self.models[1:] or self.models

    def _body(self, messages: List[Dict[str, str]], model: str, models: Sequence[str]) -> Dict[str, Any]:
        body: Dict[str, Any] = {"model": model, "messages": messages, "temperature": self.temperature,
                                "max_tokens": self.max_tokens}
        if self.json_mode:
            body["response_format"] = {"type": "json_object"}
        if is_openrouter(self.base_url):
            body["models"] = list(models)
            body["provider"] = {"max_price": {"prompt": 0, "completion": 0}}
            if self.reasoning:
                body["reasoning"] = {"effort": self.reasoning, "exclude": True}
        elif self.reasoning:
            body["reasoning_effort"] = self.reasoning  # OpenAI's and Ollama's name for it
        return body

    async def complete(self, messages: List[Dict[str, str]], models: Optional[Sequence[str]] = None) -> Completion:
        models = list(models) if models else self.models
        # OpenRouter falls back between the models itself; elsewhere each is tried in turn.
        attempts = [models[0]] if is_openrouter(self.base_url) else models
        error: Optional[LLMError] = None
        for model in attempts:
            try:
                return await self._complete(messages, model, models)
            except LLMError as exc:
                if exc.status == 429 or exc.user_message == MISCONFIGURED:
                    raise
                error = exc
        raise error or LLMError(UNAVAILABLE)

    async def _complete(self, messages: List[Dict[str, str]], model: str, models: Sequence[str]) -> Completion:
        client = httpx.AsyncClient(timeout=TIMEOUT_SECONDS, transport=self._transport) if self._transport \
            else httpx.AsyncClient(timeout=TIMEOUT_SECONDS)
        try:
            async with client:
                response = await client.post(f"{self.base_url}/chat/completions", json=self._body(messages, model, models),
                                             headers={"Authorization": f"Bearer {self._api_key}"})
        except httpx.HTTPError as exc:
            raise LLMError(UNAVAILABLE, detail=f"{exc.__class__.__name__}: {exc}") from exc
        error = _status_error(response.status_code, response.text)
        if error:
            raise error
        try:
            data = response.json()
            error = data.get("error")
            choice, text = {}, ""
            if not error:
                choice = data["choices"][0]
                text = choice["message"].get("content") or ""
        except (ValueError, KeyError, IndexError, TypeError, AttributeError) as exc:
            raise LLMError(UNAVAILABLE, detail=f"unexpected response: {response.text[:300]}") from exc
        if error:
            # Upstream errors, the daily cap among them, can arrive with HTTP 200.
            raise _upstream_error(error)
        if choice.get("finish_reason") == "length":
            raise LLMError(TOO_LONG, detail="answer cut off at max_tokens")  # as OpenRouterClient does
        if not text.strip():
            raise LLMError(UNAVAILABLE, detail=f"empty answer (finish_reason {choice.get('finish_reason')})")
        return Completion(text=text.strip(), model=data.get("model") or model)


JUDGE_SYSTEM = """You are an impartial evaluator of a retrieval-augmented question answering system for North Carolina Department of Transportation manuals.
You apply the RAGAS evaluation definitions strictly and literally. You judge only from the texts given; your own knowledge of the topic does not count as support.
You reply with one JSON object and nothing else."""

JUDGE_USER = """Question:
{question}

Retrieved passages, numbered as the system received them:

{passages}

The system's answer:
{answer}

Reference answer (written by a person who checked the manual):
{reference}

Do these four tasks.

1. answer_statements (faithfulness). Break the system's answer into short standalone factual statements: one fact each, pronouns replaced by what they refer to, citation markers like [1] left out. For each statement set "supported" to true only if it can be directly inferred from the retrieved passages, else false. If the answer states no facts (for example it says it could not find an answer), return [].

2. generated_questions and noncommittal (answer relevancy). Write 3 different questions that the system's answer answers completely. Set "noncommittal" to true if the answer is evasive, vague or ambiguous, or says it cannot answer (for example "I don't know" or "the documents don't cover that"); otherwise false.

3. passage_verdicts (context precision). For every passage number from 1 to {n_passages}, set "useful" to true if the passage was useful in arriving at the reference answer (it holds information the reference answer states), else false. {no_reference_precision}

4. reference_statements (context recall). Break the reference answer into short standalone statements. For each, set "attributed" to true if it can be attributed to the retrieved passages (they state it or it follows directly from them), else false. {no_reference_recall}

Reply with JSON only, in exactly this shape:
{{"answer_statements": [{{"statement": "...", "supported": true}}],
 "generated_questions": ["...", "...", "..."],
 "noncommittal": false,
 "passage_verdicts": [{{"passage": 1, "useful": true}}],
 "reference_statements": [{{"statement": "...", "attributed": true}}]}}"""


def judge_messages(question: str, passages: Sequence[str], answer: str, reference: Optional[str]) -> List[Dict[str, str]]:
    """The judge's messages. `passages` are the full texts the answering model was given, in its order."""
    numbered = "\n\n---\n\n".join(f"[{n}]\n{text}" for n, text in enumerate(passages, 1))
    user = JUDGE_USER.format(
        question=question, passages=numbered or "(none)", answer=answer, n_passages=len(passages),
        reference=reference or "(none: this question has no reference answer)",
        no_reference_precision="" if reference else "There is no reference answer, so judge whether the passage is useful for answering the question.",
        no_reference_recall="" if reference else "There is no reference answer, so return [].",
    )
    return [{"role": "system", "content": JUDGE_SYSTEM}, {"role": "user", "content": user}]


def _json_object(text: str) -> Dict[str, Any]:
    text = re.sub(r"^```(?:json)?\s*|\s*```$", "", text.strip())
    start, end = text.find("{"), text.rfind("}")
    if start < 0 or end <= start:
        raise JudgeError(f"no JSON object in the reply: {text[:200]!r}")
    try:
        data = json.loads(text[start:end + 1])
    except ValueError as exc:
        raise JudgeError(f"reply is not valid JSON: {exc}") from exc
    if not isinstance(data, dict):
        raise JudgeError("reply is not a JSON object")
    return data


def _flag(value: Any) -> bool:
    """A verdict as a bool; models sometimes write "yes", 1 or "true"."""
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return value != 0
    return str(value).strip().lower() in ("true", "yes", "1", "supported", "attributed", "useful")


def _statements(data: Dict[str, Any], key: str, verdict: str) -> List[Dict[str, Any]]:
    items = data.get(key) or []
    if not isinstance(items, list):
        raise JudgeError(f"{key} is not a list")
    out = []
    for item in items:
        if isinstance(item, dict) and str(item.get("statement") or "").strip():
            out.append({"statement": str(item["statement"]).strip(), verdict: _flag(item.get(verdict))})
    return out


def parse_verdicts(text: str, n_passages: int, has_reference: bool = True) -> Dict[str, Any]:
    """The judge's reply as clean verdicts; raises JudgeError when it can't be read.

    `useful` has one entry per passage, in passage order; a passage the judge
    left out counts as not useful and is counted in `missing_passages`. A reply
    with no passage verdicts at all, or no reference statements although there
    is a reference, skipped a task (gpt-oss did on X3's long answer) and would
    score 0 for it, so it is an error and the question is asked again.
    """
    data = _json_object(text)
    questions = data.get("generated_questions") or []
    if not isinstance(questions, list):
        raise JudgeError("generated_questions is not a list")
    useful: Dict[int, bool] = {}
    for item in data.get("passage_verdicts") or []:
        if isinstance(item, dict):
            try:
                n = int(item.get("passage"))
            except (TypeError, ValueError):
                continue
            if 1 <= n <= n_passages:
                useful[n] = _flag(item.get("useful"))
    reference_statements = _statements(data, "reference_statements", "attributed")
    if n_passages and not useful:
        raise JudgeError("no passage verdicts")
    if has_reference and not reference_statements:
        raise JudgeError("no reference statements")
    return {
        "answer_statements": _statements(data, "answer_statements", "supported"),
        "generated_questions": [str(q).strip() for q in questions if str(q).strip()],
        "noncommittal": _flag(data.get("noncommittal", False)),
        "useful": [useful.get(n, False) for n in range(1, n_passages + 1)],
        "missing_passages": sum(1 for n in range(1, n_passages + 1) if n not in useful),
        "reference_statements": reference_statements,
    }
