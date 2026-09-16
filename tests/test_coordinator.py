"""Tests for the Marstek coordinator and its write paths.

These run against a real Home Assistant instance with the UDP client replaced
by a stub, so the coordinator's own behaviour -- failure tolerance, write
throttling and setpoint de-duplication -- is what is under test.
"""
from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest
from pytest_homeassistant_custom_component.common import MockConfigEntry

from homeassistant.core import HomeAssistant

from custom_components.marstek_ha.const import (
    CONF_DEVICE_IP,
    CONF_DEVICE_PORT,
    CONF_MIN_WRITE_INTERVAL,
    DOMAIN,
    MAX_CONSECUTIVE_FAILURES,
)


def _sample_data(mode: str = "Auto") -> dict:
    """Return one plausible poll result."""
    return {
        "device": {"device": "VenusE", "ver": 150, "ble_mac": "aabbcc"},
        "battery": {"soc": 61, "bat_temp": 24, "charg_flag": 1, "dischrg_flag": 1},
        "es_mode": {"mode": mode},
        "es_status": {
            "bat_soc": 61,
            "bat_power": -800,
            "ongrid_power": 800,
            "total_grid_input_energy": 12345,
            "total_grid_output_energy": 6789,
            "total_pv_energy": 250,
        },
        "em_status": {
            "ct_state": 1,
            "a_power": 120,
            "total_power": 120,
            "input_energy": 5000,
            "output_energy": 2000,
        },
        "wifi": {"rssi": -55, "sta_ip": "192.168.2.178"},
    }


@pytest.fixture
def api():
    """Patch the UDP client with a stub and hand the stub to the test."""
    with patch(
        "custom_components.marstek_ha.coordinator.MarstekAPI", autospec=True
    ) as api_class:
        client = api_class.return_value
        client.host = "192.168.2.178"
        client.get_all_data = AsyncMock(return_value=_sample_data())
        client.set_es_mode = AsyncMock(return_value=True)
        client.set_passive_power = AsyncMock(return_value=True)
        client.set_dod = AsyncMock(return_value=True)
        client.async_close = AsyncMock()
        yield client


@pytest.fixture
async def entry(hass: HomeAssistant, api) -> MockConfigEntry:
    """Set up a configured Marstek entry."""
    config_entry = MockConfigEntry(
        domain=DOMAIN,
        version=2,
        unique_id="aabbcc",
        title="Venus E",
        data={CONF_DEVICE_IP: "192.168.2.178", CONF_DEVICE_PORT: 30000},
        # No spacing between writes, so tests do not have to wait it out.
        options={CONF_MIN_WRITE_INTERVAL: 0},
    )
    config_entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(config_entry.entry_id)
    await hass.async_block_till_done()
    return config_entry


async def test_entities_are_created_and_scaled(hass: HomeAssistant, entry) -> None:
    """Sensors read the right fields and apply the documented scaling."""
    assert hass.states.get("sensor.venus_e_battery_state_of_charge").state == "61"
    assert hass.states.get("sensor.venus_e_total_solar_energy") is None  # disabled
    # meter input_energy is in units of 0.1 Wh -> 5000 means 0.5 kWh.
    assert hass.states.get("sensor.venus_e_meter_input_energy").state == "0.5"
    # total_grid_input_energy is in Wh -> 12345 means 12.345 kWh.
    assert (
        hass.states.get("sensor.venus_e_total_grid_input_energy").state == "12.345"
    )
    # bat_power is negative while charging, so charging power is its magnitude.
    assert hass.states.get("sensor.venus_e_charging_power").state == "800.0"
    assert hass.states.get("sensor.venus_e_discharging_power").state == "0.0"


async def test_unsigned_power_field_is_reinterpreted(
    hass: HomeAssistant, entry, api
) -> None:
    """A uint16 wrap-around must be read back as the small negative it is.

    The device reports offgrid_power unsigned, so -12 W arrives as 65524. The
    correction is applied to every power field, checked here on two that are
    enabled by default.
    """
    data = _sample_data()
    data["es_status"]["ongrid_power"] = 65524
    data["em_status"]["a_power"] = 64682  # -854 W
    api.get_all_data.return_value = data
    await entry.runtime_data.async_refresh()
    await hass.async_block_till_done()

    assert hass.states.get("sensor.venus_e_grid_power").state == "-12.0"
    assert hass.states.get("sensor.venus_e_phase_a_power").state == "-854.0"


