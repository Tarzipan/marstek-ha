"""Number platform for Marstek."""
from __future__ import annotations

import logging

from homeassistant.components.number import NumberEntity, NumberMode
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DOMAIN, DOD_MAX, DOD_MIN
from .coordinator import MarstekDataUpdateCoordinator

_LOGGER = logging.getLogger(__name__)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up Marstek number entities based on a config entry."""
    coordinator: MarstekDataUpdateCoordinator = hass.data[DOMAIN][entry.entry_id]

    async_add_entities([MarstekDODNumber(coordinator, entry)])


class MarstekDODNumber(CoordinatorEntity[MarstekDataUpdateCoordinator], NumberEntity):
    """Representation of Marstek Depth of Discharge setting."""

    _attr_has_entity_name = True
    _attr_name = "Depth of Discharge"
    _attr_icon = "mdi:battery-arrow-down"
    _attr_native_min_value = DOD_MIN
    _attr_native_max_value = DOD_MAX
    _attr_native_step = 1
    _attr_mode = NumberMode.SLIDER
    _attr_native_unit_of_measurement = "%"

    def __init__(
        self,
        coordinator: MarstekDataUpdateCoordinator,
        entry: ConfigEntry,
    ) -> None:
        """Initialize the number entity."""
        super().__init__(coordinator)
        device_id = entry.unique_id or entry.entry_id
        self._attr_unique_id = f"{device_id}_dod"

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

    @property
    def native_value(self) -> float | None:
        """Return the current DOD value."""
        # DOD is a write-only setting per the API; no query command exists.
        # Return None (unknown) - the entity still allows setting the value.
        return None

    async def async_set_native_value(self, value: float) -> None:
        """Set the DOD value."""
        int_value = int(value)
        _LOGGER.debug("Setting DOD to: %s", int_value)
        result = await self.coordinator.async_set_dod(int_value)

        if not result:
            raise HomeAssistantError(f"Failed to set DOD to {int_value}")

    @property
    def available(self) -> bool:
        """Return if entity is available."""
        return self.coordinator.last_update_success
