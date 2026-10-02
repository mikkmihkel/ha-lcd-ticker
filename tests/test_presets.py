"""Tests for preset defaults, form fields and validation."""

from __future__ import annotations

import pytest

from custom_components.lcd_ticker import presets
from custom_components.lcd_ticker.const import PRESETS_ORDER
from custom_components.lcd_ticker.presets import (
    BASE_SCREEN,
    LOOK_FIELDS,
    SOURCE_FIELDS,
    apply_sources,
    default_title,
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


@pytest.mark.parametrize("preset", PRESETS_ORDER)
def test_new_screen_keys_match_base(preset):
    data = new_screen_data(preset, 3)
    assert data.keys() == BASE_SCREEN.keys()
    assert data["preset"] == preset
    assert data["position"] == 3


def test_new_screen_is_a_copy():
    data = new_screen_data("custom", 1)
    data["seconds"] = 99
    assert BASE_SCREEN["seconds"] == 0


def test_solar_overrides():
    data = new_screen_data("solar", 2)
    assert data["big_convert"] == "kw"
    assert data["small_source"] == "self_consumption"
    assert data["percent"] is True
    assert data["face_mode"] == "scale"
    assert data["face_source"] == "small"
    assert data["face_direction"] == "higher_better"
    assert [data[f"face_t{i}"] for i in range(1, 5)] == [20.0, 40.0, 60.0, 80.0]


def test_climate_and_price_overrides():
    climate = new_screen_data("climate", 1)
    assert climate["big_convert"] == "celsius"
    assert climate["unit"] == "deg_c"
    assert climate["small_source"] == "entity"
    assert climate["percent"] is True
    price = new_screen_data("price", 1)
    assert price["big_convert"] == "cents_per_kwh"
    assert price["small_convert"] == "cents_per_kwh"
    assert price["face_direction"] == "lower_better"
    assert [price[f"face_t{i}"] for i in range(1, 5)] == [5.0, 10.0, 15.0, 20.0]


def test_single_small_fixed_is_position():
    data = new_screen_data("single", 4)
    assert data["small_source"] == "fixed"
    assert data["small_fixed"] == 4


def test_custom_is_base():
    data = new_screen_data("custom", 1)
    assert data == BASE_SCREEN | {"preset": "custom", "position": 1}


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


def test_field_sets_are_consistent():
    assert list(SOURCE_FIELDS) == PRESETS_ORDER
    for fields in SOURCE_FIELDS.values():
        assert set(fields) <= BASE_SCREEN.keys()
    assert set(LOOK_FIELDS) - {"title"} <= BASE_SCREEN.keys()
    assert "title" in LOOK_FIELDS


def test_apply_sources_solar_with_small_entity():
    data = new_screen_data("solar", 1)
    out = apply_sources(
        "solar",
        data,
        {"big_entity": "sensor.power", "small_entity": "sensor.s"},
    )
    assert out["production_entity"] == "sensor.power"
    assert out["small_source"] == "entity"
    assert out["small_convert"] == "none"
    assert out["export_entity"] is None


def test_apply_sources_solar_with_export():
    data = new_screen_data("solar", 1)
    out = apply_sources(
        "solar",
        data,
        {"big_entity": "sensor.power", "export_entity": "sensor.export"},
    )
    assert out["small_source"] == "self_consumption"
    assert out["small_entity"] is None


def test_apply_sources_solar_neither_leaves_source():
    data = new_screen_data("solar", 1)
    out = apply_sources("solar", data, {"big_entity": "sensor.power"})
    assert out["small_source"] == "self_consumption"


def test_apply_sources_cleared_picker_is_none():
    data = new_screen_data("solar", 1) | {"export_entity": "sensor.export"}
    out = apply_sources("solar", data, {"big_entity": "sensor.power"})
    assert out["export_entity"] is None
    # non-entity fields are kept
    assert out["big_convert"] == "kw"


def test_apply_sources_climate():
    data = new_screen_data("climate", 1)
    out = apply_sources(
        "climate",
        data,
        {"big_entity": "sensor.temp", "big_convert": "fahrenheit"},
    )
    assert out["small_source"] == "none"
    assert out["percent"] is False
    assert out["unit"] == "deg_f"
    out = apply_sources(
        "climate",
        data,
        {
            "big_entity": "sensor.temp",
            "big_convert": "celsius",
            "small_entity": "sensor.h",
        },
    )
    assert out["small_source"] == "entity"
    assert out["percent"] is True
    assert out["unit"] == "deg_c"
    out = apply_sources(
        "climate", data, {"big_entity": "sensor.temp", "big_convert": "none"}
    )
    assert out["unit"] == "none"


def test_apply_sources_price():
    data = new_screen_data("price", 1)
    out = apply_sources("price", data, {"big_entity": "sensor.price"})
    assert out["small_source"] == "none"
    out = apply_sources(
        "price", data, {"big_entity": "sensor.price", "small_entity": "sensor.p2"}
    )
    assert out["small_source"] == "entity"


@pytest.mark.parametrize("preset", ["single", "custom"])
def test_apply_sources_nothing_derived(preset):
    data = new_screen_data(preset, 1)
    out = apply_sources(preset, data, {"big_entity": "sensor.power"})
    assert out["small_source"] == data["small_source"]
    assert out["unit"] == data["unit"]
    assert out["big_entity"] == "sensor.power"


def test_apply_sources_does_not_mutate_input():
    data = new_screen_data("solar", 1)
    before = dict(data)
    apply_sources("solar", data, {"big_entity": "sensor.power"})
    assert data == before


def test_validate_solar_valid():
    data = apply_sources(
        "solar",
        new_screen_data("solar", 1),
        {"big_entity": "sensor.power", "export_entity": "sensor.export"},
    )
    assert validate_sources(data, unit_of) == {}


def test_validate_unit_unknown_and_not_supported():
    data = new_screen_data("custom", 1) | {
        "big_entity": "sensor.nope",
        "big_convert": "celsius",
    }
    assert validate_sources(data, unit_of) == {"big_entity": "unit_unknown"}
    data["big_entity"] = "sensor.bad"
    assert validate_sources(data, unit_of) == {"big_entity": "unit_not_supported"}
    data["big_entity"] = "sensor.temp"
    assert validate_sources(data, unit_of) == {}


def test_validate_convert_none_skips_unit_check():
    data = new_screen_data("custom", 1) | {"big_entity": "sensor.nope"}
    assert validate_sources(data, unit_of) == {}


def test_validate_small_entity_checks():
    data = new_screen_data("custom", 1) | {
        "big_entity": "sensor.temp",
        "small_source": "entity",
    }
    assert validate_sources(data, unit_of) == {"small_entity": "small_entity_required"}
    data |= {"small_entity": "sensor.bad", "small_convert": "celsius"}
    assert validate_sources(data, unit_of) == {"small_entity": "unit_not_supported"}
    data["small_entity"] = "sensor.nope"
    assert validate_sources(data, unit_of) == {"small_entity": "unit_unknown"}


def test_validate_small_convert_ignored_when_source_not_entity():
    data = new_screen_data("custom", 1) | {
        "big_entity": "sensor.temp",
        "small_source": "none",
        "small_entity": "sensor.bad",
        "small_convert": "celsius",
    }
    assert validate_sources(data, unit_of) == {}


def test_validate_self_consumption():
    base = new_screen_data("custom", 1) | {"small_source": "self_consumption"}
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


def test_validate_solar_preset_needs_small():
    data = new_screen_data("solar", 1) | {
        "big_entity": "sensor.power",
        "production_entity": "sensor.power",
    }
    assert validate_sources(data, unit_of) == {"base": "solar_small_required"}


def test_validate_look_thresholds():
    ok = new_screen_data("solar", 1)
    assert validate_look(ok) == {}
    bad = ok | {"face_t2": 10.0, "face_t1": 30.0}
    assert validate_look(bad) == {"base": "thresholds_order"}
    equal = ok | {"face_t1": 20.0, "face_t2": 20.0}
    assert validate_look(equal) == {}
    unsorted_but_not_scale = bad | {"face_mode": "none"}
    assert validate_look(unsorted_but_not_scale) == {}


def test_default_title():
    assert default_title("solar", None) == "Solar"
    assert default_title("single", None) == "Value"
    assert default_title("price", "Nord Pool") == "Price · Nord Pool"
    assert default_title("custom", "") == "Custom"


def test_module_exports_base_screen():
    assert presets.BASE_SCREEN["preset"] == "custom"
