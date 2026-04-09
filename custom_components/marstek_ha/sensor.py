"""Sensor platform for Marstek."""
from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
import logging
from typing import Any

from homeassistant.components.sensor import (
    SensorDeviceClass,
    SensorEntity,
    SensorEntityDescription,
    SensorStateClass,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import (
    PERCENTAGE,
    UnitOfEnergy,
    UnitOfPower,
    UnitOfTemperature,
)
from homeassistant.core import HomeAssistant
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DOMAIN
from .coordinator import MarstekDataUpdateCoordinator

_LOGGER = logging.getLogger(__name__)


@dataclass
class MarstekSensorEntityDescription(SensorEntityDescription):
    """Describes Marstek sensor entity."""

    value_fn: Callable[[dict[str, Any]], Any] | None = None


def _safe_get(data: dict, *keys: str) -> Any:
    """Safely traverse nested dict keys, returning None if any key is missing."""
    current = data
    for key in keys:
        if not isinstance(current, dict):
            return None
        current = current.get(key)
        if current is None:
            return None
    return current


SENSOR_TYPES: tuple[MarstekSensorEntityDescription, ...] = (
    # ── Battery sensors (from Bat.GetStatus) ──
    MarstekSensorEntityDescription(
        key="battery_soc",
        name="Battery State of Charge",
        native_unit_of_measurement=PERCENTAGE,
        device_class=SensorDeviceClass.BATTERY,
        state_class=SensorStateClass.MEASUREMENT,
        value_fn=lambda data: _safe_get(data, "battery", "soc"),
    ),
    MarstekSensorEntityDescription(
        key="battery_temperature",
        name="Battery Temperature",
        native_unit_of_measurement=UnitOfTemperature.CELSIUS,
        device_class=SensorDeviceClass.TEMPERATURE,
        state_class=SensorStateClass.MEASUREMENT,
        # Note: VenusE may report bat_temp scaled by 10 (e.g. 250 = 25.0°C).
        # The API doc example shows 25.0 directly. Keeping /10 based on real device data.
        value_fn=lambda data: _safe_get(data, "battery", "bat_temp") / 10.0 if _safe_get(data, "battery", "bat_temp") is not None else None,
    ),
    MarstekSensorEntityDescription(
        key="battery_capacity",
        name="Battery Capacity",
        native_unit_of_measurement=UnitOfEnergy.WATT_HOUR,
        device_class=SensorDeviceClass.ENERGY_STORAGE,
        state_class=SensorStateClass.MEASUREMENT,
        # Note: VenusE may report bat_capacity scaled by 0.1 (e.g. 25.6 = 256 Wh).
        # The API doc example shows 256.0 directly. Keeping *10 based on real device data.
        value_fn=lambda data: _safe_get(data, "battery", "bat_capacity") * 10.0 if _safe_get(data, "battery", "bat_capacity") is not None else None,
    ),
    MarstekSensorEntityDescription(
        key="battery_rated_capacity",
        name="Battery Rated Capacity",
        native_unit_of_measurement=UnitOfEnergy.WATT_HOUR,
        device_class=SensorDeviceClass.ENERGY_STORAGE,
        value_fn=lambda data: _safe_get(data, "battery", "rated_capacity"),
    ),

    # ── ES realtime sensors (from ES.GetMode) ──
    MarstekSensorEntityDescription(
        key="es_mode",
        name="Energy Storage Mode",
        value_fn=lambda data: _safe_get(data, "es_mode", "mode"),
    ),
    MarstekSensorEntityDescription(
        key="grid_power",
        name="Grid Power",
        native_unit_of_measurement=UnitOfPower.WATT,
        device_class=SensorDeviceClass.POWER,
        state_class=SensorStateClass.MEASUREMENT,
        value_fn=lambda data: _safe_get(data, "es_mode", "ongrid_power"),
    ),
    MarstekSensorEntityDescription(
        key="battery_charging_power",
        name="Battery Charging Power",
        native_unit_of_measurement=UnitOfPower.WATT,
        device_class=SensorDeviceClass.POWER,
        state_class=SensorStateClass.MEASUREMENT,
        icon="mdi:battery-charging",
        # Positive value when battery is charging (ongrid_power < 0)
        value_fn=lambda data: abs(_safe_get(data, "es_mode", "ongrid_power") or 0) if (_safe_get(data, "es_mode", "ongrid_power") or 0) < 0 else 0,
    ),
    MarstekSensorEntityDescription(
        key="battery_discharging_power",
        name="Battery Discharging Power",
        native_unit_of_measurement=UnitOfPower.WATT,
        device_class=SensorDeviceClass.POWER,
        state_class=SensorStateClass.MEASUREMENT,
        icon="mdi:battery-minus",
        # Positive value when battery is discharging (ongrid_power > 0)
        value_fn=lambda data: (_safe_get(data, "es_mode", "ongrid_power") or 0) if (_safe_get(data, "es_mode", "ongrid_power") or 0) > 0 else 0,
    ),
    MarstekSensorEntityDescription(
        key="offgrid_power",
        name="Off-Grid Power",
        native_unit_of_measurement=UnitOfPower.WATT,
        device_class=SensorDeviceClass.POWER,
        state_class=SensorStateClass.MEASUREMENT,
        value_fn=lambda data: _safe_get(data, "es_mode", "offgrid_power"),
    ),
    MarstekSensorEntityDescription(
        key="phase_a_power",
        name="Phase A Power",
        native_unit_of_measurement=UnitOfPower.WATT,
        device_class=SensorDeviceClass.POWER,
        state_class=SensorStateClass.MEASUREMENT,
        value_fn=lambda data: _safe_get(data, "es_mode", "a_power"),
    ),
    MarstekSensorEntityDescription(
        key="phase_b_power",
        name="Phase B Power",
        native_unit_of_measurement=UnitOfPower.WATT,
        device_class=SensorDeviceClass.POWER,
        state_class=SensorStateClass.MEASUREMENT,
        value_fn=lambda data: _safe_get(data, "es_mode", "b_power"),
    ),
    MarstekSensorEntityDescription(
        key="phase_c_power",
        name="Phase C Power",
        native_unit_of_measurement=UnitOfPower.WATT,
        device_class=SensorDeviceClass.POWER,
        state_class=SensorStateClass.MEASUREMENT,
        value_fn=lambda data: _safe_get(data, "es_mode", "c_power"),
    ),
    MarstekSensorEntityDescription(
        key="total_power",
        name="Total Power",
        native_unit_of_measurement=UnitOfPower.WATT,
        device_class=SensorDeviceClass.POWER,
        state_class=SensorStateClass.MEASUREMENT,
        value_fn=lambda data: _safe_get(data, "es_mode", "total_power"),
    ),
    # ES.GetMode cumulative energy (value * 0.1 = Wh per API docs)
    MarstekSensorEntityDescription(
        key="input_energy",
        name="Cumulative Input Energy",
        native_unit_of_measurement=UnitOfEnergy.WATT_HOUR,
        device_class=SensorDeviceClass.ENERGY,
        state_class=SensorStateClass.TOTAL_INCREASING,
        value_fn=lambda data: _safe_get(data, "es_mode", "input_energy") * 0.1 if _safe_get(data, "es_mode", "input_energy") is not None else None,
    ),
    MarstekSensorEntityDescription(
        key="output_energy",
        name="Cumulative Output Energy",
        native_unit_of_measurement=UnitOfEnergy.WATT_HOUR,
        device_class=SensorDeviceClass.ENERGY,
        state_class=SensorStateClass.TOTAL_INCREASING,
        value_fn=lambda data: _safe_get(data, "es_mode", "output_energy") * 0.1 if _safe_get(data, "es_mode", "output_energy") is not None else None,
    ),

    # ── ES statistics sensors (from ES.GetStatus) ──
    MarstekSensorEntityDescription(
        key="pv_power",
        name="Solar Power",
        native_unit_of_measurement=UnitOfPower.WATT,
        device_class=SensorDeviceClass.POWER,
        state_class=SensorStateClass.MEASUREMENT,
        icon="mdi:solar-power",
        value_fn=lambda data: _safe_get(data, "es_status", "pv_power"),
    ),
    MarstekSensorEntityDescription(
        key="bat_power",
        name="Battery Power",
        native_unit_of_measurement=UnitOfPower.WATT,
        device_class=SensorDeviceClass.POWER,
        state_class=SensorStateClass.MEASUREMENT,
        value_fn=lambda data: _safe_get(data, "es_status", "bat_power"),
    ),
    MarstekSensorEntityDescription(
        key="total_pv_energy",
        name="Total Solar Energy",
        native_unit_of_measurement=UnitOfEnergy.WATT_HOUR,
        device_class=SensorDeviceClass.ENERGY,
        state_class=SensorStateClass.TOTAL_INCREASING,
        icon="mdi:solar-power",
        value_fn=lambda data: _safe_get(data, "es_status", "total_pv_energy"),
    ),
    MarstekSensorEntityDescription(
        key="total_grid_output_energy",
        name="Total Grid Output Energy",
        native_unit_of_measurement=UnitOfEnergy.WATT_HOUR,
        device_class=SensorDeviceClass.ENERGY,
        state_class=SensorStateClass.TOTAL_INCREASING,
        value_fn=lambda data: _safe_get(data, "es_status", "total_grid_output_energy"),
    ),
    MarstekSensorEntityDescription(
        key="total_grid_input_energy",
        name="Total Grid Input Energy",
        native_unit_of_measurement=UnitOfEnergy.WATT_HOUR,
        device_class=SensorDeviceClass.ENERGY,
        state_class=SensorStateClass.TOTAL_INCREASING,
        value_fn=lambda data: _safe_get(data, "es_status", "total_grid_input_energy"),
    ),
    MarstekSensorEntityDescription(
        key="total_load_energy",
        name="Total Load Energy",
        native_unit_of_measurement=UnitOfEnergy.WATT_HOUR,
        device_class=SensorDeviceClass.ENERGY,
        state_class=SensorStateClass.TOTAL_INCREASING,
        value_fn=lambda data: _safe_get(data, "es_status", "total_load_energy"),
    ),

    # ── Device info sensors (from Marstek.GetDevice) ──
    MarstekSensorEntityDescription(
        key="firmware_version",
        name="Firmware Version",
        value_fn=lambda data: _safe_get(data, "device", "ver"),
    ),
    MarstekSensorEntityDescription(
        key="wifi_ssid",
        name="WiFi SSID",
        value_fn=lambda data: _safe_get(data, "device", "wifi_name"),
    ),
)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up Marstek sensor based on a config entry."""
    coordinator: MarstekDataUpdateCoordinator = hass.data[DOMAIN][entry.entry_id]

    async_add_entities(
        MarstekSensor(coordinator, description, entry)
        for description in SENSOR_TYPES
    )


class MarstekSensor(CoordinatorEntity[MarstekDataUpdateCoordinator], SensorEntity):
    """Representation of a Marstek sensor."""

    entity_description: MarstekSensorEntityDescription
    _attr_has_entity_name = True

    def __init__(
        self,
        coordinator: MarstekDataUpdateCoordinator,
        description: MarstekSensorEntityDescription,
        entry: ConfigEntry,
    ) -> None:
        """Initialize the sensor."""
        super().__init__(coordinator)
        self.entity_description = description
        self._attr_unique_id = f"{entry.entry_id}_{description.key}"

        device_data = coordinator.data.get("device") or {}
        device_name = device_data.get("device", "Unknown")
        firmware_ver = device_data.get("ver", "Unknown")

        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, entry.entry_id)},
            name=entry.title,
            manufacturer="Marstek",
            model=device_name,
            sw_version=str(firmware_ver),
        )

    def _get_native_value(self) -> Any:
        """Extract value from coordinator data."""
        if self.entity_description.value_fn is None:
            return None
        return self.entity_description.value_fn(self.coordinator.data)

    @property
    def native_value(self) -> Any:
        """Return the state of the sensor."""
        return self._get_native_value()

    @property
    def available(self) -> bool:
        """Return if entity is available."""
        return (
            self.coordinator.last_update_success
            and self._get_native_value() is not None
        )
