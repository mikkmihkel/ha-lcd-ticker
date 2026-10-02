"""Tests for diagnostics."""

from __future__ import annotations

from homeassistant.core import HomeAssistant
from pytest_homeassistant_custom_component.components.diagnostics import (
    get_diagnostics_for_config_entry,
)
from pytest_homeassistant_custom_component.typing import ClientSessionGenerator

from .conftest import ADDR


async def test_diagnostics(
    hass: HomeAssistant,
    hass_client: ClientSessionGenerator,
    setup_entry,
) -> None:
    result = await get_diagnostics_for_config_entry(hass, hass_client, setup_entry)
    assert result["entry"]["data"]["address"] == "**REDACTED**"
    assert result["entry"]["title"] == "**REDACTED**"
    assert result["screens"][0]["title"] == "Power"
    assert "slots" in result["scheduler"]
    assert ADDR not in str(result)
