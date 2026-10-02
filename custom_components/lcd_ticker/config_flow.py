"""Config flow, options flow and screen subentry flow for LCD Ticker."""

from __future__ import annotations

from collections.abc import Mapping
import logging
from typing import Any

from homeassistant.components.bluetooth import (
    BluetoothServiceInfoBleak,
    async_discovered_service_info,
)
from homeassistant.config_entries import (
    SOURCE_USER,
    ConfigEntry,
    ConfigFlow,
    ConfigFlowResult,
    ConfigSubentryFlow,
    OptionsFlow,
    SubentryFlowResult,
)
from homeassistant.core import callback
from homeassistant.data_entry_flow import section
from homeassistant.helpers import entity_registry as er
from homeassistant.helpers.selector import (
    BooleanSelector,
    EntityFilterSelectorConfig,
    EntitySelector,
    EntitySelectorConfig,
    NumberSelector,
    NumberSelectorConfig,
    NumberSelectorMode,
    SelectSelector,
    SelectSelectorConfig,
    SelectSelectorMode,
    TextSelector,
    TimeSelector,
)
import voluptuous as vol

from .ble import DeviceUnreachable, WriteFailed, get_writer, normalize_address
from .const import (
    CONF_ACTIVE_ENTITY,
    CONF_ADDRESS,
    CONF_BATTERY,
    CONF_BIG_CONVERT,
    CONF_BIG_DECIMALS,
    CONF_BIG_ENTITY,
    CONF_BIG_MULTIPLIER,
    CONF_BIG_OFFSET,
    CONF_BUILTIN_IN_ROTATION,
    CONF_BUILTIN_SECONDS,
    CONF_ENABLED,
    CONF_EXPORT_ENTITY,
    CONF_FACE_DIRECTION,
    CONF_FACE_FIXED,
    CONF_FACE_MODE,
    CONF_FACE_SOURCE,
    CONF_FACE_T1,
    CONF_FACE_T2,
    CONF_FACE_T3,
    CONF_FACE_T4,
    CONF_INACTIVE_DISPLAY,
    CONF_JUMP_DELTA,
    CONF_MODE,
    CONF_ON_HA_STOP,
    CONF_PERCENT,
    CONF_POSITION,
    CONF_PRESENCE_ENTITY,
    CONF_PRODUCTION_ENTITY,
    CONF_PROFILE,
    CONF_QUIET_END,
    CONF_QUIET_START,
    CONF_SCREEN_ENABLED,
    CONF_SCREEN_SECONDS,
    CONF_SECONDS,
    CONF_SECONDS_PRESENT,
    CONF_SHOW_WHEN,
    CONF_SMALL_CONVERT,
    CONF_SMALL_ENTITY,
    CONF_SMALL_FIXED,
    CONF_SMALL_MULTIPLIER,
    CONF_SMALL_OFFSET,
    CONF_SMALL_SOURCE,
    CONF_TAKEOVER,
    CONF_TITLE,
    CONF_UNIT,
    CONF_VAT_PERCENT,
    CONVERT_OPTIONS,
    DECIMALS_OPTIONS,
    DEFAULT_NAME_PREFIX,
    DIRECTION_OPTIONS,
    DOMAIN,
    FACE_MODE_OPTIONS,
    FACE_SOURCE_OPTIONS,
    HA_STOP_OPTIONS,
    INACTIVE_OPTIONS,
    MAX_SECONDS,
    MIN_SECONDS,
    MODES,
    PROFILE_BALANCED,
    PROFILE_CUSTOM,
    PROFILE_OPTIONS,
    PROFILES,
    SMALL_ENTITY,
    SMALL_NONE,
    SMALL_SOURCE_OPTIONS,
    SUBENTRY_SCREEN,
    VALIDITY_TEST,
    WARN_UPDATES_PER_HOUR,
    default_options,
)
from .presets import (
    ADVANCED_FIELDS,
    BASE_SCREEN,
    new_screen_data,
    validate_look,
    validate_sources,
)
from .protocol import FACE_KEYS, UNIT_KEYS, DisplayFrame, Face, build_ext_frame
from .render import (
    TARGET_LABELS,
    SourceValue,
    describe_screen,
    markers,
    screen_entity_ids,
)
from .scheduler import estimate_updates_per_hour

