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
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import BINARY_FLAG_DEBOUNCE, DATA_BATTERY, DATA_EM_STATUS, DATA_ES_MODE
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
    """A Marstek binary sensor backed by one flag of the polled data.

    The reported value is debounced: a flag only changes once the device has
    reported the new value on BINARY_FLAG_DEBOUNCE consecutive polls. See the
    comment on that constant for the measurements behind it.

    The flags here are latched summaries of hardware state -- a CT is plugged
    in or it is not, charging is permitted or it is not -- and none of them can
    genuinely toggle and toggle back inside a poll cycle. A lone deviating
    reading is therefore noise, and publishing it is actively harmful: a
    "CT lost" that lasts ten seconds sends automations chasing a fault that
    never happened, and a flapping charge-permission flag invites exactly the
    wrong diagnosis when charging really does stop.

    Note what this does NOT do: it never invents a value. Until the device has
    reported anything the sensor is unknown, and a device that stops answering
    altogether is handled by the coordinator, which marks every entity
    unavailable after MAX_CONSECUTIVE_FAILURES empty polls.
    """

    entity_description: MarstekBinarySensorEntityDescription

    def __init__(
        self,
        coordinator: MarstekDataUpdateCoordinator,
        description: MarstekBinarySensorEntityDescription,
    ) -> None:
        """Initialize the binary sensor."""
        super().__init__(coordinator, description.key, description)
        # The value currently published, and how many polls in a row have
        # disagreed with it.
        self._reported: bool | None = None
        self._pending: bool | None = None
        self._pending_count = 0

    async def async_added_to_hass(self) -> None:
        """Seed the filter from whatever the coordinator already holds."""
        self._advance()
        await super().async_added_to_hass()

    @callback
    def _handle_coordinator_update(self) -> None:
        """Advance the filter once per poll, then publish."""
        self._advance()
        super()._handle_coordinator_update()

    def _advance(self) -> None:
        """Feed one poll's reading into the debounce filter.

        Called exactly once per coordinator update. The counting deliberately
        does not live in the is_on property: Home Assistant may read a property
        several times for one state write, which would make each poll count
        more than once and quietly shorten the debounce.
        """
        raw = self.entity_description.value_fn(self.coordinator.data or {})

        if raw is None:
            # No reading at all. Hold whatever was last published rather than
            # blanking the entity, and do not let the gap count towards a
            # pending change either way.
            return

        value = bool(raw)

        if value == self._reported:
            # Back in agreement -- discard any change that was building up.
            self._pending = None
            self._pending_count = 0
            return

        if self._reported is None:
            # First ever reading: publish it immediately. Debouncing the very
            # first value would only leave the entity unknown for no reason.
            self._reported = value
            return

        if value != self._pending:
            self._pending = value
            self._pending_count = 1
        else:
            self._pending_count += 1

        if self._pending_count >= BINARY_FLAG_DEBOUNCE:
            self._reported = value
            self._pending = None
            self._pending_count = 0

    @property
    def is_on(self) -> bool | None:
        """Return the debounced flag."""
        return self._reported
