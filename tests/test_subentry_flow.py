"""Tests for the screen subentry flow."""

from collections.abc import Generator
from unittest.mock import patch

from homeassistant.config_entries import (
    SOURCE_RECONFIGURE,
    SOURCE_USER,
    ConfigSubentryData,
)
from homeassistant.core import HomeAssistant
from homeassistant.data_entry_flow import FlowResultType, section
from homeassistant.helpers import entity_registry as er
import pytest
from pytest_homeassistant_custom_component.common import MockConfigEntry
import voluptuous as vol

from custom_components.lcd_ticker.const import (
    CONF_ADDRESS,
    CONF_BIG_ENTITY,
    CONF_EXPORT_ENTITY,
    CONF_FACE_T1,
    CONF_FACE_T2,
    CONF_FACE_T3,
    CONF_FACE_T4,
    CONF_PERCENT,
    CONF_PRODUCTION_ENTITY,
    CONF_SCREEN_SECONDS,
    CONF_SHOW_WHEN,
    CONF_SMALL_ENTITY,
    CONF_SMALL_SOURCE,
    CONF_TAKEOVER,
    CONF_TITLE,
    CONF_UNIT,
    DOMAIN,
    SUBENTRY_SCREEN,
    default_options,
)
from custom_components.lcd_ticker.presets import (
    ADVANCED_FIELDS,
    BASE_SCREEN,
)


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


async def start(hass, entry):
    result = await hass.config_entries.subentries.async_init(
        (entry.entry_id, SUBENTRY_SCREEN), context={"source": SOURCE_USER}
    )
    assert result["step_id"] == "screen"
    return result


async def reconfigure(hass, entry, sub):
    result = await hass.config_entries.subentries.async_init(
        (entry.entry_id, SUBENTRY_SCREEN),
        context={"source": SOURCE_RECONFIGURE, "subentry_id": sub.subentry_id},
    )
    assert result["step_id"] == "screen"
    return result


def suggested(schema) -> dict:
    """What the frontend would send back untouched: suggested values and defaults."""
    out = {}
    for key, val in schema.schema.items():
        if isinstance(val, section):
            out[str(key)] = suggested(val.schema)
            continue
        value = (key.description or {}).get("suggested_value")
        if value is None and key.default is not vol.UNDEFINED:
            value = key.default()
        if value is not None:
            out[str(key)] = value
    return out


async def submit(hass, result, user_input):
    return await hass.config_entries.subentries.async_configure(
        result["flow_id"], user_input
    )


async def add(hass, entry, screen, advanced=None, **check):
    """Run both steps for a new screen; returns the result of the check step."""
    result = await start(hass, entry)
    result = await submit(hass, result, screen)
    assert result["step_id"] == "check"
    return await submit(hass, result, {"advanced": advanced or {}, **check})


def stored(entry):
    return list(entry.subentries.values())


SOLAR_SCREEN = {
    **BASE_SCREEN,
    "preset": "solar",
    "big_entity": "sensor.pv",
    "production_entity": "sensor.pv",
    "export_entity": "sensor.export",
    "big_convert": "kw",
    "small_source": "self_consumption",
    "percent": True,
    "face_mode": "scale",
    "face_source": "small",
    "face_t1": 20.0,
    "face_t2": 40.0,
    "face_t3": 60.0,
    "face_t4": 80.0,
}
PRICE_SCREEN = {
    **BASE_SCREEN,
    "preset": "price",
    "big_entity": "sensor.price",
    "big_convert": "cents_per_kwh",
    "small_convert": "cents_per_kwh",
    "vat_percent": 24.0,
    "face_mode": "scale",
    "face_direction": "lower_better",
    "face_t1": 5.0,
    "face_t2": 10.0,
    "face_t3": 15.0,
    "face_t4": 20.0,
}


