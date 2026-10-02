"""Tests for the readings listener."""

from __future__ import annotations

from datetime import UTC, datetime

from freezegun.api import FrozenDateTimeFactory
from homeassistant.core import HomeAssistant
from homeassistant.helpers.dispatcher import async_dispatcher_connect
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.lcd_ticker.const import CONF_ADDRESS, DOMAIN, signal_readings
from custom_components.lcd_ticker.readings import ReadingsListener

from .conftest import ADDR, ADVERT_A, ADVERT_B, FakeBluetooth, service_info


def make_listener(hass: HomeAssistant) -> ReadingsListener:
    entry = MockConfigEntry(
        domain=DOMAIN, unique_id=ADDR, data={CONF_ADDRESS: ADDR}, entry_id="e1"
    )
    return ReadingsListener(hass, entry)


async def test_nothing_before_first_advert(
    hass: HomeAssistant, bluetooth_mock: FakeBluetooth
) -> None:
    listener = make_listener(hass)
    await listener.async_start()
    assert listener.values == {}
    assert listener.rssi is None
    assert listener.last_seen is None
    assert listener.available is False
    assert bluetooth_mock.matcher["address"] == ADDR
    assert bluetooth_mock.matcher["connectable"] is False


async def test_alternating_adverts_merge(
    hass: HomeAssistant, bluetooth_mock: FakeBluetooth, freezer: FrozenDateTimeFactory
) -> None:
    freezer.move_to(datetime(2026, 10, 2, 12, 0, tzinfo=UTC))
    listener = make_listener(hass)
    await listener.async_start()
    signals: list[None] = []
    async_dispatcher_connect(hass, signal_readings("e1"), lambda: signals.append(None))
    bluetooth_mock.advert(ADVERT_A, rssi=-71)
    bluetooth_mock.advert(ADVERT_B, rssi=-65)
    assert listener.values == {
        "temperature": 25.0,
        "humidity": 50.55,
        "battery": 92,
        "voltage": 2.858,
    }
    assert listener.rssi == -65
    assert listener.last_seen == datetime(2026, 10, 2, 12, 0, tzinfo=UTC)
    assert listener.available is True
    await hass.async_block_till_done()
    assert len(signals) == 2


async def test_unusable_advert_ignored(
    hass: HomeAssistant, bluetooth_mock: FakeBluetooth
) -> None:
    listener = make_listener(hass)
    await listener.async_start()
    bluetooth_mock.advert(b"\x41\x01\x5c")  # encrypted
    assert listener.values == {}
    assert listener.available is False


async def test_unavailable_flips_available(
    hass: HomeAssistant, bluetooth_mock: FakeBluetooth
) -> None:
    listener = make_listener(hass)
    await listener.async_start()
    bluetooth_mock.advert(ADVERT_A)
    signals: list[None] = []
    async_dispatcher_connect(hass, signal_readings("e1"), lambda: signals.append(None))
    bluetooth_mock.go_unavailable()
    await hass.async_block_till_done()
    assert listener.available is False
    assert listener.values["temperature"] == 25.0  # last values are kept
    assert len(signals) == 1
    bluetooth_mock.advert(ADVERT_A)
    assert listener.available is True


async def test_seeded_from_last_service_info(
    hass: HomeAssistant, bluetooth_mock: FakeBluetooth
) -> None:
    bluetooth_mock.last_info = service_info(ADVERT_A, rssi=-80)
    listener = make_listener(hass)
    await listener.async_start()
    assert listener.values["battery"] == 92
    assert listener.rssi == -80
    assert listener.available is True


async def test_stop_unregisters(
    hass: HomeAssistant, bluetooth_mock: FakeBluetooth
) -> None:
    listener = make_listener(hass)
    await listener.async_start()
    await listener.async_stop()
    bluetooth_mock.unregister.assert_called_once()
    bluetooth_mock.unregister_unavailable.assert_called_once()
    await listener.async_stop()  # harmless a second time
    bluetooth_mock.unregister.assert_called_once()
