from __future__ import annotations

import logging
from datetime import datetime, timedelta

from langchain_core.messages import AIMessage, HumanMessage, SystemMessage
from pydantic import ValidationError

from agent.llm import safe_structured, safe_text
from agent.prompts import (
    COMPLAINT_SYSTEM_PROMPT,
    COMPOSE_SYSTEM_PROMPT,
    FIELD_PROMPTS,
    GREETING_SYSTEM_PROMPT,
    HOURS_SYSTEM_PROMPT,
    INTENT_SYSTEM_PROMPT,
    MENU_SYSTEM_PROMPT,
    OFF_TOPIC_TRIAGE_PROMPT,
    ORDER_SYSTEM_PROMPT,
    RESCHEDULE_SYSTEM_PROMPT,
    RESERVATION_SYSTEM_PROMPT,
)
from agent.state import AgentState
from clock import now, today
from config import settings
from models.schemas import (
    ConversationLog,
    IntentResult,
    OffTopicTriage,
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
    fits_within_hours,
    format_time_12h,
    max_table_seats,
    nearby_open_slots,
    snap_to_slot,
    within_edit_window,
)
from tools.logging_tool import log_conversation
from tools.order import save_order
from tools.reservation import (
    cancel_reservation,
    reserve_table,
    save_reservation,
    update_reservation_if_free,
)

logger = logging.getLogger("restaurant-ai.agent")


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


_GLITCH_FALLBACK = "Sorry — I glitched for a second there. Mind trying that again?"


def compose(
    situation: str,
    facts: str = "",
    *,
    fallback: str | None = None,
    temperature: float = 0.75,
) -> str:
    """Phrase a reply from a situation + locked facts. The model varies wording;
    the facts must come through verbatim. Never raises — on any LLM failure it
    returns ``fallback`` (or a generic line), so a turn that has already written
    to the DB still completes and commits its state instead of erroring and
    inviting a duplicate-booking retry."""
    human = f"Situation: {situation}"
    if facts:
        human += f"\n\nFacts (use exactly, don't alter):\n{facts}"
    return safe_text(
        [SystemMessage(content=COMPOSE_SYSTEM_PROMPT), HumanMessage(content=human)],
        temperature=temperature,
        fallback=fallback or _GLITCH_FALLBACK,
    )


def _format_history(messages: list, limit: int = 12) -> str:
    lines = []
    for message in messages[-limit:]:
        role = "Customer" if message.type == "human" else "Assistant"
        lines.append(f"{role}: {message.content}")
    return "\n".join(lines)


def _bill_lines(priced: list) -> str:
    return "\n".join(
        f"- {i['quantity']}× {i['name']} — ${i['price'] * i['quantity']:.2f}" for i in priced
    )


def _check_reservation_date(date_str: str) -> str | None:
    try:
        requested = datetime.strptime(date_str, "%Y-%m-%d").date()
    except (ValueError, TypeError):
        return None
    today_ = today()
    if requested < today_:
        return compose(
            "The date the customer asked for has already gone by; gently ask what "
            "upcoming date they'd like to come in instead.",
            f"date they gave: {date_str} (already in the past)",
        )
    if requested > today_ + timedelta(days=settings.max_advance_days):
        return compose(
            "The customer asked for a date too far out; ask them to pick one within "
            "our booking window.",
            f"how far ahead we book: about {settings.max_advance_days} days",
        )
    return None


def _natural_join(phrases: list[str]) -> str:
    if len(phrases) == 1:
        return phrases[0]
    return ", ".join(phrases[:-1]) + f", and {phrases[-1]}"


def classify_intent(state: AgentState) -> dict:
    history = _format_history(state.get("messages", []))
    result = safe_structured(
        [
            SystemMessage(content=INTENT_SYSTEM_PROMPT),
            HumanMessage(
                content=(
                    f"Conversation so far:\n{history}\n\n"
                    f"Classify the latest customer message: {state['user_message']}"
                )
            ),
        ],
        IntentResult,
        fallback=IntentResult(intent="other", confidence=0.0),
    )
    return {"intent": result.intent, "confidence": result.confidence}


def route_intent(state: AgentState) -> str:
    if state.get("confidence", 1.0) < settings.low_confidence_threshold:
        return "handle_other"
    return INTENT_TO_NODE.get(state.get("intent", "other"), "handle_other")


