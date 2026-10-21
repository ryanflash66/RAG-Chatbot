"""Tests for the hosted demo's HTTP API (hosted/index.py) with a fake retriever and LLM; no network."""

import asyncio
import dataclasses
import json
import re
import sys
import time
from pathlib import Path

import numpy as np
import pytest
from fastapi.testclient import TestClient

HOSTED = Path(__file__).resolve().parent.parent / "hosted"
sys.path.insert(0, str(HOSTED))

import index as hosted  # noqa: E402
from divrag.answer import NOT_FOUND  # noqa: E402
from divrag.divisions import Division, Document  # noqa: E402
from divrag.index_file import Hit, IndexFile  # noqa: E402
from divrag.llm import BUSY, TOO_SLOW, Completion, LLMError  # noqa: E402
from divrag.timing import STEPS  # noqa: E402

UAM = "20220713 NCDOT UAM Ver 2-0.pdf"
TMP = "TMP Design Manual (Combined, No Links).pdf"
SECRET = "sk-or-test-secret"


class _FakeRetriever:
    reranker = None

    def __init__(self):
        self.divisions = []
        self.sources = []
        self.questions = []

    def retrieve(self, question, division, k=5, timer=None, candidates=None, sources=None):
        self.divisions.append(division)
        self.sources.append(sources)
        self.questions.append(question)
        if timer is not None:
            with timer.step("embed"):
                pass
            with timer.step("search"):
                pass
        text = "Any work within 5 feet of the edge of any travel lane shall require a lane closure."
        return [Hit(2.0, {"text": text, "source": UAM, "page": 126, "division": division,
                          "section": "3.6.4.1 Lane and Road Closures"})]

    def with_following(self, hits, top=2):
        return hits

    def as_passages(self, hits):
        return hits


class _FakeLLM:
    """Replies with `reply` (a text or an exception); a list of replies is replayed one per call."""

    def __init__(self, reply):
        self.reply = reply
        self.messages = None
        self.calls = 0

    def _next(self, messages):
        self.messages = messages
        self.calls += 1
        reply = self.reply[min(self.calls, len(self.reply)) - 1] if isinstance(self.reply, list) else self.reply
        if isinstance(reply, Exception):
            raise reply
        return reply

    async def complete(self, messages, models=None):
        return Completion(self._next(messages), models[0] if models else "test/model:free")

    def retry_models(self, used):
        return ["test/second:free"]

    def complete_stream(self, messages, models=None):
        return _FakeStream(self, messages, models[0] if models else "test/model:free")


class _FakeStream:
    """The reply word by word, as OpenRouterClient.complete_stream hands it over."""

    def __init__(self, llm, messages, model):
        self._llm, self._messages, self.model, self.text = llm, messages, model, ""

    def __aiter__(self):
        return self._pieces()

    async def _pieces(self):
        reply = self._llm._next(self._messages)
        for word in re.findall(r"\S+\s*", reply):
            yield word
        self.text = reply.strip()


@pytest.fixture
def api(monkeypatch):
    retriever = _FakeRetriever()
    llm = _FakeLLM("Within 5 feet of the travel lane on an undivided facility [1].")
    monkeypatch.setattr(hosted, "settings", dataclasses.replace(hosted.settings, openrouter_api_key=SECRET))
    monkeypatch.setattr(hosted.runtime, "retriever", lambda: retriever)
    monkeypatch.setattr(hosted, "_make_llm", lambda: llm)
    monkeypatch.setattr(hosted, "limiter", hosted._RateLimiter(100))
    return TestClient(hosted.app), retriever, llm


def _ask(client, question="When is a lane closure required?", asker="wztc", target="utilities"):
    return client.post("/api/ask", json={"question": question, "asker": asker, "target": target})


