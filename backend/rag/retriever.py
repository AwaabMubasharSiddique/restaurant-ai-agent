"""Query-time side of RAG: load the FAISS index and fetch relevant chunks.

The agent's menu_question and hours_location handlers call `retrieve(query)` to
get grounding text, which they pass to the LLM. This keeps the menu OUT of the
prompt/code: update the text file, re-embed, and the agent's answers change with
no code edits.
"""
from __future__ import annotations

import os
from functools import lru_cache

from langchain_community.vectorstores import FAISS

from config import settings
from rag.ingest import build_index, get_embeddings


@lru_cache(maxsize=1)
def _load_store() -> FAISS:
    """Load the index once per process. Build it on first use if missing so the
    demo works without a separate ingest step."""
    if not os.path.exists(settings.faiss_index_path):
        build_index()
    return FAISS.load_local(
        settings.faiss_index_path,
        get_embeddings(),
        allow_dangerous_deserialization=True,  # we created this file ourselves
    )


def retrieve(query: str, k: int | None = None) -> str:
    """Return the top-k most relevant chunks, joined into one context string."""
    k = k or settings.retrieval_k
    docs = _load_store().similarity_search(query, k=k)
    return "\n\n---\n\n".join(d.page_content for d in docs)
