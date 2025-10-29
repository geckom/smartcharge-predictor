"""SmartCharge Predictor integration."""

from __future__ import annotations

import logging
from typing import Any
from datetime import timedelta
from pathlib import Path

import voluptuous as vol
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import Platform
from homeassistant.core import HomeAssistant, ServiceCall
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers.dispatcher import async_dispatcher_send
from homeassistant.util import dt as dt_util

from .const import (
    CONF_DEVICE_NAME,
    CONF_BATTERY_ENTITY,
    CONF_AMBIENT_TEMP_ENTITY,
    CONF_HUMIDITY_ENTITY,
    CONF_CHARGER_POWER,
    CONF_BATTERY_HEALTH,
    CONF_OPTIMIZED_CHARGING_ENABLED,
    CONF_LEARN_FROM_HISTORY,
    CONF_MAX_HISTORY_SAMPLES,
    DEFAULT_MAX_HISTORY_SAMPLES,
    DOMAIN,
    INTEGRATION_VERSION,
    SERVICE_EXPORT_DATA,
    SERVICE_RETRAIN,
    STORAGE_DIR,
    MODEL_FILE_SUFFIX,
)

_LOGGER = logging.getLogger(__name__)

PLATFORMS: list[Platform] = [Platform.BINARY_SENSOR, Platform.SENSOR]

# Config schema for YAML configuration (legacy support)
CONFIG_SCHEMA = vol.Schema({DOMAIN: vol.Schema({})}, extra=vol.ALLOW_EXTRA)


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Set up SmartCharge Predictor from a config entry."""
    hass.data.setdefault(DOMAIN, {})

    # Defer heavy imports to setup time to avoid import side effects during config flow load.
    from .coordinator import SmartChargeCoordinator
    from .history_manager import HistoryManager
    from .model import ChargingModel

    # Get device configuration (merge data and options).
    config = {**entry.data, **entry.options}
    device_name = config[CONF_DEVICE_NAME]
    device_id = f"{device_name}_{config['battery_entity']}"

    # Initialize components.
    history_manager = HistoryManager(hass)
    await history_manager.async_load()

    # Clean up orphaned devices (devices that no longer exist).
    # Collect all active device IDs from all config entries for this domain.
    active_device_ids: set[str] = set()

    # Get device IDs from already-loaded entries.
    for entry_id, entry_data in hass.data.get(DOMAIN, {}).items():
        if "device_id" in entry_data:
            active_device_ids.add(entry_data["device_id"])

    # Also get device IDs from all config entries (including not-yet-loaded ones).
    for entry in hass.config_entries.async_entries(DOMAIN):
        config = {**entry.data, **entry.options}
        if CONF_DEVICE_NAME in config and CONF_BATTERY_ENTITY in config:
            entry_device_id = (
                f"{config[CONF_DEVICE_NAME]}_{config[CONF_BATTERY_ENTITY]}"
            )
            active_device_ids.add(entry_device_id)

    # Also include current entry's device_id.
    active_device_ids.add(device_id)

    # Clean up orphaned history.
    orphaned_ids = history_manager.cleanup_orphaned_devices(active_device_ids)

    # Clean up orphaned model files.
    if orphaned_ids:
        storage_path = Path(hass.config.path(STORAGE_DIR))
        for orphaned_id in orphaned_ids:
            model_file = storage_path / f"{orphaned_id}{MODEL_FILE_SUFFIX}"
            if model_file.exists():
                try:
                    model_file.unlink()
                    _LOGGER.info("Removed orphaned model file: %s", model_file.name)
                except Exception as err:
                    _LOGGER.warning(
                        "Failed to remove orphaned model file %s: %s",
                        model_file.name,
                        err,
                    )

        # Save history after cleanup.
        await history_manager.async_save(immediate=True)

    # Set max history samples for this device.
    max_history_samples = config.get(
        CONF_MAX_HISTORY_SAMPLES, DEFAULT_MAX_HISTORY_SAMPLES
    )
    history_manager.set_max_history_samples(device_id, max_history_samples)

    charging_model = ChargingModel(hass, device_id, history_manager)
    await charging_model.async_load_model()

    coordinator = SmartChargeCoordinator(
        hass, device_id, config, history_manager, charging_model
    )

    # Store coordinator and components.
    hass.data[DOMAIN][entry.entry_id] = {
        "coordinator": coordinator,
        "history_manager": history_manager,
        "charging_model": charging_model,
        "device_id": device_id,
        "device_name": device_name,
    }

    # Create device entry.
    device_registry = dr.async_get(hass)
    device_registry.async_get_or_create(
        config_entry_id=entry.entry_id,
        identifiers={(DOMAIN, device_id)},
        name=device_name,
        manufacturer="SmartCharge Predictor",
        model="Charging Predictor",
        sw_version=INTEGRATION_VERSION,
    )

    # Forward to sensor platforms.
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)

    # Register services.
    await _register_services(hass)

    # Start coordinator.
    await coordinator.async_config_entry_first_refresh()

    _LOGGER.info("SmartCharge Predictor setup complete for device: %s", device_name)
    return True


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Unload a config entry."""
    unload_ok = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)

    if unload_ok:
        # Clean up data.
        if entry.entry_id in hass.data[DOMAIN]:
            coordinator = hass.data[DOMAIN][entry.entry_id]["coordinator"]
            history_manager = hass.data[DOMAIN][entry.entry_id]["history_manager"]

            # Clean up coordinator resources.
            coordinator._cleanup_state_listener()  # type: ignore[attr-defined]

            # Save history before cleanup (immediate save).
            await history_manager.async_save(immediate=True)

            del hass.data[DOMAIN][entry.entry_id]

        # Unregister services if this was the last entry.
        if not hass.data[DOMAIN]:
            await _unregister_services(hass)

    return unload_ok


