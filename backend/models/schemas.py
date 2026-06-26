"""Pydantic schemas shared across the app.

Three groups live here:

1. Persisted domain models  -> Reservation, Order, ConversationLog
   These are what we write to Supabase (or the in-memory fallback).

2. LLM structured-output models -> IntentResult, ReservationExtraction,
   OrderExtraction. The agent forces the model to return JSON matching these,
   so we never hand-parse free text.

3. API transport models -> ChatRequest, ChatResponse.
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import List, Literal, Optional

from pydantic import BaseModel, Field, field_validator

# The categories the classifier must pick from.
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
    """Timezone-aware UTC timestamp as ISO string (sorts correctly newest-first)."""
    return datetime.now(timezone.utc).isoformat()


# ---------------------------------------------------------------------------
# 1. Persisted domain models
# ---------------------------------------------------------------------------
class OrderItem(BaseModel):
    """A single line in an order. Quantity lives on the item (a real order has
    several items, each with its own count) rather than as one number on the
    whole order."""

    name: str
    quantity: int = Field(default=1, ge=1)
    price: Optional[float] = None  # unit price, filled from the menu at order time


class Reservation(BaseModel):
    name: str
    date: str  # ISO calendar date, "YYYY-MM-DD"
    time: str  # 24h clock, "HH:MM"
    party_size: int = Field(ge=1)
    phone: str
    status: ReservationStatus = "pending"
    created_at: str = Field(default_factory=_utcnow_iso)

    @field_validator("date")
    @classmethod
    def _validate_date(cls, v: str) -> str:
        datetime.strptime(v, "%Y-%m-%d")  # raises if malformed
        return v

    @field_validator("time")
    @classmethod
    def _validate_time(cls, v: str) -> str:
        datetime.strptime(v, "%H:%M")  # raises if malformed
        return v


class Order(BaseModel):
    items: List[OrderItem]
    notes: Optional[str] = None
    status: OrderStatus = "pending"
    created_at: str = Field(default_factory=_utcnow_iso)


class ConversationLog(BaseModel):
    conversation_id: str  # == session id; groups one conversation's turns
    timestamp: str = Field(default_factory=_utcnow_iso)
    customer_message: str
    detected_intent: str
    agent_response: str
    needs_human: bool = False


# ---------------------------------------------------------------------------
# 2. LLM structured-output models (the model is forced to fill these)
# ---------------------------------------------------------------------------
class IntentResult(BaseModel):
    intent: Intent
    confidence: float = Field(ge=0.0, le=1.0)


class ReservationExtraction(BaseModel):
    """Partial reservation gathered across multiple turns. Every field is
    optional — early in the conversation most will be null."""

    name: Optional[str] = None
    date: Optional[str] = None  # "YYYY-MM-DD"
    time: Optional[str] = None  # "HH:MM"
    party_size: Optional[int] = None
    phone: Optional[str] = None


class OrderExtraction(BaseModel):
    items: List[OrderItem] = Field(default_factory=list)
    notes: Optional[str] = None


class OrderTurn(BaseModel):
    """One turn of the ordering flow: the customer's current full order, plus
    whether they're confirming or cancelling the order in progress."""

    items: List[OrderItem] = Field(default_factory=list)
    confirm: bool = False
    cancel: bool = False


class RescheduleResult(BaseModel):
    """A follow-up on an existing reservation: a status check, a cancellation, or
    a set of revised details (optional fields, defaulting to current values)."""

    action: Literal["status", "change", "cancel"] = "change"
    name: Optional[str] = None
    date: Optional[str] = None  # "YYYY-MM-DD"
    time: Optional[str] = None  # "HH:MM"
    party_size: Optional[int] = None
    phone: Optional[str] = None


# ---------------------------------------------------------------------------
# 3. API transport models
# ---------------------------------------------------------------------------
class ChatRequest(BaseModel):
    message: str = Field(min_length=1, max_length=2000)
    session_id: Optional[str] = None


class ChatResponse(BaseModel):
    session_id: str
    response: str
    intent: str
    needs_human: bool
