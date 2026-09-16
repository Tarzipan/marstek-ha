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
from homeassistant.const import (
    PERCENTAGE,
    SIGNAL_STRENGTH_DECIBELS_MILLIWATT,
    EntityCategory,
    UnitOfEnergy,
    UnitOfPower,
    UnitOfTemperature,
)
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import (
    DATA_BATTERY,
    DATA_DEVICE,
    DATA_EM_STATUS,
    DATA_ES_MODE,
    DATA_ES_STATUS,
    DATA_WIFI,
)
from .coordinator import MarstekConfigEntry, MarstekDataUpdateCoordinator
from .entity import MarstekEntity, safe_get

_LOGGER = logging.getLogger(__name__)


@dataclass(frozen=True, kw_only=True)
class MarstekSensorEntityDescription(SensorEntityDescription):
    """Describes a Marstek sensor."""

    value_fn: Callable[[dict[str, Any]], Any]


def _scaled(factor: float, *keys: str) -> Callable[[dict[str, Any]], Any]:
    """Build a value function that multiplies a raw field by a fixed factor."""

    def _value(data: dict[str, Any]) -> Any:
        raw = safe_get(data, *keys)
        if raw is None:
            return None
        try:
            return round(float(raw) * factor, 3)
        except (TypeError, ValueError):
            return None

    return _value


def _plain(*keys: str) -> Callable[[dict[str, Any]], Any]:
    """Build a value function that returns a raw field unchanged."""
    return lambda data: safe_get(data, *keys)


# Firmware build at which bat_temp is reported directly in degrees Celsius.
# Older builds scaled the value by ten (e.g. 250 meaning 25.0 C).
_BAT_TEMP_DIRECT_FW = 147


def _battery_temperature(data: dict[str, Any]) -> float | None:
    """Return battery temperature in C, handling firmware-dependent scaling."""
    raw = safe_get(data, DATA_BATTERY, "bat_temp")
    if raw is None:
        return None
    firmware = safe_get(data, DATA_DEVICE, "ver")
    try:
        if firmware is not None and int(firmware) >= _BAT_TEMP_DIRECT_FW:
            return float(raw)
    except (TypeError, ValueError):
        pass
    return float(raw) / 10.0


def _battery_power_direction(discharging: bool) -> Callable[[dict[str, Any]], Any]:
    """Split the signed battery power into a charge and a discharge sensor.

    ES.GetStatus.bat_power is positive while discharging and negative while
    charging. The Energy dashboard wants two non-negative figures instead.
    """

    def _value(data: dict[str, Any]) -> float | None:
        raw = safe_get(data, DATA_ES_STATUS, "bat_power")
        if raw is None:
            return None
        try:
            power = float(raw)
        except (TypeError, ValueError):
            return None
        if discharging:
            return power if power > 0 else 0.0
        return -power if power < 0 else 0.0

    return _value


