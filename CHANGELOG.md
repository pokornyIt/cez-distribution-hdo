# Changelog
All notable changes to this project will be documented in this file.

The format is based on Keep a Changelog, and this project adheres to Semantic Versioning.

## [Unreleased]
### Added
- TBD

### Changed
- TBD

### Fixed
- TBD

## [0.1.0] - 2026-01-04
### Added
- Async HTTP client for CEZ Distribution switch-times API (POST JSON).
- Parsing of `signals[]` including multiple signal sets.
- Tariff schedule utilities with correct handling of `24:00` and cross-midnight merges.
- High-level `TariffService` producing HA-friendly “snapshot” values.
- Tests, Ruff + Pyright, pre-commit, CI workflows.