_LOGGER = logging.getLogger(__name__)

# Telink OUI used by LYWSD03MMC thermometers.
PVVX_OUI = "A4:C1:38"
MANUAL = "manual"
NUMERIC_DOMAINS = ["sensor", "input_number", "number"]
SHOW_WHEN_DOMAINS = [
    "binary_sensor",
    "input_boolean",
    "schedule",
    "sun",
    "person",
    "device_tracker",
    "switch",
]

_INT_FIELDS = (CONF_POSITION, CONF_SCREEN_SECONDS, CONF_SMALL_FIXED)
_FLOAT_FIELDS = (
    CONF_JUMP_DELTA,
    CONF_BIG_MULTIPLIER,
    CONF_BIG_OFFSET,
    CONF_VAT_PERCENT,
    CONF_SMALL_MULTIPLIER,
    CONF_SMALL_OFFSET,
    CONF_FACE_T1,
    CONF_FACE_T2,
    CONF_FACE_T3,
    CONF_FACE_T4,
)
_SCALING_FIELDS = (
    CONF_BIG_MULTIPLIER,
    CONF_BIG_OFFSET,
    CONF_SMALL_MULTIPLIER,
    CONF_SMALL_OFFSET,
)
MAX_SCALING = 100000

ADVANCED = "advanced"
PREVIEW_AGAIN = "preview_again"
# Advanced fields that a cleared picker removes; any other missing field is kept.
_CLEARABLE = (CONF_SHOW_WHEN, CONF_EXPORT_ENTITY)

# Options form sections (name -> option keys); stored options stay flat.
_SECTIONS = {
    "rotation": (
        CONF_PROFILE,
        CONF_MODE,
        CONF_ENABLED,
        CONF_SECONDS,
        CONF_BUILTIN_IN_ROTATION,
        CONF_BUILTIN_SECONDS,
    ),
    "presence": (CONF_PRESENCE_ENTITY, CONF_SECONDS_PRESENT),
    "pause": (
        CONF_ACTIVE_ENTITY,
        CONF_QUIET_START,
        CONF_QUIET_END,
        CONF_INACTIVE_DISPLAY,
    ),
    "safety": (CONF_ON_HA_STOP,),
}


def _select(options: list[str], key: str) -> SelectSelector:
    return SelectSelector(
        SelectSelectorConfig(
            options=options, translation_key=key, mode=SelectSelectorMode.DROPDOWN
        )
    )


def _entity(domain: list[str]) -> EntitySelector:
    # No device-class filter: helpers and template sensors often have none.
    # Units are checked after picking, with a clear message.
    return EntitySelector(
        EntitySelectorConfig(filter=EntityFilterSelectorConfig(domain=domain))
    )


def _any_number(
    minimum: float | None = None, maximum: float | None = None
) -> NumberSelector:
    config = NumberSelectorConfig(step="any", mode=NumberSelectorMode.BOX)
    if minimum is not None:
        config["min"] = minimum
    if maximum is not None:
        config["max"] = maximum
    return NumberSelector(config)


def _seconds(minimum: int) -> NumberSelector:
    return NumberSelector(
        NumberSelectorConfig(
            min=minimum,
            max=MAX_SECONDS,
            step=10,
            mode=NumberSelectorMode.BOX,
            unit_of_measurement="s",
        )
    )


def _one_unit_error(
    errors: dict[str, str], details: dict[str, tuple[str | None, str]]
) -> tuple[dict[str, str], dict[str, str]]:
    """Keep only the first unit error, so the shared {unit}/{target} text is right.

    Home Assistant fills one set of placeholders for the whole form; the next unit
    problem (if any) shows after this one is fixed.
    """
    for field, (unit, target) in details.items():
        kept = {
            key: code
            for key, code in errors.items()
            if key == field or key not in details
        }
        return kept, {
            "unit": unit or "no unit",
            "target": TARGET_LABELS.get(target, target),
        }
    return errors, {"unit": "", "target": ""}


