# Domain glossary

Terms used when talking about this codebase's design. Code, docs and reviews should use these names.

## Retrieval index
The single vector index over `DATA_DIR`, stored in ChromaDB. The FastAPI stack and the Chainlit UI both use it.

- **Refresh:** rebuilds the index from the current documents. It runs only when asked, meaning after an ingest or through an explicit `refresh()` call.
- **Retrieve:** a read-only query. It can filter on Document classification fields such as `incident_type`. It never rebuilds and never writes index metadata. A stale index stays stale until someone refreshes it.

## Hit
One retrieved chunk as the rest of the code sees it: text, score, and the document's classification. It is a plain value, and LlamaIndex node types never leave the Retrieval index.

## Document
A file under `DATA_DIR`, JSON included. Its identity is its path relative to `DATA_DIR`. Hidden files and extensions missing from the Document loader's table are not Documents. Index bookkeeping lives in ChromaDB, never under `DATA_DIR`.

## Document classification
The metadata derived for each Document: `incident_type`, `doc_domain`, `tags`, `asset_scope`. (`doc_type` comes from the Document loader's format table.) It comes only from the Document's **relative path**, split into whole-word tokens. When several incident labels match, the most specific keyword wins. Content, the absolute path and the repo location never affect it. Filenames are therefore load-bearing.

## Document loader
The single table of supported file extensions, each paired with its reader, its `doc_type`, and any external tool it needs. The ingest allowlist is derived from it and only includes formats this host can actually read.

## Upload staging
The whole upload batch is validated before anything touches `DATA_DIR`. The files are then placed into `DATA_DIR` and the Retrieval index refreshes. If the refresh succeeds they stay; if it fails they are removed, and any files they overwrote are restored. An upload with the same name as an existing Document replaces it. Upload filenames are reduced to the bare name, so a name like `../x.md` cannot write outside `DATA_DIR`.
