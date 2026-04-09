"""Select platform for Marstek."""
from __future__ import annotations

import logging
from typing import Any

from homeassistant.components.select import SelectEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DOMAIN, ES_MODES
from .coordinator import MarstekDataUpdateCoordinator

_LOGGER = logging.getLogger(__name__)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up Marstek select based on a config entry."""
    coordinator: MarstekDataUpdateCoordinator = hass.data[DOMAIN][entry.entry_id]

    async_add_entities([MarstekESModeSelect(coordinator, entry)])


class MarstekESModeSelect(CoordinatorEntity[MarstekDataUpdateCoordinator], SelectEntity):
    """Representation of Marstek Energy Storage Mode selector."""

    _attr_has_entity_name = True
    _attr_name = "Energy Storage Mode"
    _attr_icon = "mdi:battery-charging"

    def __init__(
        self,
        coordinator: MarstekDataUpdateCoordinator,
        entry: ConfigEntry,
    ) -> None:
        """Initialize the select entity."""
        super().__init__(coordinator)
        self._attr_unique_id = f"{entry.entry_id}_es_mode"
        self._attr_options = ES_MODES

        device_data = coordinator.data.get("device", {})
        device_name = device_data.get("device", "Unknown")
        firmware_ver = device_data.get("ver", "Unknown")

        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, entry.entry_id)},
            name=entry.title,
            manufacturer="Marstek",
            model=device_name,
            sw_version=str(firmware_ver),
        )

    @property
    def current_option(self) -> str | None:
        """Return the current selected option."""
        es_mode_data = self.coordinator.data.get("es_mode")

        if isinstance(es_mode_data, dict):
            mode = es_mode_data.get("mode")
            if mode in ES_MODES:
                return mode

        return None

    async def async_select_option(self, option: str) -> None:
        """Change the selected option."""
        if option not in ES_MODES:
            raise HomeAssistantError(f"Invalid ES mode: {option}")

        _LOGGER.debug("Setting ES mode to: %s", option)
        result = await self.coordinator.async_set_es_mode(option)

        if not result:
            raise HomeAssistantError(f"Failed to set ES mode to {option}")

    @property
    def available(self) -> bool:
        """Return if entity is available."""
        return (
            self.coordinator.last_update_success
            and self.current_option is not None
        )