def _screen_selector(key: str) -> Any:
    """Return the selector for one screen field."""
    if key in (CONF_BIG_ENTITY, CONF_SMALL_ENTITY):
        return _entity(NUMERIC_DOMAINS)
    if key == CONF_EXPORT_ENTITY:
        return _entity(["sensor"])
    if key in (CONF_BIG_CONVERT, CONF_SMALL_CONVERT):
        return _select(CONVERT_OPTIONS, "convert")
    if key == CONF_BIG_DECIMALS:
        return _select(DECIMALS_OPTIONS, "decimals")
    if key == CONF_SMALL_SOURCE:
        return _select(SMALL_SOURCE_OPTIONS, "small_source")
    if key == CONF_JUMP_DELTA:
        return _any_number(minimum=0)
    if key in _SCALING_FIELDS:
        return _any_number(-MAX_SCALING, MAX_SCALING)
    if key in _FLOAT_FIELDS and key != CONF_VAT_PERCENT:
        return _any_number()
    if key == CONF_VAT_PERCENT:
        return NumberSelector(
            NumberSelectorConfig(
                min=0,
                max=100,
                step=0.1,
                mode=NumberSelectorMode.BOX,
                unit_of_measurement="%",
            )
        )
    if key == CONF_SMALL_FIXED:
        return NumberSelector(
            NumberSelectorConfig(min=-9, max=99, step=1, mode=NumberSelectorMode.BOX)
        )
    if key == CONF_UNIT:
        return _select(list(UNIT_KEYS), "unit")
    if key == CONF_FACE_MODE:
        return _select(FACE_MODE_OPTIONS, "face_mode")
    if key == CONF_FACE_FIXED:
        return _select(list(FACE_KEYS), "face")
    if key == CONF_FACE_SOURCE:
        return _select(FACE_SOURCE_OPTIONS, "face_source")
    if key == CONF_FACE_DIRECTION:
        return _select(DIRECTION_OPTIONS, "face_direction")
    if key == CONF_POSITION:
        return NumberSelector(
            NumberSelectorConfig(min=1, max=99, step=1, mode=NumberSelectorMode.BOX)
        )
    if key == CONF_SCREEN_SECONDS:
        return _seconds(0)
    if key == CONF_SHOW_WHEN:
        return _entity(SHOW_WHEN_DOMAINS)
    if key in (CONF_PERCENT, CONF_BATTERY, CONF_SCREEN_ENABLED, CONF_TAKEOVER):
        return BooleanSelector()
    if key == CONF_TITLE:
        return TextSelector()
    if key == PREVIEW_AGAIN:
        return BooleanSelector()
    raise ValueError(f"No selector for {key}")  # pragma: no cover


def _name_for(address: str) -> str:
    return f"{DEFAULT_NAME_PREFIX}{address.replace(':', '')[-6:]}"


def _is_thermometer(info: BluetoothServiceInfoBleak) -> bool:
    """pvvx thermometers: ATC_ name, or the LYWSD03MMC address prefix.

    The name is only sent now and then, while BTHome adverts come every few
    seconds, so the address prefix lets discovery match as fast as BTHome does.
    """
    return info.name.startswith(DEFAULT_NAME_PREFIX) or info.address.upper().startswith(
        PVVX_OUI
    )


def _display_name(info: BluetoothServiceInfoBleak) -> str:
    if info.name.startswith(DEFAULT_NAME_PREFIX):
        return info.name
    return _name_for(info.address.upper())


