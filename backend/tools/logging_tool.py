"""Conversation logging. Every turn is recorded so the restaurant can review
chats, audit the agent, and spot messages flagged needs_human."""
from __future__ import annotations

from typing import Any

from models.schemas import ConversationLog
from tools.store import insert


def log_conversation(log: ConversationLog) -> dict[str, Any]:
    return insert("conversation_logs", log.model_dump(mode="json"))