async def test_new_screen_with_minimal_input(hass: HomeAssistant) -> None:
    entry = await make_entry(hass)
    result = await add(
        hass, entry, {CONF_BIG_ENTITY: "sensor.temp", CONF_UNIT: "deg_c"}
    )
    assert result["type"] is FlowResultType.CREATE_ENTRY
    (sub,) = stored(entry)
    assert sub.data == {
        **BASE_SCREEN,
        CONF_BIG_ENTITY: "sensor.temp",
        CONF_UNIT: "deg_c",
    }
    assert sub.data[CONF_SMALL_SOURCE] == "none"
    assert sub.data["preset"] == "custom"
    assert sub.title == "temp"  # no name typed: the big entity's name
    assert CONF_TITLE not in sub.data


async def test_second_screen_gets_the_next_position(
    hass: HomeAssistant,
) -> None:
    entry = await make_entry(hass)
    await add(hass, entry, {CONF_BIG_ENTITY: "sensor.temp", CONF_UNIT: "deg_c"})
    await add(hass, entry, {CONF_BIG_ENTITY: "sensor.hum", CONF_UNIT: "minus"})
    _first, second = stored(entry)
    assert second.data["position"] == 2
    assert isinstance(second.data["position"], int)
    assert second.title == "hum"


async def test_empty_name_becomes_the_friendly_name(hass: HomeAssistant) -> None:
    entry = await make_entry(hass)
    await add(hass, entry, {CONF_BIG_ENTITY: "sensor.pv", CONF_TITLE: ""})
    await add(
        hass,
        entry,
        {CONF_BIG_ENTITY: "sensor.temp", CONF_TITLE: " ", CONF_UNIT: "deg_c"},
    )
    first, second = stored(entry)
    assert first.title == "PV"
    assert second.title == "temp"


async def test_typed_name_is_kept(hass: HomeAssistant) -> None:
    entry = await make_entry(hass)
    await add(hass, entry, {CONF_BIG_ENTITY: "sensor.pv", CONF_TITLE: " Roof "})
    assert stored(entry)[0].title == "Roof"


async def test_small_entity_sets_the_source(hass: HomeAssistant) -> None:
    entry = await make_entry(hass)
    result = await add(
        hass,
        entry,
        {
            CONF_BIG_ENTITY: "sensor.temp",
            CONF_SMALL_ENTITY: "sensor.hum",
            CONF_PERCENT: True,
        },
    )
    assert result["type"] is FlowResultType.CREATE_ENTRY
    (sub,) = stored(entry)
    assert sub.data[CONF_SMALL_ENTITY] == "sensor.hum"
    assert sub.data[CONF_SMALL_SOURCE] == "entity"
    assert sub.data[CONF_PERCENT] is True


async def test_clearing_the_small_entity_sets_the_source_to_none(
    hass: HomeAssistant,
) -> None:
    data = {
        **BASE_SCREEN,
        CONF_BIG_ENTITY: "sensor.temp",
        CONF_SMALL_ENTITY: "sensor.hum",
        CONF_SMALL_SOURCE: "entity",
    }
    entry = await make_entry(hass, [("Old", data)])
    result = await reconfigure(hass, entry, stored(entry)[0])
    form = suggested(result["data_schema"])
    assert form[CONF_SMALL_ENTITY] == "sensor.hum"
    del form[CONF_SMALL_ENTITY]
    result = await submit(hass, result, form)
    result = await submit(hass, result, suggested(result["data_schema"]))
    assert result["reason"] == "reconfigure_successful"
    (sub,) = stored(entry)
    assert sub.data[CONF_SMALL_SOURCE] == "none"
    assert sub.data[CONF_SMALL_ENTITY] is None


@pytest.mark.parametrize(
    ("source", "extra"),
    [
        ("fixed", {"small_fixed": 7}),
        ("self_consumption", {"export_entity": "sensor.export"}),
    ],
)
async def test_an_empty_small_entity_leaves_other_sources_alone(
    hass: HomeAssistant, source, extra
) -> None:
    data = {
        **BASE_SCREEN,
        CONF_BIG_ENTITY: "sensor.pv",
        CONF_SMALL_SOURCE: source,
        **extra,
    }
    entry = await make_entry(hass, [("Old", data)])
    result = await reconfigure(hass, entry, stored(entry)[0])
    result = await submit(hass, result, suggested(result["data_schema"]))
    result = await submit(hass, result, suggested(result["data_schema"]))
    assert result["reason"] == "reconfigure_successful"
    assert stored(entry)[0].data == data


