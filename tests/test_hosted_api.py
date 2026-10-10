"""Tests for the hosted demo's HTTP API (hosted/index.py) with a fake retriever and LLM; no network."""

import dataclasses
import sys
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

HOSTED = Path(__file__).resolve().parent.parent / "hosted"
sys.path.insert(0, str(HOSTED))

import index as hosted  # noqa: E402
from divrag.answer import NOT_FOUND  # noqa: E402
from divrag.index_file import Hit  # noqa: E402
from divrag.llm import BUSY, Completion, LLMError  # noqa: E402

UAM = "20220713 NCDOT UAM Ver 2-0.pdf"
SECRET = "sk-or-test-secret"


class _FakeRetriever:
    reranker = None

    def __init__(self):
        self.divisions = []

    def retrieve(self, question, division, k=5):
        self.divisions.append(division)
        text = "Any work within 5 feet of the edge of any travel lane shall require a lane closure."
        return [Hit(2.0, {"text": text, "source": UAM, "page": 126, "division": division,
                          "section": "3.6.4.1 Lane and Road Closures"})]

    def with_following(self, hits, top=2):
        return hits

    def as_passages(self, hits):
        return hits


class _FakeLLM:
    def __init__(self, reply):
        self.reply = reply
        self.messages = None

    async def complete(self, messages):
        self.messages = messages
        if isinstance(self.reply, Exception):
            raise self.reply
        return Completion(self.reply, "test/model:free")


@pytest.fixture
def api(monkeypatch):
    retriever = _FakeRetriever()
    llm = _FakeLLM("Within 5 feet of the travel lane on an undivided facility [1].")
    monkeypatch.setattr(hosted, "settings", dataclasses.replace(hosted.settings, openrouter_api_key=SECRET))
    monkeypatch.setattr(hosted.runtime, "retriever", lambda: retriever)
    monkeypatch.setattr(hosted, "_make_llm", lambda: llm)
    monkeypatch.setattr(hosted, "_warm", lambda: None)
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


@pytest.mark.parametrize("body,status", [
    ({"question": "x" * 501, "asker": "wztc", "target": "utilities"}, 400),
    ({"question": "  ", "asker": "wztc", "target": "utilities"}, 400),
    ({"question": "Is this ok?", "asker": "wztc", "target": "finance"}, 400),
    ({"question": "x" * 6000, "asker": "wztc", "target": "utilities"}, 422),
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
    assert all(m.endswith(":free") for m in health["llm_models"])
    for text in (page.text, str(divisions), str(health)):
        assert SECRET not in text


def test_no_cors_headers_for_other_origins_by_default(api):
    client, _, _ = api
    response = client.get("/api/divisions", headers={"Origin": "https://evil.example"})
    assert "access-control-allow-origin" not in response.headers
