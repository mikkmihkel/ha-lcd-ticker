# Hardware checks

These checks run on a real LYWSD03MMC with pvvx firmware, using the Bluetooth adapter of a
Raspberry Pi. Run them before features depend on them. Fill in the result and the date,
and attach photos where useful.

Run each YAML under **Developer tools → Actions → Go to YAML mode**. Replace
`A4:C1:38:XX:XX:XX` with your thermometer's MAC address. Turn the **Rotation** switch off
first so the next scheduled screen does not overwrite the test frame.

| ID | Check | How to run it | Expected result | Result | Date |
|---|---|---|---|---|---|
| H1 | The golden frame displays correctly | YAML H1 below | Shows `5.7`, `98 %`, `(^_^)` and stays | | |
| H2 | Validity 1 shows the LCD's own reading | YAML H2 below | Own temperature and humidity return within about 1 to 2 s | | |
| H3 | Finite validity alternates with the own reading | YAML H3 below | Alternates about every 4.9 s. Note whether battery or clock stages appear. | | |
| H4 | Big number ranges | YAML H4 below | One decimal up to 199.5, whole numbers above, no `iH`/`oL` at the limits | | |
| H5 | What each unit code and each face value looks like | YAML H5 below | Photo table of the 8 units and the 8 face values. Note any that look broken. | | |
| H6 | Finite validity expires on time without any time sync | YAML H6 below | Own reading only after about 60 s | | |
| H7 | BTHome device for the same MAC exists and shows the battery | Check the Devices page | A separate BTHome device with the battery sensor exists. It does not merge onto the LCD Ticker device. | | |
| H8 | Write without response followed by an immediate disconnect is reliable over 50 writes | Script H8 below | All 50 writes show on the LCD, with no errors in the log | | |
| H9 | Two-week soak at Balanced | Run the Balanced profile for two weeks | Battery % logged daily. Record the start and end values. | | |

## H1: golden frame

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

The frame sent is `22 39 00 62 00 ff ff 0d`.

## H2: validity 1

Send the H1 frame first, then:

```yaml
action: lcd_ticker.show
data:
  address: "A4:C1:38:XX:XX:XX"
  big: 5.7
  small: 98
  validity: 1
```

## H3: finite validity

```yaml
action: lcd_ticker.show
data:
  address: "A4:C1:38:XX:XX:XX"
  big: 5.7
  small: 98
  percent: true
  happy: true
  validity: 60
```

Watch for one minute. Repeat with the device settings `show_batt_enabled` and
`show_time_smile` on, and note what changes.

## H4: big number limits

Send each value in turn (change `big` and send again): `199.5`, `200`, `1999`, `1999.5`,
`-9.5`, `-10`, `-99.5`.

```yaml
action: lcd_ticker.show
data:
  address: "A4:C1:38:XX:XX:XX"
  big: 199.5
  small: 0
  validity: 65535
```

## H5: units and faces

Send each of the 8 `unit` values (`none`, `deg_ghe`, `minus`, `deg_f`, `lowdash`,
`deg_c`, `lines`, `deg_e`) and photograph the result.

```yaml
action: lcd_ticker.show
data:
  address: "A4:C1:38:XX:XX:XX"
  big: 1.0
  small: 1
  unit: deg_c
  validity: 65535
```

For faces, send each combination from [docs/reference.md](reference.md) (for example
`happy: true` with `bracket: true`). Face 4 is `bracket: true` alone. Face 7 is `happy`,
`sad` and `bracket` together.

## H6: expiry without time sync

```yaml
action: lcd_ticker.show
data:
  address: "A4:C1:38:XX:XX:XX"
  big: 5.7
  small: 98
  happy: true
  validity: 60
```

After about 60 s the display should show only its own reading.

## H8: 50 writes

Create a script in **Settings → Automations & scenes → Scripts → Edit in YAML**:

```yaml
sequence:
  - repeat:
      count: 50
      sequence:
        - action: lcd_ticker.show
          data:
            address: "A4:C1:38:XX:XX:XX"
            big: "{{ repeat.index }}"
            small: "{{ repeat.index }}"
            validity: 65535
        - delay: "00:00:10"
```

Check that the LCD shows the last number and that the Home Assistant log has no write
errors.
