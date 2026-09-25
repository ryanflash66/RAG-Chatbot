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

# Token budget for retrieved passages in one chat prompt. The Ollama context
# window (app.OLLAMA_CONTEXT_WINDOW) is 8192 tokens; this leaves 2048 of it for
# the prompt template, the question and the answer. RETRIEVAL_TOP_K x CHUNK_SIZE
# must fit inside it, or Ollama silently truncates the prompt. The defaults
# (6 x 512 = 3072) leave ample headroom.
MAX_RETRIEVED_TOKENS = 6144


@dataclass(frozen=True)
class AppConfig:
    data_dir: Path
    chroma_persist_dir: Path
    chroma_collection: str
    embedding_model: str
    # Chunks returned per chat question, and the token size/overlap of the chunks
    # a refresh splits Documents into. Changing the chunking needs `py -m rag refresh`.
    retrieval_top_k: int
    chunk_size: int
    chunk_overlap: int
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
    top_k = int(env.get("RETRIEVAL_TOP_K", "6"))
    chunk_size = int(env.get("CHUNK_SIZE", "512"))
    chunk_overlap = int(env.get("CHUNK_OVERLAP", "64"))
    if top_k < 1:
        raise ValueError(f"RETRIEVAL_TOP_K must be at least 1, got {top_k}")
    if chunk_size < 64:
        raise ValueError(f"CHUNK_SIZE must be at least 64 tokens, got {chunk_size}")
    if not 0 <= chunk_overlap < chunk_size:
        raise ValueError(f"CHUNK_OVERLAP must be at least 0 and less than CHUNK_SIZE ({chunk_size}), got {chunk_overlap}")
    if top_k * chunk_size > MAX_RETRIEVED_TOKENS:
        raise ValueError(
            f"RETRIEVAL_TOP_K x CHUNK_SIZE ({top_k} x {chunk_size}) exceeds {MAX_RETRIEVED_TOKENS} tokens "
            "and would overflow the 8192-token chat context window"
        )
    return AppConfig(
        data_dir=_path(env.get("DATA_DIR", "data")),
        chroma_persist_dir=_path(env.get("CHROMA_PERSIST_DIR", "chroma_db")),
        chroma_collection=env.get("CHROMA_COLLECTION", "irp_docs"),
        embedding_model=env.get("EMBEDDING_MODEL", "BAAI/bge-small-en-v1.5"),
        retrieval_top_k=top_k,
        chunk_size=chunk_size,
        chunk_overlap=chunk_overlap,
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
