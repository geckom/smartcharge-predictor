"""Charging model for SmartCharge Predictor integration."""

from __future__ import annotations

import logging
import pickle
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Optional

from homeassistant.core import HomeAssistant
from homeassistant.util import dt as dt_util

from .const import (
    ATTR_BATTERY_HEALTH,
    ATTR_CHARGER_POWER,
    ATTR_HUMIDITY,
    ATTR_OPTIMIZED_CHARGING,
    ATTR_TEMPERATURE,
    DEFAULT_FAST_RATE,
    DEFAULT_SLOW_RATE,
    EMPIRICAL_MODEL_TYPE,
    FAST_CHARGE_THRESHOLD,
    HEALTH_LOW_THRESHOLD,
    HEALTH_REDUCTION_FACTOR,
    ML_MODEL_TYPE,
    MIN_SAMPLES_FOR_TRAINING,
    MODEL_FILE_SUFFIX,
    STORAGE_DIR,
    TEMP_HIGH_THRESHOLD,
    TEMP_REDUCTION_MIN,
    TEMP_REDUCTION_MAX,
)
from .history_manager import HistoryManager

_LOGGER = logging.getLogger(__name__)

# Lazy ML import to avoid blocking the event loop at import time.
SKLEARN_AVAILABLE = False


def _import_ml_libs() -> dict[str, Any]:
    """Import heavy ML libraries in a background thread and return refs."""
    try:
        # Imports happen in a worker thread; return references.
        from sklearn.linear_model import LinearRegression  # type: ignore[import-not-found]
        from sklearn.ensemble import RandomForestRegressor  # type: ignore[import-not-found]
        from sklearn.model_selection import train_test_split  # type: ignore[import-not-found]
        from sklearn.metrics import mean_squared_error, r2_score  # type: ignore[import-not-found]
        import numpy as np  # type: ignore[import-not-found]

        return {
            "LinearRegression": LinearRegression,
            "RandomForestRegressor": RandomForestRegressor,
            "train_test_split": train_test_split,
            "mean_squared_error": mean_squared_error,
            "r2_score": r2_score,
            "np": np,
        }
    except Exception as exc:  # Broad to handle any optional dep import failure.
        # We cannot log here (no hass), caller will handle.
        raise exc


