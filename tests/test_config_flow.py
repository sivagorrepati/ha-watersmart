"""Validate setup and reauth identity without contacting the utility."""

from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock, patch

from custom_components.watersmart.api import AuthenticationError
from custom_components.watersmart.config_flow import (
    WaterSmartConfigFlow,
    credentials_schema,
)

DATA = {
    "url": "https://milpitas.watersmart.com",
    "email": "test@example.com",
    "password": "test-password",
    "account_number": "0012345",
}


def test_credentials_form_accepts_inputs_and_defaults():
    schema = credentials_schema({})
    assert schema({"email": "test@example.com", "password": "secret"}) == {
        "url": "https://milpitas.watersmart.com",
        "email": "test@example.com",
        "password": "secret",
    }


async def test_validation_detaches_session_on_error():
    flow = WaterSmartConfigFlow()
    flow.hass = Mock()
    client = SimpleNamespace(
        login=AsyncMock(side_effect=AuthenticationError()),
        session=SimpleNamespace(detach=Mock(), close=AsyncMock()),
    )
    with patch(
        "custom_components.watersmart.config_flow.create_client", return_value=client
    ):
        try:
            await flow._validate(DATA)
        except AuthenticationError:
            pass
        else:
            raise AssertionError("Authentication failure was swallowed")
    client.session.detach.assert_called_once()
    client.session.close.assert_not_awaited()


async def test_setup_discovers_account_and_creates_entry():
    flow = WaterSmartConfigFlow()
    flow._validate = AsyncMock(return_value=DATA)
    flow.async_set_unique_id = AsyncMock()
    flow._abort_if_unique_id_configured = Mock()
    flow.async_create_entry = Mock(return_value={"type": "create_entry"})
    result = await flow.async_step_user(DATA)
    assert result["type"] == "create_entry"
    flow.async_set_unique_id.assert_awaited_once_with(
        "https://milpitas.watersmart.com_0012345"
    )


async def test_reauth_updates_existing_entry():
    flow = WaterSmartConfigFlow()
    entry = SimpleNamespace(data=DATA)
    flow._get_reauth_entry = Mock(return_value=entry)
    flow._validate = AsyncMock(return_value=DATA | {"password": "new-password"})
    flow.async_set_unique_id = AsyncMock()
    flow._abort_if_unique_id_mismatch = Mock()
    flow.async_update_reload_and_abort = Mock(return_value={"type": "abort"})
    result = await flow.async_step_reauth_confirm({"password": "new-password"})
    assert result["type"] == "abort"
    flow._abort_if_unique_id_mismatch.assert_called_once()
    assert flow.async_update_reload_and_abort.call_args.args[0] is entry
    assert (
        flow.async_update_reload_and_abort.call_args.kwargs["data_updates"]["password"]
        == "new-password"
    )