async def test_reconfigure_a_stored_solar_screen_changes_nothing(
    hass: HomeAssistant,
) -> None:
    entry = await make_entry(hass, [("Solar · PV", SOLAR_SCREEN)])
    result = await reconfigure(hass, entry, stored(entry)[0])
    result = await submit(hass, result, suggested(result["data_schema"]))
    assert result["step_id"] == "check"
    result = await submit(hass, result, suggested(result["data_schema"]))
    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "reconfigure_successful"
    (sub,) = stored(entry)
    assert dict(sub.data) == SOLAR_SCREEN
    assert sub.title == "Solar · PV"


async def test_reconfigure_a_screen_stored_by_0_2_0_keeps_its_conversion(
    hass: HomeAssistant,
) -> None:
    old = {
        k: v
        for k, v in PRICE_SCREEN.items()
        if k not in ("small_multiplier", "small_offset")
    }
    entry = await make_entry(hass, screens=[("Price", old)])
    result = await reconfigure(hass, entry, stored(entry)[0])
    result = await submit(hass, result, suggested(result["data_schema"]))
    result = await submit(hass, result, suggested(result["data_schema"]))
    assert result["reason"] == "reconfigure_successful"
    (sub,) = stored(entry)
    assert sub.data["big_convert"] == "cents_per_kwh"
    assert sub.data["vat_percent"] == 24.0
    assert sub.data["face_direction"] == "lower_better"
    assert {k: v for k, v in sub.data.items() if k in old} == old


async def test_reconfigure_keeps_a_separate_production_entity(
    hass: HomeAssistant,
) -> None:
    data = {**SOLAR_SCREEN, "preset": "custom", CONF_PRODUCTION_ENTITY: "sensor.other"}
    hass.states.async_set("sensor.other", "1", {"unit_of_measurement": "kW"})
    entry = await make_entry(hass, [("Old", data)])
    result = await reconfigure(hass, entry, stored(entry)[0])
    result = await submit(hass, result, suggested(result["data_schema"]))
    result = await submit(hass, result, suggested(result["data_schema"]))
    assert dict(stored(entry)[0].data) == data


async def test_changing_the_big_entity_moves_the_production_entity(
    hass: HomeAssistant,
) -> None:
    hass.states.async_set("sensor.pv2", "3", {"unit_of_measurement": "kW"})
    entry = await make_entry(hass, [("Old", SOLAR_SCREEN)])
    result = await reconfigure(hass, entry, stored(entry)[0])
    form = suggested(result["data_schema"]) | {CONF_BIG_ENTITY: "sensor.pv2"}
    result = await submit(hass, result, form)
    result = await submit(hass, result, suggested(result["data_schema"]))
    (sub,) = stored(entry)
    assert sub.data[CONF_BIG_ENTITY] == "sensor.pv2"
    assert sub.data[CONF_PRODUCTION_ENTITY] == "sensor.pv2"


async def test_reconfigure_changes_title_and_advanced(hass: HomeAssistant) -> None:
    entry = await make_entry(hass, [("Old", PRICE_SCREEN)])
    result = await reconfigure(hass, entry, stored(entry)[0])
    form = suggested(result["data_schema"])
    assert form[CONF_TITLE] == "Old"
    result = await submit(hass, result, form | {CONF_TITLE: "New"})
    check = suggested(result["data_schema"])
    check["advanced"][CONF_SCREEN_SECONDS] = 120.0
    result = await submit(hass, result, check)
    assert result["reason"] == "reconfigure_successful"
    (sub,) = stored(entry)
    assert sub.title == "New"
    assert sub.data[CONF_SCREEN_SECONDS] == 120
    assert isinstance(sub.data[CONF_SCREEN_SECONDS], int)


async def test_preview_for_a_temperature(hass: HomeAssistant) -> None:
    hass.states.async_set(
        "sensor.room", "21.25", {"unit_of_measurement": "°C", "friendly_name": "Room"}
    )
    entry = await make_entry(hass)
    result = await start(hass, entry)
    result = await submit(
        hass, result, {CONF_BIG_ENTITY: "sensor.room", CONF_UNIT: "deg_c"}
    )
    assert result["step_id"] == "check"
    preview = result["description_placeholders"]["preview"]
    assert "Room (sensor.room) = 21.25 °C" in preview
    assert "shows 21.3" in preview


