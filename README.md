# LCD Ticker: show any Home Assistant value on a Xiaomi LYWSD03MMC thermometer (pvvx firmware)

[![HACS custom repository](https://img.shields.io/badge/HACS-Custom-orange.svg)](https://github.com/mikkmihkel/ha-lcd-ticker)

Turn a cheap Xiaomi LYWSD03MMC thermometer running [pvvx](https://github.com/pvvx/ATC_MiThermometer) firmware into a small glanceable display for any Home Assistant value.

<p align="center">
  <img src="docs/images/solar-meter.jpg" alt="Thermometer showing 5.7 kW solar output and 98 % self-consumption" width="480">
</p>

*Photo: jozefpis, from [xiaomi-LYWSD03MMC-to-solar-meter](https://github.com/jozefpis/xiaomi-LYWSD03MMC-to-solar-meter).*

> Status: version 0.1.0, not released yet.

## What it does

- Shows **solar production** (kW) with self-consumption (%).
- Shows **room climate** (temperature and humidity).
- Shows the **Nord Pool electricity price** in c/kWh, with VAT.
- Shows **averages and sums** from Home Assistant helpers (Min/Max, Statistics).
- **Rotates between several screens** on a speed you choose.
- Is **battery-aware**: it shows the expected updates per hour, skips writes when the screen would not change, and can pause at night.
- Is set up entirely from the Home Assistant UI. No YAML.

It uses no extra Python packages and no network. It only talks to the thermometer over Bluetooth through Home Assistant.

This project grows out of `jozefpis/xiaomi-LYWSD03MMC-to-solar-meter`.

## Requirements

- Home Assistant 2026.3 or newer.
- A Bluetooth adapter that can make **connections**. A Raspberry Pi's built-in Bluetooth works. ESPHome Bluetooth proxies use the same Home Assistant stack.
- A Xiaomi LYWSD03MMC with the **pvvx firmware**. Other pvvx devices are untested and may work.

## Flash the firmware

> **⚠ Risk.** The pvvx firmware is third-party software. Flashing can fail and leave the thermometer unusable. You flash at your own risk. Before you start, keep a copy of the stock firmware file if the flasher offers it.

The stock firmware cannot show your own values. The pvvx custom firmware can, and you flash it over the air from the browser.

1. Open the [Telink flasher](https://pvvx.github.io/ATC_MiThermometer/TelinkMiFlasher.html) in Chrome or Edge on a computer with Bluetooth.
2. Click **Connect** and select your thermometer (`LYWSD03MMC`).
3. Click **Do Activation** and wait for *Login successful*. The page shows the hardware and firmware version.
4. Under *Custom Firmware* select the pvvx firmware (this project was checked against [release v5.7](https://github.com/pvvx/ATC_MiThermometer/releases/tag/v5.7)) and click **Start Flashing**.

The upstream author flashed hardware B1.4 with stock firmware 1.0.0_0130 directly, without going through the original firmware first. Other hardware revisions or newer stock firmware may need extra steps. Check the [pvvx README](https://github.com/pvvx/ATC_MiThermometer#readme) if yours behaves differently.

After flashing, the thermometer advertises as `ATC_` plus six hex digits of its MAC address.

## Install

### HACS (custom repository)

1. In HACS, open the menu (⋮) and choose **Custom repositories**.
2. Add `https://github.com/mikkmihkel/ha-lcd-ticker` with type **Integration**.
3. Install **LCD Ticker** and restart Home Assistant.

### Manual

Copy `custom_components/lcd_ticker/` into the `config/custom_components/` folder of Home Assistant and restart.

## Set up

1. Go to **Settings → Devices & services**. A flashed thermometer named `ATC_xxxxxx` is discovered automatically. If you renamed it, choose **Add integration → LCD Ticker** and pick it from the list, or enter its MAC address.
2. Confirm the name and pick a **battery profile**. LCD Ticker sends a test smiley `(^_^)` to check the connection. If it fails, move the thermometer closer to the adapter and try again.
3. Choose **Add screen**.
4. Pick a **preset**, then pick the entities it needs.
5. Choose the **look** (unit symbol, `%` sign, battery icon, brackets, face), the position in the rotation and an optional time on screen.

Add more screens the same way. To change a screen later, open it on the integration page and choose **Edit screen**.

The LCD cannot show text. Give each screen at least one difference: a unit symbol, brackets, the `%` sign, the battery icon or a fixed small number. LCD Ticker warns you if two screens look the same.

## Presets

| Preset | Big number | Small number | Look and face |
|---|---|---|---|
| solar | Production, in kW with 1 decimal | Self-consumption % = (production − export) / production. Shows 0 when production is under 50 W. You can pick an existing % sensor instead. | `%`. Face follows the small number, higher is better, thresholds 20/40/60/80 |
| climate | Temperature, in °C with 1 decimal | Humidity %, no decimals | Unit `°C`, `%`, no face |
| price | Price in c/kWh (EUR/kWh ×100, EUR/MWh ÷10, read from the sensor's unit), times (1 + VAT %) | Optional entity, for example the next price, rounded | No unit. Face follows the big number, lower is better, thresholds 5/10/15/20 c |
| single | One entity, with your own conversion | None | Your choice |
| custom | Everything manual | Everything manual | Everything manual |

The face scale has five levels. Best to worst: `(^_^)` · `^_^` · `Δ△Δ` · `-∧-` · `(-∧-)`. With *lower is better*, the thresholds are read in reverse.

## Battery guide

Every update is one Bluetooth connection, and every connection uses battery. Writing every minute drains a CR2032 in a few months (measured by the upstream author). Writing every 3 to 8 minutes in daytime only is the upstream-tested setup.

LCD Ticker keeps the cost down:

- One write is one connection.
- A write is **skipped** when the frame is the same as the one already shown.
- Writes never come closer than 60 seconds.

Pick a profile when you add the thermometer. You can change it later in **Configure**.

| Profile | Seconds per screen | While someone is present |
|---|---|---|
| Eco | 900 | 300 |
| Balanced (default) | 480 | 180 |
| Responsive | 180 | 90 |

"Present" means the presence entity (for example a motion sensor or a person) is on or home, and for 10 minutes after it turns off. Editing a speed switches the profile to Custom.

**Configure** shows "about N updates per hour". Above 30 per hour it warns you about battery use. The same numbers are available as the *Estimated updates per hour* and *Updates in the last hour* sensors.

You can also pause updates: set an *active* entity (for example a binary sensor that is on while the panels produce), or quiet hours. While paused, the LCD shows what you choose under *When inactive, show*: the built-in reading, zeros, or the last screen.

## Modes and "If HA stops"

| Mode | What it does |
|---|---|
| Single screen + built-in reading | Only your first screen counts. The thermometer alternates it with its own temperature and humidity on its own, about every 5 seconds. LCD Ticker writes only when the value changes, and refreshes it before it expires. |
| Rotating screens | LCD Ticker switches between your enabled screens, in order. Optionally the thermometer's own reading is one of the slots. |

**If Home Assistant stops** (rotating mode only):

- **Freeze the last screen** (default): the LCD keeps the last screen until Home Assistant is back.
- **Alternate**: each screen alternates with the built-in reading, and the display falls back to the built-in reading if Home Assistant stops.

A screen can also **show immediately** when its big number changes by more than a set amount. It still never writes more than once a minute.

## Entities

Each thermometer is one device. If the BTHome device for the same MAC address exists, Home Assistant can merge it onto the same page.

| Platform | Entity | Notes |
|---|---|---|
| switch | Rotation | Turns updates on or off |
| select | Mode | Single screen + built-in reading, or Rotating screens |
| select | Screen | Shows the current screen. Selecting one shows it now. |
| number | Seconds per screen | 30 to 3600 |
| number | Seconds per screen while present | 30 to 3600 |
| button | Refresh now | Rewrites the current screen |
| sensor | Last update | Timestamp |
| sensor | Updates in the last hour | Diagnostic |
| sensor | Estimated updates per hour | Diagnostic |
| sensor | Last error | Diagnostic, disabled by default |
| binary sensor | Reachable | Off after a failed write |

Changes you make through these entities are saved and survive a restart. To show a specific screen from an automation, call `select.select_option` on the Screen entity.

If the thermometer cannot be reached for 5 writes in a row, or has had no successful write for an hour while active, Home Assistant shows a Repairs issue. It clears itself on the next success.

## Action `lcd_ticker.show`

Sends one raw frame to a thermometer. It is compatible with `pvvx_display.show`. Choose the target with `device_id` (a configured thermometer) or `address` (the MAC address, also works for thermometers you did not configure).

Rotation is not paused. The next scheduled screen overwrites your frame. For a long-lived manual value, turn the **Rotation** switch off first.

```yaml
action: lcd_ticker.show
data:
  address: "A4:C1:38:XX:XX:XX"
  big: 5.7
  small: 98
  percent: true
  happy: true
  bracket: true
  validity: 65535
```

| Field | Description |
|---|---|
| `device_id` or `address` | The thermometer: a configured device, or a MAC address |
| `big` | Big number. One decimal from −9.5 to 199.5, whole numbers up to 1999 and down to −99. Values outside are capped. |
| `small` | Small number, whole number, −9 … 99. Values outside are capped. |
| `validity` | Seconds the display keeps your value instead of its own reading. **65535 = until the thermometer reboots** |
| `unit` | Symbol next to the big number: `none`, `deg_c`, `deg_f`, `minus`, `lowdash`, `lines`, `deg_ghe`, `deg_e` |
| `percent` | Show `%` next to the small number |
| `battery` | Show the battery icon |
| `happy` / `sad` / `bracket` | Combine into faces (see below) |

The unit symbols are: none, `°Г`, `-`, `°F`, `_`, `°C`, `=`, `°E`.

| happy | sad | bracket | Face |
|:-:|:-:|:-:|---|
| ✓ | | ✓ | `(^_^)` |
| ✓ | | | `^_^` |
| ✓ | ✓ | | `Δ△Δ` |
| | ✓ | | `-∧-` |
| | ✓ | ✓ | `(-∧-)` |

## Coming from `pvvx_display`

Rename the action from `pvvx_display.show` to `lcd_ticker.show`. The fields are the same. Use `device_id` or `address` as the target.

## Averages and sums

LCD Ticker does not average values itself. Create a helper first:

1. Go to **Settings → Devices & services → Helpers**.
2. Create a **Min/Max** helper (min, max, mean, sum) or a **Statistics** helper.
3. When you add a screen, pick the helper's entity as the big or small number.

## Troubleshooting

**"Could not reach the thermometer" or "not in range".** Move the thermometer closer to the adapter. Check that the adapter supports active connections.

**The display keeps alternating with temperature and humidity.** This happens when the value has a validity shorter than 65535. While valid, the thermometer shows your value and its own reading in turn, about 5 seconds each. This is intended in *Single screen + built-in reading* mode and with *Alternate* under "If Home Assistant stops". With the thermometer's own settings `show_batt_enabled` or `show_time_smile` on, it may also show battery % or the clock in place of your small number and face. A battery at 5 % or lower forces the battery display. Validity 65535 avoids all of this. The pvvx documentation describes these settings.

**The LCD shows `iH` or `oL`.** The value is too high or too low for the display. LCD Ticker caps values so this should not appear. If you see it, check the conversion and multiplier on the screen.

**A renamed thermometer is not discovered.** Discovery looks for names starting with `ATC_`. Add it through **Add integration → LCD Ticker** and enter the MAC address.

**A new screen takes a moment.** The thermometer shows a new frame at its next display tick, up to about 2.5 seconds after the write.

Download the **diagnostics** from the device page when you report a bug. The MAC address is redacted.

## Remove the integration

1. Go to **Settings → Devices & services → LCD Ticker**.
2. Open the menu (⋮) of the thermometer and choose **Delete**.

The LCD keeps the last frame until the thermometer reboots. Take the battery out for a moment to reset it.

## How it works

LCD Ticker connects through Home Assistant's Bluetooth stack, writes an 8-byte frame to characteristic `00001f1f-0000-1000-8000-00805f9b34fb` without response, and disconnects:

| Bytes | Content |
|---|---|
| `[0]` | `0x22` |
| `[1:3]` | big number, int16 LE, value × 10 |
| `[3:5]` | small number, int16 LE |
| `[5:7]` | validity, uint16 LE, seconds. `0xFFFF` = until reboot |
| `[7]` | flags: bits 0-2 face (a 3-bit value), bit 3 `%`, bit 4 battery icon, bits 5-7 unit |

The face is one 3-bit value, not three separate bits. The firmware source defines these values: 0 none, 1 `^_^`, 2 `-∧-`, 3 `Δ△Δ`, 5 `(^_^)`, 6 `(-∧-)`. The `happy`, `sad` and `bracket` fields of the action are converted to it.

For example, big 5.7, small 98, `%`, face `(^_^)`, validity 65535 is `22 39 00 62 00 ff ff 0d`.

The same frame is used by the ESPHome [`pvvx_mithermometer`](https://esphome.io/components/display/pvvx_mithermometer.html) display component.

## Credits

- [jozefpis/xiaomi-LYWSD03MMC-to-solar-meter](https://github.com/jozefpis/xiaomi-LYWSD03MMC-to-solar-meter): the original idea and code (MIT).
- [pvvx/ATC_MiThermometer](https://github.com/pvvx/ATC_MiThermometer): the firmware and the flasher that make this possible.
- The ESPHome `pvvx_mithermometer` component: a reference for the display protocol.

This project is not affiliated with Xiaomi or with the pvvx project.

## License

MIT. See [LICENSE](LICENSE).
