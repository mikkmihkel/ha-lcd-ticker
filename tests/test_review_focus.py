"""End-to-end checks of the review focus points: shared adapter, races, empty rotation."""

from __future__ import annotations

import asyncio
import logging
import struct
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

from bleak_retry_connector import BleakOutOfConnectionSlotsError
from freezegun.api import FrozenDateTimeFactory
from homeassistant.config_entries import ConfigSubentryData
from homeassistant.core import HomeAssistant
from homeassistant.helpers import issue_registry as ir
import pytest
from pytest_homeassistant_custom_component.common import (
    MockConfigEntry,
    async_fire_time_changed,
)

from custom_components.lcd_ticker.ble import BleWriter
from custom_components.lcd_ticker.const import (
    CONF_ADDRESS,
    CONF_BIG_ENTITY,
    CONF_BUILTIN_IN_ROTATION,
    CONF_POSITION,
    CONF_SCREEN_ENABLED,
    CONF_SECONDS,
    DOMAIN,
    FAILURES_FOR_ISSUE,
    ISSUE_UNREACHABLE,
    RELOAD_DELAY,
    SUBENTRY_SCREEN,
    VALIDITY_BUILTIN,
    default_options,
)
from custom_components.lcd_ticker.scheduler import BUILTIN_NAME, Scheduler

from .conftest import FakeWriter
from .test_init import entity_id

ADDR_A = "AA:BB:CC:DD:EE:01"
ADDR_B = "AA:BB:CC:DD:EE:02"
DWELL = 480


async def advance(
    hass: HomeAssistant, freezer: FrozenDateTimeFactory, seconds: float
) -> None:
    freezer.tick(seconds)
    async_fire_time_changed(hass)
    await hass.async_block_till_done(wait_background_tasks=True)
    await asyncio.sleep(0)


def make_entry(hass: HomeAssistant, address: str, entity: str) -> MockConfigEntry:
    entry = MockConfigEntry(
        domain=DOMAIN,
        unique_id=address,
        title=f"Thermometer {address[-2:]}",
        data={CONF_ADDRESS: address},
        options=default_options(),
        subentries_data=[
            ConfigSubentryData(
                data={CONF_BIG_ENTITY: entity, CONF_POSITION: 1},
                subentry_type=SUBENTRY_SCREEN,
                title="S",
                unique_id=None,
            )
        ],
    )
    entry.add_to_hass(hass)
    return entry


# ---- RF2: two thermometers share one adapter -------------------------------


async def test_shared_writer_serializes_and_isolates_a_failing_thermometer(
    hass: HomeAssistant, freezer: FrozenDateTimeFactory, caplog
) -> None:
    active = 0
    max_active = 0
    written: list[str] = []

    def lookup(_hass, address, connectable=True):
        device = MagicMock()
        device.address = address
        device.name = None
        return device

    async def establish(_cls, device, _name, **_kwargs):
        nonlocal active, max_active
        active += 1
        max_active = max(max_active, active)
        for _ in range(3):
            await asyncio.sleep(0)
        if device.address == ADDR_A:
            active -= 1
            raise BleakOutOfConnectionSlotsError(f"no slots for {ADDR_A}")
        client = MagicMock()

        async def write(_char, _frame, response=False):
            written.append(device.address)

        async def disconnect():
            nonlocal active
            active -= 1

        client.write_gatt_char = write
        client.disconnect = disconnect
        return client

    entries = {
        ADDR_A: make_entry(hass, ADDR_A, "sensor.a"),
        ADDR_B: make_entry(hass, ADDR_B, "sensor.b"),
    }
    writer = BleWriter(hass)
    schedulers = [Scheduler(hass, entry, writer) for entry in entries.values()]
    caplog.set_level(logging.INFO)
    with (
        patch(
            "custom_components.lcd_ticker.ble.bluetooth.async_ble_device_from_address",
            lookup,
        ),
        patch("custom_components.lcd_ticker.ble.establish_connection", establish),
    ):
        for scheduler in schedulers:
            await scheduler.async_start()
        steps = FAILURES_FOR_ISSUE + 1
        for step in range(steps):
            hass.states.async_set("sensor.a", str(step))
            hass.states.async_set("sensor.b", str(step))
            await advance(hass, freezer, RELOAD_DELAY if step == 0 else DWELL)

    registry = ir.async_get(hass)
    issue_a = f"{ISSUE_UNREACHABLE}_{entries[ADDR_A].entry_id}"
    issue_b = f"{ISSUE_UNREACHABLE}_{entries[ADDR_B].entry_id}"
    assert max_active == 1
    assert registry.async_get_issue(DOMAIN, issue_a) is not None
    assert registry.async_get_issue(DOMAIN, issue_b) is None
    assert written == [ADDR_B] * steps
    warnings = [
        r.getMessage()
        for r in caplog.records
        if r.levelno >= logging.WARNING and r.name.endswith("scheduler")
    ]
    assert len(warnings) == 1
    assert "Thermometer 01" in warnings[0]
    assert ADDR_A not in caplog.text
    for scheduler in schedulers:
        await scheduler.async_stop()


