"""
RAG Chatbot for IT Support Documentation
Main application entry point with chat history support
"""
import chainlit as cl
import uuid
from datetime import datetime
from config import init_env, init_settings, setup_openai_client, get_data_dir, get_storage_dir, get_chat_history_enabled
from index_utils import load_or_create_index, DocumentLoadError, print_supported_file_types
from chat_history import chat_history_manager

# Initialize environment and configuration
try:
    print_supported_file_types()  # Show supported file types on startup
    
    OPENROUTER_API_KEY = init_env()
    setup_openai_client(OPENROUTER_API_KEY)
    init_settings(OPENROUTER_API_KEY)
    
    # Load or create the vector index
    storage_dir = get_storage_dir()
    data_dir = get_data_dir()
    index = load_or_create_index(storage_dir, data_dir)
    
except (ValueError, DocumentLoadError) as e:
    print(f"❌ Initialization error: {e}")
    raise
except Exception as e:
    print(f"❌ Unexpected error during initialization: {e}")
    raise


@cl.on_chat_start
async def factory():
    """Initialize the chat session with query engine and chat history."""
    try:
        query_engine = index.as_query_engine(streaming=True)
        cl.user_session.set("query_engine", query_engine)
        
        # Initialize chat session
        session_id = str(uuid.uuid4())
        cl.user_session.set("session_id", session_id)
        cl.user_session.set("messages", [])
        
        # Send welcome message with chat history info
        welcome_msg = """🤖 **IT Support RAG Chatbot Ready!**

I can help you find information from your uploaded documentation.

📁 **Data Directory**: `./data`
📄 **Supported Files**: PDF, DOCX, TXT, MD, JSON, XML, YAML, logs, scripts, and more
🔄 **To add files**: Place them in the data folder and restart the app

💬 **Chat History**: Your conversations are automatically saved in the sidebar

Ask me anything about your IT documentation!"""
        
        await cl.Message(
            content=welcome_msg,
            author="Assistant"
        ).send()
        
        # Add welcome message to session history
        if get_chat_history_enabled():
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
        query_engine = cl.user_session.get("query_engine")
        
        if not query_engine:
            await cl.Message(
                content="❌ Query engine not initialized. Please refresh the page.",
                author="System"
            ).send()
            return
        
        # Add user message to history
        if get_chat_history_enabled():
            messages = cl.user_session.get("messages", [])
            messages.append({
                "type": "user_message",
                "content": message.content,
                "timestamp": datetime.now().isoformat(),
                "author": "User"
            })
            cl.user_session.set("messages", messages)
        
        # Execute the query with error handling
        response = await cl.make_async(query_engine.query)(message.content)
        
        response_message = cl.Message(content="")
        
        # Stream the response with error handling
        try:
            for token in response.response_gen:
                await response_message.stream_token(token=token)
        except Exception as stream_error:
            print(f"Streaming error: {stream_error}")
            # Fall back to non-streaming response
            if response.response_txt:
                response_message.content = response.response_txt
                await response_message.send()
                return
        
        # Ensure we have content to send
        if response.response_txt:
            response_message.content = response.response_txt
        
        await response_message.send()
        
        # Add assistant response to history
        if get_chat_history_enabled():
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
    if not get_chat_history_enabled():
        return
    
    try:
        session_id = cl.user_session.get("session_id")
        messages = cl.user_session.get("messages", [])
        
        if session_id and messages:
            # Only save if there are actual user messages
            user_messages = [m for m in messages if m.get("type") == "user_message"]
            if user_messages:
                chat_history_manager.save_chat_session(session_id, messages)
                print(f"💾 Saved chat session: {session_id}")
    
    except Exception as e:
        print(f"Error saving chat session: {e}")


# Chat history sidebar actions
@cl.action_callback("load_chat")
async def load_chat(action: cl.Action):
    """Load a previous chat session."""
    session_id = action.value
    session_data = chat_history_manager.load_chat_session(session_id)
    
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
    if chat_history_manager.delete_chat_session(session_id):
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
    sessions = chat_history_manager.get_chat_history()
    for session in sessions:
        chat_history_manager.delete_chat_session(session["session_id"])
    
    await cl.Message(
        content=f"🧹 Cleared {len(sessions)} chat sessions from history.",
        author="System"
    ).send()
