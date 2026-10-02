"""Tests for setup, unload and the update listener."""

from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, patch

from freezegun.api import FrozenDateTimeFactory
from homeassistant.config_entries import ConfigEntryState, ConfigSubentry
from homeassistant.core import HomeAssistant
from homeassistant.helpers import entity_registry as er
from pytest_homeassistant_custom_component.common import (
    async_fire_time_changed,
)

from custom_components.lcd_ticker.const import (
    CONF_PRESENCE_ENTITY,
    CONF_SECONDS,
    DOMAIN,
    SUBENTRY_SCREEN,
)

from .conftest import ADDR, FakeWriter


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
