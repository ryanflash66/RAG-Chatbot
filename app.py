"""
RAG Chatbot for IT Support Documentation
Chainlit entrypoint: an adapter over the shared Retrieval index plus an LLM.

Nothing heavy runs at import time. The index, embedding model and LLM are
created on the first chat session.
"""
import functools
import hmac
import re
import uuid
from datetime import datetime
from typing import Dict, List, Optional, Tuple

import chainlit as cl
from dotenv import load_dotenv

from chat_history import ChatHistoryManager
from rag.config import AppConfig, load_config
from rag.index import EmptyIndexError, Hit, RetrievalIndex, make_embed_model, make_reranker

RECENT_CHATS_LIMIT = 10

PROMPT_TEMPLATE = """Answer the question using only the numbered context blocks below.
Cite the blocks that support your answer inline by number, like [1] or [2].
If the context does not contain the answer, say so and cite nothing.

Context:
{context}

Question: {question}
Answer:"""


@functools.lru_cache(maxsize=1)
def _config() -> AppConfig:
    load_dotenv()
    return load_config()


# Retrieved chunks plus the question run to roughly 4-5k tokens; Ollama's own
# default context is smaller and would silently cut the prompt.
OLLAMA_CONTEXT_WINDOW = 8192
# Generous, so the first request (which loads the model into VRAM) doesn't time out.
OLLAMA_REQUEST_TIMEOUT = 300.0


def _check_ollama(config: AppConfig) -> None:
    """Fail early, with a fix-it message, if Ollama is down or the model isn't pulled."""
    import httpx

    try:
        response = httpx.get(f"{config.ollama_base_url}/api/tags", timeout=5)
        response.raise_for_status()
    except httpx.HTTPError as exc:
        raise RuntimeError(
            f"Ollama isn't running at {config.ollama_base_url} ({exc.__class__.__name__}). "
            "Start the Ollama app or service, or set OLLAMA_BASE_URL."
        ) from exc

    names = {m.get("name", "") for m in response.json().get("models", [])}
    wanted = config.model_name
    if wanted not in names and f"{wanted}:latest" not in names:
        raise RuntimeError(f"Model {wanted} isn't pulled in Ollama. Run: ollama pull {wanted}")


def _make_llm(config: AppConfig):
    if config.llm_provider == "ollama":
        from llama_index.llms.ollama import Ollama

        return Ollama(
            model=config.model_name,
            base_url=config.ollama_base_url,
            temperature=config.temperature,
            context_window=OLLAMA_CONTEXT_WINDOW,
            request_timeout=OLLAMA_REQUEST_TIMEOUT,
        )

    if not config.openrouter_api_key:
        raise ValueError("OPENROUTER_API_KEY is required when LLM_PROVIDER=openrouter. Please check your .env file.")
    from llama_index.llms.openai import OpenAI

    return OpenAI(
        model=config.model_name,
        temperature=config.temperature,
        api_base="https://openrouter.ai/api/v1",
        api_key=config.openrouter_api_key,
    )


def _model_label(config: AppConfig) -> str:
    where = "local, via Ollama" if config.llm_provider == "ollama" else "remote, via OpenRouter"
    return f"{config.model_name} ({where})"


@functools.lru_cache(maxsize=1)
def _runtime():
    """Build the Retrieval index and LLM once per process."""
    config = _config()
    if config.llm_provider == "ollama":
        _check_ollama(config)
    llm = _make_llm(config)

    index = RetrievalIndex(config, make_embed_model(config), make_reranker(config))
    stats = index.ensure_built()
    print(f"Retrieval index '{stats.collection}': {stats.documents} documents, {stats.vectors} vectors")
    print(f"Answering with {_model_label(config)}")
    return index, llm