def test_cross_division_answer_cites_document_page_and_url(api):
    client, retriever, llm = api

    response = _ask(client)

    assert response.status_code == 200
    data = response.json()
    assert data["refused"] is False
    assert data["answer"].endswith("[1].")
    assert data["asker"]["id"] == "wztc" and data["target"]["id"] == "utilities"
    (source,) = data["sources"]
    assert source["title"].startswith("Utilities Accommodation Manual")
    assert source["page"] == 126
    assert source["section"] == "3.6.4.1 Lane and Road Closures"
    assert source["url"] == (
        "https://connect.ncdot.gov/municipalities/Utilities/UtilitiesDocuments/20220713%20NCDOT%20UAM%20Ver%202-0.pdf#page=126"
    )
    assert retriever.divisions == ["utilities"]  # only the asked division was searched
    assert "Work Zone Traffic Control" in llm.messages[0]["content"]  # the asker frames the answer
    assert SECRET not in response.text


def test_every_answer_reports_each_step_in_ms_and_logs_one_line(api, caplog):
    client, _, llm = api

    with caplog.at_level("INFO", logger="hosted"):
        answered = _ask(client).json()
        llm.reply = NOT_FOUND
        refused = _ask(client).json()

    for data in (answered, refused):
        timing = data["timing_ms"]
        assert list(timing) == list(STEPS) + ["retrieval", "total"]
        assert all(isinstance(ms, int) and ms >= 0 for ms in timing.values())
        assert timing["total"] >= timing["retrieval"]
        assert data["model"] == "test/model:free" and data["retried"] is False
    lines = [r.getMessage() for r in caplog.records if r.getMessage().startswith("ask ")]
    assert len(lines) == 2
    assert all("model=test/model:free" in line and " embed=" in line and " rerank=" in line and " total=" in line
               for line in lines)


def test_refusal_has_a_clear_message_and_no_sources(api):
    client, _, llm = api
    llm.reply = NOT_FOUND

    data = _ask(client, "What is the hourly rate for law enforcement?").json()

    assert data["refused"] is True
    assert data["sources"] == []
    assert data["answer"].startswith("I couldn't find an answer to that in the Utilities documents")


def test_rate_limited_model_returns_friendly_429(api):
    client, _, llm = api
    llm.reply = LLMError(BUSY, status=429, detail="upstream said no")

    response = _ask(client)

    assert response.status_code == 429
    assert response.json() == {"error": BUSY}


def test_answer_that_outlasts_the_time_budget_returns_a_friendly_504(api, monkeypatch):
    client, _, llm = api

    async def never_answers(messages):
        await asyncio.sleep(30)

    llm.complete = never_answers
    monkeypatch.setattr(hosted, "MIN_ANSWER_SECONDS", 0.05)
    monkeypatch.setattr(hosted, "settings", dataclasses.replace(hosted.settings, request_budget_seconds=0.0))

    response = _ask(client)

    assert response.status_code == 504
    assert response.json() == {"error": TOO_SLOW}


@pytest.mark.parametrize("body,status", [
    ({"question": "x" * 501, "asker": "wztc", "target": "utilities"}, 400),
    ({"question": "  ", "asker": "wztc", "target": "utilities"}, 400),
    ({"question": "Is this ok?", "asker": "wztc", "target": "finance"}, 400),
    ({"question": "x" * 6000, "asker": "wztc", "target": "utilities"}, 422),
    ({"question": "Is this ok?", "asker": "wztc", "target": "utilities", "documents": ["TMP Design Manual (Combined, No Links).pdf"]}, 400),
    ({"question": "Is this ok?", "asker": "wztc", "target": "utilities", "documents": []}, 400),
    ({"question": "Is this ok?", "asker": "wztc", "target": "utilities", "history": [{"question": "q", "answer": "a"}] * 7}, 422),
])
def test_invalid_requests_are_rejected_before_any_search(api, body, status):
    client, retriever, _ = api
    assert client.post("/api/ask", json=body).status_code == status
    assert retriever.divisions == []


def test_per_client_rate_limit(api, monkeypatch):
    client, _, _ = api
    monkeypatch.setattr(hosted, "limiter", hosted._RateLimiter(2))
    statuses = [_ask(client).status_code for _ in range(3)]
    assert statuses == [200, 200, 429]


def test_missing_api_key_is_reported_without_details(api, monkeypatch):
    client, _, _ = api
    monkeypatch.setattr(hosted, "settings", dataclasses.replace(hosted.settings, openrouter_api_key=None))
    response = _ask(client)
    assert response.status_code == 503
    assert "OPENROUTER" not in response.text


