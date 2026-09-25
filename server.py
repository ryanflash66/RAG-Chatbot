"""ASGI entrypoint for the retrieval API.

    uvicorn server:app --port 8001
"""

from dataclasses import asdict

from dotenv import load_dotenv
from fastapi import Depends, FastAPI

import api
from rag.index import RetrievalIndex

load_dotenv()

app = FastAPI(title="RAG-Chatbot API")
app.include_router(api.router)


@app.get("/health")
def health(index: RetrievalIndex = Depends(api.get_index)):
    return {"status": "ok", **asdict(index.stats())}
