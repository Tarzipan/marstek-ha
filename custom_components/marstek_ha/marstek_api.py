"""Marstek API client using UDP protocol."""
from __future__ import annotations

import asyncio
import json
import logging
import socket
from typing import Any

from .const import (
    CMD_BAT_STATUS,
    CMD_ES_GET_MODE,
    CMD_ES_SET_MODE,
    CMD_GET_DEVICE,
    DEFAULT_PORT,
    DEFAULT_TIMEOUT,
)

_LOGGER = logging.getLogger(__name__)


class MarstekAPI:
    """Marstek API client using UDP protocol."""

    def __init__(self, host: str, port: int = DEFAULT_PORT, local_port: int = DEFAULT_PORT) -> None:
        """Initialize the API client."""
        self.host = host
        self.port = port
        self.local_port = local_port
        self._sock: socket.socket | None = None
        self._connected = False
        self._timeout = DEFAULT_TIMEOUT

    def _create_socket(self) -> bool:
        """Create and bind the UDP socket. Returns True on success."""
        try:
            self._sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            self._sock.settimeout(self._timeout)

            try:
                self._sock.bind(('', self.local_port))
            except OSError as bind_err:
                _LOGGER.debug("Could not bind to port %s, using random port: %s", self.local_port, bind_err)
                self._sock.bind(('', 0))

            self._connected = True
            return True
        except OSError as err:
            _LOGGER.error("Failed to create UDP socket: %s", err)
            self._close_socket()
            return False

    def _close_socket(self) -> None:
        """Close the socket and reset state."""
        if self._sock:
            try:
                self._sock.close()
            except OSError:
                pass
            self._sock = None
        self._connected = False

    async def connect(self) -> bool:
        """Connect (bind) to the local UDP port and verify device is reachable."""
        if not self._create_socket():
            return False

        device_info = await self.get_device_info()
        if device_info:
            _LOGGER.debug("Successfully connected to Marstek device")
            return True

        _LOGGER.error("Device did not respond to test command")
        return False

    async def disconnect(self) -> None:
        """Close the UDP socket."""
        self._close_socket()
        _LOGGER.debug("UDP socket closed")

    async def _send_command(self, command: str, params: dict[str, Any] | None = None) -> dict[str, Any] | None:
        """Send a command to the device via UDP and return the response."""
        if not self._sock or not self._connected:
            _LOGGER.debug("No active socket, attempting to reconnect...")
            self._close_socket()
            if not self._create_socket():
                _LOGGER.error("Cannot send command '%s': socket creation failed", command)
                return None

        request = {
            "id": 1,
            "method": command,
            "params": params or {"ble_mac": "0"},
        }

        message = json.dumps(request, separators=(',', ':')).encode('utf-8')

        _LOGGER.debug("Sending UDP command: %s to %s:%s", command, self.host, self.port)

        try:
            loop = asyncio.get_running_loop()

            await loop.run_in_executor(
                None, self._sock.sendto, message, (self.host, self.port)
            )

            response_data, addr = await loop.run_in_executor(
                None, self._sock.recvfrom, 4096
            )

            _LOGGER.debug("Received %d bytes from %s for '%s'", len(response_data), addr, command)

            response_str = response_data.decode('utf-8', errors='ignore')
            response = json.loads(response_str)

            if "result" in response:
                _LOGGER.debug("Command '%s' successful, result keys: %s", command, list(response["result"].keys()))
                return response["result"]

            if "error" in response:
                _LOGGER.error("Device returned error for '%s': %s", command, response["error"])
                return None

            _LOGGER.warning("Unexpected response format for '%s': %s", command, response)
            return response

        except socket.timeout:
            _LOGGER.warning(
                "Timeout waiting for response to '%s' (waited %ss) - check device IP %s, port %s, and power",
                command, self._timeout, self.host, self.port,
            )
            return None
        except ConnectionResetError:
            _LOGGER.error(
                "ConnectionResetError for '%s': port %s appears closed on %s",
                command, self.port, self.host,
            )
            # Socket is likely broken after ICMP error, recreate on next call
            self._close_socket()
            return None
        except json.JSONDecodeError as err:
            _LOGGER.error("Failed to parse JSON response for '%s': %s", command, err)
            return None
        except OSError as err:
            _LOGGER.error("Socket error sending '%s': %s", command, err)
            # Socket may be broken, recreate on next call
            self._close_socket()
            return None

    async def get_device_info(self) -> dict[str, Any] | None:
        """Get device information."""
        return await self._send_command(CMD_GET_DEVICE)

    async def get_battery_status(self) -> dict[str, Any] | None:
        """Get battery status."""
        return await self._send_command(CMD_BAT_STATUS, {"id": 0})

    async def get_es_mode(self) -> dict[str, Any] | None:
        """Get energy storage mode and all related data."""
        return await self._send_command(CMD_ES_GET_MODE, {"id": 0})

    async def set_es_mode(self, mode: str, config: dict[str, Any] | None = None) -> bool:
        """Set energy storage mode.

        Args:
            mode: Mode name (Auto, AI, Manual, Passive)
            config: Optional mode-specific configuration

        Returns:
            True if successful, False otherwise
        """
        if config is None:
            config = {}

        mode_config: dict[str, Any] = {"mode": mode}

        if mode == "Auto":
            mode_config["auto_cfg"] = config.get("auto_cfg", {"enable": 1})
        elif mode == "AI":
            mode_config["ai_cfg"] = config.get("ai_cfg", {"enable": 1})
        elif mode == "Manual":
            mode_config["manual_cfg"] = config.get("manual_cfg", {
                "time_num": 1,
                "start_time": "08:30",
                "end_time": "20:30",
                "week_set": 127,
                "power": 100,
                "enable": 1
            })
        elif mode == "Passive":
            mode_config["passive_cfg"] = config.get("passive_cfg", {
                "power": 100,
                "cd_time": 300
            })

        params = {
            "id": 1,
            "config": mode_config
        }

        result = await self._send_command(CMD_ES_SET_MODE, params)
        return bool(result and result.get("set_result") is True)

    async def get_all_data(self) -> dict[str, Any]:
        """Get all data from the device.

        Only fetches data from commands that are known to work with VenusE 3.0:
        - Marstek.GetDevice
        - Bat.GetStatus
        - ES.GetMode
        """
        data = {
            "device": await self.get_device_info(),
            "battery": await self.get_battery_status(),
            "es_mode": await self.get_es_mode(),
        }

        successful = sum(1 for v in data.values() if v is not None)
        _LOGGER.debug("Data fetch complete. Successful: %s/%s", successful, len(data))

        return data
