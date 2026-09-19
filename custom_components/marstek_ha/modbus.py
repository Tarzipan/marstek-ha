"""Optional Modbus TCP side channel for the charge and discharge power limits.

WHY THIS EXISTS AT ALL

The Marstek Device Open API (Rev 3.1) -- the UDP protocol the rest of this
integration speaks -- has no command for a charge or discharge power *limit*.
The closest thing, ES.SetMode's passive_cfg.power, is an operating point rather
than a ceiling: setting it takes the device out of Auto mode, and with that goes
the device's own second-by-second regulation against its CT. That regulation is
precisely what a user with a CT wants to keep while capping how hard the device
is allowed to charge.

The same hardware does expose both limits over Modbus TCP as holding registers
(44002 and 44003), so this module writes them there. Everything else stays on
UDP.

WHY IT LOOKS SO PARANOID

The Venus Modbus server serves only ONE session, and it has been observed to
lock up under frequent access badly enough that only a power cycle recovers it.
Every design decision here follows from that:

*   Connect, write, disconnect -- every single time. The socket is never held
    open, so nothing of ours occupies the one available session between writes.
*   No polling. The registers are read exactly once, when the config entry
    loads, purely so the number entities start out showing what the device
    actually holds.
*   A minimum interval between connections that *rejects* rather than queues.
    Queueing would let a runaway automation build a backlog that then hammers
    the device for minutes; rejecting surfaces the mistake in the automation
    trace instead.
*   No retry on timeout. Re-poking a server that has stopped answering is how
    it gets wedged in the first place.
*   Writes that would not change anything are dropped before a socket is even
    opened.

The single-session limit also means no other Modbus client may talk to the same
device. Running a second Marstek Modbus integration alongside this one will
break both.
"""
from __future__ import annotations

import asyncio
import logging
import time

from .const import (
    MODBUS_MIN_WRITE_INTERVAL,
    MODBUS_POWER_MAX,
    MODBUS_POWER_MIN,
    MODBUS_REG_MAX_CHARGE_POWER,
    MODBUS_REG_MAX_DISCHARGE_POWER,
    MODBUS_TIMEOUT,
)

_LOGGER = logging.getLogger(__name__)


class MarstekModbusError(Exception):
    """A Modbus read or write did not succeed."""


class MarstekModbusRateLimited(MarstekModbusError):
    """The write was refused because the last one was too recent."""


