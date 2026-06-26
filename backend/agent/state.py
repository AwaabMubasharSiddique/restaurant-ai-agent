"""The shared state object that flows through every node in the graph.

LangGraph passes this dict from node to node. Each node returns a *partial*
dict; LangGraph merges it into the running state. Two things to note:

- `messages` uses the `add_messages` reducer, so returning {"messages": [msg]}
  APPENDS rather than overwrites. Combined with the checkpointer (see memory.py)
  this is the conversation history that makes multi-turn reservations work.
- Every other field is a plain overwrite-on-return value.
"""
from __future__ import annotations

from typing import Annotated, TypedDict

from langgraph.graph.message import add_messages


class AgentState(TypedDict, total=False):
    # Full running transcript (HumanMessage / AIMessage). Appended via reducer.
    messages: Annotated[list, add_messages]

    # Per-request scratch values
    session_id: str
    user_message: str  # the current turn's text
    intent: str  # set by classify_intent
    confidence: float  # set by classify_intent
    response: str  # set by the chosen handler
    needs_human: bool  # set by the chosen handler
