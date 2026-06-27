from __future__ import annotations

from datetime import date, datetime
from functools import lru_cache
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from config import settings


@lru_cache(maxsize=8)
def _zone(name: str) -> ZoneInfo:
    try:
        return ZoneInfo(name)
    except (ZoneInfoNotFoundError, ValueError):
        return ZoneInfo("UTC")


def tz() -> ZoneInfo:
    return _zone(settings.timezone)


def now() -> datetime:
    return datetime.now(tz())


def today() -> date:
    return now().date()


def now_iso() -> str:
    return now().isoformat()
