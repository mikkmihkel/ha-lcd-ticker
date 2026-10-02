"""Tests for the options flow."""

from collections.abc import Generator
from unittest.mock import patch

from homeassistant.config_entries import ConfigSubentryData
from homeassistant.core import HomeAssistant
from homeassistant.data_entry_flow import FlowResultType
import pytest
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.lcd_ticker.const import (
    CONF_ADDRESS,
    CONF_PRESENCE_ENTITY,
    CONF_PROFILE,
    CONF_QUIET_END,
    CONF_QUIET_START,
    CONF_SECONDS,
    CONF_SECONDS_PRESENT,
    DOMAIN,
    SUBENTRY_SCREEN,
    default_options,
)
from custom_components.lcd_ticker.presets import new_screen_data


@pytest.fixture(autouse=True)
def bluetooth_loaded(hass: HomeAssistant) -> None:
    """Mark the manifest dependencies loaded instead of starting the real stack."""
    hass.config.components.update({"bluetooth", "bluetooth_adapters"})


@pytest.fixture(autouse=True)
def no_setup() -> Generator[None]:
    with (
        patch(
            "custom_components.lcd_ticker.async_setup_entry",
            return_value=True,
            create=True,
        ),
        patch(
            "custom_components.lcd_ticker.async_unload_entry",
            return_value=True,
            create=True,
        ),
    ):
        yield


async def setup_entry(hass: HomeAssistant, options=None, screens=0) -> MockConfigEntry:
    entry = MockConfigEntry(
        domain=DOMAIN,
        unique_id="A4:C1:38:00:00:01",
        data={CONF_ADDRESS: "A4:C1:38:00:00:01"},
        options=options or default_options(),
        subentries_data=[
            ConfigSubentryData(
                data=new_screen_data(i + 1),
                subentry_type=SUBENTRY_SCREEN,
                title=f"S{i}",
                unique_id=None,
            )
            for i in range(screens)
        ],
    )
    entry.add_to_hass(hass)
    await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    return entry


SECTIONS = {
    "rotation": (
        "profile",
        "mode",
        "enabled",
        "seconds_per_screen",
        "builtin_in_rotation",
        "builtin_seconds",
    ),
    "presence": ("presence_entity", "seconds_per_screen_present"),
    "pause": ("active_entity", "quiet_start", "quiet_end", "inactive_display"),
    "safety": ("on_ha_stop",),
}


def form_input(entry: MockConfigEntry, drop=(), **changes) -> dict:
    """The sectioned form input for the entry's options plus flat changes."""
    flat = {
        k: v for k, v in {**default_options(), **entry.options}.items() if v is not None
    }
    flat.update(changes)
    for key in drop:
        flat.pop(key, None)
    return {
        name: {key: flat[key] for key in keys if key in flat}
        for name, keys in SECTIONS.items()
    }


async def test_profile_change_sets_speeds(hass: HomeAssistant) -> None:
    entry = await setup_entry(hass)
    result = await hass.config_entries.options.async_init(entry.entry_id)
    assert result["step_id"] == "init"
    assert result["description_placeholders"]["per_hour"] is not None
    result = await hass.config_entries.options.async_configure(
        result["flow_id"], form_input(entry, **{CONF_PROFILE: "eco"})
    )
    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert result["data"][CONF_PROFILE] == "eco"
    assert result["data"][CONF_SECONDS] == 900
    assert result["data"][CONF_SECONDS_PRESENT] == 300
    assert isinstance(result["data"][CONF_SECONDS], int)


async def test_editing_speed_sets_custom(hass: HomeAssistant) -> None:
    entry = await setup_entry(hass)
    result = await hass.config_entries.options.async_init(entry.entry_id)
    result = await hass.config_entries.options.async_configure(
        result["flow_id"], form_input(entry, **{CONF_SECONDS: 600.0})
    )
    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert result["data"][CONF_PROFILE] == "custom"
    assert result["data"][CONF_SECONDS] == 600
    assert result["data"][CONF_SECONDS_PRESENT] == 180


async def test_quiet_hours_incomplete(hass: HomeAssistant) -> None:
    entry = await setup_entry(hass)
    result = await hass.config_entries.options.async_init(entry.entry_id)
    result = await hass.config_entries.options.async_configure(
        result["flow_id"], form_input(entry, **{CONF_QUIET_START: "22:00:00"})
    )
    assert result["type"] is FlowResultType.FORM
    assert result["errors"] == {"base": "quiet_hours_incomplete"}

    result = await hass.config_entries.options.async_configure(
        result["flow_id"],
        form_input(entry, **{CONF_QUIET_START: "22:00:00", CONF_QUIET_END: "07:00:00"}),
    )
    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert result["data"][CONF_QUIET_START] == "22:00:00"
    assert result["data"][CONF_QUIET_END] == "07:00:00"


async def test_high_update_rate_warns_once(hass: HomeAssistant) -> None:
    entry = await setup_entry(
        hass,
        options={**default_options(), CONF_PRESENCE_ENTITY: "binary_sensor.motion"},
        screens=3,
    )
    user_input = form_input(
        entry, **{CONF_SECONDS: 60, CONF_SECONDS_PRESENT: 30, CONF_PROFILE: "custom"}
    )
    result = await hass.config_entries.options.async_init(entry.entry_id)
    result = await hass.config_entries.options.async_configure(
        result["flow_id"], user_input
    )
    assert result["type"] is FlowResultType.FORM
    assert result["errors"] == {"base": "high_update_rate"}
    # 3 screens, 60 s each (the minimum gap): 60 per hour. The description still
    # shows the current settings.
    assert float(result["description_placeholders"]["new_per_hour"]) == 60.0
    assert float(result["description_placeholders"]["per_hour"]) == 7.5

    result = await hass.config_entries.options.async_configure(
        result["flow_id"], user_input
    )
    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert result["data"][CONF_SECONDS] == 60
    assert result["data"][CONF_SECONDS_PRESENT] == 30


async def test_clearing_presence_entity_stores_none(hass: HomeAssistant) -> None:
    entry = await setup_entry(
        hass,
        options={**default_options(), CONF_PRESENCE_ENTITY: "binary_sensor.motion"},
    )
    user_input = form_input(entry, drop=[CONF_PRESENCE_ENTITY])
    result = await hass.config_entries.options.async_init(entry.entry_id)
    result = await hass.config_entries.options.async_configure(
        result["flow_id"], user_input
    )
    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert result["data"][CONF_PRESENCE_ENTITY] is None


async def test_form_is_sectioned_and_stored_options_stay_flat(
    hass: HomeAssistant,
) -> None:
    entry = await setup_entry(hass)
    result = await hass.config_entries.options.async_init(entry.entry_id)
    assert list(result["data_schema"].schema) == list(SECTIONS)
    suggested = {
        marker.schema: marker.description["suggested_value"]
        for marker in result["data_schema"].schema["rotation"].schema.schema
        if marker.description
    }
    assert suggested[CONF_PROFILE] == "balanced"
    result = await hass.config_entries.options.async_configure(
        result["flow_id"], form_input(entry)
    )
    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert set(result["data"]) == set(default_options())
