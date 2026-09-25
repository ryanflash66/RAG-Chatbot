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
from typing import Dict, List

import chainlit as cl
from dotenv import load_dotenv

from chat_history import ChatHistoryManager
from rag.config import AppConfig, load_config
from rag.index import EmptyIndexError, Hit, RetrievalIndex, make_embed_model

RECENT_CHATS_LIMIT = 10

PROMPT_TEMPLATE = """Answer the question using only the context below.
If the context does not contain the answer, say so.

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

    index = RetrievalIndex(config, make_embed_model(config))
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


def _build_prompt(question: str, hits: List[Hit]) -> str:
    context = "\n\n---\n\n".join(f"[{hit.source}]\n{hit.text}" for hit in hits)
    return PROMPT_TEMPLATE.format(context=context, question=question)


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

        sources = sorted({hit.source for hit in hits if hit.source})
        if sources:
            await response_message.stream_token(token="\n\n**Sources:** " + ", ".join(f"`{s}`" for s in sources))

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