# ---- RF3: options change while a write is in flight -------------------------


class GatedWriter(FakeWriter):
    """Blocks writes while the gate is closed."""

    def __init__(self) -> None:
        super().__init__()
        self.gate = asyncio.Event()
        self.gate.set()

    async def async_write(self, address: str, frames: Any) -> None:
        await self.gate.wait()
        await super().async_write(address, frames)


async def test_apply_options_during_a_write_neither_writes_nor_loses_the_timer(
    hass: HomeAssistant, freezer: FrozenDateTimeFactory
) -> None:
    hass.states.async_set("sensor.a", "1")
    entry = make_entry(hass, ADDR_A, "sensor.a")
    writer = GatedWriter()
    writer.gate.clear()
    scheduler = Scheduler(hass, entry, writer)
    await scheduler.async_start()
    freezer.tick(RELOAD_DELAY)
    async_fire_time_changed(hass)
    await asyncio.sleep(0)
    await asyncio.sleep(0)
    assert writer.writes == []  # the write is blocked in flight

    for seconds in (300, 600, 600):
        scheduler.apply_options({**default_options(), CONF_SECONDS: seconds})
    writer.gate.set()
    await hass.async_block_till_done(wait_background_tasks=True)
    assert len(writer.writes) == 1  # no extra write from the option changes

    hass.states.async_set("sensor.a", "2")
    await advance(hass, freezer, 300)
    await advance(hass, freezer, 180)  # old speed would have written at 480
    assert len(writer.writes) == 1
    await advance(hass, freezer, 120)  # new speed: 600 s after the first tick
    assert len(writer.writes) == 2
    await scheduler.async_stop()


# ---- RF5: nothing to show ---------------------------------------------------


async def test_removing_the_last_screen_stops_writing(
    hass: HomeAssistant,
    freezer: FrozenDateTimeFactory,
    setup_entry,
    writer: FakeWriter,
) -> None:
    sub_id = next(iter(setup_entry.subentries))
    hass.config_entries.async_remove_subentry(setup_entry, sub_id)
    await hass.async_block_till_done()
    eid = entity_id(hass, "select", "screen")
    assert hass.states.get(eid).attributes["options"] == []
    assert hass.states.get(eid).state == "unknown"
    for _ in range(8):
        await advance(hass, freezer, DWELL)
    assert writer.writes == []


async def test_all_screens_disabled_leaves_only_the_builtin_reading(
    hass: HomeAssistant,
    freezer: FrozenDateTimeFactory,
    setup_entry,
    writer: FakeWriter,
) -> None:
    hass.config_entries.async_update_entry(
        setup_entry, options={**setup_entry.options, CONF_BUILTIN_IN_ROTATION: True}
    )
    sub = next(iter(setup_entry.subentries.values()))
    hass.config_entries.async_update_subentry(
        setup_entry, sub, data={**sub.data, CONF_SCREEN_ENABLED: False}
    )
    await hass.async_block_till_done()
    eid = entity_id(hass, "select", "screen")
    assert hass.states.get(eid).attributes["options"] == [BUILTIN_NAME]
    await advance(hass, freezer, RELOAD_DELAY)
    assert [struct.unpack("<BhhHB", w)[3] for w in writer.writes] == [VALIDITY_BUILTIN]


async def test_rapid_number_changes_never_reload(
    hass: HomeAssistant, setup_entry
) -> None:
    eid = entity_id(hass, "number", "seconds_per_screen")
    with patch.object(hass.config_entries, "async_reload", AsyncMock()) as reload:
        for value in (300, 310, 320, 330, 340):
            await hass.services.async_call(
                "number", "set_value", {"entity_id": eid, "value": value}, blocking=True
            )
        await hass.async_block_till_done()
    reload.assert_not_called()
    assert setup_entry.options[CONF_SECONDS] == 340


@pytest.fixture(autouse=True)
def bluetooth_loaded(hass: HomeAssistant) -> None:
    hass.config.components.update({"bluetooth", "bluetooth_adapters"})
