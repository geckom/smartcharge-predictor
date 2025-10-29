"""History manager for SmartCharge Predictor integration."""

from __future__ import annotations

import csv
import logging
from collections.abc import Callable
from datetime import datetime
from pathlib import Path
from typing import Any, Optional

from homeassistant.core import HomeAssistant, Event
from homeassistant.const import EVENT_HOMEASSISTANT_STOP
from homeassistant.util import dt as dt_util
from homeassistant.helpers.storage import Store
from homeassistant.helpers.event import async_call_later

_LOGGER = logging.getLogger(__name__)

STORAGE_VERSION = 1
STORAGE_KEY = "smartcharge_predictor_history"


class HistoryManager:
    """Manages charging history data for devices."""

    def __init__(self, hass: HomeAssistant) -> None:
        """Initialize the history manager."""
        self.hass = hass
        self._store = Store(hass, STORAGE_VERSION, STORAGE_KEY)
        self._history: dict[str, list[dict[str, Any]]] = {}
        self._save_timer: Optional[Callable[[], None]] = None
        # Per-device max history limits (default applied if not set).
        self._max_history_limits: dict[str, int] = {}

        # Register shutdown listener for immediate save.
        hass.bus.async_listen_once(EVENT_HOMEASSISTANT_STOP, self._async_shutdown_save)

    def set_max_history_samples(self, device_id: str, max_samples: int) -> None:
        """Set maximum history samples for a device."""
        self._max_history_limits[device_id] = max_samples

    def get_max_history_samples(self, device_id: str, default: int) -> int:
        """Get maximum history samples for a device."""
        return self._max_history_limits.get(device_id, default)

    async def async_load(self) -> None:
        """Load history data from storage."""
        try:
            data = await self._store.async_load()
            if data:
                self._history = data.get("history", {})
                _LOGGER.debug("Loaded history for %d devices", len(self._history))
        except Exception as err:
            _LOGGER.error("Failed to load history data: %s", err)
            self._history = {}

    async def async_save(self, immediate: bool = False) -> None:
        """Save history data to storage with debouncing."""
        # Cancel existing timer if any.
        if self._save_timer:
            self._save_timer()
            self._save_timer = None

        if immediate:
            # Save immediately (e.g., on shutdown).
            await self._do_save()
        else:
            # Debounce: schedule save after 5 minutes of inactivity.
            self._save_timer = async_call_later(
                self.hass, 300.0, self._async_save_callback
            )

    async def _async_save_callback(self, _now: datetime) -> None:
        """Callback for debounced save."""
        self._save_timer = None
        await self._do_save()

    async def _do_save(self) -> None:
        """Perform the actual save operation."""
        try:
            await self._store.async_save({"history": self._history})
            device_count = len(self._history)
            if device_count > 0:
                total_samples = sum(len(samples) for samples in self._history.values())
                device_ids = list(self._history.keys())
                _LOGGER.debug(
                    "Saved history for %d device(s) (%d total samples): %s",
                    device_count,
                    total_samples,
                    ", ".join(device_ids),
                )
            else:
                _LOGGER.debug("Saved history (no devices)")
        except Exception as err:
            _LOGGER.error("Failed to save history data: %s", err)

    async def _async_shutdown_save(self, _event: Event) -> None:
        """Save history immediately on shutdown."""
        if self._save_timer:
            self._save_timer()
            self._save_timer = None
        await self._do_save()

    def record_sample(
        self,
        device_id: str,
        battery_pct: float,
        temperature: Optional[float] = None,
        humidity: Optional[float] = None,
        rate_pct_per_min: Optional[float] = None,
        charger_power_w: Optional[float] = None,
        optimized_charging: Optional[bool] = None,
        battery_health: Optional[float] = None,
        max_history_samples: Optional[int] = None,
    ) -> None:
        """Record a charging sample for a device."""
        if device_id not in self._history:
            self._history[device_id] = []

        sample = {
            "timestamp": dt_util.utcnow().isoformat(),
            "battery_pct": battery_pct,
            "temperature": temperature,
            "humidity": humidity,
            "rate_pct_per_min": rate_pct_per_min,
            "charger_power_w": charger_power_w,
            "optimized_charging": optimized_charging,
            "battery_health": battery_health,
        }

        # Remove None values to keep data clean.
        sample = {k: v for k, v in sample.items() if v is not None}

        self._history[device_id].append(sample)

        # Get max history limit for this device (use provided value or stored limit).
        if max_history_samples is None:
            # Use stored limit if available, otherwise keep all (will be set when device is configured).
            max_history_samples = self._max_history_limits.get(device_id)

        # Keep only last N samples per device to prevent unlimited growth.
        if (
            max_history_samples is not None
            and len(self._history[device_id]) > max_history_samples
        ):
            self._history[device_id] = self._history[device_id][-max_history_samples:]

        _LOGGER.debug(
            "Recorded sample for device %s: battery=%s%%, rate=%s%%/min",
            device_id,
            battery_pct,
            rate_pct_per_min,
        )

    def get_history(self, device_id: str) -> list[dict[str, Any]]:
        """Get charging history for a device."""
        return self._history.get(device_id, [])

    def clear_history(self, device_id: str) -> None:
        """Clear charging history for a device."""
        if device_id in self._history:
            del self._history[device_id]
            _LOGGER.info("Cleared history for device %s", device_id)

    def cleanup_orphaned_devices(self, active_device_ids: set[str]) -> list[str]:
        """Remove history for devices that no longer exist."""
        orphaned_device_ids = []
        for device_id in list(self._history.keys()):
            if device_id not in active_device_ids:
                orphaned_device_ids.append(device_id)
                sample_count = len(self._history[device_id])
                del self._history[device_id]
                # Also remove max history limit for orphaned device.
                if device_id in self._max_history_limits:
                    del self._max_history_limits[device_id]
                _LOGGER.info(
                    "Cleaned up orphaned history for device %s (%d samples removed)",
                    device_id,
                    sample_count,
                )

        if orphaned_device_ids:
            _LOGGER.info(
                "Cleaned up history for %d orphaned device(s): %s",
                len(orphaned_device_ids),
                ", ".join(orphaned_device_ids),
            )

        return orphaned_device_ids

    def clear_history_for_period(
        self, device_id: str, start_time: datetime, end_time: datetime
    ) -> None:
        """Clear charging history for a device within a specific time period."""
        if device_id not in self._history:
            return

        # Filter out samples within the specified time range.
        # Keep samples that are before the start_time or after the end_time.
        filtered_samples = []
        for sample in self._history[device_id]:
            ts_str = sample.get("timestamp")
            if not ts_str:
                continue
            ts = dt_util.parse_datetime(ts_str)
            if ts is None:
                continue
            # Keep sample if it's outside the time range.
            if ts < start_time or ts > end_time:
                filtered_samples.append(sample)

        self._history[device_id] = filtered_samples
        _LOGGER.info(
            "Cleared history for device %s from %s to %s",
            device_id,
            start_time,
            end_time,
        )

    def get_sample_count(self, device_id: str) -> int:
        """Get the number of samples for a device."""
        return len(self._history.get(device_id, []))

    def get_latest_sample(self, device_id: str) -> Optional[dict[str, Any]]:
        """Get the most recent sample for a device."""
        history = self._history.get(device_id, [])
        return history[-1] if history else None

    def calculate_rate_from_samples(
        self, device_id: str, current_battery_pct: float
    ) -> Optional[float]:
        """Calculate charging rate from recent samples."""
        history = self._history.get(device_id, [])
        if len(history) < 2:
            return None

        # Get the most recent sample.
        latest_sample = history[-1]
        latest_battery = latest_sample.get("battery_pct")
        latest_timestamp = latest_sample.get("timestamp")

        if latest_battery is None or latest_timestamp is None:
            return None

        # Calculate time difference.
        try:
            latest_time = dt_util.parse_datetime(latest_timestamp)
            if latest_time is None:
                return None
            current_time = dt_util.utcnow()
            time_diff_seconds = (current_time - latest_time).total_seconds()

            if (
                time_diff_seconds <= 0 or time_diff_seconds > 300
            ):  # Ignore old or invalid data (>300 seconds = 5 minutes).
                return None

            time_diff_minutes = time_diff_seconds / 60.0

            # Calculate rate.
            battery_diff = current_battery_pct - latest_battery
            if battery_diff <= 0:  # Not charging.
                return None

            rate = battery_diff / time_diff_minutes
            return max(0.0, rate)  # Ensure positive rate.

        except (ValueError, TypeError) as err:
            _LOGGER.warning("Failed to calculate rate from samples: %s", err)
            return None

    async def export_csv(self, device_id: str) -> Optional[str]:
        """Export device history to CSV file."""
        history = self._history.get(device_id, [])
        if not history:
            _LOGGER.warning("No history data to export for device %s", device_id)
            return None

        # Create exports directory.
        exports_dir = Path(self.hass.config.path("smartcharge_predictor_exports"))
        exports_dir.mkdir(exist_ok=True)

        # Generate filename with timestamp.
        timestamp = datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
        filename = f"{device_id}_history_{timestamp}.csv"
        filepath = exports_dir / filename

        try:
            with open(filepath, "w", newline="", encoding="utf-8") as csvfile:
                if not history:
                    return None

                # Get all possible fieldnames from all samples.
                fieldnames = set()
                for sample in history:
                    fieldnames.update(sample.keys())
                fieldnames = sorted(list(fieldnames))

                writer = csv.DictWriter(csvfile, fieldnames=fieldnames)
                writer.writeheader()
                writer.writerows(history)

            _LOGGER.info("Exported history for device %s to %s", device_id, filepath)
            return str(filepath)

        except Exception as err:
            _LOGGER.error("Failed to export CSV for device %s: %s", device_id, err)
            return None

    def get_devices(self) -> list[str]:
        """Get list of all device IDs with history."""
        return list(self._history.keys())

    def get_statistics(self, device_id: str) -> dict[str, Any]:
        """Get charging statistics for a device."""
        history = self._history.get(device_id, [])
        if not history:
            return {}

        # Calculate basic statistics.
        rates = [
            s.get("rate_pct_per_min")
            for s in history
            if s.get("rate_pct_per_min") is not None
        ]
        temperatures = [
            s.get("temperature") for s in history if s.get("temperature") is not None
        ]

        stats = {
            "total_samples": len(history),
            "date_range": {
                "first": history[0].get("timestamp") if history else None,
                "last": history[-1].get("timestamp") if history else None,
            },
        }

        if rates:
            stats["rate_stats"] = {
                "min": min(rates),
                "max": max(rates),
                "avg": sum(rates) / len(rates),
            }

        if temperatures:
            stats["temperature_stats"] = {
                "min": min(temperatures),
                "max": max(temperatures),
                "avg": sum(temperatures) / len(temperatures),
            }

        return stats
