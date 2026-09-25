"""Application configuration, resolved once from the environment.

Every setting has exactly one default here. Relative paths resolve against the
repository root, so the working directory never changes which data directory or
vector store is used.
"""

import os
from dataclasses import dataclass
from pathlib import Path
from typing import Mapping, Optional

ROOT = Path(__file__).resolve().parent.parent


@dataclass(frozen=True)
class AppConfig:
    data_dir: Path
    chroma_persist_dir: Path
    chroma_collection: str
    embedding_model: str
    model_name: str
    temperature: float
    openrouter_api_key: Optional[str]
    chat_history_enabled: bool
    max_chat_history: int
    chat_storage_dir: Path


def _path(value: str) -> Path:
    path = Path(value)
    return path if path.is_absolute() else (ROOT / path).resolve()


def load_config(env: Optional[Mapping[str, str]] = None) -> AppConfig:
    env = os.environ if env is None else env
    return AppConfig(
        data_dir=_path(env.get("DATA_DIR", "data")),
        chroma_persist_dir=_path(env.get("CHROMA_PERSIST_DIR", "chroma_db")),
        chroma_collection=env.get("CHROMA_COLLECTION", "irp_docs"),
        embedding_model=env.get("EMBEDDING_MODEL", "BAAI/bge-small-en-v1.5"),
        model_name=env.get("MODEL_NAME", "gpt-4o"),
        temperature=float(env.get("TEMPERATURE", "0")),
        openrouter_api_key=env.get("OPENROUTER_API_KEY") or None,
        chat_history_enabled=env.get("ENABLE_CHAT_HISTORY", "true").lower() == "true",
        max_chat_history=int(env.get("MAX_CHAT_HISTORY", "50")),
        chat_storage_dir=_path(env.get("CHAT_STORAGE_DIR", "chat_history")),
    )
