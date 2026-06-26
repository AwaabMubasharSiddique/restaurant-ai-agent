"""Graph nodes. Each node takes the full AgentState and returns a partial dict
that LangGraph merges back into the state.

Flow:  classify_intent -> (router) -> one handler -> persist_log -> END
"""
from __future__ import annotations

import logging
from datetime import datetime

from langchain_core.messages import AIMessage, HumanMessage, SystemMessage
from pydantic import ValidationError

from agent.llm import get_chat_model
from agent.prompts import (
    COMPLAINT_SYSTEM_PROMPT,
    FIELD_PROMPTS,
    HANDOFF_MESSAGE,
    HOURS_SYSTEM_PROMPT,
    INTENT_SYSTEM_PROMPT,
    MENU_SYSTEM_PROMPT,
    ORDER_SYSTEM_PROMPT,
    RESERVATION_SYSTEM_PROMPT,
)
from agent.state import AgentState
from config import settings
from models.schemas import (
    ConversationLog,
    IntentResult,
    Order,
    OrderExtraction,
    Reservation,
    ReservationExtraction,
)
from rag.retriever import retrieve
from tools.availability import (
    format_time_12h,
    is_available,
    is_within_hours,
    nearby_open_slots,
    snap_to_slot,
)
from tools.logging_tool import log_conversation
from tools.order import save_order
from tools.reservation import save_reservation

logger = logging.getLogger("restaurant-ai.agent")

# Maps each routable intent (and the low-confidence case) to a handler node name.
INTENT_TO_NODE = {
    "reservation": "handle_reservation",
    "menu_question": "handle_menu_question",
    "order": "handle_order",
    "hours_location": "handle_hours_location",
    "complaint": "handle_complaint",
    "other": "handle_other",
}
HANDLER_NODES = list(dict.fromkeys(INTENT_TO_NODE.values()))


def _format_history(messages: list, limit: int = 12) -> str:
    """Render recent turns as plain text for prompts that need full context."""
    lines = []
    for message in messages[-limit:]:
        role = "Customer" if message.type == "human" else "Assistant"
        lines.append(f"{role}: {message.content}")
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# 1. Intent classification + routing
# ---------------------------------------------------------------------------
def classify_intent(state: AgentState) -> dict:
    llm = get_chat_model(temperature=0).with_structured_output(IntentResult)
    history = _format_history(state.get("messages", []))
    result: IntentResult = llm.invoke(
        [
            SystemMessage(content=INTENT_SYSTEM_PROMPT),
            HumanMessage(
                content=(
                    f"Conversation so far:\n{history}\n\n"
                    f"Classify the latest customer message: {state['user_message']}"
                )
            ),
        ]
    )
    return {"intent": result.intent, "confidence": result.confidence}


def route_intent(state: AgentState) -> str:
    """Conditional edge: pick the handler node based on intent + confidence."""
    if state.get("confidence", 1.0) < settings.low_confidence_threshold:
        return "handle_other"  # not sure enough -> hand off to a human
    return INTENT_TO_NODE.get(state.get("intent", "other"), "handle_other")


# ---------------------------------------------------------------------------
# 2. Handlers
# ---------------------------------------------------------------------------
def handle_menu_question(state: AgentState) -> dict:
    context = retrieve(state["user_message"])
    llm = get_chat_model(temperature=0.2)
    reply = llm.invoke(
        [
            SystemMessage(
                content=MENU_SYSTEM_PROMPT.format(restaurant=settings.restaurant_name)
            ),
            HumanMessage(
                content=f"Menu & info:\n{context}\n\nCustomer question: {state['user_message']}"
            ),
        ]
    )
    return {"response": reply.content, "needs_human": False}


def handle_hours_location(state: AgentState) -> dict:
    context = retrieve(state["user_message"])
    llm = get_chat_model(temperature=0.2)
    reply = llm.invoke(
        [
            SystemMessage(
                content=HOURS_SYSTEM_PROMPT.format(restaurant=settings.restaurant_name)
            ),
            HumanMessage(
                content=f"Info:\n{context}\n\nCustomer question: {state['user_message']}"
            ),
        ]
    )
    return {"response": reply.content, "needs_human": False}


def handle_complaint(state: AgentState) -> dict:
    llm = get_chat_model(temperature=0.4)
    reply = llm.invoke(
        [
            SystemMessage(content=COMPLAINT_SYSTEM_PROMPT),
            HumanMessage(content=state["user_message"]),
        ]
    )
    # A complaint always escalates to a person.
    return {"response": reply.content, "needs_human": True}


def handle_order(state: AgentState) -> dict:
    llm = get_chat_model(temperature=0).with_structured_output(OrderExtraction)
    history = _format_history(state.get("messages", []))
    extraction: OrderExtraction = llm.invoke(
        [
            SystemMessage(content=ORDER_SYSTEM_PROMPT),
            HumanMessage(
                content=f"Conversation:\n{history}\n\nLatest message: {state['user_message']}"
            ),
        ]
    )

    if not extraction.items:
        return {
            "response": (
                "I'd love to take your order! What would you like? "
                "Let me know any sizes or special requests too."
            ),
            "needs_human": False,
        }

    order = Order(items=extraction.items, notes=extraction.notes)
    save_order(order)

    summary = ", ".join(f"{i.quantity}× {i.name}" for i in order.items)
    note = f" (note: {order.notes})" if order.notes else ""
    return {
        "response": (
            f"Got it — I've started an order for {summary}{note}, marked as "
            f"pending. The kitchen will confirm it shortly. Anything else?"
        ),
        "needs_human": False,
    }


