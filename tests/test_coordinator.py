"""Verify cache restoration, historical correction and failure behavior."""

import asyncio
from datetime import UTC, datetime
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock, patch
from zoneinfo import ZoneInfo

import pytest
from homeassistant.config_entries import ConfigEntryState
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ConfigEntryAuthFailed
from homeassistant.helpers.update_coordinator import UpdateFailed

from custom_components.ha_watersmart.api import (
    AuthenticationError,
    WaterSmartError,
    parse_chart,
)
from custom_components.ha_watersmart.coordinator import WaterSmartCoordinator
from custom_components.ha_watersmart.sensor import WaterSmartHourlySensor


@pytest.fixture
async def coordinator(tmp_path):
    hass = HomeAssistant(str(tmp_path))
    entry = SimpleNamespace(
        entry_id="test_entry",
        data={"account_number": "0012345"},
        async_on_unload=Mock(),
        state=ConfigEntryState.SETUP_IN_PROGRESS,
    )
    client = SimpleNamespace(
        url="https://milpitas.watersmart.com",
        fetch_hourly=AsyncMock(return_value={3600: 2.0, 7200: 3.0}),
    )
    with patch("homeassistant.helpers.frame.report_usage"):
        result = WaterSmartCoordinator(hass, entry, client)
    assert result.store.key == "ha_watersmart.test_entry.hourly"
    result.store = SimpleNamespace(
        async_load=AsyncMock(return_value=None), async_save=AsyncMock()
    )
    return result


async def test_cache_restart_and_sensor_naming(coordinator):
    coordinator.store.async_load.return_value = {
        "account_number": "0012345",
        "hours": {"0": 1.0},
        "last_download": "2026-01-01T00:00:00+00:00",
    }
    await coordinator._async_setup()
    with patch(
        "custom_components.ha_watersmart.coordinator.async_add_external_statistics"
    ) as add:
        coordinator.data = await coordinator._async_update_data()
    assert coordinator.history == {0: 1.0, 3600: 2.0, 7200: 3.0}
    assert [r["sum"] for r in add.call_args.args[2]] == [3, 6]
    cached = coordinator.store.async_save.call_args.args[0]
    assert cached["last_hour"] == 7200
    assert cached["hours"]["0"] == 1.0
    assert coordinator.update_interval.total_seconds() == 1800
    sensor = WaterSmartHourlySensor(coordinator)
    assert sensor.entity_id == "sensor.ha_watersmart_0012345_water_usage_hourly"
    assert sensor.name == "HA WaterSmart 0012345 water usage hourly"
    assert sensor.device_info["identifiers"] == {
        ("ha_watersmart", "https://milpitas.watersmart.com_0012345")
    }
    assert coordinator.statistic_id == "ha_watersmart:0012345_water_usage_hourly"
    assert add.call_args.args[1]["source"] == "ha_watersmart"
    assert add.call_args.args[1]["name"] == "HA WaterSmart 0012345 hourly water usage"
    assert sensor.native_value == 3.0
    assert sensor.extra_state_attributes["reading_start"] == "1970-01-01T02:00:00+00:00"
    assert sensor.state_class is None


async def test_unchanged_poll_does_not_duplicate_statistics(coordinator):
    with patch(
        "custom_components.ha_watersmart.coordinator.async_add_external_statistics"
    ) as add:
        await coordinator._async_update_data()
        await coordinator._async_update_data()
    assert add.call_count == 1
    assert coordinator.store.async_save.await_count == 2


async def test_correction_reimports_affected_tail(coordinator):
    with patch(
        "custom_components.ha_watersmart.coordinator.async_add_external_statistics"
    ) as add:
        await coordinator._async_update_data()
        coordinator.client.fetch_hourly.return_value = {3600: 4.0}
        await coordinator._async_update_data()
    assert coordinator.history == {3600: 4.0, 7200: 3.0}
    assert [r["sum"] for r in add.call_args.args[2]] == [4.0, 7.0]


@pytest.mark.parametrize(
    "error,expected",
    [
        (AuthenticationError("expired"), ConfigEntryAuthFailed),
        (WaterSmartError("outage"), UpdateFailed),
    ],
)
async def test_failures_do_not_overwrite_cache(coordinator, error, expected):
    coordinator.history = {3600: 8.0}
    coordinator.client.fetch_hourly.side_effect = error
    with pytest.raises(expected):
        await coordinator._async_update_data()
    assert coordinator.history == {3600: 8.0}
    coordinator.store.async_save.assert_not_awaited()


