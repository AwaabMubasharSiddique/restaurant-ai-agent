from __future__ import annotations

from typing import Annotated, TypedDict

from langgraph.graph.message import add_messages


class AgentState(TypedDict, total=False):
    messages: Annotated[list, add_messages]

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
