"""Sensors."""

from __future__ import annotations

from datetime import datetime

from homeassistant.components.sensor import (
    SensorDeviceClass,
    SensorEntity,
    SensorStateClass,
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
    async_add_entities(
        [
            LastUpdateSensor(entry),
            UpdatesLastHourSensor(entry),
            EstimatedUpdatesSensor(entry),
            LastErrorSensor(entry),
        ]
    )


class LastUpdateSensor(LcdTickerEntity, SensorEntity):
    """When the LCD was last written."""

    _attr_device_class = SensorDeviceClass.TIMESTAMP

    def __init__(self, entry: LcdTickerConfigEntry) -> None:
        super().__init__(entry, "last_update")

    @property
    def native_value(self) -> datetime | None:
        return self.scheduler.last_success


class UpdatesLastHourSensor(LcdTickerEntity, SensorEntity):
    """Successful writes in the last hour."""

    _attr_entity_category = EntityCategory.DIAGNOSTIC
    _attr_state_class = SensorStateClass.MEASUREMENT

    def __init__(self, entry: LcdTickerConfigEntry) -> None:
        super().__init__(entry, "updates_last_hour")

    @property
    def native_value(self) -> int:
        return int(self.scheduler.updates_last_hour)


class EstimatedUpdatesSensor(LcdTickerEntity, SensorEntity):
    """Expected writes per hour with the current settings."""

    _attr_entity_category = EntityCategory.DIAGNOSTIC
    _attr_state_class = SensorStateClass.MEASUREMENT

    def __init__(self, entry: LcdTickerConfigEntry) -> None:
        super().__init__(entry, "estimated_updates_per_hour")

    @property
    def native_value(self) -> float:
        return self.scheduler.estimated_updates_per_hour


class LastErrorSensor(LcdTickerEntity, SensorEntity):
    """The last write error."""

    _attr_entity_category = EntityCategory.DIAGNOSTIC
    _attr_entity_registry_enabled_default = False

    def __init__(self, entry: LcdTickerConfigEntry) -> None:
        super().__init__(entry, "last_error")

    @property
    def native_value(self) -> str | None:
        return self.scheduler.last_error
