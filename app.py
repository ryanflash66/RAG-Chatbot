"""
RAG Chatbot for IT Support Documentation
Chainlit entrypoint: an adapter over the shared Retrieval index plus an LLM.

Nothing heavy runs at import time. The index, embedding model and LLM are
created on the first chat session.
"""
import functools
import re
import uuid
from datetime import datetime

import chainlit as cl
from dotenv import load_dotenv

from chat_history import ChatHistoryManager
from rag.config import load_config
from rag.index import EmptyIndexError, Hit, RetrievalIndex, make_embed_model

TOP_K = 4

PROMPT_TEMPLATE = """Answer the question using only the context below.
If the context does not contain the answer, say so.

Context:
{context}

Question: {question}
Answer:"""


# Simple authentication callback for chat history
@cl.password_auth_callback
def auth_callback(username: str, password: str):
    """
    Simple password authentication for chat history.
    In production, use proper authentication methods.
    """
    # Simple demo credentials - in production, use proper auth
    if username == "admin" and password == "password":
        return cl.User(
            identifier="admin", 
            metadata={"role": "admin", "provider": "credentials"}
        )
    else:
        return None


@functools.lru_cache(maxsize=1)
def _runtime():
    """Build the config, Retrieval index and LLM once per process."""
    load_dotenv()
    config = load_config()
    if not config.openrouter_api_key:
        raise ValueError("OPENROUTER_API_KEY not found in environment variables. Please check your .env file.")

    index = RetrievalIndex(config, make_embed_model(config))
    stats = index.ensure_built()
    print(f"Retrieval index '{stats.collection}': {stats.documents} documents, {stats.vectors} vectors")

    from llama_index.llms.openai import OpenAI

    llm = OpenAI(
        model=config.model_name,
        temperature=config.temperature,
        api_base="https://openrouter.ai/api/v1",
        api_key=config.openrouter_api_key,
    )
    return config, index, llm


def _history() -> ChatHistoryManager:
    config, _, _ = _runtime()
    user = cl.user_session.get("user")
    user_id = re.sub(r"[^A-Za-z0-9_-]", "_", user.identifier)[:64] if user else None
    return ChatHistoryManager(config.chat_storage_dir, config.max_chat_history, user_id)


def _build_prompt(question: str, hits: list[Hit]) -> str:
    context = "\n\n---\n\n".join(f"[{hit.source}]\n{hit.text}" for hit in hits)
    return PROMPT_TEMPLATE.format(context=context, question=question)


@cl.on_chat_start
async def factory():
    """Initialize the chat session and chat history."""
    try:
        config, _, _ = await cl.make_async(_runtime)()

        session_id = str(uuid.uuid4())
        cl.user_session.set("session_id", session_id)
        cl.user_session.set("messages", [])

        welcome_msg = f"""🤖 **IT Support RAG Chatbot Ready!**

I can help you find information from your uploaded documentation.

📁 **Data Directory**: `{config.data_dir}`
🔄 **To add files**: upload them via `POST /api/ingest`, or place them in the data folder and run `py -m rag refresh`

💬 **Chat History**: Your conversations are saved when the chat ends

Ask me anything about your IT documentation!"""

        await cl.Message(
            content=welcome_msg,
            author="Assistant"
        ).send()

        if config.chat_history_enabled:
            messages = cl.user_session.get("messages", [])
            messages.append({
                "type": "assistant_message",
                "content": welcome_msg,
                "timestamp": datetime.now().isoformat(),
                "author": "Assistant"
            })
            cl.user_session.set("messages", messages)

    except Exception as e:
        await cl.Message(
            content=f"❌ Error initializing chat session: {str(e)}",
            author="System"
        ).send()
        raise


@cl.on_message
async def main(message: cl.Message):
    """Handle user messages with error handling and history tracking."""
    try:
        config, index, llm = _runtime()

        # Add user message to history
        if config.chat_history_enabled:
            messages = cl.user_session.get("messages", [])
            messages.append({
                "type": "user_message",
                "content": message.content,
                "timestamp": datetime.now().isoformat(),
                "author": "User"
            })
            cl.user_session.set("messages", messages)

        try:
            hits = await cl.make_async(index.retrieve)(message.content, k=TOP_K)
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

        # Add assistant response to history
        if config.chat_history_enabled:
            messages = cl.user_session.get("messages", [])
            messages.append({
                "type": "assistant_message", 
                "content": response_message.content,
                "timestamp": datetime.now().isoformat(),
                "author": "Assistant"
            })
            cl.user_session.set("messages", messages)
        
    except Exception as e:
        print(f"Error in message handler: {e}")
        await cl.Message(
            content=f"❌ Sorry, I encountered an error processing your request: {str(e)}",
            author="System"
        ).send()


@cl.on_chat_end
async def on_chat_end():
    """Save chat session when conversation ends."""
    config, _, _ = _runtime()
    if not config.chat_history_enabled:
        return
    
    try:
        session_id = cl.user_session.get("session_id")
        messages = cl.user_session.get("messages", [])
        
        if session_id and messages:
            # Only save if there are actual user messages
            user_messages = [m for m in messages if m.get("type") == "user_message"]
            if user_messages:
                _history().save_chat_session(session_id, messages)
                print(f"💾 Saved chat session: {session_id}")
    
    except Exception as e:
        print(f"Error saving chat session: {e}")


# Chat history sidebar actions
@cl.action_callback("load_chat")
async def load_chat(action: cl.Action):
    """Load a previous chat session."""
    session_id = action.value
    session_data = _history().load_chat_session(session_id)
    
    if not session_data:
        await cl.Message(
            content="❌ Could not load chat session.",
            author="System"
        ).send()
        return
    
    # Clear current chat and load historical messages
    await cl.Message(
        content=f"📜 **Loaded Chat:** {session_data['title']}\n\n---\n",
        author="System"
    ).send()
    
    # Display previous messages
    for msg in session_data.get("messages", []):
        if msg.get("type") in ["user_message", "assistant_message"]:
            await cl.Message(
                content=msg["content"],
                author=msg.get("author", "Unknown")
            ).send()
    
    await cl.Message(
        content="\n---\n💬 **Continue the conversation below:**",
        author="System"
    ).send()


@cl.action_callback("delete_chat")
async def delete_chat(action: cl.Action):
    """Delete a chat session."""
    session_id = action.value
    if _history().delete_chat_session(session_id):
        await cl.Message(
            content="🗑️ Chat session deleted successfully.",
            author="System"
        ).send()
    else:
        await cl.Message(
            content="❌ Could not delete chat session.",
            author="System"
        ).send()


@cl.action_callback("clear_all_history")
async def clear_all_history(action: cl.Action):
    """Clear all chat history."""
    history = _history()
    sessions = history.get_chat_history()
    for session in sessions:
        history.delete_chat_session(session["session_id"])
    
    await cl.Message(
        content=f"🧹 Cleared {len(sessions)} chat sessions from history.",
        author="System"
    ).send()
