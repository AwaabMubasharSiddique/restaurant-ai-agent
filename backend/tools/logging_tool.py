from __future__ import annotations

import re
from typing import Any

from models.schemas import ConversationLog
from tools.store import insert

# Reservations/orders keep the real contact details for fulfillment; the
# conversation log is for audit/analytics, so we strip obvious PII from it.
_EMAIL_RE = re.compile(r"\b[\w.+-]+@[\w-]+\.[\w.-]+\b")
_PHONE_RE = re.compile(r"(?<!\w)(\+?\d[\d\s().-]{6,}\d)(?!\w)")


def redact_pii(text: str) -> str:
    if not text:
        return text
    text = _EMAIL_RE.sub("[email]", text)
    text = _PHONE_RE.sub("[phone]", text)
    return text


def log_conversation(log: ConversationLog) -> dict[str, Any]:
    safe = log.model_copy(
        update={
            "customer_message": redact_pii(log.customer_message),
            "agent_response": redact_pii(log.agent_response),
        }
    )
    return insert("conversation_logs", safe.model_dump(mode="json"))
