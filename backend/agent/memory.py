from __future__ import annotations

import logging
import os
import sqlite3

from langgraph.checkpoint.memory import MemorySaver

from config import settings

logger = logging.getLogger("restaurant-ai.memory")

_checkpointer = None


def _build_checkpointer():
    """Prefer a durable SQLite checkpointer so conversations survive a restart;
    fall back to in-process memory if the sqlite saver package isn't installed."""
    try:
        from langgraph.checkpoint.sqlite import SqliteSaver

        path = settings.checkpoint_db_path
        os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
        conn = sqlite3.connect(path, check_same_thread=False)
        logger.info("Using SQLite checkpointer at %s", path)
        return SqliteSaver(conn)
    except Exception:
        logger.warning(
            "SQLite checkpointer unavailable; using in-memory checkpointer "
            "(conversation state will not survive a restart).",
            exc_info=True,
        )
        return MemorySaver()


def get_checkpointer():
    global _checkpointer
    if _checkpointer is None:
        _checkpointer = _build_checkpointer()
    return _checkpointer
