"""The hosted prototype: search over a precomputed index, small enough for Vercel.

Documents are loaded, chunked and embedded offline (`prototype.ingest`), with
the same PDF-to-Markdown loader and table-aware chunking as the Chainlit app.
The result is a pair of plain files (`prototype.index_file`). At query time only
the question is embedded (`prototype.embedder`), and hits are found with numpy
cosine similarity. Nothing here calls a paid API.

`embedder` and `index_file` need only numpy and fastembed
(requirements-prototype.txt), so a serverless function can import them without
the Chainlit app's dependencies. `ingest` runs on a developer machine with the
full requirements.txt plus fastembed.
"""
