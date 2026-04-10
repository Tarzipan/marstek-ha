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
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DOMAIN
from .coordinator import MarstekDataUpdateCoordinator

_LOGGER = logging.getLogger(__name__)


@dataclass
class MarstekBinarySensorEntityDescription(BinarySensorEntityDescription):
    """Describes Marstek binary sensor entity."""

    value_fn: Callable[[dict[str, Any]], bool | None] | None = None


def _safe_get(data: dict, *keys: str) -> Any:
    """Safely traverse nested dict keys."""
    current = data
    for key in keys:
        if not isinstance(current, dict):
            return None
        current = current.get(key)
        if current is None:
            return None
    return current


BINARY_SENSOR_TYPES: tuple[MarstekBinarySensorEntityDescription, ...] = (
    MarstekBinarySensorEntityDescription(
        key="battery_charging_allowed",
        name="Battery Charging Allowed",
        device_class=BinarySensorDeviceClass.POWER,
        icon="mdi:battery-charging-check",
        value_fn=lambda data: _safe_get(data, "battery", "charg_flag"),
    ),
    MarstekBinarySensorEntityDescription(
        key="battery_discharging_allowed",
        name="Battery Discharging Allowed",
        device_class=BinarySensorDeviceClass.POWER,
        icon="mdi:battery-minus-check",
        value_fn=lambda data: _safe_get(data, "battery", "dischrg_flag"),
    ),
    MarstekBinarySensorEntityDescription(
        key="ct_connected",
        name="CT Connected",
        device_class=BinarySensorDeviceClass.CONNECTIVITY,
        # EM.GetStatus.ct_state is the authoritative source (always valid).
        # ES.GetMode.ct_state is only meaningful in Auto/AI mode per API docs,
        # so it's used only as a fallback when EM.GetStatus is unavailable.
        value_fn=lambda data: _safe_get(data, "em_status", "ct_state") if _safe_get(data, "em_status", "ct_state") is not None else _safe_get(data, "es_mode", "ct_state"),
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

    def _get_value(self) -> bool | None:
        """Extract value from coordinator data."""
        if self.entity_description.value_fn is None:
            return None
        value = self.entity_description.value_fn(self.coordinator.data)
        if value is None:
            return None
        return bool(value)

    @property
    def is_on(self) -> bool | None:
        """Return true if the binary sensor is on."""
        return self._get_value()

    @property
    def available(self) -> bool:
        """Return if entity is available."""
        return (
            self.coordinator.last_update_success
            and self._get_value() is not None
        )
