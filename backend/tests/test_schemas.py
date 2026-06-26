"""Tests for the domain models: defaults and validation."""
import pytest
from pydantic import ValidationError

from models.schemas import ConversationLog, Order, OrderItem, Reservation


def test_reservation_defaults_to_pending_with_timestamp():
    r = Reservation(name="Ada", date="2099-01-01", time="19:00", party_size=2, phone="555")
    assert r.status == "pending"
    assert r.created_at


def test_reservation_rejects_malformed_date():
    with pytest.raises(ValidationError):
        Reservation(name="Ada", date="01/02/2099", time="19:00", party_size=2, phone="555")


def test_reservation_rejects_malformed_time():
    with pytest.raises(ValidationError):
        Reservation(name="Ada", date="2099-01-01", time="7pm", party_size=2, phone="555")


def test_reservation_requires_positive_party_size():
    with pytest.raises(ValidationError):
        Reservation(name="Ada", date="2099-01-01", time="19:00", party_size=0, phone="555")


def test_order_defaults_and_item_quantity():
    order = Order(items=[OrderItem(name="Margherita Pizza", quantity=2)])
    assert order.status == "pending"
    assert order.items[0].quantity == 2


def test_order_item_defaults_quantity_to_one():
    assert OrderItem(name="Baklava").quantity == 1


def test_conversation_log_defaults():
    log = ConversationLog(
        conversation_id="s1",
        customer_message="hi",
        detected_intent="other",
        agent_response="hello",
    )
    assert log.needs_human is False
    assert log.timestamp
