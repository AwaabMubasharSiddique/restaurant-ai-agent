from __future__ import annotations

from datetime import datetime, timedelta

from config import settings
from tools.store import select


_ACTIVE_STATUSES = {"pending", "confirmed"}


def _to_minutes(hhmm: str) -> int:
    hours, minutes = hhmm.split(":")
    return int(hours) * 60 + int(minutes)


def _to_hhmm(total_minutes: int) -> str:
    return f"{total_minutes // 60:02d}:{total_minutes % 60:02d}"


def operating_slots() -> list[str]:
    start = _to_minutes(settings.opening_time)
    end = _to_minutes(settings.closing_time)
    step = settings.reservation_slot_minutes
    return [_to_hhmm(m) for m in range(start, end, step)]


def is_within_hours(time_str: str) -> bool:
    minutes = _to_minutes(time_str)
    return _to_minutes(settings.opening_time) <= minutes < _to_minutes(settings.closing_time)


def snap_to_slot(time_str: str) -> str:
    step = settings.reservation_slot_minutes
    start = _to_minutes(settings.opening_time)
    end = _to_minutes(settings.closing_time)
    minutes = _to_minutes(time_str)
    snapped = round((minutes - start) / step) * step + start
    snapped = max(start, min(snapped, end - step))
    return _to_hhmm(snapped)


def tables() -> list[dict]:
    return settings.restaurant_tables


def max_table_seats() -> int:
    return max((int(t["seats"]) for t in tables()), default=0)


def _occupied_table_ids(
    date_str: str, time_str: str, exclude_id: str | None = None
) -> set[str]:
    duration = settings.seating_duration_minutes
    requested = _to_minutes(time_str)
    busy: set[str] = set()
    for row in select("reservations", filters={"date": date_str}, order_by=None):
        if row.get("status", "pending") not in _ACTIVE_STATUSES:
            continue
        if exclude_id is not None and row.get("id") == exclude_id:
            continue
        table_id = row.get("table_id")
        booked_time = row.get("time")
        if not table_id or not booked_time:
            continue
        try:
            if abs(_to_minutes(booked_time) - requested) < duration:
                busy.add(table_id)
        except (ValueError, AttributeError):
            continue
    return busy


def find_table(
    date_str: str, time_str: str, party_size: int, exclude_id: str | None = None
) -> str | None:
    busy = _occupied_table_ids(date_str, time_str, exclude_id)
    fits = [
        t
        for t in tables()
        if int(t["seats"]) >= party_size and t["id"] not in busy
    ]
    fits.sort(key=lambda t: (int(t["seats"]), str(t["id"])))
    return str(fits[0]["id"]) if fits else None


def is_available(
    date_str: str, time_str: str, party_size: int, exclude_id: str | None = None
) -> bool:
    return find_table(date_str, time_str, party_size, exclude_id) is not None


def slot_count(date_str: str, time_str: str) -> int:
    rows = select(
        "reservations",
        filters={"date": date_str, "time": time_str},
        order_by=None,
    )
    return sum(1 for r in rows if r.get("status", "pending") in _ACTIVE_STATUSES)


def nearby_open_slots(
    date_str: str,
    time_str: str,
    party_size: int,
    limit: int = 3,
    exclude_id: str | None = None,
) -> list[str]:
    requested = _to_minutes(snap_to_slot(time_str))
    candidates = [
        slot
        for slot in operating_slots()
        if slot != time_str and is_available(date_str, slot, party_size, exclude_id)
    ]
    candidates.sort(key=lambda s: abs(_to_minutes(s) - requested))
    return candidates[:limit]


def format_time_12h(hhmm: str) -> str:
    hour, minute = (int(p) for p in hhmm.split(":"))
    suffix = "AM" if hour < 12 else "PM"
    display_hour = hour % 12 or 12
    return f"{display_hour}:{minute:02d} {suffix}"


def within_edit_window(created_at_iso: str, window_minutes: int) -> bool:
    if not created_at_iso:
        return False
    try:
        created = datetime.fromisoformat(created_at_iso)
    except (ValueError, TypeError):
        return False
    now = datetime.now(created.tzinfo)
    return (now - created) <= timedelta(minutes=window_minutes)