def test_page_divisions_and_health_expose_no_secrets(api):
    client, _, _ = api
    page = client.get("/")
    divisions = client.get("/api/divisions").json()
    health = client.get("/api/health").json()

    assert page.status_code == 200 and "<title>" in page.text
    assert [d["id"] for d in divisions["divisions"]] == ["wztc", "utilities"]
    assert all(d["examples"] and d["documents"][0]["url"].startswith("https://connect.ncdot.gov/") for d in divisions["divisions"])
    assert health["llm_configured"] is True
    assert health["cpus"]["cpu_count"] >= 1
    assert all(m.endswith(":free") for m in health["llm_models"])
    for text in (page.text, str(divisions), str(health)):
        assert SECRET not in text


def test_warm_loads_the_models_and_divisions_does_not(api, monkeypatch):
    client, _, _ = api
    loads = []
    monkeypatch.setattr(hosted.runtime, "retriever", lambda: loads.append(1))

    client.get("/api/divisions")
    assert loads == []
    response = client.post("/api/warm")

    assert response.status_code == 200 and response.json()["ready"] is True
    assert loads == [1]


def test_failed_warm_up_reports_not_ready_without_details(api, monkeypatch):
    client, _, _ = api

    def broken():
        raise RuntimeError("model file missing at /var/task/models")

    monkeypatch.setattr(hosted.runtime, "retriever", broken)
    response = client.post("/api/warm")

    assert response.status_code == 503
    assert response.json() == {"ready": False}


def test_no_cors_headers_for_other_origins_by_default(api):
    client, _, _ = api
    response = client.get("/api/divisions", headers={"Origin": "https://evil.example"})
    assert "access-control-allow-origin" not in response.headers


def test_only_the_targets_ticked_documents_are_searched_and_history_is_accepted(api):
    client, retriever, _ = api
    body = {"question": "When is a lane closure required?", "asker": "wztc", "target": "utilities",
            "documents": [UAM, "TMP Design Manual (Combined, No Links).pdf", UAM],
            "history": [{"question": "Who pays for a detour?", "answer": "The encroaching party [1]."}]}

    response = client.post("/api/ask", json=body)

    assert response.status_code == 200
    assert retriever.sources == [[UAM]]  # the other division's manual is dropped, duplicates too
    _ask(client)
    assert retriever.sources[-1] is None  # no list: every document of the target


def test_a_follow_ups_history_reaches_the_search_and_the_prompt(api):
    client, retriever, llm = api
    history = [{"question": f"Earlier question {n}?", "answer": f"Earlier answer {n} [1]."} for n in range(1, 6)]
    body = {"question": "And within 5 feet of the lane?", "asker": "wztc", "target": "utilities", "history": history}

    response = client.post("/api/ask", json=body)

    assert response.status_code == 200 and response.json()["refused"] is False
    assert retriever.questions == ["Earlier question 5? And within 5 feet of the lane?"]
    user = llm.messages[1]["content"]
    # Five turns arrived; only the last three are used.
    assert [n for n in range(1, 6) if f"Earlier question {n}?" in user] == [3, 4, 5]
    assert "Earlier answer 5." in user and user.rstrip().endswith("Question: And within 5 feet of the lane?")
    assert "8. The earlier conversation" in llm.messages[0]["content"]


def test_a_question_without_history_is_searched_as_asked(api):
    client, retriever, llm = api

    _ask(client, "When is a lane closure required?")

    assert retriever.questions == ["When is a lane closure required?"]
    assert "Earlier" not in llm.messages[1]["content"]


def test_divisions_name_each_documents_file_for_the_documents_filter(api):
    client, _, _ = api
    documents = {d["id"]: d["documents"] for d in client.get("/api/divisions").json()["divisions"]}
    assert documents["utilities"][0]["file"] == UAM


def _small_index(counts):
    """An index with counts[(division, source)] chunks of each document; search is never called."""
    chunks = [{"text": "t", "source": source, "page": 1, "section": "", "division": division}
              for (division, source), n in counts.items() for _ in range(n)]
    return IndexFile("test-model", chunks, np.zeros((len(chunks), 4), dtype=np.float32))


