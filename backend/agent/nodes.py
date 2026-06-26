"""Graph nodes. Each node takes the full AgentState and returns a partial dict
that LangGraph merges back into the state.

Flow:  classify_intent -> (router) -> one handler -> persist_log -> END
"""
from __future__ import annotations

import logging
from datetime import datetime, timedelta

from langchain_core.messages import AIMessage, HumanMessage, SystemMessage
from pydantic import ValidationError

from agent.llm import get_chat_model
from agent.prompts import (
    COMPLAINT_SYSTEM_PROMPT,
    FIELD_PROMPTS,
    GREETING_SYSTEM_PROMPT,
    HOURS_SYSTEM_PROMPT,
    INTENT_SYSTEM_PROMPT,
    MENU_SYSTEM_PROMPT,
    OFF_TOPIC_SYSTEM_PROMPT,
    ORDER_SYSTEM_PROMPT,
    RESCHEDULE_SYSTEM_PROMPT,
    RESERVATION_SYSTEM_PROMPT,
)
from agent.state import AgentState
from config import settings
from models.schemas import (
    ConversationLog,
    IntentResult,
    Order,
    OrderItem,
    OrderTurn,
    Reservation,
    ReservationExtraction,
    RescheduleResult,
)
from menu import format_menu_for_prompt, order_total, price_items
from rag.retriever import retrieve
from tools.availability import (
    format_time_12h,
    is_available,
    is_within_hours,
    nearby_open_slots,
    snap_to_slot,
    within_edit_window,
)
from tools.logging_tool import log_conversation
from tools.order import save_order
from tools.reservation import cancel_reservation, save_reservation, update_reservation

logger = logging.getLogger("restaurant-ai.agent")