@cl.password_auth_callback
async def auth_callback(username: str, password: str):
    """Password login against CHAINLIT_AUTH_USERNAME / CHAINLIT_AUTH_PASSWORD.

    With either variable unset, every login is refused.
    """
    config = _config()
    if not (config.auth_username and config.auth_password):
        print("Login refused: CHAINLIT_AUTH_USERNAME / CHAINLIT_AUTH_PASSWORD are not set.")
        return None
    user_ok = hmac.compare_digest(username.encode(), config.auth_username.encode())
    password_ok = hmac.compare_digest(password.encode(), config.auth_password.encode())
    if user_ok and password_ok:
        return cl.User(identifier=username, metadata={"role": "admin", "provider": "credentials"})
    return None


def _history() -> ChatHistoryManager:
    config = _config()
    user = cl.user_session.get("user")
    user_id = re.sub(r"[^A-Za-z0-9_-]", "_", user.identifier)[:64] if user else None
    return ChatHistoryManager(config.chat_storage_dir, config.max_chat_history, user_id)


UNKNOWN_SOURCE = "unknown source"
EN_DASH = "–"


def _page_label(hit: Hit) -> Optional[str]:
    label = str(hit.metadata.get("page_label") or "").strip()
    return label or None


def _locator(hit: Hit) -> str:
    """'file, p. N' for one Hit; just the file when it has no page label."""
    source = hit.source or UNKNOWN_SOURCE
    page = _page_label(hit)
    return f"{source}, p. {page}" if page else source


def _build_prompt(question: str, hits: List[Hit]) -> str:
    context = "\n\n---\n\n".join(
        f"[{n}] ({_locator(hit)})\n{hit.text}" for n, hit in enumerate(hits, start=1)
    )
    return PROMPT_TEMPLATE.format(context=context, question=question)


# One bracketed citation: "[1]", "[1, 2]", "[1; 2]", "[1-3]", "[1–3]". Some models
# (gpt-oss) use lenticular or full-width brackets instead: "【2】", "［2］".
# Adjacent markers such as "[1][2]" match one at a time.
_CITATION = re.compile(r"[\[【［]\s*(\d+(?:\s*[,;\-–]\s*\d+)*)\s*[\]】］]")
# Non-citations the model sometimes emits when nothing applies, e.g. "[None]".
_EMPTY_CITATION = re.compile(r"\s*[\[【［]\s*(?:none|n/?a)\s*[\]】］]", re.IGNORECASE)
_RANGE = re.compile(r"(\d+)\s*[\-–]\s*(\d+)")


def _marker_numbers(marker: "re.Match[str]", n_hits: int) -> List[int]:
    """Valid block numbers in one citation marker; out-of-range and malformed parts are dropped."""
    numbers: List[int] = []
    for part in re.split(r"\s*[,;]\s*", marker.group(1)):
        span = _RANGE.fullmatch(part)
        if span:
            low, high = int(span.group(1)), int(span.group(2))
            candidates = range(low, high + 1) if low <= high <= n_hits else []
        else:
            candidates = [int(part)] if part.isdigit() else []  # e.g. "1-2-3"
        numbers += [n for n in candidates if 1 <= n <= n_hits and n not in numbers]
    return numbers


def _cited_indices(answer: str, n_hits: int) -> List[int]:
    """1-based context block numbers cited in the answer, in order of first mention.

    Numbers outside 1..n_hits (made-up blocks, bracketed years) are dropped.
    """
    cited: List[int] = []
    for marker in _CITATION.finditer(answer):
        cited += [n for n in _marker_numbers(marker, n_hits) if n not in cited]
    return cited


def _split_citations(answer: str, n_hits: int) -> str:
    """Rewrite markers as one "[n]" each: "[1, 3]" -> "[1][3]", "【2】" -> "[2]".

    Chainlit links only text that exactly matches an element name, so each
    passage needs its own "[n]". Markers with no valid number are left alone;
    empty ones such as "[None]" are removed.
    """
    def expand(marker: "re.Match[str]") -> str:
        numbers = _marker_numbers(marker, n_hits)
        return "".join(f"[{n}]" for n in numbers) if numbers else marker.group(0)

    return _CITATION.sub(expand, _EMPTY_CITATION.sub("", answer))


