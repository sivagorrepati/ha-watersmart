"""Home Assistant WaterSmart integration."""

import aiohttp
from homeassistant.const import CONF_EMAIL, CONF_PASSWORD, CONF_URL, Platform
from homeassistant.helpers.aiohttp_client import async_create_clientsession

from .api import WaterSmartClient
from .const import CONF_ACCOUNT_NUMBER
from .coordinator import WaterSmartCoordinator

PLATFORMS = [Platform.SENSOR]


def create_client(hass, data) -> WaterSmartClient:
    """Use a separate cookie jar so different entries cannot share sessions."""
    session = async_create_clientsession(
        hass,
        cookie_jar=aiohttp.CookieJar(),
        timeout=aiohttp.ClientTimeout(total=60),
    )
    return WaterSmartClient(
        session, data[CONF_URL], data[CONF_EMAIL], data[CONF_PASSWORD]
    )


async def async_setup_entry(hass, entry) -> bool:
    client = create_client(hass, entry.data)
    # Verify the configured account on every new login.
    client.account_number = entry.data[CONF_ACCOUNT_NUMBER]
    coordinator = WaterSmartCoordinator(hass, entry, client)
    try:
        await coordinator.async_config_entry_first_refresh()
        entry.runtime_data = coordinator
        await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    except Exception:
        await client.session.close()
        raise
    return True


async def async_unload_entry(hass, entry) -> bool:
    unloaded = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
    if unloaded:
        await entry.runtime_data.client.session.close()
    return unloaded


async def async_remove_entry(hass, entry) -> None:
    """Remove the local cache when the entry is deleted."""
    from homeassistant.helpers.storage import Store

    from .const import DOMAIN, STORAGE_VERSION

    await Store(
        hass, STORAGE_VERSION, f"{DOMAIN}.{entry.entry_id}.hourly"
    ).async_remove()
