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

# Which LLM answers chat questions, and its model when MODEL_NAME is unset.
# "ollama" runs on this machine; "openrouter" sends the question and retrieved
# passages to OpenRouter.
DEFAULT_MODELS = {"ollama": "qwen2.5:14b", "openrouter": "gpt-4o"}


@dataclass(frozen=True)
class AppConfig:
    data_dir: Path
    chroma_persist_dir: Path
    chroma_collection: str
    embedding_model: str
    llm_provider: str
    model_name: str
    temperature: float
    ollama_base_url: str
    openrouter_api_key: Optional[str]
    chat_history_enabled: bool
    max_chat_history: int
    chat_storage_dir: Path
    auth_username: Optional[str]
    auth_password: Optional[str]


def _path(value: str) -> Path:
    path = Path(value)
    return path if path.is_absolute() else (ROOT / path).resolve()


def load_config(env: Optional[Mapping[str, str]] = None) -> AppConfig:
    env = os.environ if env is None else env
    provider = env.get("LLM_PROVIDER", "ollama").strip().lower()
    if provider not in DEFAULT_MODELS:
        raise ValueError(f"LLM_PROVIDER must be one of {sorted(DEFAULT_MODELS)}, got {provider!r}")
    return AppConfig(
        data_dir=_path(env.get("DATA_DIR", "data")),
        chroma_persist_dir=_path(env.get("CHROMA_PERSIST_DIR", "chroma_db")),
        chroma_collection=env.get("CHROMA_COLLECTION", "irp_docs"),
        embedding_model=env.get("EMBEDDING_MODEL", "BAAI/bge-small-en-v1.5"),
        llm_provider=provider,
        model_name=env.get("MODEL_NAME") or DEFAULT_MODELS[provider],
        temperature=float(env.get("TEMPERATURE", "0")),
        ollama_base_url=env.get("OLLAMA_BASE_URL", "http://localhost:11434").rstrip("/"),
        openrouter_api_key=env.get("OPENROUTER_API_KEY") or None,
        chat_history_enabled=env.get("ENABLE_CHAT_HISTORY", "true").lower() == "true",
        max_chat_history=int(env.get("MAX_CHAT_HISTORY", "50")),
        chat_storage_dir=_path(env.get("CHAT_STORAGE_DIR", "chat_history")),
        auth_username=env.get("CHAINLIT_AUTH_USERNAME") or None,
        auth_password=env.get("CHAINLIT_AUTH_PASSWORD") or None,
    )
