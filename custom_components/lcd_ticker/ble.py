"""The only module that talks Bluetooth. One write at a time, for all thermometers."""

from __future__ import annotations

import asyncio
from collections.abc import Sequence
import contextlib
import logging
import re

from bleak.backends.device import BLEDevice
from bleak.exc import BleakCharacteristicNotFoundError, BleakError
import bleak_retry_connector
from bleak_retry_connector import clear_cache as clear_bluez_cache, establish_connection
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

# Also matches the BlueZ forms dev_AA_BB_CC_DD_EE_FF and dash-separated MACs.
_MAC_RE = re.compile(r"(?i)([0-9a-f]{2}[:_-]){5}[0-9a-f]{2}")

WRITER_KEY: HassKey[BleWriter] = HassKey(f"{DOMAIN}_writer")


_SEPARATORS_RE = re.compile(r"[\s:._-]")
_HEX12_RE = re.compile(r"^[0-9A-F]{12}$")


def normalize_address(raw: str) -> str | None:
    """Return AA:BB:CC:DD:EE:FF for any common MAC spelling, or None.

    Accepts upper or lower case with ':', '-', '.', '_', spaces or no separators
    (the pvvx Telink flasher shows A4C138FE8D46).
    """
    digits = _SEPARATORS_RE.sub("", raw).upper()
    if not _HEX12_RE.match(digits):
        return None
    return ":".join(digits[i : i + 2] for i in range(0, 12, 2))


def mask_address(text: str) -> str:
    """Hide any MAC address in text."""
    return _MAC_RE.sub("<address>", text)


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
        try:
            await self._connect_and_write(address, device, frames, use_cache=True)
        except BleakCharacteristicNotFoundError:
            # A stale or incomplete GATT cache (e.g. from before the pvvx flash) hides
            # the display characteristic. Look the services up fresh, once.
            _LOGGER.debug("display characteristic missing, retrying without cache")
            device = (
                bluetooth.async_ble_device_from_address(
                    self._hass, address, connectable=True
                )
                or device
            )
            try:
                await self._connect_and_write(address, device, frames, use_cache=False)
            except BleakCharacteristicNotFoundError as err:
                raise WriteFailed(
                    "the thermometer has no display characteristic; "
                    "check that the pvvx firmware is installed"
                ) from err

    async def _connect_and_write(
        self,
        address: str,
        device: BLEDevice,
        frames: Sequence[bytes],
        *,
        use_cache: bool,
    ) -> None:
        client = None
        try:
            # Looked up at call time: Home Assistant installs its own client class
            # (with working cache clearing) after this module is imported.
            client = await establish_connection(
                bleak_retry_connector.BleakClientWithServiceCache,
                device,
                device.name or "thermometer",
                max_attempts=CONNECT_ATTEMPTS,
                use_services_cache=use_cache,
            )
            try:
                for frame in frames:
                    await client.write_gatt_char(CHAR_UUID, frame, response=False)
            except BleakCharacteristicNotFoundError:
                with contextlib.suppress(Exception):
                    if not await client.clear_cache():
                        await clear_bluez_cache(address)
                raise
            _LOGGER.debug("wrote %d frame(s)", len(frames))
        except BleakCharacteristicNotFoundError:
            raise
        except (BleakError, OSError, EOFError) as err:
            raise WriteFailed(mask_address(str(err)) or type(err).__name__) from err
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
