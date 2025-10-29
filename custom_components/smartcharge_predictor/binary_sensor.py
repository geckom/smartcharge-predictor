"""Binary sensor platform for SmartCharge Predictor integration."""

from __future__ import annotations

import logging
from typing import Any

from homeassistant.components.binary_sensor import (
    BinarySensorDeviceClass,
    BinarySensorEntity,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity import DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DOMAIN, ENTITY_ID_OPTIMIZED_CHARGING, INTEGRATION_VERSION
from .coordinator import SmartChargeCoordinator

_LOGGER = logging.getLogger(__name__)


async def async_setup_entry(
    hass: HomeAssistant,
    config_entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up SmartCharge Predictor binary sensors from a config entry."""
    coordinator: SmartChargeCoordinator = hass.data[DOMAIN][config_entry.entry_id][
        "coordinator"
    ]
    device_name = hass.data[DOMAIN][config_entry.entry_id]["device_name"]

    # Create binary sensor entity
    entities = [OptimizedChargingBinarySensor(coordinator, device_name)]
    async_add_entities(entities)


class OptimizedChargingBinarySensor(
    CoordinatorEntity[SmartChargeCoordinator], BinarySensorEntity
):
    """Binary sensor for optimized charging status."""

    _attr_name = "Optimized Charging"
    _attr_device_class = BinarySensorDeviceClass.BATTERY_CHARGING
    _attr_icon = "mdi:battery-charging-wireless"

    def __init__(self, coordinator: SmartChargeCoordinator, device_name: str) -> None:
        """Initialize the binary sensor."""
        super().__init__(coordinator)
        self._device_name = device_name
        self._attr_unique_id = f"{coordinator.device_id}_{ENTITY_ID_OPTIMIZED_CHARGING}"
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, coordinator.device_id)},
            name=device_name,
            manufacturer="SmartCharge Predictor",
            model="Charging Predictor",
            sw_version=INTEGRATION_VERSION,
        )

    @property
    def is_on(self) -> bool | None:
        """Return if optimized charging is active."""
        if not self.coordinator.data:
            return None
        return self.coordinator.data.get("optimized_charging")

    @property
    def available(self) -> bool:
        """Return if entity is available."""
        return (
            self.coordinator.last_update_success and self.coordinator.data is not None
        )