@pytest.fixture
def small_index(monkeypatch):
    index = _small_index({("utilities", UAM): 3, ("wztc", TMP): 2})
    monkeypatch.setattr(hosted.runtime, "index", index)
    return index


def test_divisions_count_the_passages_of_each_document_and_division(api, small_index):
    client, _, _ = api

    divisions = {d["id"]: d for d in client.get("/api/divisions").json()["divisions"]}

    assert divisions["utilities"]["passages"] == 3 and divisions["wztc"]["passages"] == 2
    (uam,) = divisions["utilities"]["documents"]
    assert uam["passages"] == 3 and uam["file"] == UAM and uam["title"] and uam["url"]
    assert divisions["wztc"]["documents"][0]["passages"] == 2


def test_every_listed_document_has_passages_in_the_committed_index(api):
    # A document added to divisions.py without rerunning prototype.ingest would show "0 passages"
    # and, ticked alone, make every question search nothing.
    client, _, _ = api

    for division in client.get("/api/divisions").json()["divisions"]:
        assert all(doc["passages"] > 0 for doc in division["documents"]), division["id"]
        assert division["passages"] == sum(doc["passages"] for doc in division["documents"]), division["id"]


def test_every_reply_says_how_many_documents_and_passages_were_searched(api, small_index):
    client, _, llm = api

    answered = _ask(client).json()
    ticked = client.post("/api/ask", json={"question": "When is a lane closure required?", "asker": "wztc",
                                           "target": "utilities", "documents": [UAM, TMP]}).json()
    llm.reply = NOT_FOUND
    refused = _ask(client).json()

    for data in (answered, ticked, refused):
        assert data["searched"] == {"documents": 1, "passages": 3}  # never the asker's (wztc) 2 passages
    assert refused["refused"] is True


def test_searched_counts_only_the_ticked_documents(monkeypatch):
    monkeypatch.setattr(hosted.runtime, "index", _small_index({("utilities", UAM): 3, ("utilities", "Permits.pdf"): 4,
                                                               ("wztc", TMP): 2}))
    division = Division("utilities", "Utilities", "NCDOT Utilities Unit",
                        (Document(UAM, "UAM", "https://x/uam.pdf"), Document("Permits.pdf", "Permits", "https://x/p.pdf")))

    assert hosted._searched(division, None) == {"documents": 2, "passages": 7}
    assert hosted._searched(division, ["Permits.pdf"]) == {"documents": 1, "passages": 4}


@pytest.mark.parametrize("path,kind", [("/css/base.css", "text/css"), ("/js/app.js", "javascript")])
def test_the_pages_stylesheets_and_scripts_are_served(api, path, kind):
    client, _, _ = api
    response = client.get(path)
    assert response.status_code == 200 and kind in response.headers["content-type"]


# POST /api/ask/stream (DAR-629)

def _stream(client, question="When is a lane closure required?", asker="wztc", target="utilities"):
    return client.post("/api/ask/stream", json={"question": question, "asker": asker, "target": target})


def _events(response):
    """[(event, data)] of a server-sent event stream."""
    events = []
    for block in response.text.split("\n\n"):
        if block.strip():
            fields = dict(line.split(": ", 1) for line in block.split("\n"))
            events.append((fields["event"], json.loads(fields["data"])))
    return events


def _order(events):
    """The events as "read:start", "delta", "done", ..."""
    return [f"{data['id']}:{data['status']}" if event == "step" else event for event, data in events]


