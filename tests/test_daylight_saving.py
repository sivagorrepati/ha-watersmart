"""Exercise HAR transition patterns using synthetic, account-free readings."""

from datetime import UTC, datetime
from zoneinfo import ZoneInfo

import pytest

from custom_components.watersmart.api import parse_chart
from custom_components.watersmart.history import (
    localize_history,
    merge_history,
    statistics_rows,
)

TIMEZONE = ZoneInfo("America/Los_Angeles")


@pytest.mark.parametrize("day", ["2025-03-09", "2026-03-08"])
def test_har_spring_forward_skips_two_am_without_missing_reading(day):
    start = int(datetime.fromisoformat(day).replace(tzinfo=UTC).timestamp())
    # Both captured spring transitions omit 02:00 without a missing-data marker.
    payload = {
        "data": {
            "series": [
                {"read_datetime": start + hour * 3600, "gallons": float(hour + 1)}
                for hour in range(24)
                if hour != 2
            ],
            "missing": [],
        }
    }
    raw = parse_chart(payload)
    converted = localize_history(raw, TIMEZONE)
    assert len(raw) == len(converted) == 23
    assert [datetime.fromtimestamp(t, TIMEZONE).hour for t in converted] == [
        hour for hour in range(24) if hour != 2
    ]
    assert all(
        datetime.fromtimestamp(t, TIMEZONE).date().isoformat() == day for t in converted
    )
    instants = list(converted)
    assert all(b - a == 3600 for a, b in zip(instants, instants[1:]))
    rows = statistics_rows(converted, min(converted))
    assert len(rows) == 23
    assert rows[0]["start"] == datetime.fromtimestamp(start + 8 * 3600, UTC)
    assert rows[-1]["sum"] == sum(r["gallons"] for r in payload["data"]["series"])
    replay, changed = merge_history(
        converted, localize_history(parse_chart(payload), TIMEZONE)
    )
    assert replay == converted
    assert changed is None


@pytest.mark.parametrize(
    "first,second",
    [(0.0, 0.0), (2.0, 3.0)],
    ids=["har-zero-volumes", "nonzero-volumes"],
)
def test_har_fall_back_combines_both_one_am_readings(first, second):
    start = int(datetime(2025, 11, 2, tzinfo=UTC).timestamp())
    # The capture repeats 01:00 with identical timestamps and no offset flags.
    # Midnight is marked missing, leaving 24 actual rows on a 25-hour day.
    payload = {
        "data": {
            "series": [
                {"read_datetime": start + 3600, "gallons": first, "flags": None},
                {"read_datetime": start + 3600, "gallons": second, "flags": None},
                *[
                    {
                        "read_datetime": start + hour * 3600,
                        "gallons": 1.0,
                        "flags": None,
                    }
                    for hour in range(2, 24)
                ],
            ],
            "missing": [{"read_datetime": start, "value": 1}],
        }
    }
    converted = localize_history(parse_chart(payload), TIMEZONE)
    first_one_am = int(datetime(2025, 11, 2, 8, tzinfo=UTC).timestamp())
    second_one_am = first_one_am + 3600
    assert first_one_am - 3600 not in converted  # Missing midnight stays unknown.
    assert converted[first_one_am] == first + second
    assert second_one_am not in converted
    assert len(converted) == 23
    assert datetime.fromtimestamp(first_one_am, TIMEZONE).fold == 0
    assert datetime.fromtimestamp(second_one_am, TIMEZONE).fold == 1
    assert sum(converted.values()) == first + second + 22
    rows = statistics_rows(converted, min(converted))
    assert rows[-1]["sum"] == first + second + 22
    replay, changed = merge_history(
        converted, localize_history(parse_chart(payload), TIMEZONE)
    )
    assert replay == converted
    assert changed is None


def test_corrected_repeated_hour_replaces_previous_total():
    timestamp = int(datetime(2025, 11, 2, 1, tzinfo=UTC).timestamp())
    later = timestamp + 3600
    original = {
        "data": {
            "series": [
                {"read_datetime": timestamp, "gallons": 2},
                {"read_datetime": timestamp, "gallons": 3},
                {"read_datetime": later, "gallons": 4},
            ]
        }
    }
    corrected = {
        "data": {
            "series": [
                {"read_datetime": timestamp, "gallons": 2},
                {"read_datetime": timestamp, "gallons": 5},
                {"read_datetime": later, "gallons": 4},
            ]
        }
    }
    history = localize_history(parse_chart(original), TIMEZONE)
    merged, changed = merge_history(
        history, localize_history(parse_chart(corrected), TIMEZONE)
    )
    assert sum(history.values()) == 9
    assert sum(merged.values()) == 11
    assert changed == min(merged)
    assert [r["sum"] for r in statistics_rows(merged, changed)] == [7, 11]
