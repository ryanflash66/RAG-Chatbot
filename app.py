from llama_index.core.callbacks import CallbackManager
from llama_index.core import VectorStoreIndex, SimpleDirectoryReader, StorageContext, load_index_from_storage
from llama_index.core.settings import Settings
from llama_index.llms.openai import OpenAI
from llama_index.embeddings.huggingface import HuggingFaceEmbedding
import chainlit as cl
import os
import openai
from dotenv import load_dotenv

# Load environment vars from .env
load_dotenv()

# Use OpenRouter instead of OpenAI
openrouter_api_key = os.getenv("OPENROUTER_API_KEY")
if not openrouter_api_key:
    raise ValueError("OPENROUTER_API_KEY not found in environment variables. Please check your .env file.")
os.environ["OPENROUTER_API_KEY"] = openrouter_api_key
openai.api_key = openrouter_api_key
openai.api_base = "https://openrouter.ai/api/v1"

# Configure LLM to use OpenRouter - use standard OpenAI model name
Settings.llm = OpenAI(
    temperature=0,
    model="gpt-4o",  # Use standard model name, not "openai/gpt-4o"
    api_base="https://openrouter.ai/api/v1",
    api_key=openrouter_api_key
)

# Use a local embedding model instead of OpenAI
Settings.embed_model = HuggingFaceEmbedding(
    model_name="BAAI/bge-small-en-v1.5"
)

try:
    # rebuild storage context
    storage_context = StorageContext.from_defaults(persist_dir="./storage")
    # load index
    index = load_index_from_storage(storage_context)
    print("Loaded existing index from storage.")
except:
    print("Creating new index from documents...")
    # Use SimpleDirectoryReader without custom file extractors first
    dir_reader = SimpleDirectoryReader("./data")
    
    data = dir_reader.load_data()
    print(f"Loaded {len(data)} documents")
    index = VectorStoreIndex.from_documents(data)
    index.storage_context.persist()
    print("Index created and saved to storage.")


@cl.on_chat_start
async def factory():
    # Configure callback manager
    Settings.callback_manager = CallbackManager([cl.LlamaIndexCallbackHandler()])

    query_engine = index.as_query_engine(streaming=True)
    cl.user_session.set("query_engine", query_engine)


@cl.on_message
async def main(message: cl.Message):
    query_engine = cl.user_session.get("query_engine")
    response = await cl.make_async(query_engine.query)(message.content)

    response_message = cl.Message(content="")

    for token in response.response_gen:
        await response_message.stream_token(token=token)

    if response.response_txt:
        response_message.content = response.response_txt

    await response_message.send()
