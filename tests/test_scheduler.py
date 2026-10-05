"""Tests for the scheduler."""

from __future__ import annotations

import asyncio
import datetime
import logging
import struct
from typing import Any
from unittest.mock import patch

from freezegun.api import FrozenDateTimeFactory
from homeassistant.config_entries import ConfigSubentryData
from homeassistant.core import CoreState, HomeAssistant
from homeassistant.helpers import issue_registry as ir
from homeassistant.helpers.dispatcher import async_dispatcher_connect
import pytest
from pytest_homeassistant_custom_component.common import (
    MockConfigEntry,
    async_fire_time_changed,
)

from custom_components.lcd_ticker.ble import DeviceUnreachable, WriteFailed
from custom_components.lcd_ticker.const import (
    ACTIVITY_CHECK_INTERVAL,
    CONF_ACTIVE_ENTITY,
    CONF_ADDRESS,
    CONF_BIG_ENTITY,
    CONF_BUILTIN_IN_ROTATION,
    CONF_ENABLED,
    CONF_INACTIVE_DISPLAY,
    CONF_JUMP_DELTA,
    CONF_MODE,
    CONF_ON_HA_STOP,
    CONF_POSITION,
    CONF_PRESENCE_ENTITY,
    CONF_QUIET_END,
    CONF_QUIET_START,
    CONF_SCREEN_ENABLED,
    CONF_SECONDS,
    CONF_SHOW_WHEN,
    CONF_TAKEOVER,
    CONF_UNIT,
    DOMAIN,
    FAILURES_FOR_ISSUE,
    HA_STOP_ALTERNATE,
    INACTIVE_LEAVE,
    INACTIVE_ZEROS,
    ISSUE_UNREACHABLE,
    MIN_WRITE_GAP,
    MODE_SINGLE,
    RELOAD_DELAY,
    START_DELAY,
    SUBENTRY_SCREEN,
    VALIDITY_BUILTIN,
    VALIDITY_PERMANENT,
    default_options,
    signal_update,
)
from custom_components.lcd_ticker.protocol import build_ext_frame
from custom_components.lcd_ticker.render import SourceValue, render
from custom_components.lcd_ticker.scheduler import (
    BUILTIN_NAME,
    Scheduler,
    estimate_updates_per_hour,
    in_quiet_hours,
)

ADDR = "AA:BB:CC:DD:EE:FF"
DWELL = 480  # balanced profile, normal
DWELL_PRESENT = 180


class FakeWriter:
    """Records frames; can be told to fail."""

    def __init__(self) -> None:
        self.writes: list[bytes] = []
        self.fail: Exception | None = None

    async def async_write(self, address: str, frames: Any) -> None:
        if self.fail:
            raise self.fail
        self.writes.extend(frames)


def decode(payload: bytes) -> tuple[float, int, int, int]:
    """(big, small, validity, flags)"""
    _, big, small, validity, flags = struct.unpack("<BhhHB", payload)
    return big / 10, small, validity, flags


def bigs(writer: FakeWriter) -> list[float]:
    return [decode(w)[0] for w in writer.writes]


def screen(entity: str, position: int = 1, **extra: Any) -> dict[str, Any]:
    return {CONF_BIG_ENTITY: entity, CONF_POSITION: position, **extra}


def make_entry(
    hass: HomeAssistant,
    options: dict[str, Any] | None = None,
    screens: tuple[dict[str, Any], ...] = (),
) -> MockConfigEntry:
    entry = MockConfigEntry(
        domain=DOMAIN,
        unique_id=ADDR,
        title="Kitchen",
        data={CONF_ADDRESS: ADDR},
        options={**default_options(), **(options or {})},
        subentries_data=[
            ConfigSubentryData(
                data=s, subentry_type=SUBENTRY_SCREEN, title=f"S{i}", unique_id=None
            )
            for i, s in enumerate(screens, 1)
        ],
    )
    entry.add_to_hass(hass)
    return entry


async def advance(
    hass: HomeAssistant, freezer: FrozenDateTimeFactory, seconds: float
) -> None:
    freezer.tick(seconds)
    async_fire_time_changed(hass)
    await hass.async_block_till_done()
    await asyncio.sleep(0)


def set_value(hass: HomeAssistant, entity: str, state: str, unit: str = "kW") -> None:
    hass.states.async_set(entity, state, {"unit_of_measurement": unit})


@pytest.fixture
def writer() -> FakeWriter:
    return FakeWriter()


async def start(
    hass: HomeAssistant,
    freezer: FrozenDateTimeFactory,
    writer: FakeWriter,
    options: dict[str, Any] | None = None,
    screens: tuple[dict[str, Any], ...] = (),
    first_tick: bool = True,
):
    """Create and start a scheduler; by default run its first tick."""
    entry = make_entry(hass, options, screens)
    scheduler = Scheduler(hass, entry, writer)
    await scheduler.async_start()
    if first_tick:
        await advance(hass, freezer, RELOAD_DELAY)
    return scheduler


@pytest.fixture
async def stop_all(hass: HomeAssistant):
    """Stop every scheduler a test created."""
    created: list[Scheduler] = []
    yield created
    for scheduler in created:
        await scheduler.async_stop()


@pytest.fixture
def run(hass, freezer, writer, stop_all):
    async def _run(options=None, screens=(), first_tick=True) -> Scheduler:
        scheduler = await start(hass, freezer, writer, options, screens, first_tick)
        stop_all.append(scheduler)
        return scheduler

    return _run


# ---- pure helpers ---------------------------------------------------------


@pytest.mark.parametrize(
    ("now", "start", "end", "expected"),
    [
        ("23:00", "22:00", "06:00", True),
        ("05:59", "22:00", "06:00", True),
        ("06:00", "22:00", "06:00", False),
        ("12:00", "22:00", "06:00", False),
        ("12:00", "08:00", "17:00", True),
        ("12:00", "08:00:00", "17:00:00", True),
        ("12:00", "10:00", "10:00", False),
        ("12:00", None, "17:00", False),
        ("12:00", "08:00", None, False),
    ],
)
def test_in_quiet_hours(now, start, end, expected) -> None:
    assert in_quiet_hours(datetime.time.fromisoformat(now), start, end) is expected


def test_estimate_balanced() -> None:
    screens = [screen("sensor.a"), screen("sensor.b"), screen("sensor.c")]
    with_presence = {**default_options(), CONF_PRESENCE_ENTITY: "binary_sensor.p"}
    assert estimate_updates_per_hour(with_presence, screens) == (7.5, 20.0)
    assert estimate_updates_per_hour(default_options(), screens) == (7.5, 7.5)


def test_estimate_single_mode() -> None:
    options = {**default_options(), CONF_MODE: MODE_SINGLE}
    assert estimate_updates_per_hour(options, [screen("sensor.a")]) == (7.5, 7.5)
    with_presence = {**options, CONF_PRESENCE_ENTITY: "binary_sensor.p"}
    assert estimate_updates_per_hour(with_presence, [screen("sensor.a")]) == (7.5, 20.0)


def test_estimate_no_screens() -> None:
    assert estimate_updates_per_hour(default_options(), []) == (0.0, 0.0)
    single = {**default_options(), CONF_MODE: MODE_SINGLE}
    disabled = [screen("sensor.a", **{CONF_SCREEN_ENABLED: False})]
    assert estimate_updates_per_hour(single, disabled) == (0.0, 0.0)


def test_estimate_builtin_slot() -> None:
    options = {**default_options(), CONF_BUILTIN_IN_ROTATION: True}
    # (480 + 120) seconds for 2 slots -> 12 per hour
    assert estimate_updates_per_hour(options, [screen("sensor.a")]) == (12.0, 12.0)
    assert estimate_updates_per_hour(options, []) == (30.0, 30.0)


# ---- rotation -------------------------------------------------------------


