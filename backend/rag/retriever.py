from __future__ import annotations

import os
from functools import lru_cache

from langchain_community.vectorstores import FAISS

from config import settings
from rag.ingest import build_index, get_embeddings


@lru_cache(maxsize=1)
def _load_store() -> FAISS:
    if not os.path.exists(settings.faiss_index_path):
        build_index()
    return FAISS.load_local(
        settings.faiss_index_path,
        get_embeddings(),
        allow_dangerous_deserialization=True,
    )


def retrieve(query: str, k: int | None = None) -> str:
    k = k or settings.retrieval_k
    docs = _load_store().similarity_search(query, k=k)
    return "\n\n---\n\n".join(d.page_content for d in docs)
