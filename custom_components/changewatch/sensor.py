"""Changewatch sensor entities."""
from __future__ import annotations

from homeassistant.components.sensor import SensorEntity, SensorStateClass
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

    entities: list[SensorEntity] = [
        ChangeWatchCountSensor(coordinator, "monitors_total", "Changewatch Monitors Total", "mdi:eye-check"),
        ChangeWatchCountSensor(coordinator, "monitors_ok", "Changewatch Monitors OK", "mdi:check-circle"),
        ChangeWatchCountSensor(coordinator, "monitors_changed", "Changewatch Monitors Changed", "mdi:bell-ring"),
        ChangeWatchCountSensor(coordinator, "monitors_error", "Changewatch Monitors Error", "mdi:alert-circle"),
    ]

    for monitor in (coordinator.data or {}).get("monitors", []):
        name = monitor["name"]
        entities.append(ChangeWatchMonitorStatusSensor(coordinator, name))
        entities.append(ChangeWatchMonitorValueSensor(coordinator, name))

    async_add_entities(entities)


class ChangeWatchCountSensor(CoordinatorEntity, SensorEntity):
    _attr_state_class = SensorStateClass.MEASUREMENT
    _attr_native_unit_of_measurement = "monitors"

    def __init__(self, coordinator: ChangeWatchCoordinator, key: str, name: str, icon: str) -> None:
        super().__init__(coordinator)
        self._key = key
        self._attr_name = name
        self._attr_icon = icon
        self._attr_unique_id = f"changewatch_{key}"

    @property
    def native_value(self) -> int:
        return self.coordinator.data.get(self._key, 0) if self.coordinator.data else 0


class ChangeWatchMonitorStatusSensor(CoordinatorEntity, SensorEntity):
    _attr_icon = "mdi:eye"

    def __init__(self, coordinator: ChangeWatchCoordinator, monitor_name: str) -> None:
        super().__init__(coordinator)
        self._monitor_name = monitor_name
        self._attr_name = f"Changewatch {monitor_name} Status"
        self._attr_unique_id = f"changewatch_{monitor_name}_status"

    def _monitor_data(self) -> dict:
        for m in (self.coordinator.data or {}).get("monitors", []):
            if m["name"] == self._monitor_name:
                return m
        return {}

    @property
    def native_value(self) -> str:
        return self._monitor_data().get("status", "unknown")

    @property
    def extra_state_attributes(self) -> dict:
        m = self._monitor_data()
        return {
            "last_value": m.get("last_value"),
            "ran_at": m.get("ran_at"),
            "paused": m.get("paused", False),
            "duration_ms": m.get("duration_ms"),
        }


class ChangeWatchMonitorValueSensor(CoordinatorEntity, SensorEntity):
    _attr_icon = "mdi:text-box"

    def __init__(self, coordinator: ChangeWatchCoordinator, monitor_name: str) -> None:
        super().__init__(coordinator)
        self._monitor_name = monitor_name
        self._attr_name = f"Changewatch {monitor_name} Value"
        self._attr_unique_id = f"changewatch_{monitor_name}_last_value"

    def _monitor_data(self) -> dict:
        for m in (self.coordinator.data or {}).get("monitors", []):
            if m["name"] == self._monitor_name:
                return m
        return {}

    @property
    def native_value(self) -> str | None:
        return self._monitor_data().get("last_value")
