"""Tests for the hosted demo's answers: citations, refusals, prompt, settings and the OpenRouter client."""

import asyncio
import json
import sys
import time
from pathlib import Path

import httpx
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "hosted"))

from divrag import llm as llm_module  # noqa: E402
from divrag.answer import NOT_FOUND, SUGGEST_CANDIDATES, Answerer, attach_sources, build_messages, cited_numbers  # noqa: E402
from divrag.config import load_settings  # noqa: E402
from divrag.divisions import BY_ID  # noqa: E402
from divrag.index_file import Hit  # noqa: E402
from divrag.llm import BUSY, DAILY_LIMIT, UNAVAILABLE, Completion, LLMError, OpenRouterClient  # noqa: E402
from divrag.timing import StepTimer  # noqa: E402

UAM = "20220713 NCDOT UAM Ver 2-0.pdf"
TMP = "TMP Design Manual (Combined, No Links).pdf"


def _hit(page, text="text", source=UAM, division="utilities", section=None, score=1.0):
    return Hit(score, {"text": text, "source": source, "page": page, "section": section, "division": division})


def test_citations_are_renumbered_in_order_with_document_page_and_url():
    hits = [_hit(126, section="3.6.4.1 Lane and Road Closures"), _hit(127), _hit(101)]

    text, sources = attach_sources("Closure within 5 feet [3]. Detours are reimbursed [1, 2].", hits)

    assert text == "Closure within 5 feet [1]. Detours are reimbursed [2][3]."
    assert [(s.n, s.page) for s in sources] == [(1, 101), (2, 126), (3, 127)]
    assert sources[1].title.startswith("Utilities Accommodation Manual")
    assert sources[1].section == "3.6.4.1 Lane and Road Closures"
    assert sources[1].url.startswith("https://connect.ncdot.gov/") and sources[1].url.endswith("#page=126")
    assert sources[1].division == "utilities"


def test_passages_from_the_same_page_share_one_source_and_bad_markers_are_dropped():
    hits = [_hit(18, "a"), _hit(18, "b"), _hit(40)]

    text, sources = attach_sources("Three days [2]. Also [1][2]. Not real [9]. 【3】", hits)

    assert [s.page for s in sources] == [18, 40]
    assert text == "Three days [1]. Also [1]. Not real. [2]"


def _merged(*parts):
    chunks = [{"text": text, "source": UAM, "page": page, "section": section, "division": "utilities"}
              for text, page, section in parts]
    first = chunks[0]
    return dict(first, text="\n\n".join(c["text"] for c in chunks), page_end=chunks[-1]["page"],
                section="; ".join(c["section"] for c in chunks), parts=chunks)


def test_a_merged_passage_is_cited_by_the_pages_the_answer_drew_on():
    passage = _merged(
        ("Barrier types: concrete barrier weighs 3,900 lbs.", 32, "5.4 Types"),
        ("The NC-PCB is 10 ft long, 24 in wide at the base and 32 in high.", 33, "5.4.1 NC-PCB"),
        ("Water-filled barrier is for 45 mph or less.", 34, "5.4.3 Water-Filled"),
    )

    text, sources = attach_sources("The NC-PCB is 10 ft long and 32 in high [1].", [Hit(1.0, passage)])

    (source,) = sources
    assert (source.page, source.page_end) == (33, None)
    assert source.section == "5.4.1 NC-PCB"
    assert source.url.endswith("#page=33")


def test_a_rule_spanning_two_pages_is_cited_with_both():
    passage = _merged(
        ("D) Drop-offs greater than 12 inches: 1. traffic barrier 2. wedge slope", 16, "2.4"),
        ("3. Provide a lateral distance of 6 feet; more than 3 days use traffic barrier", 17, "2.4"),
        ("Chapter 3 lane widths are 11 feet", 18, "3.3"),
    )

    _, sources = attach_sources(
        "Use traffic barrier or a wedge slope, or shift traffic 6 feet; for more than 3 days use traffic barrier [1].",
        [Hit(1.0, passage)],
    )

    assert (sources[0].page, sources[0].page_end) == (16, 17)


