"""Time-zone choices and demo fallbacks."""
from __future__ import annotations
from datetime import timedelta, timezone
from typing import List, Tuple
try:
    from zoneinfo import ZoneInfo, ZoneInfoNotFoundError
except Exception:
    from backports.zoneinfo import ZoneInfo, ZoneInfoNotFoundError  # type: ignore
from .errors import TimezoneError

FALLBACK_TIMEZONES = {
    "UTC": timezone.utc,
    "America/Los_Angeles": timezone(timedelta(hours=-8)),
    "America/Vancouver": timezone(timedelta(hours=-8)),
    "America/Denver": timezone(timedelta(hours=-7)),
    "America/Edmonton": timezone(timedelta(hours=-7)),
    "America/Phoenix": timezone(timedelta(hours=-7)),
    "America/Chicago": timezone(timedelta(hours=-6)),
    "America/Winnipeg": timezone(timedelta(hours=-6)),
    "America/New_York": timezone(timedelta(hours=-5)),
    "America/Toronto": timezone(timedelta(hours=-5)),
    "America/Halifax": timezone(timedelta(hours=-4)),
    "America/Puerto_Rico": timezone(timedelta(hours=-4)),
}

TIMEZONE_CHOICES: List[Tuple[str, str]] = [
    ("Pacific - Los Angeles", "America/Los_Angeles"),
    ("Pacific - Vancouver", "America/Vancouver"),
    ("Mountain - Denver", "America/Denver"),
    ("Mountain - Edmonton", "America/Edmonton"),
    ("Mountain - Phoenix", "America/Phoenix"),
    ("Central - Chicago", "America/Chicago"),
    ("Central - Winnipeg", "America/Winnipeg"),
    ("Eastern - New York", "America/New_York"),
    ("Eastern - Toronto", "America/Toronto"),
    ("Atlantic - Halifax", "America/Halifax"),
    ("Atlantic - Puerto Rico", "America/Puerto_Rico"),
]

def get_timezone(key: str):
    try:
        return ZoneInfo(key)
    except ZoneInfoNotFoundError:
        if key in FALLBACK_TIMEZONES:
            return FALLBACK_TIMEZONES[key]
        raise TimezoneError(f"No time zone found with key {key}. Install the 'tzdata' package for full coverage.") from None

UTC = get_timezone("UTC")
