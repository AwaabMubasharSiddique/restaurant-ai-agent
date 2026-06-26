"""Reservation availability via simple per-slot counting (v1).

The model is deliberately coarse: a day is divided into fixed time slots
(RESERVATION_SLOT_MINUTES apart, between OPENING_TIME and CLOSING_TIME), and each
slot can hold up to MAX_RESERVATIONS_PER_SLOT reservations. We just COUNT the
active reservations sitting in a slot and compare to that cap — we are not
tracking individual tables, table sizes, or how long a party stays.

Where this extends later (see README): replace the integer cap with a set of
real tables (capacity, joinable, indoor/outdoor), turn "count < cap" into a
bin-packing/assignment check against party_size, and model seating duration so a
7:00 booking still blocks part of 8:00.
"""
from __future__ import annotations

from config import settings
from tools.store import select

# A reservation in one of these states occupies a seat for counting purposes.
_ACTIVE_STATUSES = {"pending", "confirmed"}


def _to_minutes(hhmm: str) -> int:
    hours, minutes = hhmm.split(":")
    return int(hours) * 60 + int(minutes)


def _to_hhmm(total_minutes: int) -> str:
    return f"{total_minutes // 60:02d}:{total_minutes % 60:02d}"


def operating_slots() -> list[str]:
    """All bookable slot start-times for a day, e.g. 11:00, 11:30, ... 21:30."""
    start = _to_minutes(settings.opening_time)
    end = _to_minutes(settings.closing_time)
    step = settings.reservation_slot_minutes
    return [_to_hhmm(m) for m in range(start, end, step)]


def is_within_hours(time_str: str) -> bool:
    """True if a (valid) HH:MM time falls inside [opening, closing).

    Raises ValueError on a malformed time so callers can ask for clarification
    instead of silently snapping a nonsense time into the open window.
    """
    minutes = _to_minutes(time_str)
    return _to_minutes(settings.opening_time) <= minutes < _to_minutes(settings.closing_time)


def snap_to_slot(time_str: str) -> str:
    """Round an arbitrary time to the nearest valid slot, clamped to opening hours.

    Callers should check is_within_hours() first; the clamp here is just a
    safety net so we never produce an out-of-range slot.
    """
    step = settings.reservation_slot_minutes
    start = _to_minutes(settings.opening_time)
    end = _to_minutes(settings.closing_time)
    minutes = _to_minutes(time_str)
    snapped = round((minutes - start) / step) * step + start
    snapped = max(start, min(snapped, end - step))
    return _to_hhmm(snapped)


def slot_count(date_str: str, time_str: str) -> int:
    """How many active reservations already sit in this date+time slot."""
    rows = select(
        "reservations",
        filters={"date": date_str, "time": time_str},
        order_by=None,
    )
    return sum(1 for r in rows if r.get("status", "pending") in _ACTIVE_STATUSES)


def is_available(date_str: str, time_str: str) -> bool:
    """True if the slot is under capacity."""
    return slot_count(date_str, time_str) < settings.max_reservations_per_slot


def nearby_open_slots(date_str: str, time_str: str, limit: int = 3) -> list[str]:
    """Return open slots on the same day, closest in time to the requested one."""
    requested = _to_minutes(snap_to_slot(time_str))
    candidates = [
        slot
        for slot in operating_slots()
        if slot != time_str and is_available(date_str, slot)
    ]
    candidates.sort(key=lambda s: abs(_to_minutes(s) - requested))
    return candidates[:limit]


def format_time_12h(hhmm: str) -> str:
    """'19:00' -> '7:00 PM' (cross-platform, no %-I)."""
    hour, minute = (int(p) for p in hhmm.split(":"))
    suffix = "AM" if hour < 12 else "PM"
    display_hour = hour % 12 or 12
    return f"{display_hour}:{minute:02d} {suffix}"