def test_a_streamed_answer_sends_the_steps_and_the_text_as_they_happen_then_the_same_answer_as_ask(api, caplog):
    client, retriever, _ = api

    with caplog.at_level("INFO", logger="hosted"):
        response = _stream(client)

    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/event-stream")
    assert response.headers["cache-control"] == "no-cache" and response.headers["x-accel-buffering"] == "no"
    events = _events(response)
    order = _order(events)
    written = order.index("write:done")
    assert order[:5] == ["read:start", "read:done", "search:start", "search:done", "write:start"]
    assert set(order[5:written]) == {"delta"} and written - 5 > 1  # the text in pieces, while it is written
    assert order[written:] == ["write:done", "check:start", "check:done", "done"]
    # The citation comes with the checked answer: the prompt's numbers are renumbered.
    assert "".join(data["text"] for event, data in events if event == "delta") == (
        "Within 5 feet of the travel lane on an undivided facility.")

    labels = {data["id"]: data["label"] for event, data in events if event == "step"}
    passages = hosted.runtime.index.count("utilities")
    assert labels["read"] == "Reading your question" and labels["write"] == "Writing the answer"
    assert labels["search"] == f"Searching Utilities documents ({passages:,} passages)"
    assert labels["check"] == "Checking sources"

    done = events[-1][1]
    timing = done["timing_ms"]
    step_ms = {data["id"]: data["ms"] for event, data in events if event == "step" and data["status"] == "done"}
    assert step_ms["read"] == timing["model_load"] + timing["embed"] and step_ms["search"] == timing["search"]
    assert step_ms["write"] == timing["llm"] and step_ms["check"] == timing["citations"]
    assert done["steps"] == [{"id": data["id"], "label": data["label"], "ms": data["ms"]}
                             for event, data in events if event == "step" and data["status"] == "done"]

    asked = _ask(client).json()
    assert [s["id"] for s in asked["steps"]] == [s["id"] for s in done["steps"]]  # the fallback shows the same steps
    timed = ("timing_ms", "steps")  # the same keys and steps, but measured again
    assert {k: v for k, v in done.items() if k not in timed} == {k: v for k, v in asked.items() if k not in timed}
    assert list(done["timing_ms"]) == list(asked["timing_ms"])
    assert done["refused"] is False and done["uncited"] is False and done["sources"][0]["page"] == 126
    assert retriever.divisions == ["utilities", "utilities"]
    lines = [r.getMessage() for r in caplog.records if r.getMessage().startswith("ask ")]
    assert len(lines) == 1 and "stream=True" in lines[0] and "uncited=False" in lines[0]
    assert SECRET not in response.text


def test_a_streamed_refusal_with_strong_retrieval_double_checks_and_replaces_the_text(api):
    client, retriever, llm = api
    retriever.reranker = object()  # scores are reranker scores, and 2.0 counts as strong retrieval
    llm.reply = [NOT_FOUND, "Within 5 feet [1]."]

    events = _events(_stream(client))

    order = _order(events)
    retry = order.index("retry:start")
    assert order[:retry] == ["read:start", "read:done", "search:start", "search:done", "write:start", "write:done",
                             "check:start", "check:done"]  # no delta: the refusal's marker is never shown
    assert events[retry][1]["label"] == "Double-checking the source…"
    assert events[retry + 1] == ("replace", {"text": ""})
    assert set(order[retry + 2:-2]) == {"delta"} and order[-2:] == ["retry:done", "done"]
    done = events[-1][1]
    assert done["retried"] is True and done["refused"] is False and done["answer"] == "Within 5 feet [1]."
    assert (done["first_model"], done["model"]) == ("test/model:free", "test/second:free")


def test_a_streamed_refusal_refused_again_suggests_another_division(api):
    client, retriever, llm = api
    retriever.reranker = object()
    llm.reply = NOT_FOUND

    events = _events(_stream(client))

    order = _order(events)
    assert "delta" not in order
    assert order[-6:] == ["retry:start", "replace", "retry:done", "suggest:start", "suggest:done", "done"]
    done = events[-1][1]
    assert done["refused"] is True and done["retried"] is True and done["sources"] == []
    assert done["suggest"] == [{"id": "wztc", "name": "Work Zone Traffic Control"}]
    assert [s["id"] for s in done["steps"]] == ["read", "search", "write", "check", "retry", "suggest"]
    assert [s["id"] for s in _ask(client).json()["steps"]] == ["read", "search", "write", "check", "retry", "suggest"]


def test_an_uncited_answer_is_kept_and_flagged_by_both_endpoints(api):
    client, _, llm = api
    llm.reply = "Within 5 feet of the travel lane."

    streamed = _events(_stream(client))[-1]
    asked = _ask(client).json()

    assert streamed[0] == "done"
    for data in (streamed[1], asked):
        assert data["uncited"] is True and data["refused"] is False and data["sources"] == []
        assert data["answer"] == "Within 5 feet of the travel lane."


