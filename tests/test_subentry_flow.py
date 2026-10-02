"""Tests for the screen subentry flow."""

from collections.abc import Generator
from unittest.mock import patch

from homeassistant.config_entries import (
    SOURCE_RECONFIGURE,
    SOURCE_USER,
    ConfigSubentryData,
)
from homeassistant.core import HomeAssistant
from homeassistant.data_entry_flow import FlowResultType
from homeassistant.helpers import entity_registry as er
import pytest
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.lcd_ticker.const import (
    CONF_ADDRESS,
    CONF_BIG_ENTITY,
    CONF_EXPORT_ENTITY,
    CONF_FACE_MODE,
    CONF_FACE_T1,
    CONF_FACE_T2,
    CONF_FACE_T3,
    CONF_FACE_T4,
    CONF_POSITION,
    CONF_PRESET,
    CONF_PRODUCTION_ENTITY,
    CONF_SCREEN_SECONDS,
    CONF_SMALL_ENTITY,
    CONF_TITLE,
    CONF_UNIT,
    DOMAIN,
    SUBENTRY_SCREEN,
    default_options,
)
from custom_components.lcd_ticker.presets import BASE_SCREEN, new_screen_data


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


async def make_entry(hass: HomeAssistant, screens=()) -> MockConfigEntry:
    entry = MockConfigEntry(
        domain=DOMAIN,
        unique_id="A4:C1:38:00:00:01",
        data={CONF_ADDRESS: "A4:C1:38:00:00:01"},
        options=default_options(),
        subentries_data=[
            ConfigSubentryData(
                data=data, subentry_type=SUBENTRY_SCREEN, title=title, unique_id=None
            )
            for title, data in screens
        ],
    )
    entry.add_to_hass(hass)
    await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    hass.states.async_set(
        "sensor.pv", "2500", {"unit_of_measurement": "W", "friendly_name": "PV"}
    )
    hass.states.async_set("sensor.export", "500", {"unit_of_measurement": "W"})
    hass.states.async_set("sensor.temp", "21.5", {"unit_of_measurement": "°C"})
    hass.states.async_set("sensor.hum", "45", {"unit_of_measurement": "%"})
    hass.states.async_set("sensor.price", "0.12", {"unit_of_measurement": "EUR/kWh"})
    return entry


async def start(hass, entry, preset):
    result = await hass.config_entries.subentries.async_init(
        (entry.entry_id, SUBENTRY_SCREEN), context={"source": SOURCE_USER}
    )
    assert result["step_id"] == "user"
    result = await hass.config_entries.subentries.async_configure(
        result["flow_id"], {CONF_PRESET: preset}
    )
    assert result["step_id"] == "sources"
    return result


async def configure(hass, result, sources, look=None):
    result = await hass.config_entries.subentries.async_configure(
        result["flow_id"], sources
    )
    if result["type"] is FlowResultType.FORM and result["step_id"] == "sources":
        return result
    assert result["step_id"] == "look"
    return await hass.config_entries.subentries.async_configure(
        result["flow_id"], look or {}
    )


def stored(entry):
    return list(entry.subentries.values())


async def test_solar(hass: HomeAssistant) -> None:
    entry = await make_entry(hass)
    result = await start(hass, entry, "solar")
    result = await configure(
        hass,
        result,
        {CONF_BIG_ENTITY: "sensor.pv", CONF_EXPORT_ENTITY: "sensor.export"},
    )
    assert result["type"] is FlowResultType.CREATE_ENTRY
    (sub,) = stored(entry)
    assert set(sub.data) == set(BASE_SCREEN)
    assert sub.data[CONF_PRODUCTION_ENTITY] == "sensor.pv"
    assert sub.data[CONF_POSITION] == 1
    assert isinstance(sub.data[CONF_POSITION], int)
    assert sub.title == "Solar · PV"
    assert CONF_TITLE not in sub.data


async def test_climate(hass: HomeAssistant) -> None:
    entry = await make_entry(hass)
    result = await start(hass, entry, "climate")
    result = await configure(
        hass, result, {CONF_BIG_ENTITY: "sensor.temp", CONF_SMALL_ENTITY: "sensor.hum"}
    )
    assert result["type"] is FlowResultType.CREATE_ENTRY
    (sub,) = stored(entry)
    assert set(sub.data) == set(BASE_SCREEN)
    assert sub.data[CONF_UNIT] == "deg_c"
    assert sub.data["small_source"] == "entity"


async def test_price(hass: HomeAssistant) -> None:
    entry = await make_entry(hass)
    result = await start(hass, entry, "price")
    result = await configure(hass, result, {CONF_BIG_ENTITY: "sensor.price"})
    assert result["type"] is FlowResultType.CREATE_ENTRY
    (sub,) = stored(entry)
    assert set(sub.data) == set(BASE_SCREEN)
    assert sub.data[CONF_FACE_MODE] == "scale"
    assert sub.data["small_source"] == "none"


async def test_single_and_custom(hass: HomeAssistant) -> None:
    entry = await make_entry(hass)
    for preset in ("single", "custom"):
        result = await start(hass, entry, preset)
        result = await configure(hass, result, {CONF_BIG_ENTITY: "sensor.hum"})
        assert result["type"] is FlowResultType.CREATE_ENTRY
    first, second = stored(entry)
    assert set(first.data) == set(second.data) == set(BASE_SCREEN)
    assert first.data[CONF_POSITION] == 1
    assert second.data[CONF_POSITION] == 2
    assert first.data["small_fixed"] == 1


