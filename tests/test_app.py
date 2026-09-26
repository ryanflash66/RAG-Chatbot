"""Tests for the Chainlit entrypoint's pure helpers and import safety.

The Chainlit handlers themselves need a running Chainlit context and are
covered by the manual smoke test in README.md.
"""

import asyncio
import importlib
import secrets

import pytest

pytest.importorskip("chainlit")

import app  # noqa: E402
from rag.config import load_config  # noqa: E402
from rag.index import Hit  # noqa: E402


@pytest.fixture(autouse=True)
def _clear_caches():
    app._config.cache_clear()
    app._runtime.cache_clear()
    yield
    app._config.cache_clear()
    app._runtime.cache_clear()


def test_import_builds_nothing(monkeypatch):
    def explode(*_args, **_kwargs):
        raise AssertionError("RetrievalIndex built at import time")

    monkeypatch.setattr("rag.index.RetrievalIndex", explode)
    importlib.reload(app)
    assert app._runtime.cache_info().currsize == 0


def test_build_prompt_includes_sources_and_question():
    hits = [
        Hit(text="Isolate the host.", score=0.9, source="playbooks/ransomware.md"),
        Hit(text="Reset credentials.", score=0.8, source="phishing.md"),
    ]
    prompt = app._build_prompt("What first?", hits)

    assert "[1] (playbooks/ransomware.md)\nIsolate the host." in prompt
    assert "[2] (phishing.md)\nReset credentials." in prompt
    assert prompt.rstrip().endswith("Question: What first?\nAnswer:")


def test_build_prompt_numbers_blocks_with_page_labels():
    hits = [
        Hit(text="Table 17", score=0.9, source="manual.pdf", metadata={"page_label": "64"}),
        Hit(text="No page", score=0.8, source="notes.md", metadata={"page_label": ""}),
        Hit(text="Orphan", score=0.7, source=None),
    ]
    prompt = app._build_prompt("Q?", hits)

    assert "[1] (manual.pdf, p. 64)\nTable 17" in prompt
    assert "[2] (notes.md)\nNo page" in prompt
    assert "[3] (unknown source)\nOrphan" in prompt
    assert "cite nothing" in prompt


@pytest.mark.parametrize("answer,n_hits,expected", [
    ("Use Table 17 [2].", 4, [2]),
    ("Both apply [1][3], see also [1].", 4, [1, 3]),
    ("Both apply [3, 1].", 4, [3, 1]),
    ("Both apply [1;2].", 4, [1, 2]),
    ("Pages [2-4] and [1–2].", 4, [2, 3, 4, 1]),
    ("Made up [7], a year [2024], a zero [0].", 4, []),
    ("Mixed [2, 9].", 4, [2]),
    ("Range past the end [3-9].", 4, []),
    ("Malformed [1-2-3] [ 2 ] [a] [] [1,] [,1]", 4, [2]),
    ("The context doesn't contain that.", 4, []),
    ("Nothing to cite [1].", 0, []),
])
def test_cited_indices(answer, n_hits, expected):
    assert app._cited_indices(answer, n_hits) == expected


@pytest.mark.parametrize("answer,expected", [
    ("Both [1, 3] and [2-4].", "Both [1][3] and [2][3][4]."),
    ("Keep [2] and [1][2].", "Keep [2] and [1][2]."),
    ("Drop bad parts [2, 9].", "Drop bad parts [2]."),
    ("Leave [2024] and [a] alone.", "Leave [2024] and [a] alone."),
])
def test_split_citations(answer, expected):
    assert app._split_citations(answer, 4) == expected


def _hit(source, page=None):
    return Hit(text=f"{source} p{page}", score=1.0, source=source,
               metadata={"page_label": page} if page is not None else {})


def test_format_sources_lists_only_cited_passages():
    hits = [_hit("manual.pdf", "64"), _hit("other.pdf", "3")]

    assert app._format_sources(hits, [1]) == "**Sources:** `manual.pdf`, p. 64"


def test_format_sources_groups_pages_per_file():
    hits = [
        _hit("manual.pdf", "59"), _hit("guide.md"), _hit("manual.pdf", "58"),
        _hit("manual.pdf", "12"), _hit("manual.pdf", "59"), _hit("manual.pdf", "iv"),
    ]

    assert app._format_sources(hits, [1, 3, 5]) == "**Sources:** `manual.pdf`, pp. 58–59"
    assert app._format_sources(hits, [4, 1, 2, 3]) == (
        "**Sources:** `manual.pdf`, pp. 12, 58–59; `guide.md`"
    )
    assert app._format_sources(hits, [6, 4]) == "**Sources:** `manual.pdf`, pp. iv, 12"


def test_format_sources_none_without_citations():
    assert app._format_sources([_hit("manual.pdf", "64")], []) is None


def test_cited_passages_are_named_like_the_markers():
    hits = [_hit("manual.pdf", "64"), _hit("guide.md")]

    passages = app._cited_passages(hits, [2, 1])

    assert passages == [
        ("[2]", "**guide.md**\n\nguide.md pNone"),
        ("[1]", "**manual.pdf, p. 64**\n\nmanual.pdf p64"),
    ]