async def test_first_tick_after_reload_delay(hass, freezer, writer, run) -> None:
    set_value(hass, "sensor.a", "5")
    s1 = screen("sensor.a")
    scheduler = await run(first_tick=False, screens=(s1,))
    assert writer.writes == []
    await advance(hass, freezer, RELOAD_DELAY)
    expected = render(s1, {"sensor.a": SourceValue("5", "kW")}, VALIDITY_PERMANENT)
    assert writer.writes == [build_ext_frame(expected)]
    assert scheduler.current_slot is not None
    assert scheduler.current_screen_name == "S1"
    assert scheduler.reachable is True
    assert scheduler.last_success is not None


async def test_first_tick_waits_for_ha_start(hass, freezer, writer, run) -> None:
    set_value(hass, "sensor.a", "5")
    hass.set_state(CoreState.starting)
    await run(first_tick=False, screens=(screen("sensor.a"),))
    await advance(hass, freezer, RELOAD_DELAY)
    assert writer.writes == []
    hass.set_state(CoreState.running)
    hass.bus.async_fire("homeassistant_started")
    await hass.async_block_till_done()
    await advance(hass, freezer, START_DELAY)
    assert bigs(writer) == [5.0]


async def test_rotation_follows_position_then_wraps(hass, freezer, writer, run) -> None:
    for entity, value in (("sensor.a", "1"), ("sensor.b", "2")):
        set_value(hass, entity, value)
    await run(screens=(screen("sensor.a", 2), screen("sensor.b", 1)))
    await advance(hass, freezer, DWELL)
    await advance(hass, freezer, DWELL)
    assert bigs(writer) == [2.0, 1.0, 2.0]


async def test_unchanged_value_is_not_rewritten(hass, freezer, writer, run) -> None:
    set_value(hass, "sensor.a", "5")
    await run(screens=(screen("sensor.a"),))
    await advance(hass, freezer, DWELL)
    assert bigs(writer) == [5.0]
    set_value(hass, "sensor.a", "6")
    await advance(hass, freezer, DWELL)
    assert bigs(writer) == [5.0, 6.0]


async def test_unavailable_screen_is_skipped(hass, freezer, writer, run) -> None:
    for entity, value in (
        ("sensor.a", "1"),
        ("sensor.b", "unavailable"),
        ("sensor.c", "3"),
    ):
        set_value(hass, entity, value)
    await run(
        screens=(screen("sensor.a", 1), screen("sensor.b", 2), screen("sensor.c", 3))
    )
    for _ in range(3):
        await advance(hass, freezer, DWELL)
    assert bigs(writer) == [1.0, 3.0, 1.0, 3.0]


async def test_all_unavailable_writes_nothing_and_keeps_ticking(
    hass, freezer, writer, run
) -> None:
    set_value(hass, "sensor.a", "unavailable")
    await run(screens=(screen("sensor.a"),))
    assert writer.writes == []
    await advance(hass, freezer, DWELL)
    assert writer.writes == []
    set_value(hass, "sensor.a", "7")
    await advance(hass, freezer, DWELL)
    assert bigs(writer) == [7.0]


async def test_no_screens_writes_nothing(hass, freezer, writer, run) -> None:
    scheduler = await run()
    await advance(hass, freezer, DWELL)
    assert writer.writes == []
    assert scheduler.current_slot is None
    assert scheduler.current_screen_name is None


async def test_builtin_slot_in_rotation(hass, freezer, writer, run) -> None:
    for entity, value in (("sensor.a", "1"), ("sensor.b", "2")):
        set_value(hass, entity, value)
    options = {CONF_BUILTIN_IN_ROTATION: True}
    await run(options, screens=(screen("sensor.a", 1), screen("sensor.b", 2)))
    await advance(hass, freezer, DWELL)
    await advance(hass, freezer, DWELL)  # builtin shown
    await advance(hass, freezer, 120)  # builtin dwell
    assert [decode(w)[2] for w in writer.writes] == [
        VALIDITY_PERMANENT,
        VALIDITY_PERMANENT,
        VALIDITY_BUILTIN,
        VALIDITY_PERMANENT,
    ]
    assert bigs(writer) == [1.0, 2.0, 0.0, 1.0]


async def test_presence_changes_dwell(hass, freezer, writer, run) -> None:
    for entity, value in (("sensor.a", "1"), ("sensor.b", "2")):
        set_value(hass, entity, value)
    hass.states.async_set("binary_sensor.p", "on")
    options = {CONF_PRESENCE_ENTITY: "binary_sensor.p"}
    await run(options, screens=(screen("sensor.a", 1), screen("sensor.b", 2)))
    assert bigs(writer) == [1.0]
    await advance(hass, freezer, DWELL_PRESENT)
    assert bigs(writer) == [1.0, 2.0]

    hass.states.async_set("binary_sensor.p", "off")  # t = 182 s
    for expected in (1.0, 2.0, 1.0):  # t = 362, 542, 722: within 10 min of "off"
        await advance(hass, freezer, DWELL_PRESENT)
        assert bigs(writer)[-1] == expected
    await advance(hass, freezer, DWELL_PRESENT)  # t = 902: the linger is over
    assert bigs(writer)[-1] == 2.0
    count = len(writer.writes)
    await advance(hass, freezer, DWELL_PRESENT)  # normal dwell: nothing yet
    assert len(writer.writes) == count
    await advance(hass, freezer, DWELL - DWELL_PRESENT)
    assert len(writer.writes) == count + 1


async def test_presence_arrival_shortens_pending_tick(
    hass, freezer, writer, run
) -> None:
    for entity, value in (("sensor.a", "1"), ("sensor.b", "2")):
        set_value(hass, entity, value)
    hass.states.async_set("binary_sensor.p", "off")
    options = {CONF_PRESENCE_ENTITY: "binary_sensor.p"}
    await run(options, screens=(screen("sensor.a", 1), screen("sensor.b", 2)))
    await advance(hass, freezer, 200)
    hass.states.async_set("binary_sensor.p", "on")
    await hass.async_block_till_done()
    await advance(hass, freezer, 0)
    assert bigs(writer) == [1.0, 2.0]


async def test_jump_shows_screen_now(hass, freezer, writer, run) -> None:
    set_value(hass, "sensor.a", "10")
    set_value(hass, "sensor.b", "2")
    screens = (
        screen("sensor.a", 1, **{CONF_JUMP_DELTA: 1}),
        screen("sensor.b", 2),
    )
    await run(screens=screens)
    await advance(hass, freezer, DWELL)  # screen 2 is up
    assert bigs(writer) == [10.0, 2.0]
    await advance(hass, freezer, MIN_WRITE_GAP + 1)
    set_value(hass, "sensor.a", "12")
    await hass.async_block_till_done()
    await asyncio.sleep(0)
    assert bigs(writer) == [10.0, 2.0, 12.0]
    await advance(hass, freezer, DWELL)  # rotation continues after the jumped screen
    assert bigs(writer) == [10.0, 2.0, 12.0, 2.0]


async def test_jump_within_gap_is_ignored(hass, freezer, writer, run) -> None:
    set_value(hass, "sensor.a", "10")
    set_value(hass, "sensor.b", "2")
    screens = (
        screen("sensor.a", 1, **{CONF_JUMP_DELTA: 1}),
        screen("sensor.b", 2),
    )
    await run(screens=screens)
    await advance(hass, freezer, DWELL)
    await advance(hass, freezer, MIN_WRITE_GAP - 10)
    set_value(hass, "sensor.a", "12")
    await hass.async_block_till_done()
    await asyncio.sleep(0)
    assert bigs(writer) == [10.0, 2.0]


async def test_small_change_below_delta_does_not_jump(
    hass, freezer, writer, run
) -> None:
    set_value(hass, "sensor.a", "10")
    set_value(hass, "sensor.b", "2")
    screens = (
        screen("sensor.a", 1, **{CONF_JUMP_DELTA: 5}),
        screen("sensor.b", 2),
    )
    await run(screens=screens)
    await advance(hass, freezer, DWELL)
    await advance(hass, freezer, MIN_WRITE_GAP + 1)
    set_value(hass, "sensor.a", "12")
    await hass.async_block_till_done()
    await asyncio.sleep(0)
    assert bigs(writer) == [10.0, 2.0]


