# RAG-Chatbot

An IT support and incident response chatbot. It indexes documents from `data/` into ChromaDB and answers questions about them through a Chainlit chat UI. A FastAPI retrieval API ingests and queries the same index.

- **Chat UI** (`app.py`, Chainlit): retrieves relevant chunks, streams an answer from an LLM, and cites its sources. By default the LLM runs locally through Ollama; OpenRouter is optional. It requires login and keeps chat history per user.
- **Retrieval API** (`server.py`, FastAPI): `POST /api/ingest` uploads documents and rebuilds the index. `POST /api/query` returns ranked chunks with metadata and never calls an LLM.
- **Shared core** (`rag/`): both entrypoints use one Retrieval index.

## Setup

```bash
py -m venv .venv
.venv\Scripts\activate            # Windows  (source .venv/bin/activate elsewhere)
pip install -r requirements.txt
copy .env.example .env            # then edit .env
```

Install [Ollama](https://ollama.com) and pull the default model (about 9 GB; it fits a 12 GB GPU):

```bash
winget install Ollama.Ollama
ollama pull qwen2.5:14b
```

Required in `.env` for the chat UI:

| Variable | Purpose |
|---|---|
| `CHAINLIT_AUTH_SECRET` | Signs login sessions. Generate one with `chainlit create-secret` |
| `CHAINLIT_AUTH_USERNAME` / `CHAINLIT_AUTH_PASSWORD` | The login. If either is unset, every login is refused |

Choosing the LLM:

| Variable | Default | Purpose |
|---|---|---|
| `LLM_PROVIDER` | `ollama` | `ollama` (local) or `openrouter` (remote) |
| `MODEL_NAME` | `qwen2.5:14b` / `gpt-4o` | The model, defaulting per provider |
| `OLLAMA_BASE_URL` | `http://localhost:11434` | Where Ollama is running |
| `OPENROUTER_API_KEY` | — | Only needed with `LLM_PROVIDER=openrouter` |

If Ollama isn't running, or the model hasn't been pulled, the chat says so and tells you the command to fix it.

Every other setting is optional; see `.env.example`. Relative paths resolve against the repo root, whatever the working directory. The embedding model (`BAAI/bge-small-en-v1.5`) downloads on first use.

## Running

```bash
chainlit run app.py                  # chat UI on http://localhost:8000
uvicorn server:app --port 8001       # retrieval API, docs at http://localhost:8001/docs
```

Both build the index once at startup if it is empty. After that, the index changes only when you ask it to:

```bash
py -m rag refresh    # rebuild from everything in data/
py -m rag stats      # collection, document and vector counts, last refresh time
```

Dropping a file into `data/` does nothing until you run a refresh or ingest through the API.

## Privacy

Indexing, embeddings, search and chat history all stay on your machine. What leaves it depends on `LLM_PROVIDER`:

- **`ollama` (default):** no document text leaves the machine. The only outbound traffic is model downloads (Hugging Face for the embedding model, Ollama for the LLM) and library telemetry, which you can turn off (see the end of `.env.example`).
- **`openrouter`:** every chat question sends the question, the 4 best-matching passages and their file paths to OpenRouter, which passes them to the model's provider. Check OpenRouter's privacy settings if the documents are sensitive.

`POST /api/query` never calls an LLM, so it's local with either provider.

## Retrieval API

```bash
curl -F files=@playbook.md -F files=@runbook.pdf localhost:8001/api/ingest

curl -H "content-type: application/json" localhost:8001/api/query \
     -d '{"query": "contain infected hosts", "top_k": 4, "where": {"incident_type": "ransomware"}}'

curl localhost:8001/health
```

- **Ingest:** the whole batch is validated before anything is written. Filenames are reduced to their base name. Uploading a file with the same name replaces the existing one. If the rebuild fails, the uploads are removed and any replaced files are restored.
- **Query:** returns 503 until something has been indexed. `where` filters on the classification fields below. Each result has `text`, `source`, `score`, `incident_type`, `doc_domain`, plus `page` (the PDF page label, `null` for formats without pages) and `section` (the heading the chunk sits under, `null` when unknown), so a citation can point to where in the source the answer came from.

## Document metadata

Each Document is labelled from its **path relative to `data/`**, never from its content:

- `incident_type`: e.g. `ransomware`, `phishing` or `credential_dumping`. The most specific keyword wins.
- `doc_domain`: `ir`, `general` or `asset_inventory`.
- `tags`, `asset_scope`, `doc_type`, and `source` (the relative path).

Filenames matter: `playbooks/ransomware_containment.md` is filed and filterable as ransomware. The keyword lists are in `rag/classify.py`.

## Supported formats

The single source of truth is `FORMATS` in [`rag/loader.py`](rag/loader.py). The API's allowlist and the ingest error message are derived from it.

- **Always available:** PDF, DOCX, PPTX, Markdown, text, CSV, JSON/JSONL, HTML, XML/YAML/INI/config, scripts, logs, XLSX/XLS, EML/MSG.
- **Only available when the tool is on `PATH`:**

  | Formats | Tool |
  |---|---|
  | Images (OCR) | `tesseract` |
  | `.doc`, `.ppt` | `soffice` (LibreOffice) |
  | `.rtf`, `.odt` | `pandoc` |

  On hosts without the tool, those extensions are rejected at ingest and skipped when loading.

## Login and chat history

**Login.** `auth_callback` in `app.py` checks the submitted credentials against `CHAINLIT_AUTH_USERNAME` and `CHAINLIT_AUTH_PASSWORD`, using a constant-time comparison. There are no built-in defaults: if either variable is unset, every login is refused and the server logs why. Changing `CHAINLIT_AUTH_SECRET` logs everyone out.

**Separate users.** This is one shared account, so everyone who uses it sees the same history. To give each user their own, replace `auth_callback` with a lookup against your user store, or switch to Chainlit's OAuth or header auth. The user's identifier becomes their history folder name; characters other than letters, digits, `_` and `-` are replaced with `_`.

**Recent chats.** When a chat starts, and after you delete one, the app posts a **Recent chats** message with buttons for up to 10 sessions, newest first:
- click a title to replay that chat and keep going in it
- the trash icon deletes a chat
- **Clear all** deletes every chat for the current user

A chat's title is its first message, cut to 50 characters. Chainlit's own thread sidebar stays empty, because history is kept by the app's own JSON store (`chat_history.py`), not a Chainlit data layer.

**Saving.** A chat is saved after every reply, so reloading the page loses nothing, and again when the chat ends. It's only saved once you've sent at least one message. When a user has more than `MAX_CHAT_HISTORY` chats (default 50), the oldest are deleted.

**Storage.** Each chat is a JSON file at `chat_history/<user>/<session>.json`, and `chat_history/` is gitignored. Session and user ids must match `[A-Za-z0-9_-]{1,64}`, so an id can't point outside the storage directory. The other settings are `ENABLE_CHAT_HISTORY` (default `true`) and `CHAT_STORAGE_DIR` (default `chat_history`).

```json
{
  "session_id": "uuid", "title": "First user message…", "timestamp": "ISO-8601", "message_count": 1,
  "messages": [
    {"type": "user_message", "content": "...", "timestamp": "ISO-8601", "author": "User"},
    {"type": "assistant_message", "content": "...", "timestamp": "ISO-8601", "author": "Assistant"}
  ]
}
```

**Chainlit settings.** `.chainlit/config.toml` turns off two features:
- message editing, because an edited message would no longer match the saved history
- file upload in the chat, because those files aren't indexed; use `POST /api/ingest` instead

**Troubleshooting.**
- *Every login is rejected:* check that both `CHAINLIT_AUTH_USERNAME` and `CHAINLIT_AUTH_PASSWORD` are set in `.env`, and read the server log.
- *Chainlit complains about a missing auth secret:* set `CHAINLIT_AUTH_SECRET`.
- *You're logged out after a restart:* the secret changed.

## Tests

```bash
.venv\Scripts\python -m pytest tests/
```

The tests use a real ChromaDB in a temp directory and a deterministic hash embedding, so nothing is downloaded. Tests that need Tesseract or LibreOffice are skipped when the tool is missing.

**Manual smoke test for the chat UI** (needs Ollama running with the model pulled, or `LLM_PROVIDER=openrouter` with a real key):
1. Log in.
2. Ask about a document in `data/`, and check that the answer streams and cites `Sources`.
3. Reload the page, load the chat from **Recent chats**, then delete it.

## License

MIT
