"""Marstek Device Open API (Rev 3.1) client over UDP.

The device speaks a JSON-RPC-like protocol over UDP:

    request   {"id": <int>, "method": "<Namespace.Method>", "params": {...}}
    response  {"id": <int>, "src": "<device>", "result": {...}}
              {"id": <int>, "src": "<device>", "error": {...}}

Two properties of that protocol drive the design of this module:

1.  Responses are matched to requests **by id**. Every request gets a fresh,
    monotonically increasing id and a pending future; a datagram whose id is
    not pending is discarded. Reusing a single id (as an earlier revision of
    this integration did) makes a late reply to request A get parsed as the
    reply to request B, silently writing values into the wrong fields.

2.  UDP is connectionless, so the local socket receives anything sent to it,
    including datagrams from *other* Marstek devices on the same network.
    Every response is therefore checked against the expected peer address, and
    the socket binds an ephemeral local port rather than a fixed one so that
    several config entries can coexist.
"""
from __future__ import annotations

import asyncio
import contextlib
import json
import logging
from typing import Any

from .const import (
    CMD_BAT_STATUS,
    CMD_BLE_ADV,
    CMD_DOD_SET,
    CMD_EM_STATUS,
    CMD_ES_GET_MODE,
    CMD_ES_SET_MODE,
    CMD_ES_STATUS,
    CMD_GET_DEVICE,
    CMD_LED_CTRL,
    CMD_WIFI_STATUS,
    DATA_BATTERY,
    DATA_DEVICE,
    DATA_EM_STATUS,
    DATA_ES_MODE,
    DATA_ES_STATUS,
    DATA_WIFI,
    DEFAULT_PORT,
    DEFAULT_TIMEOUT,
    ES_MODE_AUTO,
    ES_MODE_PASSIVE,
    PASSIVE_CD_TIME_DEFAULT,
    PASSIVE_POWER_SIGN,
    REQUEST_RETRIES,
)

_LOGGER = logging.getLogger(__name__)

# Marstek's own firmware caps datagrams well below this; 4096 is ample.
_RECV_BUFFER = 4096


class MarstekError(Exception):
    """Base error for Marstek API failures."""


class MarstekTimeout(MarstekError):
    """No response arrived within the timeout, after all retries."""


class MarstekDeviceError(MarstekError):
    """The device answered with an explicit error object."""


class _MarstekProtocol(asyncio.DatagramProtocol):
    """Demultiplexes incoming datagrams onto pending request futures."""

    def __init__(self, owner: MarstekAPI) -> None:
        self._owner = owner

    def datagram_received(self, data: bytes, addr: tuple[str, int]) -> None:
        self._owner._handle_datagram(data, addr)

    def error_received(self, exc: Exception) -> None:
        # ICMP port-unreachable and friends. Not fatal: the endpoint stays
        # usable and the pending request will time out on its own.
        _LOGGER.debug("UDP error from %s: %s", self._owner.host, exc)

    def connection_lost(self, exc: Exception | None) -> None:
        self._owner._handle_connection_lost(exc)


