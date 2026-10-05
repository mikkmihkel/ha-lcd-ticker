# Reference

## Action `lcd_ticker.show`

Choose the target with one of `device_id` (a configured thermometer) or `address` (a MAC address; also works for thermometers you did not configure). Rotation is not paused: the next scheduled screen overwrites your frame.

| Field | Description |
|---|---|
| `device_id` or `address` | The thermometer: a configured device, or a MAC address |
| `big` | Big number. One decimal from −9.5 to 199.5, whole numbers up to 1999 and down to −99. Values outside are capped (to 1999.4 and −99.4, so the LCD never shows a value it can't draw). |
| `small` | Small number, rounded to a whole number, −9 … 99. Values outside are capped. |
| `validity` | Seconds the display keeps your value instead of its own reading. Default 900. **65535 = until the thermometer reboots** |
| `unit` | Symbol next to the big number (see below) |
| `percent` | Show `%` next to the small number |
| `battery` | Show the battery icon |
| `happy` / `sad` / `bracket` | Combine into a face (see below) |

## Unit symbols

| `unit` | Symbol |
|---|---|
| `none` | none |
| `deg_ghe` | `°Г` |
| `minus` | `-` |
| `deg_f` | `°F` |
| `lowdash` | `_` |
| `deg_c` | `°C` |
| `lines` | `=` |
| `deg_e` | `°E` |

## Faces

| happy | sad | bracket | Face |
|:-:|:-:|:-:|---|
| | | | none |
| ✓ | | | `^_^` |
| | ✓ | | `-∧-` |
| ✓ | ✓ | | `Δ△Δ` |
| | | ✓ | `( )` |
| ✓ | | ✓ | `(^_^)` |
| | ✓ | ✓ | `(-∧-)` |
| ✓ | ✓ | ✓ | `(Δ△Δ)` |

The scale faces, best to worst: `(^_^)` · `^_^` · `Δ△Δ` · `-∧-` · `(-∧-)`. With *lower is better* the thresholds are read in reverse.

## Frame layout

LCD Ticker writes an 8-byte frame to characteristic `00001f1f-0000-1000-8000-00805f9b34fb` without response, then disconnects:

| Bytes | Content |
|---|---|
| `[0]` | `0x22` |
| `[1:3]` | big number, int16 LE, value × 10 |
| `[3:5]` | small number, int16 LE |
| `[5:7]` | validity, uint16 LE, seconds. `0xFFFF` = until reboot |
| `[7]` | flags: bits 0-2 face (3-bit value), bit 3 `%`, bit 4 battery icon, bits 5-7 unit |

The face is one 3-bit value: bit 0 happy, bit 1 sad, bit 2 bracket. For example big 5.7, small 98, `%`, face `(^_^)`, validity 65535 is `22 39 00 62 00 ff ff 0d`. The ESPHome `pvvx_mithermometer` display component uses the same frame.

## Alternating display

A validity below 65535 makes the thermometer show your value and its own reading in turn, about 5 seconds each (longer if the thermometer's *LCD refresh* or advertising interval is set higher). Only 65535 shows your value steadily. This is intended in *Single screen + built-in reading* mode and with *Always alternate* under "If Home Assistant stops". The **Display** sensor's `alternating` attribute says whether the last frame alternates. With the thermometer's own settings `show_batt_enabled` or `show_time_smile` on, it may also show battery % or the clock in place of your small number and face. A battery at 5 % or lower forces the battery display. A new frame appears at the next display tick, up to about 2.5 seconds after the write.
