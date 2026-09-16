"""Binary sensor platform for Marstek."""
from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from homeassistant.components.binary_sensor import (
    BinarySensorDeviceClass,
    BinarySensorEntity,
    BinarySensorEntityDescription,
)
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import DATA_BATTERY, DATA_EM_STATUS, DATA_ES_MODE
from .coordinator import MarstekConfigEntry, MarstekDataUpdateCoordinator
from .entity import MarstekEntity, safe_get


@dataclass(frozen=True, kw_only=True)
class MarstekBinarySensorEntityDescription(BinarySensorEntityDescription):
    """Describes a Marstek binary sensor."""

    value_fn: Callable[[dict[str, Any]], Any]


def _ct_connected(data: dict[str, Any]) -> Any:
    """Return whether the CT / energy meter is connected.

    EM.GetStatus.ct_state is authoritative and always valid. ES.GetMode.ct_state
    is only meaningful in Auto/AI mode per the API docs, so it is used solely as
    a fallback when EM.GetStatus went unanswered.
    """
    state = safe_get(data, DATA_EM_STATUS, "ct_state")
    if state is not None:
        return state
    return safe_get(data, DATA_ES_MODE, "ct_state")


BINARY_SENSOR_TYPES: tuple[MarstekBinarySensorEntityDescription, ...] = (
    MarstekBinarySensorEntityDescription(
        key="battery_charging_allowed",
        translation_key="battery_charging_allowed",
        device_class=BinarySensorDeviceClass.POWER,
        icon="mdi:battery-charging-check",
        value_fn=lambda data: safe_get(data, DATA_BATTERY, "charg_flag"),
    ),
    MarstekBinarySensorEntityDescription(
        key="battery_discharging_allowed",
        translation_key="battery_discharging_allowed",
        device_class=BinarySensorDeviceClass.POWER,
        icon="mdi:battery-minus-check",
        value_fn=lambda data: safe_get(data, DATA_BATTERY, "dischrg_flag"),
    ),
    MarstekBinarySensorEntityDescription(
        key="ct_connected",
        translation_key="ct_connected",
        device_class=BinarySensorDeviceClass.CONNECTIVITY,
        value_fn=_ct_connected,
    ),
)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: MarstekConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up Marstek binary sensors from a config entry."""
    coordinator = entry.runtime_data
    async_add_entities(
        MarstekBinarySensor(coordinator, description)
        for description in BINARY_SENSOR_TYPES
    )


class MarstekBinarySensor(MarstekEntity, BinarySensorEntity):
    """A Marstek binary sensor backed by one flag of the polled data."""

    entity_description: MarstekBinarySensorEntityDescription

    def __init__(
        self,
        coordinator: MarstekDataUpdateCoordinator,
        description: MarstekBinarySensorEntityDescription,
    ) -> None:
        """Initialize the binary sensor."""
        super().__init__(coordinator, description.key, description)

    @property
    def is_on(self) -> bool | None:
        """Return true if the flag is set."""
        value = self.entity_description.value_fn(self.coordinator.data or {})
        if value is None:
            return None
        return bool(value)
