"""Conversation memory = a LangGraph checkpointer.

The compiled graph is given this checkpointer. On every invoke we pass
config={"configurable": {"thread_id": session_id}}. LangGraph then:

  1. loads the saved state for that thread (all prior messages) before the run,
  2. runs the graph with the new message appended,
  3. saves the updated state back under the same thread_id.

So each session/conversation has its own isolated, persistent history with no
manual bookkeeping. MemorySaver keeps it in RAM (fine for a single-process demo).
For production, swap to a durable saver — e.g. SqliteSaver or PostgresSaver —
without touching any node code.
"""
from __future__ import annotations

from langgraph.checkpoint.memory import MemorySaver

_checkpointer = MemorySaver()


def get_checkpointer() -> MemorySaver:
    return _checkpointer
