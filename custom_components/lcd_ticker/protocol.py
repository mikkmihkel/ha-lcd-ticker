"""pvvx LCD frame encoding. Pure: no Home Assistant imports.

External data frame (command 0x22), 8 bytes, little endian:
    [0]   0x22
    [1:3] big number    int16, value x 10   (-99.4 .. 1999.4)
    [3:5] small number  int16               (-9 .. 99)
    [5:7] validity      uint16, seconds     (0xFFFF = show permanently)
    [7]   flags: bits0-2 smiley value, bit3 %, bit4 battery icon, bits5-7 unit

Time frame (command 0x23): 0x23 + uint32 unix time.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import IntEnum
import math
import struct

EXT_CMD = 0x22
TIME_CMD = 0x23

# -99.5 would encode -995, which the firmware draws as a garbled "-100".
BIG_MIN = -99.4
# 1999.5 would encode 19995; the firmware rounds that to 2000, which the LCD shows as "1000".
BIG_MAX = 1999.4
SMALL_MIN = -9
SMALL_MAX = 99
VALIDITY_MIN = 1
VALIDITY_MAX = 0xFFFF


class Unit(IntEnum):
    """Symbol next to the big number (firmware `temp_symbol`)."""

    NONE = 0
    DEG_GHE = 1
    MINUS = 2
    DEG_F = 3
    LOWDASH = 4
    DEG_C = 5
    LINES = 6
    DEG_E = 7


class Face(IntEnum):
    """3-bit smiley value. Bit 0 happy, bit 1 sad, bit 2 bracket."""

    NONE = 0
    HAPPY = 1
    SAD = 2
    HAPPY_SAD = 3
    BRACKET = 4
    HAPPY_BRACKET = 5
    SAD_BRACKET = 6
    HAPPY_SAD_BRACKET = 7


UNIT_KEYS: dict[str, Unit] = {u.name.lower(): u for u in Unit}
FACE_KEYS: dict[str, Face] = {f.name.lower(): f for f in Face}


def face_from_flags(happy: bool, sad: bool, bracket: bool) -> Face:
    """Map the upstream pvvx_display booleans onto the firmware smiley value."""
    return Face(int(bool(happy)) | int(bool(sad)) << 1 | int(bool(bracket)) << 2)


@dataclass(frozen=True, slots=True)
class DisplayFrame:
    """What the LCD should show."""

    big: float = 0.0
    small: int = 0
    validity: int = VALIDITY_MAX
    unit: Unit = Unit.NONE
    face: Face = Face.NONE
    percent: bool = False
    battery: bool = False


def round_half_away(value: float) -> int:
    """Round 2.5 -> 3 and -2.5 -> -3 (Python's round() would give 2 and -2)."""
    return int(math.copysign(math.floor(abs(value) + 0.5), value))


def _clamp(value: float, low: float, high: float) -> float:
    return max(low, min(high, value))


def _finite(value: float) -> float:
    value = float(value)
    if not math.isfinite(value):
        raise ValueError(f"value must be a finite number, got {value!r}")
    return value


def encode_big(value: float) -> int:
    """Big number as int16 tenths, clamped so the LCD never shows iH/oL."""
    return round_half_away(_clamp(_finite(value), BIG_MIN, BIG_MAX) * 10)


def encode_small(value: float) -> int:
    """Small number as a whole int16, clamped to -9..99 (100 would show iH)."""
    return int(_clamp(round_half_away(_finite(value)), SMALL_MIN, SMALL_MAX))


def build_ext_frame(frame: DisplayFrame) -> bytes:
    """Encode a DisplayFrame as the 8-byte 0x22 command."""
    flags = (
        (int(frame.face) & 0x07)
        | (0x08 if frame.percent else 0)
        | (0x10 if frame.battery else 0)
        | ((int(frame.unit) & 0x07) << 5)
    )
    validity = int(_clamp(int(frame.validity), VALIDITY_MIN, VALIDITY_MAX))
    return struct.pack(
        "<BhhHB",
        EXT_CMD,
        encode_big(frame.big),
        encode_small(frame.small),
        validity,
        flags,
    )


def build_time_frame(unix_ts: float) -> bytes:
    """Encode the 0x23 set-time command."""
    return struct.pack("<BI", TIME_CMD, int(unix_ts) & 0xFFFFFFFF)
