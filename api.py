"""FastAPI router for document ingestion and ChromaDB-backed RAG retrieval.

Endpoints
---------
POST /api/ingest  -- upload files (DOCX, PPTX, PDF, images, Markdown) into the
                     data directory and rebuild the ChromaDB index.
POST /api/query   -- retrieve relevant chunks from ChromaDB without LLM generation.
"""

import os
from pathlib import Path
from typing import List, Optional

from fastapi import APIRouter, File, HTTPException, UploadFile
from pydantic import BaseModel

from rag_index import RAGIndexConfig, create_or_load_index

# File types accepted by the ingest endpoint.
# LlamaIndex + unstructured handle all of these via llama-index-readers-file.
SUPPORTED_EXTENSIONS: frozenset = frozenset({
    ".md", ".txt", ".pdf",
    ".docx", ".doc",
    ".pptx", ".ppt",
    ".png", ".jpg", ".jpeg", ".gif", ".bmp", ".tiff",
})

# Lazy singleton for the HuggingFace embedding model.
# Replace this attribute with a test double before importing the router in tests.
_embed_model = None


def _get_embed_model():
    global _embed_model
    if _embed_model is None:
        from llama_index.embeddings.huggingface import HuggingFaceEmbedding
        _embed_model = HuggingFaceEmbedding(
            model_name=os.getenv("EMBEDDING_MODEL", "BAAI/bge-small-en-v1.5")
        )
    return _embed_model


def _build_config(data_dir: str) -> RAGIndexConfig:
    base = Path(__file__).resolve().parent
    chroma_dir = os.getenv("CHROMA_PERSIST_DIR", str(base / "chroma_db"))
    collection = os.getenv("CHROMA_COLLECTION", "irp_docs")
    return RAGIndexConfig(
        data_dir=data_dir,
        chroma_persist_dir=chroma_dir,
        chroma_collection=collection,
        metadata_path=str(Path(chroma_dir) / "index_meta.json"),
    )


# ---------------------------------------------------------------------------
# Pydantic models
# ---------------------------------------------------------------------------

class QueryRequest(BaseModel):
    query: str
    top_k: int = 4


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
async def ingest_documents(files: List[UploadFile] = File(...)):
    """Save uploaded files to the data directory and force-rebuild the ChromaDB index.

    Accepted formats: Markdown, plain text, PDF, Word (DOCX/DOC),
    PowerPoint (PPTX/PPT), and common image types (PNG, JPG, GIF, BMP, TIFF).
    Parsing is handled by llama-index-readers-file via unstructured.
    """
    base = Path(__file__).resolve().parent
    data_dir = os.getenv("DATA_DIR", str(base / "data"))
    os.makedirs(data_dir, exist_ok=True)

    saved: List[Path] = []
    try:
        for upload in files:
            filename = upload.filename or "upload"
            suffix = Path(filename).suffix.lower()
            if suffix not in SUPPORTED_EXTENSIONS:
                raise HTTPException(
                    status_code=400,
                    detail=(
                        f"Unsupported file type '{suffix}'. "
                        f"Accepted extensions: {sorted(SUPPORTED_EXTENSIONS)}"
                    ),
                )
            dest = Path(data_dir) / filename
            dest.write_bytes(await upload.read())
            saved.append(dest)

        config = _build_config(data_dir)
        _, meta = create_or_load_index(
            config=config,
            embed_model=_get_embed_model(),
            force_rebuild=True,
        )
        return IngestResponse(
            success=True,
            indexed_docs=int(meta.get("indexed_docs") or 0),
            vector_count=int(meta.get("vector_count") or 0),
            collection=str(meta.get("collection", "")),
            message=(
                f"Saved {len(saved)} file(s) and rebuilt ChromaDB "
                f"collection '{meta.get('collection')}'."
            ),
        )
    except HTTPException:
        raise
    except Exception as exc:
        for p in saved:
            try:
                p.unlink()
            except OSError:
                pass
        raise HTTPException(status_code=500, detail=str(exc))


@router.post("/query", response_model=QueryResponse)
async def query_rag(body: QueryRequest):
    """Retrieve the top-k most relevant chunks from ChromaDB for a given query.

    Returns ranked source nodes with text, metadata, and similarity scores.
    No LLM generation is performed -- this endpoint exposes the retrieval layer
    directly so callers can inspect context without triggering the full pipeline.
    """
    base = Path(__file__).resolve().parent
    data_dir = os.getenv("DATA_DIR", str(base / "data"))

    config = _build_config(data_dir)
    try:
        index, _ = create_or_load_index(
            config=config,
            embed_model=_get_embed_model(),
            force_rebuild=False,
        )
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Index unavailable: {exc}")

    retriever = index.as_retriever(similarity_top_k=body.top_k)
    nodes = retriever.retrieve(body.query)

    results: List[SourceNode] = []
    for nws in nodes:
        node = getattr(nws, "node", nws)
        text = node.get_content().strip() if hasattr(node, "get_content") else str(node)
        md = getattr(node, "metadata", {}) or {}
        results.append(SourceNode(
            text=text,
            source=md.get("source") or md.get("filename"),
            score=getattr(nws, "score", None),
            incident_type=md.get("incident_type"),
            doc_domain=md.get("doc_domain"),
        ))

    return QueryResponse(query=body.query, results=results)
