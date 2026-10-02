"""Diagnostics."""

from __future__ import annotations

from typing import Any

from homeassistant.components.diagnostics import async_redact_data
from homeassistant.core import HomeAssistant

from .const import CONF_ADDRESS
from .models import LcdTickerConfigEntry

TO_REDACT = {CONF_ADDRESS, "title"}


async def async_get_config_entry_diagnostics(
    hass: HomeAssistant, entry: LcdTickerConfigEntry
) -> dict[str, Any]:
    """Return diagnostics with the address redacted."""
    readings = entry.runtime_data.readings
    last_seen = readings.last_seen
    return {
        "entry": async_redact_data(
            {
                "title": entry.title,
                "data": dict(entry.data),
                "options": dict(entry.options),
            },
            TO_REDACT,
        ),
        "screens": [
            {"title": s.title, "data": dict(s.data)} for s in entry.subentries.values()
        ],
        "scheduler": entry.runtime_data.scheduler.diagnostics(),
        "readings": {
            "values": dict(readings.values),
            "rssi": readings.rssi,
            "last_seen": last_seen.isoformat() if last_seen else None,
            "available": readings.available,
        },
    }
