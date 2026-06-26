from __future__ import annotations

from datetime import datetime, timezone
from typing import List, Literal, Optional

from pydantic import BaseModel, Field, field_validator


Intent = Literal[
    "reservation",
    "menu_question",
    "order",
    "hours_location",
    "complaint",
    "greeting",
    "other",
]

ReservationStatus = Literal["pending", "confirmed", "cancelled", "rejected"]
OrderStatus = Literal["pending", "confirmed", "completed", "cancelled"]


def _utcnow_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


class OrderItem(BaseModel):
    name: str
    quantity: int = Field(default=1, ge=1)
    price: Optional[float] = None


class Reservation(BaseModel):
    name: str
    date: str
    time: str
    party_size: int = Field(ge=1)
    phone: str

    table_id: Optional[str] = None
    status: ReservationStatus = "pending"
    created_at: str = Field(default_factory=_utcnow_iso)

    @field_validator("date")
    @classmethod
    def _validate_date(cls, v: str) -> str:
        datetime.strptime(v, "%Y-%m-%d")
        return v

    @field_validator("time")
    @classmethod
    def _validate_time(cls, v: str) -> str:
        datetime.strptime(v, "%H:%M")
        return v


class Order(BaseModel):
    items: List[OrderItem]
    customer_name: str
    phone: str
    address: str
    total: Optional[float] = None
    notes: Optional[str] = None
    status: OrderStatus = "pending"
    created_at: str = Field(default_factory=_utcnow_iso)


class ConversationLog(BaseModel):
    conversation_id: str
    timestamp: str = Field(default_factory=_utcnow_iso)
    customer_message: str
    detected_intent: str
    agent_response: str
    needs_human: bool = False


class IntentResult(BaseModel):
    intent: Intent
    confidence: float = Field(ge=0.0, le=1.0)


class ReservationExtraction(BaseModel):
    name: Optional[str] = None
    date: Optional[str] = None
    time: Optional[str] = None
    party_size: Optional[int] = None
    phone: Optional[str] = None


class OrderExtraction(BaseModel):
    items: List[OrderItem] = Field(default_factory=list)
    notes: Optional[str] = None


class OrderTurn(BaseModel):
    items: List[OrderItem] = Field(default_factory=list)
    name: Optional[str] = None
    phone: Optional[str] = None
    address: Optional[str] = None
    confirm: bool = False
    cancel: bool = False


class RescheduleResult(BaseModel):
    action: Literal["status", "change", "cancel"] = "change"
    name: Optional[str] = None
    date: Optional[str] = None
    time: Optional[str] = None
    party_size: Optional[int] = None
    phone: Optional[str] = None


class ChatRequest(BaseModel):
    message: str = Field(min_length=1, max_length=2000)
    session_id: Optional[str] = None


class ChatResponse(BaseModel):
    session_id: str
    response: str
    intent: str
    needs_human: bool
