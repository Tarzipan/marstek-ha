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
    MODBUS_POWER_MAX,
    MODBUS_POWER_MIN,
    MODBUS_POWER_STEP,
    MODBUS_REG_MAX_CHARGE_POWER,
    MODBUS_REG_MAX_DISCHARGE_POWER,
    PASSIVE_CD_TIME_MAX,
    PASSIVE_CD_TIME_MIN,
    PASSIVE_POWER_MAX,
    PASSIVE_POWER_MIN,
)
from .coordinator import MarstekConfigEntry, MarstekDataUpdateCoordinator
from .entity import MarstekEntity
from .modbus import MarstekModbusError

_LOGGER = logging.getLogger(__name__)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: MarstekConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up Marstek number entities from a config entry."""
    coordinator = entry.runtime_data
    entities: list[NumberEntity] = [
        MarstekDODNumber(coordinator),
        MarstekPassivePowerNumber(coordinator),
        MarstekPassiveCountdownNumber(coordinator),
    ]

    # The power limits live on the optional Modbus channel, so they only exist
    # when that channel is switched on. Read both registers once here -- see the
    # module docstring in modbus.py for why exactly once.
    if coordinator.modbus is not None:
        await coordinator.modbus.async_read_limits()
        entities += [
            MarstekPowerLimitNumber(
                coordinator,
                key="max_charge_power",
                register=MODBUS_REG_MAX_CHARGE_POWER,
                icon="mdi:battery-arrow-up-outline",
            ),
            MarstekPowerLimitNumber(
                coordinator,
                key="max_discharge_power",
                register=MODBUS_REG_MAX_DISCHARGE_POWER,
                icon="mdi:battery-arrow-down-outline",
            ),
        ]

    async_add_entities(entities)


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


class MarstekPowerLimitNumber(MarstekEntity, NumberEntity):
    """A charge or discharge power ceiling, written over Modbus TCP.

    This is the one entity that does not use the UDP Open API: that protocol
    has no command for a power *limit*, only the Passive setpoint, which is an
    operating point and would cost the device its own CT regulation. See the
    module docstring in modbus.py.

    The intended use is a handful of writes per day. Setting the charge limit
    to 0 W stops a device in Auto mode from charging while leaving its
    second-by-second discharge regulation untouched -- useful overnight, when
    a load dropping away makes the device overshoot, briefly export, and then
    buy that same energy back a second later through two conversions.

    Unlike the other numbers this one does not restore its value across
    restarts: the register lives in the device and survives a Home Assistant
    restart on its own, so the value is read back from the device once at
    startup instead of being guessed from the recorder.
    """

    _attr_native_min_value = MODBUS_POWER_MIN
    _attr_native_max_value = MODBUS_POWER_MAX
    _attr_native_step = MODBUS_POWER_STEP
    _attr_mode = NumberMode.BOX
    _attr_device_class = NumberDeviceClass.POWER
    _attr_native_unit_of_measurement = UnitOfPower.WATT
    _attr_entity_category = EntityCategory.CONFIG

    def __init__(
        self,
        coordinator: MarstekDataUpdateCoordinator,
        *,
        key: str,
        register: int,
        icon: str,
    ) -> None:
        """Initialize a power limit number bound to one holding register."""
        super().__init__(coordinator, key)
        self._attr_translation_key = key
        self._attr_icon = icon
        self._register = register

    @property
    def native_value(self) -> float | None:
        """Return the limit last read from or written to the device."""
        if self.coordinator.modbus is None:
            return None
        known = self.coordinator.modbus.known_value(self._register)
        return None if known is None else float(known)

    async def async_set_native_value(self, value: float) -> None:
        """Write a new limit to the device."""
        if self.coordinator.modbus is None:
            raise HomeAssistantError("The Modbus channel is not enabled")

        try:
            await self.coordinator.modbus.async_write_limit(self._register, int(value))
        except MarstekModbusError as err:
            # Surfaced rather than logged: a rate-limited or refused write means
            # the device is still running on the old limit, and an automation
            # that silently believed otherwise is worse than a failed action.
            raise HomeAssistantError(str(err)) from err

        self.async_write_ha_state()
