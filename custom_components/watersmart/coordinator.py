"""Poll WaterSmart every 30 minutes and persist validated hourly data."""

import logging
from datetime import UTC, datetime

from homeassistant.components.recorder.models import StatisticMeanType
from homeassistant.components.recorder.statistics import async_add_external_statistics
from homeassistant.exceptions import ConfigEntryAuthFailed
from homeassistant.helpers.storage import Store
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed
from homeassistant.util import slugify

from .api import AccountMismatchError, AuthenticationError, WaterSmartError
from .const import CONF_ACCOUNT_NUMBER, DOMAIN, STORAGE_VERSION, UPDATE_INTERVAL
from .history import merge_history, statistics_rows

_LOGGER = logging.getLogger(__name__)


class WaterSmartCoordinator(DataUpdateCoordinator[dict[int, float]]):
    """Share one history download between all entities."""

    def __init__(self, hass, entry, client) -> None:
        super().__init__(
            hass,
            _LOGGER,
            name=DOMAIN,
            config_entry=entry,
            update_interval=UPDATE_INTERVAL,
        )
        self.client = client
        self.account_number = entry.data[CONF_ACCOUNT_NUMBER]
        self.statistic_id = (
            f"{DOMAIN}:{slugify(self.account_number)}_water_usage_hourly"
        )
        self.store = Store(hass, STORAGE_VERSION, f"{DOMAIN}.{entry.entry_id}.hourly")
        self.history: dict[int, float] = {}
        self.last_download: str | None = None
        self._reimport = True

    async def _async_setup(self) -> None:
        cached = await self.store.async_load()
        if cached and cached.get("account_number") == self.account_number:
            self.history = {int(t): float(v) for t, v in cached["hours"].items()}
            self.last_download = cached.get("last_download")

    async def _async_update_data(self) -> dict[int, float]:
        try:
            downloaded = await self.client.fetch_hourly()
        except (AuthenticationError, AccountMismatchError) as err:
            raise ConfigEntryAuthFailed(str(err)) from err
        except WaterSmartError as err:
            raise UpdateFailed(str(err)) from err
        # Incomplete/current hours are not final usage values.
        cutoff = int(datetime.now(UTC).timestamp()) // 3600 * 3600
        downloaded = {t: v for t, v in downloaded.items() if t < cutoff}
        merged, changed = merge_history(self.history, downloaded)
        if not merged:
            raise UpdateFailed("No completed hourly readings are available")
        since = min(merged) if self._reimport else changed
        if since is not None:
            rows = await self.hass.async_add_executor_job(
                statistics_rows, merged, since
            )
            async_add_external_statistics(
                self.hass,
                {
                    "statistic_id": self.statistic_id,
                    "source": DOMAIN,
                    "name": f"WaterSmart {self.account_number} hourly water usage",
                    "unit_of_measurement": "gal",
                    "unit_class": "volume",
                    "mean_type": StatisticMeanType.NONE,
                    "has_sum": True,
                },
                rows,
            )
        last_download = datetime.now(UTC).isoformat()
        await self.store.async_save(
            {
                "account_number": self.account_number,
                "hours": {str(t): v for t, v in merged.items()},
                "last_download": last_download,
                "last_hour": max(merged),
            }
        )
        self.history = merged
        self.last_download = last_download
        self._reimport = False
        return merged
