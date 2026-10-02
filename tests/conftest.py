"""Shared test fixtures."""

from __future__ import annotations

from collections.abc import Callable
from types import SimpleNamespace
from typing import Any
from unittest.mock import MagicMock, patch

from homeassistant.config_entries import ConfigEntryState
from homeassistant.core import HomeAssistant
import pytest
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.lcd_ticker.const import (
    CONF_ADDRESS,
    DOMAIN,
    SUBENTRY_SCREEN,
    default_options,
)


@pytest.fixture(autouse=True)
def auto_enable_custom_integrations(enable_custom_integrations: None) -> None:
    """Load custom_components/ in every test."""


ADDR = "AA:BB:CC:DD:EE:FF"


class FakeWriter:
    """Records frames; can be told to fail."""

    def __init__(self) -> None:
        self.writes: list[bytes] = []
        self.fail: Exception | None = None

    async def async_write(self, address: str, frames: Any) -> None:
        if self.fail:
            raise self.fail
        self.writes.extend(frames)


BTHOME = "0000fcd2-0000-1000-8000-00805f9b34fb"
ADVERT_A = bytes.fromhex("40002a015c02c40903bf13")  # 92 %, 25.0 °C, 50.55 %
ADVERT_B = bytes.fromhex("40002b0c2a0b")  # 2.858 V


def service_info(data: bytes, rssi: int = -60) -> SimpleNamespace:
    """The few fields of a Bluetooth service info that the listener reads."""
    return SimpleNamespace(service_data={BTHOME: data}, rssi=rssi)


class FakeBluetooth:
    """Stands in for the Bluetooth stack: keeps the registered callbacks."""

    def __init__(self) -> None:
        self.callback: Callable[..., None] | None = None
        self.unavailable_callback: Callable[..., None] | None = None
        self.last_info: SimpleNamespace | None = None
        self.unregister = MagicMock()
        self.unregister_unavailable = MagicMock()

    def register(self, hass, callback, matcher, mode, **kwargs):
        self.callback = callback
        self.matcher = matcher
        self.mode = mode
        return self.unregister

    def track_unavailable(self, hass, callback, address, connectable=True):
        self.unavailable_callback = callback
        return self.unregister_unavailable

    def advert(self, data: bytes, rssi: int = -60) -> None:
        assert self.callback is not None
        self.callback(service_info(data, rssi), None)

    def go_unavailable(self) -> None:
        assert self.unavailable_callback is not None
        self.unavailable_callback(SimpleNamespace())


@pytest.fixture
def bluetooth_mock():
    """Replace the three Bluetooth calls the readings listener makes."""
    fake = FakeBluetooth()
    base = "custom_components.lcd_ticker.readings.bluetooth"
    with (
        patch(f"{base}.async_register_callback", side_effect=fake.register),
        patch(f"{base}.async_track_unavailable", side_effect=fake.track_unavailable),
        patch(
            f"{base}.async_last_service_info",
            side_effect=lambda hass, address, connectable=True: fake.last_info,
        ),
    ):
        yield fake


@pytest.fixture
def writer() -> FakeWriter:
    return FakeWriter()


@pytest.fixture
async def setup_entry(
    hass: HomeAssistant, writer: FakeWriter, bluetooth_mock: FakeBluetooth
):
    """Set up a real entry with a fake writer; unload at the end."""
    # The manifest depends on bluetooth_adapters. Mark it loaded instead of
    # setting up the real stack (enable_bluetooth needs BlueZ/dbus on the host).
    hass.config.components.update({"bluetooth", "bluetooth_adapters"})
    hass.states.async_set("sensor.power", "3.2", {"unit_of_measurement": "kW"})
    entry = MockConfigEntry(
        domain=DOMAIN,
        unique_id=ADDR,
        title="Kitchen",
        data={CONF_ADDRESS: ADDR},
        options=default_options(),
        subentries_data=[
            {
                "data": {"big_entity": "sensor.power", "position": 1},
                "subentry_type": SUBENTRY_SCREEN,
                "title": "Power",
                "unique_id": None,
            }
        ],
    )
    entry.add_to_hass(hass)
    with (
        patch("custom_components.lcd_ticker.get_writer", return_value=writer),
        patch("custom_components.lcd_ticker.services.get_writer", return_value=writer),
    ):
        assert await hass.config_entries.async_setup(entry.entry_id)
        await hass.async_block_till_done()
        yield entry
        if entry.state is ConfigEntryState.LOADED:
            await hass.config_entries.async_unload(entry.entry_id)
            await hass.async_block_till_done()
