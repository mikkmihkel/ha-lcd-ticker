"""Shared test fixtures."""

from __future__ import annotations

from typing import Any
from unittest.mock import patch

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


@pytest.fixture
def writer() -> FakeWriter:
    return FakeWriter()


@pytest.fixture
async def setup_entry(hass: HomeAssistant, writer: FakeWriter):
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