def test_cited_numbers_handles_ranges_and_lists():
    assert cited_numbers("x [2-3] y [1; 3] z [5]", 4) == [2, 3, 1]


def test_prompt_frames_the_asker_but_contains_only_the_targets_passages():
    hits = [_hit(126, "Lane closure within 5 feet.")]
    system, user = build_messages("When is a lane closure needed?", BY_ID["wztc"], BY_ID["utilities"], hits)

    assert "Utilities" in system["content"] and "Work Zone Traffic Control" in system["content"]
    assert NOT_FOUND in system["content"]
    assert "[1] (Utilities Accommodation Manual" in user["content"] and "PDF page 126" in user["content"]
    assert "When is a lane closure needed?" in user["content"]


class _FakeLLM:
    """Replies with `text`; a list of texts is replayed one per call (the last repeats)."""

    def __init__(self, text):
        self.texts = [text] if isinstance(text, str) else list(text)
        self.calls = []
        self.models_used = []

    def retry_models(self, used):
        return ["test/second:free"]

    async def complete(self, messages, models=None):
        self.calls.append(messages)
        self.models_used.append(models)
        text = self.texts[min(len(self.calls), len(self.texts)) - 1]
        if isinstance(text, Exception):
            raise text
        return Completion(text, "test/model:free" if models is None else models[0])


class _FakeRetriever:
    """Returns a fixed best score per division; records which divisions were searched."""

    def __init__(self, scores, reranker=True):
        self.scores = scores
        self.reranker = object() if reranker else None
        self.searched = []
        self.candidates = []

    def retrieve(self, question, division, k=5, timer=None, candidates=None):
        self.searched.append(division)
        self.candidates.append(candidates)
        source = TMP if division == "wztc" else UAM
        return [_hit(10, source=source, division=division, score=self.scores[division])]


def _answer(llm_text, scores=None, target="utilities"):
    retriever = _FakeRetriever(scores or {"wztc": -9.0, "utilities": -9.0})
    answerer = Answerer(retriever, _FakeLLM(llm_text))
    hits = retriever.retrieve("q", target)
    return asyncio.run(answerer.answer("q", BY_ID["wztc"], BY_ID[target], hits)), retriever


def _ask_with_retry(replies, score, seconds_left=None, reranker=True, **options):
    """Answer a Utilities question whose best passage scores `score`; returns (result, llm)."""
    retriever = _FakeRetriever({"wztc": -9.0, "utilities": score}, reranker=reranker)
    llm = _FakeLLM(replies)
    answerer = Answerer(retriever, llm, **options)
    hits = retriever.retrieve("q", "utilities")
    deadline = None if seconds_left is None else time.monotonic() + seconds_left
    return asyncio.run(answerer.answer("q", BY_ID["utilities"], BY_ID["utilities"], hits, deadline)), llm


def test_answer_with_citations_is_not_a_refusal():
    result, _ = _answer("Three feet [1].")
    assert not result.refused
    assert result.answer == "Three feet [1]."
    assert len(result.sources) == 1 and result.sources[0].url.endswith("#page=10")


def test_not_in_documents_reply_is_a_refusal_with_no_sources():
    result, retriever = _answer(NOT_FOUND)

    assert result.refused
    assert result.sources == []
    assert "Utilities documents" in result.answer and "Utilities Accommodation Manual" in result.answer
    assert result.suggest == []  # the other division's best passage scored too low


def test_answer_without_any_citation_is_treated_as_a_refusal():
    result, _ = _answer("The rate is $50 per hour.")
    assert result.refused and result.sources == []
    assert "$50" not in result.answer


def test_refusal_suggests_the_other_division_when_its_documents_look_relevant():
    result, retriever = _answer(NOT_FOUND, scores={"wztc": 3.2, "utilities": -9.0})

    assert result.refused
    assert result.suggest == ["wztc"]
    assert retriever.candidates[-1] == SUGGEST_CANDIDATES  # a smaller rerank than the question's own
    assert "try asking Work Zone Traffic Control" in result.answer
    assert result.as_dict()["suggest"] == [{"id": "wztc", "name": "Work Zone Traffic Control"}]


