"""Base entity and option helper."""

from __future__ import annotations

from typing import Any

from homeassistant.core import HomeAssistant
from homeassistant.helpers.device_registry import CONNECTION_BLUETOOTH, DeviceInfo
from homeassistant.helpers.dispatcher import async_dispatcher_connect
from homeassistant.helpers.entity import Entity

from .const import (
    CONF_ADDRESS,
    CONF_PROFILE,
    CONF_SECONDS,
    CONF_SECONDS_PRESENT,
    DOMAIN,
    PROFILE_CUSTOM,
    signal_update,
)
from .models import LcdTickerConfigEntry


class LcdTickerEntity(Entity):
    """Common bits of every LCD Ticker entity."""

    _attr_has_entity_name = True
    _attr_should_poll = False

    def __init__(self, entry: LcdTickerConfigEntry, key: str) -> None:
        self.entry = entry
        self.scheduler = entry.runtime_data.scheduler
        address = entry.data[CONF_ADDRESS]
        self._attr_translation_key = key
        self._attr_unique_id = f"{entry.unique_id}_{key}"
        self._attr_device_info = DeviceInfo(
            connections={(CONNECTION_BLUETOOTH, address)},
            identifiers={(DOMAIN, address)},
            name=entry.title,
            manufacturer="Xiaomi",
            model="LYWSD03MMC (pvvx)",
        )

    async def async_added_to_hass(self) -> None:
        """Refresh the state when the scheduler changes."""
        self.async_on_remove(
            async_dispatcher_connect(
                self.hass, signal_update(self.entry.entry_id), self.async_write_ha_state
            )
        )


def async_set_option(
    hass: HomeAssistant, entry: LcdTickerConfigEntry, key: str, value: Any
) -> None:
    """Change one option. Editing a speed switches the profile to custom."""
    options = {**entry.options, key: value}
    if key in (CONF_SECONDS, CONF_SECONDS_PRESENT):
        options[CONF_PROFILE] = PROFILE_CUSTOM
    hass.config_entries.async_update_entry(entry, options=options)