# ---- activity -------------------------------------------------------------


async def test_quiet_hours_write_inactive_frame_once(
    hass, freezer, writer, run
) -> None:
    await hass.config.async_set_time_zone("UTC")
    freezer.move_to("2026-10-02 21:59:00+00:00")
    set_value(hass, "sensor.a", "5")
    options = {CONF_QUIET_START: "22:00", CONF_QUIET_END: "06:00"}
    scheduler = await run(options, screens=(screen("sensor.a"),))
    assert bigs(writer) == [5.0]
    await advance(hass, freezer, ACTIVITY_CHECK_INTERVAL)  # 22:00:02, quiet
    await advance(hass, freezer, MIN_WRITE_GAP)
    assert scheduler.active is False
    assert len(writer.writes) == 2
    assert decode(writer.writes[-1])[2] == VALIDITY_BUILTIN
    await advance(hass, freezer, 3 * DWELL)
    assert len(writer.writes) == 2


async def test_quiet_hours_end_resumes_within_check_interval(
    hass, freezer, writer, run
) -> None:
    await hass.config.async_set_time_zone("UTC")
    freezer.move_to("2026-10-02 05:58:30+00:00")
    set_value(hass, "sensor.a", "5")
    options = {CONF_QUIET_START: "22:00", CONF_QUIET_END: "06:00"}
    scheduler = await run(options, screens=(screen("sensor.a"),))
    assert decode(writer.writes[-1])[2] == VALIDITY_BUILTIN
    # quiet ends at 06:00:00; the next activity check is at 06:00:30
    await advance(hass, freezer, 2 * ACTIVITY_CHECK_INTERVAL - RELOAD_DELAY)
    await advance(hass, freezer, 0)
    assert scheduler.active is True
    assert bigs(writer)[-1] == 5.0


async def test_zeros_inactive_display(hass, freezer, writer, run) -> None:
    set_value(hass, "sensor.a", "5")
    options = {CONF_ENABLED: False, CONF_INACTIVE_DISPLAY: INACTIVE_ZEROS}
    await run(options, screens=(screen("sensor.a", **{CONF_UNIT: "deg_c"}),))
    assert len(writer.writes) == 1
    big, small, validity, flags = decode(writer.writes[0])
    assert (big, small, validity) == (0.0, 0, VALIDITY_PERMANENT)
    assert flags >> 5 == 5  # deg_c


async def test_leave_inactive_display_writes_nothing(
    hass, freezer, writer, run
) -> None:
    set_value(hass, "sensor.a", "5")
    options = {CONF_ENABLED: False, CONF_INACTIVE_DISPLAY: INACTIVE_LEAVE}
    await run(options, screens=(screen("sensor.a"),))
    await advance(hass, freezer, DWELL)
    assert writer.writes == []


async def test_active_entity(hass, freezer, writer, run) -> None:
    set_value(hass, "sensor.a", "5")
    options = {CONF_ACTIVE_ENTITY: "binary_sensor.sun_up"}
    scheduler = await run(options, screens=(screen("sensor.a"),), first_tick=False)
    assert scheduler.active is False  # missing counts as inactive
    hass.states.async_set("binary_sensor.sun_up", "off")
    await hass.async_block_till_done()
    assert scheduler.active is False
    hass.states.async_set("binary_sensor.sun_up", "unavailable")
    await hass.async_block_till_done()
    assert scheduler.active is False
    hass.states.async_set("binary_sensor.sun_up", "on")
    await hass.async_block_till_done()
    assert scheduler.active is True
    hass.states.async_set("binary_sensor.sun_up", "off")
    await hass.async_block_till_done()
    assert scheduler.active is False


# ---- single mode and validity --------------------------------------------


async def test_single_mode_validity_and_refresh(hass, freezer, writer, run) -> None:
    set_value(hass, "sensor.a", "5")
    set_value(hass, "sensor.b", "9")
    options = {CONF_MODE: MODE_SINGLE}
    await run(options, screens=(screen("sensor.a", 1), screen("sensor.b", 2)))
    assert [decode(w)[2] for w in writer.writes] == [1800]
    await advance(hass, freezer, DWELL)  # 480 s, unchanged
    await advance(hass, freezer, DWELL)  # 960 s, unchanged
    assert len(writer.writes) == 1
    await advance(hass, freezer, DWELL)  # 1440 s > 1200 s: refresh
    assert bigs(writer) == [5.0, 5.0]
    set_value(hass, "sensor.a", "6")
    await advance(hass, freezer, DWELL)
    assert bigs(writer) == [5.0, 5.0, 6.0]


async def test_single_mode_unavailable_keeps_ticking(
    hass, freezer, writer, run
) -> None:
    set_value(hass, "sensor.a", "unavailable")
    options = {CONF_MODE: MODE_SINGLE}
    await run(options, screens=(screen("sensor.a"),))
    set_value(hass, "sensor.a", "4")
    await advance(hass, freezer, DWELL)
    assert bigs(writer) == [4.0]


async def test_single_mode_without_screens(hass, freezer, writer, run) -> None:
    await run({CONF_MODE: MODE_SINGLE})
    await advance(hass, freezer, DWELL)
    assert writer.writes == []


async def test_long_screen_dwell_raises_validity(hass, freezer, writer, run) -> None:
    set_value(hass, "sensor.a", "5")
    options = {CONF_MODE: MODE_SINGLE}
    await run(options, screens=(screen("sensor.a", **{"seconds": 900}),))
    assert decode(writer.writes[0])[2] == 2700


async def test_alternate_uses_finite_validity(hass, freezer, writer, run) -> None:
    set_value(hass, "sensor.a", "5")
    options = {CONF_ON_HA_STOP: HA_STOP_ALTERNATE}
    await run(options, screens=(screen("sensor.a"),))
    assert decode(writer.writes[0])[2] == 1800


# ---- failures -------------------------------------------------------------


async def test_failures_create_and_clear_issue(
    hass, freezer, writer, run, caplog
) -> None:
    caplog.set_level(logging.INFO)
    set_value(hass, "sensor.a", "1")
    scheduler = await run(screens=(screen("sensor.a"),))
    issue_id = f"{ISSUE_UNREACHABLE}_{scheduler.entry.entry_id}"
    registry = ir.async_get(hass)
    writer.fail = DeviceUnreachable("not seen")
    for step in range(FAILURES_FOR_ISSUE):
        assert registry.async_get_issue(DOMAIN, issue_id) is None
        set_value(hass, "sensor.a", str(step + 10))
        await advance(hass, freezer, DWELL)
    assert registry.async_get_issue(DOMAIN, issue_id) is not None
    assert scheduler.reachable is False
    assert scheduler.last_error == "not seen"
    warnings = [
        r
        for r in caplog.records
        if r.levelno == logging.WARNING and r.name.endswith("scheduler")
    ]
    assert len(warnings) == 1
    assert "ADDR" not in caplog.text and ADDR not in caplog.text

    writer.fail = None
    set_value(hass, "sensor.a", "99")
    await advance(hass, freezer, DWELL)
    assert registry.async_get_issue(DOMAIN, issue_id) is None
    assert scheduler.reachable is True
    assert scheduler.last_error is None
    assert caplog.text.count("back online") == 1


async def test_failed_write_is_not_retried_in_a_burst(
    hass, freezer, writer, run
) -> None:
    set_value(hass, "sensor.a", "1")
    writer.fail = WriteFailed("boom")
    calls = 0
    real = writer.async_write

    async def counting(address, frames):
        nonlocal calls
        calls += 1
        await real(address, frames)

    writer.async_write = counting  # type: ignore[method-assign]
    scheduler = await run(screens=(screen("sensor.a"),))
    assert calls == 1
    await advance(hass, freezer, DWELL - 1)
    assert calls == 1
    assert scheduler.updates_last_hour == 0