@pytest.mark.parametrize("first", [NOT_FOUND, "The rate is three feet."])
def test_refusal_despite_strong_retrieval_is_retried_once_with_the_next_model(first):
    result, llm = _ask_with_retry([first, "Three feet [1]."], score=3.5, seconds_left=40)

    assert not result.refused and result.retried
    assert result.answer == "Three feet [1]." and len(result.sources) == 1
    assert result.model == "test/second:free"
    assert llm.models_used == [None, ["test/second:free"]]
    assert llm.calls[0] == llm.calls[1]  # same prompt, different model


class _SlowLLM(_FakeLLM):
    async def complete(self, messages, models=None):
        await asyncio.sleep(0.03)
        return await super().complete(messages, models)


def test_answer_times_the_model_call_citations_and_retry_and_names_both_models():
    timer = StepTimer()
    retriever = _FakeRetriever({"wztc": -9.0, "utilities": 3.5})
    answerer = Answerer(retriever, _SlowLLM([NOT_FOUND, "Three feet [1]."]))
    hits = retriever.retrieve("q", "utilities")

    result = asyncio.run(answerer.answer("q", BY_ID["utilities"], BY_ID["utilities"], hits, time.monotonic() + 40, timer))

    ms = timer.as_ms()
    assert ms["llm"] >= 25 and ms["retry"] >= 25  # one slow call each
    assert ms["suggest"] == 0  # the retry answered, so no refusal to suggest for
    assert (result.first_model, result.model) == ("test/model:free", "test/second:free")
    assert result.as_dict()["first_model"] == "test/model:free" and result.as_dict()["retried"] is True


def test_refusal_times_the_search_of_the_other_division_as_suggest():
    class _SlowRetriever(_FakeRetriever):
        def retrieve(self, question, division, k=5, timer=None, candidates=None):
            time.sleep(0.03)
            return super().retrieve(question, division, k, timer, candidates)

    timer = StepTimer()
    retriever = _SlowRetriever({"wztc": -9.0, "utilities": 0.5})
    answerer = Answerer(retriever, _FakeLLM(NOT_FOUND))
    hits = retriever.retrieve("q", "utilities")

    result = asyncio.run(answerer.answer("q", BY_ID["wztc"], BY_ID["utilities"], hits, None, timer))

    ms = timer.as_ms()
    assert result.refused and not result.retried
    assert ms["suggest"] >= 25 and ms["retry"] == 0
    assert ms["embed"] == 0  # the suggestion's own searches are not counted as the question's


def test_no_retry_when_retrieval_is_weak():
    result, llm = _ask_with_retry([NOT_FOUND, "Three feet [1]."], score=0.5, seconds_left=40)

    assert result.refused and not result.retried
    assert len(llm.calls) == 1


def test_no_retry_without_a_reranker_because_scores_are_then_not_comparable():
    result, llm = _ask_with_retry([NOT_FOUND, "Three feet [1]."], score=3.5, reranker=False)

    assert result.refused and len(llm.calls) == 1


def test_no_retry_when_too_little_of_the_time_budget_is_left():
    result, llm = _ask_with_retry([NOT_FOUND, "Three feet [1]."], score=3.5, seconds_left=10)

    assert result.refused and not result.retried
    assert len(llm.calls) == 1


def test_no_retry_when_switched_off():
    result, llm = _ask_with_retry([NOT_FOUND, "Three feet [1]."], score=3.5, seconds_left=40, retry_min_score=None)

    assert result.refused and len(llm.calls) == 1


def test_refusal_is_returned_when_the_retry_refuses_too():
    result, llm = _ask_with_retry([NOT_FOUND, NOT_FOUND, "Three feet [1]."], score=3.5, seconds_left=40)

    assert result.refused and result.retried and result.sources == []
    assert len(llm.calls) == 2  # retried once, not more
    assert "Utilities documents" in result.answer