async def test_preview_again_applies_advanced_and_stores_nothing(
    hass: HomeAssistant,
) -> None:
    hass.states.async_set(
        "sensor.nordpool", "0.1234", {"unit_of_measurement": "EUR/kWh"}
    )
    entry = await make_entry(hass)
    result = await start(hass, entry)
    result = await submit(hass, result, {CONF_BIG_ENTITY: "sensor.nordpool"})
    assert "shows 0.1" in result["description_placeholders"]["preview"]
    result = await submit(
        hass,
        result,
        {
            "advanced": {
                "big_convert": "cents_per_kwh",
                "big_multiplier": 1.0,
                "vat_percent": 24,
            },
            "preview_again": True,
        },
    )
    assert result["type"] is FlowResultType.FORM
    assert result["step_id"] == "check"
    assert "shows 15.3" in result["description_placeholders"]["preview"]
    assert stored(entry) == []
    form = suggested(result["data_schema"])
    assert form["advanced"]["big_convert"] == "cents_per_kwh"
    assert form["advanced"]["vat_percent"] == 24
    assert form.get("preview_again") is False
    result = await submit(hass, result, form)
    assert result["type"] is FlowResultType.CREATE_ENTRY
    (sub,) = stored(entry)
    assert sub.data["big_convert"] == "cents_per_kwh"
    assert "preview_again" not in sub.data


async def test_preview_again_does_not_validate(hass: HomeAssistant) -> None:
    entry = await make_entry(hass)
    result = await start(hass, entry)
    result = await submit(hass, result, {CONF_BIG_ENTITY: "sensor.hum"})
    result = await submit(
        hass,
        result,
        {"advanced": {"big_convert": "cents_per_kwh"}, "preview_again": True},
    )
    assert result["type"] is FlowResultType.FORM
    assert not result["errors"]
    assert (
        'can\'t convert "%" to cents per kWh'
        in (result["description_placeholders"]["preview"])
    )


async def test_preview_when_unavailable(hass: HomeAssistant) -> None:
    entry = await make_entry(hass)
    hass.states.async_set("sensor.price", "unavailable", {})
    result = await start(hass, entry)
    result = await submit(hass, result, {CONF_BIG_ENTITY: "sensor.price"})
    preview = result["description_placeholders"]["preview"]
    assert "(sensor.price) is unavailable" in preview


async def test_preview_survives_a_render_error(hass: HomeAssistant) -> None:
    entry = await make_entry(hass)
    result = await start(hass, entry)
    with patch(
        "custom_components.lcd_ticker.config_flow.describe_screen",
        side_effect=ValueError,
    ):
        result = await submit(hass, result, {CONF_BIG_ENTITY: "sensor.price"})
    assert result["step_id"] == "check"
    assert "could not be calculated" in result["description_placeholders"]["preview"]


async def test_check_step_has_a_collapsed_advanced_section(hass: HomeAssistant) -> None:
    entry = await make_entry(hass)
    result = await start(hass, entry)
    result = await submit(hass, result, {CONF_BIG_ENTITY: "sensor.price"})
    schema = result["data_schema"].schema
    adv = next(v for k, v in schema.items() if str(k) == "advanced")
    assert isinstance(adv, section)
    assert adv.options == {"collapsed": True}
    assert {str(k) for k in adv.schema.schema} == set(ADVANCED_FIELDS)
    assert {str(k) for k in schema} == {"advanced", "preview_again"}


async def test_unit_error_shows_on_the_check_step(hass: HomeAssistant) -> None:
    entry = await make_entry(hass)
    result = await add(
        hass, entry, {CONF_BIG_ENTITY: "sensor.temp"}, {"big_convert": "cents_per_kwh"}
    )
    assert result["type"] is FlowResultType.FORM
    assert result["step_id"] == "check"
    assert result["errors"] == {"base": "unit_not_supported"}
    assert result["description_placeholders"]["unit"] == "°C"
    assert result["description_placeholders"]["target"] == "cents per kWh"
    assert "preview" in result["description_placeholders"]
    result = await submit(hass, result, {"advanced": {"big_convert": "celsius"}})
    assert result["type"] is FlowResultType.CREATE_ENTRY


