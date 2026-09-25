# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Commands

```bash
pip install -r requirements.txt

# Chainlit chat UI (port 8000 by default)
chainlit run app.py

# Retrieval API (server.py mounts api.router)
uvicorn server:app --port 8001

# Rebuild / inspect the Retrieval index from the command line
py -m rag refresh
py -m rag stats

# Test suite
pytest tests/
pytest tests/test_api.py                                                  # one file
pytest tests/test_retrieval_index.py::test_failed_refresh_keeps_previous_index   # one test
pytest tests/ -k "ingest"                                                 # by keyword
```

There is no lint/format/typecheck tooling and no `pyproject.toml`/`pytest.ini`. Run `pytest` from the repo root — `tests/test_api.py` imports `tests.conftest`, which needs the root on `sys.path` (provided by `tests/__init__.py` + pytest rootdir insertion).

On this machine `python` resolves to the Microsoft Store alias; use `py` (Python 3.13) or the `.venv` interpreter.

## Architecture

Read `CONTEXT.md` first — it defines Retrieval index, Hit, Document, Document classification, Document loader and Upload staging, and code should use those names.

The `rag/` package is the retrieval core. `server.py`/`api.py` (FastAPI) and `app.py` (Chainlit) are thin entrypoints over it and share **one** ChromaDB index.

- `rag/config.py` — `load_config(env) -> AppConfig` (frozen, hashable). The only place env vars are read and defaults live. Relative paths resolve against the repo root, not the cwd.
- `rag/loader.py` — `FORMATS`, the single extension → (doc_type, reader, requires) table. `supported_extensions()` is the ingest allowlist; it is computed per call and leaves out formats whose external tool (`requires`: `tesseract`, `soffice`, `pandoc`) is not on PATH. `load(data_dir)` walks recursively, skips hidden and unsupported files, drops empty Documents, and attaches metadata with `source` = the POSIX path relative to `data_dir`. Readers: LlamaIndex defaults, plain text, or `UnstructuredReader` (imported only when such a file is present).
- `rag/classify.py` — `classify(relative_path) -> DocClassification`. Metadata comes from **path tokens only**, never content. Keywords match whole tokens; keywords of ≥4 chars also match as a token prefix; multi-word keywords match consecutive tokens. The label with the most specific matching keyword (more words, then more characters) wins; ties go to the earlier label in `INCIDENT_KEYWORDS`. Filenames are load-bearing: renaming a Document changes its metadata.
- `rag/index.py` — `RetrievalIndex(config, embed_model)` with `refresh()`, `retrieve(q, k, where)`, `stats()` and `ensure_built()`. **Refresh is explicit only**: `retrieve` never rebuilds or writes, so files dropped into `data/` by hand are invisible until something calls `refresh()`. A refresh builds into `<collection>__staging` and swaps it in only on success, so a failed refresh leaves the old index serving. Stats (`documents`, `last_refresh_at`) are stored in the Chroma collection's metadata; there is no `index_meta.json`. A single RLock serialises refresh and retrieve within one instance. Instances never cache the Chroma collection: every call looks it up by name (waiting up to 5s if another instance is mid-swap), so the API server, the Chainlit app and `py -m rag refresh` see each other's refreshes. Concurrent refreshes from *different processes* are not coordinated.
- `rag/staging.py` — `stage(data_dir, uploads, allowed)` validates the whole batch (extension, duplicates, filename reduced to its final component) before touching disk. The resulting context manager places the files, then on exit keeps them or rolls back and restores any files they overwrote.
- `api.py` — the `/api/ingest` and `/api/query` router. It gets `get_config` and `get_index` through FastAPI `Depends`; `get_index` caches one `RetrievalIndex` per `AppConfig` and calls `ensure_built()` on first use. Endpoints are sync `def` (they run in the threadpool). `/api/query` is retrieval only, with optional `where` metadata filters, and returns 503 when the index is empty.
- `server.py` — the ASGI app: mounts `api.router` and adds `GET /health` (index stats). Calls `load_dotenv()` at import.
- `app.py` — nothing heavy at import time. `_config()` (lru_cache, runs `load_dotenv`) and `_runtime()` (lru_cache: index via `ensure_built` + OpenRouter LLM, `llama_index.llms.openai.OpenAI` with `api_base=https://openrouter.ai/api/v1`) are built on first use. Each message retrieves Hits, formats a prompt, streams `llm.astream_complete`, appends the sources and saves the session. `auth_callback` (async, as Chainlit 2 expects) checks `CHAINLIT_AUTH_USERNAME`/`CHAINLIT_AUTH_PASSWORD` with `hmac.compare_digest` and refuses everyone when they're unset. The chat-history UI is a "Recent chats" message with `cl.Action` buttons (`load_chat`, `delete_chat`, `clear_all_history`) carrying `payload={"session_id": ...}`.
- `chat_history.py` — `ChatHistoryManager(storage_dir, max_history, user_id)`, with no module singleton. Sessions are stored per user under `<storage_dir>/<user_id>/`, and ids are restricted to `[A-Za-z0-9_-]{1,64}`.

## Tests

`tests/` is the only suite. `conftest.py` provides `_HashEmbedding` (deterministic SHA-256 32-dim vectors, so no model download). The `config`/`seeded_config`/`index` fixtures are isolated with `tmp_path`, and `make_client(index)` injects the index through `app.dependency_overrides` — no env monkeypatching. ChromaDB is **not** mocked. Tests go through the module interfaces (`refresh`/`retrieve`/`stats`, `classify`, `load`, `stage`) and check metadata on real Hits. `tests/test_app.py` covers `app.py`'s pure helpers, auth and import safety (it needs `chainlit` installed); the Chainlit handlers themselves are only covered by the manual smoke test in `README.md`. Tests needing Tesseract/LibreOffice skip when the tool is absent.

The `.venv` needs the full `requirements.txt`, including `chainlit` and `unstructured`. On Windows, `python-magic` hangs importing a foreign libmagic DLL from PATH (Git's mingw64 ships one); `python-magic-bin` (in requirements for win32) fixes it. Wrap pytest in `timeout` if unstructured is ever reinstalled.

## Configuration

Copy `.env.example` to `.env`. The chat UI needs `OPENROUTER_API_KEY`, `CHAINLIT_AUTH_SECRET`, `CHAINLIT_AUTH_USERNAME` and `CHAINLIT_AUTH_PASSWORD`. The full list of vars and their defaults is `rag/config.py`. `.chainlit/config.toml` is committed (rest of `.chainlit/` is ignored) with message editing and chat file upload turned off.

## Known gaps

- Chat sessions are persisted by the project's own JSON store (`chat_history.py` → `./chat_history/<user_id>/<session_id>.json`), not a Chainlit data layer, so Chainlit's built-in thread sidebar stays empty; history is reached through the "Recent chats" action buttons.
- Login is a single shared account from env vars, so everyone using it shares one history.