def test_refusal_is_returned_when_the_retry_fails_or_runs_out_of_time():
    failed, _ = _ask_with_retry([NOT_FOUND, LLMError(BUSY, status=429)], score=3.5, seconds_left=40)
    assert failed.refused and failed.retried

    class _SlowRetry(_FakeLLM):
        async def complete(self, messages, models=None):
            if models:
                await asyncio.sleep(30)
            return await super().complete(messages, models)

    retriever = _FakeRetriever({"wztc": -9.0, "utilities": 3.5})
    answerer = Answerer(retriever, _SlowRetry(NOT_FOUND), retry_min_seconds=0.0)
    hits = retriever.retrieve("q", "utilities")
    started = time.monotonic()
    slow = asyncio.run(answerer.answer("q", BY_ID["utilities"], BY_ID["utilities"], hits, started + 1.5))
    assert slow.refused and time.monotonic() - started < 1.5  # gave up before the request deadline


def test_no_retry_when_less_than_the_retry_margin_is_left():
    result, llm = _ask_with_retry([NOT_FOUND, "Three feet [1]."], score=3.5, seconds_left=0.5, retry_min_seconds=0.0)

    assert result.refused and not result.retried  # not reported as a retry that never got to call the model
    assert len(llm.calls) == 1


def test_retry_settings_have_defaults_and_can_be_changed():
    default = load_settings({})
    assert (default.retry_on_refusal, default.retry_min_score, default.retry_min_seconds) == (True, 1.0, 15.0)
    custom = load_settings({"RETRY_ON_REFUSAL": "off", "RETRY_MIN_SCORE": "2.5", "RETRY_MIN_SECONDS": "20"})
    assert (custom.retry_on_refusal, custom.retry_min_score, custom.retry_min_seconds) == (False, 2.5, 20.0)
    with pytest.raises(ValueError):
        load_settings({"RETRY_ON_REFUSAL": "maybe"})


def test_retry_models_are_the_ones_after_the_model_that_answered():
    client = OpenRouterClient("k", ["a:free", "b:free", "c:free"])
    assert client.retry_models("a:free") == ["b:free", "c:free"]
    assert client.retry_models("c:free") == ["c:free"]  # no fallback left: same model
    assert client.retry_models("unknown:free") == ["b:free", "c:free"]
    assert OpenRouterClient("k", ["a:free"]).retry_models("a:free") == ["a:free"]


def test_complete_can_override_the_model_list():
    seen = {}

    def handler(request):
        seen["models"] = json.loads(request.content)["models"]
        return httpx.Response(200, json={"choices": [{"message": {"content": "ok [1]"}}]})

    asyncio.run(_client(handler).complete([], models=["e/f:free"]))
    assert seen["models"] == ["e/f:free"]


def test_settings_reject_paid_models():
    with pytest.raises(ValueError):
        load_settings({"OPENROUTER_MODEL": "openai/gpt-4o"})
    with pytest.raises(ValueError):
        load_settings({"OPENROUTER_FALLBACK_MODELS": "x/y:free, openai/gpt-4o"})
    settings = load_settings({"OPENROUTER_MODEL": "a/b:free", "OPENROUTER_FALLBACK_MODELS": "c/d:free", "RERANK": "off"})
    assert settings.models == ("a/b:free", "c/d:free")
    assert settings.rerank is False


@pytest.mark.parametrize("value", ["two", "0", "-1", "1.5"])
def test_a_bad_onnx_threads_value_stops_startup(value):
    with pytest.raises(ValueError):
        load_settings({"ONNX_THREADS": value})
    load_settings({"ONNX_THREADS": "2"})


def test_request_budget_defaults_under_vercels_limit_and_rejects_values_above_it():
    assert load_settings({}).request_budget_seconds == 55
    assert load_settings({"REQUEST_BUDGET_SECONDS": "30"}).request_budget_seconds == 30
    with pytest.raises(ValueError):
        load_settings({"REQUEST_BUDGET_SECONDS": "60"})


def _client(handler):
    return OpenRouterClient("sk-test", ["a/b:free", "c/d:free"], transport=httpx.MockTransport(handler))


def test_openrouter_client_sends_the_fallback_list_and_returns_the_answering_model():
    seen = {}

    def handler(request):
        seen["body"] = json.loads(request.content)
        seen["auth"] = request.headers["authorization"]
        return httpx.Response(200, json={"model": "c/d:free", "choices": [{"message": {"content": " Answer [1]. "}}]})

    completion = asyncio.run(_client(handler).complete([{"role": "user", "content": "hi"}]))

    assert completion == Completion("Answer [1].", "c/d:free")
    assert seen["body"]["models"] == ["a/b:free", "c/d:free"]
    assert seen["auth"] == "Bearer sk-test"


