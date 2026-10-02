"""Parse the thermometer's own Bluetooth adverts. Pure: no Home Assistant imports."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
import struct

BTHOME_UUID = "0000fcd2-0000-1000-8000-00805f9b34fb"
ENV_UUID = "0000181a-0000-1000-8000-00805f9b34fb"

# BTHome object id -> value size in bytes. Objects not listed (variable length
# or unknown) end the parse, because we can't tell where the next one starts.
_SIZES: dict[int, int] = {
    **dict.fromkeys(
        [
            0x00,
            0x01,
            0x09,
            *range(0x0F, 0x30),
            0x46,
            0x57,
            0x58,
            0x59,
            0x60,
            0x64,
            0x65,
        ],
        1,
    ),
    **dict.fromkeys(
        [
            0x02,
            0x03,
            0x06,
            0x07,
            0x08,
            0x0C,
            0x0D,
            0x0E,
            0x12,
            0x13,
            0x14,
            0x3D,
            0x3F,
            0x40,
            0x41,
            0x43,
            0x44,
            0x45,
            0x47,
            0x48,
            0x49,
            0x4A,
            0x51,
            0x52,
            0x56,
            0x5A,
            0x5D,
            0x5E,
            0x5F,
            0x61,
        ],
        2,
    ),
    **dict.fromkeys([0x04, 0x05, 0x0A, 0x0B, 0x42, 0x4B], 3),
    **dict.fromkeys(
        [0x3E, 0x4C, 0x4D, 0x4E, 0x4F, 0x50, 0x55, 0x5B, 0x5C, 0x62, 0x63], 4
    ),
}


@dataclass(frozen=True, slots=True)
class Readings:
    """What one advert tells us. None means not in this advert."""

    temperature: float | None = None  # °C
    humidity: float | None = None  # %
    battery: int | None = None  # %
    voltage: float | None = None  # V


def parse_service_data(service_data: Mapping[str, bytes]) -> Readings | None:
    """Return the readings in an advert, or None if there are none. Never raises."""
    try:
        values = _parse_env(service_data.get(ENV_UUID))
        values.update(_parse_bthome(service_data.get(BTHOME_UUID)))
        return _readings(values)
    except struct.error, ValueError, TypeError:
        return None


def _readings(values: dict[str, float]) -> Readings | None:
    """Build Readings, dropping values a real sensor could not report."""
    ranges = {
        "temperature": (-40, 100),
        "humidity": (0, 100),
        "battery": (0, 100),
        "voltage": (0, 4),
    }
    ok = {k: v for k, v in values.items() if ranges[k][0] <= v <= ranges[k][1]}
    if not ok:
        return None
    return Readings(
        temperature=ok.get("temperature"),
        humidity=ok.get("humidity"),
        battery=int(ok["battery"]) if "battery" in ok else None,
        voltage=ok.get("voltage"),
    )


def _parse_bthome(data: bytes | None) -> dict[str, float]:
    """BTHome v2, unencrypted. Objects follow the device-info byte."""
    values: dict[str, float] = {}
    if not data or data[0] & 0x01 or (data[0] >> 5) != 2:
        return values
    pos = 1
    while pos < len(data):
        object_id = data[pos]
        size = _SIZES.get(object_id)
        if size is None or pos + 1 + size > len(data):
            break  # unknown, variable length or truncated
        raw = data[pos + 1 : pos + 1 + size]
        pos += 1 + size
        if object_id == 0x01:
            values["battery"] = raw[0]
        elif object_id == 0x02:
            values["temperature"] = round(
                int.from_bytes(raw, "little", signed=True) * 0.01, 2
            )
        elif object_id == 0x45:
            values["temperature"] = round(
                int.from_bytes(raw, "little", signed=True) * 0.1, 1
            )
        elif object_id == 0x03:
            values["humidity"] = round(int.from_bytes(raw, "little") * 0.01, 2)
        elif object_id == 0x2E:
            values["humidity"] = raw[0]
        elif object_id == 0x0C:
            values["voltage"] = round(int.from_bytes(raw, "little") * 0.001, 3)
    return values


def _parse_env(data: bytes | None) -> dict[str, float]:
    """pvvx custom (14 or 15 bytes, little endian) or ATC1441 (13, big endian)."""
    if data is not None and len(data) == 13:
        temp, hum, battery, millivolts, _counter = struct.unpack_from(">hBBHB", data, 6)
        return {
            "temperature": round(temp * 0.1, 1),
            "humidity": hum,
            "battery": battery,
            "voltage": round(millivolts * 0.001, 3),
        }
    if data is not None and len(data) in (14, 15):
        temp, hum, millivolts, battery = struct.unpack_from("<hHHB", data, 6)
        return {
            "temperature": round(temp * 0.01, 2),
            "humidity": round(hum * 0.01, 2),
            "battery": battery,
            "voltage": round(millivolts * 0.001, 3),
        }
    return {}