class MarstekAPI:
    """Async UDP client for a single Marstek device."""

    def __init__(
        self,
        host: str,
        port: int = DEFAULT_PORT,
        timeout: float = DEFAULT_TIMEOUT,
    ) -> None:
        """Initialize the client for one device."""
        self.host = host
        self.port = port
        self._timeout = timeout

        self._transport: asyncio.DatagramTransport | None = None
        self._pending: dict[int, asyncio.Future[dict[str, Any]]] = {}
        self._next_id = 1
        self._lock = asyncio.Lock()

    # --- Endpoint lifecycle ---------------------------------------------

    async def _ensure_endpoint(self) -> None:
        """Create the datagram endpoint if it is not open yet."""
        if self._transport is not None and not self._transport.is_closing():
            return

        loop = asyncio.get_running_loop()
        # Bind an ephemeral local port. The device replies to whatever source
        # port the request came from, so there is no need to occupy the well
        # known port -- and doing so would collide between config entries.
        transport, _ = await loop.create_datagram_endpoint(
            lambda: _MarstekProtocol(self),
            local_addr=("0.0.0.0", 0),
        )
        self._transport = transport
        _LOGGER.debug("UDP endpoint opened for %s:%s", self.host, self.port)

    async def async_close(self) -> None:
        """Close the endpoint and fail any in-flight requests."""
        transport, self._transport = self._transport, None
        if transport is not None:
            transport.close()
        self._fail_pending(MarstekError("Connection closed"))

    def _fail_pending(self, exc: Exception) -> None:
        """Resolve all pending futures with an exception."""
        pending, self._pending = self._pending, {}
        for future in pending.values():
            if not future.done():
                future.set_exception(exc)

    def _handle_connection_lost(self, exc: Exception | None) -> None:
        """Handle the transport going away."""
        self._transport = None
        self._fail_pending(MarstekError(f"UDP endpoint lost: {exc}"))

    # --- Receive path ----------------------------------------------------

    def _handle_datagram(self, data: bytes, addr: tuple[str, int]) -> None:
        """Route one received datagram to its pending request."""
        if addr[0] != self.host:
            # Another Marstek device (or anything else) on the network.
            _LOGGER.debug("Ignoring datagram from unexpected peer %s", addr[0])
            return

        try:
            message = json.loads(data.decode("utf-8", errors="ignore"))
        except json.JSONDecodeError:
            _LOGGER.debug("Discarding non-JSON datagram from %s", addr[0])
            return

        if not isinstance(message, dict):
            return

        message_id = message.get("id")
        future = self._pending.pop(message_id, None) if isinstance(message_id, int) else None
        if future is None:
            # Late reply to a request that already timed out, or an unsolicited
            # broadcast. Dropping it is exactly what keeps values from landing
            # in the wrong sensor.
            _LOGGER.debug("Discarding unmatched response id=%s", message_id)
            return

        if future.done():
            return

        if "error" in message:
            future.set_exception(
                MarstekDeviceError(f"Device returned error: {message['error']}")
            )
            return

        result = message.get("result")
        if isinstance(result, dict):
            future.set_result(result)
        else:
            future.set_exception(
                MarstekError(f"Malformed response without result: {message}")
            )

    # --- Send path -------------------------------------------------------

    async def async_request(
        self, method: str, params: dict[str, Any] | None = None
    ) -> dict[str, Any]:
        """Send one command and await its matching response.

        Retries on timeout, since a lost datagram is routine on UDP. Raises
        MarstekTimeout if every attempt goes unanswered, or MarstekDeviceError
        if the device explicitly rejects the command.
        """
        if params is None:
            params = {"ble_mac": "0"} if method == CMD_GET_DEVICE else {"id": 0}

        last_error: Exception = MarstekTimeout(f"No response to '{method}'")

        for attempt in range(1, REQUEST_RETRIES + 1):
            try:
                return await self._attempt_request(method, params)
            except MarstekDeviceError:
                # An explicit rejection will be rejected again; do not retry.
                raise
            except (MarstekTimeout, MarstekError, OSError) as err:
                last_error = err
                _LOGGER.debug(
                    "Attempt %s/%s for '%s' on %s failed: %s",
                    attempt, REQUEST_RETRIES, method, self.host, err,
                )

        raise MarstekTimeout(str(last_error)) from last_error

    async def _attempt_request(
        self, method: str, params: dict[str, Any]
    ) -> dict[str, Any]:
        """Perform a single send/await cycle."""
        await self._ensure_endpoint()
        transport = self._transport
        if transport is None:
            raise MarstekError("UDP endpoint unavailable")

        loop = asyncio.get_running_loop()
        future: asyncio.Future[dict[str, Any]] = loop.create_future()

        # Hold the lock across the send AND the wait, so only one request is
        # ever in flight towards a given device.
        #
        # This is not an optimisation, it is a requirement of the hardware: the
        # device serves one request at a time and silently drops whatever
        # arrives while it is busy. Firing a poll's commands concurrently makes
        # it answer roughly the first one and ignore the rest, which shows up
        # as arbitrary endpoints timing out on every poll.
        async with self._lock:
            request_id = self._next_id
            # Stay inside 32 bits; the device echoes the id verbatim.
            self._next_id = request_id + 1 if request_id < 0x7FFFFFFF else 1
            self._pending[request_id] = future
            payload = json.dumps(
                {"id": request_id, "method": method, "params": params},
                separators=(",", ":"),
            ).encode("utf-8")
            transport.sendto(payload, (self.host, self.port))

            _LOGGER.debug(
                "Sent '%s' id=%s to %s:%s", method, request_id, self.host, self.port
            )

            try:
                async with asyncio.timeout(self._timeout):
                    return await future
            except TimeoutError as err:
                raise MarstekTimeout(
                    f"Timeout after {self._timeout}s waiting for '{method}'"
                ) from err
            finally:
                self._pending.pop(request_id, None)

    async def _request_or_none(
        self, method: str, params: dict[str, Any] | None = None
    ) -> dict[str, Any] | None:
        """Send a command, returning None instead of raising on failure."""
        try:
            return await self.async_request(method, params)
        except MarstekError as err:
            _LOGGER.debug("Command '%s' failed: %s", method, err)
            return None

    # --- Query commands --------------------------------------------------

    async def get_device_info(self) -> dict[str, Any] | None:
        """Get device information (Marstek.GetDevice)."""
        return await self._request_or_none(CMD_GET_DEVICE)

    async def get_battery_status(self) -> dict[str, Any] | None:
        """Get battery status (Bat.GetStatus)."""
        return await self._request_or_none(CMD_BAT_STATUS)

    async def get_es_mode(self) -> dict[str, Any] | None:
        """Get the current energy storage mode (ES.GetMode)."""
        return await self._request_or_none(CMD_ES_GET_MODE)

    async def get_es_status(self) -> dict[str, Any] | None:
        """Get energy storage power and energy counters (ES.GetStatus)."""
        return await self._request_or_none(CMD_ES_STATUS)

    async def get_em_status(self) -> dict[str, Any] | None:
        """Get energy meter / CT status (EM.GetStatus)."""
        return await self._request_or_none(CMD_EM_STATUS)

    async def get_wifi_status(self) -> dict[str, Any] | None:
        """Get Wi-Fi diagnostics (Wifi.GetStatus)."""
        return await self._request_or_none(CMD_WIFI_STATUS)

    # --- Control commands ------------------------------------------------

    async def set_es_mode(
        self, mode: str, config: dict[str, Any] | None = None
    ) -> bool:
        """Set the energy storage mode (ES.SetMode).

        Args:
            mode: One of Auto, AI, Manual, Passive, UPS.
            config: The mode-specific config block. For Passive this must
                carry the already sign-corrected power and cd_time; prefer
                set_passive_power(), which applies PASSIVE_POWER_SIGN for you.
        """
        mode_config: dict[str, Any] = {"mode": mode}

        if config is not None:
            mode_config.update(config)
        elif mode == ES_MODE_AUTO:
            mode_config["auto_cfg"] = {"enable": 1}
        elif mode == "AI":
            mode_config["ai_cfg"] = {"enable": 1}
        elif mode == "UPS":
            mode_config["ups_cfg"] = {"enable": 1}
        elif mode == ES_MODE_PASSIVE:
            # Entering Passive without a setpoint: hold at zero and let the
            # countdown return the device to its previous behaviour, rather
            # than silently pushing an arbitrary amount of power.
            mode_config["passive_cfg"] = {
                "power": 0,
                "cd_time": PASSIVE_CD_TIME_DEFAULT,
            }

        result = await self._request_or_none(
            CMD_ES_SET_MODE, {"id": 0, "config": mode_config}
        )
        return bool(result and result.get("set_result") is True)

    async def set_passive_power(self, power: int, cd_time: int) -> bool:
        """Enter Passive mode with a setpoint and a countdown.

        `power` is given in the integration's own convention (positive =
        discharge, negative = charge) and converted to the device convention
        via PASSIVE_POWER_SIGN -- see the comment on that constant.

        `cd_time` is the device-side watchdog: once it elapses without a new
        command the device leaves Passive on its own. This is why the
        integration needs no heartbeat of its own.
        """
        return await self.set_es_mode(
            ES_MODE_PASSIVE,
            {
                "passive_cfg": {
                    "power": int(power) * PASSIVE_POWER_SIGN,
                    "cd_time": int(cd_time),
                }
            },
        )

    async def set_dod(self, value: int) -> bool:
        """Set depth of discharge (DOD.SET), valid range 30-88."""
        result = await self._request_or_none(CMD_DOD_SET, {"value": int(value)})
        return bool(result and result.get("set_result") is True)

    async def set_ble_adv(self, enable: bool) -> bool:
        """Enable or disable Bluetooth advertising (Ble.Adv)."""
        # API: 0 = enable, 1 = disable (inverted logic per docs).
        result = await self._request_or_none(
            CMD_BLE_ADV, {"enable": 0 if enable else 1}
        )
        return bool(result and result.get("set_result") is True)

    async def set_led(self, state: bool) -> bool:
        """Control the status LED (Led.Ctrl)."""
        result = await self._request_or_none(
            CMD_LED_CTRL, {"state": 1 if state else 0}
        )
        return bool(result and result.get("set_result") is True)

    # --- Bulk data fetch -------------------------------------------------

    async def get_all_data(self, budget: float | None = None) -> dict[str, Any]:
        """Fetch every polled endpoint, one command after the other.

        The requests are issued strictly sequentially because the device only
        serves one at a time -- see the locking comment in _attempt_request.
        In normal operation each answer arrives within a few tens of
        milliseconds, so a full poll costs well under a second.

        `budget` caps how long the whole poll may take. Without it a device
        that has gone quiet would hold the poll for retries * timeout seconds
        per endpoint, far beyond the polling interval. Endpoints not reached
        within the budget are reported as None, exactly like an unanswered one.

        Each entry is None if that particular command went unanswered; the
        coordinator decides what to do with partial results.
        """
        endpoints: tuple[tuple[str, Any], ...] = (
            (DATA_DEVICE, self.get_device_info),
            (DATA_BATTERY, self.get_battery_status),
            (DATA_ES_MODE, self.get_es_mode),
            (DATA_ES_STATUS, self.get_es_status),
            (DATA_EM_STATUS, self.get_em_status),
            (DATA_WIFI, self.get_wifi_status),
        )

        loop = asyncio.get_running_loop()
        deadline = loop.time() + budget if budget is not None else None

        data: dict[str, Any] = {}
        for key, fetch in endpoints:
            if deadline is not None and loop.time() >= deadline:
                _LOGGER.debug("Poll budget exhausted before '%s'", key)
                data[key] = None
                continue
            try:
                data[key] = await fetch()
            except Exception as err:  # noqa: BLE001
                _LOGGER.debug("Fetch of '%s' raised: %s", key, err)
                data[key] = None

        successful = sum(1 for value in data.values() if value is not None)
        _LOGGER.debug(
            "Poll of %s complete: %s/%s endpoints answered",
            self.host, successful, len(data),
        )
        return data

    async def async_probe(self) -> dict[str, Any] | None:
        """One-shot reachability check used by the config flow."""
        try:
            return await self.async_request(CMD_GET_DEVICE)
        except MarstekError:
            return None
        finally:
            with contextlib.suppress(Exception):
                await self.async_close()


