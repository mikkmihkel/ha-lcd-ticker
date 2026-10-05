"""Rotation, pausing, presence, jump, failures and Repairs for one thermometer."""

from __future__ import annotations

import asyncio
from collections import deque
from collections.abc import Callable, Coroutine, Mapping, Sequence
import datetime
import logging
from typing import Any

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import (
    CoreState,
    Event,
    EventStateChangedData,
    HomeAssistant,
    callback,
)
from homeassistant.helpers import issue_registry as ir
from homeassistant.helpers.dispatcher import async_dispatcher_send
from homeassistant.helpers.event import (
    async_track_point_in_utc_time,
    async_track_state_change_event,
    async_track_time_interval,
)
from homeassistant.helpers.start import async_at_started
from homeassistant.util import dt as dt_util

from .ble import BleWriter, DeviceUnreachable, WriteFailed, mask_address
from .const import (
    ACTIVE_STATES,
    ACTIVITY_CHECK_INTERVAL,
    BUILTIN_SLOT,
    CONF_ACTIVE_ENTITY,
    CONF_ADDRESS,
    CONF_BATTERY,
    CONF_BUILTIN_IN_ROTATION,
    CONF_BUILTIN_SECONDS,
    CONF_ENABLED,
    CONF_INACTIVE_DISPLAY,
    CONF_JUMP_DELTA,
    CONF_MODE,
    CONF_ON_HA_STOP,
    CONF_PERCENT,
    CONF_POSITION,
    CONF_PRESENCE_ENTITY,
    CONF_QUIET_END,
    CONF_QUIET_START,
    CONF_SCREEN_ENABLED,
    CONF_SCREEN_SECONDS,
    CONF_SECONDS,
    CONF_SECONDS_PRESENT,
    CONF_SHOW_WHEN,
    CONF_TAKEOVER,
    CONF_UNIT,
    DEFAULT_BUILTIN_SECONDS,
    DOMAIN,
    FAILURES_FOR_ISSUE,
    HA_STOP_FREEZE,
    INACTIVE_BUILTIN,
    INACTIVE_ZEROS,
    ISSUE_UNREACHABLE,
    MAX_FINITE_VALIDITY,
    MIN_FINITE_VALIDITY,
    MIN_WRITE_GAP,
    MODE_ROTATING,
    MODE_SINGLE,
    NO_SUCCESS_FOR_ISSUE,
    PRESENCE_LINGER,
    PRESENT_STATES,
    RELOAD_DELAY,
    START_DELAY,
    SUBENTRY_SCREEN,
    VALIDITY_BUILTIN,
    VALIDITY_PERMANENT,
    signal_update,
)
from .protocol import UNIT_KEYS, DisplayFrame, Unit, build_ext_frame
from .render import SourceValue, render, screen_entity_ids

_LOGGER = logging.getLogger(__name__)

BUILTIN_NAME = "Built-in reading"
LAST_ERROR_MAX = 255


def in_quiet_hours(now: datetime.time, start: str | None, end: str | None) -> bool:
    """True if `now` is inside the quiet window (which may cross midnight)."""
    if start is None or end is None:
        return False
    start_time = datetime.time.fromisoformat(start)
    end_time = datetime.time.fromisoformat(end)
    if start_time == end_time:
        return False
    if start_time < end_time:
        return start_time <= now < end_time
    return now >= start_time or now < end_time


def _dwell_seconds(
    options: Mapping[str, Any], screen: Mapping[str, Any] | None, present: bool
) -> int:
    """Seconds one slot stays up. `screen` is None for the built-in slot."""
    if screen is None:
        return options.get(CONF_BUILTIN_SECONDS, DEFAULT_BUILTIN_SECONDS)
    if screen.get(CONF_SCREEN_SECONDS, 0) > 0:
        return screen[CONF_SCREEN_SECONDS]
    if present:
        return options[CONF_SECONDS_PRESENT]
    return options[CONF_SECONDS]


