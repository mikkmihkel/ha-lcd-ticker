"""Tests for the entities."""

from __future__ import annotations

import struct
from unittest.mock import AsyncMock, patch

from freezegun.api import FrozenDateTimeFactory
from homeassistant.config_entries import ConfigEntryState
from homeassistant.const import (
    STATE_OFF,
    STATE_ON,
    STATE_UNAVAILABLE,
    STATE_UNKNOWN,
    EntityCategory,
)
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

from .conftest import ADVERT_A, ADVERT_B, FakeBluetooth, FakeWriter
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


READING_NAMES = {
    "temperature": "Kitchen Temperature",
    "humidity": "Kitchen Humidity",
    "battery": "Kitchen Battery",
    "voltage": "Kitchen Voltage",
    "signal_strength": "Kitchen Signal strength",
}


async def test_reading_sensors_unavailable_until_advert(
    hass: HomeAssistant, setup_entry
) -> None:
    for key in ("temperature", "humidity", "battery", "voltage"):
        state = hass.states.get(entity_id(hass, "sensor", key))
        assert state.state == STATE_UNAVAILABLE


async def test_reading_sensors_follow_adverts(
    hass: HomeAssistant, setup_entry, bluetooth_mock: FakeBluetooth
) -> None:
    bluetooth_mock.advert(ADVERT_A, rssi=-71)
    await hass.async_block_till_done()
    temperature = hass.states.get(entity_id(hass, "sensor", "temperature"))
    assert float(temperature.state) == 25.0
    assert temperature.attributes["unit_of_measurement"] == "°C"
    assert temperature.attributes["device_class"] == "temperature"
    assert float(hass.states.get(entity_id(hass, "sensor", "humidity")).state) == 50.55
    assert hass.states.get(entity_id(hass, "sensor", "battery")).state == "92"
    # The voltage comes with the other advert; until then it stays unavailable.
    voltage_id = entity_id(hass, "sensor", "voltage")
    assert hass.states.get(voltage_id).state == STATE_UNAVAILABLE
    bluetooth_mock.advert(ADVERT_B)
    await hass.async_block_till_done()
    assert float(hass.states.get(voltage_id).state) == 2.858
    # The earlier values stay while the adverts alternate.
    assert hass.states.get(entity_id(hass, "sensor", "battery")).state == "92"


async def test_reading_sensors_unavailable_when_thermometer_silent(
    hass: HomeAssistant, setup_entry, bluetooth_mock: FakeBluetooth
) -> None:
    bluetooth_mock.advert(ADVERT_A)
    bluetooth_mock.go_unavailable()
    await hass.async_block_till_done()
    eid = entity_id(hass, "sensor", "temperature")
    assert hass.states.get(eid).state == STATE_UNAVAILABLE


async def test_signal_strength_disabled_by_default(
    hass: HomeAssistant, setup_entry
) -> None:
    entry = er.async_get(hass).async_get(entity_id(hass, "sensor", "signal_strength"))
    assert entry.disabled_by is er.RegistryEntryDisabler.INTEGRATION


async def test_reading_sensor_names_and_categories(
    hass: HomeAssistant, setup_entry
) -> None:
    registry = er.async_get(hass)
    for key, name in READING_NAMES.items():
        entry = registry.async_get(entity_id(hass, "sensor", key))
        assert entry.original_name == name.removeprefix("Kitchen ")
    categories = {
        key: registry.async_get(entity_id(hass, "sensor", key)).entity_category
        for key in READING_NAMES
    }
    assert categories["temperature"] is None
    assert categories["humidity"] is None
    assert categories["battery"] is EntityCategory.DIAGNOSTIC
    assert categories["voltage"] is EntityCategory.DIAGNOSTIC


async def test_signal_strength_value_when_enabled(
    hass: HomeAssistant, setup_entry, bluetooth_mock: FakeBluetooth
) -> None:
    registry = er.async_get(hass)
    eid = entity_id(hass, "sensor", "signal_strength")
    registry.async_update_entity(eid, disabled_by=None)
    await hass.config_entries.async_reload(setup_entry.entry_id)
    await hass.async_block_till_done()
    bluetooth_mock.advert(ADVERT_A, rssi=-71)
    await hass.async_block_till_done()
    assert hass.states.get(eid).state == "-71"
