"""Switch platform for Marstek."""
from __future__ import annotations

from collections.abc import Callable, Coroutine
from dataclasses import dataclass
import logging
from typing import Any

from homeassistant.components.switch import SwitchEntity, SwitchEntityDescription
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DOMAIN
from .coordinator import MarstekDataUpdateCoordinator

_LOGGER = logging.getLogger(__name__)


@dataclass
class MarstekSwitchEntityDescription(SwitchEntityDescription):
    """Describes Marstek switch entity."""

    turn_on_fn: Callable[[MarstekDataUpdateCoordinator], Coroutine[Any, Any, bool]] | None = None
    turn_off_fn: Callable[[MarstekDataUpdateCoordinator], Coroutine[Any, Any, bool]] | None = None


SWITCH_TYPES: tuple[MarstekSwitchEntityDescription, ...] = (
    MarstekSwitchEntityDescription(
        key="led",
        name="LED",
        icon="mdi:led-on",
        turn_on_fn=lambda coord: coord.async_set_led(True),
        turn_off_fn=lambda coord: coord.async_set_led(False),
    ),
    MarstekSwitchEntityDescription(
        key="bluetooth",
        name="Bluetooth",
        icon="mdi:bluetooth",
        turn_on_fn=lambda coord: coord.async_set_ble_adv(True),
        turn_off_fn=lambda coord: coord.async_set_ble_adv(False),
    ),
)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up Marstek switch entities based on a config entry."""
    coordinator: MarstekDataUpdateCoordinator = hass.data[DOMAIN][entry.entry_id]

    async_add_entities(
        MarstekSwitch(coordinator, description, entry)
        for description in SWITCH_TYPES
    )


class MarstekSwitch(CoordinatorEntity[MarstekDataUpdateCoordinator], SwitchEntity):
    """Representation of a Marstek switch."""

    entity_description: MarstekSwitchEntityDescription
    _attr_has_entity_name = True

    def __init__(
        self,
        coordinator: MarstekDataUpdateCoordinator,
        description: MarstekSwitchEntityDescription,
        entry: ConfigEntry,
    ) -> None:
        """Initialize the switch."""
        super().__init__(coordinator)
        self.entity_description = description
        device_id = entry.unique_id or entry.entry_id
        self._attr_unique_id = f"{device_id}_{description.key}_switch"
        self._assumed_state: bool | None = None

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
    def is_on(self) -> bool | None:
        """Return the assumed state of the switch."""
        # LED and BLE are write-only commands per the API; no query for current state.
        return self._assumed_state

    @property
    def assumed_state(self) -> bool:
        """Return True since we can't query the actual state."""
        return True

    async def async_turn_on(self, **kwargs: Any) -> None:
        """Turn the switch on."""
        if self.entity_description.turn_on_fn is None:
            return
        result = await self.entity_description.turn_on_fn(self.coordinator)
        if not result:
            raise HomeAssistantError(f"Failed to turn on {self.entity_description.name}")
        self._assumed_state = True
        self.async_write_ha_state()

    async def async_turn_off(self, **kwargs: Any) -> None:
        """Turn the switch off."""
        if self.entity_description.turn_off_fn is None:
            return
        result = await self.entity_description.turn_off_fn(self.coordinator)
        if not result:
            raise HomeAssistantError(f"Failed to turn off {self.entity_description.name}")
        self._assumed_state = False
        self.async_write_ha_state()

    @property
    def available(self) -> bool:
        """Return if entity is available."""
        return self.coordinator.last_update_success