def test_history_actions_payloads_and_cap():
    sessions = [{"session_id": f"s{i}", "title": f"Chat {i}"} for i in range(12)]

    actions = app._history_actions(sessions, limit=10)

    loads = [a for a in actions if a.name == "load_chat"]
    deletes = [a for a in actions if a.name == "delete_chat"]
    assert [a.payload for a in loads] == [{"session_id": f"s{i}"} for i in range(10)]
    assert [a.label for a in loads] == [f"Chat {i}" for i in range(10)]
    assert [a.payload for a in deletes] == [a.payload for a in loads]
    assert actions[-1].name == "clear_all_history"


def test_history_actions_empty():
    assert app._history_actions([]) == []


def _login(monkeypatch, env, username, password):
    monkeypatch.setattr(app, "_config", lambda: load_config(env))
    return asyncio.run(app.auth_callback(username, password))


# Generated per run so no credential-looking literal lives in the repo.
TEST_USER = "analyst"
TEST_PASSWORD = secrets.token_urlsafe(16)
TEST_ENV = {"CHAINLIT_AUTH_USERNAME": TEST_USER, "CHAINLIT_AUTH_PASSWORD": TEST_PASSWORD}


def test_auth_accepts_configured_credentials(monkeypatch):
    user = _login(monkeypatch, TEST_ENV, TEST_USER, TEST_PASSWORD)
    assert user is not None and user.identifier == TEST_USER


@pytest.mark.parametrize("username,password", [
    (TEST_USER, TEST_PASSWORD + "x"),
    ("someone-else", TEST_PASSWORD),
    ("", ""),
])
def test_auth_rejects_wrong_credentials(monkeypatch, username, password):
    assert _login(monkeypatch, TEST_ENV, username, password) is None


def test_auth_rejects_everyone_when_unconfigured(monkeypatch):
    assert _login(monkeypatch, {}, TEST_USER, TEST_PASSWORD) is None


# ---------------------------------------------------------------------------
# LLM provider
# ---------------------------------------------------------------------------

def test_make_llm_ollama_uses_large_context_and_base_url():
    llm = app._make_llm(load_config({"OLLAMA_BASE_URL": "http://gpu-box:11434"}))

    assert type(llm).__name__ == "Ollama"
    assert llm.model == "qwen2.5:14b"
    assert llm.base_url == "http://gpu-box:11434"
    assert llm.context_window == app.OLLAMA_CONTEXT_WINDOW >= 8192


def test_make_llm_openrouter_needs_key():
    with pytest.raises(ValueError, match="OPENROUTER_API_KEY"):
        app._make_llm(load_config({"LLM_PROVIDER": "openrouter"}))

    llm = app._make_llm(load_config({"LLM_PROVIDER": "openrouter", "OPENROUTER_API_KEY": "test-key"}))
    assert type(llm).__name__ == "OpenAI"
    assert llm.api_base == "https://openrouter.ai/api/v1"


def test_model_label_says_where_it_runs():
    assert "local" in app._model_label(load_config({}))
    assert "OpenRouter" in app._model_label(load_config({"LLM_PROVIDER": "openrouter"}))


class _FakeResponse:
    def __init__(self, models):
        self._models = models

    def raise_for_status(self):
        pass

    def json(self):
        return {"models": [{"name": name} for name in self._models]}


def test_check_ollama_passes_when_model_pulled(monkeypatch):
    import httpx

    monkeypatch.setattr(httpx, "get", lambda *a, **k: _FakeResponse(["qwen2.5:14b", "llama3.1:8b"]))
    app._check_ollama(load_config({}))


def test_check_ollama_accepts_implicit_latest_tag(monkeypatch):
    import httpx

    monkeypatch.setattr(httpx, "get", lambda *a, **k: _FakeResponse(["mistral:latest"]))
    app._check_ollama(load_config({"MODEL_NAME": "mistral"}))


def test_check_ollama_reports_missing_model(monkeypatch):
    import httpx

    monkeypatch.setattr(httpx, "get", lambda *a, **k: _FakeResponse(["llama3.1:8b"]))
    with pytest.raises(RuntimeError, match="ollama pull qwen2.5:14b"):
        app._check_ollama(load_config({}))


def test_check_ollama_reports_server_down(monkeypatch):
    import httpx

    def refuse(*_args, **_kwargs):
        raise httpx.ConnectError("connection refused")

    monkeypatch.setattr(httpx, "get", refuse)
    with pytest.raises(RuntimeError, match="isn't running at http://localhost:11434"):
        app._check_ollama(load_config({}))


# ---------------------------------------------------------------------------
# Citation styles from other models
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("answer, expected", [
    ("Florida uses > 3 inches 【2】.", [2]),
    ("See ［1］ and ［3］.", [1, 3]),
    ("Mixed [1] and 【2】.", [1, 2]),
])
def test_cited_indices_accepts_lenticular_and_fullwidth_brackets(answer, expected):
    assert app._cited_indices(answer, 4) == expected


def test_split_citations_normalises_to_square_brackets():
    assert app._split_citations("It is 1.3【2】 or ［1, 3］.", 4) == "It is 1.3[2] or [1][3]."


@pytest.mark.parametrize("answer", [
    "The context does not cover it. [None]",
    "The context does not cover it.【none】",
    "The context does not cover it. [N/A]",
])
def test_split_citations_drops_empty_markers(answer):
    assert app._split_citations(answer, 4) == "The context does not cover it."
