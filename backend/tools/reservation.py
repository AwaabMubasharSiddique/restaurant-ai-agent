from __future__ import annotations

from typing import Any

from models.schemas import Reservation
from tools.store import insert, update


def save_reservation(reservation: Reservation) -> dict[str, Any]:
    return insert("reservations", reservation.model_dump(mode="json"))


def update_reservation(reservation_id: str, changes: dict[str, Any]) -> dict[str, Any]:
    return update("reservations", reservation_id, changes)


def cancel_reservation(reservation_id: str) -> dict[str, Any]:
    return update("reservations", reservation_id, {"status": "cancelled"})
