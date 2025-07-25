"""
Configuration module for RAG Chatbot
Handles environment setup and LLM/embedding model configuration
"""
import os
from dotenv import load_dotenv
from llama_index.core.settings import Settings
from llama_index.llms.openai import OpenAI
from llama_index.embeddings.huggingface import HuggingFaceEmbedding
from llama_index.core.callbacks import CallbackManager
import chainlit as cl


def init_env() -> str:
    """
    Initialize environment variables and return the OpenRouter API key.
    
    Returns:
        str: The OpenRouter API key
        
    Raises:
        ValueError: If OPENROUTER_API_KEY is not found in environment variables
    """
    load_dotenv()
    api_key = os.getenv("OPENROUTER_API_KEY")
    if not api_key:
        raise ValueError("OPENROUTER_API_KEY not found in environment variables. Please check your .env file.")
    return api_key


def get_data_dir() -> str:
    """Get the data directory path from environment or use default."""
    return os.getenv("DATA_DIR", "./data")


def get_storage_dir() -> str:
    """Get the storage directory path from environment or use default."""
    return os.getenv("STORAGE_DIR", "./storage")


def get_model_name() -> str:
    """Get the model name from environment or use default."""
    return os.getenv("MODEL_NAME", "gpt-4o")


def get_temperature() -> float:
    """Get the temperature setting from environment or use default."""
    return float(os.getenv("TEMPERATURE", "0"))


def get_embedding_model() -> str:
    """Get the embedding model name from environment or use default."""
    return os.getenv("EMBEDDING_MODEL", "BAAI/bge-small-en-v1.5")


def get_chat_history_enabled() -> bool:
    """Get whether chat history is enabled from environment or use default."""
    return os.getenv("ENABLE_CHAT_HISTORY", "true").lower() == "true"


def get_max_chat_history() -> int:
    """Get the maximum number of chat sessions to keep in history."""
    return int(os.getenv("MAX_CHAT_HISTORY", "50"))


def get_chat_storage_dir() -> str:
    """Get the chat storage directory path from environment or use default."""
    return os.getenv("CHAT_STORAGE_DIR", "./chat_history")


def init_settings(api_key: str) -> None:
    """
    Initialize LlamaIndex settings with LLM and embedding models.
    
    Args:
        api_key (str): The OpenRouter API key
    """
    Settings.llm = OpenAI(
        temperature=get_temperature(),
        model=get_model_name(),
        api_base="https://openrouter.ai/api/v1",
        api_key=api_key,
    )
    
    Settings.embed_model = HuggingFaceEmbedding(
        model_name=get_embedding_model()
    )
    
    Settings.callback_manager = CallbackManager([cl.LlamaIndexCallbackHandler()])


def setup_openai_client(api_key: str) -> None:
    """
    Configure the OpenAI client to use OpenRouter.
    
    Args:
        api_key (str): The OpenRouter API key
    """
    import openai
    openai.api_key = api_key
    openai.api_base = "https://openrouter.ai/api/v1"
