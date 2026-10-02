"""Seconds-per-screen numbers."""

from __future__ import annotations

from homeassistant.components.number import NumberEntity, NumberMode
from homeassistant.const import EntityCategory, UnitOfTime
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from .const import CONF_SECONDS, CONF_SECONDS_PRESENT, MAX_SECONDS, MIN_SECONDS
from .entity import LcdTickerEntity, async_set_option
from .models import LcdTickerConfigEntry

PARALLEL_UPDATES = 0


async def async_setup_entry(
    hass: HomeAssistant,
    entry: LcdTickerConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    async_add_entities(
        [SecondsNumber(entry, CONF_SECONDS), SecondsNumber(entry, CONF_SECONDS_PRESENT)]
    )


class SecondsNumber(LcdTickerEntity, NumberEntity):
    """How long a screen stays."""

    _attr_entity_category = EntityCategory.CONFIG
    _attr_mode = NumberMode.BOX
    _attr_native_min_value = MIN_SECONDS
    _attr_native_max_value = MAX_SECONDS
    _attr_native_step = 10
    _attr_native_unit_of_measurement = UnitOfTime.SECONDS

    def __init__(self, entry: LcdTickerConfigEntry, key: str) -> None:
        super().__init__(entry, key)
        self._key = key

    @property
    def native_value(self) -> float:
        return self.entry.options[self._key]

    async def async_set_native_value(self, value: float) -> None:
        async_set_option(self.hass, self.entry, self._key, int(value))
