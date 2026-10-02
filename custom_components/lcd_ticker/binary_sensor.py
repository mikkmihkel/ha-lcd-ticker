"""Reachable binary sensor."""

from __future__ import annotations

from homeassistant.components.binary_sensor import (
    BinarySensorDeviceClass,
    BinarySensorEntity,
)
from homeassistant.const import EntityCategory
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
    async_add_entities([ReachableSensor(entry)])


class ReachableSensor(LcdTickerEntity, BinarySensorEntity):
    """Whether the last write worked."""

    _attr_device_class = BinarySensorDeviceClass.CONNECTIVITY
    _attr_entity_category = EntityCategory.DIAGNOSTIC

    def __init__(self, entry: LcdTickerConfigEntry) -> None:
        super().__init__(entry, "reachable")

    @property
    def is_on(self) -> bool | None:
        return self.scheduler.reachable
