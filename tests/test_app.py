"""Tests for the Chainlit entrypoint's pure helpers and import safety.

The Chainlit handlers themselves need a running Chainlit context and are
covered by the manual smoke test in README.md.
"""

import asyncio
import importlib

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


def test_auth_accepts_configured_credentials(monkeypatch):
    env = {"CHAINLIT_AUTH_USERNAME": "analyst", "CHAINLIT_AUTH_PASSWORD": "s3cret"}
    user = _login(monkeypatch, env, "analyst", "s3cret")
    assert user is not None and user.identifier == "analyst"


@pytest.mark.parametrize("username,password", [("analyst", "wrong"), ("admin", "s3cret"), ("", "")])
def test_auth_rejects_wrong_credentials(monkeypatch, username, password):
    env = {"CHAINLIT_AUTH_USERNAME": "analyst", "CHAINLIT_AUTH_PASSWORD": "s3cret"}
    assert _login(monkeypatch, env, username, password) is None


def test_auth_rejects_everyone_when_unconfigured(monkeypatch):
    assert _login(monkeypatch, {}, "admin", "password") is None