async def test_cache_for_other_account_is_ignored(coordinator):
    coordinator.store.async_load.return_value = {
        "account_number": "different",
        "hours": {"3600": 99},
    }
    await coordinator._async_setup()
    assert coordinator.history == {}


async def test_current_hour_not_published_as_final(coordinator):
    current_hour = int(datetime.now(UTC).timestamp()) // 3600 * 3600
    coordinator.client.fetch_hourly.return_value = {
        current_hour - 3600: 4.0,
        current_hour: 1.0,
    }
    with patch(
        "custom_components.ha_watersmart.coordinator.async_add_external_statistics"
    ):
        data = await coordinator._async_update_data()
    assert data == {current_hour - 3600: 4.0}


async def test_legacy_cache_preserved_and_only_new_readings_imported(coordinator):
    coordinator.timezone = ZoneInfo("America/Los_Angeles")
    raw = int(datetime(2026, 7, 1, tzinfo=UTC).timestamp())
    coordinator.store.async_load.return_value = {
        "account_number": "0012345",
        "hours": {str(raw): 2.0},
        "last_download": "2026-07-02T00:00:00+00:00",
    }
    coordinator.client.fetch_hourly.return_value = {raw: 99, raw + 3600: 3}
    await coordinator._async_setup()
    assert coordinator.history == {raw: 2}
    assert coordinator.last_download == "2026-07-02T00:00:00+00:00"
    with patch(
        "custom_components.ha_watersmart.coordinator.async_add_external_statistics"
    ) as add:
        coordinator.data = await coordinator._async_update_data()
        assert coordinator.history == {raw: 2, raw + 8 * 3600: 3}
        rows = add.call_args.args[2]
        assert len(rows) == 1
        assert rows[0]["start"] == datetime(2026, 7, 1, 8, tzinfo=UTC)
        assert rows[0]["sum"] == 5
        await coordinator._async_update_data()
        assert add.call_count == 1
        # The preservation boundary survives restart and permits future corrections.
        cached = coordinator.store.async_save.call_args.args[0]
        coordinator.store.async_load.return_value = cached
        await coordinator._async_setup()
        coordinator.client.fetch_hourly.return_value = {raw: 100, raw + 3600: 4}
        await coordinator._async_update_data()
        assert coordinator.history == {raw: 2, raw + 8 * 3600: 4}
        assert add.call_args.args[2][0]["sum"] == 6
    cached = coordinator.store.async_save.call_args.args[0]
    assert cached["raw_hours"] == {str(raw + 3600): 4}
    assert cached["preserve_history_through"] == raw
    assert cached["preserve_raw_through"] == raw
    assert cached["timezone"] == "America/Los_Angeles"


async def test_local_cache_is_not_converted_twice(coordinator):
    coordinator.timezone = ZoneInfo("America/Los_Angeles")
    raw = int(datetime(2026, 1, 1, tzinfo=UTC).timestamp())
    coordinator.store.async_load.return_value = {
        "account_number": "0012345",
        "raw_hours": {str(raw): 2},
        "hours": {str(raw + 8 * 3600): 2},
        "timestamp_mode": "local_wall_time",
        "timezone": "America/Los_Angeles",
    }
    await coordinator._async_setup()
    assert coordinator.history == {raw + 8 * 3600: 2}
    assert coordinator._preserve_through == raw + 8 * 3600


@pytest.mark.parametrize("saved_boundary", [False, True])
async def test_timezone_change_preserves_existing_cache(coordinator, saved_boundary):
    coordinator.timezone = ZoneInfo("America/New_York")
    raw = int(datetime(2026, 1, 1, tzinfo=UTC).timestamp())
    coordinator.store.async_load.return_value = {
        "account_number": "0012345",
        "raw_hours": {str(raw): 2},
        "hours": {str(raw + 8 * 3600): 2},
        "timestamp_mode": "local_wall_time",
        "timezone": "America/Los_Angeles",
    }
    if saved_boundary:
        coordinator.store.async_load.return_value.update(
            preserve_history_through=None, preserve_raw_through=None
        )
    await coordinator._async_setup()
    assert coordinator.history == {raw + 8 * 3600: 2}
    assert coordinator._preserve_raw_through == raw
    coordinator.client.fetch_hourly.return_value = {raw: 99, raw + 4 * 3600: 3}
    with patch(
        "custom_components.ha_watersmart.coordinator.async_add_external_statistics"
    ) as add:
        await coordinator._async_update_data()
    assert coordinator.history == {raw + 8 * 3600: 2, raw + 9 * 3600: 3}
    assert len(add.call_args.args[2]) == 1


