"""Refresh button."""

from __future__ import annotations

from homeassistant.components.button import ButtonEntity
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from .entity import LcdTickerEntity
from .models import LcdTickerConfigEntry

PARALLEL_UPDATES = 0


async def async_setup_entry(
    hass: HomeAssistant,
    entry: LcdTickerConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    async_add_entities([RefreshButton(entry)])


class RefreshButton(LcdTickerEntity, ButtonEntity):
    """Rewrites the current screen."""

    def __init__(self, entry: LcdTickerConfigEntry) -> None:
        super().__init__(entry, "refresh")

    async def async_press(self) -> None:
        await self.scheduler.async_refresh()
