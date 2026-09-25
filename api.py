"""FastAPI router for document ingestion and ChromaDB-backed retrieval.

Endpoints
---------
POST /api/ingest  -- upload files into the data directory and refresh the index.
POST /api/query   -- retrieve relevant chunks from the index without LLM generation.

Dependencies (get_config, get_index) can be swapped with
app.dependency_overrides, which is how the tests isolate each run.
"""

import threading
from typing import Dict, List, Optional

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile
from pydantic import BaseModel

from rag import loader
from rag.config import AppConfig, load_config
from rag.index import EmptyIndexError, NoDocumentsError, RetrievalIndex, make_embed_model
from rag.staging import UploadRejected, stage

_indexes: Dict[AppConfig, RetrievalIndex] = {}
_indexes_lock = threading.Lock()
_ingest_lock = threading.Lock()


def get_config() -> AppConfig:
    return load_config()


def get_index(config: AppConfig = Depends(get_config)) -> RetrievalIndex:
    with _indexes_lock:
        index = _indexes.get(config)
        if index is None:
            index = RetrievalIndex(config, make_embed_model(config))
            index.ensure_built()
            _indexes[config] = index
        return index


# ---------------------------------------------------------------------------
# Pydantic models
# ---------------------------------------------------------------------------

class QueryRequest(BaseModel):
    query: str
    top_k: int = 4
    where: Optional[Dict[str, str]] = None


class SourceNode(BaseModel):
    text: str
    source: Optional[str] = None
    score: Optional[float] = None
    incident_type: Optional[str] = None
    doc_domain: Optional[str] = None


class QueryResponse(BaseModel):
    query: str
    results: List[SourceNode]


class IngestResponse(BaseModel):
    success: bool
    indexed_docs: int
    vector_count: int
    collection: str
    message: str


# ---------------------------------------------------------------------------
# Router
# ---------------------------------------------------------------------------

router = APIRouter(prefix="/api")


@router.post("/ingest", response_model=IngestResponse)
def ingest_documents(
    files: List[UploadFile] = File(...),
    index: RetrievalIndex = Depends(get_index),
):
    """Save uploaded files to the data directory and refresh the index.

    The whole batch is validated first. If the refresh fails, the uploads are
    removed and any files they replaced are restored.
    """
    try:
        staged = stage(
            index.config.data_dir,
            ((upload.filename, upload.file.read()) for upload in files),
            loader.supported_extensions(),
        )
    except UploadRejected as exc:
        raise HTTPException(status_code=400, detail=str(exc))

    with _ingest_lock:
        try:
            with staged:
                stats = index.refresh()
        except Exception as exc:
            raise HTTPException(status_code=500, detail=str(exc))

    return IngestResponse(
        success=True,
        indexed_docs=stats.documents,
        vector_count=stats.vectors,
        collection=stats.collection,
        message=f"Saved {len(staged.filenames)} file(s) and rebuilt collection '{stats.collection}'.",
    )


@router.post("/query", response_model=QueryResponse)
def query_rag(body: QueryRequest, index: RetrievalIndex = Depends(get_index)):
    """Retrieve the top-k most relevant chunks for a query.

    Read-only: this never rebuilds the index. Optional `where` filters on
    Document classification fields, e.g. {"incident_type": "ransomware"}.
    """
    try:
        hits = index.retrieve(body.query, k=body.top_k, where=body.where)
    except (EmptyIndexError, NoDocumentsError) as exc:
        raise HTTPException(status_code=503, detail=f"Index unavailable: {exc}")

    return QueryResponse(
        query=body.query,
        results=[
            SourceNode(
                text=hit.text,
                source=hit.source,
                score=hit.score,
                incident_type=hit.metadata.get("incident_type"),
                doc_domain=hit.metadata.get("doc_domain"),
            )
            for hit in hits
        ],
    )
