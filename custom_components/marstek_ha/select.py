"""Select platform for Marstek."""
from __future__ import annotations

import logging

from homeassistant.components.select import SelectEntity
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import ES_MODES
from .coordinator import MarstekConfigEntry, MarstekDataUpdateCoordinator
from .entity import MarstekEntity

_LOGGER = logging.getLogger(__name__)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: MarstekConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up the Marstek mode select from a config entry."""
    async_add_entities([MarstekESModeSelect(entry.runtime_data)])


class MarstekESModeSelect(MarstekEntity, SelectEntity):
    """Selects the energy storage mode.

    Note on the Auto mode: with the Open API enabled, Marstek document that
    some built-in behaviour may be disabled to avoid command conflicts, so Auto
    (anti-feed regulation against the CT) is not guaranteed to keep working.
    If it does not, drive the device through Passive instead -- see the
    marstek_ha.set_passive_power service, which is designed for exactly that.
    """

    _attr_translation_key = "es_mode_select"
    _attr_icon = "mdi:battery-charging"
    _attr_options = ES_MODES

    def __init__(self, coordinator: MarstekDataUpdateCoordinator) -> None:
        """Initialize the select entity."""
        super().__init__(coordinator, "es_mode_select")

    @property
    def current_option(self) -> str | None:
        """Return the mode the device currently reports."""
        mode = self.coordinator.current_mode
        return mode if mode in ES_MODES else None

    async def async_select_option(self, option: str) -> None:
        """Switch the device to the selected mode."""
        if option not in ES_MODES:
            raise HomeAssistantError(f"Invalid energy storage mode: {option}")

        _LOGGER.debug("Setting energy storage mode to %s", option)
        if not await self.coordinator.async_set_es_mode(option):
            raise HomeAssistantError(f"Failed to set energy storage mode to {option}")
