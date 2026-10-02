"""Preset defaults, form fields and validation for screens. Pure: no I/O."""

from __future__ import annotations

from collections.abc import Callable, Mapping
from typing import Any

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
    CONF_FACE_T1,
    CONF_FACE_T2,
    CONF_FACE_T3,
    CONF_FACE_T4,
    CONF_JUMP_DELTA,
    CONF_PERCENT,
    CONF_POSITION,
    CONF_PRESET,
    CONF_PRODUCTION_ENTITY,
    CONF_SCREEN_ENABLED,
    CONF_SCREEN_SECONDS,
    CONF_SMALL_CONVERT,
    CONF_SMALL_ENTITY,
    CONF_SMALL_FIXED,
    CONF_SMALL_MULTIPLIER,
    CONF_SMALL_OFFSET,
    CONF_SMALL_SOURCE,
    CONF_TITLE,
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
    FACE_MODE_NONE,
    FACE_MODE_SCALE,
    FACE_SOURCE_BIG,
    FACE_SOURCE_SMALL,
    PRESET_CLIMATE,
    PRESET_CUSTOM,
    PRESET_PRICE,
    PRESET_SINGLE,
    PRESET_SOLAR,
    SMALL_ENTITY,
    SMALL_FIXED,
    SMALL_NONE,
    SMALL_SELF_CONSUMPTION,
)
from .render import can_convert

BASE_SCREEN: dict[str, Any] = {
    CONF_PRESET: PRESET_CUSTOM,
    CONF_POSITION: 1,
    CONF_SCREEN_ENABLED: True,
    CONF_SCREEN_SECONDS: 0,
    CONF_JUMP_DELTA: 0.0,
    CONF_BIG_ENTITY: None,
    CONF_BIG_CONVERT: CONVERT_NONE,
    CONF_BIG_MULTIPLIER: 1.0,
    CONF_BIG_OFFSET: 0.0,
    CONF_BIG_DECIMALS: DECIMALS_AUTO,
    CONF_VAT_PERCENT: 0.0,
    CONF_SMALL_SOURCE: SMALL_NONE,
    CONF_SMALL_ENTITY: None,
    CONF_SMALL_CONVERT: CONVERT_NONE,
    CONF_SMALL_MULTIPLIER: 1.0,
    CONF_SMALL_OFFSET: 0.0,
    CONF_SMALL_FIXED: 0,
    CONF_PRODUCTION_ENTITY: None,
    CONF_EXPORT_ENTITY: None,
    CONF_UNIT: "none",
    CONF_PERCENT: False,
    CONF_BATTERY: False,
    CONF_FACE_MODE: FACE_MODE_NONE,
    CONF_FACE_FIXED: "happy_bracket",
    CONF_FACE_SOURCE: FACE_SOURCE_BIG,
    CONF_FACE_DIRECTION: DIRECTION_HIGHER,
    CONF_FACE_T1: 20.0,
    CONF_FACE_T2: 40.0,
    CONF_FACE_T3: 60.0,
    CONF_FACE_T4: 80.0,
}

_PRESET_OVERRIDES: dict[str, dict[str, Any]] = {
    PRESET_SOLAR: {
        CONF_BIG_CONVERT: CONVERT_KW,
        CONF_SMALL_SOURCE: SMALL_SELF_CONSUMPTION,
        CONF_PERCENT: True,
        CONF_FACE_MODE: FACE_MODE_SCALE,
        CONF_FACE_SOURCE: FACE_SOURCE_SMALL,
        CONF_FACE_DIRECTION: DIRECTION_HIGHER,
        CONF_FACE_T1: 20.0,
        CONF_FACE_T2: 40.0,
        CONF_FACE_T3: 60.0,
        CONF_FACE_T4: 80.0,
    },
    PRESET_CLIMATE: {
        CONF_BIG_CONVERT: CONVERT_CELSIUS,
        CONF_UNIT: "deg_c",
        CONF_SMALL_SOURCE: SMALL_ENTITY,
        CONF_PERCENT: True,
    },
    PRESET_PRICE: {
        CONF_BIG_CONVERT: CONVERT_CENTS_KWH,
        CONF_SMALL_CONVERT: CONVERT_CENTS_KWH,
        CONF_FACE_MODE: FACE_MODE_SCALE,
        CONF_FACE_SOURCE: FACE_SOURCE_BIG,
        CONF_FACE_DIRECTION: DIRECTION_LOWER,
        CONF_FACE_T1: 5.0,
        CONF_FACE_T2: 10.0,
        CONF_FACE_T3: 15.0,
        CONF_FACE_T4: 20.0,
    },
    PRESET_SINGLE: {CONF_SMALL_SOURCE: SMALL_FIXED},
    PRESET_CUSTOM: {},
}

