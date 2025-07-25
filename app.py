"""
RAG Chatbot for IT Support Documentation
Main application entry point
"""
import chainlit as cl
from config import init_env, init_settings, setup_openai_client, get_data_dir, get_storage_dir
from index_utils import load_or_create_index, DocumentLoadError, print_supported_file_types

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
    """Initialize the chat session with query engine."""
    try:
        query_engine = index.as_query_engine(streaming=True)
        cl.user_session.set("query_engine", query_engine)
        
        # Send welcome message
        await cl.Message(
            content="""🤖 **IT Support RAG Chatbot Ready!**

I can help you find information from your uploaded documentation.

📁 **Data Directory**: `./data`
📄 **Supported Files**: PDF, DOCX, TXT, MD, JSON, XML, YAML, logs, scripts, and more
🔄 **To add files**: Place them in the data folder and restart the app

Ask me anything about your IT documentation!""",
            author="Assistant"
        ).send()
        
    except Exception as e:
        await cl.Message(
            content=f"❌ Error initializing chat session: {str(e)}",
            author="System"
        ).send()
        raise


@cl.on_message
async def main(message: cl.Message):
    """Handle user messages with error handling."""
    try:
        query_engine = cl.user_session.get("query_engine")
        
        if not query_engine:
            await cl.Message(
                content="❌ Query engine not initialized. Please refresh the page.",
                author="System"
            ).send()
            return
        
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
        
    except Exception as e:
        print(f"Error in message handler: {e}")
        await cl.Message(
            content=f"❌ Sorry, I encountered an error processing your request: {str(e)}",
            author="System"
        ).send()
