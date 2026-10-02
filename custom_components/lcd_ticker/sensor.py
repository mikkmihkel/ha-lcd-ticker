"""Sensors."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from homeassistant.components.sensor import (
    SensorDeviceClass,
    SensorEntity,
    SensorEntityDescription,
    SensorStateClass,
)
from homeassistant.const import (
    PERCENTAGE,
    SIGNAL_STRENGTH_DECIBELS_MILLIWATT,
    EntityCategory,
    UnitOfElectricPotential,
    UnitOfTemperature,
)
from homeassistant.core import HomeAssistant
from homeassistant.helpers.dispatcher import async_dispatcher_connect
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from .const import VALIDITY_BUILTIN, signal_readings
from .entity import LcdTickerEntity
from .models import LcdTickerConfigEntry
from .render import format_big

PARALLEL_UPDATES = 0

# The thermometer's own readings. No name: Home Assistant names a sensor after
# its device class ("Temperature", "Battery", "Signal strength", ...).
READINGS = (
    SensorEntityDescription(
        key="temperature",
        device_class=SensorDeviceClass.TEMPERATURE,
        native_unit_of_measurement=UnitOfTemperature.CELSIUS,
        state_class=SensorStateClass.MEASUREMENT,
        suggested_display_precision=1,
    ),
    SensorEntityDescription(
        key="humidity",
        device_class=SensorDeviceClass.HUMIDITY,
        native_unit_of_measurement=PERCENTAGE,
        state_class=SensorStateClass.MEASUREMENT,
        suggested_display_precision=0,
    ),
    SensorEntityDescription(
        key="battery",
        device_class=SensorDeviceClass.BATTERY,
        native_unit_of_measurement=PERCENTAGE,
        state_class=SensorStateClass.MEASUREMENT,
        entity_category=EntityCategory.DIAGNOSTIC,
    ),
    SensorEntityDescription(
        key="voltage",
        device_class=SensorDeviceClass.VOLTAGE,
        native_unit_of_measurement=UnitOfElectricPotential.VOLT,
        state_class=SensorStateClass.MEASUREMENT,
        entity_category=EntityCategory.DIAGNOSTIC,
        suggested_display_precision=2,
    ),
    SensorEntityDescription(
        key="signal_strength",
        device_class=SensorDeviceClass.SIGNAL_STRENGTH,
        native_unit_of_measurement=SIGNAL_STRENGTH_DECIBELS_MILLIWATT,
        state_class=SensorStateClass.MEASUREMENT,
        entity_category=EntityCategory.DIAGNOSTIC,
        entity_registry_enabled_default=False,
    ),
)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: LcdTickerConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    async_add_entities(
        [
            DisplaySensor(entry),
            LastUpdateSensor(entry),
            UpdatesLastHourSensor(entry),
            EstimatedUpdatesSensor(entry),
            LastErrorSensor(entry),
            *(ReadingSensor(entry, description) for description in READINGS),
        ]
    )


class DisplaySensor(LcdTickerEntity, SensorEntity):
    """What the LCD shows now (the last frame written)."""

    def __init__(self, entry: LcdTickerConfigEntry) -> None:
        super().__init__(entry, "display")

    @property
    def native_value(self) -> str | None:
        frame = self.scheduler.last_frame
        if frame is None:
            return None
        if frame.validity == VALIDITY_BUILTIN:
            return "built-in reading"
        return f"{format_big(frame.big)} | {frame.small}"

    @property
    def extra_state_attributes(self) -> dict[str, Any] | None:
        frame = self.scheduler.last_frame
        if frame is None:
            return None
        return {
            "screen": self.scheduler.current_screen_name,
            "big": frame.big,
            "small": frame.small,
            "unit": frame.unit.name.lower(),
            "face": frame.face.name.lower(),
            "percent": frame.percent,
            "battery": frame.battery,
            "validity": frame.validity,
        }


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
    # Ages out with time, not with scheduler events; the property does no I/O.
    _attr_should_poll = True

    def __init__(self, entry: LcdTickerConfigEntry) -> None:
        super().__init__(entry, "updates_last_hour")

    @property
    def native_value(self) -> int:
        return int(self.scheduler.updates_last_hour)


class EstimatedUpdatesSensor(LcdTickerEntity, SensorEntity):
    """Expected writes per hour with the current settings."""

    _attr_entity_category = EntityCategory.DIAGNOSTIC
    _attr_state_class = SensorStateClass.MEASUREMENT
    _attr_should_poll = True

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


class ReadingSensor(LcdTickerEntity, SensorEntity):
    """One of the thermometer's own readings, heard from its Bluetooth adverts."""

    def __init__(
        self, entry: LcdTickerConfigEntry, description: SensorEntityDescription
    ) -> None:
        super().__init__(entry, description.key)
        self.entity_description = description
        self._attr_translation_key = None  # name comes from the device class
        self.listener = entry.runtime_data.readings

    async def async_added_to_hass(self) -> None:
        """Refresh the state when an advert arrives."""
        await super().async_added_to_hass()
        self.async_on_remove(
            async_dispatcher_connect(
                self.hass,
                signal_readings(self.entry.entry_id),
                self.async_write_ha_state,
            )
        )

    @property
    def native_value(self) -> float | int | None:
        if self.entity_description.key == "signal_strength":
            return self.listener.rssi
        return self.listener.values.get(self.entity_description.key)

    @property
    def available(self) -> bool:
        return self.listener.available and self.native_value is not None
