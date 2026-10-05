# Changelog

All notable changes to this project are documented here. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and the project uses
[Semantic Versioning](https://semver.org/).

## [Unreleased]

## [0.3.1] - 2026-10-05

### Fixed

- Switching the mode while a write was in progress took effect only after a full screen time (up to 15 minutes). In that time a screen sent in *Single screen + built-in* mode kept alternating with the temperature after switching to *Rotating screens*. The change now applies at the next allowed write.

### Changed

- *If Home Assistant stops → Alternate* is now called *Always alternate with the built-in reading*, and its help says that the LCD then switches between your screen and its own reading every few seconds all the time, not only when Home Assistant stops. Choose *Freeze the last screen* for steady screens.
- The **Display** sensor has an `alternating` attribute: `true` when the last frame makes the thermometer take turns with its own reading.
- README: what to check when the LCD switches between your value and the temperature. Presence and motion sensors don't cause it.

## [0.3.0] - 2026-10-03

### Changed

- Screen setup is one simple form with a preview. Pick the big number and its symbol, optionally a small number, then check what the LCD will show before saving.
- Presets were removed.
- Advanced options (multiplier, decimals, conversion, VAT, face, conditions and more) moved into a collapsed section on the check step. *Preview again* applies them and shows the result before saving.
- Existing screens are unchanged. Editing one opens the same two steps with its settings filled in.

## [0.2.2] - 2026-10-03

### Fixed

- Solar: a production sensor in the wrong unit (for example kWh instead of W) returned the form with no message. The error now shows on the production field.
- Unit errors always name the right unit and target (for self-consumption the target is kW), one problem at a time.

## [0.2.1] - 2026-10-03

### Fixed

- Presets no longer lock the small number's conversion: Solar, Room climate and Electricity price now show *Convert to*, multiplier and offset for the small number too. Before, the price preset always converted the small number to cents, so a humidity or percentage sensor failed with "unit cannot be converted".
- Entity pickers no longer hide sensors without a device class (common for helpers and template sensors).
- The unit error now says which unit the sensor reports and what it should convert to.
- More cent spellings are recognised in price units (`senti`, `sent`, `¢`).

## [0.2.0] - 2026-10-02

### Added

- The thermometer's own temperature, humidity, battery, voltage and signal strength as sensors, read passively from its broadcasts.
- Per-screen conditions ("only show while this is on") and take-over.
- A live preview of the LCD in each screen's setup.
- A Display sensor that shows what is on the LCD now.
- Conversion controls (multiplier, offset, decimals) in every preset.
- Comfort-range faces, where the middle of the range is the best.

### Fixed

- Values at the very top or bottom of the range are capped at 1999.4 and −99.4. Before, the firmware rounded them to numbers the LCD can't draw (shown as "1000" or a garbled "-100").

## [0.1.2] - 2026-10-02

### Fixed

- Writes failed with "Characteristic …1f1f was not found" when Home Assistant had a stale Bluetooth service cache for the thermometer (for example from before the pvvx flash). LCD Ticker now clears the cache (in Home Assistant and, if needed, in BlueZ) and retries once with a fresh lookup.
- Writes timed out after 20 s before the Bluetooth library could finish its own connection retries. The limit is now 60 s.

## [0.1.1] - 2026-10-02

### Fixed

- The MAC address field accepts every common spelling, including `A4C138FE8D46` as shown by the Telink flasher (also in `lcd_ticker.show`).
- Thermometers are discovered as quickly as BTHome finds them, even before they send their `ATC_` name. Other BTHome devices are ignored.

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