async def test_unit_not_supported(hass: HomeAssistant) -> None:
    entry = await make_entry(hass)
    result = await start(hass, entry, "price")
    result = await configure(hass, result, {CONF_BIG_ENTITY: "sensor.temp"})
    assert result["type"] is FlowResultType.FORM
    assert result["step_id"] == "sources"
    assert result["errors"] == {CONF_BIG_ENTITY: "unit_not_supported"}


async def test_look_step_rejects_short_seconds(hass: HomeAssistant) -> None:
    entry = await make_entry(hass)
    result = await start(hass, entry, "price")
    result = await configure(
        hass, result, {CONF_BIG_ENTITY: "sensor.price"}, {CONF_SCREEN_SECONDS: 10}
    )
    assert result["type"] is FlowResultType.FORM
    assert result["step_id"] == "look"
    assert result["errors"] == {CONF_SCREEN_SECONDS: "seconds_too_short"}
    result = await hass.config_entries.subentries.async_configure(
        result["flow_id"], {CONF_SCREEN_SECONDS: 30}
    )
    assert result["type"] is FlowResultType.CREATE_ENTRY


async def test_thresholds_order(hass: HomeAssistant) -> None:
    entry = await make_entry(hass)
    result = await start(hass, entry, "price")
    result = await configure(
        hass,
        result,
        {CONF_BIG_ENTITY: "sensor.price"},
        {CONF_FACE_T1: 30, CONF_FACE_T2: 10, CONF_FACE_T3: 15, CONF_FACE_T4: 20},
    )
    assert result["type"] is FlowResultType.FORM
    assert result["step_id"] == "look"
    assert result["errors"] == {"base": "thresholds_order"}
    result = await hass.config_entries.subentries.async_configure(
        result["flow_id"],
        {CONF_FACE_T1: 5, CONF_FACE_T2: 10, CONF_FACE_T3: 15, CONF_FACE_T4: 20},
    )
    assert result["type"] is FlowResultType.CREATE_ENTRY


async def test_duplicate_markers(hass: HomeAssistant) -> None:
    entry = await make_entry(hass)
    for expect_warning in (False, True):
        result = await start(hass, entry, "climate")
        sources = {CONF_BIG_ENTITY: "sensor.temp", CONF_SMALL_ENTITY: "sensor.hum"}
        result = await configure(hass, result, sources)
        if expect_warning:
            assert result["type"] is FlowResultType.FORM
            assert result["errors"] == {"base": "duplicate_markers"}
            result = await hass.config_entries.subentries.async_configure(
                result["flow_id"], {}
            )
        assert result["type"] is FlowResultType.CREATE_ENTRY
    assert len(stored(entry)) == 2


async def test_reconfigure(hass: HomeAssistant) -> None:
    data = {
        **new_screen_data("climate", 1),
        CONF_BIG_ENTITY: "sensor.temp",
        CONF_SMALL_ENTITY: "sensor.hum",
    }
    entry = await make_entry(hass, [("Old", data)])
    (sub,) = stored(entry)
    result = await hass.config_entries.subentries.async_init(
        (entry.entry_id, SUBENTRY_SCREEN),
        context={"source": SOURCE_RECONFIGURE, "subentry_id": sub.subentry_id},
    )
    assert result["step_id"] == "sources"
    result = await hass.config_entries.subentries.async_configure(
        result["flow_id"], {CONF_BIG_ENTITY: "sensor.temp"}
    )
    assert result["step_id"] == "look"
    result = await hass.config_entries.subentries.async_configure(
        result["flow_id"], {CONF_TITLE: "New", CONF_SCREEN_SECONDS: 120.0}
    )
    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "reconfigure_successful"
    (sub,) = stored(entry)
    assert sub.title == "New"
    assert sub.data[CONF_SCREEN_SECONDS] == 120
    assert isinstance(sub.data[CONF_SCREEN_SECONDS], int)
    assert sub.data[CONF_BIG_ENTITY] == "sensor.temp"


async def test_unit_from_entity_registry(hass: HomeAssistant) -> None:
    entry = await make_entry(hass)
    er.async_get(hass).async_get_or_create(
        "sensor", "test", "reg", suggested_object_id="reg", unit_of_measurement="°C"
    )
    result = await start(hass, entry, "price")
    result = await configure(hass, result, {CONF_BIG_ENTITY: "sensor.reg"})
    assert result["step_id"] == "sources"
    assert result["errors"] == {CONF_BIG_ENTITY: "unit_not_supported"}


@pytest.mark.parametrize(
    "key", ["big_multiplier", "big_offset", "small_multiplier", "small_offset"]
)
def test_scaling_fields_are_bounded(key: str) -> None:
    import voluptuous as vol

    from custom_components.lcd_ticker.config_flow import _screen_selector

    selector = _screen_selector(key, "custom")
    assert selector(100000) == 100000
    for value in (100001, -100001, 1e308):
        with pytest.raises(vol.Invalid):
            selector(value)