class MarstekModbusWriter:
    """Writes the power limit registers of one device over Modbus TCP.

    Not a client in the usual sense: it owns no connection between calls. Each
    operation opens a session, performs one transaction and closes again.
    """

    def __init__(
        self,
        host: str,
        port: int,
        unit_id: int,
        min_interval: float = MODBUS_MIN_WRITE_INTERVAL,
    ) -> None:
        """Initialize the writer for one device."""
        self.host = host
        self.port = port
        self.unit_id = unit_id
        self._min_interval = min_interval

        # Serializes our own access. Two concurrent connections from this
        # integration would be exactly the situation the device cannot handle.
        self._lock = asyncio.Lock()
        self._last_access_monotonic: float | None = None

        # Last value written or read per register, so an unchanged write can be
        # dropped without touching the device.
        self._known: dict[int, int] = {}

    # --- Connection handling --------------------------------------------

    async def _async_transaction(self, action):  # type: ignore[no-untyped-def]
        """Open a session, run one action against it and close again.

        `action` receives the connected pymodbus client and returns whatever
        the caller needs. The client is closed in a finally block so a raising
        action cannot leave the device's one session occupied.
        """
        # Imported lazily: pymodbus is a manifest requirement, but nothing
        # should pay for the import when the Modbus channel is switched off.
        from pymodbus.client import AsyncModbusTcpClient

        client = AsyncModbusTcpClient(
            host=self.host, port=self.port, timeout=MODBUS_TIMEOUT
        )
        try:
            connected = await client.connect()
            if not connected:
                raise MarstekModbusError(
                    f"Could not open a Modbus session to {self.host}:{self.port}. "
                    "The device serves only one at a time -- check that no other "
                    "Modbus client is connected to it."
                )
            return await action(client)
        except MarstekModbusError:
            raise
        except Exception as err:  # noqa: BLE001 -- pymodbus raises broadly
            raise MarstekModbusError(f"Modbus transaction failed: {err}") from err
        finally:
            client.close()
            self._last_access_monotonic = time.monotonic()

    def _check_rate_limit(self) -> None:
        """Raise if the previous access is too recent to open another session."""
        if self._last_access_monotonic is None or self._min_interval <= 0:
            return
        elapsed = time.monotonic() - self._last_access_monotonic
        if elapsed < self._min_interval:
            raise MarstekModbusRateLimited(
                f"Modbus write to {self.host} refused: only {elapsed:.0f}s since "
                f"the last access, minimum is {self._min_interval:.0f}s. The "
                "device's Modbus server locks up under frequent access, so the "
                "write is dropped rather than queued."
            )

    # --- Operations -------------------------------------------------------

    async def async_read_limits(self) -> dict[int, int]:
        """Read both power limit registers once.

        Called exactly once per config entry load, so the number entities show
        the device's actual limits instead of a guess. Never called again --
        these registers only change when something writes them.

        Returns a register -> value mapping, empty if the device did not
        answer. Failure is deliberately not raised: a device that refuses one
        read at startup must not prevent the entry from loading, and the UDP
        side of the integration is entirely unaffected by it.
        """
        base = MODBUS_REG_MAX_CHARGE_POWER

        async def _read(client):  # type: ignore[no-untyped-def]
            # One request covering both registers -- they are adjacent, so this
            # is a single transaction rather than two.
            return await client.read_holding_registers(
                address=base, count=2, device_id=self.unit_id
            )

        async with self._lock:
            try:
                response = await self._async_transaction(_read)
            except MarstekModbusError as err:
                _LOGGER.warning(
                    "Could not read the Modbus power limits from %s: %s. "
                    "The limit entities start out unknown; writing one still works.",
                    self.host, err,
                )
                return {}

        if response is None or response.isError():
            _LOGGER.warning(
                "Device %s rejected the Modbus read of registers %s-%s: %s",
                self.host, base, base + 1, response,
            )
            return {}

        registers = list(getattr(response, "registers", []))
        if len(registers) < 2:
            _LOGGER.warning(
                "Modbus read from %s returned %s register(s), expected 2",
                self.host, len(registers),
            )
            return {}

        values = {
            MODBUS_REG_MAX_CHARGE_POWER: int(registers[0]),
            MODBUS_REG_MAX_DISCHARGE_POWER: int(registers[1]),
        }
        self._known.update(values)
        _LOGGER.debug("Read Modbus power limits from %s: %s", self.host, values)
        return values

    async def async_write_limit(self, register: int, value: int) -> None:
        """Write one power limit register.

        Raises MarstekModbusRateLimited if the previous access was too recent,
        or MarstekModbusError if the device did not accept the write.
        """
        value = int(value)
        if not MODBUS_POWER_MIN <= value <= MODBUS_POWER_MAX:
            raise MarstekModbusError(
                f"Power limit {value} W is outside {MODBUS_POWER_MIN}-"
                f"{MODBUS_POWER_MAX} W"
            )

        async with self._lock:
            if self._known.get(register) == value:
                # Nothing to do, and the cheapest possible way to protect the
                # device: an automation that re-asserts the same limit every
                # few minutes never opens a socket at all.
                _LOGGER.debug(
                    "Modbus register %s on %s already holds %s W, not writing",
                    register, self.host, value,
                )
                return

            self._check_rate_limit()

            async def _write(client):  # type: ignore[no-untyped-def]
                return await client.write_register(
                    address=register, value=value, device_id=self.unit_id
                )

            response = await self._async_transaction(_write)

            if response is None or response.isError():
                # Drop the cached value: we no longer know what the register
                # holds, so the next write must go through rather than be
                # suppressed as a duplicate.
                self._known.pop(register, None)
                raise MarstekModbusError(
                    f"Device {self.host} rejected writing {value} W to register "
                    f"{register}: {response}"
                )

            self._known[register] = value
            _LOGGER.debug(
                "Wrote %s W to Modbus register %s on %s", value, register, self.host
            )

    def known_value(self, register: int) -> int | None:
        """Return the last value read from or written to a register."""
        return self._known.get(register)
