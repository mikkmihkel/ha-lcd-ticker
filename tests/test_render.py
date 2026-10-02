"""Tests for render.py (pure)."""

import pytest

from custom_components.lcd_ticker.const import (
    CONVERT_CELSIUS,
    CONVERT_CENTS_KWH,
    CONVERT_FAHRENHEIT,
    CONVERT_KW,
    CONVERT_NONE,
    DIRECTION_HIGHER,
    DIRECTION_LOWER,
    DIRECTION_MIDDLE,
)
from custom_components.lcd_ticker.protocol import Face, Unit
from custom_components.lcd_ticker.render import (
    SourceValue,
    can_convert,
    convert,
    describe_screen,
    face_for,
    format_big,
    markers,
    parse_number,
    price_factor,
    render,
    screen_entity_ids,
)

SOLAR = {
    "preset": "solar",
    "big_entity": "sensor.pv",
    "big_convert": CONVERT_KW,
    "small_source": "self_consumption",
    "export_entity": "sensor.export",
    "percent": True,
    "face_mode": "scale",
    "face_source": "small",
    "face_direction": DIRECTION_HIGHER,
    "face_t1": 20,
    "face_t2": 40,
    "face_t3": 60,
    "face_t4": 80,
}


@pytest.mark.parametrize(
    ("state", "expected"),
    [
        ("1.5", 1.5),
        ("-3", -3.0),
        ("unknown", None),
        ("unavailable", None),
        ("", None),
        (None, None),
        ("abc", None),
        ("nan", None),
        ("inf", None),
    ],
)
def test_parse_number(state, expected):
    assert parse_number(state) == expected


@pytest.mark.parametrize(
    ("unit", "factor"),
    [
        ("EUR/kWh", 100),
        ("€/kWh", 100),
        ("EUR/MWh", 0.1),
        ("c/kWh", 1),
        ("ct/kWh", 1),
        ("SEK/kWh", 100),
        ("öre/kWh", 1),
        ("EUR/Wh", 100000),
        (" EUR / kWh ", 100),
        ("kWh", None),
        ("EUR/kw", None),
        (None, None),
        ("/kWh", None),
    ],
)
def test_price_factor(unit, factor):
    result = price_factor(unit)
    assert result == (pytest.approx(factor) if factor is not None else None)


def test_can_convert_and_convert():
    assert can_convert("W", CONVERT_KW) and convert(
        4600, "W", CONVERT_KW
    ) == pytest.approx(4.6)
    assert convert(5.7, "kW", CONVERT_KW) == pytest.approx(5.7)
    assert convert(212, "°F", CONVERT_CELSIUS) == pytest.approx(100)
    assert convert(100, "°C", CONVERT_FAHRENHEIT) == pytest.approx(212)
    assert convert(0.1234, "EUR/kWh", CONVERT_CENTS_KWH) == pytest.approx(12.34)
    assert convert(7, None, CONVERT_NONE) == 7
    assert not can_convert("°C", CONVERT_KW) and convert(20, "°C", CONVERT_KW) is None
    assert not can_convert(None, CONVERT_CELSIUS)
    assert not can_convert("W", "bogus")


@pytest.mark.parametrize(
    ("value", "face"),
    [
        (85, Face.HAPPY_BRACKET),
        (80, Face.HAPPY_BRACKET),
        (65, Face.HAPPY),
        (45, Face.HAPPY_SAD),
        (25, Face.SAD),
        (5, Face.SAD_BRACKET),
    ],
)
def test_face_scale_higher_is_better(value, face):
    assert face_for(value, DIRECTION_HIGHER, [20, 40, 60, 80]) is face


@pytest.mark.parametrize(
    ("value", "face"),
    [
        (4, Face.HAPPY_BRACKET),
        (5, Face.HAPPY_BRACKET),
        (8, Face.HAPPY),
        (12, Face.HAPPY_SAD),
        (18, Face.SAD),
        (25, Face.SAD_BRACKET),
    ],
)
def test_face_scale_lower_is_better(value, face):
    assert face_for(value, DIRECTION_LOWER, [5, 10, 15, 20]) is face


def test_face_thresholds_are_sorted_first():
    assert face_for(85, DIRECTION_HIGHER, [80, 20, 60, 40]) is Face.HAPPY_BRACKET


def test_render_solar_matches_upstream_example():
    values = {
        "sensor.pv": SourceValue("5700", "W"),
        "sensor.export": SourceValue("114", "W"),
    }
    frame = render(SOLAR, values, validity=65535)
    assert frame is not None
    assert frame.big == pytest.approx(5.7)
    assert frame.small == 98
    assert frame.percent is True
    assert frame.face is Face.HAPPY_BRACKET
    assert frame.validity == 65535


