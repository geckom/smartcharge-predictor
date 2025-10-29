## 🧩 SmartCharge Predictor – Technical Specification

### 📜 Overview

The **SmartCharge Predictor** is a Home Assistant custom integration that estimates the **time remaining until a device is fully charged**, dynamically adjusting based on:

* device type (e.g., iPhone, Apple Watch, Android phone, etc.),
* charger characteristics (voltage, amperage, wattage),
* environmental factors (temperature, humidity),
* and learned charging behavior from historical data.

The integration exposes:

* a **sensor** entity per tracked device (`sensor.apple_watch_charge_time_remaining`),
* optionally a **binary_sensor** for “Optimized Charging Active”, and
* optionally a **learning service** to retrain or recalibrate charging models from historical data.

---

## 🧱 Component Architecture

### 1. File structure (based on HA developer docs)

```
custom_components/
└── smartcharge_predictor/
    ├── __init__.py
    ├── manifest.json
    ├── config_flow.py
    ├── const.py
    ├── coordinator.py
    ├── sensor.py
    ├── model.py
    ├── history_manager.py
    ├── services.yaml
    ├── strings.json
    └── translations/
        └── en.json
```

---

## ⚙️ Component Design

### 🧠 Core Concept

Each tracked **device** will have its own `ChargingProfile`, containing both static attributes (charger type, battery health, etc.) and dynamic variables (current battery %, temperature, etc.).

On every Home Assistant update interval, the component:

1. Collects current telemetry (from HA entities, user-defined fields, or APIs).
2. Calculates the **estimated charge rate** based on empirical model (piecewise or learned).
3. Outputs a **predicted full charge time** (`datetime`) and **minutes remaining** (`float`).
4. Stores the sample in a historical DB (local JSON or HA recorder) for retraining.

---

## 🧩 Configuration Options

### YAML (legacy) or UI Flow (preferred)

Example YAML for debugging:

```yaml
smartcharge_predictor:
  devices:
    - name: Apple Watch
      battery_entity: sensor.apple_watch_battery
      charger_power_w: 20
      charger_voltage_v: 9
      charger_current_a: 2.22
      ambient_temp_entity: sensor.office_temperature
      humidity_entity: sensor.office_humidity
      optimized_charging_entity: binary_sensor.apple_watch_optimized_charging
      battery_health: 94
      os_version: "WatchOS 10.4"
      learn_from_history: true
```

In the **UI config flow**, users select the battery entity and optionally link environment sensors.

---

## ⚡ Entities Exposed

| Entity                                           | Type   | Description                                           |
| ------------------------------------------------ | ------ | ----------------------------------------------------- |
| `sensor.{device_name}_charge_time_remaining`     | Sensor | Estimated minutes until full charge.                  |
| `sensor.{device_name}_full_charge_time`          | Sensor | Estimated time (datetime) when 100 % will be reached. |
| `sensor.{device_name}_predicted_rate`            | Sensor | Current effective charge rate (% per minute).         |
| `binary_sensor.{device_name}_optimized_charging` | Binary | If OS is delaying charge near 80 %. (optional)        |

---

## 🧮 Core Calculations

### Base Formula (piecewise + learned correction)

For each device:

[
R_{pred} = f(V, A, Temp, Hum, Health, OS)
]
[
t_{100} = \int_{P}^{100} \frac{1}{R_{pred}(P)} dP
]

In implementation:

```python
if battery_pct < 80:
    rate = fast_rate_base * correction_factor
else:
    rate = slow_rate_base * correction_factor
time_remaining = (100 - battery_pct) / rate  # in minutes
```

`correction_factor` is dynamically learned from historical data or simple regression models.

---

## 🧬 Learning Component (model.py / history_manager.py)

### Data Schema (stored in JSON or SQLite)

| timestamp | battery_pct | temperature | humidity | rate_pct_per_min | charger_power_w | optimized_charging | os_version | battery_health |

**Functions:**

* `record_session(device_id, metrics: dict)` → appends charge data.
* `train_model(device_id)` → trains linear regression or RandomForest (if available).
* `predict_rate(current_state)` → returns expected rate (%/min).
* Optionally use `joblib` or `pickle` to persist trained models per device.

### Model Update Flow

* On every `state_changed` for a battery entity, new samples (Δ%) are stored.
* Once sufficient samples exist, a background job recalibrates the per-device model.
* The model is reloaded on integration startup.

---

## 🔄 Update Coordinator

`coordinator.py`:

* Polls dependent entities every N minutes (configurable).
* Calls model to get predicted time remaining.
* Updates the entity states.

---

## 🛠️ Services

```yaml
smartcharge_predictor.retrain:
  description: "Retrain the model for a device using recorded history."
  fields:
    device_name:
      description: "Device name to retrain."
      example: "Apple Watch"
```

```yaml
smartcharge_predictor.export_data:
  description: "Export learned charge history as CSV for analysis."
```

---

## 🧠 Machine Learning Details

### Initial Model (bootstrapped)

* Default to empirical Apple/Android charge rates:

  * Fast phase: 0–80 % ≈ 0.55 %/min
  * Slow phase: 80–100 % ≈ 0.25 %/min
* Apply modifiers:

  * Temperature > 30 °C → reduce rate by 10–15 %
  * Battery health < 90 % → reduce rate by 5–10 %
  * Optimized Charging active → clamp rate after 80 %

### Adaptive Model (learned)

* Simple regression using scikit-learn (LinearRegression or RandomForest).
* Features: battery_pct, temperature, humidity, charger_power_w, battery_health.
* Target: rate_pct_per_min.
* Automatically replaces empirical defaults when accuracy improves.

---

## 🧰 Integration Notes

* **Requires:** Home Assistant 2024.6+
* **Dependencies:** `pandas`, `scikit-learn` (optional), or built-in regression via NumPy.
* **I/O:** Uses `hass.data["smartcharge_predictor"]` registry for per-device profiles.
* **Persistence:** Models and history stored in `.storage/smartcharge_predictor/`.

---

## 🌡️ Optional Integrations

* **HomeKit Battery Sensors** – for Apple devices.
* **Android Debug Bridge / Tasker sensors** – for Android devices.
* **Smart plugs (TP-Link, Shelly, etc.)** – to detect charger power draw and on/off state.
* **Weather or room sensors** – for temperature and humidity.

---

## 💡 Example Lovelace Card

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
    name: Optimized Charging
```

---

## 🧩 Future Enhancements

* Integration with HA **Energy dashboard** for per-device energy consumption.
* Auto-learning multiple profiles per charger type.
* Predictive “plug-in time” notifications (“Plug in by 9:37 pm to be ready by 10 pm”).
* Cloudless retraining (TinyML-style on-device model updates).
* Optional HA statistics integration to plot historical charge curves.

