"""Agent node/routing tests. The LLM is never called: we monkeypatch the
safe_* boundary so we exercise the deterministic branching logic only.

Guarded with importorskip so the suite still runs where the heavy LLM deps
aren't installed; CI installs requirements.txt and runs these for real.
"""
from datetime import timedelta

import pytest

pytest.importorskip("langgraph")
pytest.importorskip("langchain_core")
pytest.importorskip("langchain_openai")

from agent import nodes  # noqa: E402
from clock import today  # noqa: E402
from models.schemas import (  # noqa: E402
    OffTopicTriage,
    OrderTurn,
    ReservationExtraction,
)


@pytest.fixture
def echo_llm(monkeypatch):
    """safe_text returns its fallback; safe_structured returns a per-test object."""
    monkeypatch.setattr(nodes, "safe_text", lambda messages, **kw: kw.get("fallback", "ok"))

    holder = {}

    def fake_structured(messages, schema, *, fallback):
        return holder.get(schema, fallback)

    monkeypatch.setattr(nodes, "safe_structured", fake_structured)
    return holder


def _future(days: int = 2) -> str:
    return (today() + timedelta(days=days)).strftime("%Y-%m-%d")


def test_route_low_confidence_goes_to_other():
    assert nodes.route_intent({"intent": "reservation", "confidence": 0.1}) == "handle_other"


def test_route_maps_intent():
    assert nodes.route_intent({"intent": "menu_question", "confidence": 0.9}) == "handle_menu_question"
    assert nodes.route_intent({"intent": "order", "confidence": 0.9}) == "handle_order"


def test_reservation_missing_fields_does_not_submit(echo_llm):
    echo_llm[ReservationExtraction] = ReservationExtraction(name="Sara")
    out = nodes.handle_reservation({"user_message": "table for tomorrow", "messages": []})
    assert out["needs_human"] is False
    assert not out.get("reservation_submitted")


def test_reservation_books_when_table_free(echo_llm):
    echo_llm[ReservationExtraction] = ReservationExtraction(
        name="Sara", date=_future(), time="19:00", party_size=2, phone="555-0100"
    )
    out = nodes.handle_reservation({"user_message": "book it", "messages": []})
    assert out["reservation_submitted"] is True
    assert out["needs_human"] is False
    assert out["reservation_record"].get("id")
    assert out["reservation_record"]["table_id"]


def test_reservation_party_too_big_flags_human(echo_llm):
    echo_llm[ReservationExtraction] = ReservationExtraction(
        name="Sara", date=_future(), time="19:00",
        party_size=settings_max() + 1, phone="555-0100",
    )
    out = nodes.handle_reservation({"user_message": "huge party", "messages": []})
    assert out["needs_human"] is True
    assert out["reservation_submitted"] is True


def settings_max() -> int:
    from tools.availability import max_table_seats

    return max_table_seats()


def test_order_missing_contact_holds_pending(echo_llm):
    echo_llm[OrderTurn] = OrderTurn(items=[{"name": "Baklava", "quantity": 1}])
    out = nodes.handle_order({"user_message": "one baklava", "messages": [], "pending_order": []})
    assert out["needs_human"] is False
    assert out["pending_order"] and out["pending_order"][0]["name"] == "Baklava"


def test_order_confirm_places_and_clears(echo_llm):
    echo_llm[OrderTurn] = OrderTurn(
        items=[{"name": "Baklava", "quantity": 1}],
        name="Sara", phone="555-0100", address="1 Main St", confirm=True,
    )
    out = nodes.handle_order({"user_message": "place it", "messages": [], "pending_order": []})
    assert out["pending_order"] == []
    assert out["needs_human"] is False


def test_off_topic_forwards_real_request(echo_llm):
    echo_llm[OffTopicTriage] = OffTopicTriage(forward_to_team=True)
    out = nodes.handle_other({"user_message": "do you cater weddings?"})
    assert out["needs_human"] is True


def test_off_topic_trivia_no_handoff(echo_llm):
    echo_llm[OffTopicTriage] = OffTopicTriage(forward_to_team=False)
    out = nodes.handle_other({"user_message": "capital of pakistan?"})
    assert out["needs_human"] is False