def test_render_self_consumption_is_zero_below_50_w():
    values = {
        "sensor.pv": SourceValue("40", "W"),
        "sensor.export": SourceValue("0", "W"),
    }
    assert render(SOLAR, values, 65535).small == 0


def test_render_self_consumption_clamped_when_export_exceeds_production():
    values = {
        "sensor.pv": SourceValue("1000", "W"),
        "sensor.export": SourceValue("1500", "W"),
    }
    assert render(SOLAR, values, 65535).small == 0


@pytest.mark.parametrize("bad", ["unavailable", "unknown", "", "abc", "nan"])
def test_render_returns_none_when_a_required_source_is_bad(bad):
    values = {
        "sensor.pv": SourceValue(bad, "W"),
        "sensor.export": SourceValue("0", "W"),
    }
    assert render(SOLAR, values, 65535) is None


def test_render_returns_none_when_entity_missing_from_values():
    assert render(SOLAR, {}, 65535) is None


def test_render_price_with_vat_and_scale_face():
    screen = {
        "big_entity": "sensor.np",
        "big_convert": CONVERT_CENTS_KWH,
        "vat_percent": 24,
        "small_source": "none",
        "face_mode": "scale",
        "face_source": "big",
        "face_direction": DIRECTION_LOWER,
        "face_t1": 5,
        "face_t2": 10,
        "face_t3": 15,
        "face_t4": 20,
    }
    frame = render(screen, {"sensor.np": SourceValue("0.1", "EUR/kWh")}, 65535)
    assert frame.big == pytest.approx(12.4)
    assert frame.small == 0
    assert frame.face is Face.HAPPY_SAD


def test_render_climate_with_unit_and_humidity():
    screen = {
        "big_entity": "sensor.t",
        "big_convert": CONVERT_CELSIUS,
        "unit": "deg_c",
        "small_source": "entity",
        "small_entity": "sensor.h",
        "percent": True,
    }
    values = {
        "sensor.t": SourceValue("71.6", "°F"),
        "sensor.h": SourceValue("44.6", "%"),
    }
    frame = render(screen, values, 65535)
    assert frame.big == pytest.approx(22.0)
    assert frame.small == 45
    assert frame.unit is Unit.DEG_C


def test_render_multiplier_offset_and_zero_decimals():
    screen = {
        "big_entity": "sensor.x",
        "big_multiplier": 2,
        "big_offset": 0.3,
        "big_decimals": "0",
        "small_source": "fixed",
        "small_fixed": 3,
    }
    frame = render(screen, {"sensor.x": SourceValue("10.4", None)}, 900)
    assert frame.big == 21
    assert frame.small == 3


def test_render_fixed_face_and_defaults_for_missing_keys():
    frame = render(
        {"big_entity": "sensor.x", "face_mode": "fixed", "face_fixed": "bracket"},
        {"sensor.x": SourceValue("1", None)},
        65535,
    )
    assert frame.face is Face.BRACKET
    assert frame.unit is Unit.NONE and frame.small == 0 and frame.battery is False


def test_screen_entity_ids():
    assert screen_entity_ids(SOLAR) == ["sensor.pv", "sensor.export"]
    assert screen_entity_ids(
        {"big_entity": "sensor.a", "small_source": "entity", "small_entity": "sensor.b"}
    ) == ["sensor.a", "sensor.b"]
    assert screen_entity_ids(
        {"big_entity": "sensor.a", "small_source": "fixed", "small_entity": "sensor.b"}
    ) == ["sensor.a"]


def test_markers():
    a = {"unit": "deg_c", "percent": True, "face_mode": "none"}
    b = {"unit": "deg_c", "percent": True, "face_mode": "none", "face_fixed": "sad"}
    c = {"unit": "deg_c", "percent": True, "face_mode": "fixed", "face_fixed": "sad"}
    assert markers(a) == markers(b)
    assert markers(a) != markers(c)


def test_render_unknown_fixed_face_is_none_and_production_entity_is_used():
    screen = {
        "big_entity": "sensor.x",
        "face_mode": "fixed",
        "face_fixed": "bogus",
        "small_source": "self_consumption",
        "production_entity": "sensor.prod",
        "export_entity": "sensor.export",
    }
    values = {
        "sensor.x": SourceValue("1", None),
        "sensor.prod": SourceValue("2", "kW"),
        "sensor.export": SourceValue("500", "W"),
    }
    frame = render(screen, values, 65535)
    assert frame.face is Face.NONE
    assert frame.small == 75
    assert screen_entity_ids(screen) == ["sensor.x", "sensor.prod", "sensor.export"]


def test_render_self_consumption_bad_unit_returns_none():
    values = {
        "sensor.pv": SourceValue("5", "kg"),
        "sensor.export": SourceValue("0", "W"),
    }
    assert render(SOLAR, values, 65535) is None