# preset -> fields shown in the "sources" step
SOURCE_FIELDS: dict[str, tuple[str, ...]] = {
    PRESET_SOLAR: (CONF_BIG_ENTITY, CONF_EXPORT_ENTITY, CONF_SMALL_ENTITY),
    PRESET_CLIMATE: (CONF_BIG_ENTITY, CONF_BIG_CONVERT, CONF_SMALL_ENTITY),
    PRESET_PRICE: (CONF_BIG_ENTITY, CONF_VAT_PERCENT, CONF_SMALL_ENTITY),
    PRESET_SINGLE: (
        CONF_BIG_ENTITY,
        CONF_BIG_CONVERT,
        CONF_BIG_MULTIPLIER,
        CONF_BIG_OFFSET,
        CONF_BIG_DECIMALS,
    ),
    PRESET_CUSTOM: (
        CONF_BIG_ENTITY,
        CONF_BIG_CONVERT,
        CONF_BIG_MULTIPLIER,
        CONF_BIG_OFFSET,
        CONF_BIG_DECIMALS,
        CONF_VAT_PERCENT,
        CONF_SMALL_SOURCE,
        CONF_SMALL_ENTITY,
        CONF_SMALL_CONVERT,
        CONF_SMALL_MULTIPLIER,
        CONF_SMALL_OFFSET,
        CONF_SMALL_FIXED,
        CONF_PRODUCTION_ENTITY,
        CONF_EXPORT_ENTITY,
    ),
}

# Fields shown in the "look" step (all presets)
LOOK_FIELDS: tuple[str, ...] = (
    CONF_TITLE,
    CONF_UNIT,
    CONF_PERCENT,
    CONF_BATTERY,
    CONF_FACE_MODE,
    CONF_FACE_FIXED,
    CONF_FACE_SOURCE,
    CONF_FACE_DIRECTION,
    CONF_FACE_T1,
    CONF_FACE_T2,
    CONF_FACE_T3,
    CONF_FACE_T4,
    CONF_POSITION,
    CONF_SCREEN_SECONDS,
    CONF_JUMP_DELTA,
    CONF_SCREEN_ENABLED,
)

_ENTITY_FIELDS = (
    CONF_BIG_ENTITY,
    CONF_SMALL_ENTITY,
    CONF_PRODUCTION_ENTITY,
    CONF_EXPORT_ENTITY,
)

_TITLES = {
    PRESET_SOLAR: "Solar",
    PRESET_CLIMATE: "Climate",
    PRESET_PRICE: "Price",
    PRESET_SINGLE: "Value",
    PRESET_CUSTOM: "Custom",
}


def new_screen_data(preset: str, position: int) -> dict[str, Any]:
    """Return a fresh screen: BASE_SCREEN plus the preset's overrides."""
    data = dict(BASE_SCREEN)
    data.update(_PRESET_OVERRIDES[preset])
    if preset == PRESET_SINGLE:
        data[CONF_SMALL_FIXED] = position
    data[CONF_PRESET] = preset
    data[CONF_POSITION] = position
    return data