def test_half_of_a_character_split_across_two_events_does_not_break_the_stream(api):
    client, _, llm = api
    llm.reply = "Within 5 feet \ud83d [1]."  # the first half of an emoji's surrogate pair

    events = _events(_stream(client))

    assert events[-1][0] == "done" and events[-1][1]["answer"] == "Within 5 feet \ud83d [1]."


def test_a_model_error_ends_the_stream_with_a_friendly_error_event(api):
    client, _, llm = api
    llm.reply = LLMError(BUSY, status=429, detail="upstream said no")

    response = _stream(client)

    events = _events(response)
    assert events[-1] == ("error", {"error": BUSY, "status": 429})
    assert "done" not in _order(events) and "upstream said no" not in response.text


def test_a_streamed_answer_that_outlasts_the_time_budget_ends_with_an_error(api, monkeypatch):
    client, _, llm = api

    class _Never:
        model, text = "test/model:free", ""

        def __aiter__(self):
            return self._pieces()

        async def _pieces(self):
            await asyncio.sleep(30)
            yield "never"

    llm.complete_stream = lambda messages, models=None: _Never()
    monkeypatch.setattr(hosted, "MIN_ANSWER_SECONDS", 0.05)
    monkeypatch.setattr(hosted, "settings", dataclasses.replace(hosted.settings, request_budget_seconds=0.0))

    assert _events(_stream(client))[-1] == ("error", {"error": TOO_SLOW, "status": 504})


def test_a_stream_still_ends_before_vercel_stops_the_function(api, monkeypatch):
    client, _, _ = api

    def slow_models(llm):
        time.sleep(0.5)  # a cold start that eats the budget before the answer's own deadline starts
        raise AssertionError("never reached: the stream stops first")

    monkeypatch.setattr(hosted.runtime, "answerer", slow_models)
    # The stream stops STREAM_MARGIN_SECONDS after the request budget: here 0.2 s after a budget of 0.
    monkeypatch.setattr(hosted, "settings", dataclasses.replace(hosted.settings, request_budget_seconds=0.0))
    monkeypatch.setattr(hosted, "STREAM_MARGIN_SECONDS", 0.2)

    events = _events(_stream(client))

    assert _order(events) == ["read:start", "error"]
    assert events[-1][1] == {"error": TOO_SLOW, "status": 504}


def test_stream_requests_get_the_same_checks_as_ask(api, monkeypatch):
    client, retriever, _ = api

    blank = _stream(client, question="  ")
    assert blank.status_code == 400 and blank.json() == {"error": "Please type a question."}
    monkeypatch.setattr(hosted, "limiter", hosted._RateLimiter(1))
    assert _stream(client).status_code == 200
    limited = _stream(client)
    assert limited.status_code == 429 and "error" in limited.json()
    assert retriever.divisions == ["utilities"]


def test_stream_events_reach_the_client_before_the_model_has_finished(api):
    # TestClient hands over a streamed response only once it is complete, so the event
    # generator is read directly: the steps and the first words must come out while the
    # model is still held back, not all at once when it finishes.
    _, _, llm = api
    gate = asyncio.Event()

    class _Held:
        model, text = "test/model:free", ""

        def __aiter__(self):
            return self._pieces()

        async def _pieces(self):
            yield "Within 5 feet of the travel lane "
            await gate.wait()
            yield "on an undivided facility [1]."
            self.text = "Within 5 feet of the travel lane on an undivided facility [1]."

    llm.complete_stream = lambda messages, models=None: _Held()
    question = hosted.Question("When is a lane closure required?", hosted.BY_ID["wztc"], hosted.BY_ID["utilities"], None, [])

    async def run():
        seen = []

        async def read():
            async for chunk in hosted._events(question, time.monotonic()):
                seen.append(chunk)

        reader = asyncio.create_task(read())
        for _ in range(500):
            if any(c.startswith("event: delta") for c in seen):
                break
            await asyncio.sleep(0.01)
        before = list(seen)
        gate.set()
        await asyncio.wait_for(reader, 10)
        return before, seen

    before, seen = asyncio.run(run())
    assert any(c.startswith("event: step") for c in before)
    assert any(c.startswith("event: delta") for c in before)
    assert not any(c.startswith("event: done") for c in before)
    assert seen[-1].startswith("event: done")
