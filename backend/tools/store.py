from __future__ import annotations

import logging
import threading
from collections import defaultdict
from functools import lru_cache
from typing import Any
from uuid import uuid4

from clock import now_iso
from config import settings

try:
    from supabase import create_client
except ImportError:
    create_client = None

logger = logging.getLogger("restaurant-ai.store")

_MEMORY: dict[str, list[dict]] = defaultdict(list)
_MEMORY_LOCK = threading.RLock()


@lru_cache(maxsize=1)
def get_supabase():
    if create_client and settings.supabase_url and settings.supabase_key:
        return create_client(settings.supabase_url, settings.supabase_key)
    return None


def _now_iso() -> str:
    return now_iso()


def insert(table: str, row: dict[str, Any]) -> dict[str, Any]:
    row = dict(row)
    row.setdefault("created_at", _now_iso())

    client = get_supabase()
    if client is not None:
        try:
            result = client.table(table).insert(row).execute()
            if result.data:
                return result.data[0]
            logger.error("Supabase insert into %s returned no rows", table)
        except Exception:
            logger.exception("Supabase insert into %s failed; falling back to memory", table)
        # fall through to the in-memory path so the turn still completes

    row.setdefault("id", str(uuid4()))
    with _MEMORY_LOCK:
        _MEMORY[table].append(row)
    return row


def update(table: str, row_id: str, changes: dict[str, Any]) -> dict[str, Any]:
    client = get_supabase()
    if client is not None:
        try:
            result = client.table(table).update(dict(changes)).eq("id", row_id).execute()
            if result.data:
                return result.data[0]
            logger.error("Supabase update of %s id=%s matched no rows", table, row_id)
        except Exception:
            logger.exception("Supabase update of %s failed; falling back to memory", table)

    with _MEMORY_LOCK:
        for row in _MEMORY[table]:
            if row.get("id") == row_id:
                row.update(changes)
                return dict(row)
    return {"id": row_id, **dict(changes)}


def select(
    table: str,
    filters: dict[str, Any] | None = None,
    order_by: str | None = "created_at",
    descending: bool = True,
) -> list[dict[str, Any]]:
    client = get_supabase()
    if client is not None:
        try:
            query = client.table(table).select("*")
            for key, value in (filters or {}).items():
                query = query.eq(key, value)
            if order_by:
                query = query.order(order_by, desc=descending)
            return query.execute().data or []
        except Exception:
            logger.exception("Supabase select from %s failed; falling back to memory", table)

    with _MEMORY_LOCK:
        rows = [dict(r) for r in _MEMORY[table]]
    if filters:
        rows = [r for r in rows if all(r.get(k) == v for k, v in filters.items())]
    if order_by:
        # Coerce to str so mixed/missing sort keys never raise on comparison.
        rows.sort(key=lambda r: str(r.get(order_by) or ""), reverse=descending)
    return rows