@pytest.mark.parametrize("response", [
    httpx.Response(429, json={"error": {"message": "rate limited"}}),
    httpx.Response(200, json={"error": {"code": 429, "message": "upstream rate limited"}}),
])
def test_rate_limits_become_a_friendly_busy_error(response):
    with pytest.raises(LLMError) as caught:
        asyncio.run(_client(lambda request: response).complete([]))
    assert caught.value.user_message == BUSY
    assert caught.value.status == 429


@pytest.mark.parametrize("response", [
    httpx.Response(429, json={"error": {"code": 429, "message": "Rate limit exceeded: free-models-per-day. Add 10 credits to unlock."}}),
    httpx.Response(429, json={"error": {"code": 429, "message": "Rate limit exceeded", "metadata": {"headers": {"X-RateLimit-Limit": "50"}, "reason": "free-models-per-day"}}}),
    httpx.Response(200, json={"error": {"code": 429, "message": "Rate limit exceeded: free-models-per-day"}}),
])
def test_daily_free_quota_has_its_own_message(response):
    with pytest.raises(LLMError) as caught:
        asyncio.run(_client(lambda request: response).complete([]))
    assert caught.value.user_message == DAILY_LIMIT
    assert caught.value.status == 429


def test_per_minute_rate_limit_stays_busy():
    response = httpx.Response(429, json={"error": {"code": 429, "message": "Rate limit exceeded", "metadata": {"error_type": "rate_limit_exceeded"}}})
    with pytest.raises(LLMError) as caught:
        asyncio.run(_client(lambda request: response).complete([]))
    assert caught.value.user_message == BUSY


@pytest.mark.parametrize("response", [
    httpx.Response(200, text="<html>Bad gateway</html>"),
    httpx.Response(200, json={"error": "upstream exploded"}),
    httpx.Response(200, json=["not", "an", "object"]),
    httpx.Response(200, json={"choices": "nope"}),
])
def test_malformed_upstream_responses_become_the_friendly_unavailable_error(response):
    with pytest.raises(LLMError) as caught:
        asyncio.run(_client(lambda request: response).complete([]))
    assert caught.value.user_message == UNAVAILABLE
    assert caught.value.status == 503


def test_requests_cap_provider_prices_at_zero():
    seen = {}

    def handler(request):
        seen["body"] = json.loads(request.content)
        return httpx.Response(200, json={"choices": [{"message": {"content": "ok [1]"}}]})

    asyncio.run(_client(handler).complete([]))
    assert seen["body"]["provider"] == {"max_price": {"prompt": 0, "completion": 0}}


def test_cut_off_answer_is_an_error_not_a_partial_answer():
    response = httpx.Response(200, json={"model": "a/b:free", "choices": [{"finish_reason": "length", "message": {"content": "We need to"}}]})
    with pytest.raises(LLMError) as caught:
        asyncio.run(_client(lambda request: response).complete([]))
    assert caught.value.user_message == llm_module.TOO_LONG


def test_reasoning_is_off_unless_configured():
    bodies = []

    def handler(request):
        bodies.append(json.loads(request.content))
        return httpx.Response(200, json={"choices": [{"message": {"content": "ok [1]"}}]})

    asyncio.run(_client(handler).complete([]))
    asyncio.run(OpenRouterClient("k", ["a/b:free"], reasoning="low", transport=httpx.MockTransport(handler)).complete([]))
    assert bodies[0]["reasoning"] == {"enabled": False}
    assert bodies[1]["reasoning"]["effort"] == "low"


def test_network_failure_becomes_a_friendly_error_without_details():
    def handler(request):
        raise httpx.ConnectError("boom")

    with pytest.raises(LLMError) as caught:
        asyncio.run(_client(handler).complete([]))
    assert caught.value.user_message == llm_module.UNAVAILABLE
    assert "boom" not in caught.value.user_message
