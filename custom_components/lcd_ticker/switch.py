"""Rotation switch."""

from __future__ import annotations

from typing import Any

from homeassistant.components.switch import SwitchEntity
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from .const import CONF_ENABLED
from .entity import LcdTickerEntity, async_set_option
from .models import LcdTickerConfigEntry

PARALLEL_UPDATES = 0


async def async_setup_entry(
    hass: HomeAssistant,
    entry: LcdTickerConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    async_add_entities([RotationSwitch(entry)])


class RotationSwitch(LcdTickerEntity, SwitchEntity):
    """Turns the rotation on or off."""

    def __init__(self, entry: LcdTickerConfigEntry) -> None:
        super().__init__(entry, "rotation")

    @property
    def is_on(self) -> bool:
        return bool(self.entry.options[CONF_ENABLED])

    async def async_turn_on(self, **kwargs: Any) -> None:
        async_set_option(self.hass, self.entry, CONF_ENABLED, True)

    async def async_turn_off(self, **kwargs: Any) -> None:
        async_set_option(self.hass, self.entry, CONF_ENABLED, False)
