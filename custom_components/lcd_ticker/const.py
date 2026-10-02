"""Constants for LCD Ticker."""

from __future__ import annotations

from typing import Any, Final

from homeassistant.const import Platform

DOMAIN: Final = "lcd_ticker"

PLATFORMS: Final = [
    Platform.BINARY_SENSOR,
    Platform.BUTTON,
    Platform.NUMBER,
    Platform.SELECT,
    Platform.SENSOR,
    Platform.SWITCH,
]

CHAR_UUID: Final = "00001f1f-0000-1000-8000-00805f9b34fb"
DEFAULT_NAME_PREFIX: Final = "ATC_"

SUBENTRY_SCREEN: Final = "screen"
BUILTIN_SLOT: Final = "builtin"

# Config entry data
CONF_ADDRESS: Final = "address"

# Config entry options
CONF_PROFILE: Final = "profile"
CONF_MODE: Final = "mode"
CONF_ENABLED: Final = "enabled"
CONF_SECONDS: Final = "seconds_per_screen"
CONF_PRESENCE_ENTITY: Final = "presence_entity"
CONF_SECONDS_PRESENT: Final = "seconds_per_screen_present"
CONF_BUILTIN_IN_ROTATION: Final = "builtin_in_rotation"
CONF_BUILTIN_SECONDS: Final = "builtin_seconds"
CONF_ACTIVE_ENTITY: Final = "active_entity"
CONF_QUIET_START: Final = "quiet_start"
CONF_QUIET_END: Final = "quiet_end"
CONF_INACTIVE_DISPLAY: Final = "inactive_display"
CONF_ON_HA_STOP: Final = "on_ha_stop"

MODE_SINGLE: Final = "single_builtin"
MODE_ROTATING: Final = "rotating"
MODES: Final = [MODE_SINGLE, MODE_ROTATING]

PROFILE_ECO: Final = "eco"
PROFILE_BALANCED: Final = "balanced"
PROFILE_RESPONSIVE: Final = "responsive"
PROFILE_CUSTOM: Final = "custom"
# profile -> (seconds_per_screen, seconds_per_screen_present)
PROFILES: Final[dict[str, tuple[int, int]]] = {
    PROFILE_ECO: (900, 300),
    PROFILE_BALANCED: (480, 180),
    PROFILE_RESPONSIVE: (180, 90),
}
PROFILE_OPTIONS: Final = [*PROFILES, PROFILE_CUSTOM]

INACTIVE_BUILTIN: Final = "builtin"
INACTIVE_ZEROS: Final = "zeros"
INACTIVE_LEAVE: Final = "leave"
INACTIVE_OPTIONS: Final = [INACTIVE_BUILTIN, INACTIVE_ZEROS, INACTIVE_LEAVE]

HA_STOP_FREEZE: Final = "freeze"
HA_STOP_ALTERNATE: Final = "alternate"
HA_STOP_OPTIONS: Final = [HA_STOP_FREEZE, HA_STOP_ALTERNATE]

# Options that entities may change at runtime; changing only these never reloads.
LIVE_OPTION_KEYS: Final = frozenset(
    {CONF_PROFILE, CONF_MODE, CONF_ENABLED, CONF_SECONDS, CONF_SECONDS_PRESENT}
)

# Limits and timings (seconds unless noted)
MIN_SECONDS: Final = 30
MAX_SECONDS: Final = 3600
DEFAULT_BUILTIN_SECONDS: Final = 120
MIN_WRITE_GAP: Final = 60
PRESENCE_LINGER: Final = 600
START_DELAY: Final = 30
RELOAD_DELAY: Final = 2
ACTIVITY_CHECK_INTERVAL: Final = 60
WRITE_TIMEOUT: Final = 60  # bleak-retry-connector needs up to ~20 s per attempt
DISCONNECT_TIMEOUT: Final = 5
CONNECT_ATTEMPTS: Final = 3
FAILURES_FOR_ISSUE: Final = 5
NO_SUCCESS_FOR_ISSUE: Final = 3600
WARN_UPDATES_PER_HOUR: Final = 30

VALIDITY_PERMANENT: Final = 0xFFFF
VALIDITY_BUILTIN: Final = 1
VALIDITY_TEST: Final = 10
MIN_FINITE_VALIDITY: Final = 1800
MAX_FINITE_VALIDITY: Final = 0xFFFE

ACTIVE_STATES: Final = frozenset({"on", "home", "above_horizon"})
PRESENT_STATES: Final = frozenset({"on", "home"})

ISSUE_UNREACHABLE: Final = "unreachable"

