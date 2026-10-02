"""Tests for the pure advertisement parser."""

from __future__ import annotations

import random
import struct

import pytest

from custom_components.lcd_ticker.advertisement import Readings, parse_service_data

BTHOME = "0000fcd2-0000-1000-8000-00805f9b34fb"
ENV = "0000181a-0000-1000-8000-00805f9b34fb"
MAC = bytes.fromhex("ffeeddccbbaa")


def bthome(hex_string: str) -> dict[str, bytes]:
    return {BTHOME: bytes.fromhex(hex_string)}


def test_bthome_advert_a() -> None:
    r = parse_service_data(bthome("40002a015c02c40903bf13"))
    assert r == Readings(temperature=25.0, humidity=50.55, battery=92)


def test_bthome_advert_b() -> None:
    r = parse_service_data(bthome("40002b0c2a0b"))
    assert r == Readings(voltage=2.858)


def test_bthome_advert_b_with_binary_objects() -> None:
    r = parse_service_data(bthome("40002b0c2a0b1000011100"))
    assert r is not None and r.voltage == 2.858


def test_bthome_ids_12_to_14_are_two_bytes() -> None:
    # 0x12 (CO2) takes 2 bytes; if it took 1 the battery after it would be lost
    r = parse_service_data(bthome("4012e803015c"))
    assert r == Readings(battery=92)


def test_bthome_u8_humidity_and_temp_tenths() -> None:
    r = parse_service_data(bthome("402e3245fa00"))
    assert r == Readings(temperature=25.0, humidity=50.0)


def test_bthome_negative_temperature() -> None:
    r = parse_service_data(bthome("4002" + struct.pack("<h", -550).hex()))
    assert r == Readings(temperature=-5.5)


def test_bthome_encrypted_rejected() -> None:
    assert parse_service_data(bthome("412a015c")) is None


def test_bthome_wrong_version_rejected() -> None:
    assert parse_service_data(bthome("202a015c")) is None


def test_bthome_trigger_flag_ok() -> None:
    r = parse_service_data(bthome("44015c"))
    assert r == Readings(battery=92)


def test_bthome_unknown_id_keeps_earlier_fields() -> None:
    # 0x3a is variable length: stop, keep the battery read before it.
    r = parse_service_data(bthome("40015c3a01020300"))
    assert r == Readings(battery=92)


def test_bthome_skips_known_other_sizes() -> None:
    # 0x04 pressure (3 bytes), 0x05 illuminance (3), 0x3e (4), then battery.
    r = parse_service_data(bthome("40040102033e01020304015c"))
    assert r == Readings(battery=92)


def test_bthome_truncated_value() -> None:
    r = parse_service_data(bthome("40015c02c4"))
    assert r == Readings(battery=92)


def test_bthome_only_header() -> None:
    assert parse_service_data(bthome("40")) is None


def test_bthome_empty_data() -> None:
    assert parse_service_data({BTHOME: b""}) is None


def test_bthome_implausible_values_dropped() -> None:
    # temperature 150.0, humidity 120.0, battery 101, voltage 5.0
    data = "40" + "02" + struct.pack("<h", 15000).hex()
    data += "03" + struct.pack("<H", 12000).hex()
    data += "0165" + "0c" + struct.pack("<H", 5000).hex()
    assert parse_service_data(bthome(data)) is None


def test_bthome_implausible_temperature_keeps_others() -> None:
    data = "40" + "02" + struct.pack("<h", 15000).hex() + "015c"
    assert parse_service_data(bthome(data)) == Readings(battery=92)


def test_pvvx_custom_15_bytes() -> None:
    raw = MAC + struct.pack("<hHHBBB", 2512, 4987, 2950, 88, 7, 0x05)
    assert len(raw) == 15
    r = parse_service_data({ENV: raw})
    assert r == Readings(temperature=25.12, humidity=49.87, battery=88, voltage=2.95)


def test_pvvx_custom_14_bytes() -> None:
    raw = MAC + struct.pack("<hHHBB", -310, 6000, 3000, 50, 1)
    assert len(raw) == 14
    r = parse_service_data({ENV: raw})
    assert r == Readings(temperature=-3.1, humidity=60.0, battery=50, voltage=3.0)


def test_atc1441_13_bytes() -> None:
    raw = MAC + struct.pack(">hBBHB", 251, 49, 88, 2950, 7)
    assert len(raw) == 13
    r = parse_service_data({ENV: raw})
    assert r == Readings(temperature=25.1, humidity=49.0, battery=88, voltage=2.95)


@pytest.mark.parametrize("size", [0, 1, 12, 16, 20])
def test_env_wrong_length(size: int) -> None:
    assert parse_service_data({ENV: bytes(size)}) is None


def test_empty_mapping() -> None:
    assert parse_service_data({}) is None


def test_unrelated_uuid() -> None:
    assert parse_service_data({"0000feaa-0000-1000-8000-00805f9b34fb": b"1234"}) is None


def test_merges_bthome_and_env_when_both_present() -> None:
    raw = MAC + struct.pack("<hHHBB", 2000, 5000, 3000, 50, 1)
    r = parse_service_data({ENV: raw, BTHOME: bytes.fromhex("40015c")})
    assert r is not None and r.temperature == 20.0 and r.battery == 92


def test_never_raises_on_random_bytes() -> None:
    rng = random.Random(1234)  # noqa: S311 (test data only)
    for _ in range(500):
        data = bytes(rng.randrange(256) for _ in range(rng.randrange(0, 40)))
        parse_service_data({BTHOME: data})
        parse_service_data({ENV: data})
        parse_service_data({BTHOME: bytes([0x40]) + data})
