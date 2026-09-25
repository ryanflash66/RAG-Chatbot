"""Tests for ChatHistoryManager with an injected storage directory."""

import pytest

from chat_history import ChatHistoryManager

MESSAGES = [
    {"type": "user_message", "content": "How do I reset a password?"},
    {"type": "assistant_message", "content": "Use the admin console."},
]


def test_save_load_round_trip(tmp_path):
    history = ChatHistoryManager(tmp_path)
    history.save_chat_session("abc-123", MESSAGES)

    session = history.load_chat_session("abc-123")

    assert session["title"] == "How do I reset a password?"
    assert session["message_count"] == 1
    assert session["messages"] == MESSAGES


def test_sessions_are_scoped_per_user(tmp_path):
    alice = ChatHistoryManager(tmp_path, user_id="alice")
    bob = ChatHistoryManager(tmp_path, user_id="bob")
    alice.save_chat_session("s1", MESSAGES)

    assert [s["session_id"] for s in alice.get_chat_history()] == ["s1"]
    assert bob.get_chat_history() == []
    assert bob.load_chat_session("s1") is None


def test_max_history_prunes_oldest(tmp_path):
    history = ChatHistoryManager(tmp_path, max_history=2)
    for sid in ("s1", "s2", "s3"):
        history.save_chat_session(sid, MESSAGES)

    assert len(history.get_chat_history()) == 2


@pytest.mark.parametrize("bad_id", ["../escape", "a/b", "..", "", "x" * 65])
def test_invalid_session_ids_cannot_touch_the_filesystem(tmp_path, bad_id):
    history = ChatHistoryManager(tmp_path / "store")

    with pytest.raises(ValueError):
        history.save_chat_session(bad_id, MESSAGES)
    assert history.load_chat_session(bad_id) is None
    assert history.delete_chat_session(bad_id) is False
    assert not any((tmp_path).glob("*.json"))


def test_invalid_user_id_rejected(tmp_path):
    with pytest.raises(ValueError):
        ChatHistoryManager(tmp_path, user_id="../other")


def test_delete(tmp_path):
    history = ChatHistoryManager(tmp_path)
    history.save_chat_session("s1", MESSAGES)
    assert history.delete_chat_session("s1") is True
    assert history.load_chat_session("s1") is None