def estimate_updates_per_hour(
    options: Mapping[str, Any], screens: Sequence[Mapping[str, Any]]
) -> tuple[float, float]:
    """Expected writes per hour as (normal, present).

    At most one write per dwell, and never closer than MIN_WRITE_GAP.
    """
    enabled = [s for s in screens if s.get(CONF_SCREEN_ENABLED, True)]
    has_presence = bool(options.get(CONF_PRESENCE_ENTITY))
    if options.get(CONF_MODE) == MODE_SINGLE:
        if not enabled:
            return (0.0, 0.0)
        normal = 3600 / max(options[CONF_SECONDS], MIN_WRITE_GAP)
        present = (
            3600 / max(options[CONF_SECONDS_PRESENT], MIN_WRITE_GAP)
            if has_presence
            else normal
        )
        return (round(normal, 1), round(present, 1))

    slots: list[Mapping[str, Any] | None] = list(enabled)
    if options.get(CONF_BUILTIN_IN_ROTATION):
        slots.append(None)
    if not slots:
        return (0.0, 0.0)
    normal_total = sum(
        max(_dwell_seconds(options, s, False), MIN_WRITE_GAP) for s in slots
    )
    present_total = sum(
        max(_dwell_seconds(options, s, has_presence), MIN_WRITE_GAP) for s in slots
    )
    return (
        round(3600 * len(slots) / normal_total, 1),
        round(3600 * len(slots) / present_total, 1),
    )


