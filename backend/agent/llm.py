"""Single place that builds the chat model, so the model name and API key
(both from the environment) are configured once."""
from __future__ import annotations

from langchain_openai import ChatOpenAI

from config import settings


def get_chat_model(temperature: float = 0.2) -> ChatOpenAI:
    return ChatOpenAI(
        model=settings.openai_chat_model,
        api_key=settings.openai_api_key,
        temperature=temperature,
    )
