"""Pure helpers for persistent history and corrected historical statistics."""

from datetime import UTC, datetime
from zoneinfo import ZoneInfo


def local_hour(timestamp: int, timezone: ZoneInfo) -> int:
    """Interpret epoch-encoded calendar fields as local wall time, then UTC."""
    wall_time = datetime.fromtimestamp(timestamp, UTC).replace(tzinfo=timezone, fold=0)
    return int(wall_time.timestamp())


def localize_history(history: dict[int, float], timezone: ZoneInfo) -> dict[int, float]:
    """Preserve volume when a nonexistent spring hour maps onto the next hour."""
    result: dict[int, float] = {}
    for timestamp, gallons in sorted(history.items()):
        actual = local_hour(timestamp, timezone)
        result[actual] = result.get(actual, 0.0) + gallons
    return dict(sorted(result.items()))


def merge_history(
    previous: dict[int, float], downloaded: dict[int, float]
) -> tuple[dict[int, float], int | None]:
    """Retain older hours and identify the first new or corrected reading."""
    changed = [t for t, value in downloaded.items() if previous.get(t) != value]
    return dict(sorted((previous | downloaded).items())), min(changed, default=None)


def statistics_rows(history: dict[int, float], since: int) -> list[dict]:
    """Recompute sums after corrections, never counting an hour twice."""
    total = 0.0
    result = []
    buckets: dict[int, float] = {}
    for timestamp, gallons in history.items():
        bucket = timestamp // 3600 * 3600
        buckets[bucket] = buckets.get(bucket, 0.0) + gallons
    for timestamp, gallons in sorted(buckets.items()):
        total += gallons
        if timestamp >= since // 3600 * 3600:
            result.append(
                {
                    "start": datetime.fromtimestamp(timestamp, UTC),
                    "state": total,
                    "sum": total,
                }
            )
    return result