async def test_unexpected_exception_is_contained(
    hass, freezer, writer, run, caplog
) -> None:
    set_value(hass, "sensor.a", "1")
    writer.fail = RuntimeError("weird")
    scheduler = await run(screens=(screen("sensor.a"),))
    assert scheduler.reachable is False
    assert "Unexpected error" in caplog.text


async def test_outage_over_an_hour_creates_issue(hass, freezer, writer, run) -> None:
    set_value(hass, "sensor.a", "1")
    scheduler = await run(first_tick=False, screens=(screen("sensor.a"),))
    issue_id = f"{ISSUE_UNREACHABLE}_{scheduler.entry.entry_id}"
    registry = ir.async_get(hass)
    writer.fail = DeviceUnreachable("gone")
    await advance(hass, freezer, RELOAD_DELAY)  # the one and only failure, t = 2 s
    assert scheduler._failures == 1
    set_value(hass, "sensor.a", "unavailable")  # no more write attempts
    for _ in range(59):  # t = 3542 s: 3540 s of outage
        await advance(hass, freezer, ACTIVITY_CHECK_INTERVAL)
    assert registry.async_get_issue(DOMAIN, issue_id) is None
    await advance(hass, freezer, ACTIVITY_CHECK_INTERVAL)  # t = 3602 s: 3600 s
    assert scheduler._failures < FAILURES_FOR_ISSUE
    assert registry.async_get_issue(DOMAIN, issue_id) is not None


async def test_outage_clock_pauses_while_inactive(hass, freezer, writer, run) -> None:
    await hass.config.async_set_time_zone("UTC")
    freezer.move_to("2026-10-02 21:57:58+00:00")
    set_value(hass, "sensor.a", "1")
    options = {
        CONF_QUIET_START: "22:00",
        CONF_QUIET_END: "06:00",
        CONF_INACTIVE_DISPLAY: INACTIVE_LEAVE,
    }
    writer.fail = DeviceUnreachable("gone")
    with patch(
        "custom_components.lcd_ticker.scheduler.ir.async_create_issue"
    ) as create_issue:
        scheduler = await run(options, screens=(screen("sensor.a"),))
        assert scheduler._failures == 1  # 21:58:00
        writer.fail = None  # the device is fine again at resume
        for _ in range(8 * 60 + 2):  # to 06:00:00
            await advance(hass, freezer, ACTIVITY_CHECK_INTERVAL)
        assert scheduler.active is True
        assert create_issue.call_count == 0  # not even on the resume check
        await advance(hass, freezer, 0)  # the resume write
        await advance(hass, freezer, MIN_WRITE_GAP)
        assert bigs(writer) == [1.0]
        assert scheduler.reachable is True
        assert create_issue.call_count == 0


