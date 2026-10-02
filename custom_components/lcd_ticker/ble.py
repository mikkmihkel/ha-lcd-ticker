"""The only module that talks Bluetooth. One write at a time, for all thermometers."""

from __future__ import annotations

import asyncio
from collections.abc import Sequence
import contextlib
import logging

from bleak.exc import BleakError
from bleak_retry_connector import BleakClientWithServiceCache, establish_connection
from homeassistant.components import bluetooth
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError
from homeassistant.util.hass_dict import HassKey

from .const import (
    CHAR_UUID,
    CONNECT_ATTEMPTS,
    DISCONNECT_TIMEOUT,
    DOMAIN,
    WRITE_TIMEOUT,
)

_LOGGER = logging.getLogger(__name__)

WRITER_KEY: HassKey[BleWriter] = HassKey(f"{DOMAIN}_writer")


class DeviceUnreachable(HomeAssistantError):
    """No connectable adapter currently sees the thermometer."""


class WriteFailed(HomeAssistantError):
    """Connecting or writing failed or timed out."""


class BleWriter:
    """Serialize all writes: many adapters can't handle parallel connections."""

    def __init__(self, hass: HomeAssistant) -> None:
        self._hass = hass
        self._lock = asyncio.Lock()

    async def async_write(self, address: str, frames: Sequence[bytes]) -> None:
        """Connect, write each frame without response, disconnect."""
        async with self._lock:
            try:
                async with asyncio.timeout(WRITE_TIMEOUT):
                    await self._write_locked(address.upper(), frames)
            except TimeoutError as err:
                raise WriteFailed(f"timed out after {WRITE_TIMEOUT} s") from err

    async def _write_locked(self, address: str, frames: Sequence[bytes]) -> None:
        device = bluetooth.async_ble_device_from_address(
            self._hass, address, connectable=True
        )
        if device is None:
            raise DeviceUnreachable("not in Bluetooth range or not connectable")
        client = None
        try:
            client = await establish_connection(
                BleakClientWithServiceCache,
                device,
                address,
                max_attempts=CONNECT_ATTEMPTS,
            )
            for frame in frames:
                await client.write_gatt_char(CHAR_UUID, frame, response=False)
            _LOGGER.debug("wrote %d frame(s)", len(frames))
        except (BleakError, OSError, EOFError) as err:
            msg = str(err) or type(err).__name__
            # Mask the MAC address from error messages
            msg = msg.replace(address, "<address>")
            msg = msg.replace(address.lower(), "<address>")
            raise WriteFailed(msg) from err
        finally:
            if client is not None:
                # Disconnect is best effort; a failure there must never hide the real result
                with contextlib.suppress(Exception):
                    async with asyncio.timeout(DISCONNECT_TIMEOUT):
                        await client.disconnect()


def get_writer(hass: HomeAssistant) -> BleWriter:
    """Return the shared writer, creating it on first use."""
    if (writer := hass.data.get(WRITER_KEY)) is None:
        writer = hass.data[WRITER_KEY] = BleWriter(hass)
    return writer
