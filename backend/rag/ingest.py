from __future__ import annotations

import os

from langchain_community.document_loaders import PyPDFLoader, TextLoader
from langchain_community.vectorstores import FAISS
from langchain_openai import OpenAIEmbeddings
from langchain_text_splitters import RecursiveCharacterTextSplitter

from config import settings


def get_embeddings() -> OpenAIEmbeddings:
    return OpenAIEmbeddings(
        model=settings.openai_embedding_model,
        api_key=settings.openai_api_key,
    )


def _load_documents(path: str):
    if not os.path.exists(path):
        raise FileNotFoundError(
            f"Knowledge file not found: {path}. Set DATA_PATH or add the file."
        )
    if path.lower().endswith(".pdf"):
        return PyPDFLoader(path).load()
    return TextLoader(path, encoding="utf-8").load()


def build_index(data_path: str | None = None, index_path: str | None = None) -> FAISS:
    data_path = data_path or settings.data_path
    index_path = index_path or settings.faiss_index_path

    documents = _load_documents(data_path)

    splitter = RecursiveCharacterTextSplitter(
        chunk_size=800,
        chunk_overlap=120,
        separators=["\n\n", "\n", ". ", " ", ""],
    )
    chunks = splitter.split_documents(documents)

    store = FAISS.from_documents(chunks, get_embeddings())
    store.save_local(index_path)
    print(f"Indexed {len(chunks)} chunks from {data_path} -> {index_path}")
    return store


if __name__ == "__main__":
    build_index()