def _page_ranges(labels: List[str]) -> str:
    """'p. 64', 'pp. 58–59' or 'pp. 12, 58–60'; non-numeric labels are listed as-is."""
    numeric = sorted({int(label) for label in labels if label.isdigit()})
    runs: List[List[int]] = []
    for page in numeric:
        if runs and page == runs[-1][-1] + 1:
            runs[-1].append(page)
        else:
            runs.append([page])
    parts = [label for label in dict.fromkeys(labels) if not label.isdigit()]
    parts += [str(run[0]) if len(run) == 1 else f"{run[0]}{EN_DASH}{run[-1]}" for run in runs]
    prefix = "p." if len(parts) == 1 and EN_DASH not in parts[0] else "pp."
    return f"{prefix} {', '.join(parts)}"


def _format_sources(hits: List[Hit], cited: List[int]) -> Optional[str]:
    """A Sources line naming only the cited passages, pages grouped per file.

    None when nothing was cited, so an unanswered question shows no sources.
    """
    pages_by_source: Dict[str, List[str]] = {}
    for n in cited:
        hit = hits[n - 1]
        pages = pages_by_source.setdefault(hit.source or UNKNOWN_SOURCE, [])
        page = _page_label(hit)
        if page:
            pages.append(page)
    if not pages_by_source:
        return None
    entries = [
        f"`{source}`, {_page_ranges(pages)}" if pages else f"`{source}`"
        for source, pages in pages_by_source.items()
    ]
    return "**Sources:** " + "; ".join(entries)


def _cited_passages(hits: List[Hit], cited: List[int]) -> List[Tuple[str, str]]:
    """(name, content) per cited passage, named "[n]" like its marker in the answer.

    Sent as side-panel elements, so Chainlit links each "[n]" in the answer to its passage.
    """
    return [(f"[{n}]", f"**{_locator(hits[n - 1])}**\n\n{hits[n - 1].text}") for n in cited]


def _history_actions(sessions: List[Dict], limit: int = RECENT_CHATS_LIMIT) -> List[cl.Action]:
    """Load/delete buttons for the most recent sessions, plus a clear-all button."""
    actions: List[cl.Action] = []
    for session in sessions[:limit]:
        payload = {"session_id": session["session_id"]}
        actions.append(cl.Action(name="load_chat", payload=payload, label=session["title"], icon="history"))
        actions.append(cl.Action(name="delete_chat", payload=payload, label="", tooltip="Delete", icon="trash-2"))
    if sessions:
        actions.append(cl.Action(name="clear_all_history", payload={}, label="Clear all", icon="eraser"))
    return actions


async def _send_recent_chats() -> None:
    sessions = _history().get_chat_history()
    if not sessions:
        return
    await cl.Message(
        content=f"🕘 **Recent chats** ({len(sessions)})",
        author="System",
        actions=_history_actions(sessions),
    ).send()


def _record(message_type: str, content: str, author: str) -> None:
    messages = cl.user_session.get("messages", [])
    messages.append({
        "type": message_type,
        "content": content,
        "timestamp": datetime.now().isoformat(),
        "author": author,
    })
    cl.user_session.set("messages", messages)


def _save_session() -> None:
    session_id = cl.user_session.get("session_id")
    messages = cl.user_session.get("messages", [])
    if session_id and any(m.get("type") == "user_message" for m in messages):
        _history().save_chat_session(session_id, messages)


