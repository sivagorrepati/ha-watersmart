"""Check replay, late arrival, corrections and rolling windows."""

from custom_components.watersmart.history import merge_history, statistics_rows


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
