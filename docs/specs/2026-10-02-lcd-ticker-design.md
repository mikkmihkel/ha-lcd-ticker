# LCD Ticker — design spec

Date: 2026-10-02 · Status: draft for review · Target repo: `mikkmihkel/ha-lcd-ticker`

## 1. Goal

A Home Assistant custom integration, distributed through HACS, that turns a Xiaomi
LYWSD03MMC thermometer running pvvx firmware into a small glanceable display for **any**
Home Assistant value. It can rotate between several screens on a predictable battery
budget, and it is set up entirely from the HA UI.

It grows out of `jozefpis/xiaomi-LYWSD03MMC-to-solar-meter` (MIT), which supports one
solar use case through a single YAML-enabled action.

**Success criteria**

1. A flashed thermometer is discovered automatically. Adding it and a first screen takes
   under two minutes without touching YAML.
2. Each screen can show any numeric entity. Presets cover solar, room climate and
   electricity price (Nord Pool, c/kWh with VAT).
3. The user chooses the rotation speed, the number of screens, and whether the
   thermometer's own reading is part of the rotation. The UI shows the expected updates
   per hour before saving.
4. There are no runtime dependencies beyond HA core, no network access other than local
   Bluetooth, and CI pins every action to a commit SHA.
5. Everything works on a Raspberry Pi's built-in Bluetooth, which is the user's test
   setup. ESPHome Bluetooth proxies work through the same HA stack.
6. The first release passes `hassfest` and the HACS action and is eligible for the HACS
   default list.

### Guiding principle: keep it simple and secure

Each feature below is built the simplest way that works, with safe defaults, input
validated at the boundary, and no clever code. Anything not in this spec is out of scope
for v1.

## 2. Decisions (2026-10-02)