async def test_no_issue_without_failures(hass, freezer, writer, run) -> None:
    set_value(hass, "sensor.a", "1")
    scheduler = await run(screens=(screen("sensor.a"),))
    issue_id = f"{ISSUE_UNREACHABLE}_{scheduler.entry.entry_id}"
    registry = ir.async_get(hass)
    for _ in range(2 * 3600 // ACTIVITY_CHECK_INTERVAL):
        await advance(hass, freezer, ACTIVITY_CHECK_INTERVAL)
    assert registry.async_get_issue(DOMAIN, issue_id) is None


async def test_no_issue_for_unavailable_source(hass, freezer, writer, run) -> None:
    set_value(hass, "sensor.a", "unavailable")
    scheduler = await run(screens=(screen("sensor.a"),))
    issue_id = f"{ISSUE_UNREACHABLE}_{scheduler.entry.entry_id}"
    for _ in range(2 * 3600 // ACTIVITY_CHECK_INTERVAL):
        await advance(hass, freezer, ACTIVITY_CHECK_INTERVAL)
    assert ir.async_get(hass).async_get_issue(DOMAIN, issue_id) is None


# ---- options and actions ---------------------------------------------------


async def test_apply_options_new_speed_does_not_write_now(
    hass, freezer, writer, run
) -> None:
    set_value(hass, "sensor.a", "1")
    set_value(hass, "sensor.b", "2")
    scheduler = await run(screens=(screen("sensor.a", 1), screen("sensor.b", 2)))
    await advance(hass, freezer, 100)
    scheduler.apply_options({**scheduler.entry.options, CONF_SECONDS: 600})
    await advance(hass, freezer, 0)
    assert bigs(writer) == [1.0]
    await advance(hass, freezer, 380)  # old dwell would have fired by now
    assert bigs(writer) == [1.0]
    await advance(hass, freezer, 120)  # 600 s after the last tick
    assert bigs(writer) == [1.0, 2.0]


async def test_apply_options_shorter_speed_fires_early(
    hass, freezer, writer, run
) -> None:
    set_value(hass, "sensor.a", "1")
    set_value(hass, "sensor.b", "2")
    scheduler = await run(screens=(screen("sensor.a", 1), screen("sensor.b", 2)))
    await advance(hass, freezer, 100)
    scheduler.apply_options({**scheduler.entry.options, CONF_SECONDS: 120})
    await advance(hass, freezer, 20)
    assert bigs(writer) == [1.0, 2.0]


async def test_apply_options_mode_change_writes_after_delay(
    hass, freezer, writer, run
) -> None:
    set_value(hass, "sensor.a", "1")
    scheduler = await run(screens=(screen("sensor.a"),))
    await advance(hass, freezer, 10)
    scheduler.apply_options({**scheduler.entry.options, CONF_MODE: MODE_SINGLE})
    assert len(writer.writes) == 1
    await advance(hass, freezer, MIN_WRITE_GAP)
    assert len(writer.writes) == 2
    assert decode(writer.writes[-1])[2] == 1800


async def test_apply_options_mode_change_during_write_is_not_lost(
    hass, freezer, writer, run
) -> None:
    """Switching to rotating while a single-mode write is in flight applies soon."""
    set_value(hass, "sensor.a", "1")
    release = asyncio.Event()
    record = writer.async_write

    async def slow_write(address: str, frames: Any) -> None:
        await release.wait()
        await record(address, frames)

    writer.async_write = slow_write
    scheduler = await run(
        {CONF_MODE: MODE_SINGLE}, (screen("sensor.a"),), first_tick=False
    )
    freezer.tick(RELOAD_DELAY)
    async_fire_time_changed(hass)
    await asyncio.sleep(0)
    await asyncio.sleep(0)
    assert scheduler._lock.locked()  # the first write is in flight
    scheduler.apply_options({**scheduler.entry.options, CONF_MODE: "rotating"})
    release.set()
    await hass.async_block_till_done()
    assert [decode(w)[2] for w in writer.writes] == [1800]
    await advance(hass, freezer, MIN_WRITE_GAP)
    assert [decode(w)[2] for w in writer.writes] == [1800, VALIDITY_PERMANENT]


async def test_apply_options_enabling_resumes(hass, freezer, writer, run) -> None:
    set_value(hass, "sensor.a", "1")
    options = {CONF_ENABLED: False, CONF_INACTIVE_DISPLAY: INACTIVE_LEAVE}
    scheduler = await run(options, screens=(screen("sensor.a"),))
    scheduler.apply_options({**scheduler.entry.options, CONF_ENABLED: True})
    assert scheduler.active is True
    await advance(hass, freezer, 0)
    assert bigs(writer) == [1.0]


async def test_show_now(hass, freezer, writer, run) -> None:
    set_value(hass, "sensor.a", "1")
    set_value(hass, "sensor.b", "2")
    scheduler = await run(screens=(screen("sensor.a", 1), screen("sensor.b", 2)))
    slot_b = next(s for s, n in scheduler.slot_names().items() if n == "S2")
    await scheduler.async_show_now(slot_b)
    assert bigs(writer) == [1.0, 2.0]
    assert scheduler.current_slot == slot_b
    await advance(hass, freezer, DWELL)
    assert bigs(writer) == [1.0, 2.0, 1.0]
    with pytest.raises(ValueError):
        await scheduler.async_show_now("nope")


async def test_show_now_while_inactive(hass, freezer, writer, run) -> None:
    set_value(hass, "sensor.a", "1")
    options = {CONF_ENABLED: False, CONF_INACTIVE_DISPLAY: INACTIVE_LEAVE}
    scheduler = await run(options, screens=(screen("sensor.a"),))
    await scheduler.async_show_now(next(iter(scheduler.slot_names())))
    assert bigs(writer) == [1.0]
    await advance(hass, freezer, DWELL)
    assert bigs(writer) == [1.0]


async def test_refresh_rewrites_unchanged_frame(hass, freezer, writer, run) -> None:
    set_value(hass, "sensor.a", "1")
    scheduler = await run(screens=(screen("sensor.a"),))
    await scheduler.async_refresh()
    assert bigs(writer) == [1.0, 1.0]


async def test_refresh_while_inactive_writes_inactive_frame(
    hass, freezer, writer, run
) -> None:
    set_value(hass, "sensor.a", "1")
    scheduler = await run({CONF_ENABLED: False}, screens=(screen("sensor.a"),))
    await scheduler.async_refresh()
    assert len(writer.writes) == 2


async def test_invalidate_forces_next_write(hass, freezer, writer, run) -> None:
    set_value(hass, "sensor.a", "1")
    scheduler = await run(screens=(screen("sensor.a"),))
    scheduler.invalidate()
    await advance(hass, freezer, DWELL)
    assert bigs(writer) == [1.0, 1.0]


def test_slot_names_are_unique(hass: HomeAssistant) -> None:
    entry = MockConfigEntry(
        domain=DOMAIN,
        title="Kitchen",
        data={CONF_ADDRESS: ADDR},
        options={**default_options(), CONF_BUILTIN_IN_ROTATION: True},
        subentries_data=[
            ConfigSubentryData(
                data=screen("sensor.a", i),
                subentry_type=SUBENTRY_SCREEN,
                title="Temp",
                unique_id=None,
            )
            for i in (1, 2, 3)
        ],
    )
    entry.add_to_hass(hass)
    names = list(Scheduler(hass, entry, FakeWriter()).slot_names().values())
    assert names == ["Temp", "Temp (2)", "Temp (3)", BUILTIN_NAME]


async def test_stop_cancels_everything(hass, freezer, writer, run) -> None:
    set_value(hass, "sensor.a", "1")
    scheduler = await run(screens=(screen("sensor.a"),))
    await scheduler.async_stop()
    set_value(hass, "sensor.a", "2")
    await advance(hass, freezer, 5 * DWELL)
    assert bigs(writer) == [1.0]


async def test_diagnostics_and_counters(hass, freezer, writer, run) -> None:
    set_value(hass, "sensor.a", "1")
    scheduler = await run(screens=(screen("sensor.a"),))
    info = scheduler.diagnostics()
    assert info["active"] is True
    assert info["mode"] == "rotating"
    assert info["slots"] == ["S1"]
    assert info["last_payload"] == writer.writes[0].hex()
    assert info["failures"] == 0
    assert info["updates_last_hour"] == 1
    assert ADDR not in str(info)
    assert scheduler.estimated_updates_per_hour == 7.5
    await advance(hass, freezer, 3601)
    assert scheduler.updates_last_hour == 0


async def test_update_signal_is_sent(hass, freezer, writer, run) -> None:
    set_value(hass, "sensor.a", "1")
    scheduler = await run(first_tick=False, screens=(screen("sensor.a"),))
    calls: list[int] = []
    async_dispatcher_connect(
        hass, signal_update(scheduler.entry.entry_id), lambda: calls.append(1)
    )
    await advance(hass, freezer, RELOAD_DELAY)
    assert calls


async def test_writes_do_not_interleave(hass, freezer) -> None:
    events: list[str] = []

    class SlowWriter:
        async def async_write(self, address, frames):
            events.append("enter")
            for _ in range(3):  # real sleeping is not possible with frozen time
                await asyncio.sleep(0)
            events.append("exit")

    set_value(hass, "sensor.a", "1")
    entry = make_entry(hass, screens=(screen("sensor.a"),))
    scheduler = Scheduler(hass, entry, SlowWriter())
    scheduler._active = True
    await asyncio.gather(scheduler.async_refresh(), scheduler.async_refresh())
    assert events == ["enter", "exit", "enter", "exit"]
    await scheduler.async_stop()


async def test_state_without_unit_and_missing_entity(
    hass, freezer, writer, run
) -> None:
    hass.states.async_set("sensor.a", "3")
    await run(screens=(screen("sensor.a"), screen("sensor.missing", 2)))
    await advance(hass, freezer, DWELL)
    assert bigs(writer) == [3.0]


async def test_alternate_refreshes_finite_frame_after_two_thirds(
    hass, freezer, writer, run
) -> None:
    set_value(hass, "sensor.a", "5")
    options = {CONF_ON_HA_STOP: HA_STOP_ALTERNATE}
    await run(options, screens=(screen("sensor.a"),))
    await advance(hass, freezer, DWELL)  # 480 s
    await advance(hass, freezer, DWELL)  # 960 s
    assert len(writer.writes) == 1
    await advance(hass, freezer, DWELL)  # 1440 s > 1200 s
    assert len(writer.writes) == 2


async def test_permanent_frame_is_never_refreshed(hass, freezer, writer, run) -> None:
    set_value(hass, "sensor.a", "5")
    await run(screens=(screen("sensor.a"),))
    for _ in range(10):
        await advance(hass, freezer, DWELL)
    assert len(writer.writes) == 1


async def test_single_mode_two_changes_in_one_dwell_write_once(
    hass, freezer, writer, run
) -> None:
    set_value(hass, "sensor.a", "5")
    await run({CONF_MODE: MODE_SINGLE}, screens=(screen("sensor.a"),))
    set_value(hass, "sensor.a", "6")
    set_value(hass, "sensor.a", "7")
    await advance(hass, freezer, DWELL)
    assert bigs(writer) == [5.0, 7.0]


async def test_tick_does_not_overwrite_schedule_made_during_write(
    hass, freezer
) -> None:
    await hass.config.async_set_time_zone("UTC")
    freezer.move_to("2026-10-02 21:50:00+00:00")
    gate = asyncio.Event()
    written: list[bytes] = []

    class SlowWriter:
        async def async_write(self, address, frames):
            if len(written) == 1:  # block the second (active) write
                await gate.wait()
            written.extend(frames)

    set_value(hass, "sensor.a", "1")
    set_value(hass, "sensor.b", "2")
    options = {CONF_QUIET_START: "22:00", CONF_QUIET_END: "06:00"}
    entry = make_entry(hass, options, (screen("sensor.a", 1), screen("sensor.b", 2)))
    scheduler = Scheduler(hass, entry, SlowWriter())
    await scheduler.async_start()
    await advance(hass, freezer, RELOAD_DELAY)  # 21:50:02 writes screen 1
    assert len(written) == 1
    await advance(hass, freezer, DWELL)  # 21:58:02: the tick blocks in its write
    assert len(written) == 1
    await advance(hass, freezer, 120)  # 22:00:02: quiet hours begin mid-write
    assert scheduler.active is False
    gate.set()
    for _ in range(3):
        await asyncio.sleep(0)
    assert len(written) == 2  # the active frame finished
    await advance(hass, freezer, 0)  # the check already scheduled the inactive write
    assert decode(written[-1])[2] == VALIDITY_BUILTIN
    await scheduler.async_stop()


async def test_show_now_keeps_screen_for_queued_tick(hass, freezer) -> None:
    gate = asyncio.Event()
    written: list[bytes] = []

    class GatedWriter:
        block = False

        async def async_write(self, address, frames):
            if self.block:
                await gate.wait()
            written.extend(frames)

    writer = GatedWriter()
    set_value(hass, "sensor.a", "1")
    set_value(hass, "sensor.b", "2")
    entry = make_entry(hass, screens=(screen("sensor.a", 1), screen("sensor.b", 2)))
    scheduler = Scheduler(hass, entry, writer)
    await scheduler.async_start()
    await advance(hass, freezer, RELOAD_DELAY)
    slot_b = next(s for s, n in scheduler.slot_names().items() if n == "S2")
    await advance(hass, freezer, DWELL - 2)  # the tick is due in 2 s
    writer.block = True
    show = asyncio.create_task(scheduler.async_show_now(slot_b))
    await asyncio.sleep(0)  # show_now holds the lock, waiting in the write
    await advance(hass, freezer, 2)  # the tick fires and queues for the lock
    gate.set()
    await show
    await hass.async_block_till_done()
    await asyncio.sleep(0)
    assert [decode(w)[0] for w in written] == [1.0, 2.0]
    assert scheduler.current_slot == slot_b
    await scheduler.async_stop()


async def test_stop_during_write_creates_no_issue_or_signal(hass, freezer) -> None:
    gate = asyncio.Event()

    class SlowWriter:
        async def async_write(self, address, frames):
            await gate.wait()
            raise DeviceUnreachable("late")

    set_value(hass, "sensor.a", "1")
    entry = make_entry(hass, screens=(screen("sensor.a"),))
    scheduler = Scheduler(hass, entry, SlowWriter())
    scheduler._active = True
    scheduler._failures = FAILURES_FOR_ISSUE
    task = asyncio.create_task(scheduler.async_refresh())
    await asyncio.sleep(0)
    await scheduler.async_stop()
    calls: list[int] = []
    async_dispatcher_connect(
        hass, signal_update(entry.entry_id), lambda: calls.append(1)
    )
    gate.set()
    await task
    issue_id = f"{ISSUE_UNREACHABLE}_{entry.entry_id}"
    assert ir.async_get(hass).async_get_issue(DOMAIN, issue_id) is None
    assert calls == []


# ---- final review fixes ---------------------------------------------------


async def test_render_error_does_not_stop_rotation(
    hass, freezer, writer, run, caplog
) -> None:
    set_value(hass, "sensor.a", "1")
    set_value(hass, "sensor.b", "2")
    real_render = render
    calls = {"n": 0}

    def flaky(data, values, validity):
        calls["n"] += 1
        if calls["n"] == 1:
            raise ArithmeticError("boom")
        return real_render(data, values, validity)

    with patch("custom_components.lcd_ticker.scheduler.render", flaky):
        await run(screens=(screen("sensor.a", 1), screen("sensor.b", 2)))
        assert bigs(writer) == [2.0]  # the broken screen is skipped
        await advance(hass, freezer, DWELL)
    assert bigs(writer) == [2.0, 1.0]
    assert caplog.text.count("unexpected error rendering screen") == 1
    assert "ArithmeticError" in caplog.text


async def test_unexpected_tick_error_still_schedules_next_tick(
    hass, freezer, writer, run, caplog
) -> None:
    set_value(hass, "sensor.a", "1")
    real = Scheduler._tick_rotating
    calls = {"n": 0}

    async def flaky(self, now, force):
        calls["n"] += 1
        if calls["n"] == 1:
            raise RuntimeError("secret AA:BB:CC:DD:EE:FF")
        await real(self, now, force)

    with patch.object(Scheduler, "_tick_rotating", flaky):
        await run(screens=(screen("sensor.a"),))
        assert writer.writes == []
        await advance(hass, freezer, DWELL)
    assert bigs(writer) == [1.0]
    loud = [r for r in caplog.records if r.levelno >= logging.WARNING]
    assert any("RuntimeError" in r.getMessage() for r in loud)
    assert all("AA:BB" not in r.getMessage() and not r.exc_info for r in loud)


async def test_short_screen_seconds_never_write_closer_than_the_gap(
    hass, freezer, writer, run
) -> None:
    set_value(hass, "sensor.a", "1")
    set_value(hass, "sensor.b", "2")
    await run(
        screens=(screen("sensor.a", 1, seconds=30), screen("sensor.b", 2, seconds=30))
    )
    assert bigs(writer) == [1.0]
    await advance(hass, freezer, 30)
    assert bigs(writer) == [1.0]
    await advance(hass, freezer, MIN_WRITE_GAP - 30)
    assert bigs(writer) == [1.0, 2.0]
    await advance(hass, freezer, 30)
    assert bigs(writer) == [1.0, 2.0]
    await advance(hass, freezer, MIN_WRITE_GAP - 30)
    assert bigs(writer) == [1.0, 2.0, 1.0]


async def test_single_mode_short_dwell_respects_the_gap(
    hass, freezer, writer, run
) -> None:
    set_value(hass, "sensor.a", "1")
    await run(
        {CONF_MODE: MODE_SINGLE, CONF_ON_HA_STOP: HA_STOP_ALTERNATE},
        screens=(screen("sensor.a", seconds=30),),
    )
    assert bigs(writer) == [1.0]
    set_value(hass, "sensor.a", "2")
    await advance(hass, freezer, 30)
    assert bigs(writer) == [1.0]
    await advance(hass, freezer, MIN_WRITE_GAP - 30)
    assert bigs(writer) == [1.0, 2.0]


def test_estimate_uses_the_write_gap() -> None:
    screens = [screen("sensor.a", seconds=30), screen("sensor.b", seconds=30)]
    assert estimate_updates_per_hour(default_options(), screens) == (60.0, 60.0)
    fast = {**default_options(), CONF_MODE: MODE_SINGLE, CONF_SECONDS: 30}
    assert estimate_updates_per_hour(fast, [screen("sensor.a")])[0] == 60.0


async def test_no_early_write_before_ha_started(hass, freezer, writer, run) -> None:
    set_value(hass, "sensor.a", "5")
    hass.states.async_set("binary_sensor.act", "off")
    hass.set_state(CoreState.starting)
    options = {CONF_ACTIVE_ENTITY: "binary_sensor.act"}
    scheduler = await run(options, screens=(screen("sensor.a"),), first_tick=False)
    hass.states.async_set("binary_sensor.act", "on")
    await hass.async_block_till_done()
    assert scheduler.active is True
    await advance(hass, freezer, 2 * ACTIVITY_CHECK_INTERVAL)
    assert writer.writes == []
    hass.set_state(CoreState.running)
    hass.bus.async_fire("homeassistant_started")
    await hass.async_block_till_done()
    await advance(hass, freezer, START_DELAY - 1)
    assert writer.writes == []
    await advance(hass, freezer, 1)
    assert bigs(writer) == [5.0]


async def test_failed_inactive_write_is_retried_once(
    hass, freezer, writer, run
) -> None:
    set_value(hass, "sensor.a", "5")
    writer.fail = WriteFailed("nope")
    scheduler = await run({CONF_ENABLED: False}, screens=(screen("sensor.a"),))
    assert scheduler.reachable is False
    writer.fail = None
    await advance(hass, freezer, DWELL)
    assert len(writer.writes) == 1
    assert decode(writer.writes[0])[2] == VALIDITY_BUILTIN
    await advance(hass, freezer, 3 * DWELL)
    assert len(writer.writes) == 1


async def test_failed_inactive_retry_gives_up(hass, freezer, writer, run) -> None:
    set_value(hass, "sensor.a", "5")
    writer.fail = WriteFailed("nope")
    scheduler = await run({CONF_ENABLED: False}, screens=(screen("sensor.a"),))
    await advance(hass, freezer, DWELL)  # the one retry, also fails
    writer.fail = None
    await advance(hass, freezer, 3 * DWELL)
    assert writer.writes == []
    assert scheduler.active is False


async def test_last_error_is_masked_and_truncated(hass, freezer, writer, run) -> None:
    set_value(hass, "sensor.a", "5")
    writer.fail = RuntimeError("dev_AA_BB_CC_DD_EE_FF " + "x" * 400)
    scheduler = await run(screens=(screen("sensor.a"),))
    assert len(scheduler.last_error) == 255
    assert scheduler.last_error.startswith("dev_<address> x")


# ---- show-when conditions and take-over -------------------------------------

SAUNA = "binary_sensor.sauna_heating"
DAY = "schedule.daytime"


def cond(entity: str, **extra: Any) -> dict[str, Any]:
    return {CONF_SHOW_WHEN: entity, **extra}


def set_cond(hass: HomeAssistant, entity: str, state: str) -> None:
    hass.states.async_set(entity, state)


async def settle(hass: HomeAssistant) -> None:
    await hass.async_block_till_done()
    await asyncio.sleep(0)


@pytest.mark.parametrize(
    ("state", "eligible"),
    [
        ("on", True),
        ("home", True),
        ("above_horizon", True),
        ("off", False),
        ("unavailable", False),
        ("unknown", False),
        (None, False),
    ],
)
async def test_eligibility_by_state(hass, freezer, writer, run, state, eligible):
    set_value(hass, "sensor.a", "1")
    set_value(hass, "sensor.b", "2")
    if state is not None:
        set_cond(hass, SAUNA, state)
    scheduler = await run(
        screens=(screen("sensor.a", 1), screen("sensor.b", 2, **cond(SAUNA)))
    )
    await advance(hass, freezer, DWELL)
    assert bigs(writer) == ([1.0, 2.0] if eligible else [1.0])
    assert (len(scheduler.diagnostics()["eligible_slots"]) == 2) is eligible


async def test_disabled_screen_with_condition_on_stays_hidden(
    hass, freezer, writer, run
) -> None:
    set_value(hass, "sensor.a", "1")
    set_value(hass, "sensor.b", "2")
    set_cond(hass, SAUNA, "on")
    await run(
        screens=(
            screen("sensor.a", 1),
            screen("sensor.b", 2, **cond(SAUNA, **{CONF_SCREEN_ENABLED: False})),
        )
    )
    await advance(hass, freezer, DWELL)
    assert bigs(writer) == [1.0]


async def test_takeover_shows_within_write_gap_and_resumes(
    hass, freezer, writer, run
) -> None:
    set_value(hass, "sensor.a", "1")
    set_value(hass, "sensor.b", "2")
    set_value(hass, "sensor.s", "90")
    set_cond(hass, SAUNA, "off")
    options = {CONF_BUILTIN_IN_ROTATION: True}
    await run(
        options,
        screens=(
            screen("sensor.a", 1),
            screen("sensor.b", 2),
            screen("sensor.s", 3, **cond(SAUNA, **{CONF_TAKEOVER: True})),
        ),
    )
    assert bigs(writer) == [1.0]
    await advance(hass, freezer, 20)
    set_cond(hass, SAUNA, "on")
    await settle(hass)
    assert bigs(writer) == [1.0]  # not before the 60 s gap
    await advance(hass, freezer, MIN_WRITE_GAP - 20)
    assert bigs(writer) == [1.0, 90.0]  # long before a dwell
    await advance(hass, freezer, DWELL)  # only take-over screens rotate, no built-in
    await advance(hass, freezer, DWELL)
    assert bigs(writer) == [1.0, 90.0]  # unchanged value is not rewritten
    set_cond(hass, SAUNA, "off")
    await settle(hass)
    await advance(hass, freezer, MIN_WRITE_GAP)
    assert bigs(writer)[-1] == 0.0  # normal rotation: built-in follows the sauna
    await advance(hass, freezer, 120)
    await advance(hass, freezer, DWELL)
    assert bigs(writer)[-3:] == [0.0, 1.0, 2.0]


async def test_takeover_without_condition_does_nothing(hass, freezer, writer, run):
    set_value(hass, "sensor.a", "1")
    set_value(hass, "sensor.b", "2")
    await run(
        screens=(screen("sensor.a", 1), screen("sensor.b", 2, **{CONF_TAKEOVER: True}))
    )
    await advance(hass, freezer, DWELL)
    assert bigs(writer) == [1.0, 2.0]


async def test_takeover_jumps_to_the_screen_not_next(hass, freezer, writer, run):
    for entity, value in (("sensor.a", "1"), ("sensor.b", "2"), ("sensor.s", "90")):
        set_value(hass, entity, value)
    set_cond(hass, SAUNA, "off")
    await run(
        screens=(
            screen("sensor.a", 1),
            screen("sensor.b", 2),
            screen("sensor.s", 3, **cond(SAUNA, **{CONF_TAKEOVER: True})),
        )
    )
    set_cond(hass, SAUNA, "on")
    await settle(hass)
    await advance(hass, freezer, MIN_WRITE_GAP)
    assert bigs(writer) == [1.0, 90.0]  # not 2.0 (the plain next screen)


async def test_current_screen_becoming_ineligible_moves_on(
    hass, freezer, writer, run
) -> None:
    set_value(hass, "sensor.a", "1")
    set_value(hass, "sensor.b", "2")
    set_cond(hass, SAUNA, "on")
    await run(screens=(screen("sensor.a", 1, **cond(SAUNA)), screen("sensor.b", 2)))
    assert bigs(writer) == [1.0]
    await advance(hass, freezer, 10)
    set_cond(hass, SAUNA, "off")
    await settle(hass)
    await advance(hass, freezer, MIN_WRITE_GAP - 10)
    assert bigs(writer) == [1.0, 2.0]


async def test_other_screen_becoming_ineligible_does_not_move_on(
    hass, freezer, writer, run
) -> None:
    set_value(hass, "sensor.a", "1")
    set_value(hass, "sensor.b", "2")
    set_cond(hass, SAUNA, "on")
    await run(screens=(screen("sensor.a", 1), screen("sensor.b", 2, **cond(SAUNA))))
    await advance(hass, freezer, 10)
    set_cond(hass, SAUNA, "off")
    await settle(hass)
    await advance(hass, freezer, MIN_WRITE_GAP)
    assert bigs(writer) == [1.0]


async def test_shrinking_set_never_raises(hass, freezer, writer, run) -> None:
    for i, entity in enumerate(("a", "b", "c", "d"), 1):
        set_value(hass, f"sensor.{entity}", str(i))
    conds = ("binary_sensor.c1", "binary_sensor.c2", "binary_sensor.c3")
    for c in conds:
        set_cond(hass, c, "on")
    scheduler = await run(
        screens=(
            screen("sensor.a", 1),
            screen("sensor.b", 2, **cond(conds[0])),
            screen("sensor.c", 3, **cond(conds[1])),
            screen("sensor.d", 4, **cond(conds[2])),
        )
    )
    await advance(hass, freezer, DWELL)
    await advance(hass, freezer, DWELL)
    await advance(hass, freezer, DWELL)  # d is up, index at the end
    assert bigs(writer) == [1.0, 2.0, 3.0, 4.0]
    for c in conds:
        set_cond(hass, c, "off")
    await settle(hass)
    await advance(hass, freezer, DWELL)
    assert bigs(writer)[-1] == 1.0
    assert scheduler.current_slot is not None
    await advance(hass, freezer, DWELL)
    assert bigs(writer)[-1] == 1.0


async def test_empty_set_writes_nothing_and_keeps_ticking(
    hass, freezer, writer, run
) -> None:
    set_value(hass, "sensor.a", "1")
    set_cond(hass, SAUNA, "on")
    await run(screens=(screen("sensor.a", 1, **cond(SAUNA)),))
    set_cond(hass, SAUNA, "off")
    await settle(hass)
    await advance(hass, freezer, DWELL)
    assert bigs(writer) == [1.0]
    set_cond(hass, SAUNA, "on")
    await settle(hass)
    set_value(hass, "sensor.a", "5")
    await advance(hass, freezer, DWELL)
    assert bigs(writer) == [1.0, 5.0]


@pytest.mark.parametrize("mode_options", [{CONF_MODE: MODE_SINGLE}])
async def test_single_mode_picks_takeover_else_first_eligible(
    hass, freezer, writer, run, mode_options
) -> None:
    for entity, value in (("sensor.a", "1"), ("sensor.b", "2"), ("sensor.s", "90")):
        set_value(hass, entity, value)
    set_cond(hass, DAY, "off")
    set_cond(hass, SAUNA, "off")
    scheduler = await run(
        mode_options,
        screens=(
            screen("sensor.a", 1, **cond(DAY)),
            screen("sensor.b", 2),
            screen("sensor.s", 3, **cond(SAUNA, **{CONF_TAKEOVER: True})),
        ),
    )
    assert bigs(writer) == [2.0]  # first eligible
    set_cond(hass, DAY, "on")
    await advance(hass, freezer, DWELL)
    assert bigs(writer) == [2.0, 1.0]
    set_cond(hass, SAUNA, "on")
    await settle(hass)
    await advance(hass, freezer, MIN_WRITE_GAP)
    assert bigs(writer) == [2.0, 1.0, 90.0]
    assert scheduler.current_screen_name == "S3"


async def test_show_now_of_ineligible_screen_works(hass, freezer, writer, run):
    set_value(hass, "sensor.a", "1")
    set_value(hass, "sensor.b", "2")
    set_cond(hass, SAUNA, "off")
    scheduler = await run(
        screens=(screen("sensor.a", 1), screen("sensor.b", 2, **cond(SAUNA)))
    )
    names = scheduler.slot_names()
    assert list(names.values()) == ["S1", "S2"]  # select still lists every screen
    slot_b = next(s for s, n in names.items() if n == "S2")
    await scheduler.async_show_now(slot_b)
    assert bigs(writer) == [1.0, 2.0]
    await advance(hass, freezer, DWELL)
    assert bigs(writer) == [1.0, 2.0, 1.0]


async def test_users_scenario(hass, freezer, writer, run) -> None:
    set_value(hass, "sensor.home", "21")
    set_value(hass, "sensor.price", "9")
    set_value(hass, "sensor.sauna", "55")
    set_cond(hass, DAY, "off")
    set_cond(hass, SAUNA, "off")
    scheduler = await run(
        screens=(
            screen("sensor.home", 1),
            screen("sensor.price", 2, **cond(DAY)),
            screen("sensor.sauna", 3, **cond(SAUNA, **{CONF_TAKEOVER: True})),
        )
    )
    names = scheduler.diagnostics
    assert names()["eligible_slots"] == ["S1"]  # night, sauna off: only Home
    set_value(hass, "sensor.home", "22")
    await advance(hass, freezer, DWELL)
    assert bigs(writer) == [21.0, 22.0]
    set_cond(hass, DAY, "on")  # day: Home and Price rotate
    await settle(hass)
    assert names()["eligible_slots"] == ["S1", "S2"]
    await advance(hass, freezer, DWELL)
    await advance(hass, freezer, DWELL)
    assert bigs(writer)[2:] == [9.0, 22.0]
    set_cond(hass, SAUNA, "on")  # sauna: only Sauna
    await settle(hass)
    await advance(hass, freezer, MIN_WRITE_GAP)
    assert bigs(writer)[-1] == 55.0
    assert names()["eligible_slots"] == ["S3"]
    set_cond(hass, SAUNA, "off")  # back to Home and Price
    await settle(hass)
    await advance(hass, freezer, MIN_WRITE_GAP)
    assert bigs(writer)[-1] == 22.0
    assert names()["eligible_slots"] == ["S1", "S2"]
    await advance(hass, freezer, DWELL)
    assert bigs(writer)[-1] == 9.0


# ---- fixes from review ------------------------------------------------------


async def test_jump_cannot_interrupt_a_takeover(hass, freezer, writer, run) -> None:
    set_value(hass, "sensor.h", "21")
    set_value(hass, "sensor.s", "90")
    set_cond(hass, SAUNA, "off")
    await run(
        screens=(
            screen("sensor.h", 1, **{CONF_JUMP_DELTA: 1}),
            screen("sensor.s", 2, **cond(SAUNA, **{CONF_TAKEOVER: True})),
        )
    )
    set_cond(hass, SAUNA, "on")
    await settle(hass)
    await advance(hass, freezer, MIN_WRITE_GAP)
    assert bigs(writer) == [21.0, 90.0]
    await advance(hass, freezer, MIN_WRITE_GAP + 1)
    set_value(hass, "sensor.h", "25")
    await settle(hass)
    assert bigs(writer) == [21.0, 90.0]  # Home is not in the rotation now


async def test_screen_with_condition_off_never_jumps(
    hass, freezer, writer, run
) -> None:
    set_value(hass, "sensor.a", "1")
    set_value(hass, "sensor.b", "2")
    set_cond(hass, SAUNA, "on")
    await run(
        screens=(
            screen("sensor.a", 1),
            screen("sensor.b", 2, **cond(SAUNA, **{CONF_JUMP_DELTA: 1})),
        )
    )
    await advance(hass, freezer, DWELL)
    assert bigs(writer) == [1.0, 2.0]
    set_cond(hass, SAUNA, "off")
    await settle(hass)
    await advance(hass, freezer, MIN_WRITE_GAP + 1)
    assert bigs(writer) == [1.0, 2.0, 1.0]  # moved on to A
    await advance(hass, freezer, MIN_WRITE_GAP + 1)
    set_value(hass, "sensor.b", "9")
    await settle(hass)
    assert bigs(writer) == [1.0, 2.0, 1.0]


async def test_refresh_keeps_a_pending_takeover_jump(hass, freezer, writer, run):
    for entity, value in (("sensor.a", "1"), ("sensor.b", "2"), ("sensor.c", "3")):
        set_value(hass, entity, value)
    set_cond(hass, DAY, "on")
    set_cond(hass, SAUNA, "on")
    set_cond(hass, "binary_sensor.third", "off")
    scheduler = await run(
        screens=(
            screen("sensor.a", 1, **cond(DAY, **{CONF_TAKEOVER: True})),
            screen("sensor.b", 2, **cond(SAUNA, **{CONF_TAKEOVER: True})),
            screen(
                "sensor.c",
                3,
                **cond("binary_sensor.third", **{CONF_TAKEOVER: True}),
            ),
        )
    )
    assert bigs(writer) == [1.0]
    await advance(hass, freezer, 20)
    set_cond(hass, "binary_sensor.third", "on")
    await settle(hass)
    await scheduler.async_refresh()  # during the gap
    assert bigs(writer) == [1.0, 1.0]
    await advance(hass, freezer, DWELL)
    assert bigs(writer)[-1] == 3.0  # the jump was kept, not B


async def test_condition_flip_while_inactive_schedules_nothing(
    hass, freezer, writer, run
) -> None:
    await hass.config.async_set_time_zone("UTC")
    freezer.move_to("2026-10-02 21:59:00+00:00")
    set_value(hass, "sensor.a", "1")
    set_value(hass, "sensor.b", "2")
    set_cond(hass, SAUNA, "off")
    options = {CONF_QUIET_START: "22:00", CONF_QUIET_END: "06:00"}
    scheduler = await run(
        options,
        screens=(
            screen("sensor.a", 1),
            screen("sensor.b", 2, **cond(SAUNA, **{CONF_TAKEOVER: True})),
        ),
    )
    await advance(hass, freezer, ACTIVITY_CHECK_INTERVAL)
    await advance(hass, freezer, MIN_WRITE_GAP)
    assert scheduler.active is False
    count = len(writer.writes)
    set_cond(hass, SAUNA, "on")
    await settle(hass)
    assert scheduler._tick_due is None
    await advance(hass, freezer, 3 * DWELL)
    assert len(writer.writes) == count


async def test_diagnostics_eligible_slots_when_no_screens(hass, writer, run):
    scheduler = await run(first_tick=False)
    assert scheduler.diagnostics()["eligible_slots"] == []
