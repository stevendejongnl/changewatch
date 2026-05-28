"""Changewatch integration for Home Assistant."""
from __future__ import annotations

import logging
from datetime import timedelta

import aiohttp
from homeassistant.components import websocket_api
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed
import voluptuous as vol

from .const import CONF_URL, DOMAIN, SCAN_INTERVAL_SECONDS

_LOGGER = logging.getLogger(__name__)

PLATFORMS = ["sensor", "binary_sensor"]


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    url = entry.data[CONF_URL].rstrip("/")

    coordinator = ChangeWatchCoordinator(hass, url)
    await coordinator.async_config_entry_first_refresh()

    hass.data.setdefault(DOMAIN, {})[entry.entry_id] = coordinator
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)

    websocket_api.async_register_command(hass, ws_list_monitors)
    websocket_api.async_register_command(hass, ws_api_proxy)

    return True


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
    hass.data[DOMAIN].pop(entry.entry_id)
    return True


class ChangeWatchCoordinator(DataUpdateCoordinator):
    def __init__(self, hass: HomeAssistant, url: str) -> None:
        super().__init__(
            hass,
            _LOGGER,
            name=DOMAIN,
            update_interval=timedelta(seconds=SCAN_INTERVAL_SECONDS),
        )
        self._url = url

    async def _async_update_data(self) -> dict:
        try:
            async with aiohttp.ClientSession() as session:
                resp = await session.get(
                    f"{self._url}/ha/sensors",
                    timeout=aiohttp.ClientTimeout(total=10),
                )
                resp.raise_for_status()
                return await resp.json()
        except Exception as err:
            raise UpdateFailed(f"Changewatch API error: {err}") from err

    async def api_request(self, method: str, path: str, body: dict | None = None) -> dict | list:
        async with aiohttp.ClientSession() as session:
            resp = await session.request(
                method,
                f"{self._url}{path}",
                headers={"Content-Type": "application/json"},
                json=body,
                timeout=aiohttp.ClientTimeout(total=10),
            )
            resp.raise_for_status()
            return await resp.json()


def _get_coordinator(hass: HomeAssistant) -> ChangeWatchCoordinator | None:
    domain_data = hass.data.get(DOMAIN, {})
    if not domain_data:
        return None
    return next(iter(domain_data.values()))


@websocket_api.websocket_command({vol.Required("type"): "changewatch/list_monitors"})
@websocket_api.async_response
async def ws_list_monitors(
    hass: HomeAssistant,
    connection: websocket_api.ActiveConnection,
    msg: dict,
) -> None:
    coordinator = _get_coordinator(hass)
    if coordinator is None:
        connection.send_error(msg["id"], "not_configured", "Changewatch integration not set up")
        return
    try:
        result = await coordinator.api_request("GET", "/api/monitors")
        connection.send_result(msg["id"], result)
    except Exception as err:
        connection.send_error(msg["id"], "request_failed", str(err))


@websocket_api.websocket_command({
    vol.Required("type"): "changewatch/api_proxy",
    vol.Required("method"): str,
    vol.Required("path"): str,
    vol.Optional("body"): dict,
})
@websocket_api.async_response
async def ws_api_proxy(
    hass: HomeAssistant,
    connection: websocket_api.ActiveConnection,
    msg: dict,
) -> None:
    coordinator = _get_coordinator(hass)
    if coordinator is None:
        connection.send_error(msg["id"], "not_configured", "Changewatch integration not set up")
        return
    try:
        result = await coordinator.api_request(msg["method"], msg["path"], msg.get("body"))
        connection.send_result(msg["id"], result)
    except Exception as err:
        connection.send_error(msg["id"], "request_failed", str(err))