# Screen subentry data (flat keys)
CONF_TITLE: Final = "title"  # form field only; stored as the subentry title
CONF_PRESET: Final = "preset"
CONF_POSITION: Final = "position"
CONF_SCREEN_ENABLED: Final = "enabled"
CONF_SCREEN_SECONDS: Final = "seconds"  # 0 = use the thermometer's speed
CONF_JUMP_DELTA: Final = "jump_delta"  # 0 = off
CONF_BIG_ENTITY: Final = "big_entity"
CONF_BIG_CONVERT: Final = "big_convert"
CONF_BIG_MULTIPLIER: Final = "big_multiplier"
CONF_BIG_OFFSET: Final = "big_offset"
CONF_BIG_DECIMALS: Final = "big_decimals"
CONF_VAT_PERCENT: Final = "vat_percent"  # applied to fields converted to c/kWh
CONF_SMALL_SOURCE: Final = "small_source"
CONF_SMALL_ENTITY: Final = "small_entity"
CONF_SMALL_CONVERT: Final = "small_convert"
CONF_SMALL_MULTIPLIER: Final = "small_multiplier"
CONF_SMALL_OFFSET: Final = "small_offset"
CONF_SMALL_FIXED: Final = "small_fixed"
CONF_PRODUCTION_ENTITY: Final = "production_entity"
CONF_EXPORT_ENTITY: Final = "export_entity"
CONF_UNIT: Final = "unit"
CONF_PERCENT: Final = "percent"
CONF_BATTERY: Final = "battery"
CONF_FACE_MODE: Final = "face_mode"
CONF_FACE_FIXED: Final = "face_fixed"
CONF_FACE_SOURCE: Final = "face_source"
CONF_FACE_DIRECTION: Final = "face_direction"
CONF_FACE_T1: Final = "face_t1"
CONF_FACE_T2: Final = "face_t2"
CONF_FACE_T3: Final = "face_t3"
CONF_FACE_T4: Final = "face_t4"
CONF_SHOW_WHEN: Final = "show_when_entity"  # None = always eligible
CONF_TAKEOVER: Final = "takeover"  # while show_when is on, show only such screens
FACE_THRESHOLD_KEYS: Final = (CONF_FACE_T1, CONF_FACE_T2, CONF_FACE_T3, CONF_FACE_T4)

PRESET_SOLAR: Final = "solar"
PRESET_CLIMATE: Final = "climate"
PRESET_PRICE: Final = "price"
PRESET_SINGLE: Final = "single"
PRESET_CUSTOM: Final = "custom"
PRESETS_ORDER: Final = [
    PRESET_SOLAR,
    PRESET_CLIMATE,
    PRESET_PRICE,
    PRESET_SINGLE,
    PRESET_CUSTOM,
]

CONVERT_NONE: Final = "none"
CONVERT_KW: Final = "kw"
CONVERT_CELSIUS: Final = "celsius"
CONVERT_FAHRENHEIT: Final = "fahrenheit"
CONVERT_CENTS_KWH: Final = "cents_per_kwh"
CONVERT_OPTIONS: Final = [
    CONVERT_NONE,
    CONVERT_KW,
    CONVERT_CELSIUS,
    CONVERT_FAHRENHEIT,
    CONVERT_CENTS_KWH,
]

DECIMALS_AUTO: Final = "auto"
DECIMALS_OPTIONS: Final = [DECIMALS_AUTO, "0", "1"]

SMALL_NONE: Final = "none"
SMALL_ENTITY: Final = "entity"
SMALL_FIXED: Final = "fixed"
SMALL_SELF_CONSUMPTION: Final = "self_consumption"
SMALL_SOURCE_OPTIONS: Final = [
    SMALL_NONE,
    SMALL_ENTITY,
    SMALL_FIXED,
    SMALL_SELF_CONSUMPTION,
]

FACE_MODE_NONE: Final = "none"
FACE_MODE_FIXED: Final = "fixed"
FACE_MODE_SCALE: Final = "scale"
FACE_MODE_OPTIONS: Final = [FACE_MODE_NONE, FACE_MODE_FIXED, FACE_MODE_SCALE]

FACE_SOURCE_BIG: Final = "big"
FACE_SOURCE_SMALL: Final = "small"
FACE_SOURCE_OPTIONS: Final = [FACE_SOURCE_BIG, FACE_SOURCE_SMALL]

DIRECTION_HIGHER: Final = "higher_better"
DIRECTION_LOWER: Final = "lower_better"
DIRECTION_MIDDLE: Final = "middle_best"
DIRECTION_OPTIONS: Final = [DIRECTION_HIGHER, DIRECTION_LOWER, DIRECTION_MIDDLE]

# Self-consumption is 0 below this production (W), as in the upstream example.
SELF_CONSUMPTION_MIN_W: Final = 50


def signal_update(entry_id: str) -> str:
    """Dispatcher signal sent when a scheduler's state changes."""
    return f"{DOMAIN}_{entry_id}_update"


def signal_readings(entry_id: str) -> str:
    """Dispatcher signal sent when the thermometer's own readings change."""
    return f"{DOMAIN}_{entry_id}_readings"


def default_options(profile: str = PROFILE_BALANCED) -> dict[str, Any]:
    """Return the options a new thermometer starts with."""
    seconds, seconds_present = PROFILES[profile]
    return {
        CONF_PROFILE: profile,
        CONF_MODE: MODE_ROTATING,
        CONF_ENABLED: True,
        CONF_SECONDS: seconds,
        CONF_PRESENCE_ENTITY: None,
        CONF_SECONDS_PRESENT: seconds_present,
        CONF_BUILTIN_IN_ROTATION: False,
        CONF_BUILTIN_SECONDS: DEFAULT_BUILTIN_SECONDS,
        CONF_ACTIVE_ENTITY: None,
        CONF_QUIET_START: None,
        CONF_QUIET_END: None,
        CONF_INACTIVE_DISPLAY: INACTIVE_BUILTIN,
        CONF_ON_HA_STOP: HA_STOP_FREEZE,
    }