async def test_only_one_unit_error_at_a_time(hass: HomeAssistant) -> None:
    entry = await make_entry(hass)
    result = await add(
        hass,
        entry,
        {CONF_BIG_ENTITY: "sensor.hum", CONF_SMALL_ENTITY: "sensor.temp"},
        {"big_convert": "cents_per_kwh", "small_convert": "cents_per_kwh"},
    )
    assert result["errors"] == {"base": "unit_not_supported"}
    assert result["description_placeholders"]["unit"] == "%"


async def test_unit_comes_from_the_entity_registry(hass: HomeAssistant) -> None:
    entry = await make_entry(hass)
    er.async_get(hass).async_get_or_create(
        "sensor", "test", "reg", suggested_object_id="reg", unit_of_measurement="°C"
    )
    result = await add(
        hass, entry, {CONF_BIG_ENTITY: "sensor.reg"}, {"big_convert": "cents_per_kwh"}
    )
    assert result["errors"] == {"base": "unit_not_supported"}


async def test_unknown_unit_error(hass: HomeAssistant) -> None:
    hass.states.async_set("sensor.nounit", "5", {})
    entry = await make_entry(hass)
    result = await add(
        hass, entry, {CONF_BIG_ENTITY: "sensor.nounit"}, {"big_convert": "celsius"}
    )
    assert result["errors"] == {"base": "unit_unknown"}


async def test_self_consumption_in_advanced(hass: HomeAssistant) -> None:
    entry = await make_entry(hass)
    result = await add(
        hass,
        entry,
        {CONF_BIG_ENTITY: "sensor.pv", CONF_PERCENT: True},
        {"small_source": "self_consumption", "export_entity": "sensor.export"},
    )
    assert result["type"] is FlowResultType.CREATE_ENTRY
    (sub,) = stored(entry)
    assert sub.data[CONF_SMALL_SOURCE] == "self_consumption"
    assert sub.data[CONF_EXPORT_ENTITY] == "sensor.export"
    assert sub.data[CONF_PRODUCTION_ENTITY] is None


async def test_self_consumption_needs_an_export_entity(hass: HomeAssistant) -> None:
    entry = await make_entry(hass)
    result = await add(
        hass,
        entry,
        {CONF_BIG_ENTITY: "sensor.pv"},
        {"small_source": "self_consumption"},
    )
    assert result["errors"] == {"base": "solar_small_required"}


async def test_self_consumption_unit_error_names_kw(hass: HomeAssistant) -> None:
    entry = await make_entry(hass)
    result = await add(
        hass,
        entry,
        {CONF_BIG_ENTITY: "sensor.hum"},
        {"small_source": "self_consumption", "export_entity": "sensor.export"},
    )
    assert result["errors"] == {"base": "unit_not_supported"}
    assert result["description_placeholders"]["unit"] == "%"
    assert result["description_placeholders"]["target"] == "kW"


async def test_small_entity_required_returns_to_the_simple_form(
    hass: HomeAssistant,
) -> None:
    entry = await make_entry(hass)
    result = await add(
        hass, entry, {CONF_BIG_ENTITY: "sensor.pv"}, {"small_source": "entity"}
    )
    assert result["type"] is FlowResultType.FORM
    assert result["step_id"] == "screen"
    assert result["errors"] == {CONF_SMALL_ENTITY: "small_entity_required"}
    form = suggested(result["data_schema"])
    assert form[CONF_BIG_ENTITY] == "sensor.pv"
    result = await submit(hass, result, form | {CONF_SMALL_ENTITY: "sensor.hum"})
    assert result["step_id"] == "check"
    assert suggested(result["data_schema"])["advanced"]["small_source"] == "entity"
    result = await submit(hass, result, suggested(result["data_schema"]))
    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert stored(entry)[0].data[CONF_SMALL_ENTITY] == "sensor.hum"