def handle_menu_question(state: AgentState) -> dict:
    context = retrieve(state["user_message"], k=settings.menu_retrieval_k)
    reply = safe_text(
        [
            SystemMessage(content=MENU_SYSTEM_PROMPT),
            HumanMessage(
                content=f"Menu & info:\n{context}\n\nCustomer question: {state['user_message']}"
            ),
        ],
        temperature=0.6,
        fallback=(
            "I'm having a brief hiccup pulling up the menu — could you ask again in a "
            "moment? I can also help with hours or a reservation."
        ),
    )
    return {"response": reply, "needs_human": False}


def handle_hours_location(state: AgentState) -> dict:
    context = retrieve(state["user_message"])
    reply = safe_text(
        [
            SystemMessage(content=HOURS_SYSTEM_PROMPT),
            HumanMessage(
                content=f"Info:\n{context}\n\nCustomer question: {state['user_message']}"
            ),
        ],
        temperature=0.6,
        fallback=(
            "I'm having trouble looking that up this second — mind asking again in a "
            "moment?"
        ),
    )
    return {"response": reply, "needs_human": False}


def handle_complaint(state: AgentState) -> dict:
    reply = safe_text(
        [
            SystemMessage(content=COMPLAINT_SYSTEM_PROMPT),
            HumanMessage(content=state["user_message"]),
        ],
        temperature=0.6,
        fallback=(
            "I'm really sorry about that. I've flagged this for a team member who'll "
            "follow up with you personally."
        ),
    )
    return {"response": reply, "needs_human": True}


def handle_greeting(state: AgentState) -> dict:
    reply = safe_text(
        [
            SystemMessage(content=GREETING_SYSTEM_PROMPT),
            HumanMessage(content=state["user_message"]),
        ],
        temperature=0.85,
        fallback=(
            f"Welcome to {settings.restaurant_name}! How can I help — the menu, hours, "
            "a reservation, or an order?"
        ),
    )
    return {"response": reply, "needs_human": False}


def handle_order(state: AgentState) -> dict:
    pending = state.get("pending_order") or []
    pending_summary = ", ".join(f"{i['quantity']}× {i['name']}" for i in pending) or "none"

    history = _format_history(state.get("messages", []))
    turn = safe_structured(
        [
            SystemMessage(
                content=ORDER_SYSTEM_PROMPT.format(
                    menu=format_menu_for_prompt(), pending=pending_summary
                )
            ),
            HumanMessage(
                content=f"Conversation:\n{history}\n\nLatest message: {state['user_message']}"
            ),
        ],
        OrderTurn,
        fallback=OrderTurn(),
    )

    if turn.cancel and pending:
        return {
            "response": compose(
                "The customer asked to scrap the order they were building; confirm it's "
                "cleared and check whether there's anything else you can get them."
            ),
            "needs_human": False,
            "pending_order": [],
        }

    corrections: list[tuple[str, str]] = []
    if turn.items:
        priced, unknown, corrections = price_items(turn.items)
        if not priced:
            missing = ", ".join(unknown) if unknown else "those"
            return {
                "response": compose(
                    "The customer named items that aren't on our menu, so nothing could "
                    "be added; offer to list what we do have.",
                    f"items we couldn't find: {missing}",
                ),
                "needs_human": False,
            }
    elif pending:
        priced, unknown = pending, []
    else:
        priced, unknown = [], []

    if not priced:
        if turn.confirm:
            return {
                "response": compose(
                    "The customer tried to place an order, but nothing's been started "
                    "yet; ask what they'd like."
                ),
                "needs_human": False,
            }
        return {
            "response": compose(
                "The customer is in ordering mode but hasn't named anything yet; invite "
                "them to order, and mention they can ask to see the menu."
            ),
            "needs_human": False,
        }

    unknown_note = (
        f"\n\n(I couldn't find {', '.join(unknown)} on our menu, so I left those out.)"
        if unknown
        else ""
    )
    if corrections:
        reads = "; ".join(f'"{said}" as {matched}' for said, matched in corrections)
        unknown_note += f"\n\n(I read {reads} — let me know if that's not right.)"
    bill = f"{_bill_lines(priced)}\nTotal: ${order_total(priced):.2f}"

    missing_contact = []
    if not turn.name:
        missing_contact.append("your name")
    if not turn.phone:
        missing_contact.append("a phone number")
    if not turn.address:
        missing_contact.append("a delivery address")

    if missing_contact:
        return {
            "response": compose(
                "You've totaled the customer's in-progress order. Read it back to them, "
                "then ask for the delivery details still missing so you can place it.",
                f"order:\n{bill}{unknown_note}\n\nstill need: {_natural_join(missing_contact)}",
            ),
            "needs_human": False,
            "pending_order": priced,
        }

    if turn.confirm:
        items = [
            OrderItem(name=i["name"], quantity=i["quantity"], price=i["price"]) for i in priced
        ]
        total = order_total(priced)
        save_order(
            Order(
                items=items,
                customer_name=turn.name,
                phone=turn.phone,
                address=turn.address,
                total=total,
            )
        )
        return {
            "response": compose(
                "The customer just confirmed and the order is now placed. Give them a "
                "quick, upbeat recap, and make clear it's pending until the kitchen "
                "confirms and that payment is on delivery.",
                f"order placed:\n{_bill_lines(priced)}\nTotal: ${total:.2f}\n"
                f"delivering to: {turn.address}\nunder name: {turn.name}\n"
                f"phone: {turn.phone}\nstatus: pending kitchen confirmation; payment on delivery",
                fallback=(
                    f"Order placed! ✅\n{_bill_lines(priced)}\nTotal: ${total:.2f}\n"
                    f"Delivering to {turn.address}, under {turn.name} ({turn.phone}). "
                    "It's pending until the kitchen confirms — payment on delivery."
                ),
            ),
            "needs_human": False,
            "pending_order": [],
        }

    return {
        "response": compose(
            "The customer's order and all delivery details are in; read it back and ask "
            "if you should place it. Note it stays pending until the kitchen confirms and "
            "payment is on delivery.",
            f"order:\n{bill}{unknown_note}\ndelivering to: {turn.address}\n"
            f"under name: {turn.name}\nphone: {turn.phone}",
        ),
        "needs_human": False,
        "pending_order": priced,
    }


