from __future__ import annotations

from datetime import UTC, datetime
from email.utils import parsedate_to_datetime


class TimestampError(ValueError):
    pass


def parse_feed_timestamp(original: str) -> datetime:
    if not original or not original.strip():
        raise TimestampError("missing publication timestamp")
    text = original.strip()
    try:
        value = parsedate_to_datetime(text)
    except (TypeError, ValueError, IndexError):
        try:
            value = datetime.fromisoformat(text)
        except ValueError as exc:
            raise TimestampError(f"invalid publication timestamp: {original!r}") from exc
    if value.tzinfo is None or value.utcoffset() is None:
        raise TimestampError("publication timestamp requires an explicit timezone")
    return value.astimezone(UTC)


def format_utc(value: datetime) -> str:
    if value.tzinfo is None:
        raise TimestampError("naive datetime")
    return value.astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%S.%fZ")


def now_utc() -> datetime:
    return datetime.now(UTC)
