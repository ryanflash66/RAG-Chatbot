# Chat history

Chat sessions are saved by the project's own JSON store (`chat_history.py`), not by a Chainlit data layer. Chainlit's built-in thread sidebar therefore stays empty; history is reached through the **Recent chats** buttons instead.

## What the user sees

When a chat starts, and after deleting a chat, the app posts a **Recent chats** message with buttons for up to 10 sessions, newest first:

- **the chat's title**: replays that session and continues it, so new messages are saved into the same session
- **trash icon**: deletes that session
- **Clear all**: deletes every session for the current user

Titles come from the first user message, cut to 50 characters.

## When sessions are saved

- after every assistant reply, so reloading the page loses nothing
- again when the chat ends

A session is saved only once it contains at least one user message. When the number of sessions goes over `MAX_CHAT_HISTORY`, the oldest are deleted.

## Storage

```
chat_history/
  <user_id>/
    <session_id>.json
```

- `chat_history/` is gitignored.
- `ChatHistoryManager(storage_dir, max_history, user_id)` takes all of its settings as arguments; `app.py` builds one per request from `AppConfig`.
- Session and user ids must match `[A-Za-z0-9_-]{1,64}`. Anything else is rejected, so an id can't point outside the storage directory.

Session file format:

```json
{
  "session_id": "uuid",
  "title": "First user message…",
  "timestamp": "ISO-8601",
  "message_count": 2,
  "messages": [
    {"type": "user_message", "content": "...", "timestamp": "ISO-8601", "author": "User"},
    {"type": "assistant_message", "content": "...", "timestamp": "ISO-8601", "author": "Assistant"}
  ]
}
```

## Configuration

| Variable | Default |
|---|---|
| `ENABLE_CHAT_HISTORY` | `true` |
| `MAX_CHAT_HISTORY` | `50` (per user) |
| `CHAT_STORAGE_DIR` | `chat_history` (relative to the repo root) |

## Chainlit settings

In `.chainlit/config.toml`:

- `edit_message = false`, because an edited message would no longer match the saved history
- `spontaneous_file_upload` is off, because files dropped into the chat aren't indexed; use `POST /api/ingest` instead

## Tests

- `tests/test_chat_history.py`: saving and loading, per-user scoping, pruning, id validation
- `tests/test_app.py`: the payloads on the Recent chats buttons
