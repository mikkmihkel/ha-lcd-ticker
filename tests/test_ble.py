"""Tests for the serialized Bluetooth writer."""

from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

from bleak.exc import BleakError
import pytest

from custom_components.lcd_ticker.ble import (
    BleWriter,
    DeviceUnreachable,
    WriteFailed,
    get_writer,
)
from custom_components.lcd_ticker.const import CHAR_UUID

ADDR = "a4:c1:38:00:00:01"


@pytest.fixture
def client():
    """Create a mock Bluetooth client."""
    c = MagicMock()
    c.write_gatt_char = AsyncMock()
    c.disconnect = AsyncMock()
    return c


async def test_happy_path(hass, client):
    """Two frames are written, disconnect is called."""
    with (
        patch(
            "custom_components.lcd_ticker.ble.bluetooth.async_ble_device_from_address",
            return_value=MagicMock(),
        ) as lookup,
        patch(
            "custom_components.lcd_ticker.ble.establish_connection",
            AsyncMock(return_value=client),
        ),
    ):
        await BleWriter(hass).async_write(ADDR, [b"\x01", b"\x02"])

    lookup.assert_called_once_with(hass, ADDR.upper(), connectable=True)
    assert client.write_gatt_char.await_count == 2
    client.write_gatt_char.assert_any_await(CHAR_UUID, b"\x01", response=False)
    client.write_gatt_char.assert_any_await(CHAR_UUID, b"\x02", response=False)
    client.disconnect.assert_awaited_once()


async def test_no_device(hass):
    """When device is not found, raise DeviceUnreachable."""
    with (
        patch(
            "custom_components.lcd_ticker.ble.bluetooth.async_ble_device_from_address",
            return_value=None,
        ) as lookup,
        patch(
            "custom_components.lcd_ticker.ble.establish_connection",
            AsyncMock(),
        ) as establish,
        pytest.raises(DeviceUnreachable),
    ):
        await BleWriter(hass).async_write(ADDR, [b"\x01"])

    lookup.assert_called_once_with(hass, ADDR.upper(), connectable=True)
    establish.assert_not_awaited()


async def test_connect_fails(hass):
    """When connection fails, raise WriteFailed and do not disconnect."""
    with (
        patch(
            "custom_components.lcd_ticker.ble.bluetooth.async_ble_device_from_address",
            return_value=MagicMock(),
        ),
        patch(
            "custom_components.lcd_ticker.ble.establish_connection",
            AsyncMock(side_effect=BleakError("boom")),
        ),
        pytest.raises(WriteFailed),
    ):
        await BleWriter(hass).async_write(ADDR, [b"\x01"])


async def test_write_fails(hass, client):
    """When write fails, raise WriteFailed but still disconnect."""
    client.write_gatt_char = AsyncMock(side_effect=BleakError("boom"))

    with (
        patch(
            "custom_components.lcd_ticker.ble.bluetooth.async_ble_device_from_address",
            return_value=MagicMock(),
        ),
        patch(
            "custom_components.lcd_ticker.ble.establish_connection",
            AsyncMock(return_value=client),
        ),
        pytest.raises(WriteFailed),
    ):
        await BleWriter(hass).async_write(ADDR, [b"\x01"])

    client.disconnect.assert_awaited_once()


async def test_disconnect_fails(hass, client):
    """When disconnect fails, the write still succeeds."""
    client.disconnect = AsyncMock(side_effect=RuntimeError("boom"))

    with (
        patch(
            "custom_components.lcd_ticker.ble.bluetooth.async_ble_device_from_address",
            return_value=MagicMock(),
        ),
        patch(
            "custom_components.lcd_ticker.ble.establish_connection",
            AsyncMock(return_value=client),
        ),
    ):
        # Should not raise
        await BleWriter(hass).async_write(ADDR, [b"\x01"])

    client.write_gatt_char.assert_awaited_once()
    client.disconnect.assert_awaited_once()


async def test_timeout(hass, client):
    """When write times out, raise WriteFailed, disconnect is called, and lock is released."""

    async def slow_write(*args, **kwargs):
        await asyncio.sleep(1)

    client.write_gatt_char = AsyncMock(side_effect=slow_write)

    with (
        patch(
            "custom_components.lcd_ticker.ble.bluetooth.async_ble_device_from_address",
            return_value=MagicMock(),
        ),
        patch(
            "custom_components.lcd_ticker.ble.establish_connection",
            AsyncMock(return_value=client),
        ),
        patch("custom_components.lcd_ticker.ble.WRITE_TIMEOUT", 0.05),
        pytest.raises(WriteFailed),
    ):
        writer = BleWriter(hass)
        await writer.async_write(ADDR, [b"\x01"])

    # Disconnect should be called even on timeout
    client.disconnect.assert_awaited_once()
    # Lock should be released after timeout
    assert not writer._lock.locked()


