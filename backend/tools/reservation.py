from __future__ import annotations

import threading
from typing import Any

from models.schemas import Reservation
from tools.availability import find_table
from tools.store import insert, update

# Serializes the check-then-write window so two concurrent requests can't both
# claim the same table for the same slot. For the in-memory backend this is the
# guarantee; with Supabase a unique index on (date, table_id, active status) is
# the real backstop, with this lock avoiding most contention.
_booking_lock = threading.Lock()


def save_reservation(reservation: Reservation) -> dict[str, Any]:
    return insert("reservations", reservation.model_dump(mode="json"))


def reserve_table(reservation: Reservation) -> dict[str, Any] | None:
    """Atomically find a fitting free table and save the reservation. Returns the
    saved record, or None if no table is available for that slot."""
    with _booking_lock:
        table_id = find_table(
            reservation.date, reservation.time, reservation.party_size
        )
        if not table_id:
            return None
        reservation.table_id = table_id
        return insert("reservations", reservation.model_dump(mode="json"))


def update_reservation_if_free(
    reservation_id: str,
    revised: Reservation,
    *,
    current_table_id: str | None,
    needs_reseat: bool,
    too_big: bool,
) -> dict[str, Any] | None:
    """Atomically re-assign a table (if the change needs one) and apply the update.
    Returns the applied changes dict, or None if no table is free for the new slot."""
    with _booking_lock:
        if too_big:
            new_table_id: str | None = None
        elif needs_reseat:
            new_table_id = find_table(
                revised.date,
                revised.time,
                revised.party_size,
                exclude_id=reservation_id,
            )
            if not new_table_id:
                return None
        else:
            new_table_id = current_table_id

        changes = {
            "name": revised.name,
            "date": revised.date,
            "time": revised.time,
            "party_size": revised.party_size,
            "phone": revised.phone,
            "table_id": new_table_id,
        }
        update("reservations", reservation_id, changes)
        return changes


def update_reservation(reservation_id: str, changes: dict[str, Any]) -> dict[str, Any]:
    return update("reservations", reservation_id, changes)


def cancel_reservation(reservation_id: str) -> dict[str, Any]:
    return update("reservations", reservation_id, {"status": "cancelled"})
