"""LCD Ticker: show any Home Assistant value on a pvvx LYWSD03MMC LCD."""

from __future__ import annotations

from homeassistant.core import HomeAssistant
from homeassistant.helpers import config_validation as cv
from homeassistant.helpers.typing import ConfigType

from .ble import get_writer
from .const import DOMAIN, PLATFORMS
from .models import LcdTickerConfigEntry, LcdTickerData, structural_snapshot
from .scheduler import Scheduler
from .services import async_setup_services

CONFIG_SCHEMA = cv.config_entry_only_config_schema(DOMAIN)


async def async_setup(hass: HomeAssistant, config: ConfigType) -> bool:
    """Register the show action."""
    async_setup_services(hass)
    return True


async def async_setup_entry(hass: HomeAssistant, entry: LcdTickerConfigEntry) -> bool:
    """Set up one thermometer."""
    scheduler = Scheduler(hass, entry, get_writer(hass))
    entry.runtime_data = LcdTickerData(scheduler, structural_snapshot(entry))
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    await scheduler.async_start()
    entry.async_on_unload(entry.add_update_listener(_async_update_listener))
    return True


async def _async_update_listener(
    hass: HomeAssistant, entry: LcdTickerConfigEntry
) -> None:
    """Reload on structural changes; apply live options in place."""
    if structural_snapshot(entry) != entry.runtime_data.snapshot:
        await hass.config_entries.async_reload(entry.entry_id)
    else:
        entry.runtime_data.scheduler.apply_options(entry.options)


async def async_unload_entry(hass: HomeAssistant, entry: LcdTickerConfigEntry) -> bool:
    """Unload a thermometer."""
    ok = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
    if ok:
        await entry.runtime_data.scheduler.async_stop()
    return ok
