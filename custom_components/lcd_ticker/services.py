"""The show action."""

from __future__ import annotations

import math
import re

from homeassistant.config_entries import ConfigEntryState
from homeassistant.core import HomeAssistant, ServiceCall
from homeassistant.exceptions import ServiceValidationError
from homeassistant.helpers import config_validation as cv, device_registry as dr
import voluptuous as vol

from .ble import get_writer
from .const import CONF_ADDRESS, DOMAIN
from .protocol import UNIT_KEYS, DisplayFrame, build_ext_frame, face_from_flags

MAC_RE = re.compile(r"^([0-9A-F]{2}:){5}[0-9A-F]{2}$")


def _finite(value: float) -> float:
    if not math.isfinite(value):
        raise vol.Invalid("Value must be a finite number")
    return value


SHOW_SCHEMA = vol.All(
    vol.Schema(
        {
            vol.Optional("device_id"): cv.string,
            vol.Optional(CONF_ADDRESS): cv.string,
            vol.Optional("big", default=0.0): vol.All(vol.Coerce(float), _finite),
            vol.Optional("small", default=0): vol.All(vol.Coerce(float), _finite),
            vol.Optional("validity", default=900): vol.All(
                vol.Coerce(int), vol.Range(min=1, max=65535)
            ),
            vol.Optional("unit", default="none"): vol.In(list(UNIT_KEYS)),
            vol.Optional("percent", default=False): cv.boolean,
            vol.Optional("battery", default=False): cv.boolean,
            vol.Optional("happy", default=False): cv.boolean,
            vol.Optional("sad", default=False): cv.boolean,
            vol.Optional("bracket", default=False): cv.boolean,
        }
    ),
    cv.has_at_least_one_key("device_id", CONF_ADDRESS),
)


def _address_from_device(hass: HomeAssistant, device_id: str) -> str:
    device = dr.async_get(hass).async_get(device_id)
    if device is not None:
        for entry_id in device.config_entries:
            entry = hass.config_entries.async_get_entry(entry_id)
            if (
                entry is not None
                and entry.domain == DOMAIN
                and entry.state is ConfigEntryState.LOADED
            ):
                return entry.data[CONF_ADDRESS]
    raise ServiceValidationError("Not an LCD Ticker thermometer")


async def _async_show(call: ServiceCall) -> None:
    hass = call.hass
    data = call.data
    if "device_id" in data:
        address = _address_from_device(hass, data["device_id"])
    else:
        address = data[CONF_ADDRESS].strip().upper()
        if not MAC_RE.match(address):
            raise ServiceValidationError("Not a valid MAC address")

    frame = DisplayFrame(
        big=data["big"],
        small=round(data["small"]),
        validity=data["validity"],
        unit=UNIT_KEYS[data["unit"]],
        face=face_from_flags(data["happy"], data["sad"], data["bracket"]),
        percent=data["percent"],
        battery=data["battery"],
    )
    await get_writer(hass).async_write(address, [build_ext_frame(frame)])

    for entry in hass.config_entries.async_loaded_entries(DOMAIN):
        if entry.data[CONF_ADDRESS].upper() == address:
            entry.runtime_data.scheduler.invalidate()


def async_setup_services(hass: HomeAssistant) -> None:
    """Register the show action."""
    hass.services.async_register(DOMAIN, "show", _async_show, schema=SHOW_SCHEMA)
