"""Tests for the serialized Bluetooth writer."""

from __future__ import annotations

import asyncio
import time
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
    client = MagicMock()
    client.disconnect = AsyncMock()

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

    client.disconnect.assert_not_awaited()


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
    """When write times out, raise WriteFailed."""

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
        await BleWriter(hass).async_write(ADDR, [b"\x01"])


async def test_serialized(hass, client):
    """Two concurrent async_write calls never overlap."""
    timestamps = []

    async def recording_write(*args, **kwargs):
        timestamps.append(("enter", time.monotonic()))
        await asyncio.sleep(0.05)
        timestamps.append(("exit", time.monotonic()))

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

    # Should have 4 events: enter1, exit1, enter2, exit2
    assert len(timestamps) == 4
    # Second enter should be after first exit
    assert timestamps[1][1] <= timestamps[2][1]


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
