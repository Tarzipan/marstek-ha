"""Number platform for Marstek."""
from __future__ import annotations

import logging

from homeassistant.components.number import (
    NumberDeviceClass,
    NumberEntity,
    NumberMode,
)
from homeassistant.const import UnitOfPower, UnitOfTime
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers.entity import EntityCategory
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.restore_state import RestoreEntity

from .const import (
    DOD_MAX,
    DOD_MIN,
    PASSIVE_CD_TIME_MAX,
    PASSIVE_CD_TIME_MIN,
    PASSIVE_POWER_MAX,
    PASSIVE_POWER_MIN,
)
from .coordinator import MarstekConfigEntry, MarstekDataUpdateCoordinator
from .entity import MarstekEntity

_LOGGER = logging.getLogger(__name__)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: MarstekConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up Marstek number entities from a config entry."""
    coordinator = entry.runtime_data
    async_add_entities(
        [
            MarstekDODNumber(coordinator),
            MarstekPassivePowerNumber(coordinator),
            MarstekPassiveCountdownNumber(coordinator),
        ]
    )


class MarstekDODNumber(MarstekEntity, NumberEntity, RestoreEntity):
    """Depth of discharge setting.

    DOD.SET is write-only: the API offers no way to read the current value
    back, so the last value written is restored across restarts instead.
    """

    _attr_translation_key = "dod"
    _attr_icon = "mdi:battery-arrow-down"
    _attr_native_min_value = DOD_MIN
    _attr_native_max_value = DOD_MAX
    _attr_native_step = 1
    _attr_mode = NumberMode.SLIDER
    _attr_native_unit_of_measurement = "%"
    _attr_entity_category = EntityCategory.CONFIG

    def __init__(self, coordinator: MarstekDataUpdateCoordinator) -> None:
        """Initialize the DOD number."""
        super().__init__(coordinator, "dod")
        self._value: float | None = None

    async def async_added_to_hass(self) -> None:
        """Restore the last value written before the restart."""
        await super().async_added_to_hass()
        if (last_state := await self.async_get_last_state()) is not None:
            try:
                self._value = float(last_state.state)
            except (TypeError, ValueError):
                self._value = None

    @property
    def native_value(self) -> float | None:
        """Return the last value written, if any."""
        return self._value

    async def async_set_native_value(self, value: float) -> None:
        """Write a new depth of discharge."""
        int_value = int(value)
        _LOGGER.debug("Setting depth of discharge to %s%%", int_value)
        if not await self.coordinator.async_set_dod(int_value):
            raise HomeAssistantError(f"Failed to set depth of discharge to {int_value}")
        self._value = float(int_value)
        self.async_write_ha_state()


class MarstekPassivePowerNumber(MarstekEntity, NumberEntity, RestoreEntity):
    """Passive mode power setpoint.

    Sign convention (see PASSIVE_POWER_SIGN in const.py, not yet verified
    against hardware): positive discharges the battery, negative charges it.

    Changing this entity sends the setpoint immediately, together with the
    current countdown, because the API only accepts the two as one command.
    While the device is not in Passive mode, setting this value switches it
    into Passive -- that is the whole point of the entity.
    """

    _attr_translation_key = "passive_power"
    _attr_icon = "mdi:transmission-tower"
    _attr_native_min_value = PASSIVE_POWER_MIN
    _attr_native_max_value = PASSIVE_POWER_MAX
    _attr_native_step = 10
    _attr_mode = NumberMode.BOX
    _attr_device_class = NumberDeviceClass.POWER
    _attr_native_unit_of_measurement = UnitOfPower.WATT

    def __init__(self, coordinator: MarstekDataUpdateCoordinator) -> None:
        """Initialize the passive power number."""
        super().__init__(coordinator, "passive_power")

    async def async_added_to_hass(self) -> None:
        """Restore the last setpoint so a restart does not reset it to zero."""
        await super().async_added_to_hass()
        if (last_state := await self.async_get_last_state()) is not None:
            try:
                self.coordinator.passive_power = int(float(last_state.state))
            except (TypeError, ValueError):
                pass

    @property
    def native_value(self) -> float | None:
        """Return the setpoint currently held by the coordinator."""
        return float(self.coordinator.passive_power)

    async def async_set_native_value(self, value: float) -> None:
        """Send a new passive setpoint with the current countdown."""
        power = int(value)
        if not await self.coordinator.async_set_passive_power(
            power, self.coordinator.passive_cd_time
        ):
            raise HomeAssistantError(f"Failed to set passive power to {power} W")
        self.async_write_ha_state()


class MarstekPassiveCountdownNumber(MarstekEntity, NumberEntity, RestoreEntity):
    """Countdown after which the device leaves Passive mode on its own.

    This is the device-side watchdog and the reason the integration needs no
    heartbeat: if Home Assistant stops sending setpoints, the device falls back
    by itself once the countdown elapses. Set it to roughly two to three times
    the interval at which setpoints are pushed.

    Changing this value alone does not send a command -- it takes effect with
    the next setpoint write, so that adjusting the countdown never silently
    forces the device into Passive mode.
    """

    _attr_translation_key = "passive_cd_time"
    _attr_icon = "mdi:timer-outline"
    _attr_native_min_value = PASSIVE_CD_TIME_MIN
    _attr_native_max_value = PASSIVE_CD_TIME_MAX
    _attr_native_step = 1
    _attr_mode = NumberMode.BOX
    _attr_native_unit_of_measurement = UnitOfTime.SECONDS
    _attr_entity_category = EntityCategory.CONFIG

    def __init__(self, coordinator: MarstekDataUpdateCoordinator) -> None:
        """Initialize the countdown number."""
        super().__init__(coordinator, "passive_cd_time")

    async def async_added_to_hass(self) -> None:
        """Restore the countdown chosen before the restart."""
        await super().async_added_to_hass()
        if (last_state := await self.async_get_last_state()) is not None:
            try:
                self.coordinator.passive_cd_time = int(float(last_state.state))
            except (TypeError, ValueError):
                pass

    @property
    def native_value(self) -> float | None:
        """Return the countdown currently held by the coordinator."""
        return float(self.coordinator.passive_cd_time)

    async def async_set_native_value(self, value: float) -> None:
        """Store the countdown for the next setpoint write."""
        self.coordinator.passive_cd_time = int(value)
        self.async_write_ha_state()
