"""DataUpdateCoordinator for Marstek."""
from __future__ import annotations

import asyncio
from collections.abc import Mapping
from datetime import timedelta
import logging
import time
from typing import Any

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed

from .const import (
    CONF_DEVICE_IP,
    CONF_DEVICE_PORT,
    CONF_MIN_WRITE_INTERVAL,
    CONF_MODBUS_ENABLED,
    CONF_MODBUS_PORT,
    CONF_MODBUS_UNIT_ID,
    CONF_SCAN_INTERVAL,
    DATA_ES_MODE,
    DEFAULT_MIN_WRITE_INTERVAL,
    DEFAULT_PORT,
    DEFAULT_SCAN_INTERVAL,
    DOMAIN,
    ES_MODE_PASSIVE,
    MAX_CONSECUTIVE_FAILURES,
    MODBUS_DEFAULT_PORT,
    MODBUS_DEFAULT_UNIT_ID,
    PASSIVE_CD_TIME_DEFAULT,
    PASSIVE_POWER_DEFAULT,
)
from .marstek_api import MarstekAPI
from .modbus import MarstekModbusWriter

_LOGGER = logging.getLogger(__name__)


def modbus_signature(options: Mapping[str, Any]) -> tuple[bool, int, int]:
    """Return the Modbus settings from an options mapping as a comparable tuple."""
    return (
        bool(options.get(CONF_MODBUS_ENABLED, False)),
        int(options.get(CONF_MODBUS_PORT, MODBUS_DEFAULT_PORT)),
        int(options.get(CONF_MODBUS_UNIT_ID, MODBUS_DEFAULT_UNIT_ID)),
    )


# Config entry carrying its coordinator in runtime_data.
MarstekConfigEntry = ConfigEntry["MarstekDataUpdateCoordinator"]


