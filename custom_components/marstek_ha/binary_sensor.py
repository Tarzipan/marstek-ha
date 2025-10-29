"""Binary sensor platform for Marstek."""
from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
import logging
from typing import Any

from homeassistant.components.binary_sensor import (
    BinarySensorDeviceClass,
    BinarySensorEntity,
    BinarySensorEntityDescription,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DOMAIN
from .coordinator import MarstekDataUpdateCoordinator

_LOGGER = logging.getLogger(__name__)


@dataclass
class MarstekBinarySensorEntityDescription(BinarySensorEntityDescription):
    """Describes Marstek binary sensor entity."""

    value_fn: Callable[[dict[str, Any]], bool | None] | None = None


# Only binary sensors for data that is actually available from VenusE 3.0
BINARY_SENSOR_TYPES: tuple[MarstekBinarySensorEntityDescription, ...] = (
    # Battery status flags (from Bat.GetStatus)
    # These indicate if charging/discharging is ALLOWED, not if it's currently happening
    # For actual charging/discharging status, see the power sensors
    MarstekBinarySensorEntityDescription(
        key="battery_charging_allowed",
        name="Battery Charging Allowed",
        device_class=BinarySensorDeviceClass.POWER,
        icon="mdi:battery-charging-check",
        value_fn=lambda data: data.get("battery", {}).get("charg_flag"),
    ),
    MarstekBinarySensorEntityDescription(
        key="battery_discharging_allowed",
        name="Battery Discharging Allowed",
        device_class=BinarySensorDeviceClass.POWER,
        icon="mdi:battery-minus-check",
        value_fn=lambda data: data.get("battery", {}).get("dischrg_flag"),
    ),
)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up Marstek binary sensor based on a config entry."""
    coordinator: MarstekDataUpdateCoordinator = hass.data[DOMAIN][entry.entry_id]

    async_add_entities(
        MarstekBinarySensor(coordinator, description, entry)
        for description in BINARY_SENSOR_TYPES
    )


class MarstekBinarySensor(CoordinatorEntity[MarstekDataUpdateCoordinator], BinarySensorEntity):
    """Representation of a Marstek binary sensor."""

    entity_description: MarstekBinarySensorEntityDescription
    _attr_has_entity_name = True

    def __init__(
        self,
        coordinator: MarstekDataUpdateCoordinator,
        description: MarstekBinarySensorEntityDescription,
        entry: ConfigEntry,
    ) -> None:
        """Initialize the binary sensor."""
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
    def is_on(self) -> bool | None:
        """Return true if the binary sensor is on."""
        if self.entity_description.value_fn is None:
            return None
        
        value = self.entity_description.value_fn(self.coordinator.data)
        
        if value is None:
            return None
        
        return bool(value)

    @property
    def available(self) -> bool:
        """Return if entity is available."""
        return (
            self.coordinator.last_update_success
            and self.is_on is not None
        )

