"""Screen defaults, form fields and validation. Pure: no I/O."""

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
    CONF_SHOW_WHEN,
    CONF_SMALL_CONVERT,
    CONF_SMALL_ENTITY,
    CONF_SMALL_FIXED,
    CONF_SMALL_MULTIPLIER,
    CONF_SMALL_OFFSET,
    CONF_SMALL_SOURCE,
    CONF_TAKEOVER,
    CONF_UNIT,
    CONF_VAT_PERCENT,
    CONVERT_KW,
    CONVERT_NONE,
    DECIMALS_AUTO,
    DIRECTION_HIGHER,
    FACE_MODE_NONE,
    FACE_MODE_SCALE,
    FACE_SOURCE_BIG,
    MIN_SECONDS,
    PRESET_CUSTOM,
    SMALL_ENTITY,
    SMALL_NONE,
    SMALL_SELF_CONSUMPTION,
)
from .render import can_convert

BASE_SCREEN: dict[str, Any] = {
    CONF_PRESET: PRESET_CUSTOM,
    CONF_POSITION: 1,
    CONF_SCREEN_ENABLED: True,
    CONF_SHOW_WHEN: None,
    CONF_TAKEOVER: False,
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

# Fields in the Advanced section of the check step. The simple form holds the
# name, big_entity, unit, small_entity and percent.
ADVANCED_FIELDS: tuple[str, ...] = (
    CONF_BIG_MULTIPLIER,
    CONF_BIG_OFFSET,
    CONF_BIG_DECIMALS,
    CONF_BIG_CONVERT,
    CONF_VAT_PERCENT,
    CONF_SMALL_MULTIPLIER,
    CONF_SMALL_OFFSET,
    CONF_SMALL_CONVERT,
    CONF_SMALL_SOURCE,
    CONF_SMALL_FIXED,
    CONF_EXPORT_ENTITY,
    CONF_FACE_MODE,
    CONF_FACE_FIXED,
    CONF_FACE_SOURCE,
    CONF_FACE_DIRECTION,
    CONF_FACE_T1,
    CONF_FACE_T2,
    CONF_FACE_T3,
    CONF_FACE_T4,
    CONF_BATTERY,
    CONF_SHOW_WHEN,
    CONF_TAKEOVER,
    CONF_POSITION,
    CONF_SCREEN_SECONDS,
    CONF_JUMP_DELTA,
    CONF_SCREEN_ENABLED,
)


def new_screen_data(position: int) -> dict[str, Any]:
    """Return a fresh screen: BASE_SCREEN at the given position."""
    return {**BASE_SCREEN, CONF_POSITION: position}


UnitDetails = dict[str, tuple[str | None, str]]


def _check_unit(
    errors: dict[str, str],
    field: str,
    entity_id: str,
    target: str,
    unit_of: Callable[[str], str | None],
    details: UnitDetails,
) -> None:
    unit = unit_of(entity_id)
    if unit is None:
        errors[field] = "unit_unknown"
    elif not can_convert(unit, target):
        errors[field] = "unit_not_supported"
    else:
        return
    details.setdefault(field, (unit, target))


def validate_sources(
    data: Mapping[str, Any],
    unit_of: Callable[[str], str | None],
    details: UnitDetails | None = None,
) -> dict[str, str]:
    """Return {field: error}, or {"base": error}; empty when valid.

    `details` (if given) receives {field: (unit found, conversion target)} for unit
    errors, so the form can say exactly what is wrong.
    """
    errors: dict[str, str] = {}
    details = {} if details is None else details
    small_source = data.get(CONF_SMALL_SOURCE, SMALL_NONE)

    pairs = [(CONF_BIG_ENTITY, CONF_BIG_CONVERT)]
    if small_source == SMALL_ENTITY:
        pairs.append((CONF_SMALL_ENTITY, CONF_SMALL_CONVERT))
    for entity_key, convert_key in pairs:
        entity_id = data.get(entity_key)
        convert = data.get(convert_key, CONVERT_NONE)
        if entity_id and convert != CONVERT_NONE:
            _check_unit(errors, entity_key, entity_id, convert, unit_of, details)

    if small_source == SMALL_ENTITY and not data.get(CONF_SMALL_ENTITY):
        errors[CONF_SMALL_ENTITY] = "small_entity_required"

    if small_source == SMALL_SELF_CONSUMPTION:
        # Production is big_entity unless a stored screen names another sensor.
        production_key = (
            CONF_PRODUCTION_ENTITY
            if data.get(CONF_PRODUCTION_ENTITY) not in (None, data.get(CONF_BIG_ENTITY))
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
                _check_unit(errors, key, entity_id, CONVERT_KW, unit_of, details)

    return errors


def validate_look(data: Mapping[str, Any]) -> dict[str, str]:
    """Seconds are 0 or at least MIN_SECONDS; scale thresholds ascend."""
    errors: dict[str, str] = {}
    if data.get(CONF_TAKEOVER) and not data.get(CONF_SHOW_WHEN):
        errors["base"] = "takeover_needs_entity"
    if 0 < data.get(CONF_SCREEN_SECONDS, 0) < MIN_SECONDS:
        errors[CONF_SCREEN_SECONDS] = "seconds_too_short"
    if data.get(CONF_FACE_MODE) == FACE_MODE_SCALE:
        t1, t2, t3, t4 = (
            data[key]
            for key in (CONF_FACE_T1, CONF_FACE_T2, CONF_FACE_T3, CONF_FACE_T4)
        )
        if not t1 <= t2 <= t3 <= t4:
            errors["base"] = "thresholds_order"
    return errors