class LcdTickerConfigFlow(ConfigFlow, domain=DOMAIN):
    """Set up one thermometer."""

    VERSION = 1

    def __init__(self) -> None:
        self._address: str = ""
        self._name: str = ""

    @staticmethod
    @callback
    def async_get_options_flow(config_entry: ConfigEntry) -> LcdTickerOptionsFlow:
        return LcdTickerOptionsFlow()

    @classmethod
    @callback
    def async_get_supported_subentry_types(
        cls, config_entry: ConfigEntry
    ) -> dict[str, type[ConfigSubentryFlow]]:
        return {SUBENTRY_SCREEN: ScreenSubentryFlow}

    async def _select_device(self, address: str, name: str) -> ConfigFlowResult:
        await self.async_set_unique_id(address)
        self._abort_if_unique_id_configured()
        self._address = address
        self._name = name
        self.context["title_placeholders"] = {"name": name}
        return await self.async_step_confirm()

    async def async_step_bluetooth(
        self, discovery_info: BluetoothServiceInfoBleak
    ) -> ConfigFlowResult:
        if not _is_thermometer(discovery_info):
            return self.async_abort(reason="not_supported")
        return await self._select_device(
            discovery_info.address.upper(), _display_name(discovery_info)
        )

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        configured = self._async_current_ids(include_ignore=False)
        found = {
            info.address.upper(): _display_name(info)
            for info in async_discovered_service_info(self.hass, connectable=True)
            if _is_thermometer(info) and info.address.upper() not in configured
        }
        if not found:
            return await self.async_step_manual()

        if user_input is not None:
            address = user_input[CONF_ADDRESS]
            if address == MANUAL:
                return await self.async_step_manual()
            return await self._select_device(
                address, found.get(address, _name_for(address))
            )

        options = [
            {"value": address, "label": f"{name} ({address})"}
            for address, name in found.items()
        ]
        options.append({"value": MANUAL, "label": "Enter MAC address"})
        schema = vol.Schema(
            {
                vol.Required(CONF_ADDRESS): SelectSelector(
                    SelectSelectorConfig(
                        options=options, mode=SelectSelectorMode.DROPDOWN
                    )
                )
            }
        )
        return self.async_show_form(step_id="user", data_schema=schema)

    async def async_step_manual(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        errors: dict[str, str] = {}
        if user_input is not None:
            address = normalize_address(user_input[CONF_ADDRESS])
            if address is not None:
                return await self._select_device(address, _name_for(address))
            errors[CONF_ADDRESS] = "invalid_address"
        schema = vol.Schema({vol.Required(CONF_ADDRESS): TextSelector()})
        return self.async_show_form(step_id="manual", data_schema=schema, errors=errors)

    async def async_step_confirm(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        errors: dict[str, str] = {}
        if user_input is not None:
            profile = user_input[CONF_PROFILE]
            frame = build_ext_frame(
                DisplayFrame(face=Face.HAPPY_BRACKET, validity=VALIDITY_TEST)
            )
            try:
                await get_writer(self.hass).async_write(self._address, [frame])
            except DeviceUnreachable, WriteFailed:
                errors["base"] = "cannot_connect"
            else:
                return self.async_create_entry(
                    title=user_input["name"],
                    data={CONF_ADDRESS: self._address},
                    options=default_options(profile),
                )
        schema = vol.Schema(
            {
                vol.Required("name", default=f"{self._name} display"): TextSelector(),
                vol.Required(CONF_PROFILE, default=PROFILE_BALANCED): _select(
                    list(PROFILES), "profile"
                ),
            }
        )
        if user_input is not None:
            schema = self.add_suggested_values_to_schema(schema, user_input)
        return self.async_show_form(
            step_id="confirm",
            data_schema=schema,
            description_placeholders={"name": self._name},
            errors=errors,
        )


class LcdTickerOptionsFlow(OptionsFlow):
    """Display settings of one thermometer."""

    def __init__(self) -> None:
        self._warned = False

    def _screens(self) -> list[dict[str, Any]]:
        return [
            dict(sub.data)
            for sub in self.config_entry.subentries.values()
            if sub.subentry_type == SUBENTRY_SCREEN
        ]

    @staticmethod
    def _schema() -> vol.Schema:
        return vol.Schema(
            {
                vol.Required("rotation"): section(
                    vol.Schema(
                        {
                            vol.Required(CONF_PROFILE): _select(
                                PROFILE_OPTIONS, "profile"
                            ),
                            vol.Required(CONF_MODE): _select(MODES, "mode"),
                            vol.Required(CONF_ENABLED): BooleanSelector(),
                            vol.Required(CONF_SECONDS): _seconds(MIN_SECONDS),
                            vol.Required(CONF_BUILTIN_IN_ROTATION): BooleanSelector(),
                            vol.Required(CONF_BUILTIN_SECONDS): _seconds(MIN_SECONDS),
                        }
                    )
                ),
                vol.Required("presence"): section(
                    vol.Schema(
                        {
                            vol.Optional(CONF_PRESENCE_ENTITY): _entity(
                                [
                                    "binary_sensor",
                                    "person",
                                    "input_boolean",
                                    "device_tracker",
                                ]
                            ),
                            vol.Required(CONF_SECONDS_PRESENT): _seconds(MIN_SECONDS),
                        }
                    )
                ),
                vol.Required("pause"): section(
                    vol.Schema(
                        {
                            vol.Optional(CONF_ACTIVE_ENTITY): _entity(
                                ["binary_sensor", "input_boolean", "sun", "person"]
                            ),
                            vol.Optional(CONF_QUIET_START): TimeSelector(),
                            vol.Optional(CONF_QUIET_END): TimeSelector(),
                            vol.Required(CONF_INACTIVE_DISPLAY): _select(
                                INACTIVE_OPTIONS, "inactive_display"
                            ),
                        }
                    )
                ),
                vol.Required("safety"): section(
                    vol.Schema(
                        {
                            vol.Required(CONF_ON_HA_STOP): _select(
                                HA_STOP_OPTIONS, "on_ha_stop"
                            ),
                        }
                    )
                ),
            }
        )

    @staticmethod
    def _flatten(user_input: Mapping[str, Any]) -> dict[str, Any]:
        """Merge the sections of the form input into one flat dict."""
        flat: dict[str, Any] = {}
        for name in _SECTIONS:
            flat.update(user_input.get(name, {}))
        return flat

    @staticmethod
    def _nest(flat: Mapping[str, Any]) -> dict[str, dict[str, Any]]:
        """Group flat option values by form section."""
        return {
            name: {key: flat[key] for key in keys if key in flat}
            for name, keys in _SECTIONS.items()
        }

    def _build(self, user_input: Mapping[str, Any]) -> dict[str, Any]:
        """Turn flat form input into options: ints, Nones, and the profile rule."""
        current = {**default_options(), **self.config_entry.options}
        new = {key: user_input.get(key) for key in default_options()}
        for key in (CONF_SECONDS, CONF_SECONDS_PRESENT, CONF_BUILTIN_SECONDS):
            new[key] = int(new[key])
        for key in (
            CONF_PRESENCE_ENTITY,
            CONF_ACTIVE_ENTITY,
            CONF_QUIET_START,
            CONF_QUIET_END,
        ):
            new[key] = new[key] or None
        profile = new[CONF_PROFILE]
        if profile != current[CONF_PROFILE] and profile != PROFILE_CUSTOM:
            new[CONF_SECONDS], new[CONF_SECONDS_PRESENT] = PROFILES[profile]
        elif (new[CONF_SECONDS], new[CONF_SECONDS_PRESENT]) != PROFILES.get(profile):
            new[CONF_PROFILE] = PROFILE_CUSTOM
        return new

    async def async_step_init(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        screens = self._screens()
        current = {**default_options(), **self.config_entry.options}
        per_hour, per_hour_present = estimate_updates_per_hour(current, screens)
        placeholders = {
            "per_hour": str(per_hour),
            "per_hour_present": str(per_hour_present),
        }
        errors: dict[str, str] = {}
        suggested = self._nest({k: v for k, v in current.items() if v is not None})

        if user_input is not None:
            suggested = user_input
            new = self._build(self._flatten(user_input))
            normal, present = estimate_updates_per_hour(new, screens)
            if (new[CONF_QUIET_START] is None) != (new[CONF_QUIET_END] is None):
                errors["base"] = "quiet_hours_incomplete"
            elif max(normal, present) > WARN_UPDATES_PER_HOUR and not self._warned:
                self._warned = True
                errors["base"] = "high_update_rate"
                placeholders["new_per_hour"] = str(max(normal, present))
            else:
                return self.async_create_entry(data=new)

        schema = self.add_suggested_values_to_schema(self._schema(), suggested)
        return self.async_show_form(
            step_id="init",
            data_schema=schema,
            description_placeholders=placeholders,
            errors=errors,
        )


class ScreenSubentryFlow(ConfigSubentryFlow):
    """Add or edit one screen: a simple form, then a check with Advanced options."""

    def __init__(self) -> None:
        self._data: dict[str, Any] = {}
        self._title: str = ""
        self._warned = False

    def _screen_subentries(self) -> list[Any]:
        return [
            sub
            for sub in self._get_entry().subentries.values()
            if sub.subentry_type == SUBENTRY_SCREEN
        ]

    def _unit_of(self, entity_id: str) -> str | None:
        if (state := self.hass.states.get(entity_id)) is not None:
            unit = state.attributes.get("unit_of_measurement")
            if unit:
                return unit
        if (entry := er.async_get(self.hass).async_get(entity_id)) is not None:
            return entry.unit_of_measurement
        return None

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> SubentryFlowResult:
        position = (
            max(
                (s.data.get(CONF_POSITION, 0) for s in self._screen_subentries()),
                default=0,
            )
            + 1
        )
        self._data = new_screen_data(position)
        self._title = f"Screen {position}"
        return await self.async_step_screen()

    async def async_step_reconfigure(
        self, user_input: dict[str, Any] | None = None
    ) -> SubentryFlowResult:
        subentry = self._get_reconfigure_subentry()
        self._data = {**BASE_SCREEN, **subentry.data}
        self._title = subentry.title
        return await self.async_step_screen()

    async def async_step_screen(
        self, user_input: dict[str, Any] | None = None
    ) -> SubentryFlowResult:
        if user_input is not None:
            self._apply_screen(user_input)
            return await self.async_step_check()
        return self._show_screen()

    def _show_screen(self, errors: dict[str, str] | None = None) -> SubentryFlowResult:
        big_entity = self._data[CONF_BIG_ENTITY]
        schema = vol.Schema(
            {
                vol.Optional(CONF_TITLE): _screen_selector(CONF_TITLE),
                vol.Required(
                    CONF_BIG_ENTITY,
                    **({"default": big_entity} if big_entity else {}),
                ): _screen_selector(CONF_BIG_ENTITY),
                vol.Required(
                    CONF_UNIT, default=self._data[CONF_UNIT]
                ): _screen_selector(CONF_UNIT),
                vol.Optional(CONF_SMALL_ENTITY): _screen_selector(CONF_SMALL_ENTITY),
                vol.Required(
                    CONF_PERCENT, default=self._data[CONF_PERCENT]
                ): _screen_selector(CONF_PERCENT),
            }
        )
        small = self._data[CONF_SMALL_ENTITY]
        suggested = {CONF_TITLE: self._title}
        if small and self._data[CONF_SMALL_SOURCE] == SMALL_ENTITY:
            suggested[CONF_SMALL_ENTITY] = small
        return self.async_show_form(
            step_id="screen",
            data_schema=self.add_suggested_values_to_schema(schema, suggested),
            errors=errors,
        )

    def _apply_screen(self, user_input: Mapping[str, Any]) -> None:
        """Merge the simple form into the screen; leave everything else alone."""
        data = self._data
        self._title = user_input.get(CONF_TITLE, "").strip()
        old_big = data[CONF_BIG_ENTITY]
        data[CONF_BIG_ENTITY] = user_input[CONF_BIG_ENTITY]
        if old_big and data.get(CONF_PRODUCTION_ENTITY) == old_big:
            data[CONF_PRODUCTION_ENTITY] = data[CONF_BIG_ENTITY]
        data[CONF_UNIT] = user_input[CONF_UNIT]
        data[CONF_PERCENT] = user_input[CONF_PERCENT]
        if small := user_input.get(CONF_SMALL_ENTITY):
            data[CONF_SMALL_ENTITY] = small
            data[CONF_SMALL_SOURCE] = SMALL_ENTITY
        elif data[CONF_SMALL_SOURCE] == SMALL_ENTITY:
            data[CONF_SMALL_ENTITY] = None
            data[CONF_SMALL_SOURCE] = SMALL_NONE

    def _advanced_schema(self) -> vol.Schema:
        fields: dict[Any, Any] = {
            vol.Optional(key): _screen_selector(key) for key in ADVANCED_FIELDS
        }
        return vol.Schema(
            {
                vol.Required(ADVANCED): section(
                    vol.Schema(fields), {"collapsed": True}
                ),
                vol.Optional(PREVIEW_AGAIN, default=False): _screen_selector(
                    PREVIEW_AGAIN
                ),
            }
        )

    def _apply_advanced(self, advanced: Mapping[str, Any]) -> dict[str, Any]:
        """The screen with the Advanced values applied (ints and floats cleaned)."""
        data = {**self._data}
        for key in ADVANCED_FIELDS:
            if key in advanced:
                data[key] = advanced[key]
            elif key in _CLEARABLE:
                data[key] = None
        data[CONF_SHOW_WHEN] = data[CONF_SHOW_WHEN] or None
        data[CONF_EXPORT_ENTITY] = data[CONF_EXPORT_ENTITY] or None
        for key in _INT_FIELDS:
            data[key] = int(data[key])
        for key in _FLOAT_FIELDS:
            data[key] = float(data[key])
        return data

    def _friendly_name(self) -> str:
        entity_id = self._data[CONF_BIG_ENTITY]
        state = self.hass.states.get(entity_id)
        return state.name if state is not None else entity_id

    def _preview(self) -> str:
        """What the LCD would show right now for the screen set up so far."""
        values: dict[str, SourceValue] = {}
        for entity_id in screen_entity_ids(self._data):
            if (state := self.hass.states.get(entity_id)) is not None:
                values[entity_id] = SourceValue(
                    state.state,
                    state.attributes.get("unit_of_measurement"),
                    state.name,
                )
        try:
            return describe_screen(self._data, values)
        except Exception:  # never break the form over a preview
            return "Nothing (the preview could not be calculated)"

    def _check(self, data: dict[str, Any]) -> tuple[str | None, dict[str, str]]:
        """Return (error code, placeholders) for the first problem, if any."""
        details: dict[str, tuple[str | None, str]] = {}
        errors = validate_sources(data, self._unit_of, details)
        if errors:
            errors, placeholders = _one_unit_error(errors, details)
            return next(iter(errors.values())), placeholders
        if errors := validate_look(data):
            return next(iter(errors.values())), {}
        if not self._warned:
            others = [
                s
                for s in self._screen_subentries()
                if self.source == SOURCE_USER
                or s.subentry_id != self._get_reconfigure_subentry().subentry_id
            ]
            if any(markers(s.data) == markers(data) for s in others):
                self._warned = True
                return "duplicate_markers", {}
        return None, {}

    async def async_step_check(
        self, user_input: dict[str, Any] | None = None
    ) -> SubentryFlowResult:
        errors: dict[str, str] = {}
        placeholders = {"unit": "", "target": ""}
        if user_input is not None:
            data = self._apply_advanced(user_input.get(ADVANCED, {}))
            self._data = data
            if not user_input.get(PREVIEW_AGAIN):
                error, found = self._check(data)
                if error is None:
                    return self._save(data)
                if error == "small_entity_required":
                    return self._show_screen({CONF_SMALL_ENTITY: error})
                errors = {"base": error}
                placeholders |= found

        schema = self.add_suggested_values_to_schema(
            self._advanced_schema(),
            {
                ADVANCED: {
                    k: v
                    for k, v in self._data.items()
                    if k in ADVANCED_FIELDS and v is not None
                }
            },
        )
        return self.async_show_form(
            step_id="check",
            data_schema=schema,
            errors=errors,
            description_placeholders={**placeholders, "preview": self._preview()},
        )

    def _save(self, data: dict[str, Any]) -> SubentryFlowResult:
        title = self._title or self._friendly_name()
        if self.source == SOURCE_USER:
            return self.async_create_entry(title=title, data=data)
        return self.async_update_and_abort(
            self._get_entry(),
            self._get_reconfigure_subentry(),
            title=title,
            data=data,
        )
