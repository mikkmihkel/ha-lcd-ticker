"""Turn a screen's config plus entity states into a DisplayFrame. Pure: no I/O."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
import math
from typing import Any

from homeassistant.const import UnitOfPower, UnitOfTemperature
from homeassistant.util.unit_conversion import PowerConverter, TemperatureConverter

from .const import (
    CONF_BATTERY,
    CONF_BIG_CONVERT,
    CONF_BIG_DECIMALS,
    CONF_BIG_ENTITY,
    CONF_BIG_MULTIPLIER,
    CONF_BIG_OFFSET,
    CONF_EXPORT_ENTITY,
    CONF_FACE_DIRECTION,
    CONF_FACE_FIXED,
    CONF_FACE_MODE,
    CONF_FACE_SOURCE,
    CONF_PERCENT,
    CONF_PRODUCTION_ENTITY,
    CONF_SMALL_CONVERT,
    CONF_SMALL_ENTITY,
    CONF_SMALL_FIXED,
    CONF_SMALL_MULTIPLIER,
    CONF_SMALL_OFFSET,
    CONF_SMALL_SOURCE,
    CONF_UNIT,
    CONF_VAT_PERCENT,
    CONVERT_CELSIUS,
    CONVERT_CENTS_KWH,
    CONVERT_FAHRENHEIT,
    CONVERT_KW,
    CONVERT_NONE,
    DECIMALS_AUTO,
    DIRECTION_HIGHER,
    DIRECTION_LOWER,
    FACE_MODE_FIXED,
    FACE_MODE_NONE,
    FACE_MODE_SCALE,
    FACE_SOURCE_BIG,
    FACE_SOURCE_SMALL,
    FACE_THRESHOLD_KEYS,
    SELF_CONSUMPTION_MIN_W,
    SMALL_ENTITY,
    SMALL_FIXED,
    SMALL_NONE,
    SMALL_SELF_CONSUMPTION,
)
from .protocol import FACE_KEYS, UNIT_KEYS, DisplayFrame, Face, Unit, round_half_away

DEFAULT_THRESHOLDS = (20, 40, 60, 80)
_CENT_NAMES = frozenset(
    {"c", "ct", "cent", "cents", "snt", "öre", "øre", "ore", "p", "gr"}
)
_ENERGY_FACTORS = {"Wh": 1000.0, "kWh": 1.0, "MWh": 0.001}


@dataclass(frozen=True, slots=True)
class SourceValue:
    """An entity's state string and unit of measurement."""

    state: str
    unit: str | None = None


def parse_number(state: str | None) -> float | None:
    """Return the state as a finite float, or None."""
    if not state or state in ("unknown", "unavailable"):
        return None
    try:
        value = float(state)
    except TypeError, ValueError:
        return None
    return value if math.isfinite(value) else None


def price_factor(unit: str | None) -> float | None:
    """Multiplier that turns a '<money>/<energy>' price into c/kWh, or None."""
    if not unit or "/" not in unit:
        return None
    money, _, energy = unit.strip().partition("/")
    money = money.strip()
    factor = _ENERGY_FACTORS.get(energy.strip())
    if not money or factor is None:
        return None
    return factor * (1.0 if money.lower() in _CENT_NAMES else 100.0)


def can_convert(unit: str | None, target: str) -> bool:
    """True if a value in `unit` can be converted to `target`."""
    if target == CONVERT_NONE:
        return True
    if target == CONVERT_KW:
        return unit in PowerConverter.VALID_UNITS
    if target in (CONVERT_CELSIUS, CONVERT_FAHRENHEIT):
        return unit in TemperatureConverter.VALID_UNITS
    if target == CONVERT_CENTS_KWH:
        return price_factor(unit) is not None
    return False


def convert(value: float, unit: str | None, target: str) -> float | None:
    """Convert value to the target, or None if the unit does not fit."""
    if not can_convert(unit, target):
        return None
    if target == CONVERT_KW:
        return PowerConverter.convert(value, unit, UnitOfPower.KILO_WATT)
    if target == CONVERT_CELSIUS:
        return TemperatureConverter.convert(value, unit, UnitOfTemperature.CELSIUS)
    if target == CONVERT_FAHRENHEIT:
        return TemperatureConverter.convert(value, unit, UnitOfTemperature.FAHRENHEIT)
    if target == CONVERT_CENTS_KWH:
        return value * price_factor(unit)
    return value


def face_for(value: float, direction: str, thresholds: Sequence[float]) -> Face:
    """Pick a smiley for value from four thresholds (sorted first)."""
    t1, t2, t3, t4 = sorted(thresholds)
    if direction == DIRECTION_LOWER:
        if value <= t1:
            return Face.HAPPY_BRACKET
        if value <= t2:
            return Face.HAPPY
        if value <= t3:
            return Face.HAPPY_SAD
        if value <= t4:
            return Face.SAD
        return Face.SAD_BRACKET
    if value >= t4:
        return Face.HAPPY_BRACKET
    if value >= t3:
        return Face.HAPPY
    if value >= t2:
        return Face.HAPPY_SAD
    if value >= t1:
        return Face.SAD
    return Face.SAD_BRACKET