async def test_serialized(hass, client):
    """Two concurrent async_write calls never overlap."""
    events = []
    in_flight = 0
    max_in_flight = 0

    async def recording_write(*args, **kwargs):
        nonlocal in_flight, max_in_flight
        in_flight += 1
        max_in_flight = max(max_in_flight, in_flight)
        events.append("enter")
        await asyncio.sleep(0.05)
        events.append("exit")
        in_flight -= 1

    client.write_gatt_char = AsyncMock(side_effect=recording_write)

    with (
        patch(
            "custom_components.lcd_ticker.ble.bluetooth.async_ble_device_from_address",
            return_value=MagicMock(),
        ),
        patch(
            "custom_components.lcd_ticker.ble.establish_connection",
            AsyncMock(return_value=client),
        ),
    ):
        writer = BleWriter(hass)
        await asyncio.gather(
            writer.async_write("a4:c1:38:00:00:01", [b"\x01"]),
            writer.async_write("a4:c1:38:00:00:02", [b"\x02"]),
        )

    # Verify exactly 4 events in strict order: enter, exit, enter, exit
    assert events == ["enter", "exit", "enter", "exit"]
    # Verify only one write was in-flight at a time
    assert max_in_flight == 1


async def test_shared_instance(hass):
    """get_writer returns the same instance."""
    writer1 = get_writer(hass)
    writer2 = get_writer(hass)
    assert writer1 is writer2


async def test_address_upper_cased(hass):
    """Address is uppercased before lookup."""
    with (
        patch(
            "custom_components.lcd_ticker.ble.bluetooth.async_ble_device_from_address",
            return_value=MagicMock(),
        ) as lookup,
        patch(
            "custom_components.lcd_ticker.ble.establish_connection",
            AsyncMock(
                return_value=MagicMock(
                    write_gatt_char=AsyncMock(), disconnect=AsyncMock()
                )
            ),
        ),
    ):
        await BleWriter(hass).async_write(ADDR, [b"\x01"])

    # First argument after hass should be uppercase
    call_args = lookup.call_args
    assert call_args[0][1] == ADDR.upper()


async def test_address_masked_in_error(hass):
    """WriteFailed message does not contain the device address."""
    with (
        patch(
            "custom_components.lcd_ticker.ble.bluetooth.async_ble_device_from_address",
            return_value=MagicMock(),
        ),
        patch(
            "custom_components.lcd_ticker.ble.establish_connection",
            AsyncMock(side_effect=BleakError(f"{ADDR.upper()} not found")),
        ),
        pytest.raises(WriteFailed) as exc_info,
    ):
        await BleWriter(hass).async_write(ADDR, [b"\x01"])

    # Address should not appear in the error message
    assert ADDR.upper() not in str(exc_info.value)
    assert ADDR.lower() not in str(exc_info.value)
    # But the placeholder should be there
    assert "<address>" in str(exc_info.value)


def test_mask_address_covers_all_forms():
    from custom_components.lcd_ticker.ble import mask_address

    text = "a4:c1:38:00:00:01 A4-C1-38-00-00-01 dev_A4_C1_38_00_00_01 ok"
    assert mask_address(text) == "<address> <address> dev_<address> ok"


async def test_connection_name_is_not_the_address(hass, client):
    device = MagicMock()
    device.name = None
    establish = AsyncMock(return_value=client)
    with (
        patch(
            "custom_components.lcd_ticker.ble.bluetooth.async_ble_device_from_address",
            return_value=device,
        ),
        patch("custom_components.lcd_ticker.ble.establish_connection", establish),
    ):
        await BleWriter(hass).async_write(ADDR, [b"\x01"])
    assert establish.await_args.args[2] == "thermometer"


async def test_bluez_style_error_is_masked(hass):
    with (
        patch(
            "custom_components.lcd_ticker.ble.bluetooth.async_ble_device_from_address",
            return_value=MagicMock(),
        ),
        patch(
            "custom_components.lcd_ticker.ble.establish_connection",
            AsyncMock(side_effect=BleakError("/org/bluez/hci0/dev_A4_C1_38_00_00_01")),
        ),
        pytest.raises(WriteFailed) as err,
    ):
        await BleWriter(hass).async_write(ADDR, [b"\x01"])
    assert "A4_C1" not in str(err.value)