async def test_battery_power_falls_back_to_grid_power(
    hass: HomeAssistant, entry, api
) -> None:
    """Firmware that omits bat_power still yields charge/discharge figures.

    Firmware 150 on Venus E 3.0 does not report bat_power; ongrid_power
    carries the same sign convention and stands in for it.
    """
    data = _sample_data()
    del data["es_status"]["bat_power"]
    data["es_status"]["ongrid_power"] = -2491
    api.get_all_data.return_value = data
    await entry.runtime_data.async_refresh()
    await hass.async_block_till_done()

    assert hass.states.get("sensor.venus_e_battery_power").state == "-2491.0"
    assert hass.states.get("sensor.venus_e_charging_power").state == "2491.0"
    assert hass.states.get("sensor.venus_e_discharging_power").state == "0.0"


async def test_single_failed_poll_keeps_entities_available(
    hass: HomeAssistant, entry, api
) -> None:
    """A lost poll must not make entities unavailable."""
    coordinator = entry.runtime_data
    api.get_all_data.return_value = dict.fromkeys(_sample_data(), None)

    for _ in range(MAX_CONSECUTIVE_FAILURES - 1):
        await coordinator.async_refresh()

    assert coordinator.last_update_success is True
    assert hass.states.get("sensor.venus_e_battery_state_of_charge").state == "61"


async def test_repeated_failures_eventually_mark_unavailable(
    hass: HomeAssistant, entry, api
) -> None:
    """Sustained silence from the device does surface as unavailable."""
    coordinator = entry.runtime_data
    api.get_all_data.return_value = dict.fromkeys(_sample_data(), None)

    for _ in range(MAX_CONSECUTIVE_FAILURES):
        await coordinator.async_refresh()

    assert coordinator.last_update_success is False


async def test_partial_poll_keeps_previous_values(
    hass: HomeAssistant, entry, api
) -> None:
    """An endpoint that goes unanswered keeps its last known reading."""
    coordinator = entry.runtime_data
    partial = _sample_data()
    partial["battery"] = None
    api.get_all_data.return_value = partial

    await coordinator.async_refresh()

    assert coordinator.data["battery"]["soc"] == 61


async def test_duplicate_passive_setpoint_is_suppressed(
    hass: HomeAssistant, entry, api
) -> None:
    """Re-sending an unchanged setpoint while in Passive mode is a no-op."""
    coordinator = entry.runtime_data
    api.get_all_data.return_value = _sample_data(mode="Passive")
    await coordinator.async_refresh()

    assert await coordinator.async_set_passive_power(-800, 30)
    assert api.set_passive_power.await_count == 1

    assert await coordinator.async_set_passive_power(-800, 30)
    assert api.set_passive_power.await_count == 1

    # A changed setpoint must go through.
    assert await coordinator.async_set_passive_power(-600, 30)
    assert api.set_passive_power.await_count == 2


async def test_identical_setpoint_rearms_after_countdown_expired(
    hass: HomeAssistant, entry, api
) -> None:
    """Once the device has left Passive, the same setpoint is a real re-arm."""
    coordinator = entry.runtime_data
    api.get_all_data.return_value = _sample_data(mode="Passive")
    await coordinator.async_refresh()

    await coordinator.async_set_passive_power(-800, 30)
    assert api.set_passive_power.await_count == 1

    # Countdown elapsed: the device fell back to Auto on its own.
    api.get_all_data.return_value = _sample_data(mode="Auto")
    await coordinator.async_refresh()

    await coordinator.async_set_passive_power(-800, 30)
    assert api.set_passive_power.await_count == 2


async def test_service_sets_passive_power(hass: HomeAssistant, entry, api) -> None:
    """The service targets a device and issues one combined command."""
    from homeassistant.helpers import device_registry as dr

    device = dr.async_get(hass).async_get_device(identifiers={(DOMAIN, "aabbcc")})
    assert device is not None

    await hass.services.async_call(
        DOMAIN,
        "set_passive_power",
        {"device_id": device.id, "power": -1200, "cd_time": 30},
        blocking=True,
    )

    api.set_passive_power.assert_awaited_once_with(-1200, 30)


async def test_selecting_passive_carries_current_setpoint(
    hass: HomeAssistant, entry, api
) -> None:
    """Switching to Passive via the select must not push an arbitrary power."""
    coordinator = entry.runtime_data
    coordinator.passive_power = -500
    coordinator.passive_cd_time = 60

    await hass.services.async_call(
        "select",
        "select_option",
        {"entity_id": "select.venus_e_energy_storage_mode", "option": "Passive"},
        blocking=True,
    )

    api.set_passive_power.assert_awaited_once_with(-500, 60)
    api.set_es_mode.assert_not_awaited()
