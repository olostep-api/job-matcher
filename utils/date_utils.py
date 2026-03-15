from __future__ import annotations

from datetime import datetime, timezone
from typing import Optional


DATE_FORMATS = (
    "%Y-%m-%d",
    "%Y/%m/%d",
    "%d-%m-%Y",
    "%Y-%m-%dT%H:%M:%S",
    "%Y-%m-%dT%H:%M:%SZ",
)


def parse_date_safe(value: str | None) -> Optional[datetime]:
    if not value:
        return None

    raw = value.strip()
    if not raw:
        return None

    for fmt in DATE_FORMATS:
        try:
            dt = datetime.strptime(raw, fmt)
            return dt.replace(tzinfo=timezone.utc)
        except ValueError:
            continue

    try:
        normalized = raw.replace("Z", "+00:00")
        dt = datetime.fromisoformat(normalized)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt
    except ValueError:
        return None


def days_since(posted_at: datetime | None) -> int:
    if posted_at is None:
        return 365
    now = datetime.now(timezone.utc)
    delta = now - posted_at
    return max(delta.days, 0)
