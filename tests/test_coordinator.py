"""Verify cache restoration, historical correction and failure behavior."""

from datetime import UTC, datetime
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock, patch

import pytest
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ConfigEntryAuthFailed
from homeassistant.helpers.update_coordinator import UpdateFailed

from custom_components.watersmart.api import AuthenticationError, WaterSmartError
from custom_components.watersmart.coordinator import WaterSmartCoordinator
from custom_components.watersmart.sensor import WaterSmartHourlySensor


@pytest.fixture
async def coordinator(tmp_path):
    hass = HomeAssistant(str(tmp_path))
    entry = SimpleNamespace(
        entry_id="test_entry",
        data={"account_number": "0012345"},
        async_on_unload=Mock(),
    )
    client = SimpleNamespace(
        url="https://milpitas.watersmart.com",
        fetch_hourly=AsyncMock(return_value={3600: 2.0, 7200: 3.0}),
    )
    with patch("homeassistant.helpers.frame.report_usage"):
        result = WaterSmartCoordinator(hass, entry, client)
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
        "custom_components.watersmart.coordinator.async_add_external_statistics"
    ) as add:
        coordinator.data = await coordinator._async_update_data()
    assert coordinator.history == {0: 1.0, 3600: 2.0, 7200: 3.0}
    assert [r["sum"] for r in add.call_args.args[2]] == [1, 3, 6]
    cached = coordinator.store.async_save.call_args.args[0]
    assert cached["last_hour"] == 7200
    assert cached["hours"]["0"] == 1.0
    assert coordinator.update_interval.total_seconds() == 1800
    sensor = WaterSmartHourlySensor(coordinator)
    assert sensor.entity_id == "sensor.watersmart_0012345_water_usage_hourly"
    assert sensor.native_value == 3.0
    assert sensor.extra_state_attributes["reading_start"] == "1970-01-01T02:00:00+00:00"
    assert sensor.state_class is None


async def test_unchanged_poll_does_not_duplicate_statistics(coordinator):
    with patch(
        "custom_components.watersmart.coordinator.async_add_external_statistics"
    ) as add:
        await coordinator._async_update_data()
        await coordinator._async_update_data()
    assert add.call_count == 1
    assert coordinator.store.async_save.await_count == 2


async def test_correction_reimports_affected_tail(coordinator):
    with patch(
        "custom_components.watersmart.coordinator.async_add_external_statistics"
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
        "custom_components.watersmart.coordinator.async_add_external_statistics"
    ):
        data = await coordinator._async_update_data()
    assert data == {current_hour - 3600: 4.0}
