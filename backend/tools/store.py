"""Thin persistence layer used by every tool.

If Supabase is configured (SUPABASE_URL + SUPABASE_KEY) we write/read there.
Otherwise we fall back to a process-local in-memory store, so the whole demo
runs end-to-end with zero external services. The rest of the code never needs
to know which backend is active.

Every row gets a `created_at` ISO timestamp, and reads default to newest-first,
because the restaurant watches these tables directly (no notifications in v1).
"""
from __future__ import annotations

from collections import defaultdict
from datetime import datetime, timezone
from functools import lru_cache
from typing import Any

from config import settings

try:  # supabase is optional at runtime
    from supabase import Client, create_client
except ImportError:  # pragma: no cover
    Client = None  # type: ignore
    create_client = None  # type: ignore

# In-memory fallback: { table_name: [row, row, ...] }
_MEMORY: dict[str, list[dict]] = defaultdict(list)


@lru_cache(maxsize=1)
def get_supabase():
    """Return a Supabase client, or None to use the in-memory fallback."""
    if create_client and settings.supabase_url and settings.supabase_key:
        return create_client(settings.supabase_url, settings.supabase_key)
    return None


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def insert(table: str, row: dict[str, Any]) -> dict[str, Any]:
    """Insert one row. Stamps created_at if the caller didn't."""
    row = dict(row)
    row.setdefault("created_at", _now_iso())

    client = get_supabase()
    if client is not None:
        result = client.table(table).insert(row).execute()
        return result.data[0] if result.data else row

    _MEMORY[table].append(row)
    return row


def select(
    table: str,
    filters: dict[str, Any] | None = None,
    order_by: str | None = "created_at",
    descending: bool = True,
) -> list[dict[str, Any]]:
    """Read rows, optionally filtered by equality and ordered (newest-first)."""
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
