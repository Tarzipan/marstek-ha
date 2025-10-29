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
    UnitOfElectricCurrent,
    UnitOfElectricPotential,
    UnitOfEnergy,
    UnitOfPower,
    UnitOfTemperature,
    SIGNAL_STRENGTH_DECIBELS_MILLIWATT,
)
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DOMAIN
from .coordinator import MarstekDataUpdateCoordinator

_LOGGER = logging.getLogger(__name__)


@dataclass
class MarstekSensorEntityDescription(SensorEntityDescription):
    """Describes Marstek sensor entity."""

    value_fn: Callable[[dict[str, Any]], Any] | None = None


# Only sensors for data that is actually available from VenusE 3.0
SENSOR_TYPES: tuple[MarstekSensorEntityDescription, ...] = (
    # Battery sensors (from Bat.GetStatus)
    MarstekSensorEntityDescription(
        key="battery_soc",
        name="Battery State of Charge",
        native_unit_of_measurement=PERCENTAGE,
        device_class=SensorDeviceClass.BATTERY,
        state_class=SensorStateClass.MEASUREMENT,
        value_fn=lambda data: data.get("battery", {}).get("soc"),
    ),
    MarstekSensorEntityDescription(
        key="battery_temperature",
        name="Battery Temperature",
        native_unit_of_measurement=UnitOfTemperature.CELSIUS,
        device_class=SensorDeviceClass.TEMPERATURE,
        state_class=SensorStateClass.MEASUREMENT,
        # bat_temp is in °C * 10, so divide by 10
        value_fn=lambda data: data.get("battery", {}).get("bat_temp") / 10.0 if data.get("battery", {}).get("bat_temp") is not None else None,
    ),
    MarstekSensorEntityDescription(
        key="battery_capacity",
        name="Battery Capacity",
        native_unit_of_measurement=UnitOfEnergy.WATT_HOUR,
        device_class=SensorDeviceClass.ENERGY_STORAGE,
        state_class=SensorStateClass.MEASUREMENT,
        # bat_capacity is in Wh / 10, so multiply by 10
        value_fn=lambda data: data.get("battery", {}).get("bat_capacity") * 10.0 if data.get("battery", {}).get("bat_capacity") is not None else None,
    ),
    MarstekSensorEntityDescription(
        key="battery_rated_capacity",
        name="Battery Rated Capacity",
        native_unit_of_measurement=UnitOfEnergy.WATT_HOUR,
        device_class=SensorDeviceClass.ENERGY_STORAGE,
        value_fn=lambda data: data.get("battery", {}).get("rated_capacity"),
    ),
    # Energy Storage sensors (from ES.GetMode)
    MarstekSensorEntityDescription(
        key="es_mode",
        name="Energy Storage Mode",
        value_fn=lambda data: data.get("es_mode", {}).get("mode") if isinstance(data.get("es_mode"), dict) else None,
    ),
    MarstekSensorEntityDescription(
        key="grid_power",
        name="Grid Power",
        native_unit_of_measurement=UnitOfPower.WATT,
        device_class=SensorDeviceClass.POWER,
        state_class=SensorStateClass.MEASUREMENT,
        # ongrid_power: negative = feeding to grid, positive = consuming from grid
        value_fn=lambda data: data.get("es_mode", {}).get("ongrid_power") if isinstance(data.get("es_mode"), dict) else None,
    ),

    MarstekSensorEntityDescription(
        key="battery_charging_power",
        name="Battery Charging Power",
        native_unit_of_measurement=UnitOfPower.WATT,
        device_class=SensorDeviceClass.POWER,
        state_class=SensorStateClass.MEASUREMENT,
        icon="mdi:battery-charging",
        # Positive value when battery is charging (ongrid_power < 0 = feeding to grid = charging)
        value_fn=lambda data: abs(data.get("es_mode", {}).get("ongrid_power", 0)) if isinstance(data.get("es_mode"), dict) and data.get("es_mode", {}).get("ongrid_power", 0) < 0 else 0,
    ),
    MarstekSensorEntityDescription(
        key="battery_discharging_power",
        name="Battery Discharging Power",
        native_unit_of_measurement=UnitOfPower.WATT,
        device_class=SensorDeviceClass.POWER,
        state_class=SensorStateClass.MEASUREMENT,
        icon="mdi:battery-minus",
        # Positive value when battery is discharging (ongrid_power > 0 = consuming from grid = discharging)
        value_fn=lambda data: data.get("es_mode", {}).get("ongrid_power", 0) if isinstance(data.get("es_mode"), dict) and data.get("es_mode", {}).get("ongrid_power", 0) > 0 else 0,
    ),
    MarstekSensorEntityDescription(
        key="offgrid_power",
        name="Off-Grid Power",
        native_unit_of_measurement=UnitOfPower.WATT,
        device_class=SensorDeviceClass.POWER,
        state_class=SensorStateClass.MEASUREMENT,
        value_fn=lambda data: data.get("es_mode", {}).get("offgrid_power") if isinstance(data.get("es_mode"), dict) else None,
    ),
    MarstekSensorEntityDescription(
        key="phase_a_power",
        name="Phase A Power",
        native_unit_of_measurement=UnitOfPower.WATT,
        device_class=SensorDeviceClass.POWER,
        state_class=SensorStateClass.MEASUREMENT,
        value_fn=lambda data: data.get("es_mode", {}).get("a_power") if isinstance(data.get("es_mode"), dict) else None,
    ),
    MarstekSensorEntityDescription(
        key="phase_b_power",
        name="Phase B Power",
        native_unit_of_measurement=UnitOfPower.WATT,
        device_class=SensorDeviceClass.POWER,
        state_class=SensorStateClass.MEASUREMENT,
        value_fn=lambda data: data.get("es_mode", {}).get("b_power") if isinstance(data.get("es_mode"), dict) else None,
    ),
    MarstekSensorEntityDescription(
        key="phase_c_power",
        name="Phase C Power",
        native_unit_of_measurement=UnitOfPower.WATT,
        device_class=SensorDeviceClass.POWER,
        state_class=SensorStateClass.MEASUREMENT,
        value_fn=lambda data: data.get("es_mode", {}).get("c_power") if isinstance(data.get("es_mode"), dict) else None,
    ),
    MarstekSensorEntityDescription(
        key="total_power",
        name="Total Power",
        native_unit_of_measurement=UnitOfPower.WATT,
        device_class=SensorDeviceClass.POWER,
        state_class=SensorStateClass.MEASUREMENT,
        value_fn=lambda data: data.get("es_mode", {}).get("total_power") if isinstance(data.get("es_mode"), dict) else None,
    ),
    # Device info sensors (from Marstek.GetDevice)
    MarstekSensorEntityDescription(
        key="firmware_version",
        name="Firmware Version",
        value_fn=lambda data: data.get("device", {}).get("ver"),
    ),
    MarstekSensorEntityDescription(
        key="wifi_ssid",
        name="WiFi SSID",
        value_fn=lambda data: data.get("device", {}).get("wifi_name"),
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

        # Get device info from coordinator data
        device_info = coordinator.data.get("device", {})
        device_name = device_info.get("device", "Unknown")
        firmware_ver = device_info.get("ver", "Unknown")

        self._attr_device_info = {
            "identifiers": {(DOMAIN, entry.entry_id)},
            "name": entry.title,
            "manufacturer": "Marstek",
            "model": device_name,
            "sw_version": str(firmware_ver),
        }

    @property
    def native_value(self) -> Any:
        """Return the state of the sensor."""
        if self.entity_description.value_fn is None:
            return None
        
        value = self.entity_description.value_fn(self.coordinator.data)
        
        if value is None:
            return None
        
        return value

    @property
    def available(self) -> bool:
        """Return if entity is available."""
        return (
            self.coordinator.last_update_success
            and self.native_value is not None
        )

