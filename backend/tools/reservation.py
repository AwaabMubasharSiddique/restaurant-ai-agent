"""Reservation persistence. Availability checking lives in availability.py."""
from __future__ import annotations

from typing import Any

from models.schemas import Reservation
from tools.store import insert


def save_reservation(reservation: Reservation) -> dict[str, Any]:
    """Persist a reservation. Status is 'pending' by default — a human approves."""
    return insert("reservations", reservation.model_dump(mode="json"))
