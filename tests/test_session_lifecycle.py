"""Exercise HA-created sessions and keep their shared connector alive."""

import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock, patch

import aiohttp
import pytest
from homeassistant.core import HomeAssistant

from custom_components.watersmart import (
    async_setup_entry,
    async_unload_entry,
    create_client,
)
from custom_components.watersmart.api import AuthenticationError, WaterSmartClient
from custom_components.watersmart.config_flow import WaterSmartConfigFlow

DATA = {
    "url": "https://milpitas.watersmart.com",
    "email": "test@example.com",
    "password": "test-password",
    "account_number": "0012345",
}


@pytest.fixture
async def sessions(tmp_path):
    hass = HomeAssistant(str(tmp_path))
    connector = aiohttp.TCPConnector()
    clients = []
    with patch(
        "homeassistant.helpers.aiohttp_client._async_get_connector",
        return_value=connector,
    ):

        def make_client(*args, **kwargs):
            client = create_client(*args, **kwargs)
            clients.append(client)
            return client

        yield hass, connector, clients, make_client
    for client in clients:
        client.session.detach()
    await connector.close()


async def test_sessions_have_isolated_cookies_and_shared_connector(sessions):
    hass, connector, _, make_client = sessions
    first = make_client(hass, DATA, auto_cleanup=False)
    second = make_client(hass, DATA, auto_cleanup=False)
    first.session.cookie_jar.update_cookies({"session": "first-account"})
    assert not list(second.session.cookie_jar)
    assert first.session.connector is second.session.connector is connector
    assert first.session.connector_owner is False
    first.session.detach()
    assert first.session.closed
    assert not second.session.closed
    assert not connector.closed


@pytest.mark.parametrize("login_error", [None, AuthenticationError("rejected")])
async def test_config_validation_preserves_shared_connector(sessions, login_error):
    hass, connector, clients, make_client = sessions
    flow = WaterSmartConfigFlow()
    flow.hass = hass
    with (
        patch("custom_components.watersmart.config_flow.create_client", make_client),
        patch.object(
            WaterSmartClient,
            "login",
            AsyncMock(return_value="0012345", side_effect=login_error),
        ),
        patch.object(
            WaterSmartClient, "fetch_hourly", AsyncMock(return_value={3600: 1})
        ),
    ):
        if login_error:
            with pytest.raises(AuthenticationError):
                await flow._validate(DATA)
        else:
            assert await flow._validate(DATA) == DATA
    assert clients[0].session.closed
    assert not connector.closed


@pytest.mark.parametrize(
    "error", [RuntimeError("setup failed"), asyncio.CancelledError()]
)
async def test_failed_setup_detaches_session(sessions, error):
    hass, connector, clients, make_client = sessions
    coordinator = SimpleNamespace(
        async_config_entry_first_refresh=AsyncMock(side_effect=error)
    )
    entry = SimpleNamespace(data=DATA)
    with (
        patch("custom_components.watersmart.create_client", make_client),
        patch(
            "custom_components.watersmart.WaterSmartCoordinator",
            return_value=coordinator,
        ),
        pytest.raises(type(error)),
    ):
        await async_setup_entry(hass, entry)
    assert clients[0].session.closed
    assert not connector.closed


@pytest.mark.parametrize("unloaded", [True, False])
async def test_unload_detaches_only_after_success(sessions, unloaded):
    hass, connector, _, make_client = sessions
    client = make_client(hass, DATA, auto_cleanup=False)
    entry = SimpleNamespace(runtime_data=SimpleNamespace(client=client))
    hass.config_entries = Mock(async_unload_platforms=AsyncMock(return_value=unloaded))
    assert await async_unload_entry(hass, entry) is unloaded
    assert client.session.closed is unloaded
    assert not connector.closed
