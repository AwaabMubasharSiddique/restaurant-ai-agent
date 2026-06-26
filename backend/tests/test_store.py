"""Tests for the persistence fallback: stamping created_at, filtering, and the
newest-first ordering the restaurant relies on when reading tables directly."""
from tools.store import insert, select, update


def test_insert_stamps_created_at():
    row = insert("orders", {"items": [], "status": "pending"})
    assert "created_at" in row and row["created_at"]


def test_insert_keeps_caller_created_at():
    row = insert("orders", {"items": [], "created_at": "2020-01-01T00:00:00+00:00"})
    assert row["created_at"] == "2020-01-01T00:00:00+00:00"


def test_select_orders_newest_first():
    insert("conversation_logs", {"conversation_id": "old", "created_at": "2020-01-01T00:00:00+00:00"})
    insert("conversation_logs", {"conversation_id": "new", "created_at": "2024-01-01T00:00:00+00:00"})

    rows = select("conversation_logs")  # defaults to created_at desc

    assert rows[0]["conversation_id"] == "new"
    assert rows[1]["conversation_id"] == "old"


def test_select_filters_by_equality():
    insert("reservations", {"date": "2099-01-01", "time": "19:00"})
    insert("reservations", {"date": "2099-01-01", "time": "20:00"})

    matches = select("reservations", filters={"time": "19:00"}, order_by=None)

    assert len(matches) == 1
    assert matches[0]["time"] == "19:00"


def test_insert_assigns_id_in_memory():
    row = insert("reservations", {"date": "2099-01-01", "time": "19:00"})
    assert row.get("id")  # needed so rows can be updated in place


def test_update_modifies_row_by_id():
    row = insert("reservations", {"date": "2099-01-01", "time": "19:00", "party_size": 2})

    update("reservations", row["id"], {"time": "20:00", "party_size": 4})

    updated = select("reservations", filters={"id": row["id"]}, order_by=None)[0]
    assert updated["time"] == "20:00"
    assert updated["party_size"] == 4


def test_cancel_reservation_sets_status():
    from tools.reservation import cancel_reservation

    row = insert("reservations", {"date": "2099-01-01", "time": "19:00", "status": "pending"})
    cancel_reservation(row["id"])

    updated = select("reservations", filters={"id": row["id"]}, order_by=None)[0]
    assert updated["status"] == "cancelled"
