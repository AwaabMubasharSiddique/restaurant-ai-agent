from __future__ import annotations

import logging
import os
from functools import lru_cache

from langchain_community.vectorstores import FAISS

from config import settings
from rag.ingest import build_index, get_embeddings

logger = logging.getLogger("restaurant-ai.rag")


@lru_cache(maxsize=1)
def _load_store() -> FAISS:
    if not os.path.exists(settings.faiss_index_path):
        build_index()
    return FAISS.load_local(
        settings.faiss_index_path,
        get_embeddings(),
        allow_dangerous_deserialization=True,
    )


def warm_up() -> bool:
    """Build/load the index ahead of the first request. Returns True on success.
    Safe to call at startup — failures are logged, not raised."""
    try:
        _load_store()
        return True
    except Exception:
        logger.exception("RAG index warm-up failed; menu/hours answers will be degraded")
        return False


def retrieve(query: str, k: int | None = None) -> str:
    k = k or settings.retrieval_k
    try:
        docs = _load_store().similarity_search(query, k=k)
        return "\n\n---\n\n".join(d.page_content for d in docs)
    except Exception:
        # A missing index / API key / data file shouldn't crash the turn — the
        # handler's prompt still has the customer's question and can ask them to
        # rephrase or defer to staff.
        logger.exception("Retrieval failed for query; returning empty context")
        return ""
