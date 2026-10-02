"""Tests for screen defaults, form fields and validation."""

from __future__ import annotations

import pytest

from custom_components.lcd_ticker import presets
from custom_components.lcd_ticker.presets import (
    ADVANCED_FIELDS,
    BASE_SCREEN,
    new_screen_data,
    validate_look,
    validate_sources,
)
from custom_components.lcd_ticker.protocol import Face, Unit
from custom_components.lcd_ticker.render import SourceValue, render

UNITS = {
    "sensor.power": "W",
    "sensor.export": "kW",
    "sensor.temp": "°C",
    "sensor.price": "EUR/kWh",
    "sensor.bad": "m",
}


def unit_of(entity_id: str) -> str | None:
    return UNITS.get(entity_id)


def test_new_screen_is_base_plus_position():
    data = new_screen_data(3)
    assert data == BASE_SCREEN | {"position": 3}
    assert data["preset"] == "custom"
    assert data["small_source"] == "none"


def test_new_screen_is_a_copy():
    data = new_screen_data(1)
    data["seconds"] = 99
    assert BASE_SCREEN["seconds"] == 0


def test_render_defaults_match_base_screen():
    frame = render(
        BASE_SCREEN | {"big_entity": "sensor.x"},
        {"sensor.x": SourceValue("1", None)},
        65535,
    )
    assert frame is not None
    assert frame.big == 1.0
    assert frame.small == 0
    assert frame.face == Face.NONE
    assert frame.unit == Unit.NONE


def test_advanced_fields_are_stored_keys():
    assert set(ADVANCED_FIELDS) <= BASE_SCREEN.keys()
    assert len(set(ADVANCED_FIELDS)) == len(ADVANCED_FIELDS)
    for simple in ("big_entity", "small_entity", "unit", "percent", "preset"):
        assert simple not in ADVANCED_FIELDS


def test_validate_self_consumption_valid():
    data = new_screen_data(1) | {
        "big_entity": "sensor.power",
        "small_source": "self_consumption",
        "export_entity": "sensor.export",
    }
    assert validate_sources(data, unit_of) == {}


def test_validate_unit_unknown_and_not_supported():
    data = new_screen_data(1) | {
        "big_entity": "sensor.nope",
        "big_convert": "celsius",
    }
    assert validate_sources(data, unit_of) == {"big_entity": "unit_unknown"}
    data["big_entity"] = "sensor.bad"
    assert validate_sources(data, unit_of) == {"big_entity": "unit_not_supported"}
    data["big_entity"] = "sensor.temp"
    assert validate_sources(data, unit_of) == {}


def test_validate_convert_none_skips_unit_check():
    data = new_screen_data(1) | {"big_entity": "sensor.nope"}
    assert validate_sources(data, unit_of) == {}


def test_validate_small_entity_checks():
    data = new_screen_data(1) | {
        "big_entity": "sensor.temp",
        "small_source": "entity",
    }
    assert validate_sources(data, unit_of) == {"small_entity": "small_entity_required"}
    data |= {"small_entity": "sensor.bad", "small_convert": "celsius"}
    assert validate_sources(data, unit_of) == {"small_entity": "unit_not_supported"}
    data["small_entity"] = "sensor.nope"
    assert validate_sources(data, unit_of) == {"small_entity": "unit_unknown"}


def test_validate_small_convert_ignored_when_source_not_entity():
    data = new_screen_data(1) | {
        "big_entity": "sensor.temp",
        "small_source": "none",
        "small_entity": "sensor.bad",
        "small_convert": "celsius",
    }
    assert validate_sources(data, unit_of) == {}


def test_validate_self_consumption():
    base = new_screen_data(1) | {"small_source": "self_consumption"}
    assert validate_sources(base, unit_of) == {"base": "production_required"}
    data = base | {"big_entity": "sensor.power"}
    assert validate_sources(data, unit_of) == {"base": "solar_small_required"}
    data["export_entity"] = "sensor.export"
    assert validate_sources(data, unit_of) == {}
    # production_entity wins over big_entity
    data["production_entity"] = "sensor.bad"
    assert validate_sources(data, unit_of) == {
        "production_entity": "unit_not_supported"
    }
    data["production_entity"] = "sensor.nope"
    assert validate_sources(data, unit_of) == {"production_entity": "unit_unknown"}
    data["production_entity"] = None
    data["export_entity"] = "sensor.bad"
    assert validate_sources(data, unit_of) == {"export_entity": "unit_not_supported"}


def test_validate_production_equal_to_big_reports_on_big_entity():
    data = new_screen_data(1) | {
        "big_entity": "sensor.bad",
        "production_entity": "sensor.bad",
        "small_source": "self_consumption",
        "export_entity": "sensor.export",
    }
    assert validate_sources(data, unit_of) == {"big_entity": "unit_not_supported"}


def test_validate_ignores_the_stored_preset():
    data = new_screen_data(1) | {
        "preset": "solar",
        "big_entity": "sensor.power",
        "small_source": "none",
    }
    assert validate_sources(data, unit_of) == {}


def test_validate_look_thresholds():
    ok = new_screen_data(1) | {"face_mode": "scale"}
    assert validate_look(ok) == {}
    bad = ok | {"face_t2": 10.0, "face_t1": 30.0}
    assert validate_look(bad) == {"base": "thresholds_order"}
    equal = ok | {"face_t1": 20.0, "face_t2": 20.0}
    assert validate_look(equal) == {}
    unsorted_but_not_scale = bad | {"face_mode": "none"}
    assert validate_look(unsorted_but_not_scale) == {}


def test_validate_look_seconds():
    ok = new_screen_data(1)
    assert validate_look(ok | {"seconds": 0}) == {}
    assert validate_look(ok | {"seconds": 30}) == {}
    assert validate_look(ok | {"seconds": 10}) == {"seconds": "seconds_too_short"}


def test_module_exports_base_screen():
    assert presets.BASE_SCREEN["preset"] == "custom"


def test_show_when_and_takeover_defaults_and_fields():
    assert BASE_SCREEN["show_when_entity"] is None
    assert BASE_SCREEN["takeover"] is False
    assert {"show_when_entity", "takeover", "enabled"} <= set(ADVANCED_FIELDS)
    assert new_screen_data(2)["show_when_entity"] is None


def test_validate_look_takeover_needs_entity():
    ok = new_screen_data(1)
    assert validate_look(ok | {"takeover": True}) == {"base": "takeover_needs_entity"}
    assert validate_look(ok | {"takeover": True, "show_when_entity": "x.y"}) == {}
    assert validate_look(ok | {"show_when_entity": "x.y"}) == {}


def test_user_multiplier_reaches_render():
    data = new_screen_data(1) | {
        "big_entity": "sensor.price",
        "big_convert": "cents_per_kwh",
        "big_multiplier": 2.0,
        "big_offset": 1.0,
    }
    frame = render(data, {"sensor.price": SourceValue("0.1", "EUR/kWh")}, 65535)
    assert frame.big == pytest.approx(21.0)
