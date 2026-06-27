from __future__ import annotations

from typing import Annotated, TypedDict

from langgraph.graph.message import add_messages

from config import settings


def add_bounded_messages(left: list, right: list) -> list:
    """add_messages, then keep only the most recent turns so a session's stored
    state can't grow without bound across a long conversation."""
    merged = add_messages(left, right)
    cap = settings.max_history_messages
    if cap and len(merged) > cap:
        return merged[-cap:]
    return merged


class AgentState(TypedDict, total=False):
    messages: Annotated[list, add_bounded_messages]

    session_id: str
    user_message: str
    intent: str
    confidence: float
    response: str
    needs_human: bool

    reservation_submitted: bool
    reservation_summary: str
    reservation_record: dict

    pending_order: list