async def async_discover_devices(
    port: int = DEFAULT_PORT, timeout: float = DEFAULT_TIMEOUT
) -> list[dict[str, Any]]:
    """Broadcast Marstek.GetDevice and collect every device that answers.

    Returns one dict per device, each carrying the reported fields plus the
    source IP under "ip". Failures are swallowed: discovery is best effort and
    the user can always enter an address by hand.
    """
    loop = asyncio.get_running_loop()
    found: dict[str, dict[str, Any]] = {}

    class _DiscoveryProtocol(asyncio.DatagramProtocol):
        def datagram_received(self, data: bytes, addr: tuple[str, int]) -> None:
            try:
                message = json.loads(data.decode("utf-8", errors="ignore"))
            except json.JSONDecodeError:
                return
            result = message.get("result") if isinstance(message, dict) else None
            if isinstance(result, dict):
                found[addr[0]] = {**result, "ip": addr[0]}

    transport: asyncio.DatagramTransport | None = None
    try:
        transport, _ = await loop.create_datagram_endpoint(
            _DiscoveryProtocol,
            local_addr=("0.0.0.0", 0),
            allow_broadcast=True,
        )
        payload = json.dumps(
            {"id": 1, "method": CMD_GET_DEVICE, "params": {"ble_mac": "0"}},
            separators=(",", ":"),
        ).encode("utf-8")
        # Send twice: a single lost broadcast would otherwise hide a device.
        for _ in range(2):
            transport.sendto(payload, ("255.255.255.255", port))
            await asyncio.sleep(0.2)
        await asyncio.sleep(timeout)
    except OSError as err:
        _LOGGER.debug("Discovery broadcast failed: %s", err)
    finally:
        if transport is not None:
            transport.close()

    _LOGGER.debug("Discovery found %s device(s)", len(found))
    return list(found.values())
