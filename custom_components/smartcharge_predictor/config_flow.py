"""Config flow for SmartCharge Predictor integration."""

from __future__ import annotations

import logging
from typing import Any

import voluptuous as vol
from homeassistant import config_entries
from homeassistant.const import CONF_NAME
from homeassistant.core import HomeAssistant, callback
from homeassistant.data_entry_flow import FlowResult
from homeassistant.helpers import entity_registry as er
from homeassistant.helpers import selector

from .const import (
    ATTR_BATTERY_HEALTH,
    ATTR_CHARGER_POWER,
    CONF_AMBIENT_TEMP_ENTITY,
    CONF_BATTERY_ENTITY,
    CONF_BATTERY_HEALTH,
    CONF_CHARGER_POWER,
    CONF_DEVICE_NAME,
    CONF_HUMIDITY_ENTITY,
    CONF_LEARN_FROM_HISTORY,
    CONF_OPTIMIZED_CHARGING_ENABLED,
    CONF_OPTIMIZED_CHARGING_ENTITY,
    CONF_SCAN_INTERVAL,
    CONF_MAX_HISTORY_SAMPLES,
    DEFAULT_BATTERY_HEALTH,
    DEFAULT_CHARGER_POWER,
    DEFAULT_MAX_HISTORY_SAMPLES,
    DEFAULT_SCAN_INTERVAL_SECONDS,
    MAX_MAX_HISTORY_SAMPLES,
    MIN_MAX_HISTORY_SAMPLES,
    DOMAIN,
    ERROR_INVALID_ENTITY,
    ERROR_INVALID_NUMBER,
    INTEGRATION_NAME,
    STEP_DEVICE_DETAILS,
    STEP_ENVIRONMENT,
    STEP_OPTIMIZED_CHARGING,
    STEP_OPTIONS,
    STEP_USER,
)

_LOGGER = logging.getLogger(__name__)

# Configuration schema for device details step
DEVICE_DETAILS_SCHEMA = vol.Schema(
    {
        vol.Required(CONF_DEVICE_NAME): str,
        vol.Required(CONF_CHARGER_POWER, default=DEFAULT_CHARGER_POWER): vol.All(
            vol.Coerce(float), vol.Range(min=1.0, max=1000.0)
        ),
        vol.Required(CONF_BATTERY_HEALTH, default=DEFAULT_BATTERY_HEALTH): vol.All(
            vol.Coerce(float), vol.Range(min=1.0, max=100.0)
        ),
        vol.Required(CONF_LEARN_FROM_HISTORY, default=True): bool,
    }
)

# Configuration schema for environment step
ENVIRONMENT_SCHEMA = vol.Schema(
    {
        vol.Optional(CONF_AMBIENT_TEMP_ENTITY): selector.EntitySelector(
            selector.EntitySelectorConfig(
                domain=["sensor"],
                device_class="temperature",
            )
        ),
        vol.Optional(CONF_HUMIDITY_ENTITY): selector.EntitySelector(
            selector.EntitySelectorConfig(
                domain=["sensor"],
                device_class="humidity",
            )
        ),
        vol.Optional(CONF_OPTIMIZED_CHARGING_ENTITY): selector.EntitySelector(
            selector.EntitySelectorConfig(
                domain=["binary_sensor"],
            )
        ),
    }
)

# Configuration schema for optimized charging step (boolean setting)
OPTIMIZED_CHARGING_SCHEMA = vol.Schema(
    {vol.Required(CONF_OPTIMIZED_CHARGING_ENABLED, default=False): bool}
)


class ConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    """Handle a config flow for SmartCharge Predictor."""

    VERSION = 1

    def __init__(self) -> None:
        """Initialize the config flow."""
        self._data: dict[str, Any] = {}

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        """Handle the initial step."""
        if user_input is None:
            return self.async_show_form(
                step_id=STEP_USER,
                data_schema=vol.Schema(
                    {
                        vol.Required(CONF_BATTERY_ENTITY): selector.EntitySelector(
                            selector.EntitySelectorConfig(
                                domain=["sensor"],
                                device_class="battery",
                            )
                        ),
                    }
                ),
                errors={},
            )

        # Validate the battery entity exists
        battery_entity = user_input[CONF_BATTERY_ENTITY]
        if not await self._validate_entity(battery_entity):
            return self.async_show_form(
                step_id=STEP_USER,
                data_schema=vol.Schema(
                    {
                        vol.Required(CONF_BATTERY_ENTITY): selector.EntitySelector(
                            selector.EntitySelectorConfig(
                                domain=["sensor"],
                                device_class="battery",
                            )
                        ),
                    }
                ),
                errors={CONF_BATTERY_ENTITY: ERROR_INVALID_ENTITY},
            )

        self._data[CONF_BATTERY_ENTITY] = battery_entity
        return await self.async_step_device_details()

    async def async_step_device_details(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        """Handle device details configuration."""
        if user_input is None:
            return self.async_show_form(
                step_id=STEP_DEVICE_DETAILS,
                data_schema=DEVICE_DETAILS_SCHEMA,
                errors={},
            )

        # Validate numeric inputs
        try:
            charger_power = float(user_input[CONF_CHARGER_POWER])
            battery_health = float(user_input[CONF_BATTERY_HEALTH])
        except (ValueError, TypeError):
            return self.async_show_form(
                step_id=STEP_DEVICE_DETAILS,
                data_schema=DEVICE_DETAILS_SCHEMA,
                errors={CONF_CHARGER_POWER: ERROR_INVALID_NUMBER},
            )

        self._data.update(user_input)
        return await self.async_step_environment()

    async def async_step_environment(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        """Handle environment sensors configuration."""
        if user_input is None:
            return self.async_show_form(
                step_id=STEP_ENVIRONMENT,
                data_schema=ENVIRONMENT_SCHEMA,
                errors={},
            )

        # Validate optional entities if provided
        if user_input.get(CONF_AMBIENT_TEMP_ENTITY):
            if not await self._validate_entity(user_input[CONF_AMBIENT_TEMP_ENTITY]):
                return self.async_show_form(
                    step_id=STEP_ENVIRONMENT,
                    data_schema=ENVIRONMENT_SCHEMA,
                    errors={CONF_AMBIENT_TEMP_ENTITY: ERROR_INVALID_ENTITY},
                )

        if user_input.get(CONF_HUMIDITY_ENTITY):
            if not await self._validate_entity(user_input[CONF_HUMIDITY_ENTITY]):
                return self.async_show_form(
                    step_id=STEP_ENVIRONMENT,
                    data_schema=ENVIRONMENT_SCHEMA,
                    errors={CONF_HUMIDITY_ENTITY: ERROR_INVALID_ENTITY},
                )

        if user_input.get(CONF_OPTIMIZED_CHARGING_ENTITY):
            if not await self._validate_entity(
                user_input[CONF_OPTIMIZED_CHARGING_ENTITY]
            ):
                return self.async_show_form(
                    step_id=STEP_ENVIRONMENT,
                    data_schema=ENVIRONMENT_SCHEMA,
                    errors={CONF_OPTIMIZED_CHARGING_ENTITY: ERROR_INVALID_ENTITY},
                )

        self._data.update(user_input)
        return await self.async_step_optimized_charging()

    async def async_step_optimized_charging(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        """Handle optimized charging sensor configuration."""
        if user_input is None:
            return self.async_show_form(
                step_id=STEP_OPTIMIZED_CHARGING,
                data_schema=OPTIMIZED_CHARGING_SCHEMA,
                errors={},
            )

        # Store boolean setting
        self._data.update(user_input)

        # Generate unique ID for this device
        device_name = self._data[CONF_DEVICE_NAME]
        unique_id = f"{device_name}_{self._data[CONF_BATTERY_ENTITY]}"

        await self.async_set_unique_id(unique_id)
        self._abort_if_unique_id_configured()

        return self.async_create_entry(
            title=f"{INTEGRATION_NAME} - {device_name}",
            data=self._data,
        )

    async def _validate_entity(self, entity_id: str) -> bool:
        """Validate that an entity exists and is accessible."""
        try:
            entity_registry = er.async_get(self.hass)
            return entity_registry.async_get(entity_id) is not None
        except Exception:
            return False

    @staticmethod
    @callback
    def async_get_options_flow(
        config_entry: config_entries.ConfigEntry,
    ) -> OptionsFlowHandler:
        """Get the options flow for this handler."""
        return OptionsFlowHandler(config_entry)


class OptionsFlowHandler(config_entries.OptionsFlow):
    """Handle options flow for SmartCharge Predictor."""

    def __init__(self, config_entry: config_entries.ConfigEntry) -> None:
        """Initialize options flow."""
        self.config_entry = config_entry

    async def async_step_init(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        """Manage the options."""
        if user_input is not None:
            return self.async_create_entry(title="", data=user_input)

        options_schema = vol.Schema(
            {
                vol.Optional(
                    CONF_CHARGER_POWER,
                    default=self.config_entry.data.get(
                        CONF_CHARGER_POWER, DEFAULT_CHARGER_POWER
                    ),
                ): vol.All(vol.Coerce(float), vol.Range(min=1.0, max=1000.0)),
                vol.Optional(
                    CONF_BATTERY_HEALTH,
                    default=self.config_entry.data.get(
                        CONF_BATTERY_HEALTH, DEFAULT_BATTERY_HEALTH
                    ),
                ): vol.All(vol.Coerce(float), vol.Range(min=1.0, max=100.0)),
                vol.Optional(
                    CONF_LEARN_FROM_HISTORY,
                    default=self.config_entry.data.get(CONF_LEARN_FROM_HISTORY, True),
                ): bool,
                vol.Optional(
                    CONF_SCAN_INTERVAL,
                    default=self.config_entry.options.get(
                        CONF_SCAN_INTERVAL,
                        self.config_entry.data.get(
                            CONF_SCAN_INTERVAL, DEFAULT_SCAN_INTERVAL_SECONDS
                        ),
                    ),
                ): vol.All(vol.Coerce(int), vol.Range(min=30, max=300)),
                vol.Optional(
                    CONF_MAX_HISTORY_SAMPLES,
                    default=self.config_entry.options.get(
                        CONF_MAX_HISTORY_SAMPLES,
                        self.config_entry.data.get(
                            CONF_MAX_HISTORY_SAMPLES, DEFAULT_MAX_HISTORY_SAMPLES
                        ),
                    ),
                ): vol.All(
                    vol.Coerce(int),
                    vol.Range(min=MIN_MAX_HISTORY_SAMPLES, max=MAX_MAX_HISTORY_SAMPLES),
                ),
            }
        )

        return self.async_show_form(
            step_id=STEP_OPTIONS,
            data_schema=options_schema,
        )