def apply_sources(
    preset: str, data: Mapping[str, Any], user_input: Mapping[str, Any]
) -> dict[str, Any]:
    """Merge the sources step's input and derive the preset's hidden fields."""
    result = {**data, **user_input}
    for key in SOURCE_FIELDS[preset]:
        if key in _ENTITY_FIELDS and key not in user_input:
            result[key] = None

    if preset == PRESET_SOLAR:
        result[CONF_PRODUCTION_ENTITY] = result.get(CONF_BIG_ENTITY)
        if result.get(CONF_SMALL_ENTITY):
            result[CONF_SMALL_SOURCE] = SMALL_ENTITY
            result[CONF_SMALL_CONVERT] = CONVERT_NONE
        elif result.get(CONF_EXPORT_ENTITY):
            result[CONF_SMALL_SOURCE] = SMALL_SELF_CONSUMPTION
    elif preset == PRESET_CLIMATE:
        has_small = bool(result.get(CONF_SMALL_ENTITY))
        result[CONF_SMALL_SOURCE] = SMALL_ENTITY if has_small else SMALL_NONE
        result[CONF_PERCENT] = has_small
        convert = result.get(CONF_BIG_CONVERT)
        if convert == CONVERT_FAHRENHEIT:
            result[CONF_UNIT] = "deg_f"
        elif convert == CONVERT_CELSIUS:
            result[CONF_UNIT] = "deg_c"
        else:
            result[CONF_UNIT] = "none"
    elif preset == PRESET_PRICE:
        has_small = bool(result.get(CONF_SMALL_ENTITY))
        result[CONF_SMALL_SOURCE] = SMALL_ENTITY if has_small else SMALL_NONE
    return result


def _check_unit(
    errors: dict[str, str],
    field: str,
    entity_id: str,
    target: str,
    unit_of: Callable[[str], str | None],
) -> None:
    unit = unit_of(entity_id)
    if unit is None:
        errors[field] = "unit_unknown"
    elif not can_convert(unit, target):
        errors[field] = "unit_not_supported"


def validate_sources(
    data: Mapping[str, Any], unit_of: Callable[[str], str | None]
) -> dict[str, str]:
    """Return {field: error}, or {"base": error}; empty when valid."""
    errors: dict[str, str] = {}
    small_source = data.get(CONF_SMALL_SOURCE, SMALL_NONE)

    pairs = [(CONF_BIG_ENTITY, CONF_BIG_CONVERT)]
    if small_source == SMALL_ENTITY:
        pairs.append((CONF_SMALL_ENTITY, CONF_SMALL_CONVERT))
    for entity_key, convert_key in pairs:
        entity_id = data.get(entity_key)
        convert = data.get(convert_key, CONVERT_NONE)
        if entity_id and convert != CONVERT_NONE:
            _check_unit(errors, entity_key, entity_id, convert, unit_of)

    if small_source == SMALL_ENTITY and not data.get(CONF_SMALL_ENTITY):
        errors[CONF_SMALL_ENTITY] = "small_entity_required"

    if small_source == SMALL_SELF_CONSUMPTION:
        production_key = (
            CONF_PRODUCTION_ENTITY
            if data.get(CONF_PRODUCTION_ENTITY)
            else CONF_BIG_ENTITY
        )
        production = data.get(production_key)
        export = data.get(CONF_EXPORT_ENTITY)
        if not production:
            errors["base"] = "production_required"
        elif not export:
            errors["base"] = "solar_small_required"
        for key, entity_id in (
            (production_key, production),
            (CONF_EXPORT_ENTITY, export),
        ):
            if entity_id:
                _check_unit(errors, key, entity_id, CONVERT_KW, unit_of)

    if (
        data.get(CONF_PRESET) == PRESET_SOLAR
        and not data.get(CONF_EXPORT_ENTITY)
        and not data.get(CONF_SMALL_ENTITY)
    ):
        errors["base"] = "solar_small_required"
    return errors


def validate_look(data: Mapping[str, Any]) -> dict[str, str]:
    """Scale thresholds must be in ascending order."""
    if data.get(CONF_FACE_MODE) != FACE_MODE_SCALE:
        return {}
    t1, t2, t3, t4 = (
        data[key] for key in (CONF_FACE_T1, CONF_FACE_T2, CONF_FACE_T3, CONF_FACE_T4)
    )
    if t1 <= t2 <= t3 <= t4:
        return {}
    return {"base": "thresholds_order"}


def default_title(preset: str, entity_name: str | None) -> str:
    """Title suggested for a new screen."""
    title = _TITLES[preset]
    if entity_name:
        return f"{title} · {entity_name}"
    return title
