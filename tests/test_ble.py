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


def test_normalize_address() -> None:
    from custom_components.lcd_ticker.ble import normalize_address

    assert normalize_address("a4c138fe8d46") == "A4:C1:38:FE:8D:46"
    assert normalize_address(" A4-C1-38-FE-8D-46 ") == "A4:C1:38:FE:8D:46"
    assert normalize_address("a4 c1 38 fe 8d 46") == "A4:C1:38:FE:8D:46"
    assert normalize_address("A4C138FE8D4") is None
    assert normalize_address("MAC A4C138FE8D46") is None
    assert normalize_address("") is None


def _client() -> MagicMock:
    c = MagicMock()
    c.write_gatt_char = AsyncMock()
    c.disconnect = AsyncMock()
    c.clear_cache = AsyncMock(return_value=True)
    return c


async def test_stale_service_cache_is_cleared_and_retried_once(hass):
    """A stale GATT cache gives 'characteristic not found'; clear it and retry."""
    from bleak.exc import BleakCharacteristicNotFoundError

    stale, fresh = _client(), _client()
    stale.write_gatt_char.side_effect = BleakCharacteristicNotFoundError(CHAR_UUID)
    connect = AsyncMock(side_effect=[stale, fresh])
    with (
        patch(
            "custom_components.lcd_ticker.ble.bluetooth.async_ble_device_from_address",
            return_value=MagicMock(name="dev"),
        ),
        patch("custom_components.lcd_ticker.ble.establish_connection", connect),
    ):
        await BleWriter(hass).async_write(ADDR, [b"\x01"])
    stale.clear_cache.assert_awaited_once()
    stale.disconnect.assert_awaited_once()
    assert connect.await_count == 2
    assert connect.await_args_list[1].kwargs["use_services_cache"] is False
    fresh.write_gatt_char.assert_awaited_once_with(CHAR_UUID, b"\x01", response=False)
    fresh.disconnect.assert_awaited_once()


async def test_missing_characteristic_after_fresh_lookup_fails_clearly(hass):
    from bleak.exc import BleakCharacteristicNotFoundError

    first, second = _client(), _client()
    for c in (first, second):
        c.write_gatt_char.side_effect = BleakCharacteristicNotFoundError(CHAR_UUID)
    connect = AsyncMock(side_effect=[first, second])
    with (
        patch(
            "custom_components.lcd_ticker.ble.bluetooth.async_ble_device_from_address",
            return_value=MagicMock(name="dev"),
        ),
        patch("custom_components.lcd_ticker.ble.establish_connection", connect),
        pytest.raises(WriteFailed, match="pvvx"),
    ):
        await BleWriter(hass).async_write(ADDR, [b"\x01"])
    assert connect.await_count == 2
    second.disconnect.assert_awaited_once()


def test_write_timeout_leaves_room_for_connection_retries():
    from custom_components.lcd_ticker.const import WRITE_TIMEOUT

    # bleak-retry-connector allows ~20 s per connection attempt.
    assert WRITE_TIMEOUT >= 60


async def test_connects_with_the_client_class_installed_at_runtime(hass, client):
    """HA swaps in its own client class after import; look it up when connecting."""
    import bleak_retry_connector

    sentinel = type("HaClient", (), {})
    connect = AsyncMock(return_value=client)
    with (
        patch(
            "custom_components.lcd_ticker.ble.bluetooth.async_ble_device_from_address",
            return_value=MagicMock(name="dev"),
        ),
        patch("custom_components.lcd_ticker.ble.establish_connection", connect),
        patch.object(bleak_retry_connector, "BleakClientWithServiceCache", sentinel),
    ):
        await BleWriter(hass).async_write(ADDR, [b"\x01"])
    assert connect.await_args.args[0] is sentinel


async def test_stale_cache_falls_back_to_bluez_clear_and_refetches_device(hass):
    from bleak.exc import BleakCharacteristicNotFoundError

    stale, fresh = _client(), _client()
    stale.clear_cache.return_value = False  # class without HA's clear_cache support
    stale.write_gatt_char.side_effect = BleakCharacteristicNotFoundError(CHAR_UUID)
    connect = AsyncMock(side_effect=[stale, fresh])
    first_dev, second_dev = MagicMock(name="dev1"), MagicMock(name="dev2")
    bluez_clear = AsyncMock(return_value=True)
    with (
        patch(
            "custom_components.lcd_ticker.ble.bluetooth.async_ble_device_from_address",
            side_effect=[first_dev, second_dev],
        ),
        patch("custom_components.lcd_ticker.ble.establish_connection", connect),
        patch("custom_components.lcd_ticker.ble.clear_bluez_cache", bluez_clear),
    ):
        await BleWriter(hass).async_write(ADDR, [b"\x01"])
    bluez_clear.assert_awaited_once_with(ADDR.upper())
    assert connect.await_args_list[1].args[1] is second_dev
    fresh.write_gatt_char.assert_awaited_once()