async def test_leaving_the_small_entity_empty_means_no_small_number(
    hass: HomeAssistant,
) -> None:
    entry = await make_entry(hass)
    result = await add(
        hass, entry, {CONF_BIG_ENTITY: "sensor.pv"}, {"small_source": "entity"}
    )
    result = await submit(hass, result, suggested(result["data_schema"]))
    result = await submit(hass, result, suggested(result["data_schema"]))
    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert stored(entry)[0].data[CONF_SMALL_SOURCE] == "none"


async def test_an_emptied_name_falls_back_to_the_big_entity_name(
    hass: HomeAssistant,
) -> None:
    entry = await make_entry(hass)
    result = await start(hass, entry)
    schema_keys = {str(k): k for k in result["data_schema"].schema}
    assert isinstance(schema_keys[CONF_TITLE], vol.Optional)
    assert schema_keys[CONF_TITLE].description == {"suggested_value": "Screen 1"}
    result = await submit(
        hass,
        result,
        {CONF_BIG_ENTITY: "sensor.pv", CONF_UNIT: "none", "percent": False},
    )
    result = await submit(hass, result, {"advanced": {}})
    assert stored(entry)[0].title == "PV"


async def test_seconds_too_short(hass: HomeAssistant) -> None:
    entry = await make_entry(hass)
    result = await add(
        hass, entry, {CONF_BIG_ENTITY: "sensor.price"}, {CONF_SCREEN_SECONDS: 10}
    )
    assert result["step_id"] == "check"
    assert result["errors"] == {"base": "seconds_too_short"}
    result = await submit(hass, result, {"advanced": {CONF_SCREEN_SECONDS: 30}})
    assert result["type"] is FlowResultType.CREATE_ENTRY


async def test_thresholds_order(hass: HomeAssistant) -> None:
    entry = await make_entry(hass)
    result = await add(
        hass,
        entry,
        {CONF_BIG_ENTITY: "sensor.price"},
        {
            "face_mode": "scale",
            CONF_FACE_T1: 30,
            CONF_FACE_T2: 10,
            CONF_FACE_T3: 15,
            CONF_FACE_T4: 20,
        },
    )
    assert result["step_id"] == "check"
    assert result["errors"] == {"base": "thresholds_order"}
    result = await submit(
        hass,
        result,
        {
            "advanced": {
                CONF_FACE_T1: 5,
                CONF_FACE_T2: 10,
                CONF_FACE_T3: 15,
                CONF_FACE_T4: 20,
            }
        },
    )
    assert result["type"] is FlowResultType.CREATE_ENTRY


async def test_takeover_without_entity_is_an_error(hass: HomeAssistant) -> None:
    entry = await make_entry(hass)
    result = await add(
        hass, entry, {CONF_BIG_ENTITY: "sensor.price"}, {CONF_TAKEOVER: True}
    )
    assert result["errors"] == {"base": "takeover_needs_entity"}
    result = await submit(hass, result, {"advanced": {CONF_TAKEOVER: False}})
    assert result["type"] is FlowResultType.CREATE_ENTRY


async def test_show_when_and_takeover_are_stored(hass: HomeAssistant) -> None:
    entry = await make_entry(hass)
    result = await add(
        hass,
        entry,
        {CONF_BIG_ENTITY: "sensor.price"},
        {CONF_SHOW_WHEN: "binary_sensor.sauna", CONF_TAKEOVER: True},
    )
    assert result["type"] is FlowResultType.CREATE_ENTRY
    (sub,) = stored(entry)
    assert sub.data[CONF_SHOW_WHEN] == "binary_sensor.sauna"
    assert sub.data[CONF_TAKEOVER] is True


async def test_defaults_are_always_on(hass: HomeAssistant) -> None:
    entry = await make_entry(hass)
    await add(hass, entry, {CONF_BIG_ENTITY: "sensor.price"})
    (sub,) = stored(entry)
    assert sub.data[CONF_SHOW_WHEN] is None
    assert sub.data[CONF_TAKEOVER] is False