class Scheduler:
    """Decides what the LCD shows and when, and writes it."""

    def __init__(
        self, hass: HomeAssistant, entry: ConfigEntry, writer: BleWriter
    ) -> None:
        self.hass = hass
        self.entry = entry
        self._writer = writer
        self._address: str = entry.data[CONF_ADDRESS]
        self._options: dict[str, Any] = dict(entry.options)
        self._screens: list[tuple[str, str, Mapping[str, Any]]] = sorted(
            (
                (sub.subentry_id, sub.title, sub.data)
                for sub in entry.subentries.values()
                if sub.subentry_type == SUBENTRY_SCREEN
            ),
            key=lambda item: (item[2].get(CONF_POSITION, 1), item[1]),
        )
        self._slots: list[str] = []
        self._rebuild_slots()
        self._known_rotation: list[str] = []
        self._jump_slot: str | None = None

        self._lock = asyncio.Lock()
        self._unsub_tick: Callable[[], None] | None = None
        self._tick_due: datetime.datetime | None = None
        self._unsubs: list[Callable[[], None]] = []
        self._stopped = False
        self._schedule_gen = 0
        self._tick_gen = 0
        self._outage_started_at: datetime.datetime | None = None

        self._index = -1
        self._active = False
        self._inactive_written = False
        self._inactive_retried = False
        self._ready = False
        self._render_error_logged = False
        self._presence_off_at: datetime.datetime | None = None
        self._last_payload: bytes | None = None
        self._last_big: dict[str, float] = {}
        self._last_tick_at: datetime.datetime | None = None
        self._last_write_at: datetime.datetime | None = None
        self._last_success_at: datetime.datetime | None = None
        self._started_at: datetime.datetime | None = None
        self._writes: deque[datetime.datetime] = deque()
        self._failures = 0
        self._warned = False

        self.last_success: datetime.datetime | None = None
        self.last_error: str | None = None
        self.last_frame: DisplayFrame | None = None
        self.last_frame_slot: str | None = None  # None for inactive frames
        self.reachable: bool | None = None

    # ---- read-only state -------------------------------------------------

    @property
    def active(self) -> bool:
        return self._active

    @property
    def current_slot(self) -> str | None:
        if 0 <= self._index < len(self._slots):
            return self._slots[self._index]
        return None

    @property
    def current_screen_name(self) -> str | None:
        slot = self.current_slot
        return self.slot_names().get(slot) if slot else None

    @property
    def last_frame_screen_name(self) -> str | None:
        """Name of the screen that produced `last_frame`."""
        slot = self.last_frame_slot
        return self.slot_names().get(slot) if slot else None

    @property
    def updates_last_hour(self) -> int:
        cutoff = dt_util.utcnow() - datetime.timedelta(hours=1)
        while self._writes and self._writes[0] <= cutoff:
            self._writes.popleft()
        return len(self._writes)

    @property
    def estimated_updates_per_hour(self) -> float:
        normal, present = estimate_updates_per_hour(
            self._options, [data for _, _, data in self._screens]
        )
        return present if self._is_present() else normal

    def slot_names(self) -> dict[str, str]:
        """slot_id -> display name, with " (2)", " (3)" for duplicate titles."""
        titles = {sid: title for sid, title, _ in self._screens}
        titles[BUILTIN_SLOT] = BUILTIN_NAME
        seen: dict[str, int] = {}
        names: dict[str, str] = {}
        for slot in self._slots:
            title = titles[slot]
            seen[title] = seen.get(title, 0) + 1
            names[slot] = title if seen[title] == 1 else f"{title} ({seen[title]})"
        return names

    def diagnostics(self) -> dict[str, Any]:
        """Runtime state for diagnostics. Contains no address."""
        names = self.slot_names()
        return {
            "active": self._active,
            "mode": self._options.get(CONF_MODE),
            "current_slot": self.current_slot,
            "slots": list(self.slot_names().values()),
            "eligible_slots": [names[s] for s in self._rotation_slots()],
            "last_payload": self._last_payload.hex() if self._last_payload else None,
            "last_success": self.last_success.isoformat()
            if self.last_success
            else None,
            "last_error": self.last_error,
            "failures": self._failures,
            "reachable": self.reachable,
            "updates_last_hour": self.updates_last_hour,
        }

    # ---- slots, dwell, validity -----------------------------------------

    def _enabled_screens(self) -> list[tuple[str, str, Mapping[str, Any]]]:
        return [s for s in self._screens if s[2].get(CONF_SCREEN_ENABLED, True)]

    def _rebuild_slots(self) -> None:
        self._slots = [sid for sid, _, _ in self._enabled_screens()]
        if self._options.get(CONF_MODE) != MODE_SINGLE and self._options.get(
            CONF_BUILTIN_IN_ROTATION
        ):
            self._slots.append(BUILTIN_SLOT)

    def _is_eligible(self, data: Mapping[str, Any]) -> bool:
        """Enabled, and its "only show while on" entity (if any) is on."""
        if not data.get(CONF_SCREEN_ENABLED, True):
            return False
        entity_id = data.get(CONF_SHOW_WHEN)
        if not entity_id:
            return True
        state = self.hass.states.get(entity_id)
        return state is not None and state.state in ACTIVE_STATES

    def _rotation_slots(self) -> list[str]:
        """Slots that may be shown now, in order. Take-over screens win."""
        eligible = [
            (sid, data) for sid, _, data in self._screens if self._is_eligible(data)
        ]
        takeover = [
            sid
            for sid, data in eligible
            if data.get(CONF_TAKEOVER) and data.get(CONF_SHOW_WHEN)
        ]
        if takeover:
            return takeover
        slots = [sid for sid, _ in eligible]
        if self._options.get(CONF_MODE) != MODE_SINGLE and self._options.get(
            CONF_BUILTIN_IN_ROTATION
        ):
            slots.append(BUILTIN_SLOT)
        return slots

    def _screen_data(self, slot: str) -> Mapping[str, Any] | None:
        for sid, _, data in self._screens:
            if sid == slot:
                return data
        return None

    def _dwell(self, slot: str | None) -> int:
        if slot == BUILTIN_SLOT:
            return _dwell_seconds(self._options, None, False)
        data = self._screen_data(slot) if slot else None
        return _dwell_seconds(self._options, data or {}, self._is_present())

    def _validity(self) -> int:
        if (
            self._options.get(CONF_MODE) == MODE_ROTATING
            and self._options.get(CONF_ON_HA_STOP, HA_STOP_FREEZE) == HA_STOP_FREEZE
        ):
            return VALIDITY_PERMANENT
        dwells = [
            self._options[CONF_SECONDS],
            self._options[CONF_SECONDS_PRESENT],
            self._options.get(CONF_BUILTIN_SECONDS, DEFAULT_BUILTIN_SECONDS),
        ]
        dwells += [
            data[CONF_SCREEN_SECONDS]
            for _, _, data in self._screens
            if data.get(CONF_SCREEN_SECONDS, 0) > 0
        ]
        return min(max(3 * max(dwells), MIN_FINITE_VALIDITY), MAX_FINITE_VALIDITY)

    def _values(self, data: Mapping[str, Any]) -> dict[str, SourceValue]:
        values: dict[str, SourceValue] = {}
        for entity_id in screen_entity_ids(data):
            state = self.hass.states.get(entity_id)
            if state is not None:
                values[entity_id] = SourceValue(
                    state.state, state.attributes.get("unit_of_measurement")
                )
        return values

    def _render_slot(self, slot: str) -> DisplayFrame | None:
        if slot == BUILTIN_SLOT:
            return DisplayFrame(validity=VALIDITY_BUILTIN)
        data = self._screen_data(slot)
        if data is None:
            return None
        try:
            return render(data, self._values(data), self._validity())
        except Exception as err:
            self._log_render_error(err)
            return None

    def _log_render_error(self, err: Exception) -> None:
        """Log an unexpected render error once; details only at debug."""
        if not self._render_error_logged:
            self._render_error_logged = True
            _LOGGER.error(
                "%s: unexpected error rendering screen: %s",
                self.entry.title,
                type(err).__name__,
            )
        _LOGGER.debug("Render error details", exc_info=True)

    # ---- presence and activity ------------------------------------------

    def _is_present(self) -> bool:
        entity_id = self._options.get(CONF_PRESENCE_ENTITY)
        if not entity_id:
            return False
        state = self.hass.states.get(entity_id)
        if state is not None and state.state in PRESENT_STATES:
            return True
        if self._presence_off_at is None:
            return False
        linger = datetime.timedelta(seconds=PRESENCE_LINGER)
        return dt_util.utcnow() - self._presence_off_at < linger

    def _is_active(self) -> bool:
        if not self._options.get(CONF_ENABLED, True):
            return False
        entity_id = self._options.get(CONF_ACTIVE_ENTITY)
        if entity_id:
            state = self.hass.states.get(entity_id)
            if state is None or state.state not in ACTIVE_STATES:
                return False
        return not in_quiet_hours(
            dt_util.now().time(),
            self._options.get(CONF_QUIET_START),
            self._options.get(CONF_QUIET_END),
        )

    # ---- timers ----------------------------------------------------------

    def _cancel_tick(self) -> None:
        if self._unsub_tick is not None:
            self._unsub_tick()
        self._unsub_tick = None
        self._tick_due = None

    def _schedule_at(self, due: datetime.datetime) -> None:
        """Keep exactly one pending tick."""
        self._cancel_tick()
        self._schedule_gen += 1
        if self._stopped:
            return
        self._tick_due = due
        self._unsub_tick = async_track_point_in_utc_time(
            self.hass, self._on_tick_due, due
        )

    def _schedule_after_write(self, due: datetime.datetime) -> None:
        """Schedule the next tick unless someone else did while we were writing."""
        if self._schedule_gen == self._tick_gen:
            self._schedule_at(due)

    def _spawn(self, coro: Coroutine[Any, Any, Any], name: str) -> None:
        self.entry.async_create_background_task(
            self.hass, coro, f"{DOMAIN} {self.entry.entry_id} {name}"
        )

    @callback
    def _on_tick_due(self, _now: datetime.datetime) -> None:
        self._unsub_tick = None
        self._tick_due = None
        self._spawn(self._async_tick(), "tick")

    def _notify(self) -> None:
        if self._stopped:
            return
        async_dispatcher_send(self.hass, signal_update(self.entry.entry_id))

    def _earliest_write(self, now: datetime.datetime) -> datetime.datetime:
        if self._last_write_at is None:
            return now
        return max(now, self._last_write_at + datetime.timedelta(seconds=MIN_WRITE_GAP))

    def _next_due(self, now: datetime.datetime, seconds: float) -> datetime.datetime:
        """Next automatic tick: after `seconds`, and never inside the write gap."""
        due = now + datetime.timedelta(seconds=seconds)
        if self._last_write_at is None:
            return due
        return max(due, self._last_write_at + datetime.timedelta(seconds=MIN_WRITE_GAP))

    # ---- lifecycle -------------------------------------------------------

    async def async_start(self) -> None:
        """Register listeners and schedule the first tick."""
        entity_ids = {
            entity_id
            for _, _, data in self._screens
            for entity_id in screen_entity_ids(data)
        }
        for key in (CONF_PRESENCE_ENTITY, CONF_ACTIVE_ENTITY):
            if self._options.get(key):
                entity_ids.add(self._options[key])
        entity_ids.update(
            data[CONF_SHOW_WHEN]
            for _, _, data in self._screens
            if data.get(CONF_SHOW_WHEN)
        )
        self._known_rotation = self._rotation_slots()
        self._unsubs.append(
            async_track_time_interval(
                self.hass,
                self._check_activity,
                datetime.timedelta(seconds=ACTIVITY_CHECK_INTERVAL),
            )
        )
        self._unsubs.append(
            async_track_state_change_event(
                self.hass, sorted(entity_ids), self._on_state_change
            )
        )
        self._active = self._is_active()
        self._started_at = dt_util.utcnow()
        if self.hass.state is CoreState.running:
            self._ready = True
            self._schedule_at(
                self._started_at + datetime.timedelta(seconds=RELOAD_DELAY)
            )
        else:
            self._unsubs.append(async_at_started(self.hass, self._on_ha_started))

    @callback
    def _on_ha_started(self, _hass: HomeAssistant) -> None:
        self._ready = True
        self._schedule_at(dt_util.utcnow() + datetime.timedelta(seconds=START_DELAY))

    async def async_stop(self) -> None:
        """Cancel timers and listeners. The entry cancels background tasks."""
        self._stopped = True
        self._cancel_tick()
        for unsub in self._unsubs:
            unsub()
        self._unsubs.clear()
        ir.async_delete_issue(self.hass, DOMAIN, self._issue_id())

    # ---- the tick --------------------------------------------------------

    async def _async_tick(self, force: bool = False) -> None:
        async with self._lock:
            now = dt_util.utcnow()
            if not force and self._tick_due is not None and self._tick_due > now:
                return  # a show or refresh rescheduled while this tick waited
            self._cancel_tick()
            self._tick_gen = self._schedule_gen
            self._last_tick_at = now
            if not self._active:
                if force or not self._inactive_written:
                    await self._finish_inactive(now, force)
                return
            self._inactive_written = False
            self._inactive_retried = False
            try:
                if self._options.get(CONF_MODE) == MODE_SINGLE:
                    await self._tick_single(now, force)
                else:
                    await self._tick_rotating(now, force)
            except Exception as err:
                self._log_render_error(err)
                self._schedule_after_write(self._next_due(now, self._dwell(None)))

    async def _finish_inactive(self, now: datetime.datetime, force: bool) -> None:
        """Write the inactive display; after a failure retry once, later."""
        ok = await self._async_write_inactive()
        if ok or force or self._inactive_retried:
            self._inactive_written = True
            self._inactive_retried = False
        else:
            self._inactive_retried = True
            self._schedule_after_write(self._next_due(now, self._dwell(None)))

    async def _tick_rotating(self, now: datetime.datetime, force: bool) -> None:
        count = len(self._slots)
        if force and 0 <= self._index < count:
            candidates = [self._index]  # a pending take-over jump stays pending
        else:
            jump, self._jump_slot = self._jump_slot, None
            rotation = self._rotation_slots()
            order = [(self._index + step) % count for step in range(1, count + 1)]
            candidates = [i for i in order if self._slots[i] in rotation]
            if jump in rotation:
                candidates.insert(0, self._slots.index(jump))
        for index in candidates:
            slot = self._slots[index]
            frame = self._render_slot(slot)
            if frame is not None:
                self._index = index
                await self._async_write_frame(slot, frame, force)
                self._schedule_after_write(self._next_due(now, self._dwell(slot)))
                return
        self._schedule_after_write(self._next_due(now, self._options[CONF_SECONDS]))

    async def _tick_single(self, now: datetime.datetime, force: bool) -> None:
        rotation = self._rotation_slots()
        slot = rotation[0] if rotation else None
        self._jump_slot = None
        frame = self._render_slot(slot) if slot else None
        if slot is not None and frame is not None:
            self._index = self._slots.index(slot)
            await self._async_write_frame(slot, frame, force)
        self._schedule_after_write(self._next_due(now, self._dwell(slot)))

    async def _async_write_inactive(self) -> bool:
        """Write the inactive display. True if it worked or nothing was to write."""
        mode = self._options.get(CONF_INACTIVE_DISPLAY, INACTIVE_BUILTIN)
        if mode == INACTIVE_BUILTIN:
            frame = DisplayFrame(validity=VALIDITY_BUILTIN)
        elif mode == INACTIVE_ZEROS:
            first = self._screens[0][2] if self._screens else {}
            frame = DisplayFrame(
                validity=self._validity(),
                unit=UNIT_KEYS.get(first.get(CONF_UNIT), Unit.NONE),
                percent=bool(first.get(CONF_PERCENT, False)),
                battery=bool(first.get(CONF_BATTERY, False)),
            )
        else:
            return True
        return await self._async_write_frame(None, frame, True)

    async def _async_write_frame(
        self, slot: str | None, frame: DisplayFrame, must: bool
    ) -> bool:
        """Write if the frame changed, `must`, or a finite one is about to expire.

        True if the LCD shows the frame afterwards.
        """
        payload = build_ext_frame(frame)
        if not must and payload == self._last_payload and not self._is_stale(frame):
            return True
        if await self._async_send(payload, frame, slot):
            self._last_payload = payload
            if slot is not None and slot != BUILTIN_SLOT:
                self._last_big[slot] = frame.big
            return True
        return False

    def _is_stale(self, frame: DisplayFrame) -> bool:
        """An active finite-validity frame older than 2/3 of its validity."""
        if not self._active or frame.validity in (VALIDITY_PERMANENT, VALIDITY_BUILTIN):
            return False
        if self._last_success_at is None:
            return True
        age = (dt_util.utcnow() - self._last_success_at).total_seconds()
        return age > frame.validity * 2 / 3

    async def _async_send(
        self, payload: bytes, frame: DisplayFrame, slot: str | None
    ) -> bool:
        """Write once. Never raises, never retries."""
        now = dt_util.utcnow()
        self._last_write_at = now
        try:
            await self._writer.async_write(self._address, [payload])
        except (DeviceUnreachable, WriteFailed) as err:
            self._record_failure(err)
        except Exception as err:
            self._record_failure(err, unexpected=True)
        else:
            self._record_success(now, frame, slot)
            return True
        finally:
            self._notify()
        return False

    def _record_success(
        self, now: datetime.datetime, frame: DisplayFrame, slot: str | None
    ) -> None:
        self.last_frame = frame
        self.last_frame_slot = slot
        self.last_success = now
        self._last_success_at = now
        self.reachable = True
        self._failures = 0
        self._outage_started_at = None
        self.last_error = None
        self._writes.append(now)
        self._clear_issue()
        if self._warned:
            _LOGGER.info("%s is back online", self.entry.title)
            self._warned = False

    def _record_failure(self, err: Exception, unexpected: bool = False) -> None:
        self._failures += 1
        if self._outage_started_at is None:
            self._outage_started_at = dt_util.utcnow()
        self.reachable = False
        message = mask_address(str(err)) or type(err).__name__
        self.last_error = message[:LAST_ERROR_MAX]
        _LOGGER.debug("Write failed", exc_info=True)
        if not self._warned:
            self._warned = True
            if unexpected:
                _LOGGER.error(
                    "Unexpected error writing to %s: %s: %s",
                    self.entry.title,
                    type(err).__name__,
                    self.last_error,
                )
            else:
                _LOGGER.warning(
                    "%s is unavailable: %s", self.entry.title, self.last_error
                )
        if self._failures >= FAILURES_FOR_ISSUE:
            self._set_issue()

    # ---- activity, state changes, jump ----------------------------------

    @callback
    def _check_activity(self, now: datetime.datetime) -> bool:
        """Resume or pause on activity changes. Returns True if it changed."""
        active = self._is_active()
        changed = active != self._active
        if changed:
            self._active = active
            if active and self._outage_started_at is not None:
                self._outage_started_at = now  # the outage clock paused while inactive
            if self._ready:
                self._schedule_at(self._earliest_write(now))
            self._notify()
        if active and self._outage_started_at is not None:
            outage = (now - self._outage_started_at).total_seconds()
            if outage >= NO_SUCCESS_FOR_ISSUE:
                self._set_issue()
        return changed

    @callback
    def _on_state_change(self, event: Event[EventStateChangedData]) -> None:
        entity_id = event.data["entity_id"]
        old = event.data["old_state"]
        new = event.data["new_state"]
        if entity_id == self._options.get(CONF_PRESENCE_ENTITY):
            self._on_presence_change(
                old is not None and old.state in PRESENT_STATES,
                new is not None and new.state in PRESENT_STATES,
            )
        if entity_id == self._options.get(CONF_ACTIVE_ENTITY):
            self._check_activity(dt_util.utcnow())
        self._on_condition_change(entity_id)
        if self._jump_candidates(entity_id):
            self._spawn(self._async_jump(entity_id), "jump")

    def _on_condition_change(self, entity_id: str) -> None:
        """A screen's "only show while on" entity changed: react if the set did."""
        if not any(
            data.get(CONF_SHOW_WHEN) == entity_id for _, _, data in self._screens
        ):
            return
        old, new = self._known_rotation, self._rotation_slots()
        self._known_rotation = new
        if not (self._active and self._ready) or new == old:
            return
        current = self.current_slot
        arrived = [
            sid
            for sid in new
            if sid not in old
            and self._screen_data(sid) is not None
            and self._screen_data(sid).get(CONF_TAKEOVER)
        ]
        if arrived:
            self._jump_slot = arrived[0]
        elif current is None or current not in old or current in new:
            return
        now = dt_util.utcnow()
        target = self._earliest_write(now)
        if self._tick_due is None or target < self._tick_due:
            self._schedule_at(target)

    def _on_presence_change(self, was_present: bool, is_present: bool) -> None:
        now = dt_util.utcnow()
        if was_present and not is_present:
            self._presence_off_at = now
        if is_present and not was_present and self._active:
            self._reschedule_for_new_dwell(now)
        self._notify()

    def _reschedule_for_new_dwell(self, now: datetime.datetime) -> None:
        """Move the pending tick earlier if the current dwell is now shorter."""
        if self._tick_due is None or self._last_tick_at is None:
            return
        target = max(
            self._earliest_write(now),
            self._last_tick_at
            + datetime.timedelta(seconds=self._dwell(self.current_slot)),
        )
        if target < self._tick_due:
            self._schedule_at(target)

    def _jump_candidates(self, entity_id: str) -> list[str]:
        if not self._active or self._options.get(CONF_MODE) != MODE_ROTATING:
            return []
        rotation = self._rotation_slots()
        return [
            sid
            for sid, _, data in self._enabled_screens()
            if sid in rotation
            and data.get(CONF_JUMP_DELTA, 0) > 0
            and sid in self._last_big
            and entity_id in screen_entity_ids(data)
        ]

    async def _async_jump(self, entity_id: str) -> None:
        async with self._lock:
            now = dt_util.utcnow()
            if (
                self._last_write_at is not None
                and (now - self._last_write_at).total_seconds() < MIN_WRITE_GAP
            ):
                return
            for slot in self._jump_candidates(entity_id):
                frame = self._render_slot(slot)
                delta = self._screen_data(slot)[CONF_JUMP_DELTA]
                if frame is not None and abs(frame.big - self._last_big[slot]) >= delta:
                    await self._async_show(slot, now)
                    return

    # ---- actions ---------------------------------------------------------

    async def _async_show(self, slot: str, now: datetime.datetime) -> None:
        """Write the slot now (forced) and schedule the next tick. Lock is held."""
        self._tick_gen = self._schedule_gen
        self._index = self._slots.index(slot)
        frame = self._render_slot(slot)
        if frame is not None:
            await self._async_write_frame(slot, frame, True)
        self._last_tick_at = now
        if self._active:
            self._schedule_after_write(self._next_due(now, self._dwell(slot)))

    async def async_show_now(self, slot_id: str) -> None:
        """Show a slot now, even when inactive."""
        if slot_id not in self._slots:
            raise ValueError(f"Unknown slot: {slot_id}")
        async with self._lock:
            if slot_id not in self._slots:  # options may have changed while waiting
                raise ValueError(f"Unknown slot: {slot_id}")
            await self._async_show(slot_id, dt_util.utcnow())

    async def async_refresh(self) -> None:
        """Rewrite the current frame."""
        await self._async_tick(force=True)

    def invalidate(self) -> None:
        """The LCD no longer shows what we last sent."""
        self._last_payload = None

    def apply_options(self, options: Mapping[str, Any]) -> None:
        """Take new options. Never writes; moves the pending tick."""
        now = dt_util.utcnow()
        mode_changed = options.get(CONF_MODE) != self._options.get(CONF_MODE)
        current = self.current_slot
        self._options = dict(options)
        self._rebuild_slots()
        self._known_rotation = self._rotation_slots()
        if mode_changed:
            self._index = -1
            self._last_payload = None
            self._last_success_at = None
        else:
            self._index = self._slots.index(current) if current in self._slots else -1
        changed = self._check_activity(now)
        # While a write is in flight no tick is pending; schedule one anyway so
        # the write does not schedule the next tick with the old dwell.
        pending = self._tick_due is not None or (self._ready and self._lock.locked())
        if self._active and not changed and pending:
            if mode_changed:
                due = max(
                    now + datetime.timedelta(seconds=RELOAD_DELAY),
                    self._earliest_write(now),
                )
                self._schedule_at(due)
            elif self._last_tick_at is not None:
                dwell = datetime.timedelta(seconds=self._dwell(self.current_slot))
                self._schedule_at(
                    max(self._earliest_write(now), self._last_tick_at + dwell)
                )
        self._notify()

    # ---- Repairs ---------------------------------------------------------

    def _issue_id(self) -> str:
        return f"{ISSUE_UNREACHABLE}_{self.entry.entry_id}"

    def _set_issue(self) -> None:
        if self._stopped:
            return
        ir.async_create_issue(
            self.hass,
            DOMAIN,
            self._issue_id(),
            is_fixable=False,
            severity=ir.IssueSeverity.WARNING,
            translation_key=ISSUE_UNREACHABLE,
            translation_placeholders={"name": self.entry.title},
        )

    def _clear_issue(self) -> None:
        if self._stopped:
            return
        ir.async_delete_issue(self.hass, DOMAIN, self._issue_id())
