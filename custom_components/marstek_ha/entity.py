"""Base entity for the Marstek integration."""
from __future__ import annotations

from typing import Any

from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.entity import EntityDescription
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DATA_DEVICE, DOMAIN
from .coordinator import MarstekDataUpdateCoordinator


def safe_get(data: dict | None, *keys: str) -> Any:
    """Traverse nested dict keys, returning None if any level is missing."""
    current: Any = data
    for key in keys:
        if not isinstance(current, dict):
            return None
        current = current.get(key)
        if current is None:
            return None
    return current


class MarstekEntity(CoordinatorEntity[MarstekDataUpdateCoordinator]):
    """Common device info and availability handling for Marstek entities."""

    _attr_has_entity_name = True

    def __init__(
        self,
        coordinator: MarstekDataUpdateCoordinator,
        key: str,
        description: EntityDescription | None = None,
    ) -> None:
        """Initialize the entity and attach it to the device."""
        super().__init__(coordinator)
        if description is not None:
            self.entity_description = description
        self._attr_unique_id = f"{coordinator.device_id}_{key}"
        self._attr_device_info = self._build_device_info()

    def _build_device_info(self) -> DeviceInfo:
        """Build the device registry entry from the last polled device data."""
        entry = self.coordinator.config_entry
        device_data = (self.coordinator.data or {}).get(DATA_DEVICE) or {}

        return DeviceInfo(
            identifiers={(DOMAIN, self.coordinator.device_id)},
            name=entry.title,
            manufacturer="Marstek",
            model=device_data.get("device") or "Marstek Battery Storage",
            sw_version=str(device_data.get("ver")) if device_data.get("ver") else None,
            serial_number=device_data.get("ble_mac") or None,
        )

    def _value(self, *keys: str) -> Any:
        """Read a nested value from the coordinator data."""
        return safe_get(self.coordinator.data, *keys)

    @property
    def available(self) -> bool:
        """Return whether the device is currently reachable.

        Deliberately only tracks the coordinator, not whether this particular
        entity has a value. A single unanswered UDP datagram must not make
        entities disappear -- the coordinator already tolerates that and holds
        the previous reading.
        """
        return self.coordinator.last_update_success
