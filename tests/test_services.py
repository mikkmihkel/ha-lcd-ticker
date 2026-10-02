"""Tests for the show action."""

from __future__ import annotations

from unittest.mock import patch

from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ServiceValidationError
from homeassistant.helpers import device_registry as dr
import pytest
from pytest_homeassistant_custom_component.common import MockConfigEntry
import voluptuous as vol

from custom_components.lcd_ticker.const import DOMAIN

from .conftest import ADDR, FakeWriter


async def call(hass: HomeAssistant, data: dict) -> None:
    await hass.services.async_call(DOMAIN, "show", data, blocking=True)


async def test_show_by_address(
    hass: HomeAssistant,
    setup_entry,
    writer: FakeWriter,
) -> None:
    await call(
        hass,
        {
            "address": ADDR.lower(),
            "big": 5.7,
            "small": 98,
            "percent": True,
            "happy": True,
            "bracket": True,
            "validity": 65535,
        },
    )
    assert writer.writes == [bytes.fromhex("2239006200ffff0d")]


async def test_show_by_device_id_invalidates(
    hass: HomeAssistant,
    setup_entry,
    writer: FakeWriter,
) -> None:
    device = dr.async_get(hass).async_get_device_by_identifier(
        (DOMAIN, ADDR), setup_entry.entry_id
    )
    assert device is not None
    scheduler = setup_entry.runtime_data.scheduler
    with patch.object(scheduler, "invalidate") as invalidate:
        await call(hass, {"device_id": device.id, "big": 1})
    assert len(writer.writes) == 1
    invalidate.assert_called_once()


async def test_show_defaults(
    hass: HomeAssistant,
    setup_entry,
    writer: FakeWriter,
) -> None:
    await call(hass, {"address": ADDR})
    # big 0, small 0, validity 900 (0x0384), no flags
    assert writer.writes == [bytes.fromhex("22000000008403" + "00")]


@pytest.mark.parametrize(
    "data",
    [
        {},
        {"address": ADDR, "big": float("nan")},
        {"address": ADDR, "big": float("inf")},
    ],
)
async def test_show_invalid_schema(
    hass: HomeAssistant,
    setup_entry,
    data: dict,
) -> None:
    with pytest.raises(vol.Invalid):
        await call(hass, data)


async def test_show_bad_address(
    hass: HomeAssistant,
    setup_entry,
    writer: FakeWriter,
) -> None:
    with pytest.raises(ServiceValidationError):
        await call(hass, {"address": "not-a-mac"})
    assert writer.writes == []


async def test_show_unknown_device(
    hass: HomeAssistant,
    setup_entry,
) -> None:
    with pytest.raises(ServiceValidationError, match="Not an LCD Ticker"):
        await call(hass, {"device_id": "nope"})


async def test_show_device_of_other_integration(
    hass: HomeAssistant, setup_entry
) -> None:
    other = MockConfigEntry(domain="other")
    other.add_to_hass(hass)
    device = dr.async_get(hass).async_get_or_create(
        config_entry_id=other.entry_id, identifiers={("other", "x")}
    )
    with pytest.raises(ServiceValidationError):
        await call(hass, {"device_id": device.id})


async def test_show_device_of_unloaded_entry(hass: HomeAssistant, setup_entry) -> None:
    device = dr.async_get(hass).async_get_device_by_identifier(
        (DOMAIN, ADDR), setup_entry.entry_id
    )
    await hass.config_entries.async_unload(setup_entry.entry_id)
    await hass.async_block_till_done()
    with pytest.raises(ServiceValidationError, match="is not loaded"):
        await call(hass, {"device_id": device.id})


@pytest.mark.parametrize(("small", "expected"), [(2.5, 3), (-2.5, -3), (0.4, 0)])
async def test_show_small_rounds_half_away_from_zero(
    hass: HomeAssistant, setup_entry, writer: FakeWriter, small: float, expected: int
) -> None:
    await call(hass, {"address": ADDR, "small": small})
    assert int.from_bytes(writer.writes[0][3:5], "little", signed=True) == expected
