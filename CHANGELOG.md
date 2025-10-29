# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [2025.10.1] - 2025-10-29

### Added
- Initial release of SmartCharge Predictor
- Predictive charging time estimation for battery-powered devices
- Machine learning support with scikit-learn (LinearRegression and RandomForest)
- Empirical charging model with environmental corrections
- Automatic model selection based on accuracy
- Support for temperature and humidity sensors
- Optimized charging detection (entity-based, config setting, or behavior inference)
- Configurable scan intervals (30-300 seconds)
- History management with configurable sample limits
- Service calls for model retraining and data export
- Import history from Home Assistant recorder
- UI-based configuration flow
- Four sensor entities per device:
  - Charge time remaining (minutes)
  - Full charge time (timestamp)
  - Predicted charge rate (%/min)
  - Optimized charging status (binary sensor)

### Features
- Automatic learning from historical charging data
- Debounced history storage to reduce I/O
- Immediate updates on battery state changes
- Graceful degradation when battery entity unavailable
- Support for multiple devices with independent models

[2025.10.1]: https://github.com/geckom/smartcharge-predictor/releases/tag/v2025.10.1

