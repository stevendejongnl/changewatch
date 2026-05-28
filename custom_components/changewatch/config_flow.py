"""Config flow for Changewatch integration."""
from __future__ import annotations

import aiohttp
import voluptuous as vol
from homeassistant import config_entries
from homeassistant.data_entry_flow import FlowResult

from .const import CONF_URL, DOMAIN


class ChangeWatchConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    VERSION = 1

    async def async_step_user(self, user_input: dict | None = None) -> FlowResult:
        errors: dict[str, str] = {}

        if user_input is not None:
            url = user_input[CONF_URL].rstrip("/")
            try:
                async with aiohttp.ClientSession() as session:
                    resp = await session.get(
                        f"{url}/ha/sensors",
                        timeout=aiohttp.ClientTimeout(total=5),
                    )
                    if resp.status != 200:
                        errors["base"] = "cannot_connect"
                    else:
                        await self.async_set_unique_id(url)
                        self._abort_if_unique_id_configured()
                        return self.async_create_entry(
                            title="Changewatch",
                            data={CONF_URL: url},
                        )
            except aiohttp.ClientError:
                errors["base"] = "cannot_connect"

        return self.async_show_form(
            step_id="user",
            data_schema=vol.Schema({
                vol.Required(CONF_URL, description={"suggested_value": "http://changewatch.local:8000"}): str,
            }),
            errors=errors,
        )