async def test_current_local_hour_not_published(coordinator):
    coordinator.timezone = ZoneInfo("America/Los_Angeles")
    now = datetime.now(coordinator.timezone).replace(minute=0, second=0, microsecond=0)
    raw = int(now.replace(tzinfo=UTC).timestamp())
    coordinator.client.fetch_hourly.return_value = {raw - 3600: 4, raw: 1}
    with patch(
        "custom_components.ha_watersmart.coordinator.async_add_external_statistics"
    ):
        data = await coordinator._async_update_data()
    assert data == {int(now.timestamp()) - 3600: 4}


async def test_fractional_timezone_waits_for_full_hour(coordinator):
    coordinator.timezone = ZoneInfo("Asia/Kolkata")
    now = datetime(2026, 1, 1, 0, 45, tzinfo=coordinator.timezone)
    raw = int(datetime(2026, 1, 1, tzinfo=UTC).timestamp())
    coordinator.client.fetch_hourly.return_value = {raw - 3600: 4, raw: 1}
    with (
        patch("custom_components.ha_watersmart.coordinator.datetime") as clock,
        patch(
            "custom_components.ha_watersmart.coordinator.async_add_external_statistics"
        ),
    ):
        clock.now.return_value = now.astimezone(UTC)
        data = await coordinator._async_update_data()
    assert data == {int(now.replace(minute=0).timestamp()) - 3600: 4}


async def test_setup_preserves_existing_data_without_waiting_for_recorder(coordinator):
    coordinator.store.async_load.return_value = {
        "account_number": "0012345",
        "hours": {"3600": 2.0},
        "statistics_rebuild_pending": True,
    }
    coordinator.client.fetch_hourly.return_value = {3600: 99}
    future = coordinator.hass.loop.create_future()
    recorder = Mock(
        async_block_till_done=AsyncMock(side_effect=lambda: future),
        async_get_commit_future=Mock(return_value=future),
    )
    with (
        patch(
            "homeassistant.components.recorder.get_instance", return_value=recorder
        ) as get,
        patch(
            "custom_components.ha_watersmart.coordinator.async_add_external_statistics"
        ) as add,
    ):
        await asyncio.wait_for(
            coordinator.async_config_entry_first_refresh(), timeout=1
        )
        assert coordinator.last_update_success
        assert coordinator.data == {3600: 2}
        assert not future.done()
        get.assert_not_called()
        add.assert_not_called()
        cached = coordinator.store.async_save.call_args.args[0]
        assert "statistics_rebuild_pending" not in cached
        assert cached["hours"] == {"3600": 2}


async def test_repeated_hour_total_survives_polling_and_restart(coordinator):
    coordinator.timezone = ZoneInfo("America/Los_Angeles")
    raw = int(datetime(2025, 11, 2, 1, tzinfo=UTC).timestamp())
    actual = raw + 7 * 3600
    coordinator.client.fetch_hourly.return_value = parse_chart(
        {
            "data": {
                "series": [
                    {"read_datetime": raw, "gallons": 2},
                    {"read_datetime": raw, "gallons": 3},
                ]
            }
        }
    )
    with patch(
        "custom_components.ha_watersmart.coordinator.async_add_external_statistics"
    ) as add:
        await coordinator._async_update_data()
        await coordinator._async_update_data()
        assert add.call_count == 1
        assert add.call_args.args[2][0]["sum"] == 5
        cached = coordinator.store.async_save.call_args.args[0]
        assert cached["raw_hours"] == {str(raw): 5}
        assert cached["hours"] == {str(actual): 5}
        coordinator.store.async_load.return_value = cached
        await coordinator._async_setup()
        await coordinator._async_update_data()
    assert coordinator.history == {actual: 5}
    assert coordinator.raw_history == {raw: 5}
