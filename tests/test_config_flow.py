"""Tests for the entry config flow."""

from collections.abc import Generator
from unittest.mock import AsyncMock, MagicMock, patch

from bleak.backends.device import BLEDevice
from homeassistant.components.bluetooth import BluetoothServiceInfoBleak
from homeassistant.config_entries import SOURCE_BLUETOOTH, SOURCE_USER
from homeassistant.core import HomeAssistant
from homeassistant.data_entry_flow import FlowResultType
import pytest
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.lcd_ticker.ble import WriteFailed
from custom_components.lcd_ticker.const import (
    CONF_ADDRESS,
    CONF_PROFILE,
    CONF_SECONDS,
    CONF_SECONDS_PRESENT,
    DOMAIN,
    PROFILE_ECO,
    VALIDITY_TEST,
    default_options,
)
from custom_components.lcd_ticker.protocol import (
    DisplayFrame,
    Face,
    build_ext_frame,
)

ADDRESS = "A4:C1:38:00:00:01"
TEST_FRAME = build_ext_frame(
    DisplayFrame(face=Face.HAPPY_BRACKET, validity=VALIDITY_TEST)
)


def service_info(address=ADDRESS, name="ATC_000001"):
    return BluetoothServiceInfoBleak(
        name=name,
        address=address,
        rssi=-60,
        manufacturer_data={},
        service_data={},
        service_uuids=[],
        source="local",
        device=BLEDevice(address, name, {}),
        advertisement=None,
        connectable=True,
        time=0,
        tx_power=None,
    )


@pytest.fixture(autouse=True)
def bluetooth_loaded(hass: HomeAssistant) -> None:
    """Mark the manifest dependencies loaded instead of starting the real stack."""
    hass.config.components.update({"bluetooth", "bluetooth_adapters"})


@pytest.fixture
def writer() -> Generator[MagicMock]:
    mock = MagicMock()
    mock.async_write = AsyncMock()
    with (
        patch("custom_components.lcd_ticker.config_flow.get_writer", return_value=mock),
        patch(
            "custom_components.lcd_ticker.async_setup_entry",
            return_value=True,
            create=True,
        ),
        patch(
            "custom_components.lcd_ticker.async_unload_entry",
            return_value=True,
            create=True,
        ),
    ):
        yield mock


@pytest.fixture
def discovered() -> Generator[MagicMock]:
    with patch(
        "custom_components.lcd_ticker.config_flow.async_discovered_service_info",
        return_value=[],
    ) as mock:
        yield mock


async def test_bluetooth_flow_creates_entry(hass: HomeAssistant, writer) -> None:
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": SOURCE_BLUETOOTH}, data=service_info()
    )
    assert result["type"] is FlowResultType.FORM
    assert result["step_id"] == "confirm"
    assert result["description_placeholders"] == {"name": "ATC_000001"}

    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {"name": "Kitchen", CONF_PROFILE: PROFILE_ECO}
    )
    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert result["title"] == "Kitchen"
    assert result["data"] == {CONF_ADDRESS: ADDRESS}
    assert result["options"] == default_options(PROFILE_ECO)
    assert result["options"][CONF_SECONDS] == 900
    assert result["options"][CONF_SECONDS_PRESENT] == 300
    writer.async_write.assert_awaited_once()
    assert writer.async_write.await_args.args == (ADDRESS, [TEST_FRAME])


async def test_bluetooth_already_configured(hass: HomeAssistant, writer) -> None:
    MockConfigEntry(
        domain=DOMAIN, unique_id=ADDRESS, data={CONF_ADDRESS: ADDRESS}
    ).add_to_hass(hass)
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": SOURCE_BLUETOOTH}, data=service_info()
    )
    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "already_configured"


async def test_confirm_cannot_connect_then_retry(hass: HomeAssistant, writer) -> None:
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": SOURCE_BLUETOOTH}, data=service_info()
    )
    writer.async_write.side_effect = WriteFailed("boom")
    user_input = {"name": "Kitchen", CONF_PROFILE: PROFILE_ECO}
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], user_input
    )
    assert result["type"] is FlowResultType.FORM
    assert result["errors"] == {"base": "cannot_connect"}

    writer.async_write.side_effect = None
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], user_input
    )
    assert result["type"] is FlowResultType.CREATE_ENTRY


async def test_user_step_pick_discovered(
    hass: HomeAssistant, writer, discovered
) -> None:
    other = "A4:C1:38:00:00:02"
    discovered.return_value = [
        service_info(),
        service_info(other, "ATC_000002"),
        service_info("11:22:33:44:55:66", "Other"),
    ]
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": SOURCE_USER}
    )
    assert result["type"] is FlowResultType.FORM
    assert result["step_id"] == "user"
    values = [
        o["value"] for o in result["data_schema"].schema[CONF_ADDRESS].config["options"]
    ]
    assert values == [ADDRESS, other, "manual"]

    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {CONF_ADDRESS: other}
    )
    assert result["step_id"] == "confirm"
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {"name": "Hall", CONF_PROFILE: "balanced"}
    )
    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert result["data"] == {CONF_ADDRESS: other}


async def test_user_step_skips_configured(
    hass: HomeAssistant, writer, discovered
) -> None:
    MockConfigEntry(
        domain=DOMAIN, unique_id=ADDRESS, data={CONF_ADDRESS: ADDRESS}
    ).add_to_hass(hass)
    discovered.return_value = [service_info()]
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": SOURCE_USER}
    )
    assert result["step_id"] == "manual"


async def test_user_step_none_discovered_goes_to_manual(
    hass: HomeAssistant, writer, discovered
) -> None:
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": SOURCE_USER}
    )
    assert result["type"] is FlowResultType.FORM
    assert result["step_id"] == "manual"


async def test_user_step_choose_manual(hass: HomeAssistant, writer, discovered) -> None:
    discovered.return_value = [service_info()]
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": SOURCE_USER}
    )
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {CONF_ADDRESS: "manual"}
    )
    assert result["step_id"] == "manual"


async def test_manual_normalizes_and_validates(
    hass: HomeAssistant, writer, discovered
) -> None:
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": SOURCE_USER}
    )
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {CONF_ADDRESS: "xyz"}
    )
    assert result["step_id"] == "manual"
    assert result["errors"] == {CONF_ADDRESS: "invalid_address"}

    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {CONF_ADDRESS: " a4-c1-38-00-00-02 "}
    )
    assert result["step_id"] == "confirm"
    assert result["description_placeholders"] == {"name": "ATC_000002"}
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {"name": "Hall", CONF_PROFILE: "balanced"}
    )
    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert result["data"] == {CONF_ADDRESS: "A4:C1:38:00:00:02"}


async def test_manual_already_configured(
    hass: HomeAssistant, writer, discovered
) -> None:
    MockConfigEntry(
        domain=DOMAIN, unique_id=ADDRESS, data={CONF_ADDRESS: ADDRESS}
    ).add_to_hass(hass)
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": SOURCE_USER}
    )
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {CONF_ADDRESS: ADDRESS.lower()}
    )
    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "already_configured"
