# Division documents (not committed)

One folder per division id from `hosted/divrag/divisions.py`, holding that division's
PDFs. They are gitignored and left out of Vercel uploads: the deployed app reads only
the index built from them (`hosted/index/`).

From the repo root:

```bash
.venv\Scripts\python hosted/scripts/fetch_documents.py   # download every listed PDF here
.venv\Scripts\python -m prototype.ingest                 # rebuild hosted/index/ from them
```

Each file's source URL, page count and fetch date are in `docs/source-documents/SOURCES.md`.