async def _register_services(hass: HomeAssistant) -> None:
    """Register integration services."""
    if hass.services.has_service(DOMAIN, SERVICE_RETRAIN):
        return  # Services already registered.

    async def retrain_service(call: ServiceCall) -> None:
        """Handle retrain service call."""
        device_name = call.data.get("device_name")
        entity_id = call.data.get("entity_id")
        if not device_name and not entity_id:
            raise HomeAssistantError(
                "Provide either entity_id (preferred) or device_name"
            )

        # Resolve device by entity_id (preferred) or device_name.
        device_entry = None
        if entity_id:
            for _, data in hass.data[DOMAIN].items():
                if data["coordinator"].config.get("battery_entity") == entity_id:
                    device_entry = data
                    break
            if not device_entry:
                raise HomeAssistantError(
                    f"No SmartCharge device uses entity_id '{entity_id}'"
                )
        else:
            for _, data in hass.data[DOMAIN].items():
                if data["device_name"] == device_name:
                    device_entry = data
                    break
            if not device_entry:
                raise HomeAssistantError(f"Device '{device_name}' not found")

        try:
            # Check if learning is enabled.
            if not device_entry["coordinator"].config.get(
                CONF_LEARN_FROM_HISTORY, True
            ):
                raise HomeAssistantError(
                    f"Learning from history is disabled for device '{device_entry['device_name']}'. "
                    "Enable it in integration options to retrain models."
                )

            # Retrain the model.
            success = await device_entry["charging_model"].train_model()

            if success:
                # Trigger coordinator refresh.
                await device_entry["coordinator"].force_update()

                # Show notification (non-blocking service call).
                await hass.services.async_call(
                    "persistent_notification",
                    "create",
                    {
                        "message": f"Model retrained successfully for {device_entry['device_name']}",
                        "title": "SmartCharge Predictor",
                        "notification_id": f"smartcharge_retrain_{device_entry['device_name']}",
                    },
                    blocking=False,
                )
                _LOGGER.info(
                    "Model retrained successfully for device: %s",
                    device_entry["device_name"],
                )
            else:
                await hass.services.async_call(
                    "persistent_notification",
                    "create",
                    {
                        "message": f"Failed to retrain model for {device_entry['device_name']}. Check logs for details.",
                        "title": "SmartCharge Predictor",
                        "notification_id": f"smartcharge_retrain_error_{device_entry['device_name']}",
                    },
                    blocking=False,
                )
                _LOGGER.warning(
                    "Failed to retrain model for device: %s",
                    device_entry["device_name"],
                )

        except Exception as err:
            _LOGGER.error("Error during model retraining: %s", err)
            raise HomeAssistantError(f"Failed to retrain model: {err}")

    async def export_data_service(call: ServiceCall) -> None:
        """Handle export data service call."""
        device_name = call.data.get("device_name")
        if not device_name:
            raise HomeAssistantError("device_name is required")

        # Find the device.
        device_entry = None
        for entry_id, data in hass.data[DOMAIN].items():
            if data["device_name"] == device_name:
                device_entry = data
                break

        if not device_entry:
            raise HomeAssistantError(f"Device '{device_name}' not found")

        try:
            # Export data.
            filepath = await device_entry["history_manager"].export_csv(
                device_entry["device_id"]
            )

            if filepath:
                await hass.services.async_call(
                    "persistent_notification",
                    "create",
                    {
                        "message": f"Data exported successfully for {device_name} to: {filepath}",
                        "title": "SmartCharge Predictor",
                        "notification_id": f"smartcharge_export_{device_name}",
                    },
                    blocking=False,
                )
                _LOGGER.info(
                    "Data exported successfully for device: %s to %s",
                    device_name,
                    filepath,
                )
            else:
                await hass.services.async_call(
                    "persistent_notification",
                    "create",
                    {
                        "message": f"No data to export for {device_name}",
                        "title": "SmartCharge Predictor",
                        "notification_id": f"smartcharge_export_empty_{device_name}",
                    },
                    blocking=False,
                )
                _LOGGER.warning("No data to export for device: %s", device_name)

        except Exception as err:
            _LOGGER.error("Error during data export: %s", err)
            raise HomeAssistantError(f"Failed to export data: {err}")

    async def import_history_service(call: ServiceCall) -> None:
        """Import historical battery data from recorder and record samples once."""
        # Allow either days or hours; hours wins if both provided.
        days = call.data.get("days")
        hours = call.data.get("hours")
        now = dt_util.utcnow()
        if hours is not None:
            start = now - timedelta(hours=int(hours))
        elif days is not None:
            start = now - timedelta(days=int(days))
        else:
            start = now - timedelta(hours=48)

        # Use first loaded entry.
        if not hass.data.get(DOMAIN):
            raise HomeAssistantError("Integration not initialized")
        _, device_entry = next(iter(hass.data[DOMAIN].items()))

        coordinator = device_entry["coordinator"]
        history_manager = device_entry["history_manager"]
        config = coordinator.config
        device_id = coordinator.device_id
        battery_entity = config[CONF_BATTERY_ENTITY]
        temp_entity = config.get(CONF_AMBIENT_TEMP_ENTITY)
        humid_entity = config.get(CONF_HUMIDITY_ENTITY)

        # Recorder history API must be run in executor.
        from homeassistant.components.recorder import history as recorder_history  # noqa: PLC0415

        def _fetch_states():
            changes_map: dict[str, list] = {}

            # Use state_changes_during_period for maximum fidelity of numeric steps.
            # Note: state_changes_during_period only accepts a single entity_id (singular).
            # So we need to call it once per entity.
            batt_result = recorder_history.state_changes_during_period(  # type: ignore[attr-defined]
                hass,
                start_time=start,
                end_time=now,
                entity_id=battery_entity,
                no_attributes=True,
            )
            changes_map.update(batt_result)

            if temp_entity:
                temp_result = recorder_history.state_changes_during_period(  # type: ignore[attr-defined]
                    hass,
                    start_time=start,
                    end_time=now,
                    entity_id=temp_entity,
                    no_attributes=True,
                )
                changes_map.update(temp_result)

            if humid_entity:
                humid_result = recorder_history.state_changes_during_period(  # type: ignore[attr-defined]
                    hass,
                    start_time=start,
                    end_time=now,
                    entity_id=humid_entity,
                    no_attributes=True,
                )
                changes_map.update(humid_result)

            # Ensure chronological order.
            def _sorted_list(lst):
                return sorted(
                    lst,
                    key=lambda s: (s.last_changed or s.last_updated or now),
                )

            return (
                _sorted_list(changes_map.get(battery_entity, [])),
                _sorted_list(changes_map.get(temp_entity, [])) if temp_entity else [],
                _sorted_list(changes_map.get(humid_entity, [])) if humid_entity else [],
            )

        batt_states, temp_states, humid_states = await hass.async_add_executor_job(
            _fetch_states
        )
        if not batt_states:
            raise HomeAssistantError("No recorder history found for battery entity")

        _LOGGER.debug(
            "Importer fetched %s battery state rows (%s to %s)",
            len(batt_states),
            start.isoformat(),
            now.isoformat(),
        )

        def _value_at(states_list, ts):
            last_val = None
            for st in states_list:
                ref_ts = st.last_changed or st.last_updated
                if ref_ts and ref_ts <= ts:
                    try:
                        last_val = float(st.state)
                    except Exception:
                        continue
                else:
                    break
            return last_val

        # Always clear existing samples in the selected window before import.
        history_manager.clear_history_for_period(device_id, start, now)
        _LOGGER.debug(
            "Cleared history for device %s from %s to %s", device_id, start, now
        )

        prev = None
        imported = 0
        considered = 0
        no_change_count = 0
        decrease_count = 0
        for st in batt_states:
            try:
                ts = st.last_changed or st.last_updated or now
                pct = float(st.state)
            except Exception:
                continue
            considered += 1
            if prev is not None:
                prev_ts, prev_pct = prev
                minutes = (ts - prev_ts).total_seconds() / 60.0
                if minutes <= 0:
                    # Skip if time difference is invalid.
                    prev = (ts, pct)
                    continue

                # Calculate rate (can be positive, zero, or negative).
                rate = (pct - prev_pct) / minutes

                # Record sample for any change (matches normal operation behavior).
                # Normal operation records all changes and sets rate_pct_per_min=None for decreases.
                # Training filters out None rates, so decreases don't affect training.
                temp_val = _value_at(temp_states, ts) if temp_states else None
                humid_val = _value_at(humid_states, ts) if humid_states else None
                history_manager.record_sample(
                    device_id=device_id,
                    battery_pct=pct,
                    temperature=temp_val,
                    humidity=humid_val,
                    rate_pct_per_min=rate
                    if rate > 0
                    else None,  # None for decreases/same (like normal operation).
                    charger_power_w=config.get(CONF_CHARGER_POWER, 20.0),
                    optimized_charging=bool(
                        config.get(CONF_OPTIMIZED_CHARGING_ENABLED, False)
                    ),
                    battery_health=config.get(CONF_BATTERY_HEALTH, 100.0),
                )
                imported += 1
                if pct == prev_pct:
                    no_change_count += 1
                elif pct < prev_pct:
                    decrease_count += 1
            else:
                # First sample - record it with no rate.
                temp_val = _value_at(temp_states, ts) if temp_states else None
                humid_val = _value_at(humid_states, ts) if humid_states else None
                history_manager.record_sample(
                    device_id=device_id,
                    battery_pct=pct,
                    temperature=temp_val,
                    humidity=humid_val,
                    rate_pct_per_min=None,  # No rate for first sample.
                    charger_power_w=config.get(CONF_CHARGER_POWER, 20.0),
                    optimized_charging=bool(
                        config.get(CONF_OPTIMIZED_CHARGING_ENABLED, False)
                    ),
                    battery_health=config.get(CONF_BATTERY_HEALTH, 100.0),
                )
                imported += 1
            prev = (ts, pct)

        await history_manager.async_save(immediate=True)
        increases = (
            imported - no_change_count - decrease_count - 1
        )  # Subtract no-change, decrease samples and first sample.
        _LOGGER.info(
            "Import complete for %s: imported %s samples from %s history rows (%s increases, %s no-change, %s decreases)",
            device_entry["device_name"],
            imported,
            len(batt_states),
            increases,
            no_change_count,
            decrease_count,
        )
        await hass.services.async_call(
            "persistent_notification",
            "create",
            {
                "message": f"Imported {imported} historical samples for {device_entry['device_name']}",
                "title": "SmartCharge Predictor",
                "notification_id": f"smartcharge_import_{device_id}",
            },
            blocking=False,
        )

    # Register services.
    hass.services.async_register(
        DOMAIN,
        SERVICE_RETRAIN,
        retrain_service,
        schema=vol.Schema(
            {
                vol.Optional("entity_id"): str,
                vol.Optional("device_name"): str,  # Kept for backward compatibility.
            }
        ),
    )

    hass.services.async_register(
        DOMAIN,
        SERVICE_EXPORT_DATA,
        export_data_service,
        schema=vol.Schema(
            {
                vol.Required("device_name"): str,
            }
        ),
    )

    hass.services.async_register(
        DOMAIN,
        "import_history",
        import_history_service,
        schema=vol.Schema(
            {
                vol.Optional("hours"): vol.All(vol.Coerce(int), vol.Range(min=1)),
                vol.Optional("days"): vol.All(vol.Coerce(int), vol.Range(min=1)),
            }
        ),
    )

    _LOGGER.info("SmartCharge Predictor services registered")


async def _unregister_services(hass: HomeAssistant) -> None:
    """Unregister integration services."""
    hass.services.async_remove(DOMAIN, SERVICE_RETRAIN)
    hass.services.async_remove(DOMAIN, SERVICE_EXPORT_DATA)
    hass.services.async_remove(DOMAIN, "import_history")
    _LOGGER.info("SmartCharge Predictor services unregistered")


class SmartChargeError(HomeAssistantError):
    """Base exception for SmartCharge Predictor."""


class SmartChargeConnectionError(SmartChargeError):
    """Exception for connection errors."""


class SmartChargeInvalidEntityError(SmartChargeError):
    """Exception for invalid entity errors."""