@cl.on_chat_start
async def factory():
    """Initialize the chat session and chat history."""
    try:
        config = _config()
        await cl.make_async(_runtime)()

        cl.user_session.set("session_id", str(uuid.uuid4()))
        cl.user_session.set("messages", [])

        welcome_msg = f"""🤖 **IT Support RAG Chatbot Ready!**

I can help you find information from your uploaded documentation.

📁 **Data Directory**: `{config.data_dir}`
🧠 **Model**: {_model_label(config)}
🔄 **To add files**: upload them via `POST /api/ingest`, or place them in the data folder and run `py -m rag refresh`

Ask me anything about your IT documentation!"""

        await cl.Message(content=welcome_msg, author="Assistant").send()

        if config.chat_history_enabled:
            _record("assistant_message", welcome_msg, "Assistant")
            await _send_recent_chats()

    except Exception as e:
        await cl.Message(
            content=f"❌ Error initializing chat session: {str(e)}",
            author="System"
        ).send()
        raise


@cl.on_message
async def main(message: cl.Message):
    """Retrieve Hits, stream the LLM's answer, and save the session."""
    try:
        config = _config()
        index, llm = _runtime()

        if config.chat_history_enabled:
            _record("user_message", message.content, "User")

        try:
            hits = await cl.make_async(index.retrieve)(message.content, k=config.retrieval_top_k)
        except EmptyIndexError:
            await cl.Message(
                content="📭 The index is empty. Add documents via `POST /api/ingest` or run `py -m rag refresh`.",
                author="System"
            ).send()
            return

        response_message = cl.Message(content="")
        stream = await llm.astream_complete(_build_prompt(message.content, hits))
        async for chunk in stream:
            await response_message.stream_token(token=chunk.delta or "")

        response_message.content = _split_citations(response_message.content, len(hits))
        cited = _cited_indices(response_message.content, len(hits))
        sources = _format_sources(hits, cited)
        if sources:
            await response_message.stream_token(token="\n\n" + sources)
        response_message.elements = [
            cl.Text(name=name, content=content, display="side")
            for name, content in _cited_passages(hits, cited)
        ]

        await response_message.send()

        if config.chat_history_enabled:
            _record("assistant_message", response_message.content, "Assistant")
            _save_session()

    except Exception as e:
        print(f"Error in message handler: {e}")
        await cl.Message(
            content=f"❌ Sorry, I encountered an error processing your request: {str(e)}",
            author="System"
        ).send()


@cl.on_chat_end
async def on_chat_end():
    """Save the chat session when the conversation ends."""
    if not _config().chat_history_enabled:
        return
    try:
        _save_session()
    except Exception as e:
        print(f"Error saving chat session: {e}")


@cl.action_callback("load_chat")
async def load_chat(action: cl.Action):
    """Replay a previous session and continue it."""
    session_id = action.payload.get("session_id", "")
    session_data = _history().load_chat_session(session_id)

    if not session_data:
        await cl.Message(content="❌ Could not load chat session.", author="System").send()
        return

    # Later messages are appended to the loaded session rather than a new one.
    cl.user_session.set("session_id", session_id)
    cl.user_session.set("messages", list(session_data.get("messages", [])))

    await cl.Message(
        content=f"📜 **Loaded Chat:** {session_data['title']}\n\n---\n",
        author="System"
    ).send()
    for msg in session_data.get("messages", []):
        if msg.get("type") in ("user_message", "assistant_message"):
            await cl.Message(content=msg["content"], author=msg.get("author", "Unknown")).send()
    await cl.Message(content="\n---\n💬 **Continue the conversation below:**", author="System").send()


@cl.action_callback("delete_chat")
async def delete_chat(action: cl.Action):
    """Delete a chat session and show the updated list."""
    if _history().delete_chat_session(action.payload.get("session_id", "")):
        await cl.Message(content="🗑️ Chat session deleted.", author="System").send()
        await _send_recent_chats()
    else:
        await cl.Message(content="❌ Could not delete chat session.", author="System").send()


@cl.action_callback("clear_all_history")
async def clear_all_history(action: cl.Action):
    """Delete every chat session for the current user."""
    history = _history()
    sessions = history.get_chat_history()
    for session in sessions:
        history.delete_chat_session(session["session_id"])

    await cl.Message(content=f"🧹 Cleared {len(sessions)} chat sessions from history.", author="System").send()
