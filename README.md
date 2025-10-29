# SmartCharge Predictor

## Overview

SmartCharge Predictor is a Home Assistant custom component that adds predictive charging entities for any battery sensor you configure. It estimates the time remaining to full charge, the timestamp when charge will complete, and the current predicted charging rate. Under the hood, it combines a reliable empirical model with optional machine learning (LinearRegression and RandomForest) trained on your device's historical data to improve accuracy over time. It also supports optimized charging detection (via entity, setting, or behavior), immediate updates on state change, configurable scan interval, and safe, debounced history storage.

## Features

- **Accurate Predictions**: Estimates time remaining until devices are fully charged
- **Multiple Models**: Uses empirical piecewise models with optional ML enhancement
- **Learning Capability**: Learns from historical charging data to improve accuracy
- **Environment Awareness**: Considers temperature, humidity, and battery health
- **Multiple Sensors**: Provides time remaining, full charge time, and charge rate
- **Easy Configuration**: Simple UI-based setup process
- **Data Export**: Export charging history for analysis
- **Smart Updates**: Immediate updates on battery state changes plus configurable polling

## Installation

### Requirements

- Home Assistant 2024.6 or later

### Manual Installation

1. **Download or clone this repository**
   - If downloading: Extract the ZIP file
   - If cloning: `git clone <repository-url>`

2. **Copy the integration folder**
   - Copy the `custom_components/smartcharge_predictor` folder from this repository
   - Paste it into your Home Assistant `custom_components` directory
   - The final path should be: `<home-assistant-config>/custom_components/smartcharge_predictor/`

3. **Restart Home Assistant**
   - Go to Settings → System → Restart
   - Or restart your Home Assistant instance through your hosting method

4. **Add the integration**
   - Go to Settings → Devices & Services → Add Integration
   - Search for "SmartCharge Predictor" and click on it
   - Follow the configuration flow to set up your first device

**Note**: If you don't have a `custom_components` folder in your Home Assistant configuration directory, create it first.

### HACS Installation (Future)

This integration will be available through HACS in the future.

## Configuration

### Setup Process

1. **Select Battery Entity**: Choose the battery sensor for your device
2. **Device Details**: Enter device name, charger specifications, and battery health
3. **Environment Sensors** (Optional): Link temperature and humidity sensors
4. **Optimized Charging** (Optional): Link binary sensor for optimized charging status

### Configuration Options

| Option | Description | Required | Default |
|--------|-------------|----------|---------|
| Device Name | Name for your device | Yes | - |
| Battery Entity | Home Assistant battery sensor | Yes | - |
| Battery Health | Battery health percentage | Yes | 100% |
| Charger Power | Charger power in watts | No | 20 |
| Learn from History | Enable ML learning | Yes | True |
| Temperature Sensor | Ambient temperature sensor | No | - |
| Humidity Sensor | Ambient humidity sensor | No | - |
| Optimized Charging Entity | Binary sensor for optimized charging status | No | - |
| Optimized Charging Enabled | Manual setting if entity not available | No | False |
| Scan Interval | Update interval in seconds (30-300) | No | 60 |
| Max History Samples | Maximum samples to store per device (100-100000) | No | 10000 (~30 days) |

**Max History Samples**: Controls how much historical charging data is stored per device. The default of 10,000 samples provides approximately 30 days of coverage at maximum scan interval (300s). At 60s interval, this covers about 7 days of continuous charging data. Older samples are automatically removed (FIFO) when the limit is reached.

### Behavior and History

- The coordinator refreshes at configurable intervals (default: 60 seconds, configurable 30-300 seconds)
- Updates are triggered immediately when battery state changes (in addition to periodic polling)
- Samples are recorded when the battery percentage increases (only if learn_from_history is enabled)
- Stored data includes: timestamp (UTC), battery_pct, optional temperature and humidity, rate_pct_per_min (derived from recorder or runtime), charger_power_w, optimized_charging, battery_health
- ML training requires enough positive-rate samples; otherwise the empirical model is used
- When learn_from_history is disabled, history recording continues but model training is skipped
- History saves are debounced (5 minutes) to reduce I/O, with immediate saves on shutdown

## Entities

For each configured device, the integration creates **four entities (three sensors + one binary sensor)**:

### Charge Time Remaining

- **Entity ID**: `sensor.{device_name}_charge_time_remaining`
- **Unit**: minutes
- **Description**: Estimated time until device reaches 100% charge
- **Attributes**: Battery health, charger power, temperature, humidity, model type, last updated

### Full Charge Time

- **Entity ID**: `sensor.{device_name}_full_charge_time`
- **Unit**: timestamp
- **Description**: Predicted datetime when device will be fully charged (UTC)
- **Attributes**: Time remaining in minutes, last updated

### Predicted Charge Rate

