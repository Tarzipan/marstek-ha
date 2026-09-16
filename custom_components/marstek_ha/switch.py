"""Switch platform for Marstek."""
from __future__ import annotations

from collections.abc import Callable, Coroutine
from dataclasses import dataclass
from typing import Any

from homeassistant.components.switch import SwitchEntity, SwitchEntityDescription
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers.entity import EntityCategory
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .coordinator import MarstekConfigEntry, MarstekDataUpdateCoordinator
from .entity import MarstekEntity


@dataclass(frozen=True, kw_only=True)
class MarstekSwitchEntityDescription(SwitchEntityDescription):
    """Describes a Marstek switch."""

    set_fn: Callable[[MarstekDataUpdateCoordinator, bool], Coroutine[Any, Any, bool]]


SWITCH_TYPES: tuple[MarstekSwitchEntityDescription, ...] = (
    MarstekSwitchEntityDescription(
        key="led",
        translation_key="led",
        icon="mdi:led-on",
        entity_category=EntityCategory.CONFIG,
        set_fn=lambda coordinator, state: coordinator.async_set_led(state),
    ),
    MarstekSwitchEntityDescription(
        key="bluetooth",
        translation_key="bluetooth",
        icon="mdi:bluetooth",
        entity_category=EntityCategory.CONFIG,
        set_fn=lambda coordinator, state: coordinator.async_set_ble_adv(state),
    ),
)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: MarstekConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up Marstek switches from a config entry."""
    coordinator = entry.runtime_data
    async_add_entities(
        MarstekSwitch(coordinator, description) for description in SWITCH_TYPES
    )


class MarstekSwitch(MarstekEntity, SwitchEntity):
    """A write-only Marstek switch.

    Led.Ctrl and Ble.Adv have no matching query command, so the state shown is
    the last one successfully written, flagged as assumed.
    """

    entity_description: MarstekSwitchEntityDescription
    _attr_assumed_state = True

    def __init__(
        self,
        coordinator: MarstekDataUpdateCoordinator,
        description: MarstekSwitchEntityDescription,
    ) -> None:
        """Initialize the switch."""
        super().__init__(coordinator, f"{description.key}_switch", description)
        self._assumed_state: bool | None = None

    @property
    def is_on(self) -> bool | None:
        """Return the last state written, if any."""
        return self._assumed_state

    async def _async_set(self, state: bool) -> None:
        """Write a new state and remember it."""
        if not await self.entity_description.set_fn(self.coordinator, state):
            raise HomeAssistantError(
                f"Failed to switch {self.entity_description.key} "
                f"{'on' if state else 'off'}"
            )
        self._assumed_state = state
        self.async_write_ha_state()

    async def async_turn_on(self, **kwargs: Any) -> None:
        """Turn the switch on."""
        await self._async_set(True)

    async def async_turn_off(self, **kwargs: Any) -> None:
        """Turn the switch off."""
        await self._async_set(False)
