"""Tests for the per-slot availability logic — the core of the reservation flow."""
import pytest

from config import settings
from tools import availability
from tools.store import insert

FUTURE_DATE = "2099-01-01"


def _add_reservation(date: str, time: str, status: str = "pending") -> None:
    insert(
        "reservations",
        {"date": date, "time": time, "status": status,
         "name": "Test", "party_size": 2, "phone": "0"},
    )


def test_snap_to_slot_rounds_to_grid():
    assert availability.snap_to_slot("19:10") == "19:00"
    assert availability.snap_to_slot("19:20") == "19:30"


def test_snap_to_slot_clamps_into_hours():
    assert availability.snap_to_slot("08:00") == settings.opening_time
    assert availability.snap_to_slot("23:59") == availability.operating_slots()[-1]


def test_is_within_hours():
    assert availability.is_within_hours("19:00") is True
    assert availability.is_within_hours("09:00") is False  # before open
    assert availability.is_within_hours("23:00") is False  # after close
    with pytest.raises(ValueError):
        availability.is_within_hours("7pm")  # malformed -> caller asks again


def test_slot_count_only_counts_active_statuses():
    _add_reservation(FUTURE_DATE, "19:00", "pending")
    _add_reservation(FUTURE_DATE, "19:00", "confirmed")
    _add_reservation(FUTURE_DATE, "19:00", "cancelled")  # should not count
    assert availability.slot_count(FUTURE_DATE, "19:00") == 2


def test_is_available_respects_capacity(monkeypatch):
    monkeypatch.setattr(settings, "max_reservations_per_slot", 2)
    assert availability.is_available(FUTURE_DATE, "19:00") is True
    _add_reservation(FUTURE_DATE, "19:00")
    assert availability.is_available(FUTURE_DATE, "19:00") is True
    _add_reservation(FUTURE_DATE, "19:00")  # now at capacity
    assert availability.is_available(FUTURE_DATE, "19:00") is False


def test_nearby_open_slots_excludes_full_and_sorts_by_distance(monkeypatch):
    monkeypatch.setattr(settings, "max_reservations_per_slot", 1)
    _add_reservation(FUTURE_DATE, "19:00")  # fills the requested slot

    nearby = availability.nearby_open_slots(FUTURE_DATE, "19:00", limit=3)

    assert "19:00" not in nearby            # the full slot is excluded
    assert nearby[0] in {"18:30", "19:30"}  # closest neighbours first
    assert len(nearby) == 3


def test_format_time_12h():
    assert availability.format_time_12h("19:00") == "7:00 PM"
    assert availability.format_time_12h("00:30") == "12:30 AM"
    assert availability.format_time_12h("12:00") == "12:00 PM"
    assert availability.format_time_12h("11:00") == "11:00 AM"