class ChargingModel:
    """Charging prediction model with empirical and ML capabilities."""

    def __init__(
        self, hass: HomeAssistant, device_id: str, history_manager: HistoryManager
    ) -> None:
        """Initialize the charging model."""
        self.hass = hass
        self.device_id = device_id
        self.history_manager = history_manager
        self.model_type = EMPIRICAL_MODEL_TYPE
        self.ml_model = None
        self.last_training = None
        self.model_accuracy = None
        self.empirical_accuracy = None
        self.selected_model_type = EMPIRICAL_MODEL_TYPE
        self._ml_refs: Optional[dict[str, Any]] = None

        # Model storage path.
        self.storage_path = Path(hass.config.path(STORAGE_DIR))
        self.storage_path.mkdir(parents=True, exist_ok=True)
        self.model_file = self.storage_path / f"{device_id}{MODEL_FILE_SUFFIX}"

    async def _async_ensure_ml(self) -> bool:
        """Ensure ML libraries are imported without blocking the event loop."""
        global SKLEARN_AVAILABLE
        if self._ml_refs is not None:
            return True
        try:
            refs = await self.hass.async_add_executor_job(_import_ml_libs)
        except Exception:
            SKLEARN_AVAILABLE = False
            if self._ml_refs is None:
                _LOGGER.debug("scikit-learn not available - using empirical model only")
            return False
        self._ml_refs = refs
        SKLEARN_AVAILABLE = True
        _LOGGER.info("Scikit-learn available - ML features enabled")
        return True

    async def async_load_model(self) -> None:
        """Load trained model from storage if available."""
        if not await self._async_ensure_ml():
            return

        try:
            if self.model_file.exists():
                # Load model file in executor to avoid blocking event loop.
                def _load_model():
                    with open(self.model_file, "rb") as f:
                        return pickle.load(f)

                model_data = await self.hass.async_add_executor_job(_load_model)
                self.ml_model = model_data.get("model")
                self.last_training = model_data.get("last_training")
                self.model_accuracy = model_data.get("accuracy")
                self.empirical_accuracy = model_data.get("empirical_accuracy")
                self.selected_model_type = model_data.get(
                    "selected_model_type", ML_MODEL_TYPE
                )
                self.model_type = self.selected_model_type
                _LOGGER.info(
                    "Loaded ML model for device %s (accuracy: %.3f)",
                    self.device_id,
                    self.model_accuracy or 0.0,
                )
        except Exception as err:
            _LOGGER.warning(
                "Failed to load ML model for device %s: %s", self.device_id, err
            )
            self.ml_model = None
            self.model_type = EMPIRICAL_MODEL_TYPE

    async def async_save_model(self) -> None:
        """Save trained model to storage."""
        if not SKLEARN_AVAILABLE or not self.ml_model:
            return

        try:
            model_data = {
                "model": self.ml_model,
                "last_training": self.last_training,
                "accuracy": self.model_accuracy,
                "empirical_accuracy": self.empirical_accuracy,
                "selected_model_type": self.selected_model_type,
            }
            with open(self.model_file, "wb") as f:
                pickle.dump(model_data, f)
            _LOGGER.info("Saved ML model for device %s", self.device_id)
        except Exception as err:
            _LOGGER.error(
                "Failed to save ML model for device %s: %s", self.device_id, err
            )

    def predict_rate(
        self,
        battery_pct: float,
        temperature: Optional[float] = None,
        humidity: Optional[float] = None,
        charger_power_w: Optional[float] = None,
        battery_health: Optional[float] = None,
        optimized_charging: Optional[bool] = None,
    ) -> float:
        """Predict charging rate based on current conditions."""
        # Use selected model type (determined by accuracy comparison).
        if self.selected_model_type == ML_MODEL_TYPE and self.ml_model:
            return self._predict_with_ml(
                battery_pct,
                temperature,
                humidity,
                charger_power_w,
                battery_health,
                optimized_charging,
            )
        else:
            return self._predict_empirical(
                battery_pct,
                temperature,
                humidity,
                charger_power_w,
                battery_health,
                optimized_charging,
            )

    def _predict_empirical(
        self,
        battery_pct: float,
        temperature: Optional[float] = None,
        humidity: Optional[float] = None,
        charger_power_w: Optional[float] = None,
        battery_health: Optional[float] = None,
        optimized_charging: Optional[bool] = None,
    ) -> float:
        """Predict charging rate using empirical model."""
        # Base rate based on battery level.
        if battery_pct < FAST_CHARGE_THRESHOLD:
            base_rate = DEFAULT_FAST_RATE
        else:
            base_rate = DEFAULT_SLOW_RATE

        # Apply correction factors.
        correction_factor = 1.0

        # Temperature correction (variable 10-15% reduction).
        if temperature is not None and temperature > TEMP_HIGH_THRESHOLD:
            # Calculate variable reduction: 10% + (temperature - 30) * 0.05 / 10.
            # Caps between TEMP_REDUCTION_MIN and TEMP_REDUCTION_MAX.
            temp_excess = temperature - TEMP_HIGH_THRESHOLD
            reduction = min(
                TEMP_REDUCTION_MAX,
                max(
                    TEMP_REDUCTION_MIN,
                    TEMP_REDUCTION_MIN + (temp_excess * 0.05 / 10.0),
                ),
            )
            correction_factor *= 1.0 - reduction

        # Battery health correction.
        if battery_health is not None and battery_health < HEALTH_LOW_THRESHOLD:
            correction_factor *= HEALTH_REDUCTION_FACTOR

        # Optimized charging correction (clamp rate after 80%).
        if optimized_charging and battery_pct >= FAST_CHARGE_THRESHOLD:
            correction_factor *= 0.5  # Significantly reduce rate.

        # Charger power correction (normalize to 20W baseline).
        if charger_power_w is not None:
            power_factor = min(charger_power_w / 20.0, 2.0)  # Cap at 2x.
            correction_factor *= power_factor

        predicted_rate = base_rate * correction_factor
        return max(0.01, predicted_rate)  # Minimum rate to prevent zero.

    def _predict_with_ml(
        self,
        battery_pct: float,
        temperature: Optional[float] = None,
        humidity: Optional[float] = None,
        charger_power_w: Optional[float] = None,
        battery_health: Optional[float] = None,
        optimized_charging: Optional[bool] = None,
    ) -> float:
        """Predict charging rate using trained ML model."""
        if not self.ml_model:
            return self._predict_empirical(
                battery_pct,
                temperature,
                humidity,
                charger_power_w,
                battery_health,
                optimized_charging,
            )

        try:
            # Prepare features for prediction.
            features = [
                battery_pct,
                temperature or 20.0,  # Default temperature.
                humidity or 50.0,  # Default humidity.
                charger_power_w or 20.0,  # Default power.
                battery_health or 100.0,  # Default health.
                1.0 if optimized_charging else 0.0,  # Binary flag.
            ]

            # Predict rate.
            predicted_rate = self.ml_model.predict([features])[0]
            return max(0.01, predicted_rate)  # Ensure positive rate.

        except Exception as err:
            _LOGGER.warning(
                "ML prediction failed for device %s: %s", self.device_id, err
            )
            # Fallback to empirical model.
            return self._predict_empirical(
                battery_pct,
                temperature,
                humidity,
                charger_power_w,
                battery_health,
                optimized_charging,
            )

    def _evaluate_empirical_accuracy(
        self, X_test: list[list[float]], y_test: list[float]
    ) -> float:
        """Evaluate empirical model accuracy on test data."""
        y_pred_empirical = []
        for features in X_test:
            battery_pct = features[0]
            temperature = features[1] if len(features) > 1 else None
            humidity = features[2] if len(features) > 2 else None
            charger_power_w = features[3] if len(features) > 3 else None
            battery_health = features[4] if len(features) > 4 else None
            optimized_charging = bool(features[5]) if len(features) > 5 else False

            predicted_rate = self._predict_empirical(
                battery_pct,
                temperature,
                humidity,
                charger_power_w,
                battery_health,
                optimized_charging,
            )
            y_pred_empirical.append(predicted_rate)

        r2 = self._ml_refs["r2_score"](y_test, y_pred_empirical)
        return r2

    async def train_model(self) -> bool:
        """Train ML model using historical data."""
        if not await self._async_ensure_ml():
            _LOGGER.debug("Scikit-learn not available - skipping ML training")
            return False

        history = self.history_manager.get_history(self.device_id)
        if len(history) < MIN_SAMPLES_FOR_TRAINING:
            _LOGGER.info(
                "Insufficient samples for training (%d < %d)",
                len(history),
                MIN_SAMPLES_FOR_TRAINING,
            )
            return False

        try:
            # Prepare training data.
            X, y = self._prepare_training_data(history)
            if len(X) < MIN_SAMPLES_FOR_TRAINING:
                return False

            # Split data for validation.
            X_train, X_test, y_train, y_test = self._ml_refs["train_test_split"](
                X, y, test_size=0.2, random_state=42
            )

            # Train LinearRegression model.
            lr_model = self._ml_refs["LinearRegression"]()
            lr_model.fit(X_train, y_train)
            lr_pred = lr_model.predict(X_test)
            lr_r2 = self._ml_refs["r2_score"](y_test, lr_pred)
            lr_mse = self._ml_refs["mean_squared_error"](y_test, lr_pred)

            # Train RandomForest model.
            rf_model = self._ml_refs["RandomForestRegressor"](
                n_estimators=100, random_state=42, max_depth=10
            )
            rf_model.fit(X_train, y_train)
            rf_pred = rf_model.predict(X_test)
            rf_r2 = self._ml_refs["r2_score"](y_test, rf_pred)
            rf_mse = self._ml_refs["mean_squared_error"](y_test, rf_pred)

            # Evaluate empirical model accuracy.
            empirical_r2 = self._evaluate_empirical_accuracy(X_test, y_test)

            # Select best model based on R² score.
            model_options = [
                ("linear", lr_model, lr_r2, lr_mse),
                ("random_forest", rf_model, rf_r2, rf_mse),
                ("empirical", None, empirical_r2, None),
            ]
            best_model_name, best_model, best_r2, best_mse = max(
                model_options, key=lambda x: x[2]
            )

            # Store selected model and accuracies.
            if best_model_name == "empirical":
                self.selected_model_type = EMPIRICAL_MODEL_TYPE
                self.model_type = EMPIRICAL_MODEL_TYPE
                self.ml_model = None
            else:
                self.selected_model_type = ML_MODEL_TYPE
                self.model_type = ML_MODEL_TYPE
                self.ml_model = best_model

            self.model_accuracy = best_r2
            self.empirical_accuracy = empirical_r2
            self.last_training = datetime.now().isoformat()

            _LOGGER.info(
                "Trained models for device %s: LinearRegression R²=%.3f, RandomForest R²=%.3f, Empirical R²=%.3f",
                self.device_id,
                lr_r2,
                rf_r2,
                empirical_r2,
            )
            _LOGGER.info(
                "Selected %s model for device %s (R²=%.3f)",
                best_model_name,
                self.device_id,
                best_r2,
            )

            # Save model.
            await self.async_save_model()

            return True

        except Exception as err:
            _LOGGER.error(
                "Failed to train ML model for device %s: %s", self.device_id, err
            )
            return False

    def _prepare_training_data(
        self, history: list[dict[str, Any]]
    ) -> tuple[list[list[float]], list[float]]:
        """Prepare training data from history."""
        X = []  # Features.
        y = []  # Target (rate).

        for sample in history:
            # Skip samples without rate data.
            rate = sample.get("rate_pct_per_min")
            if rate is None or rate <= 0:
                continue

            # Extract features.
            features = [
                sample.get("battery_pct", 0.0),
                sample.get("temperature", 20.0),
                sample.get("humidity", 50.0),
                sample.get("charger_power_w", 20.0),
                sample.get("battery_health", 100.0),
                1.0 if sample.get("optimized_charging") else 0.0,
            ]

            X.append(features)
            y.append(rate)

        return X, y

    def calculate_time_remaining(
        self, battery_pct: float, predicted_rate: float
    ) -> float:
        """Calculate time remaining until 100% charge."""
        if predicted_rate <= 0 or battery_pct >= 100:
            return 0.0

        remaining_percentage = 100.0 - battery_pct
        time_remaining = remaining_percentage / predicted_rate
        return max(0.0, time_remaining)

    def calculate_full_charge_time(self, time_remaining_minutes: float) -> datetime:
        """Calculate datetime when device will be fully charged."""
        if time_remaining_minutes <= 0:
            return dt_util.utcnow()

        return dt_util.utcnow() + timedelta(minutes=time_remaining_minutes)

    def get_model_info(self) -> dict[str, Any]:
        """Get information about the current model."""
        info = {
            "model_type": self.selected_model_type,
            "last_training": self.last_training,
            "accuracy": self.model_accuracy,
            "empirical_accuracy": self.empirical_accuracy,
            "sample_count": self.history_manager.get_sample_count(self.device_id),
            "sklearn_available": SKLEARN_AVAILABLE,
        }

        if self.selected_model_type == ML_MODEL_TYPE and self.ml_model:
            if hasattr(self.ml_model, "coef_"):
                # LinearRegression.
                info["model_coefficients"] = self.ml_model.coef_.tolist()
                info["model_intercept"] = self.ml_model.intercept_
            elif hasattr(self.ml_model, "feature_importances_"):
                # RandomForest.
                info["feature_importances"] = (
                    self.ml_model.feature_importances_.tolist()
                )

        return info

    def should_retrain(self) -> bool:
        """Check if model should be retrained."""
        if not SKLEARN_AVAILABLE:
            return False

        sample_count = self.history_manager.get_sample_count(self.device_id)

        # Retrain if we have enough new samples since last training.
        if self.last_training is None:
            return sample_count >= MIN_SAMPLES_FOR_TRAINING

        try:
            last_training_time = datetime.fromisoformat(self.last_training)
            time_since_training = datetime.now() - last_training_time

            # Retrain if it's been more than 24 hours and we have new samples.
            return (
                time_since_training.total_seconds() > 86400
                and sample_count >= MIN_SAMPLES_FOR_TRAINING
            )
        except (ValueError, TypeError):
            return sample_count >= MIN_SAMPLES_FOR_TRAINING
