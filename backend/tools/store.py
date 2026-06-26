from __future__ import annotations

from collections import defaultdict
from datetime import datetime, timezone
from functools import lru_cache
from typing import Any
from uuid import uuid4

from config import settings

try:
    from supabase import Client, create_client
except ImportError:
    Client = None
    create_client = None


_MEMORY: dict[str, list[dict]] = defaultdict(list)


@lru_cache(maxsize=1)
def get_supabase():
    if create_client and settings.supabase_url and settings.supabase_key:
        return create_client(settings.supabase_url, settings.supabase_key)
    return None


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def insert(table: str, row: dict[str, Any]) -> dict[str, Any]:
    row = dict(row)
    row.setdefault("created_at", _now_iso())

    client = get_supabase()
    if client is not None:
        result = client.table(table).insert(row).execute()
        return result.data[0] if result.data else row

    row.setdefault("id", str(uuid4()))
    _MEMORY[table].append(row)
    return row


def update(table: str, row_id: str, changes: dict[str, Any]) -> dict[str, Any]:
    client = get_supabase()
    if client is not None:
        result = client.table(table).update(dict(changes)).eq("id", row_id).execute()
        return result.data[0] if result.data else {"id": row_id, **dict(changes)}

    for row in _MEMORY[table]:
        if row.get("id") == row_id:
            row.update(changes)
            return row
    return {"id": row_id, **dict(changes)}


def select(
    table: str,
    filters: dict[str, Any] | None = None,
    order_by: str | None = "created_at",
    descending: bool = True,
) -> list[dict[str, Any]]:
    client = get_supabase()
    if client is not None:
        query = client.table(table).select("*")
        for key, value in (filters or {}).items():
            query = query.eq(key, value)
        if order_by:
            query = query.order(order_by, desc=descending)
        return query.execute().data or []

    rows = list(_MEMORY[table])
    if filters:
        rows = [r for r in rows if all(r.get(k) == v for k, v in filters.items())]
    if order_by:
        rows.sort(key=lambda r: r.get(order_by, ""), reverse=descending)
    return rows