def handle_reservation(state: AgentState) -> dict:
    if state.get("reservation_submitted"):
        record = state.get("reservation_record")
        if record and record.get("id"):
            return _handle_reservation_followup(state, record)
        return {
            "response": compose(
                "The customer already has a pending reservation request on file; let them "
                "know the team will handle any change when they confirm, and ask what "
                "they'd like to change."
            ),
            "needs_human": True,
        }

    history = _format_history(state.get("messages", []))
    today_str = now().strftime("%A, %Y-%m-%d")

    extraction = safe_structured(
        [
            SystemMessage(content=RESERVATION_SYSTEM_PROMPT.format(today=today_str)),
            HumanMessage(
                content=(
                    f"Conversation:\n{history}\n\n"
                    f"Latest customer message: {state['user_message']}"
                )
            ),
        ],
        ReservationExtraction,
        fallback=ReservationExtraction(),
    )

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

    try:
        if not fits_within_hours(extraction.time):
            return {
                "response": compose(
                    "The time the customer wants doesn't leave a full seating before we "
                    "close; share the hours and ask for an earlier time.",
                    f"open from {format_time_12h(settings.opening_time)} to "
                    f"{format_time_12h(settings.closing_time)}; a seating runs "
                    f"{settings.seating_duration_minutes} minutes",
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
            "response": compose(
                "You couldn't make sense of the date/time the customer gave; ask them to "
                "restate it as a normal calendar date and clock time.",
                "example to suggest: June 28 at 7:00 PM",
            ),
            "needs_human": False,
        }

    date_problem = _check_reservation_date(reservation.date)
    if date_problem:
        return {"response": date_problem, "needs_human": False}

    pretty_time = format_time_12h(reservation.time)
    summary = f"{reservation.party_size} on {reservation.date} at {pretty_time}"

    if reservation.party_size > max_table_seats():
        saved = save_reservation(reservation)
        return {
            "response": compose(
                "The party is bigger than any single table, so you've logged the request "
                "as pending and a team member will personally arrange the seating. "
                "Reassure them.",
                f"name: {reservation.name}\nparty size: {reservation.party_size}\n"
                f"date: {reservation.date}\ntime: {pretty_time}\n"
                f"we'll contact them at: {reservation.phone}\nstatus: pending",
                fallback=(
                    f"Thanks, {reservation.name}! A party of {reservation.party_size} is "
                    f"larger than any single table, so I've logged your request for "
                    f"{summary} as pending — a team member will arrange the seating and "
                    f"reach you at {reservation.phone}."
                ),
            ),
            "needs_human": True,
            "reservation_submitted": True,
            "reservation_summary": summary,
            "reservation_record": saved,
        }

    saved = reserve_table(reservation)
    if saved is not None:
        return {
            "response": compose(
                "You've put in the customer's reservation request; thank them and recap "
                "it. It's pending until the team reviews and confirms.",
                f"name: {reservation.name}\nparty size: {reservation.party_size}\n"
                f"date: {reservation.date}\ntime: {pretty_time}\n"
                f"we'll reach them at: {reservation.phone}\nstatus: pending confirmation",
                fallback=(
                    f"Thank you, {reservation.name}! I've put in your reservation request "
                    f"for {summary}. It's pending — our team will confirm shortly and "
                    f"reach you at {reservation.phone}."
                ),
            ),
            "needs_human": False,
            "reservation_submitted": True,
            "reservation_summary": summary,
            "reservation_record": saved,
        }

    alternatives = nearby_open_slots(
        reservation.date, reservation.time, reservation.party_size
    )
    if alternatives:
        pretty = ", ".join(format_time_12h(s) for s in alternatives)
        return {
            "response": compose(
                "The requested time is fully booked for that party size, but other times "
                "that day are open; offer them and ask if any work.",
                f"date: {reservation.date}\nparty size: {reservation.party_size}\n"
                f"open times: {pretty}",
            ),
            "needs_human": False,
        }
    return {
        "response": compose(
            "That whole day is fully booked for the customer's party size; apologize and "
            "offer to check another day.",
            f"date: {reservation.date}\nparty size: {reservation.party_size}",
        ),
        "needs_human": False,
    }


def _handle_reservation_followup(state: AgentState, record: dict) -> dict:
    window = settings.reservation_edit_window_minutes
    old_summary = state.get("reservation_summary", "your reservation")
    within = within_edit_window(record.get("created_at", ""), window)

    history = _format_history(state.get("messages", []))
    today_str = now().strftime("%A, %Y-%m-%d")
    result = safe_structured(
        [
            SystemMessage(
                content=RESCHEDULE_SYSTEM_PROMPT.format(
                    today=today_str,
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
        ],
        RescheduleResult,
        fallback=RescheduleResult(action="status"),
    )

    if result.action == "status":
        return {
            "response": compose(
                "The customer is asking about their existing reservation; tell them what's "
                "on file and that it's still pending team confirmation.",
                f"name: {record['name']}\nparty size: {record['party_size']}\n"
                f"date: {record['date']}\ntime: {format_time_12h(record['time'])}\n"
                f"status: pending",
            ),
            "needs_human": False,
        }

    if result.action == "cancel":
        if within:
            cancel_reservation(record["id"])
            return {
                "response": compose(
                    "You've cancelled the customer's reservation as they asked; confirm "
                    "it's done and that you'd love to see them another time.",
                    f"cancelled reservation: {old_summary}",
                    fallback=(
                        f"Done — I've cancelled your reservation for {old_summary}. "
                        "We hope to welcome you another time!"
                    ),
                ),
                "needs_human": False,
                "reservation_submitted": False,
                "reservation_record": {},
                "reservation_summary": "",
            }
        return {
            "response": compose(
                "The customer wants to cancel, but it's past the self-serve window, so "
                "you've passed it to the team to handle on review. Sorry to see them go.",
                f"reservation to cancel: {old_summary}",
            ),
            "needs_human": True,
        }

    if not within:
        return {
            "response": compose(
                "The customer wants to change a reservation that's past the self-serve "
                "edit window; let them know the team will apply changes on confirmation, "
                "and ask what they'd like changed.",
                f"reservation: {old_summary}\nedit window: {window} minutes",
            ),
            "needs_human": True,
        }

    try:
        new_time_raw = result.time or record["time"]
        if not fits_within_hours(new_time_raw):
            return {
                "response": compose(
                    "The new time doesn't leave a full seating before we close; share the "
                    "hours and ask for an earlier time.",
                    f"open from {format_time_12h(settings.opening_time)} to "
                    f"{format_time_12h(settings.closing_time)}; a seating runs "
                    f"{settings.seating_duration_minutes} minutes",
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
            "response": compose(
                "You couldn't parse the new date/time for the change; ask them to restate "
                "it as a calendar date and clock time.",
                "example to suggest: June 28 at 7:00 PM",
            ),
            "needs_human": False,
        }

    date_problem = _check_reservation_date(revised.date)
    if date_problem:
        return {"response": date_problem, "needs_human": False}

    if (
        revised.date == record["date"]
        and revised.time == record["time"]
        and revised.party_size == record["party_size"]
        and revised.phone == record["phone"]
        and revised.name == record["name"]
    ):
        return {
            "response": compose(
                "The customer wants to change the reservation but hasn't said what; ask "
                "what they'd like to change — time, date, or party size."
            ),
            "needs_human": False,
        }

    too_big = revised.party_size > max_table_seats()
    needs_reseat = (
        revised.date != record["date"]
        or revised.time != record["time"]
        or revised.party_size != record["party_size"]
    )
    new_summary = f"{revised.party_size} on {revised.date} at {format_time_12h(revised.time)}"

    changes = update_reservation_if_free(
        record["id"],
        revised,
        current_table_id=record.get("table_id"),
        needs_reseat=needs_reseat,
        too_big=too_big,
    )
    if changes is None:
        alternatives = nearby_open_slots(
            revised.date, revised.time, revised.party_size, exclude_id=record["id"]
        )
        if alternatives:
            pretty = ", ".join(format_time_12h(s) for s in alternatives)
            return {
                "response": compose(
                    "The requested change leaves no free table at that time, but other "
                    "times that day are open; offer them and ask if one works.",
                    f"date: {revised.date}\ntime: {format_time_12h(revised.time)}\n"
                    f"party size: {revised.party_size}\nopen times: {pretty}",
                ),
                "needs_human": False,
            }
        return {
            "response": compose(
                "The requested change can't be fit — that day is fully booked for the "
                "new party size; offer another day.",
                f"date: {revised.date}\nparty size: {revised.party_size}",
            ),
            "needs_human": False,
        }

    new_record = {**record, **changes}
    if too_big:
        return {
            "response": compose(
                "You've updated the reservation, but the new party is larger than any "
                "single table, so the team will arrange seating personally. It's still "
                "pending.",
                f"name: {revised.name}\nparty size: {revised.party_size}\n"
                f"updated to: {new_summary}\nstatus: pending",
                fallback=(
                    f"Thanks, {revised.name} — I've updated your request to {new_summary}. "
                    f"A party that size needs the team to arrange seating, so it stays "
                    f"pending."
                ),
            ),
            "needs_human": True,
            "reservation_submitted": True,
            "reservation_record": new_record,
            "reservation_summary": new_summary,
        }
    return {
        "response": compose(
            "You've updated the customer's reservation; confirm the new details and that "
            "it's still pending team confirmation.",
            f"name: {revised.name}\nupdated to: {new_summary}\nstatus: pending",
            fallback=(
                f"All set, {revised.name} — I've updated your reservation to {new_summary}. "
                f"It's still pending and our team will confirm shortly."
            ),
        ),
        "needs_human": False,
        "reservation_submitted": True,
        "reservation_record": new_record,
        "reservation_summary": new_summary,
    }


def handle_other(state: AgentState) -> dict:
    triage = safe_structured(
        [
            SystemMessage(content=OFF_TOPIC_TRIAGE_PROMPT),
            HumanMessage(content=state["user_message"]),
        ],
        OffTopicTriage,
        fallback=OffTopicTriage(forward_to_team=False),
    )

    if triage.forward_to_team:
        return {
            "response": compose(
                "The customer asked for something outside what you handle, but it sounds "
                "like a real request our team should follow up on. Let them know you've "
                "passed it along and someone will get back to them, then mention you can "
                "help directly with the menu, hours, reservations, or an order.",
                f"their message: {state['user_message']}",
            ),
            "needs_human": True,
        }

    return {
        "response": compose(
            "The customer's message is off-topic and not something the restaurant deals "
            "with at all. Lightly let them know it's outside what you can help with, "
            "without answering it, and steer them toward what you can do — the menu, "
            "hours & location, reservations, and orders."
        ),
        "needs_human": False,
    }


def _ask_for_missing(missing: list[str]) -> str:
    needed = _natural_join([FIELD_PROMPTS[field] for field in missing])
    return compose(
        "You're setting up a reservation and still need a few details from the customer; "
        "ask for them warmly.",
        f"still need: {needed}",
    )


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
    except Exception:
        logger.exception("Failed to log conversation for session %s", state["session_id"])

    return {"messages": [AIMessage(content=response)]}
