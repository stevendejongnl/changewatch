"""Changewatch binary sensors — per-monitor change detection."""
from __future__ import annotations

from homeassistant.components.binary_sensor import BinarySensorDeviceClass, BinarySensorEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from . import ChangeWatchCoordinator
from .const import DOMAIN


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    coordinator: ChangeWatchCoordinator = hass.data[DOMAIN][entry.entry_id]
    entities = [
        ChangeWatchChangedBinarySensor(coordinator, m["name"])
        for m in (coordinator.data or {}).get("monitors", [])
    ]
    async_add_entities(entities)


class ChangeWatchChangedBinarySensor(CoordinatorEntity, BinarySensorEntity):
    _attr_device_class = BinarySensorDeviceClass.UPDATE
    _attr_icon = "mdi:bell-ring"

    def __init__(self, coordinator: ChangeWatchCoordinator, monitor_name: str) -> None:
        super().__init__(coordinator)
        self._monitor_name = monitor_name
        self._attr_name = f"Changewatch {monitor_name} Changed"
        self._attr_unique_id = f"changewatch_{monitor_name}_changed"

    def _monitor_data(self) -> dict:
        for m in (self.coordinator.data or {}).get("monitors", []):
            if m["name"] == self._monitor_name:
                return m
        return {}

    @property
    def is_on(self) -> bool:
        return self._monitor_data().get("status") == "changed"
