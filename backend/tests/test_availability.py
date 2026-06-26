import pytest

from config import settings
from tools import availability
from tools.store import insert

FUTURE_DATE = "2099-01-01"


def _book(date: str, time: str, table_id: str, party_size: int = 2,
          status: str = "pending") -> dict:
    return insert(
        "reservations",
        {"date": date, "time": time, "table_id": table_id, "status": status,
         "name": "Test", "party_size": party_size, "phone": "0"},
    )


def test_snap_to_slot_rounds_to_grid():
    assert availability.snap_to_slot("19:10") == "19:00"
    assert availability.snap_to_slot("19:20") == "19:30"


def test_snap_to_slot_clamps_into_hours():
    assert availability.snap_to_slot("08:00") == settings.opening_time
    assert availability.snap_to_slot("23:59") == availability.operating_slots()[-1]


def test_is_within_hours():
    assert availability.is_within_hours("19:00") is True
    assert availability.is_within_hours("09:00") is False
    assert availability.is_within_hours("23:00") is False
    with pytest.raises(ValueError):
        availability.is_within_hours("7pm")


def test_slot_count_only_counts_active_statuses():
    _book(FUTURE_DATE, "19:00", "T1", status="pending")
    _book(FUTURE_DATE, "19:00", "T2", status="confirmed")
    _book(FUTURE_DATE, "19:00", "T3", status="cancelled")
    assert availability.slot_count(FUTURE_DATE, "19:00") == 2


def test_find_table_prefers_tightest_fit():
    assert availability.find_table(FUTURE_DATE, "19:00", 2) in {"T1", "T2"}


def test_find_table_uses_big_table_for_big_party():
    assert availability.find_table(FUTURE_DATE, "19:00", 6) == "T3"


def test_party_larger_than_biggest_table_gets_no_table():
    assert availability.find_table(FUTURE_DATE, "19:00", 9) is None
    assert availability.is_available(FUTURE_DATE, "19:00", 9) is False


def test_max_table_seats():
    assert availability.max_table_seats() == 8


def test_same_table_never_double_booked():
    _book(FUTURE_DATE, "19:00", "T1", 4)
    _book(FUTURE_DATE, "19:00", "T2", 4)
    _book(FUTURE_DATE, "19:00", "T3", 8)

    assert availability.is_available(FUTURE_DATE, "19:00", 2) is False
    assert availability.find_table(FUTURE_DATE, "19:00", 2) is None


def test_only_the_taken_table_is_blocked():
    _book(FUTURE_DATE, "19:00", "T1", 4)

    assert availability.find_table(FUTURE_DATE, "19:00", 4) == "T2"


def test_cancelled_reservation_frees_its_table():
    _book(FUTURE_DATE, "19:00", "T1", 4, status="cancelled")
    _book(FUTURE_DATE, "19:00", "T2", 4)

    assert availability.find_table(FUTURE_DATE, "19:00", 4) == "T1"


def test_seating_duration_blocks_overlapping_slot():
    for tid in ("T1", "T2", "T3"):
        _book(FUTURE_DATE, "19:00", tid, 4)
    assert availability.is_available(FUTURE_DATE, "19:30", 2) is False
    assert availability.is_available(FUTURE_DATE, "18:30", 2) is False

    assert availability.is_available(FUTURE_DATE, "20:30", 2) is True
    assert availability.is_available(FUTURE_DATE, "17:30", 2) is True


def test_exclude_id_lets_a_reservation_keep_its_table():
    row = _book(FUTURE_DATE, "19:00", "T3", party_size=6)

    assert availability.is_available(FUTURE_DATE, "19:00", 6) is False

    assert availability.is_available(FUTURE_DATE, "19:00", 6, exclude_id=row["id"]) is True


def test_nearby_open_slots_skip_blocked_window_and_sort_by_distance():
    for tid in ("T1", "T2", "T3"):
        _book(FUTURE_DATE, "19:00", tid, 4)

    nearby = availability.nearby_open_slots(FUTURE_DATE, "19:00", 2, limit=3)

    assert "19:00" not in nearby
    assert "19:30" not in nearby
    assert nearby[0] in {"17:30", "20:30"}
    assert len(nearby) == 3


def test_format_time_12h():
    assert availability.format_time_12h("19:00") == "7:00 PM"
    assert availability.format_time_12h("00:30") == "12:30 AM"
    assert availability.format_time_12h("12:00") == "12:00 PM"
    assert availability.format_time_12h("11:00") == "11:00 AM"


def test_within_edit_window():
    from datetime import datetime, timedelta, timezone

    recent = (datetime.now(timezone.utc) - timedelta(minutes=10)).isoformat()
    old = (datetime.now(timezone.utc) - timedelta(minutes=45)).isoformat()
    assert availability.within_edit_window(recent, 30) is True
    assert availability.within_edit_window(old, 30) is False
    assert availability.within_edit_window("", 30) is False
    assert availability.within_edit_window("not-a-date", 30) is False
