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


# Firmware build at which bat_temp is reported directly in °C (API-conformant).
# Older builds scaled the value ×10 (e.g. 250 = 25.0 °C).
_BAT_TEMP_DIRECT_FW = 147


def _battery_temperature(data: dict) -> float | None:
    """Return battery temperature in °C, handling firmware-dependent scaling."""
    raw = _safe_get(data, "battery", "bat_temp")
    if raw is None:
        return None
    fw = _safe_get(data, "device", "ver")
    try:
        if fw is not None and int(fw) >= _BAT_TEMP_DIRECT_FW:
            return float(raw)
    except (TypeError, ValueError):
        pass
    return float(raw) / 10.0


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
        value_fn=_battery_temperature,
    ),
    MarstekSensorEntityDescription(
        key="battery_capacity",
        name="Battery Capacity",
        native_unit_of_measurement=UnitOfEnergy.WATT_HOUR,
        device_class=SensorDeviceClass.ENERGY_STORAGE,
        state_class=SensorStateClass.MEASUREMENT,
        # bat_capacity is reported directly in Wh per API docs
        value_fn=lambda data: _safe_get(data, "battery", "bat_capacity"),
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
        # Single-phase Venus models always report 0 here; opt-in for 3-phase devices.
        entity_registry_enabled_default=False,
        value_fn=lambda data: _safe_get(data, "es_mode", "b_power"),
    ),
    MarstekSensorEntityDescription(
        key="phase_c_power",
        name="Phase C Power",
        native_unit_of_measurement=UnitOfPower.WATT,
        device_class=SensorDeviceClass.POWER,
        state_class=SensorStateClass.MEASUREMENT,
        entity_registry_enabled_default=False,
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
    # ES.GetMode cumulative energy (value * 0.1 = Wh per API docs).
    # Disabled by default: on Venus E these stay 0; the authoritative cumulative
    # counters come from ES.GetStatus (total_grid_input_energy / ..._output_energy).
    MarstekSensorEntityDescription(
        key="input_energy",
        name="Cumulative Input Energy",
        native_unit_of_measurement=UnitOfEnergy.WATT_HOUR,
        device_class=SensorDeviceClass.ENERGY,
        state_class=SensorStateClass.TOTAL_INCREASING,
        entity_registry_enabled_default=False,
        value_fn=lambda data: _safe_get(data, "es_mode", "input_energy") * 0.1 if _safe_get(data, "es_mode", "input_energy") is not None else None,
    ),
    MarstekSensorEntityDescription(
        key="output_energy",
        name="Cumulative Output Energy",
        native_unit_of_measurement=UnitOfEnergy.WATT_HOUR,
        device_class=SensorDeviceClass.ENERGY,
        state_class=SensorStateClass.TOTAL_INCREASING,
        entity_registry_enabled_default=False,
        value_fn=lambda data: _safe_get(data, "es_mode", "output_energy") * 0.1 if _safe_get(data, "es_mode", "output_energy") is not None else None,
    ),

    # ── ES statistics sensors (from ES.GetStatus) ──
    # Solar sensors disabled by default: only Venus variants with a PV input
    # populate these. Users of PV-capable devices can enable them in the UI.
    MarstekSensorEntityDescription(
        key="pv_power",
        name="Solar Power",
        native_unit_of_measurement=UnitOfPower.WATT,
        device_class=SensorDeviceClass.POWER,
        state_class=SensorStateClass.MEASUREMENT,
        icon="mdi:solar-power",
        entity_registry_enabled_default=False,
        value_fn=lambda data: _safe_get(data, "es_status", "pv_power"),
    ),
    MarstekSensorEntityDescription(
        key="total_pv_energy",
        name="Total Solar Energy",
        native_unit_of_measurement=UnitOfEnergy.WATT_HOUR,
        device_class=SensorDeviceClass.ENERGY,
        state_class=SensorStateClass.TOTAL_INCREASING,
        icon="mdi:solar-power",
        entity_registry_enabled_default=False,
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
        # Per API: "total load (or off-grid) energy consumed" — effectively 0
        # for on-grid installations without UPS/off-grid load.
        entity_registry_enabled_default=False,
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
        device_id = entry.unique_id or entry.entry_id
        self._attr_unique_id = f"{device_id}_{description.key}"

        device_data = coordinator.data.get("device") or {}
        device_name = device_data.get("device", "Unknown")
        firmware_ver = device_data.get("ver", "Unknown")

        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, device_id)},
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