def test_render_wrong_unit_for_conversion_returns_none():
    values = {
        "sensor.pv": SourceValue("5", "°C"),
        "sensor.export": SourceValue("0", "W"),
    }
    assert render(SOLAR, values, 65535) is None


def test_render_overflowing_big_value_returns_none():
    screen = {"big_entity": "sensor.x", "big_multiplier": 10.0}
    assert render(screen, {"sensor.x": SourceValue("1e308", None)}, 65535) is None


def test_render_overflowing_small_value_returns_none():
    screen = {
        "big_entity": "sensor.x",
        "small_source": "entity",
        "small_entity": "sensor.y",
        "small_multiplier": 10.0,
    }
    values = {
        "sensor.x": SourceValue("1", None),
        "sensor.y": SourceValue("1e308", None),
    }
    assert render(screen, values, 65535) is None


def test_render_overflowing_self_consumption_returns_none():
    values = {
        "sensor.pv": SourceValue("1e308", "kW"),
        "sensor.export": SourceValue("0", "W"),
    }
    assert render(SOLAR, values, 65535) is None


@pytest.mark.parametrize(
    ("value", "face"),
    [
        (10, Face.SAD_BRACKET),
        (29.9, Face.SAD_BRACKET),
        (30, Face.HAPPY_SAD),
        (35, Face.HAPPY_SAD),
        (40, Face.HAPPY_BRACKET),
        (50, Face.HAPPY_BRACKET),
        (60, Face.HAPPY_BRACKET),
        (65, Face.HAPPY_SAD),
        (70, Face.HAPPY_SAD),
        (70.1, Face.SAD_BRACKET),
        (95, Face.SAD_BRACKET),
    ],
)
def test_face_middle_is_best(value, face):
    assert face_for(value, DIRECTION_MIDDLE, [30, 40, 60, 70]) is face


def test_face_middle_sorts_thresholds_first():
    assert face_for(50, DIRECTION_MIDDLE, [70, 30, 60, 40]) is Face.HAPPY_BRACKET


@pytest.mark.parametrize(
    ("value", "text"),
    [
        (12.44, "12.4"),
        (-9.5, "-9.5"),
        (199.5, "199.5"),
        (199.6, "200"),
        (-9.6, "-10"),
        (21.25, "21.3"),
        (12.45, "12.5"),
        (0.25, "0.3"),
        (199.54, "199.5"),
        (-9.54, "-9.5"),
        (250.45, "251"),
        (-0.04, "0.0"),
        (1e6, "1999"),
        (-1e6, "-100"),
    ],
)
def test_format_big(value, text):
    """Matches the LCD: tenths up to 199.5, whole numbers above, half away from 0."""
    assert format_big(value) == text


def test_user_multiplier_and_offset_are_used():
    screen = {
        "big_entity": "sensor.t",
        "big_convert": CONVERT_NONE,
        "big_multiplier": 2,
        "big_offset": 1,
    }
    frame = render(screen, {"sensor.t": SourceValue("10", None)}, 65535)
    assert frame.big == 21


PRICE_SCREEN = {
    "big_entity": "sensor.np",
    "big_convert": CONVERT_CENTS_KWH,
    "vat_percent": 24,
    "unit": "deg_c",
    "face_mode": "fixed",
    "face_fixed": "happy_sad",
}


def test_describe_screen_shows_value_symbols_and_source():
    text = describe_screen(
        PRICE_SCREEN, {"sensor.np": SourceValue("0.1234", "EUR/kWh")}
    )
    assert "big 15.3" in text
    assert "small 0" in text
    assert "face \u0394\u25b3\u0394" in text
    assert "\u00b0C" in text
    assert "from 0.1234 EUR/kWh" in text


def test_describe_screen_shows_percent_and_battery():
    screen = {
        "big_entity": "sensor.t",
        "small_source": "fixed",
        "small_fixed": 55,
        "percent": True,
        "battery": True,
    }
    text = describe_screen(screen, {"sensor.t": SourceValue("5", None)})
    assert "small 55%" in text
    assert "battery icon" in text


def test_describe_screen_omits_none_parts():
    screen = {"big_entity": "sensor.t"}
    assert (
        describe_screen(screen, {"sensor.t": SourceValue("5", None)})
        == "big 5.0 \u00b7 small 0 \u00b7 from 5"
    )


def test_describe_screen_nothing_when_unusable():
    text = describe_screen(
        PRICE_SCREEN, {"sensor.np": SourceValue("unavailable", None)}
    )
    assert text.startswith("nothing (an entity is unavailable")
    assert describe_screen(PRICE_SCREEN, {}).startswith("nothing")
