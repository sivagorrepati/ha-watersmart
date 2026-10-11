"""Poll WaterSmart every 30 minutes and persist validated hourly data."""

import logging
from datetime import UTC, datetime
from zoneinfo import ZoneInfo

from homeassistant.components.recorder.models import StatisticMeanType
from homeassistant.components.recorder.statistics import async_add_external_statistics
from homeassistant.exceptions import ConfigEntryAuthFailed
from homeassistant.helpers.storage import Store
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed
from homeassistant.util import slugify

from .api import AccountMismatchError, AuthenticationError, WaterSmartError
from .const import CONF_ACCOUNT_NUMBER, DOMAIN, NAME, STORAGE_VERSION, UPDATE_INTERVAL
from .history import local_hour, localize_history, merge_history, statistics_rows

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
        self.raw_history: dict[int, float] = {}
        self.last_download: str | None = None
        self._reimport = True
        self._preserve_through: int | None = None
        self._preserve_raw_through: int | None = None
        self.timezone = ZoneInfo(hass.config.time_zone)

    async def _async_setup(self) -> None:
        cached = await self.store.async_load()
        if cached and cached.get("account_number") == self.account_number:
            # Retain stored timestamps exactly; existing history is not migrated.
            self.history = {int(t): float(v) for t, v in cached["hours"].items()}
            self.raw_history = {
                int(t): float(v) for t, v in cached.get("raw_hours", {}).items()
            }
            self._preserve_through = cached.get(
                "preserve_history_through", max(self.history, default=None)
            )
            self._preserve_raw_through = cached.get("preserve_raw_through")
            timezone_changed = (
                cached.get("timezone") is not None
                and cached["timezone"] != self.timezone.key
            )
            if timezone_changed and self.history:
                self._preserve_through = max(self.history)
            if self.history and (
                "preserve_raw_through" not in cached or timezone_changed
            ):
                if cached.get("timestamp_mode") == "local_wall_time":
                    # Use the timezone recorded when this cache was created.
                    old_timezone = ZoneInfo(cached.get("timezone", self.timezone.key))
                    last_local = datetime.fromtimestamp(max(self.history), old_timezone)
                    self._preserve_raw_through = int(
                        last_local.replace(tzinfo=UTC).timestamp()
                    )
                else:
                    self._preserve_raw_through = max(self.history)
            self._reimport = not bool(self.history)
            self.last_download = cached.get("last_download")

    async def _async_update_data(self) -> dict[int, float]:
        try:
            downloaded = await self.client.fetch_hourly()
        except (AuthenticationError, AccountMismatchError) as err:
            raise ConfigEntryAuthFailed(str(err)) from err
        except WaterSmartError as err:
            raise UpdateFailed(str(err)) from err
        # Incomplete/current hours are not final usage values.
        cutoff = int(datetime.now(UTC).timestamp()) - 3600
        raw, _ = merge_history(self.raw_history, downloaded)
        raw = {
            t: v
            for t, v in raw.items()
            if local_hour(t, self.timezone) <= cutoff
            and (self._preserve_raw_through is None or t > self._preserve_raw_through)
        }
        converted = await self.hass.async_add_executor_job(
            localize_history, raw, self.timezone
        )
        converted = {
            t: v
            for t, v in converted.items()
            if self._preserve_through is None or t > self._preserve_through
        }
        merged, changed = merge_history(self.history, converted)
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
                    "name": f"{NAME} {self.account_number} hourly water usage",
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
                "raw_hours": {str(t): v for t, v in raw.items()},
                "timestamp_mode": "local_wall_time",
                "timezone": self.timezone.key,
                "preserve_history_through": self._preserve_through,
                "preserve_raw_through": self._preserve_raw_through,
                "last_download": last_download,
                "last_hour": max(merged),
            }
        )
        self.history = merged
        self.raw_history = raw
        self.last_download = last_download
        self._reimport = False
        return merged
