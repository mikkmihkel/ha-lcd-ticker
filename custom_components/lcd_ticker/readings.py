"""Listen to the thermometer's own adverts (passive: no connection, no battery cost)."""

from __future__ import annotations

from collections.abc import Callable
from datetime import datetime

from homeassistant.components import bluetooth
from homeassistant.components.bluetooth import (
    BluetoothCallbackMatcher,
    BluetoothChange,
    BluetoothScanningMode,
    BluetoothServiceInfoBleak,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.dispatcher import async_dispatcher_send
from homeassistant.util import dt as dt_util

from .advertisement import parse_service_data
from .const import CONF_ADDRESS, signal_readings


class ReadingsListener:
    """Keeps the latest temperature, humidity, battery and voltage."""

    def __init__(self, hass: HomeAssistant, entry: ConfigEntry) -> None:
        self._hass = hass
        self._entry_id = entry.entry_id
        self._address: str = entry.data[CONF_ADDRESS]
        self._unsubscribe: list[Callable[[], None]] = []
        self.values: dict[str, float | int] = {}
        self.rssi: int | None = None
        self.last_seen: datetime | None = None
        self.available = False

    async def async_start(self) -> None:
        """Start listening; use the last advert HA already saw, if any."""
        last = bluetooth.async_last_service_info(
            self._hass, self._address, connectable=False
        )
        if last is not None:
            self._on_advert(last, BluetoothChange.ADVERTISEMENT, notify=False)
        self._unsubscribe = [
            bluetooth.async_register_callback(
                self._hass,
                self._on_advert,
                BluetoothCallbackMatcher(address=self._address, connectable=False),
                BluetoothScanningMode.PASSIVE,
            ),
            bluetooth.async_track_unavailable(
                self._hass, self._on_unavailable, self._address, connectable=False
            ),
        ]

    async def async_stop(self) -> None:
        """Stop listening."""
        for unsubscribe in self._unsubscribe:
            unsubscribe()
        self._unsubscribe = []

    @callback
    def _on_advert(
        self,
        service_info: BluetoothServiceInfoBleak,
        change: BluetoothChange,
        notify: bool = True,
    ) -> None:
        readings = parse_service_data(service_info.service_data)
        if readings is None:
            return
        for name in ("temperature", "humidity", "battery", "voltage"):
            value = getattr(readings, name)
            if value is not None:
                self.values[name] = value
        self.rssi = service_info.rssi
        self.last_seen = dt_util.utcnow()
        self.available = True
        if notify:
            async_dispatcher_send(self._hass, signal_readings(self._entry_id))

    @callback
    def _on_unavailable(self, service_info: BluetoothServiceInfoBleak) -> None:
        self.available = False
        async_dispatcher_send(self._hass, signal_readings(self._entry_id))