SENSOR_TYPES: tuple[MarstekSensorEntityDescription, ...] = (
    # -- Battery (Bat.GetStatus) --------------------------------------------
    MarstekSensorEntityDescription(
        key="battery_soc",
        translation_key="battery_soc",
        native_unit_of_measurement=PERCENTAGE,
        device_class=SensorDeviceClass.BATTERY,
        state_class=SensorStateClass.MEASUREMENT,
        value_fn=_plain(DATA_BATTERY, "soc"),
    ),
    MarstekSensorEntityDescription(
        key="battery_temperature",
        translation_key="battery_temperature",
        native_unit_of_measurement=UnitOfTemperature.CELSIUS,
        device_class=SensorDeviceClass.TEMPERATURE,
        state_class=SensorStateClass.MEASUREMENT,
        value_fn=_battery_temperature,
    ),
    MarstekSensorEntityDescription(
        key="battery_capacity",
        translation_key="battery_capacity",
        native_unit_of_measurement=UnitOfEnergy.WATT_HOUR,
        device_class=SensorDeviceClass.ENERGY_STORAGE,
        state_class=SensorStateClass.MEASUREMENT,
        # bat_capacity is reported directly in Wh per API docs.
        value_fn=_plain(DATA_BATTERY, "bat_capacity"),
    ),
    MarstekSensorEntityDescription(
        key="battery_rated_capacity",
        translation_key="battery_rated_capacity",
        native_unit_of_measurement=UnitOfEnergy.WATT_HOUR,
        device_class=SensorDeviceClass.ENERGY_STORAGE,
        entity_category=EntityCategory.DIAGNOSTIC,
        value_fn=_plain(DATA_BATTERY, "rated_capacity"),
    ),

    # -- Energy storage power (ES.GetStatus) --------------------------------
    MarstekSensorEntityDescription(
        key="es_battery_soc",
        translation_key="es_battery_soc",
        native_unit_of_measurement=PERCENTAGE,
        device_class=SensorDeviceClass.BATTERY,
        state_class=SensorStateClass.MEASUREMENT,
        # Same quantity as battery_soc but sampled by the inverter rather than
        # the BMS; disabled by default to avoid two competing SoC sensors.
        entity_registry_enabled_default=False,
        value_fn=_plain(DATA_ES_STATUS, "bat_soc"),
    ),
    MarstekSensorEntityDescription(
        key="es_battery_capacity",
        translation_key="es_battery_capacity",
        native_unit_of_measurement=UnitOfEnergy.WATT_HOUR,
        device_class=SensorDeviceClass.ENERGY_STORAGE,
        state_class=SensorStateClass.MEASUREMENT,
        entity_registry_enabled_default=False,
        value_fn=_plain(DATA_ES_STATUS, "bat_cap"),
    ),
    MarstekSensorEntityDescription(
        key="battery_power",
        translation_key="battery_power",
        native_unit_of_measurement=UnitOfPower.WATT,
        device_class=SensorDeviceClass.POWER,
        state_class=SensorStateClass.MEASUREMENT,
        # Signed: positive while discharging, negative while charging.
        value_fn=_plain(DATA_ES_STATUS, "bat_power"),
    ),
    MarstekSensorEntityDescription(
        key="battery_charging_power",
        translation_key="battery_charging_power",
        native_unit_of_measurement=UnitOfPower.WATT,
        device_class=SensorDeviceClass.POWER,
        state_class=SensorStateClass.MEASUREMENT,
        icon="mdi:battery-charging",
        value_fn=_battery_power_direction(discharging=False),
    ),
    MarstekSensorEntityDescription(
        key="battery_discharging_power",
        translation_key="battery_discharging_power",
        native_unit_of_measurement=UnitOfPower.WATT,
        device_class=SensorDeviceClass.POWER,
        state_class=SensorStateClass.MEASUREMENT,
        icon="mdi:battery-minus",
        value_fn=_battery_power_direction(discharging=True),
    ),
    MarstekSensorEntityDescription(
        key="grid_power",
        translation_key="grid_power",
        native_unit_of_measurement=UnitOfPower.WATT,
        device_class=SensorDeviceClass.POWER,
        state_class=SensorStateClass.MEASUREMENT,
        value_fn=_plain(DATA_ES_STATUS, "ongrid_power"),
    ),
    MarstekSensorEntityDescription(
        key="offgrid_power",
        translation_key="offgrid_power",
        native_unit_of_measurement=UnitOfPower.WATT,
        device_class=SensorDeviceClass.POWER,
        state_class=SensorStateClass.MEASUREMENT,
        entity_registry_enabled_default=False,
        value_fn=_plain(DATA_ES_STATUS, "offgrid_power"),
    ),
    MarstekSensorEntityDescription(
        key="pv_power",
        translation_key="pv_power",
        native_unit_of_measurement=UnitOfPower.WATT,
        device_class=SensorDeviceClass.POWER,
        state_class=SensorStateClass.MEASUREMENT,
        icon="mdi:solar-power",
        # Only Venus variants with a PV input populate this.
        entity_registry_enabled_default=False,
        value_fn=_plain(DATA_ES_STATUS, "pv_power"),
    ),

    # -- Energy counters (ES.GetStatus) -------------------------------------
    # Scaling differs per field and is the reason these are usable in the
    # Energy dashboard at all -- see the unit comments on each entry.
    MarstekSensorEntityDescription(
        key="total_pv_energy",
        translation_key="total_pv_energy",
        native_unit_of_measurement=UnitOfEnergy.KILO_WATT_HOUR,
        device_class=SensorDeviceClass.ENERGY,
        state_class=SensorStateClass.TOTAL_INCREASING,
        icon="mdi:solar-power",
        entity_registry_enabled_default=False,
        # Reported in units of 0.01 kWh.
        value_fn=_scaled(0.01, DATA_ES_STATUS, "total_pv_energy"),
    ),
    MarstekSensorEntityDescription(
        key="total_grid_output_energy",
        translation_key="total_grid_output_energy",
        native_unit_of_measurement=UnitOfEnergy.WATT_HOUR,
        device_class=SensorDeviceClass.ENERGY,
        state_class=SensorStateClass.TOTAL_INCREASING,
        # Reported directly in Wh.
        value_fn=_plain(DATA_ES_STATUS, "total_grid_output_energy"),
    ),
    MarstekSensorEntityDescription(
        key="total_grid_input_energy",
        translation_key="total_grid_input_energy",
        native_unit_of_measurement=UnitOfEnergy.WATT_HOUR,
        device_class=SensorDeviceClass.ENERGY,
        state_class=SensorStateClass.TOTAL_INCREASING,
        # Reported directly in Wh.
        value_fn=_plain(DATA_ES_STATUS, "total_grid_input_energy"),
    ),
    MarstekSensorEntityDescription(
        key="total_load_energy",
        translation_key="total_load_energy",
        native_unit_of_measurement=UnitOfEnergy.WATT_HOUR,
        device_class=SensorDeviceClass.ENERGY,
        state_class=SensorStateClass.TOTAL_INCREASING,
        # Off-grid load only; stays at zero on a purely on-grid install.
        entity_registry_enabled_default=False,
        value_fn=_plain(DATA_ES_STATUS, "total_load_energy"),
    ),

    # -- Energy meter / CT (EM.GetStatus) -----------------------------------
    MarstekSensorEntityDescription(
        key="phase_a_power",
        translation_key="phase_a_power",
        native_unit_of_measurement=UnitOfPower.WATT,
        device_class=SensorDeviceClass.POWER,
        state_class=SensorStateClass.MEASUREMENT,
        value_fn=_plain(DATA_EM_STATUS, "a_power"),
    ),
    MarstekSensorEntityDescription(
        key="phase_b_power",
        translation_key="phase_b_power",
        native_unit_of_measurement=UnitOfPower.WATT,
        device_class=SensorDeviceClass.POWER,
        state_class=SensorStateClass.MEASUREMENT,
        value_fn=_plain(DATA_EM_STATUS, "b_power"),
    ),
    MarstekSensorEntityDescription(
        key="phase_c_power",
        translation_key="phase_c_power",
        native_unit_of_measurement=UnitOfPower.WATT,
        device_class=SensorDeviceClass.POWER,
        state_class=SensorStateClass.MEASUREMENT,
        value_fn=_plain(DATA_EM_STATUS, "c_power"),
    ),
    MarstekSensorEntityDescription(
        key="meter_total_power",
        translation_key="meter_total_power",
        native_unit_of_measurement=UnitOfPower.WATT,
        device_class=SensorDeviceClass.POWER,
        state_class=SensorStateClass.MEASUREMENT,
        value_fn=_plain(DATA_EM_STATUS, "total_power"),
    ),
    MarstekSensorEntityDescription(
        key="meter_input_energy",
        translation_key="meter_input_energy",
        native_unit_of_measurement=UnitOfEnergy.WATT_HOUR,
        device_class=SensorDeviceClass.ENERGY,
        state_class=SensorStateClass.TOTAL_INCREASING,
        # Reported in units of 0.1 Wh.
        value_fn=_scaled(0.1, DATA_EM_STATUS, "input_energy"),
    ),
    MarstekSensorEntityDescription(
        key="meter_output_energy",
        translation_key="meter_output_energy",
        native_unit_of_measurement=UnitOfEnergy.WATT_HOUR,
        device_class=SensorDeviceClass.ENERGY,
        state_class=SensorStateClass.TOTAL_INCREASING,
        # Reported in units of 0.1 Wh.
        value_fn=_scaled(0.1, DATA_EM_STATUS, "output_energy"),
    ),

    # -- Mode and diagnostics ------------------------------------------------
    MarstekSensorEntityDescription(
        key="es_mode",
        translation_key="es_mode",
        entity_category=EntityCategory.DIAGNOSTIC,
        value_fn=_plain(DATA_ES_MODE, "mode"),
    ),
    MarstekSensorEntityDescription(
        key="firmware_version",
        translation_key="firmware_version",
        entity_category=EntityCategory.DIAGNOSTIC,
        entity_registry_enabled_default=False,
        value_fn=_plain(DATA_DEVICE, "ver"),
    ),
    MarstekSensorEntityDescription(
        key="wifi_ssid",
        translation_key="wifi_ssid",
        entity_category=EntityCategory.DIAGNOSTIC,
        entity_registry_enabled_default=False,
        value_fn=_plain(DATA_DEVICE, "wifi_name"),
    ),
    MarstekSensorEntityDescription(
        key="wifi_rssi",
        translation_key="wifi_rssi",
        native_unit_of_measurement=SIGNAL_STRENGTH_DECIBELS_MILLIWATT,
        device_class=SensorDeviceClass.SIGNAL_STRENGTH,
        state_class=SensorStateClass.MEASUREMENT,
        entity_category=EntityCategory.DIAGNOSTIC,
        value_fn=_plain(DATA_WIFI, "rssi"),
    ),
    MarstekSensorEntityDescription(
        key="wifi_ip",
        translation_key="wifi_ip",
        entity_category=EntityCategory.DIAGNOSTIC,
        entity_registry_enabled_default=False,
        value_fn=_plain(DATA_WIFI, "sta_ip"),
    ),
)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: MarstekConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up Marstek sensors from a config entry."""
    coordinator = entry.runtime_data
    async_add_entities(
        MarstekSensor(coordinator, description) for description in SENSOR_TYPES
    )


class MarstekSensor(MarstekEntity, SensorEntity):
    """A Marstek sensor backed by one field of the polled data."""

    entity_description: MarstekSensorEntityDescription

    def __init__(
        self,
        coordinator: MarstekDataUpdateCoordinator,
        description: MarstekSensorEntityDescription,
    ) -> None:
        """Initialize the sensor."""
        super().__init__(coordinator, description.key, description)

    @property
    def native_value(self) -> Any:
        """Return the sensor value."""
        return self.entity_description.value_fn(self.coordinator.data or {})
