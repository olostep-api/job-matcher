from __future__ import annotations

from datetime import datetime, timezone


def days_since(posted_at: datetime | None) -> int:
    if posted_at is None:
        return 365
    now = datetime.now(timezone.utc)
    delta = now - posted_at
    return max(delta.days, 0)
