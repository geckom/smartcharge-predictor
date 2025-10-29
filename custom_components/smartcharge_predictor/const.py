"""Constants for the SmartCharge Predictor integration."""

from datetime import timedelta

# Integration info
DOMAIN = "smartcharge_predictor"
INTEGRATION_NAME = "SmartCharge Predictor"
INTEGRATION_VERSION = "2025.10.1"

# Default charge rates (% per minute)
DEFAULT_FAST_RATE = 0.55  # 0-80% battery
DEFAULT_SLOW_RATE = 0.25  # 80-100% battery

# Battery level thresholds
FAST_CHARGE_THRESHOLD = 80.0

# Correction factors
TEMP_HIGH_THRESHOLD = 30.0  # Celsius
TEMP_REDUCTION_MIN = 0.10  # Minimum reduction (10%)
TEMP_REDUCTION_MAX = 0.15  # Maximum reduction (15%)
HEALTH_LOW_THRESHOLD = 90.0  # Battery health %
HEALTH_REDUCTION_FACTOR = 0.90  # Reduce rate by 10% below 90% health

# Update intervals
DEFAULT_SCAN_INTERVAL = timedelta(minutes=1)
MIN_SCAN_INTERVAL = timedelta(seconds=30)
MAX_SCAN_INTERVAL = timedelta(minutes=5)

# Storage paths
STORAGE_DIR = f".storage/{DOMAIN}"
HISTORY_FILE_SUFFIX = "_history.json"
MODEL_FILE_SUFFIX = "_model.pkl"

# Entity attributes
ATTR_BATTERY_PCT = "battery_percentage"
ATTR_CHARGE_RATE = "charge_rate"
ATTR_TEMPERATURE = "temperature"
ATTR_HUMIDITY = "humidity"
ATTR_CHARGER_POWER = "charger_power_w"
ATTR_BATTERY_HEALTH = "battery_health"
ATTR_OPTIMIZED_CHARGING = "optimized_charging"
ATTR_MODEL_TYPE = "model_type"
ATTR_LAST_TRAINING = "last_training"
ATTR_LAST_UPDATED = "last_updated"
ATTR_TIME_REMAINING_MINUTES = "time_remaining_minutes"

# Device classes
DEVICE_CLASS_DURATION = "duration"
DEVICE_CLASS_TIMESTAMP = "timestamp"

# Units
UNIT_PERCENT_PER_MINUTE = "%/min"
UNIT_MINUTES = "min"

# ML training
MIN_SAMPLES_FOR_TRAINING = 20
ML_MODEL_TYPE = "learned"
EMPIRICAL_MODEL_TYPE = "empirical"

# Service names
SERVICE_RETRAIN = "retrain"
SERVICE_EXPORT_DATA = "export_data"

# Configuration keys
CONF_AMBIENT_TEMP_ENTITY = "ambient_temp_entity"
CONF_BATTERY_ENTITY = "battery_entity"
CONF_BATTERY_HEALTH = "battery_health"
CONF_CHARGER_POWER = "charger_power_w"
CONF_DEVICE_NAME = "name"
CONF_HUMIDITY_ENTITY = "humidity_entity"
CONF_LEARN_FROM_HISTORY = "learn_from_history"
CONF_OPTIMIZED_CHARGING_ENABLED = "optimized_charging_enabled"
CONF_OPTIMIZED_CHARGING_ENTITY = "optimized_charging_entity"
CONF_SCAN_INTERVAL = "scan_interval"
CONF_MAX_HISTORY_SAMPLES = "max_history_samples"

# Config flow steps
STEP_USER = "user"
STEP_DEVICE_DETAILS = "device_details"
STEP_ENVIRONMENT = "environment"
STEP_OPTIMIZED_CHARGING = "optimized_charging"
STEP_OPTIONS = "options"

# Error messages
ERROR_CANNOT_CONNECT = "cannot_connect"
ERROR_INVALID_ENTITY = "invalid_entity"
ERROR_INVALID_NUMBER = "invalid_number"
ERROR_UNKNOWN = "unknown"

# Default values
DEFAULT_CHARGER_POWER = 20.0  # Watts
DEFAULT_BATTERY_HEALTH = 100.0
DEFAULT_SCAN_INTERVAL_SECONDS = 60  # seconds
# Default max history: ~30 days at max scan interval (300s) = 8,640 samples, rounded to 10,000
DEFAULT_MAX_HISTORY_SAMPLES = 10000
MIN_MAX_HISTORY_SAMPLES = 100  # Minimum samples for reasonable ML training
MAX_MAX_HISTORY_SAMPLES = 100000  # Maximum samples to prevent excessive storage

# Entity IDs
ENTITY_ID_TIME_REMAINING = "charge_time_remaining"
ENTITY_ID_FULL_CHARGE_TIME = "full_charge_time"
ENTITY_ID_PREDICTED_RATE = "predicted_rate"
ENTITY_ID_OPTIMIZED_CHARGING = "optimized_charging"
