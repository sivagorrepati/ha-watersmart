"""Pure helpers for persistent history and corrected historical statistics."""

from datetime import UTC, datetime


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
    for timestamp, gallons in sorted(history.items()):
        total += gallons
        if timestamp >= since:
            result.append(
                {
                    "start": datetime.fromtimestamp(timestamp, UTC),
                    "state": total,
                    "sum": total,
                }
            )
    return result
