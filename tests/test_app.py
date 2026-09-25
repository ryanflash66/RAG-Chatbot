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

    assert "[playbooks/ransomware.md]\nIsolate the host." in prompt
    assert "[phishing.md]\nReset credentials." in prompt
    assert prompt.rstrip().endswith("Question: What first?\nAnswer:")


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
