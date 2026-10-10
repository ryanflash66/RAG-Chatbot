"""Division-scoped question answering over a precomputed index (the hosted demo's runtime).

divisions   the divisions and their documents (one row each)
index_file  chunks.json + vectors.npy, searched with numpy, filtered by division
embedder    question embeddings and the cross-encoder reranker (fastembed, ONNX)
retrieval   vector search within one division, then rerank
llm         OpenRouter chat completions, free models only
answer      the prompt, citations and the "not in these documents" reply
config      settings from environment variables
"""
