"""Tests for the entities."""

from __future__ import annotations

import struct
from unittest.mock import AsyncMock, patch

from freezegun.api import FrozenDateTimeFactory
from homeassistant.config_entries import ConfigEntryState
from homeassistant.const import STATE_OFF, STATE_ON, STATE_UNKNOWN
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ServiceValidationError
from homeassistant.helpers import entity_registry as er
import pytest

from custom_components.lcd_ticker.ble import DeviceUnreachable
from custom_components.lcd_ticker.const import (
    ACTIVITY_CHECK_INTERVAL,
    CONF_ENABLED,
    CONF_MODE,
    CONF_PROFILE,
    CONF_SECONDS,
    DOMAIN,
    MODE_SINGLE,
    PROFILE_CUSTOM,
    RELOAD_DELAY,
)

from .conftest import FakeWriter
from .test_init import advance, entity_id


async def test_rotation_switch(hass: HomeAssistant, setup_entry) -> None:
    eid = entity_id(hass, "switch", "rotation")
    assert hass.states.get(eid).state == STATE_ON
    with patch.object(hass.config_entries, "async_reload", AsyncMock()) as reload:
        await hass.services.async_call(
            "switch", "turn_off", {"entity_id": eid}, blocking=True
        )
        await hass.async_block_till_done()
    reload.assert_not_called()
    assert setup_entry.options[CONF_ENABLED] is False
    assert setup_entry.state is ConfigEntryState.LOADED
    assert hass.states.get(eid).state == STATE_OFF


async def test_seconds_number(hass: HomeAssistant, setup_entry) -> None:
    eid = entity_id(hass, "number", "seconds_per_screen")
    assert float(hass.states.get(eid).state) == 480
    with patch.object(hass.config_entries, "async_reload", AsyncMock()) as reload:
        await hass.services.async_call(
            "number", "set_value", {"entity_id": eid, "value": 300}, blocking=True
        )
        await hass.async_block_till_done()
    reload.assert_not_called()
    assert setup_entry.options[CONF_SECONDS] == 300
    assert setup_entry.options[CONF_PROFILE] == PROFILE_CUSTOM
    assert float(hass.states.get(eid).state) == 300


async def test_mode_select(hass: HomeAssistant, setup_entry) -> None:
    eid = entity_id(hass, "select", "mode")
    await hass.services.async_call(
        "select",
        "select_option",
        {"entity_id": eid, "option": MODE_SINGLE},
        blocking=True,
    )
    await hass.async_block_till_done()
    assert setup_entry.options[CONF_MODE] == MODE_SINGLE
    assert hass.states.get(eid).state == MODE_SINGLE


async def test_screen_select_shows_screen(
    hass: HomeAssistant,
    setup_entry,
    writer: FakeWriter,
) -> None:
    eid = entity_id(hass, "select", "screen")
    assert hass.states.get(eid).attributes["options"] == ["Power"]
    assert hass.states.get(eid).state == STATE_UNKNOWN
    await hass.services.async_call(
        "select", "select_option", {"entity_id": eid, "option": "Power"}, blocking=True
    )
    await hass.async_block_till_done()
    assert len(writer.writes) == 1
    assert struct.unpack("<BhhHB", writer.writes[0])[1] == 32
    assert hass.states.get(eid).state == "Power"


async def test_refresh_button(hass: HomeAssistant, setup_entry) -> None:
    eid = entity_id(hass, "button", "refresh")
    scheduler = setup_entry.runtime_data.scheduler
    with patch.object(scheduler, "async_refresh", AsyncMock()) as refresh:
        await hass.services.async_call(
            "button", "press", {"entity_id": eid}, blocking=True
        )
    refresh.assert_awaited_once()


async def test_sensors_after_write_and_failure(
    hass: HomeAssistant,
    freezer: FrozenDateTimeFactory,
    setup_entry,
    writer: FakeWriter,
) -> None:
    last_update = entity_id(hass, "sensor", "last_update")
    updates = entity_id(hass, "sensor", "updates_last_hour")
    reachable = entity_id(hass, "binary_sensor", "reachable")
    assert hass.states.get(reachable).state == STATE_UNKNOWN

    await advance(hass, freezer, RELOAD_DELAY)
    assert len(writer.writes) == 1
    assert hass.states.get(last_update).state not in (STATE_UNKNOWN, "unavailable")
    assert hass.states.get(updates).state == "1"
    assert hass.states.get(reachable).state == STATE_ON

    writer.fail = DeviceUnreachable("gone")
    await hass.services.async_call(
        "button",
        "press",
        {"entity_id": entity_id(hass, "button", "refresh")},
        blocking=True,
    )
    await hass.async_block_till_done()
    assert hass.states.get(reachable).state == STATE_OFF


async def test_last_error_disabled_by_default(
    hass: HomeAssistant,
    setup_entry,
) -> None:
    registry = er.async_get(hass)
    reg = registry.async_get(entity_id(hass, "sensor", "last_error"))
    assert reg.disabled_by is er.RegistryEntryDisabler.INTEGRATION
    assert reg.platform == DOMAIN


async def test_updates_sensor_ages_out_while_paused(
    hass: HomeAssistant,
    freezer: FrozenDateTimeFactory,
    setup_entry,
    writer: FakeWriter,
) -> None:
    updates = entity_id(hass, "sensor", "updates_last_hour")
    await advance(hass, freezer, RELOAD_DELAY)
    assert hass.states.get(updates).state == "1"
    await hass.services.async_call(
        "switch",
        "turn_off",
        {"entity_id": entity_id(hass, "switch", "rotation")},
        blocking=True,
    )
    # Let the pause settle (it writes the inactive frame once), then wait out
    # the hour. No scheduler event happens after that, only the poll.
    await advance(hass, freezer, ACTIVITY_CHECK_INTERVAL)
    await advance(hass, freezer, 3600 + 60)
    assert hass.states.get(updates).state == "0"


async def test_screen_select_vanished_slot(hass: HomeAssistant, setup_entry) -> None:
    eid = entity_id(hass, "select", "screen")
    scheduler = setup_entry.runtime_data.scheduler
    with (
        patch.object(scheduler, "async_show_now", AsyncMock(side_effect=ValueError)),
        pytest.raises(ServiceValidationError),
    ):
        await hass.services.async_call(
            "select",
            "select_option",
            {"entity_id": eid, "option": "Power"},
            blocking=True,
        )
