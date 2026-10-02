"""Runtime data for LCD Ticker."""

from __future__ import annotations

from dataclasses import dataclass
import json

from homeassistant.config_entries import ConfigEntry

from .const import LIVE_OPTION_KEYS
from .scheduler import Scheduler


@dataclass
class LcdTickerData:
    """What a loaded entry keeps."""

    scheduler: Scheduler
    snapshot: str


type LcdTickerConfigEntry = ConfigEntry[LcdTickerData]


def structural_snapshot(entry: ConfigEntry) -> str:
    """JSON of everything that needs a reload when it changes."""
    return json.dumps(
        {
            "options": {
                k: v for k, v in entry.options.items() if k not in LIVE_OPTION_KEYS
            },
            "screens": sorted(
                [sid, s.title, dict(s.data)] for sid, s in entry.subentries.items()
            ),
        },
        sort_keys=True,
        default=str,
    )
