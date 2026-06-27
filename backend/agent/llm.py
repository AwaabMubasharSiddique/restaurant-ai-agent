from __future__ import annotations

import logging
from typing import TypeVar

from langchain_openai import ChatOpenAI
from pydantic import BaseModel

from config import settings

logger = logging.getLogger("restaurant-ai.llm")

T = TypeVar("T", bound=BaseModel)


def get_chat_model(temperature: float = 0.2) -> ChatOpenAI:
    return ChatOpenAI(
        model=settings.openai_chat_model,
        api_key=settings.openai_api_key,
        temperature=temperature,
        timeout=settings.llm_timeout_seconds,
        max_retries=settings.llm_max_retries,
    )


def safe_text(messages: list, *, temperature: float = 0.2, fallback: str) -> str:
    """Invoke the model for a free-text reply; never raise. On any failure
    (timeout, rate limit, network, odd content shape) return ``fallback``."""
    try:
        reply = get_chat_model(temperature=temperature).invoke(messages)
        return _as_text(reply.content) or fallback
    except Exception:
        logger.exception("LLM text call failed; using fallback")
        return fallback


def safe_structured(messages: list, schema: type[T], *, fallback: T) -> T:
    """Invoke the model with structured output; never raise. On failure or a
    malformed/validation-failing response, return ``fallback``."""
    try:
        model = get_chat_model(temperature=0).with_structured_output(schema)
        result = model.invoke(messages)
        return result if isinstance(result, schema) else fallback
    except Exception:
        logger.exception("LLM structured call failed; using fallback")
        return fallback


def _as_text(content) -> str:
    """Normalize a message's content to a string (it may be a list of blocks)."""
    if isinstance(content, str):
        return content.strip()
    if isinstance(content, list):
        parts = []
        for block in content:
            if isinstance(block, str):
                parts.append(block)
            elif isinstance(block, dict) and "text" in block:
                parts.append(str(block["text"]))
        return "".join(parts).strip()
    return str(content or "").strip()