def handle_reservation(state: AgentState) -> dict:
    llm = get_chat_model(temperature=0).with_structured_output(ReservationExtraction)
    history = _format_history(state.get("messages", []))
    today = datetime.now().strftime("%A, %Y-%m-%d")

    extraction: ReservationExtraction = llm.invoke(
        [
            SystemMessage(content=RESERVATION_SYSTEM_PROMPT.format(today=today)),
            HumanMessage(
                content=(
                    f"Conversation:\n{history}\n\n"
                    f"Latest customer message: {state['user_message']}"
                )
            ),
        ]
    )

    # Which required details are still missing? (party_size 0/None both count.)
    required = {
        "name": extraction.name,
        "date": extraction.date,
        "time": extraction.time,
        "party_size": extraction.party_size,
        "phone": extraction.phone,
    }
    missing = [field for field, value in required.items() if not value]
    if missing:
        return {"response": _ask_for_missing(missing), "needs_human": False}

    # All details present — validate the date/time and snap to a real slot.
    try:
        requested_date = datetime.strptime(extraction.date, "%Y-%m-%d").date()
        if not is_within_hours(extraction.time):
            return {
                "response": (
                    f"We're open from {format_time_12h(settings.opening_time)} to "
                    f"{format_time_12h(settings.closing_time)}. "
                    f"What time in that window would you like?"
                ),
                "needs_human": False,
            }
        time_slot = snap_to_slot(extraction.time)
        reservation = Reservation(
            name=extraction.name,
            date=extraction.date,
            time=time_slot,
            party_size=extraction.party_size,
            phone=extraction.phone,
        )
    except (ValueError, ValidationError):
        return {
            "response": (
                "I just want to get the details right — could you share the date "
                "as a calendar date (e.g. June 28) and a time (e.g. 7:00 PM)?"
            ),
            "needs_human": False,
        }

    # Don't accept requests for a date that has already passed.
    if requested_date < datetime.now().date():
        return {
            "response": (
                f"It looks like {reservation.date} has already passed — "
                "what upcoming date would you like to come in?"
            ),
            "needs_human": False,
        }

    # Large groups are coordinated by staff directly (a set menu may apply), so
    # we capture the request as pending and hand it to a person.
    if reservation.party_size >= settings.large_party_threshold:
        save_reservation(reservation)
        return {
            "response": (
                f"Thanks, {reservation.name}! For a group of {reservation.party_size} "
                f"on {reservation.date} at {format_time_12h(reservation.time)}, I've "
                f"logged your request as pending and a team member will reach out "
                f"personally to arrange the details. We'll contact you at "
                f"{reservation.phone}."
            ),
            "needs_human": True,
        }

    # Availability check BEFORE we offer anything (simple per-slot counting).
    if is_available(reservation.date, reservation.time):
        save_reservation(reservation)
        pretty_time = format_time_12h(reservation.time)
        return {
            "response": (
                f"Thank you, {reservation.name}! I've put in a reservation request "
                f"for {reservation.party_size} on {reservation.date} at {pretty_time}. "
                f"It's marked as pending — our team will review and confirm shortly, "
                f"and we'll reach you at {reservation.phone}. \U0001f33f"
            ),
            "needs_human": False,
        }

    # Slot is full: offer the nearest open slots and let the customer choose.
    alternatives = nearby_open_slots(reservation.date, reservation.time)
    if alternatives:
        pretty = ", ".join(format_time_12h(s) for s in alternatives)
        return {
            "response": (
                f"That time on {reservation.date} is fully reserved, but we do have "
                f"openings at {pretty}. Would any of those work for you?"
            ),
            "needs_human": False,
        }
    return {
        "response": (
            f"I'm so sorry — we're fully reserved on {reservation.date}. "
            f"Would another day work? I'm happy to check availability."
        ),
        "needs_human": False,
    }


def handle_other(state: AgentState) -> dict:
    """Catch-all / low-confidence: polite hand-off, flag for a human."""
    return {"response": HANDOFF_MESSAGE, "needs_human": True}


def _ask_for_missing(missing: list[str]) -> str:
    phrases = [FIELD_PROMPTS[field] for field in missing]
    if len(phrases) == 1:
        ask = phrases[0]
    else:
        ask = ", ".join(phrases[:-1]) + f", and {phrases[-1]}"
    return f"I'd be glad to help set that up! Could you share {ask}?"


# ---------------------------------------------------------------------------
# 3. Logging (runs for every turn, then END)
# ---------------------------------------------------------------------------
def persist_log(state: AgentState) -> dict:
    response = state.get("response", "")
    log = ConversationLog(
        conversation_id=state["session_id"],
        customer_message=state["user_message"],
        detected_intent=state.get("intent", "other"),
        agent_response=response,
        needs_human=state.get("needs_human", False),
    )
    try:
        log_conversation(log)
    except Exception:  # logging must never break the chat
        logger.exception("Failed to log conversation for session %s", state["session_id"])

    # Append the assistant reply to history so the next turn has full context.
    return {"messages": [AIMessage(content=response)]}