- **Entity ID**: `sensor.{device_name}_predicted_rate`
- **Unit**: %/min
- **Description**: Current effective charging rate
- **Attributes**: Calculated rate, battery percentage, model accuracy, empirical accuracy, sample count, model type

### Optimized Charging

- **Entity ID**: `binary_sensor.{device_name}_optimized_charging`
- **Type**: Binary sensor
- **Description**: Whether optimized charging is currently active
- **States**: on/off
- **Device Class**: battery_charging

**Note**: Full charge timestamps are timezone-aware UTC datetimes to satisfy Home Assistant timestamp sensors. If your battery entity reports whole percentages, history will still build as the percent ticks up over time.

## Services

### Retrain Model

Trigger model retraining for a device using recorded charging history. Requires `learn_from_history` to be enabled in integration options.

**Parameters** (provide either):
- `entity_id` (string, preferred): The configured battery entity
- `device_name` (string, legacy): The device name

**Examples**:

```yaml
# Standalone service call (Developer Tools) - using entity_id (preferred)
service: smartcharge_predictor.retrain
data:
  entity_id: sensor.apple_watch_battery

# Using device_name (legacy)
service: smartcharge_predictor.retrain
data:
  device_name: "Apple Watch"

# As action in automation/script
action:
  - service: smartcharge_predictor.retrain
    data:
      entity_id: sensor.apple_watch_battery
```

### Export Data

Export charging history to CSV file for a specific device.

**Parameters**:
- `device_name` (string, required): The device name

**Examples**:

```yaml
# Standalone service call (Developer Tools)
service: smartcharge_predictor.export_data
data:
  device_name: "Apple Watch"

# As action in automation/script
action:
  - service: smartcharge_predictor.export_data
    data:
      device_name: "Apple Watch"
```

### Import History

One-time import from Home Assistant recorder history to seed training data. Uses configured entities/values when enriching samples (battery_entity, ambient_temp_entity, humidity_entity, charger_power, battery_health, optimized_charging_enabled).

**Parameters**:
- `hours` (number, optional): How far back to import in hours. If provided, takes precedence over days.
- `days` (number, optional): How far back to import in days. Used if hours not provided.

**Notes**:
- Existing samples in the selected window are always cleared first
- If both `hours` and `days` are provided, `hours` takes precedence
- Only positive battery percentage increases generate samples (used to compute `rate_pct_per_min`)
- Each imported sample is enriched with temperature and humidity values from configured entities at the sample timestamp (if available)

**Examples**:

```yaml
# Standalone service call (Developer Tools)
service: smartcharge_predictor.import_history
data:
  days: 3

# Import last 24 hours
service: smartcharge_predictor.import_history
data:
  hours: 24

# As action in automation/script
action:
  - service: smartcharge_predictor.import_history
    data:
      days: 3
```

## Machine Learning

### Requirements

scikit-learn (>=1.0.0,<1.7.0) is automatically installed when you set up this integration. If installation fails on your environment (e.g., missing build tools on Python 3.13), the integration will continue to work using the empirical model only. You can manually install the compatible wheel inside your Home Assistant environment:

```bash
pip install "scikit-learn>=1.0.0,<1.7.0"
```

### Model Types

1. **Empirical Model**: Uses piecewise charging rates with environmental corrections
2. **Learned Model**: Uses scikit-learn (LinearRegression or RandomForest) trained on historical data

### Model Selection

The integration automatically selects the best model based on accuracy:
- Trains both LinearRegression and RandomForest models
- Evaluates empirical model accuracy on the same test set
- Selects the model with the highest R² score
- Stores selected model type and accuracy metrics

### Training

- Models automatically retrain when sufficient data is available (20+ samples)
- Training occurs in the background every 24 hours (only if learn_from_history is enabled)
- Manual retraining available via service call (requires learn_from_history to be enabled)
- Training compares all three models (LinearRegression, RandomForest, Empirical) and selects the best

## Use Cases

- **Power control automations**:
  - Turn off a charger or smart plug automatically when the device is predicted to reach 100%
  - Pause charging when the predicted full charge time falls within off-peak windows

- **Smart notifications**:
  - Notify when it is a good time to start charging so the device reaches 100% by the time you leave for work or go to bed
  - Alert if charging is slower than expected (e.g., poor cable, low-power adapter, high temperature)

- **Energy and battery health**:
  - Avoid holding the battery at 100% overnight by predicting completion time and stopping earlier
  - Track charging performance over time to detect degradation or environment-related slowdowns

## Lovelace Card Example

```yaml
type: entities
title: Charging Predictions
entities:
  - entity: sensor.apple_watch_charge_time_remaining
    name: Apple Watch – Time Remaining
  - entity: sensor.apple_watch_full_charge_time
    name: Expected Full Charge
  - entity: sensor.apple_watch_predicted_rate
    name: Current Charge Rate
  - entity: binary_sensor.apple_watch_optimized_charging
    name: Optimized Charging Active
```