def screen_entity_ids(screen: Mapping[str, Any]) -> list[str]:
    """Entities the screen reads, in order, without Nones or duplicates."""
    ids = [screen.get(CONF_BIG_ENTITY)]
    source = screen.get(CONF_SMALL_SOURCE, SMALL_NONE)
    if source == SMALL_ENTITY:
        ids.append(screen.get(CONF_SMALL_ENTITY))
    elif source == SMALL_SELF_CONSUMPTION:
        ids.append(screen.get(CONF_PRODUCTION_ENTITY))
        ids.append(screen.get(CONF_EXPORT_ENTITY))
    result: list[str] = []
    for entity_id in ids:
        if entity_id and entity_id not in result:
            result.append(entity_id)
    return result


def markers(screen: Mapping[str, Any]) -> tuple[Any, ...]:
    """The parts of a screen that change the LCD without any entity changing."""
    face_mode = screen.get(CONF_FACE_MODE, FACE_MODE_NONE)
    small_source = screen.get(CONF_SMALL_SOURCE, SMALL_NONE)
    return (
        screen.get(CONF_UNIT),
        bool(screen.get(CONF_PERCENT, False)),
        bool(screen.get(CONF_BATTERY, False)),
        face_mode,
        screen.get(CONF_FACE_FIXED, "happy_bracket")
        if face_mode == FACE_MODE_FIXED
        else None,
        screen.get(CONF_SMALL_FIXED, 0) if small_source == SMALL_FIXED else None,
    )


def _field_value(
    screen: Mapping[str, Any],
    values: Mapping[str, SourceValue],
    entity_key: str,
    convert_key: str,
    multiplier_key: str,
    offset_key: str,
) -> float | None:
    """Parse, convert, add VAT (prices only), then multiply and offset."""
    source = values.get(screen.get(entity_key))
    if source is None:
        return None
    value = parse_number(source.state)
    if value is None:
        return None
    target = screen.get(convert_key, CONVERT_NONE)
    value = convert(value, source.unit, target)
    if value is None:
        return None
    if target == CONVERT_CENTS_KWH:
        value *= 1 + screen.get(CONF_VAT_PERCENT, 0.0) / 100
    return value * screen.get(multiplier_key, 1.0) + screen.get(offset_key, 0.0)


def _watts(source: SourceValue | None) -> float | None:
    if source is None:
        return None
    value = parse_number(source.state)
    if value is None or source.unit not in PowerConverter.VALID_UNITS:
        return None
    return PowerConverter.convert(value, source.unit, UnitOfPower.WATT)


def _self_consumption(
    screen: Mapping[str, Any], values: Mapping[str, SourceValue]
) -> float | None:
    """Share of production used at home, in percent (0..100)."""
    production_id = screen.get(CONF_PRODUCTION_ENTITY) or screen.get(CONF_BIG_ENTITY)
    production = _watts(values.get(production_id))
    export = _watts(values.get(screen.get(CONF_EXPORT_ENTITY)))
    if production is None or export is None:
        return None
    if production < SELF_CONSUMPTION_MIN_W:
        return 0.0
    return max(0.0, min(100.0, (production - export) / production * 100))


def _face(screen: Mapping[str, Any], big: float, small: int) -> Face:
    mode = screen.get(CONF_FACE_MODE, FACE_MODE_NONE)
    if mode == FACE_MODE_FIXED:
        return FACE_KEYS.get(screen.get(CONF_FACE_FIXED, "happy_bracket"), Face.NONE)
    if mode == FACE_MODE_SCALE:
        source = screen.get(CONF_FACE_SOURCE, FACE_SOURCE_BIG)
        value = small if source == FACE_SOURCE_SMALL else big
        thresholds = [
            screen.get(key, default)
            for key, default in zip(
                FACE_THRESHOLD_KEYS, DEFAULT_THRESHOLDS, strict=True
            )
        ]
        direction = screen.get(CONF_FACE_DIRECTION, DIRECTION_HIGHER)
        return face_for(value, direction, thresholds)
    return Face.NONE


def render(
    screen: Mapping[str, Any], values: Mapping[str, SourceValue], validity: int
) -> DisplayFrame | None:
    """Build the frame, or None if a required value is missing or unusable."""
    big = _field_value(
        screen,
        values,
        CONF_BIG_ENTITY,
        CONF_BIG_CONVERT,
        CONF_BIG_MULTIPLIER,
        CONF_BIG_OFFSET,
    )
    if big is None:
        return None
    if screen.get(CONF_BIG_DECIMALS, DECIMALS_AUTO) == "0":
        big = round_half_away(big)

    small_source = screen.get(CONF_SMALL_SOURCE, SMALL_NONE)
    small: float | None
    if small_source == SMALL_FIXED:
        small = screen.get(CONF_SMALL_FIXED, 0)
    elif small_source == SMALL_ENTITY:
        small = _field_value(
            screen,
            values,
            CONF_SMALL_ENTITY,
            CONF_SMALL_CONVERT,
            CONF_SMALL_MULTIPLIER,
            CONF_SMALL_OFFSET,
        )
    elif small_source == SMALL_SELF_CONSUMPTION:
        small = _self_consumption(screen, values)
    else:
        small = 0
    if small is None:
        return None
    small = round_half_away(small)

    return DisplayFrame(
        big=big,
        small=small,
        validity=validity,
        unit=UNIT_KEYS.get(screen.get(CONF_UNIT), Unit.NONE),
        face=_face(screen, big, small),
        percent=bool(screen.get(CONF_PERCENT, False)),
        battery=bool(screen.get(CONF_BATTERY, False)),
    )
