"""Check replay, late arrival, corrections and rolling windows."""

from datetime import UTC, datetime
from zoneinfo import ZoneInfo

from custom_components.watersmart.history import (
    local_hour,
    localize_history,
    merge_history,
    statistics_rows,
)


def test_repeated_download_is_idempotent():
    history = {3600: 1.0, 7200: 2.0}
    merged, changed = merge_history(history, history)
    assert merged == history
    assert changed is None


def test_rolling_window_retains_old_hours():
    merged, changed = merge_history({3600: 1, 7200: 2}, {7200: 2, 10800: 3})
    assert merged == {3600: 1, 7200: 2, 10800: 3}
    assert changed == 10800


def test_late_and_corrected_hours_recompute_later_sums():
    merged, changed = merge_history({3600: 1, 10800: 3}, {3600: 2, 7200: 4})
    assert changed == 3600
    assert [r["sum"] for r in statistics_rows(merged, changed)] == [2, 6, 9]
    assert [r["sum"] for r in statistics_rows(merged, 7200)] == [6, 9]


def test_zero_is_valid_new_reading():
    merged, changed = merge_history({}, {3600: 0})
    assert changed == 3600
    assert statistics_rows(merged, changed)[0]["sum"] == 0


def test_encoded_local_hours_use_seasonal_offset():
    timezone = ZoneInfo("America/Los_Angeles")
    for month, expected_hour in [(1, 8), (7, 7)]:
        raw = int(datetime(2026, month, 1, tzinfo=UTC).timestamp())
        actual = local_hour(raw, timezone)
        assert datetime.fromtimestamp(actual, UTC) == datetime(
            2026, month, 1, expected_hour, tzinfo=UTC
        )
        assert datetime.fromtimestamp(actual, timezone).hour == 0


def test_nonexistent_spring_hour_preserves_volume():
    raw = {
        int(datetime(2026, 3, 8, hour, tzinfo=UTC).timestamp()): float(hour)
        for hour in (1, 2, 3, 4)
    }
    converted = localize_history(raw, ZoneInfo("America/Los_Angeles"))
    assert list(converted.values()) == [1, 5, 4]
    assert sum(converted.values()) == sum(raw.values())
    assert [datetime.fromtimestamp(t, UTC).hour for t in converted] == [9, 10, 11]


def test_ambiguous_fall_hour_uses_first_occurrence():
    raw = int(datetime(2026, 11, 1, 1, tzinfo=UTC).timestamp())
    actual = local_hour(raw, ZoneInfo("America/Los_Angeles"))
    assert datetime.fromtimestamp(actual, UTC) == datetime(2026, 11, 1, 8, tzinfo=UTC)


def test_fractional_timezone_statistics_align_to_utc_hours():
    raw = int(datetime(2026, 1, 1, tzinfo=UTC).timestamp())
    converted = localize_history({raw: 2}, ZoneInfo("Asia/Kolkata"))
    assert datetime.fromtimestamp(min(converted), UTC) == datetime(
        2025, 12, 31, 18, 30, tzinfo=UTC
    )
    rows = statistics_rows(converted, min(converted))
    assert rows[0]["start"] == datetime(2025, 12, 31, 18, tzinfo=UTC)
    assert rows[0]["sum"] == 2