## Troubleshooting

### Common Issues

**Sensors show "unavailable"**
- Check that the battery entity is accessible
- Verify battery entity state is not "unknown" or "unavailable"
- Sensors show last known state when entity temporarily unavailable
- Check Home Assistant logs for errors

**Predictions seem inaccurate**
- Ensure charger specifications are correct
- Link temperature and humidity sensors for better accuracy
- Enable learn_from_history and allow time for ML model to learn from historical data
- Models automatically select best algorithm (LinearRegression, RandomForest, or Empirical)

**ML features not working**
- Check logs for import errors
- Ensure learn_from_history is enabled in integration options
- Integration will fall back to empirical model if ML unavailable
- If scikit-learn installation failed, restart Home Assistant to retry installation
- On Python 3.13, versions >=1.7.0 may build from source; this integration pins to <1.7.0 to use pre-built wheels. If needed, install manually with: `pip install "scikit-learn>=1.0.0,<1.7.0"`

**Learning from history disabled**
- If learn_from_history is disabled, history recording continues but model training is skipped
- Manual retrain service will fail if learning is disabled
- Enable learn_from_history in integration options to use ML features

### Logs

Enable debug logging:

```yaml
logger:
  logs:
    custom_components.smartcharge_predictor: debug
```

## Technical Details

### Charging Models

**Empirical Model**:
- Fast phase (0-80%): 0.55%/min
- Slow phase (80-100%): 0.25%/min
- Temperature correction: Variable 10-15% reduction above 30°C (scales with temperature)
- Battery health correction: -10% below 90% health
- Optimized charging: -50% rate after 80%
- Charger power correction: Normalized to 20W baseline (capped at 2x)

**ML Models**:
- **LinearRegression**: Simple linear model for fast training
- **RandomForest**: Ensemble model for better accuracy on complex patterns
- Features: battery %, temperature, humidity, charger power, battery health, optimized charging
- Training: Minimum 20 samples, automatic retraining every 24 hours (if enabled)
- Validation: 20% holdout set for accuracy measurement
- Selection: Automatically chooses best model (LinearRegression, RandomForest, or Empirical)

### Data Storage

- History stored in `.storage/smartcharge_predictor/`
- Models persisted as pickle files
- CSV exports saved to `config/smartcharge_predictor_exports/`
- History saves are debounced: saves after 5 minutes of inactivity or immediately on shutdown
- Reduces I/O by batching saves instead of saving on every update

### Storage Limits

#### History Storage
- **Per-device limit**: Configurable (default: 10,000 samples)
- **Storage size**: ~150-200 KB per device per 1,000 samples
- **Default coverage**: ~30 days at maximum scan interval (300s)
  - At 60s interval: ~7 days continuous
  - At 300s interval: ~35 days continuous
- **Minimum for training**: 20 samples required
- **Configurable range**: 100-100,000 samples
- **Auto-pruning**: Oldest samples are automatically removed when limit is reached (FIFO)

#### Model Storage
- **Storage location**: `.storage/smartcharge_predictor/`
- **File size**: ~1-500 KB per device (depends on model type)
- **Cleanup**: Models are automatically replaced during retraining

#### Export Files
- **Storage location**: `config/smartcharge_predictor_exports/`
- **File naming**: `{device_id}_history_{timestamp}.csv`
- **Cleanup**: Export files are not automatically deleted
- **Recommendation**: Manually remove old exports periodically, or use a Home Assistant automation to clean files older than 30 days

#### Time Coverage Validation
- **Sample age limit**: Samples older than 300 seconds (5 minutes) are ignored when calculating charging rates
- Prevents stale data from affecting predictions

### Update Frequency

- Default: 60 seconds (configurable 30-300 seconds via options)
- Immediate updates: Battery state changes trigger instant refresh (in addition to polling)
- Sensors remain available even when not charging (useful for planning charge times)
- Graceful degradation: Shows last known state when battery entity unavailable

### Optimized Charging Detection

The integration supports multiple methods for detecting optimized charging:

1. **Entity-based** (Preferred): Link a binary sensor entity (`optimized_charging_entity`) that reports the device's optimized charging status
2. **Config setting**: Use the `optimized_charging_enabled` boolean setting if no entity is available
3. **Behavior inference**: Automatically detects when battery is stuck near 80% for extended periods (fallback)

The binary sensor entity (`binary_sensor.{device_name}_optimized_charging`) exposes this status, updating based on the configured method.

## Documentation

For detailed technical specifications, architecture, and implementation details, see the [Technical Specification](docs/tech_spec.md).

## Contributing

1. Fork the repository
2. Create a feature branch
3. Make your changes
4. Add tests if applicable
5. Submit a pull request

## License

This project is licensed under the MIT License.

## Support

- Create an issue on GitHub for bug reports
- Use discussions for feature requests and questions
- Check the troubleshooting section for common solutions