class MarstekDataUpdateCoordinator(DataUpdateCoordinator[dict[str, Any]]):
    """Fetches data from one Marstek device and serializes writes to it."""

    config_entry: MarstekConfigEntry

    def __init__(self, hass: HomeAssistant, entry: MarstekConfigEntry) -> None:
        """Initialize the coordinator."""
        self.api = MarstekAPI(
            entry.data[CONF_DEVICE_IP],
            entry.data.get(CONF_DEVICE_PORT, DEFAULT_PORT),
        )

        # Consecutive polls in which *every* endpoint went unanswered. A single
        # lost datagram must not flip entities to unavailable, so failures are
        # only escalated to UpdateFailed once this exceeds the threshold.
        self._consecutive_failures = 0

        # Write throttling state, shared by the select, the numbers and the
        # service so that all write paths obey one rate limit.
        self._write_lock = asyncio.Lock()
        self._last_write_monotonic = 0.0
        self._last_passive_command: tuple[int, int] | None = None

        # Desired Passive setpoint, held here so the two number entities can
        # each change one half of a command that must be sent as a whole.
        self.passive_power: int = PASSIVE_POWER_DEFAULT
        self.passive_cd_time: int = PASSIVE_CD_TIME_DEFAULT

        # Optional Modbus TCP side channel for the power limit registers, which
        # the UDP Open API does not expose. None while the option is off, and
        # deliberately not created lazily: whether the limit entities exist is
        # decided once, at entry load, rather than mid-session.
        self._modbus_signature = modbus_signature(entry.options)
        self.modbus: MarstekModbusWriter | None = None
        if self._modbus_signature[0]:
            self.modbus = MarstekModbusWriter(
                entry.data[CONF_DEVICE_IP],
                self._modbus_signature[1],
                self._modbus_signature[2],
            )

        super().__init__(
            hass,
            _LOGGER,
            name=f"{DOMAIN} {entry.data[CONF_DEVICE_IP]}",
            config_entry=entry,
            # Read from `entry` rather than self.scan_interval: the base class
            # only assigns self.config_entry inside this super() call.
            update_interval=timedelta(
                seconds=entry.options.get(CONF_SCAN_INTERVAL, DEFAULT_SCAN_INTERVAL)
            ),
        )

    @property
    def scan_interval(self) -> int:
        """Return the configured polling interval in seconds."""
        return self.config_entry.options.get(
            CONF_SCAN_INTERVAL, DEFAULT_SCAN_INTERVAL
        )

    @property
    def min_write_interval(self) -> int:
        """Return the minimum number of seconds between two ES.SetMode writes."""
        return self.config_entry.options.get(
            CONF_MIN_WRITE_INTERVAL, DEFAULT_MIN_WRITE_INTERVAL
        )

    @property
    def modbus_settings_changed(self) -> bool:
        """Return whether the entry's Modbus options differ from the live ones.

        Whether the limit entities exist at all depends on these, so a change
        has to reload the entry rather than be applied in place.
        """
        return modbus_signature(self.config_entry.options) != self._modbus_signature

    @property
    def device_id(self) -> str:
        """Return the stable identifier used for devices and unique IDs."""
        return self.config_entry.unique_id or self.config_entry.entry_id

    @property
    def current_mode(self) -> str | None:
        """Return the energy storage mode last reported by the device."""
        es_mode = (self.data or {}).get(DATA_ES_MODE)
        if isinstance(es_mode, dict):
            mode = es_mode.get("mode")
            if isinstance(mode, str):
                return mode
        return None

    # --- Polling ---------------------------------------------------------

    async def _async_update_data(self) -> dict[str, Any]:
        """Fetch all endpoints, tolerating partial and transient failures."""
        # Cap the poll at one interval so a silent device cannot make polls
        # pile up: the requests run sequentially and each one may retry.
        data = await self.api.get_all_data(budget=self.scan_interval)

        if all(value is None for value in data.values()):
            self._consecutive_failures += 1
            if self._consecutive_failures >= MAX_CONSECUTIVE_FAILURES:
                raise UpdateFailed(
                    f"No response from {self.api.host} in "
                    f"{self._consecutive_failures} consecutive polls"
                )
            _LOGGER.debug(
                "Poll %s of %s returned nothing; keeping previous data",
                self._consecutive_failures, MAX_CONSECUTIVE_FAILURES,
            )
            if self.data:
                return self.data
            raise UpdateFailed(f"No response from {self.api.host}")

        self._consecutive_failures = 0

        # Carry forward the last known good value for any endpoint that did not
        # answer this round, so one dropped datagram does not blank out a
        # subset of the entities.
        if self.data:
            for key, value in data.items():
                if value is None and self.data.get(key) is not None:
                    data[key] = self.data[key]

        return data

    def async_update_interval(self) -> None:
        """Apply a changed polling interval from the options."""
        self.update_interval = timedelta(seconds=self.scan_interval)

    # --- Writes ----------------------------------------------------------

    async def _async_throttle(self) -> None:
        """Wait until the configured minimum write spacing has elapsed."""
        interval = self.min_write_interval
        if interval <= 0:
            return
        elapsed = time.monotonic() - self._last_write_monotonic
        if elapsed < interval:
            await asyncio.sleep(interval - elapsed)

    async def async_set_es_mode(self, mode: str) -> bool:
        """Set the energy storage mode.

        Switching into Passive carries the currently held setpoint so the
        device does not sit at an unintended power level.
        """
        if mode == ES_MODE_PASSIVE:
            return await self.async_set_passive_power(
                self.passive_power, self.passive_cd_time
            )

        async with self._write_lock:
            await self._async_throttle()
            result = await self.api.set_es_mode(mode)
            self._last_write_monotonic = time.monotonic()
            self._last_passive_command = None

        if result:
            await self.async_request_refresh()
        return result

    async def async_set_passive_power(
        self, power: int, cd_time: int, *, force: bool = False
    ) -> bool:
        """Enter Passive mode with a setpoint and countdown.

        This is the integration's main write path. It is rate limited and, by
        default, suppresses a command that is identical to the last one -- but
        only while the device still reports Passive mode. Once the countdown
        has expired and the device has fallen back, an identical setpoint is a
        genuine re-arm and is sent through.
        """
        power = int(power)
        cd_time = int(cd_time)

        async with self._write_lock:
            unchanged = self._last_passive_command == (power, cd_time)
            if unchanged and not force and self.current_mode == ES_MODE_PASSIVE:
                _LOGGER.debug(
                    "Skipping duplicate passive setpoint %s W / %s s", power, cd_time
                )
                return True

            await self._async_throttle()
            result = await self.api.set_passive_power(power, cd_time)
            self._last_write_monotonic = time.monotonic()

            if result:
                self.passive_power = power
                self.passive_cd_time = cd_time
                self._last_passive_command = (power, cd_time)
            else:
                self._last_passive_command = None

        if result:
            await self.async_request_refresh()
        return result

    async def async_set_dod(self, value: int) -> bool:
        """Set the depth of discharge."""
        result = await self.api.set_dod(value)
        if result:
            await self.async_request_refresh()
        return result

    async def async_set_ble_adv(self, enable: bool) -> bool:
        """Enable or disable Bluetooth advertising."""
        return await self.api.set_ble_adv(enable)

    async def async_set_led(self, state: bool) -> bool:
        """Control the status LED."""
        return await self.api.set_led(state)

    async def async_shutdown(self) -> None:
        """Close the UDP endpoint."""
        await super().async_shutdown()
        await self.api.async_close()