async def test_show_when_and_export_can_be_cleared_in_advanced(
    hass: HomeAssistant,
) -> None:
    data = {
        **SOLAR_SCREEN,
        CONF_SHOW_WHEN: "binary_sensor.sauna",
        CONF_TAKEOVER: True,
    }
    entry = await make_entry(hass, [("Old", data)])
    result = await reconfigure(hass, entry, stored(entry)[0])
    result = await submit(hass, result, suggested(result["data_schema"]))
    form = suggested(result["data_schema"])
    assert form["advanced"][CONF_SHOW_WHEN] == "binary_sensor.sauna"
    assert form["advanced"][CONF_EXPORT_ENTITY] == "sensor.export"
    del form["advanced"][CONF_SHOW_WHEN]
    del form["advanced"][CONF_EXPORT_ENTITY]
    form["advanced"][CONF_TAKEOVER] = False
    form["advanced"]["small_source"] = "none"
    result = await submit(hass, result, form)
    assert result["reason"] == "reconfigure_successful"
    (sub,) = stored(entry)
    assert sub.data[CONF_SHOW_WHEN] is None
    assert sub.data[CONF_EXPORT_ENTITY] is None


async def test_duplicate_markers_warn_once(hass: HomeAssistant) -> None:
    entry = await make_entry(hass)
    screen = {CONF_BIG_ENTITY: "sensor.temp", CONF_UNIT: "deg_c"}
    result = await add(hass, entry, screen)
    assert result["type"] is FlowResultType.CREATE_ENTRY
    result = await add(hass, entry, screen)
    assert result["type"] is FlowResultType.FORM
    assert result["errors"] == {"base": "duplicate_markers"}
    result = await submit(hass, result, {"advanced": {}})
    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert len(stored(entry)) == 2


async def test_reconfigure_does_not_warn_about_itself(hass: HomeAssistant) -> None:
    entry = await make_entry(hass, [("Old", PRICE_SCREEN)])
    result = await reconfigure(hass, entry, stored(entry)[0])
    result = await submit(hass, result, suggested(result["data_schema"]))
    result = await submit(hass, result, suggested(result["data_schema"]))
    assert result["reason"] == "reconfigure_successful"


@pytest.mark.parametrize(
    "key", ["big_multiplier", "big_offset", "small_multiplier", "small_offset"]
)
def test_scaling_fields_are_bounded(key: str) -> None:
    from custom_components.lcd_ticker.config_flow import _screen_selector

    selector = _screen_selector(key)
    assert selector(100000) == 100000
    for value in (100001, -100001, 1e308):
        with pytest.raises(vol.Invalid):
            selector(value)


async def test_entity_pickers_do_not_hide_sensors_without_device_class(
    hass: HomeAssistant,
) -> None:
    """Helpers and template sensors often have no device class."""
    entry = await make_entry(hass)
    result = await start(hass, entry)
    pickers = {
        str(k): v
        for k, v in result["data_schema"].schema.items()
        if str(k).endswith("_entity")
    }
    assert set(pickers) == {"big_entity", "small_entity"}
    result = await submit(hass, result, {CONF_BIG_ENTITY: "sensor.price"})
    adv = next(
        v for k, v in result["data_schema"].schema.items() if str(k) == "advanced"
    )
    pickers |= {
        str(k): v for k, v in adv.schema.schema.items() if str(k).endswith("_entity")
    }
    assert {"export_entity", "show_when_entity"} <= set(pickers)
    for key, selector in pickers.items():
        flt = selector.config.get("filter") or [{}]
        assert all("device_class" not in f for f in flt), key


async def test_screen_step_fields(hass: HomeAssistant) -> None:
    entry = await make_entry(hass)
    result = await start(hass, entry)
    fields = {str(k): k for k in result["data_schema"].schema}
    assert set(fields) == {"title", "big_entity", "unit", "small_entity", "percent"}
    assert isinstance(fields["big_entity"], vol.Required)
    assert isinstance(fields["small_entity"], vol.Optional)
    assert fields["title"].description == {"suggested_value": "Screen 1"}
    assert result["data_schema"]({"big_entity": "sensor.pv"})["unit"] == "none"
