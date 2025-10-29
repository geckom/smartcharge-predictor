"""Data update coordinator for SmartCharge Predictor integration."""

from __future__ import annotations

import logging
from collections.abc import Callable
from datetime import datetime, timedelta
from typing import Any, Optional

from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.event import async_track_state_change_event
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator

from .const import (
    CONF_AMBIENT_TEMP_ENTITY,
    CONF_BATTERY_ENTITY,
    CONF_BATTERY_HEALTH,
    CONF_CHARGER_POWER,
    CONF_HUMIDITY_ENTITY,
    CONF_LEARN_FROM_HISTORY,
    CONF_OPTIMIZED_CHARGING_ENABLED,
    CONF_OPTIMIZED_CHARGING_ENTITY,
    CONF_SCAN_INTERVAL,
    DEFAULT_SCAN_INTERVAL_SECONDS,
    DOMAIN,
    FAST_CHARGE_THRESHOLD,
    INTEGRATION_VERSION,
)
from .history_manager import HistoryManager
from .model import ChargingModel

_LOGGER = logging.getLogger(__name__)


class SmartChargeCoordinator(DataUpdateCoordinator[dict[str, Any]]):
    """Coordinator for SmartCharge Predictor data updates."""

    def __init__(
        self,
        hass: HomeAssistant,
        device_id: str,
        config: dict[str, Any],
        history_manager: HistoryManager,
        charging_model: ChargingModel,
    ) -> None:
        """Initialize the coordinator."""
        self.device_id = device_id
        self.config = config
        self.history_manager = history_manager
        self.charging_model = charging_model

        # Track previous battery level for rate calculation.
        self._previous_battery_pct: Optional[float] = None
        self._previous_timestamp: Optional[datetime] = None

        # Cache last known data for graceful error handling.
        self._last_known_data: Optional[dict[str, Any]] = None
        self._state_listener: Optional[Callable[[], None]] = None

        # Determine scan interval from config (already merged with options in __init__.py).
        scan_interval_seconds = config.get(
            CONF_SCAN_INTERVAL, DEFAULT_SCAN_INTERVAL_SECONDS
        )
        scan_interval = timedelta(seconds=int(scan_interval_seconds))

        super().__init__(
            hass,
            _LOGGER,
            name=f"SmartCharge Predictor - {device_id}",
            update_interval=scan_interval,
        )

        # Register state change listener for battery entity.
        self._setup_state_listener()

    @callback
    def _setup_state_listener(self) -> None:
        """Set up state change listener for battery entity."""
        battery_entity = self.config.get(CONF_BATTERY_ENTITY)
        if not battery_entity:
            return

        @callback
        def _async_battery_state_changed(event) -> None:
            """Handle battery state changes."""
            self.async_request_refresh()

        self._state_listener = async_track_state_change_event(
            self.hass, [battery_entity], _async_battery_state_changed
        )
        _LOGGER.debug("Registered state change listener for %s", battery_entity)

    def _cleanup_state_listener(self) -> None:
        """Clean up state change listener."""
        if self._state_listener:
            self._state_listener()
            self._state_listener = None

    async def _async_update_data(self) -> dict[str, Any]:
        """Update data from entities and calculate predictions."""
        try:
            # Get current battery level.
            battery_entity = self.config[CONF_BATTERY_ENTITY]
            _LOGGER.debug("Reading battery entity: %s", battery_entity)
            battery_state = self.hass.states.get(battery_entity)

            if not battery_state or battery_state.state in ("unknown", "unavailable"):
                _LOGGER.debug(
                    "Battery entity %s unavailable (state: %s)",
                    battery_entity,
                    battery_state.state if battery_state else "None",
                )
                # Return last known data instead of raising exception.
                if self._last_known_data:
                    return self._last_known_data
                # If no previous data, return empty dict but don't fail.
                return {}

            try:
                battery_pct = float(battery_state.state)
            except (ValueError, TypeError):
                _LOGGER.debug(
                    "Battery entity %s has non-numeric state: %s",
                    battery_entity,
                    battery_state.state,
                )
                # Return last known data instead of raising exception.
                if self._last_known_data:
                    return self._last_known_data
                return {}

            # Get optional sensor values.
            temperature = await self._get_sensor_value(CONF_AMBIENT_TEMP_ENTITY)
            humidity = await self._get_sensor_value(CONF_HUMIDITY_ENTITY)
            _LOGGER.debug(
                "Sensors -> battery_pct=%s temp=%s humidity=%s",
                battery_pct,
                temperature,
                humidity,
            )

            # Get optimized charging status (from entity if configured, else infer from behavior).
            optimized_charging = await self._get_optimized_charging_status(battery_pct)
            _LOGGER.debug("Optimized charging enabled: %s", optimized_charging)

            # Get charger and battery health from config.
            charger_power_w = self.config.get(CONF_CHARGER_POWER, 20.0)
            battery_health = self.config.get(CONF_BATTERY_HEALTH, 100.0)

            # Calculate charging rate from previous sample if available.
            calculated_rate = self.history_manager.calculate_rate_from_samples(
                self.device_id, battery_pct
            )

            # Record a sample when the reported battery percent changes.
            # Only record if learn_from_history is enabled.
            learn_from_history = self.config.get(CONF_LEARN_FROM_HISTORY, True)
            if learn_from_history:
                latest_sample = self.history_manager.get_latest_sample(self.device_id)
                latest_pct = latest_sample.get("battery_pct") if latest_sample else None
                if latest_pct is None or battery_pct != latest_pct:
                    self.history_manager.record_sample(
                        device_id=self.device_id,
                        battery_pct=battery_pct,
                        temperature=temperature,
                        humidity=humidity,
                        rate_pct_per_min=calculated_rate,
                        charger_power_w=charger_power_w,
                        optimized_charging=optimized_charging,
                        battery_health=battery_health,
                    )

            # Predict charging rate using model.
            predicted_rate = self.charging_model.predict_rate(
                battery_pct=battery_pct,
                temperature=temperature,
                humidity=humidity,
                charger_power_w=charger_power_w,
                battery_health=battery_health,
                optimized_charging=optimized_charging,
            )

            # Calculate time remaining and full charge time.
            time_remaining_minutes = self.charging_model.calculate_time_remaining(
                battery_pct, predicted_rate
            )
            full_charge_time = self.charging_model.calculate_full_charge_time(
                time_remaining_minutes
            )

            # Check if we should retrain the model (only if learning is enabled).
            if learn_from_history and self.charging_model.should_retrain():
                _LOGGER.info("Retraining model for device %s", self.device_id)
                await self.charging_model.train_model()

            # Update previous values for next calculation.
            self._previous_battery_pct = battery_pct
            self._previous_timestamp = datetime.now()

            # Prepare data for sensors.
            data = {
                "battery_pct": battery_pct,
                "temperature": temperature,
                "humidity": humidity,
                "charger_power_w": charger_power_w,
                "battery_health": battery_health,
                "optimized_charging": optimized_charging,
                "charge_rate": predicted_rate,
                "calculated_rate": calculated_rate,
                "time_remaining": time_remaining_minutes,
                "full_charge_time": full_charge_time,
                "last_updated": datetime.now().isoformat(),
                "model_info": self.charging_model.get_model_info(),
            }
            _LOGGER.debug("Coordinator data prepared: %s", data)

            # Cache last known data for graceful error handling.
            self._last_known_data = data

            # Save history periodically (only if learning enabled, debounced).
            if learn_from_history:
                await self.history_manager.async_save(immediate=False)

            return data

        except Exception as err:
            _LOGGER.error("Failed to update SmartCharge data: %s", err)
            # Return last known data instead of raising exception.
            if self._last_known_data:
                return self._last_known_data
            # If no previous data and error occurred, return empty dict.
            return {}

    async def _get_sensor_value(self, config_key: str) -> Optional[float]:
        """Get numeric value from an optional sensor entity."""
        entity_id = self.config.get(config_key)
        if not entity_id:
            return None

        state = self.hass.states.get(entity_id)
        if not state or state.state in ("unknown", "unavailable"):
            return None

        try:
            return float(state.state)
        except (ValueError, TypeError):
            _LOGGER.warning("Invalid numeric value from %s: %s", entity_id, state.state)
            return None

    async def _get_binary_sensor_value(self, entity_id: str) -> Optional[bool]:
        """Get boolean value from a binary sensor entity."""
        if not entity_id:
            return None

        state = self.hass.states.get(entity_id)
        if not state or state.state in ("unknown", "unavailable"):
            return None

        return state.state.lower() in ("on", "true", "1")

    async def _get_optimized_charging_status(self, battery_pct: float) -> bool:
        """Get optimized charging status from entity or infer from behavior."""
        # First, try to read from configured entity.
        optimized_charging_entity = self.config.get(CONF_OPTIMIZED_CHARGING_ENTITY)
        if optimized_charging_entity:
            entity_value = await self._get_binary_sensor_value(
                optimized_charging_entity
            )
            if entity_value is not None:
                return entity_value

        # Fall back to config boolean setting.
        if self.config.get(CONF_OPTIMIZED_CHARGING_ENABLED, False):
            return True

        # Infer from battery behavior: stuck near 80% for extended period.
        if (
            battery_pct >= FAST_CHARGE_THRESHOLD - 2
            and battery_pct <= FAST_CHARGE_THRESHOLD + 2
        ):
            # Check if battery has been stuck in this range.
            history = self.history_manager.get_history(self.device_id)
            if len(history) >= 3:
                recent_samples = history[-3:]
                if all(
                    FAST_CHARGE_THRESHOLD - 2
                    <= s.get("battery_pct", 0)
                    <= FAST_CHARGE_THRESHOLD + 2
                    for s in recent_samples
                ):
                    # Battery stuck near 80%, likely optimized charging.
                    return True

        return False

    def is_charging(self) -> bool:
        """Check if device is currently charging based on recent data."""
        # Check current battery level from coordinator data.
        if self.data:
            battery_pct = self.data.get("battery_pct")
            if battery_pct is not None:
                # Invalid battery level.
                if battery_pct > 100:
                    return False
                # Battery at 100% is not charging.
                if battery_pct >= 100:
                    return False

        latest_sample = self.history_manager.get_latest_sample(self.device_id)
        if not latest_sample:
            return False

        # Check if we have a recent positive charging rate.
        rate = latest_sample.get("rate_pct_per_min")
        if rate is not None and rate > 0:
            # Check if sample is recent (within last 5 minutes).
            try:
                timestamp_str = latest_sample.get("timestamp")
                if timestamp_str:
                    timestamp = datetime.fromisoformat(timestamp_str)
                    time_diff = (datetime.now() - timestamp).total_seconds()
                    if time_diff < 300:  # 5 minutes
                        return True
            except (ValueError, TypeError):
                pass

        # Check if battery percentage is increasing based on recent samples.
        history = self.history_manager.get_history(self.device_id)
        if len(history) >= 2:
            recent_samples = history[-2:]
            if len(recent_samples) == 2:
                prev_pct = recent_samples[0].get("battery_pct")
                curr_pct = recent_samples[1].get("battery_pct")
                if (
                    prev_pct is not None
                    and curr_pct is not None
                    and curr_pct > prev_pct
                ):
                    return True

        return False

    async def force_update(self) -> None:
        """Force an immediate update of the coordinator data."""
        await self.async_request_refresh()

    def get_device_info(self) -> dict[str, Any]:
        """Get device information for entity registration."""
        return {
            "identifiers": {(DOMAIN, self.device_id)},
            "name": self.config.get("name", f"SmartCharge Device {self.device_id}"),
            "manufacturer": "SmartCharge Predictor",
            "model": "Charging Predictor",
            "sw_version": INTEGRATION_VERSION,
        }

    def async_shutdown(self) -> None:
        """Clean up coordinator resources."""
        self._cleanup_state_listener()
