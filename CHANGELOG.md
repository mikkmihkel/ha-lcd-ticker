# Changelog

All notable changes to this project are documented here. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and the project uses
[Semantic Versioning](https://semver.org/).

## [Unreleased]

## [0.1.0] - 2026-10-02

### Added

- Config entry per thermometer, found by Bluetooth discovery or added by MAC address, with a test frame on setup.
- Config subentry per screen, started from the presets solar, climate, price, single and custom.
- Entity values with multiplier, offset, decimals, automatic unit conversion and VAT.
- Face scale from the `(^_^)` to `(-∧-)` range, with thresholds in both directions.
- Two modes: single screen + built-in reading, and rotating screens.
- Battery profiles Eco, Balanced and Responsive, with an estimated updates per hour shown in the options.
- Faster rotation while someone is present, quiet hours, an active entity and an inactive display choice.
- Skipping writes when the frame has not changed, and a 60 second minimum gap between writes.
- Per-screen "show immediately on big change".
- "If HA stops" option: freeze the last screen or alternate with the built-in reading.
- Entities: Rotation, Mode, Screen, Seconds per screen, Seconds per screen while present, Refresh now, Last update, Updates in the last hour, Estimated updates per hour, Last error and Reachable.
- Repairs issue when a thermometer stays unreachable.
- Action `lcd_ticker.show`, compatible with `pvvx_display.show`.
- Diagnostics download with the MAC address redacted.
- Warning when two screens look the same on the LCD.
- Release asset `lcd_ticker.zip` for manual and HACS installs.
