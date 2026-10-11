"""Latest completed hourly volume, with the requested entity naming convention."""

from datetime import UTC, datetime

from homeassistant.components.sensor import SensorDeviceClass, SensorEntity
from homeassistant.const import UnitOfVolume
from homeassistant.helpers.update_coordinator import CoordinatorEntity
from homeassistant.util import slugify

from .const import DOMAIN, NAME

PARALLEL_UPDATES = 0


async def async_setup_entry(hass, entry, async_add_entities) -> None:
    async_add_entities([WaterSmartHourlySensor(entry.runtime_data)])


class WaterSmartHourlySensor(CoordinatorEntity, SensorEntity):
    """Report one hourly interval, never a cumulative meter reading."""

    _attr_device_class = SensorDeviceClass.WATER
    _attr_native_unit_of_measurement = UnitOfVolume.GALLONS
    _attr_icon = "mdi:water"

    def __init__(self, coordinator) -> None:
        super().__init__(coordinator)
        account = coordinator.account_number
        object_id = f"{DOMAIN}_{slugify(account)}_water_usage_hourly"
        self._attr_unique_id = f"{coordinator.client.url}_{account}_water_usage_hourly"
        self._attr_name = f"{NAME} {account} water usage hourly"
        self.entity_id = f"sensor.{object_id}"
        self._attr_device_info = {
            "identifiers": {(DOMAIN, f"{coordinator.client.url}_{account}")},
            "name": f"{NAME} {account}",
            "manufacturer": "WaterSmart",
        }

    @property
    def native_value(self) -> float | None:
        history = self.coordinator.data
        return history[max(history)] if history else None

    @property
    def extra_state_attributes(self) -> dict:
        history = self.coordinator.data or {}
        return {
            "account_number": self.coordinator.account_number,
            "reading_start": (
                datetime.fromtimestamp(max(history), UTC).isoformat()
                if history
                else None
            ),
            "last_download": self.coordinator.last_download,
            "cached_hours": len(history),
            "historical_statistic_id": self.coordinator.statistic_id,
        }