| # | Decision |
|---|---|
| D1 | Hardware scope v1: LYWSD03MMC only. Other pvvx LCD devices are documented as "untested, may work". |
| D2 | New repo `mikkmihkel/ha-lcd-ticker`, not a GitHub fork. Display name **LCD Ticker**, domain `lcd_ticker`. The upstream author is credited in LICENSE and README. Names avoid "Xiaomi" (trademark) and "pvvx" (the firmware author's handle, which reads as "photovoltaic"). Both names appear in the README and the HACS description for search. |
| D3 | Two modes per thermometer: *Single screen + built-in reading* (free alternation by the firmware) and *Rotating screens* (budgeted). In both modes the user sets the speed. In rotating mode they also set the screens and whether the built-in reading is one of them. |
| D4 | Screen values come from an entity with multiplier/offset/decimals and automatic unit conversion, started from a preset. No Jinja templates in v1. Averages and sums come from HA helpers (Min/Max, Statistics, Template). |
| D5 | Architecture approach 1: config entry per thermometer, config subentry per screen, a scheduler per thermometer, one global BLE queue. Runtime settings are also exposed as entities. |
| D6 | Minimum HA version is 2026.3, which brings config subentries and the integration's own `brand/` icons. |
| D8 | Keep it simple and secure: the simplest implementation of each feature, hard to misuse or misconfigure. Section 13 lists the few removals the user confirmed. |

## 3. Hardware and protocol

### 3.1 Known facts (verified in pvvx source on `master`, release v5.7 from 2026-03-21)

- GATT characteristic `00001f1f-0000-1000-8000-00805f9b34fb`, written without response.
- **External data, `0x22`** (`CMD_ID_EXTDATA`). The struct is in `app.h` and the handler
  in `cmd_parser.c`. The frame is 8 bytes:

  | Bytes | Content |
  |---|---|
  | `[0]` | `0x22` |
  | `[1:3]` | big number, int16 LE, value×10, range −995…19995 |
  | `[3:5]` | small number, int16 LE, range −9…99 |
  | `[5:7]` | validity, uint16 LE, seconds; `0xFFFF` = permanent until reboot |
  | `[7]` | flags: bits0-2 smiley (a 3-bit **value**, not three bits), bit3 %, bit4 battery icon, bits5-7 unit |

  - **Correction to upstream:** the upstream code treats happy, sad and bracket as
    separate bits. In the firmware they form one 3-bit smiley value. The upstream
    combinations map onto that value:

    | Value | Face |
    |---|---|
    | 0 | none |
    | 1 | `^_^` |
    | 2 | `-∧-` |
    | 3 | `Δ△Δ` |
    | 5 | `(^_^)` |
    | 6 | `(-∧-)` |
    | 4, 7 | unknown (H5) |

    We model the face as an enum. The compat action keeps the old booleans and converts
    them.
  - Unit codes (`temp_symbol`): 0 none, 1 °Г, 2 `-`, 3 °F, 4 `_`, 5 °C, 6 `=`, 7 °E.
  - A frame shorter than 8 bytes updates only the leading fields. We always send the
    full frame.
- **Golden frame:** big 5.7, small 98, %, face 5, validity 65535 →
  `22 39 00 62 00 ff ff 0d`.
- **Big number display** (`show_big_number_x10`):
  - One decimal from −9.5 to 199.5.
  - Above 199.5 (or below −9.5) an integer: up to 1999, down to −99.
  - `iH` above 1999.5, `oL` below −99.5.
- **Small number display:** an integer from −9 to 99, otherwise `iH`/`oL`.
- We clamp so `iH`/`oL` never appear.
- **Time, `0x23`:** `23 | uint32 LE unix time`. The device clock advances once per
  second.
- **Validity behavior** (in `lcd()`):
  - `0xFFFF`: external data only, with no alternation, until reboot or a new finite
    write.
  - Finite: `expiry = device_utc + vtime`. While valid, the screen alternates on a stage
    counter: external data on stages where `stage & 2`, its own reading otherwise. The
    stage step is `min_step_time_update_lcd`, default 2.45 s on LYWSD03MMC, so about
    4.9 s each. After expiry it shows its own reading only.
  - Device config can change what appears in the external stages:
    - `show_batt_enabled` makes odd external stages show battery % instead of our face
      and small number.
    - `show_time_smile` shows the clock there.
    - A battery at 5 % or lower forces the battery display.
    - Validity `0xFFFF` bypasses all of this.
  - A new frame shows at the next stage tick, so up to about 2.45 s later. The data is
    copied as soon as the write arrives, so we can disconnect immediately.
  - Validity 1 reverts to the device's own reading after about 1–2 s.
- The device advertises its own readings, including battery (BTHome v2 on recent
  firmware). Its default name is `ATC_` plus 6 hex digits of the MAC (`ble_set_name`).
  Users can rename it.
- Each frame is an independent write, so several writes per connection are fine. The
  display shows the last one.
- Power: about 14–15 µA while advertising. There are no published figures for a
  connection. Upstream measured that one write per minute drains a CR2032 in a few
  months. Writes every 3–8 minutes in daytime only is the upstream-tested setup.

### 3.2 Hardware checks (on the user's LYWSD03MMC + Raspberry Pi, before features depend on them)

Results are recorded in `docs/hardware-checks.md`. Each feature that depends on a check
has a fallback in case the check fails.

| ID | Check | Feature depending on it | Fallback if it fails |
|---|---|---|---|
| H1 | The golden frame displays correctly | everything | stop and debug |
| H2 | Validity = 1 makes the LCD show its own reading within about 1–2 s (source says yes) | built-in slot, "show built-in when inactive" | use validity = 2–5 |
| H3 | Finite-validity alternation on the user's device config (about 4.9 s each; whether battery/clock stages appear) | single + built-in mode, "alternate if HA stops" | document it; the README explains `show_batt_enabled`/`show_time_smile` |
| H4 | Big number: one decimal up to 199.5, integer above, clamps at 1999.5 and −99.5 (source says yes) | rendering decimals | adjust clamps |
| H5 | What each of the 8 unit codes and 8 smiley values looks like (photo table) | marker and face picker labels, README | hide values that look broken |
| H6 | Finite validity expires on time without any time sync | finite validity | send `0x23` before finite-validity frames |
| H7 | BTHome device exists for the same MAC; README tells users the battery is on that device | battery display | document where the battery appears |
| H8 | Write-without-response followed by an immediate disconnect is reliable over 50 writes | BLE layer | add a 0.5 s delay before disconnecting |
| H9 | Two-week soak at Balanced, battery % logged daily | profile defaults, README battery guide | adjust profiles |

## 4. Architecture

```
custom_components/lcd_ticker/
  __init__.py      setup/unload, runtime_data, registers actions in async_setup
  const.py         domain, keys, profile table, limits
  protocol.py      PURE  frame encoding: build_ext_frame(DisplayFrame), build_time_frame(ts)
  render.py        PURE  ScreenConfig + source values → DisplayFrame (conversion, clamp, faces, markers)
  presets.py       PURE  preset definitions → default ScreenConfig fields + which pickers to show
  scheduler.py     per-thermometer state machine (no BLE, no HA config flow)
  ble.py           global BleWriter: queue, connect, write, disconnect, error classification
  config_flow.py   entry flow (bluetooth/user/confirm), options flow, ScreenSubentryFlow
  entity.py        base entity (has_entity_name, device_info)
  switch.py select.py number.py button.py sensor.py binary_sensor.py
  diagnostics.py   redacted config + scheduler/BLE state
  services.yaml  icons.json  strings.json  translations/en.json  manifest.json
  brand/icon.png  brand/icon@2x.png  brand/logo.png
```

### 4.1 Module contracts

- **`protocol.py`**
  - `DisplayFrame` is a frozen dataclass: `big: float`, `small: int`, `validity: int`,
    `unit: Unit`, `face: Face` (IntEnum 0–7), `percent: bool`, `battery: bool`.
  - `face_from_flags(happy, sad, bracket) -> Face` exists for the compat action.
  - `build_ext_frame(frame) -> bytes` clamps, rounds and packs `<BhhHB`.
  - `build_time_frame(unix_ts) -> bytes`.
  - It has no HA imports and is 100 % unit-tested.
- **`render.py`**
  - `render(screen: ScreenConfig, values: SourceValues, validity: int) -> DisplayFrame | None`.
  - `SourceValues` holds each referenced entity's state and unit, already read by the
    scheduler.
  - It returns `None` when a required source is unavailable or not numeric.
  - It owns unit conversion (through HA's `homeassistant.util.unit_conversion`
    converters), multiplier/offset, decimals, the self-consumption computation, the face
    rule and markers.
  - It is pure and does no I/O.
- **`presets.py`**
  - `PRESETS: dict[str, Preset]`.
  - Each `Preset` has the default `ScreenConfig` field values and the list of entity
    pickers its form shows.
- **`scheduler.py`**
  - `Scheduler(hass, entry, writer)` exposes `async_start()`, `async_stop()`,
    `apply_options()`, `show_now(screen_id | None)`, `refresh()`.
  - Read-only properties: `current_screen`, `last_frame`, `last_success`, `last_error`,
    `updates_last_hour`, `estimated_updates_per_hour`.
  - It listens to state changes of referenced entities and to the presence and active
    entities, and it uses `async_track_point_in_utc_time` for due times.
  - Entities subscribe to it through a dispatcher signal per entry.
- **`ble.py`**
  - `BleWriter(hass)` is created once in `hass.data[DOMAIN]` and shared by all entries.
  - `async write(address, frames: list[bytes]) -> None` raises `DeviceUnreachable` or
    `WriteFailed`.
  - Writes are serialized with one `asyncio.Lock`, so they are handled one at a time,
    first come first served. Each scheduler awaits its own write, so a thermometer never
    has more than one write in flight. No queue-replacement logic is needed.
  - Connections go through `bluetooth.async_ble_device_from_address(...,
    connectable=True)` and `bleak_retry_connector.establish_connection(...,
    max_attempts=3)`, under a 20 s overall timeout. The connection is always closed in
    `finally`.

### 4.2 Data model

**Config entry `data`:** `address` (upper-case MAC). The entry `unique_id` is the
address, so one entry per thermometer.

**Config entry `options`** (all editable in the options flow; the starred ones also work
as entities and apply live without a reload):

| Key | Type | Default (Balanced) |
|---|---|---|
| `profile` | eco / balanced / responsive / custom | balanced |
| `mode`* | single_builtin / rotating | rotating |
| `enabled`* | bool | true |
| `seconds_per_screen`* | 30…3600 | 480 |
| `presence_entity` | entity id or empty | – |
| `seconds_per_screen_present`* | 30…3600 | 180 |
| `builtin_in_rotation` | bool | false |
| `builtin_seconds` | 30…3600 | 120 |
| `active_entity` | binary_sensor/input_boolean/sun/etc. or empty | – |
| `quiet_start`, `quiet_end` | time or empty | – |
| `inactive_display` | builtin / zeros / leave | builtin |
| `on_ha_stop` | freeze / alternate | freeze |

**Profiles:**

| Profile | Normal | Present |
|---|---|---|
| eco | 900 s | 300 s |
| balanced | 480 s | 180 s (the upstream-tested values) |
| responsive | 180 s | 90 s |

Editing a speed sets the profile to `custom`. The presence linger is fixed at 10 min and
the minimum gap between writes is fixed at 60 s, both as constants.

**Screen subentry** (`subentry_type: "screen"`) `data`:

```
preset: solar | climate | price | single | custom
position: int                     # rotation order, ascending
enabled: bool
seconds: int | None               # time-on-screen override
jump_delta: float | None          # "show immediately on big change"
big:   {entity_id, convert: none|kW|°C|°F|c/kWh, multiplier: 1.0, offset: 0.0, decimals: auto|0|1}
                                  # auto = 1 decimal where the LCD can show it (−9.5…199.5), else integer
small: {source: none|entity|fixed|self_consumption, entity_id, convert, multiplier, offset, fixed: int}
solar: {production_entity, export_entity}            # only for small.source = self_consumption
look:  {unit: none|deg_c|deg_f|minus|lowdash|lines|deg_ghe|deg_e, percent, battery, bracket}
face:  {mode: none|fixed|scale, fixed: Face,
        source: big|small, direction: higher_better|lower_better, thresholds: [t1,t2,t3,t4]}
vat_percent: float | None         # price preset; folded into the multiplier at render time
```

## 5. Setup UX

### 5.1 Adding a thermometer

- **Discovery:** the manifest matches `local_name: "ATC_*"` with `connectable: true`. The
  discovery card reads "LCD Ticker: ATC_1A2B3C". Renamed devices are added through the
  manual path.
- **Manual (`user` step):** a picker of nearby connectable `ATC_*` devices, plus a
  "Enter MAC manually" option.
- **Confirm step:** a name (default "ATC_1A2B3C display") and a profile. On submit it
  sends a test frame (happy face, validity 10 s). On failure it shows the error
  `cannot_connect` with a hint about range and adapter support, and you can retry.
- After setup, HA prompts with an **Add screen** button.

### 5.2 Options flow (Configure)

- One form with the options from 4.2, grouped into sections: *Rotation*, *Presence*,
  *When to pause*, *Safety*.
- The description shows **"≈ N updates/hour (M while someone is present)"**, computed
  from the current values. Above 30/h it adds a battery warning. It is a warning only and
  does not block saving.

### 5.3 Screen subentry flow (Add screen / Reconfigure)

1. **Preset:** solar, climate, price, single or custom.
2. **Sources:** only the pickers the preset needs, filtered by domain `sensor` and the
   relevant device class (power, temperature, humidity, monetary/none). This step also
   holds the multiplier, offset, decimals and VAT %.
3. **Look and order:** marker unit, % sign, battery icon, brackets, face rule and
   thresholds, position, time-on-screen override, jump delta, enabled.

The subentry title defaults to the preset name plus the main entity's friendly name
(for example "Price · Nord Pool EE"), and you can edit it.

### 5.4 Presets

| Preset | Big | Small | Look and face |
|---|---|---|---|
| solar | production → kW, 1 decimal | self-consumption % = (production − export) / production. 0 when production < 50 W. Alternatively pick an existing % sensor. | `%`; face scale on small, higher is better, thresholds 20/40/60/80 (the upstream mapping) |
| climate | temperature → °C, 1 decimal | humidity %, 0 decimals | unit `deg_c`, `%`, no face |
| price | price → c/kWh (EUR/kWh ×100, EUR/MWh ÷10, read from the unit), × (1 + VAT %) | optional entity (for example the next price), rounded | no unit; face scale on big, lower is better, thresholds 5/10/15/20 c |
| single | one entity, user conversion | none | user choice |
| custom | everything manual | everything manual | everything manual |

The face scale has five levels, using the upstream mapping. Best to worst: `(^_^)` (5) ·
`^_^` (1) · `Δ△Δ` (3) · `-∧-` (2) · `(-∧-)` (6). With *lower is better* the thresholds
are read in reverse.

### 5.5 Telling screens apart

Each screen should differ by at least one marker: unit symbol, brackets, `%`, the
battery icon, or `small.source = fixed` (a screen number). The subentry flow warns,
without blocking, when a new screen's markers are identical to an existing screen's.

## 6. Runtime behavior

### 6.1 Rotating mode

- The **eligible screens** are those that are enabled, sorted by `position`, and
  render to a frame (not `None`). The built-in slot is inserted after the last screen
  when `builtin_in_rotation` is on.
- **At each due time:**
  1. Advance to the next eligible screen and render it.
  2. If the frame equals `last_frame`, skip the write and keep the slot timing.
  3. Otherwise write it.
  4. Schedule the next due time at now + (the screen's `seconds`, or
     `seconds_per_screen_present` while present, or `seconds_per_screen`).
- **Presence** counts as on while the presence entity is `on`/`home`, and for 10 min
  after it turns off.
- **Jump:** when a referenced entity changes and the screen's value moved by at least
  `jump_delta` since that screen was last shown, show that screen now, provided 60 s have
  passed since the last write. Rotation then continues from it.
- **Built-in slot:** write a frame with validity = 1 (H2), so the LCD shows its own
  reading for `builtin_seconds`.

### 6.2 Single + built-in mode

- Only the screen at the lowest position counts.
- Validity = `max(3 × seconds_per_screen, 1800)`, capped at 65534. The firmware
  alternates our frame with its own reading.
- It writes when the rendered frame changes, at most once per `seconds_per_screen`, and
  also refreshes when 2/3 of the validity has elapsed.
- No time sync is needed. Expiry is computed against the device's own clock
  (`chow_ext_ut = utc_time_sec + vtime`, compared with the same counter), so it is
  relative. Correction from the earlier draft, 2026-10-02.

### 6.3 Validity in rotating mode

- `on_ha_stop = freeze`: validity 65535.
- `on_ha_stop = alternate`: validity = `max(3 × the longest time on screen, 1800)`,
  capped at 65534. No time sync is needed (see 6.2).
  The firmware then alternates every screen with its own reading. The options flow
  explains this.

### 6.4 Pausing

- The thermometer is **inactive** when `enabled` is off, the active entity is not
  on/home/`above_horizon`, or the time is inside quiet hours (a window that crosses
  midnight is allowed).
- On becoming inactive, it writes one frame according to `inactive_display`:
  - `builtin`: validity-1 frame
  - `zeros`: 0 / 0 with the first screen's markers
  - `leave`: no write
- On becoming active it writes immediately, respecting the 60 s gap.
- After an HA start it writes once 30 s after `EVENT_HOMEASSISTANT_STARTED`.

### 6.5 Bluetooth and errors

- All writes go through the global `BleWriter` (see 4.1). The writer never retries
  beyond `establish_connection`'s own attempts. A failed write is recorded and the next
  scheduled turn simply tries again.
- When `async_ble_device_from_address` returns nothing, the error is
  `DeviceUnreachable`, and the scheduler logs it once at warning level until the next
  success (the HA log-when-unavailable rule).
- **Repairs issue** `unreachable_<entry_id>`: created after 5 consecutive failures, or
  when there has been no success for 1 h while active. Deleted on the next success.
- Unload cancels timers, removes the listeners and drops this entry's pending writes.

## 7. Entities and actions

The device has `connections = {(CONNECTION_BLUETOOTH, address)}`. Home Assistant 2026.9
keeps one device per config entry, so the BTHome device for the same MAC does not merge
onto it. It stays a separate device, and the README tells users the battery is on that
one (H7). The model is "LYWSD03MMC (pvvx)". There are no per-screen entities in v1.

| Platform | Entity | Notes |
|---|---|---|
| switch | Rotation | `enabled` |
| select | Mode | single_builtin / rotating |
| select | Screen | shows the current screen; selecting one shows it now |
| number | Seconds per screen | box mode, 30–3600 |
| number | Seconds per screen (present) | box mode |
| button | Refresh now | rewrites the current screen |
| sensor | Last update | timestamp |
| sensor | Updates (last hour) | diagnostic |
| sensor | Estimated updates per hour | diagnostic |
| sensor | Last error | diagnostic, disabled by default |
| binary_sensor | Reachable | connectivity; off after a failed write |

Changes made through entities are written to the entry options, so they persist. The entry
update listener fires for option changes **and** subentry changes (verified in
`ConfigEntries.async_update_subentry` → `_async_save_and_notify`). The listener compares
the new state with a snapshot:

- If only the starred live keys changed, it calls `scheduler.apply_options()`.
- If anything else changed (other options, or screens added, edited or removed), it
  reloads the entry.

Because we register an update listener, subentry flows use `async_update_and_abort`.
`async_update_reload_and_abort` refuses entries that have listeners.

**Action** (registered in `async_setup`, translated, with `icons.json`). To show a
specific screen from an automation, use `select.select_option` on the Screen entity. No
separate action is needed.

- **`lcd_ticker.show`:** a raw frame, compatible with upstream `pvvx_display.show`. It
  takes the same fields as upstream (`big`, `small`, `validity`, `unit`, `percent`,
  `battery`, `happy`, `sad`, `bracket`). The target is either a `device_id` (device
  selector filtered to `lcd_ticker`) or `address`, so it also works for thermometers
  that aren't configured. Rotation is unaffected: the next scheduled screen overwrites
  it. For a long-lived manual value, turn the Rotation switch off first.

## 8. Security and third-party policy

- **Runtime requirements:** none. `manifest.json` has `"requirements": []` and
  `"dependencies": ["bluetooth_adapters"]`, as in the inkbird and switchbot manifests at
  2026.9.3. It uses HA's bundled `bleak`, `bleak-retry-connector` and `habluetooth`.
- **No network, telemetry or remote code.** There's no frontend JS in v1.
- **Diagnostics** redact the MAC and any entity ids the user marks private. In practice
  we redact `address` and leave entity ids in.
- **CI:**
  - Every `uses:` is pinned to a 40-char SHA with a `# vX.Y.Z` comment.
  - Workflow-level `permissions: {}`, with job-level grants only where needed (the
    release job gets `contents: write`).
  - No `pull_request_target`. Releases use the preinstalled `gh` CLI, so no third-party
    release action is needed.
  - Dependabot updates `github-actions` and `pip` weekly.
- **Dev dependencies** are pinned exactly in `requirements_test.txt`, checked on
  2026-10-02. Python is 3.14.
  - `pytest-homeassistant-custom-component==0.13.367` (pins HA 2026.9.4)
  - `ruff==0.16.10`
  - `pytest-cov==7.1.0`
- **Action pins**, checked on 2026-10-02. Dependabot keeps them current.

  | Action | Version | Commit |
  |---|---|---|
  | `actions/checkout` | v7.0.1 | `3d3c42e5aac5ba805825da76410c181273ba90b1` |
  | `actions/setup-python` | v7.0.0 | `5fda3b95a4ea91299a34e894583c3862153e4b97` |
  | `hacs/action` | main | `1ebf01c408f29afcb6406bd431bc98fd8cbb15aa` |
  | `home-assistant/actions/hassfest` | master | `06749dd8c0b54f350bc69c8752456cee498808a3` |

  No other actions are used. The implementer re-checks these SHAs against the GitHub API.
- **Repo settings** (manual, documented in CONTRIBUTING):
  - branch protection on `main`, with required checks and no force-push
  - secret scanning and push protection
  - private vulnerability reporting
  - CodeQL default setup
- `SECURITY.md` explains how to report a vulnerability.
- **Upstream review result:** the upstream code is small and clean. Its only requirement
  was `bleak-retry-connector`, which is bundled with HA. The firmware is third-party; the
  README links a specific pvvx release and states the flashing risk plainly.

## 9. Repository, versioning and release

```
ha-lcd-ticker/
  custom_components/lcd_ticker/...
  tests/  (conftest.py, test_protocol.py, test_render.py, test_presets.py, test_scheduler.py,
           test_ble.py, test_config_flow.py, test_subentry_flow.py, test_init.py, test_entities.py,
           test_services.py, test_diagnostics.py)
  docs/specs/  docs/hardware-checks.md  docs/images/
  .github/workflows/ci.yml  release.yml  validate.yml   .github/dependabot.yml
  .github/ISSUE_TEMPLATE/{bug.yml,feature.yml}
  hacs.json  pyproject.toml (ruff + pytest config)  requirements_test.txt
  README.md  CHANGELOG.md  CONTRIBUTING.md  SECURITY.md  LICENSE
```

- **LICENSE:** MIT, with `Copyright (c) 2026 jozefpis` and
  `Copyright (c) 2026 Mikk Mihkel Vaabel`.
- **`hacs.json`:** `{"name": "LCD Ticker", "homeassistant": "2026.3.0", "render_readme": true}`.
- **Versions:** SemVer.
  - `0.1.0` is the first public pre-release, after H1–H8 pass.
  - `1.0.0` follows the H9 soak and at least one other tester.
  - `manifest.json` `version` must equal the tag. CI checks this on tag push.
- **Release flow:**
  1. Bump the version and CHANGELOG in a PR.
  2. After merging, push tag `vX.Y.Z`.
  3. `release.yml` runs the tests and validation, then `gh release create` with that
     CHANGELOG section.

  Never without the user's go-ahead.
- **HACS default list:** submitted after `0.1.0` has a release, and the repo has a
  description, topics (`home-assistant`, `hacs`, `bluetooth`, `lywsd03mmc`, `pvvx`,
  `display`) and `brand/icon.png`.
- **README:**
  - what it does, with photos
  - flashing (linking a pinned pvvx release and Telink flasher), stating the risk
  - install via HACS and manually
  - setup walkthrough with screenshots
  - presets
  - battery guide (profiles, the updates/hour meaning)
  - "Coming from pvvx_display" (rename the action)
  - troubleshooting
  - removal instructions
  - credits

## 10. Testing

- **Pure modules** (`protocol`, `render`, `presets`): table-driven tests covering the
  golden frame, clamps at every limit, rounding, all units and flags, conversions (W→kW,
  °F→°C, EUR/MWh→c/kWh), VAT, self-consumption guards, the face scale in both
  directions, and unavailable or non-numeric values.
- **Scheduler:** HA test harness with time travel (`async_fire_time_changed`) and a fake
  writer. Cases:
  - rotation order and skipping
  - skip-unchanged
  - presence speed-up and linger
  - jump with the 60 s gap
  - built-in slot
  - single-mode refresh at 2/3 validity
  - quiet hours across midnight
  - active entity on/off and the inactive display
  - the start delay
  - apply_options live
  - failure counting and the repairs issue lifecycle
- **BLE:** mocked `async_ble_device_from_address` and `establish_connection`. Cases:
  serialization across entries, disconnect on error, timeout,
  error classification.
- **Flows:**
  - bluetooth discovery
  - the manual picker and manual MAC
  - test-before-configure success and failure
  - duplicate abort
  - options with the updates/hour description
  - each preset's subentry path
  - subentry reconfigure
  - the duplicate-marker warning
- **Integration:** setup and unload, the entities and their live option updates, both
  action, diagnostics redaction.
- **Fixtures:** `enable_bluetooth`, `mock_bluetooth_adapters` and
  `mock_bleak_scanner_start` come from the plugin. Core's advertisement-injection helpers
  are not packaged, so tests build `BluetoothServiceInfoBleak` objects and patch
  `async_discovered_service_info` and `async_ble_device_from_address` at our module
  boundary.
- **Coverage gate:** at least 95 % overall in CI.
- **Hardware:** the H1–H9 checklist on the user's device, recorded with dates and photos.

## 11. Out of scope for v1

- Other pvvx devices (MHO-C401, CGG1, MJWSD05MMC), and raw LCD segment writes (`0x60`).
- Jinja templates as sources, our own averaging, a custom dashboard card.
- Writing pvvx device configuration (`0x55`), such as advertising interval or comfort
  smiley.
- Multiple thermometers sharing one screen set; each thermometer has its own screens.
- Per-screen entities.

## 12. Verification status

Checked on 2026-10-02 against HA core `2026.9.3`, pvvx `master`/v5.7 source,
`pytest-homeassistant-custom-component`, and the GitHub/PyPI APIs:

- manifest dependency
- bluetooth flow API
- subentry API and listener semantics
- selectors and unit converters
- repairs API
- test fixtures
- frame layouts
- display ranges
- validity behavior

What remains is hardware behavior, covered by H1–H9.

## 13. Removals confirmed by the user (2026-10-02)

| Removed | Covered by |
|---|---|
| `lcd_ticker.show_screen` action | `select.select_option` on the Screen entity |
| `pause_rotation` field on `lcd_ticker.show` | The Rotation switch |
| "Latest wins" write-queue replacement | A plain lock, with each scheduler awaiting its own write |
| Time sync (`0x23`) entirely | Not needed, because validity is relative to the device's own clock (source check, 2026-10-02). `build_time_frame` stays in `protocol.py` as the H6 fallback. |

Kept at the user's request: the "If HA stops" option, per-screen "show immediately on big
change", the duplicate-marker warning, both Repairs triggers (5 failures or 1 h), and the
Estimated updates/hour and Last error diagnostic sensors.

