"""Tests for the pure frame encoder."""

import math

import pytest

from custom_components.lcd_ticker.protocol import (
    DisplayFrame,
    Face,
    Unit,
    build_ext_frame,
    build_time_frame,
    encode_big,
    encode_small,
    face_from_flags,
    round_half_away,
)


def test_golden_frame_from_upstream_readme() -> None:
    frame = DisplayFrame(
        big=5.7, small=98, validity=65535, face=Face.HAPPY_BRACKET, percent=True
    )
    assert build_ext_frame(frame).hex(" ") == "22 39 00 62 00 ff ff 0d"


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        (0, 0),
        (5.7, 57),
        (0.25, 3),
        (-0.25, -3),
        (199.5, 1995),
        (1999.5, 19995),
        (5000, 19995),
        (-99.5, -995),
        (-1000, -995),
    ],
)
def test_encode_big_rounds_and_clamps(value: float, expected: int) -> None:
    assert encode_big(value) == expected


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        (0, 0),
        (98.4, 98),
        (98.5, 99),
        (100, 99),
        (250, 99),
        (-9, -9),
        (-50, -9),
        (-2.5, -3),
    ],
)
def test_encode_small_rounds_and_clamps(value: float, expected: int) -> None:
    assert encode_small(value) == expected


@pytest.mark.parametrize("bad", [math.nan, math.inf, -math.inf])
def test_non_finite_values_are_rejected(bad: float) -> None:
    with pytest.raises(ValueError):
        encode_big(bad)
    with pytest.raises(ValueError):
        encode_small(bad)


@pytest.mark.parametrize("unit", list(Unit))
def test_unit_goes_to_top_three_bits(unit: Unit) -> None:
    assert build_ext_frame(DisplayFrame(unit=unit))[7] == unit << 5


@pytest.mark.parametrize("face", list(Face))
def test_face_goes_to_low_three_bits(face: Face) -> None:
    assert build_ext_frame(DisplayFrame(face=face))[7] == int(face)


def test_percent_and_battery_flags() -> None:
    assert build_ext_frame(DisplayFrame(percent=True))[7] == 0x08
    assert build_ext_frame(DisplayFrame(battery=True))[7] == 0x10


@pytest.mark.parametrize(
    ("validity", "expected"), [(0, 1), (1, 1), (900, 900), (70000, 65535)]
)
def test_validity_is_clamped(validity: int, expected: int) -> None:
    raw = build_ext_frame(DisplayFrame(validity=validity))
    assert int.from_bytes(raw[5:7], "little") == expected


@pytest.mark.parametrize(
    ("happy", "sad", "bracket", "face"),
    [
        (True, False, True, Face.HAPPY_BRACKET),
        (True, False, False, Face.HAPPY),
        (True, True, False, Face.HAPPY_SAD),
        (False, True, False, Face.SAD),
        (False, True, True, Face.SAD_BRACKET),
        (False, False, False, Face.NONE),
    ],
)
def test_face_from_upstream_flags(
    happy: bool, sad: bool, bracket: bool, face: Face
) -> None:
    assert face_from_flags(happy, sad, bracket) is face


def test_time_frame() -> None:
    assert build_time_frame(0x01020304).hex(" ") == "23 04 03 02 01"


def test_round_half_away() -> None:
    assert [round_half_away(v) for v in (0.5, 1.5, 2.5, -0.5, -1.5)] == [
        1,
        2,
        3,
        -1,
        -2,
    ]
