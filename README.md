# LCD Ticker

Show any Home Assistant value on a Xiaomi LYWSD03MMC thermometer running [pvvx](https://github.com/pvvx/ATC_MiThermometer) firmware: solar power, room climate, the electricity price, averages. It rotates between screens and keeps the CR2032 battery in mind. Everything is set up in the Home Assistant UI.

<p align="center">
  <img src="docs/images/solar-meter.jpg" alt="Thermometer showing 5.7 kW solar output and 98 % self-consumption" width="480">
</p>

*Photo: jozefpis, from [xiaomi-LYWSD03MMC-to-solar-meter](https://github.com/jozefpis/xiaomi-LYWSD03MMC-to-solar-meter).*

No extra Python packages, no network. It only talks to the thermometer over Bluetooth through Home Assistant.

## Requirements

- Home Assistant 2026.3 or newer.
- A Bluetooth adapter that can make connections (a Raspberry Pi's built-in one works, and so do ESPHome Bluetooth proxies).
- A LYWSD03MMC with pvvx firmware (checked against [v5.7](https://github.com/pvvx/ATC_MiThermometer/releases/tag/v5.7)).

## Flash the firmware

> **Risk.** pvvx is third-party firmware. A failed flash can leave the thermometer unusable. You flash at your own risk.

1. Open the [Telink flasher](https://pvvx.github.io/ATC_MiThermometer/TelinkMiFlasher.html) in Chrome or Edge.
2. **Connect** and pick `LYWSD03MMC`, then **Do Activation** and wait for *Login successful*.
3. Under *Custom Firmware* choose the pvvx firmware and **Start Flashing**.

Afterwards it advertises as `ATC_` plus six hex digits of its MAC. Other hardware or stock firmware versions may need extra steps; see the pvvx README.

## Install

**A. Manual.** Download `lcd_ticker.zip` from the latest [GitHub release](https://github.com/mikkmihkel/ha-lcd-ticker/releases), unzip it into `config/custom_components/lcd_ticker/` and restart Home Assistant.

**B. HACS.** Add `https://github.com/mikkmihkel/ha-lcd-ticker` as a custom repository of type Integration, install **LCD Ticker** and restart. HACS needs the repository to be public.

## Set up

1. **Settings → Devices & services**: a flashed `ATC_xxxxxx` is discovered. Otherwise **Add integration → LCD Ticker** and pick it or enter its MAC.
2. Confirm the name and a **battery profile**. A test smiley `(^_^)` checks the connection.
3. **Add screen**, pick a preset and its entities, then the look: unit symbol, `%`, battery icon, face, position and optional seconds on screen.

The LCD cannot show text, so give each screen something different (unit, `%`, battery icon, brackets or a fixed small number). You get a warning if two screens look the same. Edit a screen from the integration page with **Edit screen**.

## Presets

| Preset | Big number | Small number | Look |
|---|---|---|---|
| solar | Production in kW | Self-consumption % = (production − export) / production, or your own % sensor | `%`, face by small number (higher is better, 20/40/60/80) |
| climate | Temperature in °C | Humidity % | `°C`, `%` |
| price | Price in c/kWh, VAT added (read from the sensor's unit) | Optional entity | Face by big number (lower is better, 5/10/15/20 c) |
| single | One entity, your own conversion | Fixed number: the screen's position when created | Your choice |
| custom | Everything manual | Everything manual | Everything manual |

A screen can also **show immediately** when its big number changes by at least a set amount.

## Modes and "If HA stops"

- **Single screen + built-in reading**: the thermometer alternates your first screen with its own temperature and humidity.
- **Rotating screens**: LCD Ticker switches between your enabled screens; the built-in reading can be one slot.

If Home Assistant stops (rotating mode): **Freeze** keeps the last screen until Home Assistant is back; **Alternate** alternates each screen with the built-in reading and falls back to it.

## Battery

Every update is one Bluetooth connection. LCD Ticker skips a write when the screen would not change, and **writes never come closer than 60 seconds** (except when you press Refresh, pick a screen, or call the action). **Configure** shows the expected updates per hour and warns above 30.

| Profile | Seconds per screen | While present |
|---|---|---|
| Eco | 900 | 300 |
| Balanced (default) | 480 | 180 |
| Responsive | 180 | 90 |

"Present" means your presence entity is on or home, and for 10 minutes after. You can pause at night with quiet hours or an *active* entity; the LCD then shows the built-in reading, zeros or the last screen.

## Entities

| Entity | Notes |
|---|---|
| Rotation (switch) | Turns updates on or off |
| Mode, Screen (select) | Selecting a screen shows it now |
| Seconds per screen, while present (number) | 30 to 3600 |
| Refresh now (button) | Rewrites the current screen |
| Last update, Updates in the last hour, Estimated updates per hour, Last error (sensor) | Last error is disabled by default |
| Reachable (binary sensor) | Off after a failed write |

## Action `lcd_ticker.show`

Sends a frame directly; the next scheduled screen overwrites it, so turn Rotation off for a lasting value.

```yaml
action: lcd_ticker.show
data:
  address: "A4:C1:38:XX:XX:XX"   # or device_id
  big: 5.7
  small: 98
  percent: true
  happy: true
  bracket: true
  validity: 65535
```

Fields: `device_id` or `address`, `big`, `small`, `validity` (default 900; 65535 = until reboot), `unit`, `percent`, `battery`, `happy`, `sad`, `bracket`. Details are in [docs/reference.md](docs/reference.md).

Coming from `pvvx_display`: rename `pvvx_display.show` to `lcd_ticker.show`; the fields are the same.

Averages and sums: create a Min/Max or Statistics helper and pick it as a screen entity.

## Troubleshooting

- **"Could not reach the thermometer"**: move it closer to the adapter and check that the adapter supports active connections.
- **The LCD alternates with temperature and humidity**: expected with a validity below 65535 (Single mode, Alternate). Pvvx settings such as `show_batt_enabled` can add battery or clock stages.
- **A screen shows 1999 or -99**: values are capped to what the LCD can show; check the screen's conversion and multiplier.
- **Battery %**: the thermometer's own BTHome device (same MAC) shows it, not the LCD Ticker device.
- **Deleting your last screen**: turn Rotation off first, otherwise the LCD keeps the last value.

Attach the **diagnostics** download to bug reports; the MAC is redacted.

## Remove

Delete the thermometer under **Settings → Devices & services → LCD Ticker**. A frozen frame (validity 65535) stays until the thermometer reboots, so briefly take out the battery.

## Credits and license

Based on [jozefpis/xiaomi-LYWSD03MMC-to-solar-meter](https://github.com/jozefpis/xiaomi-LYWSD03MMC-to-solar-meter) (MIT). Thanks to [pvvx/ATC_MiThermometer](https://github.com/pvvx/ATC_MiThermometer) for the firmware and flasher, and to the ESPHome [`pvvx_mithermometer`](https://esphome.io/components/display/pvvx_mithermometer.html) component as a protocol reference. Not affiliated with Xiaomi or pvvx.

MIT. See [LICENSE](LICENSE).