# Maps each routable intent (and the low-confidence case) to a handler node name.
INTENT_TO_NODE = {
    "reservation": "handle_reservation",
    "menu_question": "handle_menu_question",
    "order": "handle_order",
    "hours_location": "handle_hours_location",
    "complaint": "handle_complaint",
    "greeting": "handle_greeting",
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


def _bill_lines(priced: list) -> str:
    """Render priced order items as bullet lines with per-line subtotals."""
    return "\n".join(
        f"- {i['quantity']}× {i['name']} — ${i['price'] * i['quantity']:.2f}" for i in priced
    )


def _check_reservation_date(date_str: str) -> str | None:
    """Return an error message if the date is in the past or beyond the booking
    window (max_advance_days), else None."""
    requested = datetime.strptime(date_str, "%Y-%m-%d").date()
    today = datetime.now().date()
    if requested < today:
        return (
            f"It looks like {date_str} has already passed — "
            "what upcoming date would you like to come in?"
        )
    if requested > today + timedelta(days=settings.max_advance_days):
        return (
            f"We take reservations up to about a month ahead. Could you pick a date "
            f"within the next {settings.max_advance_days} days?"
        )
    return None


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
    # Pull more chunks for menu questions so "show me the menu" gets the full list.
    context = retrieve(state["user_message"], k=settings.menu_retrieval_k)
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


def handle_greeting(state: AgentState) -> dict:
    """Greetings, thanks, goodbyes — reply warmly, do NOT escalate to a human."""
    llm = get_chat_model(temperature=0.5)
    reply = llm.invoke(
        [
            SystemMessage(
                content=GREETING_SYSTEM_PROMPT.format(restaurant=settings.restaurant_name)
            ),
            HumanMessage(content=state["user_message"]),
        ]
    )
    return {"response": reply.content, "needs_human": False}


def handle_order(state: AgentState) -> dict:
    pending = state.get("pending_order") or []
    pending_summary = ", ".join(f"{i['quantity']}× {i['name']}" for i in pending) or "none"

    llm = get_chat_model(temperature=0).with_structured_output(OrderTurn)
    history = _format_history(state.get("messages", []))
    turn: OrderTurn = llm.invoke(
        [
            SystemMessage(
                content=ORDER_SYSTEM_PROMPT.format(
                    menu=format_menu_for_prompt(), pending=pending_summary
                )
            ),
            HumanMessage(
                content=f"Conversation:\n{history}\n\nLatest message: {state['user_message']}"
            ),
        ]
    )

    # Drop an order in progress.
    if turn.cancel and pending:
        return {
            "response": "No problem — I've cleared that order. Anything else?",
            "needs_human": False,
            "pending_order": [],
        }

    # Place the order the customer is confirming.
    if turn.confirm and pending:
        items = [
            OrderItem(name=i["name"], quantity=i["quantity"], price=i["price"]) for i in pending
        ]
        save_order(Order(items=items))
        return {
            "response": (
                "Order placed! ✅\n"
                f"{_bill_lines(pending)}\n"
                f"Total: ${order_total(pending):.2f}\n"
                "It's pending — the kitchen will confirm shortly. Payment on pickup."
            ),
            "needs_human": False,
            "pending_order": [],
        }

    # New / updated items -> price them, show the bill, and ask to confirm.
    if turn.items:
        priced, unknown = price_items(turn.items)
        if not priced:
            missing = ", ".join(unknown) if unknown else "those"
            return {
                "response": (
                    f"I couldn't find {missing} on our menu, so I can't add that. "
                    "Want me to list what we have?"
                ),
                "needs_human": False,
            }
        note = (
            f"\n\n(I couldn't find {', '.join(unknown)} on our menu, so I left those out.)"
            if unknown
            else ""
        )
        return {
            "response": (
                "Here's your order:\n"
                f"{_bill_lines(priced)}\n"
                f"Total: ${order_total(priced):.2f}{note}\n\n"
                "Shall I place it? It'll be pending until the kitchen confirms. (Payment on pickup.)"
            ),
            "needs_human": False,
            "pending_order": priced,
        }

    # "Confirm" but nothing is in progress.
    if turn.confirm:
        return {
            "response": "I don't have an order started yet — what would you like to order?",
            "needs_human": False,
        }

    # Nothing actionable yet.
    return {
        "response": (
            "I'd love to take your order! What would you like? "
            "You can ask to see the menu too."
        ),
        "needs_human": False,
    }


def handle_reservation(state: AgentState) -> dict:
    # A request was already saved this session -> reschedule flow (self-service
    # within the edit window, otherwise hand the change to staff). Never silently
    # save a duplicate row.
    if state.get("reservation_submitted"):
        record = state.get("reservation_record")
        if record and record.get("id"):
            return _handle_reservation_followup(state, record)
        return {
            "response": (
                "You already have a pending request — I've flagged your change for "
                "our team, who'll adjust it when they confirm. What would you like to change?"
            ),
            "needs_human": True,
        }

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

    # Reject past dates and dates beyond the booking window.
    date_problem = _check_reservation_date(reservation.date)
    if date_problem:
        return {"response": date_problem, "needs_human": False}

    # Large groups are coordinated by staff directly (a set menu may apply), so
    # we capture the request as pending and hand it to a person.
    if reservation.party_size >= settings.large_party_threshold:
        saved = save_reservation(reservation)
        summary = (
            f"{reservation.party_size} on {reservation.date} "
            f"at {format_time_12h(reservation.time)}"
        )
        return {
            "response": (
                f"Thanks, {reservation.name}! For a group of {reservation.party_size} "
                f"on {reservation.date} at {format_time_12h(reservation.time)}, I've "
                f"logged your request as pending and a team member will reach out "
                f"personally to arrange the details. We'll contact you at "
                f"{reservation.phone}."
            ),
            "needs_human": True,
            "reservation_submitted": True,
            "reservation_summary": summary,
            "reservation_record": saved,
        }

    # Availability check BEFORE we offer anything (simple per-slot counting).
    if is_available(reservation.date, reservation.time):
        saved = save_reservation(reservation)
        pretty_time = format_time_12h(reservation.time)
        summary = f"{reservation.party_size} on {reservation.date} at {pretty_time}"
        return {
            "response": (
                f"Thank you, {reservation.name}! I've put in a reservation request "
                f"for {reservation.party_size} on {reservation.date} at {pretty_time}. "
                f"It's marked as pending — our team will review and confirm shortly, "
                f"and we'll reach you at {reservation.phone}. \U0001f33f"
            ),
            "needs_human": False,
            "reservation_submitted": True,
            "reservation_summary": summary,
            "reservation_record": saved,
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


def _handle_reservation_followup(state: AgentState, record: dict) -> dict:
    """Change OR cancel an already-submitted reservation in place if still within
    the edit window; otherwise hand it to staff. (Reservations only — not orders.)"""
    window = settings.reservation_edit_window_minutes
    old_summary = state.get("reservation_summary", "your reservation")
    within = within_edit_window(record.get("created_at", ""), window)

    llm = get_chat_model(temperature=0).with_structured_output(RescheduleResult)
    history = _format_history(state.get("messages", []))
    today = datetime.now().strftime("%A, %Y-%m-%d")
    result: RescheduleResult = llm.invoke(
        [
            SystemMessage(
                content=RESCHEDULE_SYSTEM_PROMPT.format(
                    today=today,
                    name=record["name"],
                    date=record["date"],
                    time=record["time"],
                    party_size=record["party_size"],
                    phone=record["phone"],
                )
            ),
            HumanMessage(
                content=f"Conversation:\n{history}\n\nLatest message: {state['user_message']}"
            ),
        ]
    )

    # --- Status inquiry (just asking about the booking, not changing it) ---
    if result.action == "status":
        return {
            "response": (
                f"Your reservation is for {record['party_size']} on {record['date']} "
                f"at {format_time_12h(record['time'])}, under {record['name']}. "
                "It's still pending — our team will confirm shortly."
            ),
            "needs_human": False,
        }

    # --- Cancellation ---
    if result.action == "cancel":
        if within:
            cancel_reservation(record["id"])
            return {
                "response": (
                    f"Done — I've cancelled your reservation for {old_summary}. "
                    "We hope to welcome you another time!"
                ),
                "needs_human": False,
                "reservation_submitted": False,
                "reservation_record": {},
                "reservation_summary": "",
            }
        return {
            "response": (
                f"I've passed your request to cancel {old_summary} to our team — "
                "they'll take care of it when they review. Sorry we'll miss you!"
            ),
            "needs_human": True,
        }

    # --- Change: only self-serve within the window ---
    if not within:
        return {
            "response": (
                f"Your request for {old_summary} has been in for over {window} minutes, "
                "so our team will make any changes when they confirm — I've flagged your "
                "note. What would you like changed?"
            ),
            "needs_human": True,
        }

    # Keep current values for anything the customer didn't change.
    try:
        new_time_raw = result.time or record["time"]
        if not is_within_hours(new_time_raw):
            return {
                "response": (
                    f"We're open from {format_time_12h(settings.opening_time)} to "
                    f"{format_time_12h(settings.closing_time)}. What time should I change it to?"
                ),
                "needs_human": False,
            }
        revised = Reservation(
            name=result.name or record["name"],
            date=result.date or record["date"],
            time=snap_to_slot(new_time_raw),
            party_size=result.party_size or record["party_size"],
            phone=result.phone or record["phone"],
        )
    except (ValueError, ValidationError):
        return {
            "response": "Sure — what new date and time would you like? (e.g. June 28 at 7:00 PM)",
            "needs_human": False,
        }

    date_problem = _check_reservation_date(revised.date)
    if date_problem:
        return {"response": date_problem, "needs_human": False}

    # Nothing actually changed yet -> ask what they want to change.
    if (
        revised.date == record["date"]
        and revised.time == record["time"]
        and revised.party_size == record["party_size"]
        and revised.phone == record["phone"]
        and revised.name == record["name"]
    ):
        return {
            "response": "Of course — what would you like to change (time, date, or party size)?",
            "needs_human": False,
        }

    # If the slot moved, make sure the new one isn't full.
    slot_moved = revised.date != record["date"] or revised.time != record["time"]
    if slot_moved and not is_available(revised.date, revised.time):
        alternatives = nearby_open_slots(revised.date, revised.time)
        if alternatives:
            pretty = ", ".join(format_time_12h(s) for s in alternatives)
            return {
                "response": (
                    f"That new time on {revised.date} is fully reserved, but we have "
                    f"openings at {pretty}. Want one of those?"
                ),
                "needs_human": False,
            }
        return {
            "response": f"We're fully reserved on {revised.date}. Would another day work?",
            "needs_human": False,
        }

    # Apply the change to the SAME row (keep id / status / created_at).
    changes = {
        "name": revised.name,
        "date": revised.date,
        "time": revised.time,
        "party_size": revised.party_size,
        "phone": revised.phone,
    }
    update_reservation(record["id"], changes)
    new_record = {**record, **changes}
    new_summary = f"{revised.party_size} on {revised.date} at {format_time_12h(revised.time)}"
    return {
        "response": (
            f"All set, {revised.name} — I've updated your reservation to {new_summary}. "
            "It's still pending and our team will confirm shortly."
        ),
        "needs_human": revised.party_size >= settings.large_party_threshold,
        "reservation_submitted": True,
        "reservation_record": new_record,
        "reservation_summary": new_summary,
    }


def handle_other(state: AgentState) -> dict:
    """Off-topic / unclear / out-of-scope: warm redirect, NO human escalation —
    trivia and chit-chat shouldn't create staff follow-ups."""
    llm = get_chat_model(temperature=0.3)
    reply = llm.invoke(
        [
            SystemMessage(
                content=OFF_TOPIC_SYSTEM_PROMPT.format(restaurant=settings.restaurant_name)
            ),
            HumanMessage(content=state["user_message"]),
        ]
    )
    return {"response": reply.content, "needs_human": False}


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
