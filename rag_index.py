import json
import os
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Tuple

import chromadb
from llama_index.core import SimpleDirectoryReader, StorageContext, VectorStoreIndex
from llama_index.vector_stores.chroma import ChromaVectorStore


@dataclass
class RAGIndexConfig:
    data_dir: str
    chroma_persist_dir: str
    chroma_collection: str
    metadata_path: str


INCIDENT_KEYWORDS = {
    "ransomware": ["ransomware", "encrypt", "crypto"],
    "phishing": ["phishing", "credential", "spearphish", "spoof"],
    "data_breach": ["breach", "exfil", "pii", "leak"],
    "malware": ["malware", "trojan", "worm", "virus", "backdoor", "c2", "command.and.control"],
    "insider_threat": ["insider", "privilege abuse", "usb", "data theft"],
    "credential_dumping": ["dcsync", "credential.dump", "ad_attack", "kerberoast", "pass.the.hash", "mimikatz", "ntds"],
    "supply_chain": ["supply.chain", "dependency", "package", "ci/cd", "zero.day"],
    "ddos": ["ddos", "network_attack", "brute.force", "botnet", "cryptojack"],
    "iot_ot": ["iot", "ot", "scada", "hvac", "ics"],
}

IR_KEYWORDS = {
    "incident",
    "response",
    "playbook",
    "mitre",
    "nist",
    "threat",
    "ransomware",
    "phishing",
    "malware",
    "forensic",
    "siem",
    "edr",
}


def _infer_doc_type(file_path: str) -> str:
    extension = Path(file_path).suffix.lower()
    mapping = {
        ".pdf": "pdf",
        ".md": "markdown",
        ".txt": "text",
        ".docx": "word",
        ".doc": "word",
        ".pptx": "powerpoint",
        ".ppt": "powerpoint",
        ".json": "json",
        ".jsonl": "jsonl",
        ".csv": "csv",
        ".html": "html",
    }
    return mapping.get(extension, "other")


def _file_metadata(file_path: str) -> Dict[str, Any]:
    path = Path(file_path)
    path_text = str(path).lower()

    is_asset_inventory = "asset_inventory" in path_text or "asset-inventory" in path_text

    if is_asset_inventory:
        return {
            "source": str(path),
            "filename": path.name,
            "doc_type": _infer_doc_type(file_path),
            "section": "N/A",
            "doc_domain": "asset_inventory",
            "incident_type": "general",
            "asset_scope": "org_inventory",
            "tags": "asset,inventory",
        }

    incident_type = "unknown"
    for label, keywords in INCIDENT_KEYWORDS.items():
        if any(keyword in path_text for keyword in keywords):
            incident_type = label
            break

    doc_domain = "ir" if any(keyword in path_text for keyword in IR_KEYWORDS) else "general"

    matched_tags = [
        label for label, keywords in INCIDENT_KEYWORDS.items() if any(keyword in path_text for keyword in keywords)
    ]
    if doc_domain == "ir" and "ir" not in matched_tags:
        matched_tags.append("ir")

    return {
        "source": str(path),
        "filename": path.name,
        "doc_type": _infer_doc_type(file_path),
        "section": "N/A",
        "doc_domain": doc_domain,
        "incident_type": incident_type,
        "asset_scope": "unknown",
        "tags": ",".join(matched_tags) if matched_tags else "none",
    }


def _write_metadata(path: str, payload: Dict[str, Any]) -> None:
    metadata_dir = os.path.dirname(path)
    if metadata_dir:
        os.makedirs(metadata_dir, exist_ok=True)

    with open(path, "w", encoding="utf-8") as handle:
        json.dump(payload, handle, indent=2)


def read_index_metadata(path: str) -> Dict[str, Any]:
    if not os.path.exists(path):
        return {}

    try:
        with open(path, "r", encoding="utf-8") as handle:
            return json.load(handle)
    except (json.JSONDecodeError, OSError):
        return {}


def _data_dir_mtime(data_dir: str) -> float:
    """Return the most recent modification time across all files in data_dir."""
    latest = 0.0
    for root, _dirs, files in os.walk(data_dir):
        for fname in files:
            mtime = os.path.getmtime(os.path.join(root, fname))
            if mtime > latest:
                latest = mtime
    return latest


def _needs_rebuild(config: RAGIndexConfig) -> bool:
    """Check if any file in data_dir is newer than the last index build."""
    metadata = read_index_metadata(config.metadata_path)
    last_refresh = metadata.get("last_refresh_at")
    if not last_refresh:
        return True

    last_refresh_ts = datetime.fromisoformat(last_refresh).timestamp()
    data_mtime = _data_dir_mtime(config.data_dir)
    return data_mtime > last_refresh_ts


def create_or_load_index(
    config: RAGIndexConfig,
    embed_model: Any,
    force_rebuild: bool = False,
) -> Tuple[VectorStoreIndex, Dict[str, Any]]:
    os.makedirs(config.chroma_persist_dir, exist_ok=True)

    if not force_rebuild and _needs_rebuild(config):
        print("Index stale: data directory has changed since last build. Auto-rebuilding.")
        force_rebuild = True

    client = chromadb.PersistentClient(path=config.chroma_persist_dir)

    if force_rebuild:
        try:
            client.delete_collection(config.chroma_collection)
        except Exception:
            pass

    collection = client.get_or_create_collection(config.chroma_collection)
    vector_store = ChromaVectorStore(chroma_collection=collection)
    storage_context = StorageContext.from_defaults(vector_store=vector_store)

    existing_vectors = collection.count()

    if force_rebuild or existing_vectors == 0:
        reader = SimpleDirectoryReader(
            input_dir=config.data_dir,
            file_metadata=_file_metadata,
            exclude=["*.json"],
        )
        documents = reader.load_data()
        if not documents:
            raise ValueError(
                f"No documents found under data directory: {config.data_dir}. "
                "Add IR documents before building the RAG index."
            )

        index = VectorStoreIndex.from_documents(
            documents,
            storage_context=storage_context,
            embed_model=embed_model,
        )
        index_source = "rebuilt" if force_rebuild else "built"
        indexed_docs = len(documents)
        vector_count = collection.count()
    else:
        index = VectorStoreIndex.from_vector_store(
            vector_store=vector_store,
            embed_model=embed_model,
        )
        index_source = "loaded"
        indexed_docs = "unknown"
        vector_count = existing_vectors

    metadata = {
        "index_backend": "chroma",
        "index_source": index_source,
        "collection": config.chroma_collection,
        "persist_dir": config.chroma_persist_dir,
        "indexed_docs": indexed_docs,
        "vector_count": vector_count,
        "last_refresh_at": datetime.now(timezone.utc).isoformat(),
    }
    _write_metadata(config.metadata_path, metadata)

    return index, metadata
