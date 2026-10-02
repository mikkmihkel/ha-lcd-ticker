"""Mode and screen selects."""

from __future__ import annotations

from homeassistant.components.select import SelectEntity
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from .const import CONF_MODE, MODES
from .entity import LcdTickerEntity, async_set_option
from .models import LcdTickerConfigEntry

PARALLEL_UPDATES = 0


async def async_setup_entry(
    hass: HomeAssistant,
    entry: LcdTickerConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    async_add_entities([ModeSelect(entry), ScreenSelect(entry)])


class ModeSelect(LcdTickerEntity, SelectEntity):
    """Single screen + built-in, or rotating."""

    _attr_options = MODES

    def __init__(self, entry: LcdTickerConfigEntry) -> None:
        super().__init__(entry, "mode")

    @property
    def current_option(self) -> str | None:
        return self.entry.options[CONF_MODE]

    async def async_select_option(self, option: str) -> None:
        async_set_option(self.hass, self.entry, CONF_MODE, option)


class ScreenSelect(LcdTickerEntity, SelectEntity):
    """Shows the chosen screen now."""

    def __init__(self, entry: LcdTickerConfigEntry) -> None:
        super().__init__(entry, "screen")

    @property
    def options(self) -> list[str]:
        return list(self.scheduler.slot_names().values())

    @property
    def current_option(self) -> str | None:
        name = self.scheduler.current_screen_name
        return name if name in self.options else None

    async def async_select_option(self, option: str) -> None:
        for slot_id, name in self.scheduler.slot_names().items():
            if name == option:
                await self.scheduler.async_show_now(slot_id)
                return
