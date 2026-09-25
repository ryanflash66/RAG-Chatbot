# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Commands

```bash
pip install -r requirements.txt

# Chainlit chat UI (port 8000 by default)
chainlit run app.py

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

The `rag/` package is the retrieval core. `api.py` (FastAPI) and `app.py` (Chainlit) are thin entrypoints over it and share **one** ChromaDB index.

- `rag/config.py` — `load_config(env) -> AppConfig` (frozen, hashable). The only place env vars are read and defaults live. Relative paths resolve against the repo root, not the cwd.
- `rag/loader.py` — `FORMATS`, the single extension → (doc_type, reader) table. `supported_extensions()` is the ingest allowlist. `load(data_dir)` walks recursively, skips hidden and unsupported files, drops empty Documents, and attaches metadata with `source` = the POSIX path relative to `data_dir`. Readers: LlamaIndex defaults, plain text, or `UnstructuredReader` (imported only when such a file is present).
- `rag/classify.py` — `classify(relative_path) -> DocClassification`. Metadata comes from **path tokens only**, never content. Keywords match whole tokens; keywords of ≥4 chars also match as a token prefix; multi-word keywords match consecutive tokens. The first `INCIDENT_KEYWORDS` label in dict order wins. Filenames are load-bearing: renaming a Document changes its metadata.
- `rag/index.py` — `RetrievalIndex(config, embed_model)` with `refresh()`, `retrieve(q, k, where)`, `stats()` and `ensure_built()`. **Refresh is explicit only**: `retrieve` never rebuilds or writes, so files dropped into `data/` by hand are invisible until something calls `refresh()`. A refresh builds into `<collection>__staging` and swaps it in only on success, so a failed refresh leaves the old index serving. Stats (`documents`, `last_refresh_at`) are stored in the Chroma collection's metadata; there is no `index_meta.json`. A single RLock serialises refresh and retrieve.
- `rag/staging.py` — `stage(data_dir, uploads, allowed)` validates the whole batch (extension, duplicates, filename reduced to its final component) before touching disk. The resulting context manager places the files, then on exit keeps them or rolls back and restores any files they overwrote.
- `api.py` — the `/api/ingest` and `/api/query` router. It gets `get_config` and `get_index` through FastAPI `Depends`; `get_index` caches one `RetrievalIndex` per `AppConfig` and calls `ensure_built()` on first use. Endpoints are sync `def` (they run in the threadpool). `/api/query` is retrieval only, with optional `where` metadata filters, and returns 503 when the index is empty. **`api.router` is not mounted anywhere** — serving it needs an ASGI app.
- `app.py` — nothing heavy at import time. `_runtime()` (lru_cache) builds the config, the index (`ensure_built`) and the OpenRouter LLM (`llama_index.llms.openai.OpenAI`, `api_base=https://openrouter.ai/api/v1`) on the first chat. Each message retrieves Hits, formats a prompt, streams `llm.astream_complete` and appends the sources.
- `chat_history.py` — `ChatHistoryManager(storage_dir, max_history, user_id)`, with no module singleton. Sessions are stored per user under `<storage_dir>/<user_id>/`, and ids are restricted to `[A-Za-z0-9_-]{1,64}`.

## Tests

`tests/` is the only suite. `conftest.py` provides `_HashEmbedding` (deterministic SHA-256 32-dim vectors, so no model download). The `config`/`seeded_config`/`index` fixtures are isolated with `tmp_path`, and `make_client(index)` injects the index through `app.dependency_overrides` — no env monkeypatching. ChromaDB is **not** mocked. Tests go through the module interfaces (`refresh`/`retrieve`/`stats`, `classify`, `load`, `stage`) and check metadata on real Hits. Chainlit is not installed in `.venv` and `app.py` has no tests.

## Configuration

Copy `.env.example` to `.env`. `OPENROUTER_API_KEY` is required for the Chainlit app (`README.md` still says `OPENAI_API_KEY` — stale). The full list of vars and their defaults is `rag/config.py`.

## Known gaps in the Chainlit chat history

The markdown docs (`CHAT_HISTORY_IMPLEMENTATION.md`, `AUTHENTICATION_SETUP.md`) describe a working sidebar; the code is only partly there.

- `app.py` registers `@cl.action_callback` handlers for `load_chat`, `delete_chat`, and `clear_all_history`, but **nothing ever sends a `cl.Action`** with those names, so they are unreachable from the UI.
- `.chainlit/config.toml` is referenced by the docs but does not exist in the repo.
- Sessions are persisted by the project's own JSON writer (`chat_history.py` → `./chat_history/<user_id>/<session_id>.json`), not by a Chainlit data layer, so Chainlit's built-in history UI won't see them.
- The action callbacks read `action.value`; newer Chainlit versions use `payload` (Chainlit is unpinned).
- `auth_callback` in `app.py` hardcodes `admin` / `password`.
