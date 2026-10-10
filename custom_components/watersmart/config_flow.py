"""UI setup and credential reauthentication for WaterSmart."""

import aiohttp
import probatio as vol
from homeassistant import config_entries
from homeassistant.const import CONF_EMAIL, CONF_PASSWORD, CONF_URL
from homeassistant.helpers import selector

from . import create_client
from .api import (
    AccountMismatchError,
    AuthenticationError,
    WaterSmartError,
    normalize_url,
)
from .const import CONF_ACCOUNT_NUMBER, DEFAULT_URL, DOMAIN


def credentials_schema(defaults: dict, include_url: bool = True) -> vol.Schema:
    fields = {}
    if include_url:
        fields[vol.Required(CONF_URL, default=defaults.get(CONF_URL, DEFAULT_URL))] = (
            str
        )
    fields[vol.Required(CONF_EMAIL, default=defaults.get(CONF_EMAIL, ""))] = str
    fields[vol.Required(CONF_PASSWORD)] = selector.TextSelector(
        selector.TextSelectorConfig(type=selector.TextSelectorType.PASSWORD)
    )
    return vol.Schema(fields)


class WaterSmartConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    VERSION = 1

    async def _validate(self, data: dict) -> dict:
        data = dict(data)
        data[CONF_URL] = normalize_url(data[CONF_URL])
        data[CONF_EMAIL] = data[CONF_EMAIL].strip()
        client = create_client(self.hass, data)
        try:
            data[CONF_ACCOUNT_NUMBER] = await client.login()
            await client.fetch_hourly()
        finally:
            await client.session.close()
        return data

    async def async_step_user(self, user_input=None):
        return await self._credentials_step("user", user_input)

    async def async_step_reauth(self, entry_data):
        return await self.async_step_reauth_confirm()

    async def async_step_reauth_confirm(self, user_input=None):
        return await self._credentials_step("reauth_confirm", user_input)

    async def _credentials_step(self, step: str, user_input):
        errors = {}
        reauth = step == "reauth_confirm"
        entry = self._get_reauth_entry() if reauth else None
        defaults = dict(entry.data) if entry else {}
        if user_input is not None:
            try:
                data = await self._validate(defaults | user_input)
            except AuthenticationError:
                errors["base"] = "invalid_auth"
            except AccountMismatchError:
                errors["base"] = "account_mismatch"
            except aiohttp.ClientError, TimeoutError:
                errors["base"] = "cannot_connect"
            except ValueError:
                errors["base"] = "invalid_url"
            except WaterSmartError:
                errors["base"] = "invalid_response"
            else:
                await self.async_set_unique_id(
                    f"{data[CONF_URL]}_{data[CONF_ACCOUNT_NUMBER]}"
                )
                if entry:
                    self._abort_if_unique_id_mismatch()
                    return self.async_update_reload_and_abort(entry, data_updates=data)
                self._abort_if_unique_id_configured()
                return self.async_create_entry(
                    title=f"WaterSmart {data[CONF_ACCOUNT_NUMBER]}", data=data
                )
        return self.async_show_form(
            step_id=step,
            data_schema=credentials_schema(defaults | (user_input or {}), not reauth),
            errors=errors,
        )
