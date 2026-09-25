# RAG-Chatbot

An IT support and incident response chatbot. It indexes documents from `data/` into ChromaDB and answers questions about them through a Chainlit chat UI. A FastAPI retrieval API ingests and queries the same index.

- **Chat UI** (`app.py`, Chainlit): retrieves relevant chunks, streams an answer from an OpenRouter-hosted LLM, and cites its sources. It requires login and keeps chat history per user.
- **Retrieval API** (`server.py`, FastAPI): `POST /api/ingest` uploads documents and rebuilds the index. `POST /api/query` returns ranked chunks with metadata and never calls an LLM.
- **Shared core** (`rag/`): both entrypoints use one Retrieval index. See [`CONTEXT.md`](CONTEXT.md) for the vocabulary.

## Setup

```bash
py -m venv .venv
.venv\Scripts\activate            # Windows  (source .venv/bin/activate elsewhere)
pip install -r requirements.txt
copy .env.example .env            # then edit .env
```

Required in `.env` for the chat UI:

| Variable | Purpose |
|---|---|
| `OPENROUTER_API_KEY` | LLM access via OpenRouter |
| `CHAINLIT_AUTH_SECRET` | Signs login sessions. Generate one with `chainlit create-secret` |
| `CHAINLIT_AUTH_USERNAME` / `CHAINLIT_AUTH_PASSWORD` | The login. If either is unset, every login is refused |

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

## Retrieval API

```bash
curl -F files=@playbook.md -F files=@runbook.pdf localhost:8001/api/ingest

curl -H "content-type: application/json" localhost:8001/api/query \
     -d '{"query": "contain infected hosts", "top_k": 4, "where": {"incident_type": "ransomware"}}'

curl localhost:8001/health
```

- **Ingest:** the whole batch is validated before anything is written. Filenames are reduced to their base name. Uploading a file with the same name replaces the existing one. If the rebuild fails, the uploads are removed and any replaced files are restored.
- **Query:** returns 503 until something has been indexed. `where` filters on the classification fields below.

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

## Chat history

After logging in, each chat is saved as you go under `chat_history/<user>/<session>.json`. A **Recent chats** message at the start of each chat has buttons to load a chat (and keep going in it), delete one, or clear everything. See [`CHAT_HISTORY_IMPLEMENTATION.md`](CHAT_HISTORY_IMPLEMENTATION.md) and [`AUTHENTICATION_SETUP.md`](AUTHENTICATION_SETUP.md).

## Tests

```bash
.venv\Scripts\python -m pytest tests/
```

The tests use a real ChromaDB in a temp directory and a deterministic hash embedding, so nothing is downloaded. Tests that need Tesseract or LibreOffice are skipped when the tool is missing.

**Manual smoke test for the chat UI** (needs a real `OPENROUTER_API_KEY`):
1. Log in.
2. Ask about a document in `data/`, and check that the answer streams and cites `Sources`.
3. Reload the page, load the chat from **Recent chats**, then delete it.

## License

MIT
