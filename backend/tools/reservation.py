"""Reservation persistence. Availability checking lives in availability.py."""
from __future__ import annotations

from typing import Any

from models.schemas import Reservation
from tools.store import insert, update


def save_reservation(reservation: Reservation) -> dict[str, Any]:
    """Persist a reservation. Status is 'pending' by default — a human approves."""
    return insert("reservations", reservation.model_dump(mode="json"))


def update_reservation(reservation_id: str, changes: dict[str, Any]) -> dict[str, Any]:
    """Update fields on an existing reservation row (used for self-reschedules)."""
    return update("reservations", reservation_id, changes)


def cancel_reservation(reservation_id: str) -> dict[str, Any]:
    """Mark a reservation cancelled (frees its slot; staff still see the row)."""
    return update("reservations", reservation_id, {"status": "cancelled"})
