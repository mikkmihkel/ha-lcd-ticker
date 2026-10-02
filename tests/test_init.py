"""Tests for setup, unload and the update listener."""

from __future__ import annotations

import asyncio
from typing import Any
from unittest.mock import AsyncMock, patch

from freezegun.api import FrozenDateTimeFactory
from homeassistant.config_entries import ConfigEntryState, ConfigSubentry
from homeassistant.core import HomeAssistant
from homeassistant.helpers import entity_registry as er
import pytest
from pytest_homeassistant_custom_component.common import (
    MockConfigEntry,
    async_fire_time_changed,
)

from custom_components.lcd_ticker.const import (
    CONF_ADDRESS,
    CONF_PRESENCE_ENTITY,
    CONF_SECONDS,
    DOMAIN,
    SUBENTRY_SCREEN,
    default_options,
)

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


def entity_id(hass: HomeAssistant, platform: str, key: str) -> str:
    found = er.async_get(hass).async_get_entity_id(platform, DOMAIN, f"{ADDR}_{key}")
    assert found is not None, f"{platform} {key} missing"
    return found


async def advance(
    hass: HomeAssistant, freezer: FrozenDateTimeFactory, seconds: float
) -> None:
    freezer.tick(seconds)
    async_fire_time_changed(hass)
    await hass.async_block_till_done()
    await asyncio.sleep(0)


ENTITIES = [
    ("switch", "rotation"),
    ("select", "mode"),
    ("select", "screen"),
    ("number", "seconds_per_screen"),
    ("number", "seconds_per_screen_present"),
    ("button", "refresh"),
    ("sensor", "last_update"),
    ("sensor", "updates_last_hour"),
    ("sensor", "estimated_updates_per_hour"),
    ("sensor", "last_error"),
    ("binary_sensor", "reachable"),
]


async def test_setup_creates_entities(hass: HomeAssistant, setup_entry) -> None:
    assert setup_entry.state is ConfigEntryState.LOADED
    for platform, key in ENTITIES:
        entity_id(hass, platform, key)


async def test_unload_stops_scheduler(
    hass: HomeAssistant,
    freezer: FrozenDateTimeFactory,
    setup_entry,
    writer: FakeWriter,
) -> None:
    assert await hass.config_entries.async_unload(setup_entry.entry_id)
    await hass.async_block_till_done()
    assert setup_entry.state is ConfigEntryState.NOT_LOADED
    await advance(hass, freezer, 3600)
    assert writer.writes == []


async def test_live_option_does_not_reload(hass: HomeAssistant, setup_entry) -> None:
    with patch.object(hass.config_entries, "async_reload", AsyncMock()) as reload:
        hass.config_entries.async_update_entry(
            setup_entry, options={**setup_entry.options, CONF_SECONDS: 300}
        )
        await hass.async_block_till_done()
    reload.assert_not_called()
    assert setup_entry.state is ConfigEntryState.LOADED


async def test_structural_option_reloads(hass: HomeAssistant, setup_entry) -> None:
    with patch.object(hass.config_entries, "async_reload", AsyncMock()) as reload:
        hass.config_entries.async_update_entry(
            setup_entry,
            options={**setup_entry.options, CONF_PRESENCE_ENTITY: "binary_sensor.p"},
        )
        await hass.async_block_till_done()
    reload.assert_called_once_with(setup_entry.entry_id)


async def test_new_subentry_reloads(hass: HomeAssistant, setup_entry) -> None:
    with patch.object(hass.config_entries, "async_reload", AsyncMock()) as reload:
        hass.config_entries.async_add_subentry(
            setup_entry,
            ConfigSubentry(
                data={"big_entity": "sensor.power", "position": 2},
                subentry_type=SUBENTRY_SCREEN,
                title="Two",
                unique_id=None,
            ),
        )
        await hass.async_block_till_done()
    reload.assert_called_once_with(setup_entry.entry_id)
