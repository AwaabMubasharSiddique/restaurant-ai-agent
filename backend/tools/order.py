from __future__ import annotations

from typing import Any

from models.schemas import Order
from tools.store import insert


def save_order(order: Order) -> dict[str, Any]:
    return insert("orders", order.model_dump(mode="json"))
