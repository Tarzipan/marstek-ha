"""DataUpdateCoordinator for Marstek."""
from __future__ import annotations

from datetime import timedelta
import logging
from typing import Any

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed

from .const import (
    CONF_DEVICE_IP,
    CONF_DEVICE_PORT,
    DEFAULT_PORT,
    DEFAULT_SCAN_INTERVAL,
    DOMAIN,
)
from .marstek_api import MarstekAPI

_LOGGER = logging.getLogger(__name__)


class MarstekDataUpdateCoordinator(DataUpdateCoordinator[dict[str, Any]]):
    """Class to manage fetching Marstek data."""

    def __init__(self, hass: HomeAssistant, entry: ConfigEntry) -> None:
        """Initialize the coordinator."""
        port = entry.data.get(CONF_DEVICE_PORT, DEFAULT_PORT)
        self.api = MarstekAPI(
            entry.data[CONF_DEVICE_IP],
            port,
            port,
        )
        self.entry = entry

        super().__init__(
            hass,
            _LOGGER,
            name=DOMAIN,
            update_interval=timedelta(seconds=DEFAULT_SCAN_INTERVAL),
        )

    async def _async_update_data(self) -> dict[str, Any]:
        """Fetch data from API."""
        try:
            data = await self.api.get_all_data()
        except Exception as err:
            raise UpdateFailed(f"Error communicating with device: {err}") from err

        # Check if all API calls failed (dict with all None values)
        if all(v is None for v in data.values()):
            raise UpdateFailed("All API calls failed - device may be unreachable")

        return data

    async def async_set_es_mode(self, mode: str) -> bool:
        """Set the energy storage mode via the API."""
        result = await self.api.set_es_mode(mode)
        if result:
            await self.async_request_refresh()
        return result

    async def async_shutdown(self) -> None:
        """Shutdown the coordinator."""
        await self.api.disconnect()
