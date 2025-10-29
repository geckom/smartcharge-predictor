"""Sensor platform for SmartCharge Predictor integration."""

from __future__ import annotations

import logging
from datetime import datetime
from typing import Any

from homeassistant.components.sensor import SensorDeviceClass, SensorEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity import DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import (
    ATTR_BATTERY_HEALTH,
    ATTR_CHARGER_POWER,
    ATTR_HUMIDITY,
    ATTR_LAST_TRAINING,
    ATTR_LAST_UPDATED,
    ATTR_MODEL_TYPE,
    ATTR_OPTIMIZED_CHARGING,
    ATTR_TEMPERATURE,
    ATTR_TIME_REMAINING_MINUTES,
    CONF_DEVICE_NAME,
    DEVICE_CLASS_DURATION,
    DEVICE_CLASS_TIMESTAMP,
    DOMAIN,
    ENTITY_ID_FULL_CHARGE_TIME,
    ENTITY_ID_PREDICTED_RATE,
    ENTITY_ID_TIME_REMAINING,
    INTEGRATION_VERSION,
    UNIT_MINUTES,
    UNIT_PERCENT_PER_MINUTE,
)
from .coordinator import SmartChargeCoordinator

_LOGGER = logging.getLogger(__name__)


async def async_setup_entry(
    hass: HomeAssistant,
    config_entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up SmartCharge Predictor sensors from a config entry."""
    coordinator: SmartChargeCoordinator = hass.data[DOMAIN][config_entry.entry_id][
        "coordinator"
    ]
    device_name = hass.data[DOMAIN][config_entry.entry_id]["device_name"]

    _LOGGER.debug("Setting up sensors for device: %s", device_name)
    _LOGGER.debug("Coordinator data available: %s", coordinator.data is not None)

    # Create sensor entities
    entities = [
        ChargeTimeRemainingSensor(coordinator, device_name),
        FullChargeTimeSensor(coordinator, device_name),
        PredictedRateSensor(coordinator, device_name),
    ]

    _LOGGER.debug("Created %d sensor entities", len(entities))
    async_add_entities(entities)


class SmartChargeSensor(CoordinatorEntity[SmartChargeCoordinator], SensorEntity):
    """Base class for SmartCharge Predictor sensors."""

    def __init__(self, coordinator: SmartChargeCoordinator, device_name: str) -> None:
        """Initialize the sensor."""
        super().__init__(coordinator)
        self._device_name = device_name
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, coordinator.device_id)},
            name=device_name,
            manufacturer="SmartCharge Predictor",
            model="Charging Predictor",
            sw_version=INTEGRATION_VERSION,
        )
        _LOGGER.debug(
            "Initialized %s for device %s", self.__class__.__name__, device_name
        )

    @property
    def available(self) -> bool:
        """Return if entity is available."""
        available = (
            self.coordinator.last_update_success and self.coordinator.data is not None
        )
        _LOGGER.debug(
            "%s availability -> %s (last_update_success=%s, has_data=%s)",
            self.__class__.__name__,
            available,
            self.coordinator.last_update_success,
            self.coordinator.data is not None,
        )
        return available


class ChargeTimeRemainingSensor(SmartChargeSensor):
    """Sensor for estimated time remaining until full charge."""

    _attr_name = "Charge Time Remaining"
    _attr_native_unit_of_measurement = UNIT_MINUTES
    _attr_device_class = SensorDeviceClass.DURATION
    _attr_suggested_display_precision = 1
    _attr_icon = "mdi:clock-outline"

    def __init__(self, coordinator: SmartChargeCoordinator, device_name: str) -> None:
        """Initialize the sensor."""
        super().__init__(coordinator, device_name)
        self._attr_unique_id = f"{coordinator.device_id}_{ENTITY_ID_TIME_REMAINING}"

    @property
    def native_value(self) -> float | None:
        """Return the state of the sensor."""
        if not self.coordinator.data:
            _LOGGER.debug(
                "%s native_value: no coordinator data", self.__class__.__name__
            )
            return None

        time_remaining = self.coordinator.data.get("time_remaining")
        _LOGGER.debug(
            "%s coordinator data keys: %s",
            self.__class__.__name__,
            list(self.coordinator.data.keys()),
        )
        _LOGGER.debug(
            "%s time_remaining value: %s", self.__class__.__name__, time_remaining
        )

        if time_remaining is None:
            return None

        value = round(time_remaining, 1)
        _LOGGER.debug("%s native_value=%s", self.__class__.__name__, value)
        return value

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """Return the state attributes."""
        if not self.coordinator.data:
            return {}

        attrs = {
            ATTR_BATTERY_HEALTH: self.coordinator.data.get("battery_health"),
            ATTR_CHARGER_POWER: self.coordinator.data.get("charger_power_w"),
            ATTR_TEMPERATURE: self.coordinator.data.get("temperature"),
            ATTR_HUMIDITY: self.coordinator.data.get("humidity"),
            ATTR_OPTIMIZED_CHARGING: self.coordinator.data.get("optimized_charging"),
            ATTR_LAST_UPDATED: self.coordinator.data.get("last_updated"),
        }

        # Add model info if available
        model_info = self.coordinator.data.get("model_info", {})
        if model_info:
            attrs[ATTR_MODEL_TYPE] = model_info.get("model_type")
            attrs[ATTR_LAST_TRAINING] = model_info.get("last_training")

        # Remove None values
        return {k: v for k, v in attrs.items() if v is not None}


class FullChargeTimeSensor(SmartChargeSensor):
    """Sensor for estimated datetime when device will be fully charged."""

    _attr_name = "Full Charge Time"
    _attr_device_class = SensorDeviceClass.TIMESTAMP
    _attr_icon = "mdi:battery-charging-100"

    def __init__(self, coordinator: SmartChargeCoordinator, device_name: str) -> None:
        """Initialize the sensor."""
        super().__init__(coordinator, device_name)
        self._attr_unique_id = f"{coordinator.device_id}_{ENTITY_ID_FULL_CHARGE_TIME}"

    @property
    def native_value(self) -> datetime | None:
        """Return the state of the sensor."""
        if not self.coordinator.data:
            _LOGGER.debug(
                "%s native_value: no coordinator data", self.__class__.__name__
            )
            return None

        full_charge_time = self.coordinator.data.get("full_charge_time")
        _LOGGER.debug(
            "%s coordinator data keys: %s",
            self.__class__.__name__,
            list(self.coordinator.data.keys()),
        )
        _LOGGER.debug(
            "%s full_charge_time value: %s", self.__class__.__name__, full_charge_time
        )

        if full_charge_time is None:
            return None

        _LOGGER.debug("%s native_value=%s", self.__class__.__name__, full_charge_time)
        return full_charge_time

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """Return the state attributes."""
        if not self.coordinator.data:
            return {}

        attrs = {
            ATTR_TIME_REMAINING_MINUTES: self.coordinator.data.get("time_remaining"),
            ATTR_LAST_UPDATED: self.coordinator.data.get("last_updated"),
        }

        # Remove None values
        return {k: v for k, v in attrs.items() if v is not None}


class PredictedRateSensor(SmartChargeSensor):
    """Sensor for current predicted charging rate."""

    _attr_name = "Predicted Charge Rate"
    _attr_native_unit_of_measurement = UNIT_PERCENT_PER_MINUTE
    _attr_suggested_display_precision = 3
    _attr_icon = "mdi:speedometer"

    def __init__(self, coordinator: SmartChargeCoordinator, device_name: str) -> None:
        """Initialize the sensor."""
        super().__init__(coordinator, device_name)
        self._attr_unique_id = f"{coordinator.device_id}_{ENTITY_ID_PREDICTED_RATE}"

    @property
    def native_value(self) -> float | None:
        """Return the state of the sensor."""
        if not self.coordinator.data:
            _LOGGER.debug(
                "%s native_value: no coordinator data", self.__class__.__name__
            )
            return None

        charge_rate = self.coordinator.data.get("charge_rate")
        _LOGGER.debug(
            "%s coordinator data keys: %s",
            self.__class__.__name__,
            list(self.coordinator.data.keys()),
        )
        _LOGGER.debug("%s charge_rate value: %s", self.__class__.__name__, charge_rate)

        if charge_rate is None:
            return None

        value = round(charge_rate, 3)
        _LOGGER.debug("%s native_value=%s", self.__class__.__name__, value)
        return value

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """Return the state attributes."""
        if not self.coordinator.data:
            return {}

        attrs = {
            "calculated_rate": self.coordinator.data.get("calculated_rate"),
            "battery_pct": self.coordinator.data.get("battery_pct"),
            ATTR_TEMPERATURE: self.coordinator.data.get("temperature"),
            ATTR_HUMIDITY: self.coordinator.data.get("humidity"),
            ATTR_CHARGER_POWER: self.coordinator.data.get("charger_power_w"),
            ATTR_BATTERY_HEALTH: self.coordinator.data.get("battery_health"),
            ATTR_OPTIMIZED_CHARGING: self.coordinator.data.get("optimized_charging"),
            ATTR_LAST_UPDATED: self.coordinator.data.get("last_updated"),
        }

        # Add model info if available
        model_info = self.coordinator.data.get("model_info", {})
        if model_info:
            attrs[ATTR_MODEL_TYPE] = model_info.get("model_type")
            attrs[ATTR_LAST_TRAINING] = model_info.get("last_training")
            attrs["model_accuracy"] = model_info.get("accuracy")
            attrs["sample_count"] = model_info.get("sample_count")

        # Remove None values
        return {k: v for k, v in attrs.items() if v is not None}
