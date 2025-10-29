"""Marstek API client using UDP protocol."""
from __future__ import annotations

import asyncio
import json
import logging
import socket
from typing import Any

from .const import (
    CMD_BAT_STATUS,
    CMD_BLE_STATUS,
    CMD_ES_GET_MODE,
    CMD_ES_SET_MODE,
    CMD_ES_STATUS,
    CMD_GET_DEVICE,
    CMD_PV_STATUS,
    CMD_WIFI_STATUS,
    DEFAULT_PORT,
    DEFAULT_TIMEOUT,
)

_LOGGER = logging.getLogger(__name__)


class MarstekAPI:
    """Marstek API client using UDP protocol."""

    def __init__(self, host: str, port: int = DEFAULT_PORT, local_port: int = DEFAULT_PORT) -> None:
        """Initialize the API client.
        
        Args:
            host: IP address of the Marstek device
            port: UDP port of the device (default: 30000)
            local_port: Local UDP port to bind to (default: 30000)
        """
        self.host = host
        self.port = port
        self.local_port = local_port
        self._sock: socket.socket | None = None
        self._connected = False
        self._timeout = DEFAULT_TIMEOUT

    async def connect(self) -> bool:
        """Connect (bind) to the local UDP port."""
        try:
            # Create UDP socket
            self._sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            self._sock.settimeout(self._timeout)

            # Bind to local port
            try:
                self._sock.bind(('', self.local_port))
            except OSError as bind_err:
                _LOGGER.debug("Could not bind to port %s, using random port: %s", self.local_port, bind_err)
                # Try with random port
                self._sock.bind(('', 0))

            self._connected = True

            # Test connection with a simple command
            device_info = await self.get_device_info()
            if device_info:
                _LOGGER.debug("Successfully connected to Marstek device")
                return True
            else:
                _LOGGER.error("Device did not respond to test command")
                return False

        except OSError as err:
            _LOGGER.error("Failed to create UDP socket: %s", err)
            return False
        except Exception as err:
            _LOGGER.error("Unexpected error setting up UDP connection: %s", err)
            return False

    async def disconnect(self) -> None:
        """Close the UDP socket."""
        if self._sock:
            try:
                self._sock.close()
                _LOGGER.debug("UDP socket closed")
            except Exception as err:
                _LOGGER.debug("Error closing socket: %s", err)
            finally:
                self._sock = None
                self._connected = False

    async def _send_command(self, command: str, params: dict[str, Any] | None = None) -> dict[str, Any] | None:
        """Send a command to the device via UDP and return the response."""
        if not self._sock:
            _LOGGER.debug("No active socket, attempting to connect...")
            if not await self.connect():
                _LOGGER.error("Cannot send command '%s': connection failed", command)
                return None

        try:
            # Build request according to protocol format
            # Based on user's example: {"id":1,"method":"Marstek.GetDevice","params":{"ble_mac":"0"}}
            # Note: ID must be constant (1), not incrementing
            request = {
                "id": 1,
                "method": command,
                "params": params or {}
            }

            # Add default params if not provided
            if not request["params"]:
                request["params"] = {"ble_mac": "0"}

            message = json.dumps(request, separators=(',', ':')).encode('utf-8')

            _LOGGER.info("→ Sending UDP command: %s", command)
            _LOGGER.debug("  Request payload: %s", message.decode('utf-8'))
            _LOGGER.debug("  Request size: %d bytes", len(message))
            _LOGGER.debug("  Sending from local port %s to %s:%s", 
                         self._sock.getsockname()[1] if self._sock else "unknown",
                         self.host, self.port)

            # Send the command via UDP
            await asyncio.get_event_loop().run_in_executor(
                None, self._sock.sendto, message, (self.host, self.port)
            )
            _LOGGER.debug("  ✓ Command sent, waiting for response...")

            # Receive response
            try:
                response_data, addr = await asyncio.get_event_loop().run_in_executor(
                    None, self._sock.recvfrom, 4096
                )
                
                _LOGGER.debug("  ✓ Received %d bytes from %s", len(response_data), addr)
                _LOGGER.debug("  Raw response (hex): %s", response_data.hex())
                _LOGGER.debug("  Raw response (ascii): %s", response_data)

                # Decode response
                response_str = response_data.decode('utf-8', errors='ignore')
                _LOGGER.debug("  Decoded response: %s", response_str)

                # Parse JSON
                response = json.loads(response_str)
                _LOGGER.info("← Received response for '%s'", command)
                
                if "result" in response:
                    _LOGGER.debug("  ✓ Command successful, result keys: %s", list(response["result"].keys()))
                    return response["result"]
                elif "error" in response:
                    _LOGGER.error("  ✗ Device returned error: %s", response["error"])
                    return None
                else:
                    _LOGGER.warning("  ⚠ Unexpected response format: %s", response)
                    return response

            except socket.timeout:
                _LOGGER.error("  ✗ Timeout waiting for response (waited %s seconds)", self._timeout)
                _LOGGER.error("  → Check if the device IP is correct: %s", self.host)
                _LOGGER.error("  → Check if the device port is correct: %s", self.port)
                _LOGGER.error("  → Check if the device is powered on and connected")
                return None
            except ConnectionResetError:
                _LOGGER.error("  ✗ ConnectionResetError: Remote host sent Port Unreachable (ICMP)")
                _LOGGER.error("  → The device is reachable but port %s is closed", self.port)
                _LOGGER.error("  → Check if the correct port is configured")
                return None

        except json.JSONDecodeError as err:
            _LOGGER.error("  ✗ Failed to parse JSON response: %s", err)
            _LOGGER.error("  → Response was: %s", response_data if 'response_data' in locals() else "no data")
            _LOGGER.error("  → The device might not be using the expected protocol")
            return None
        except Exception as err:
            _LOGGER.error("  ✗ Error sending command '%s': %s", command, err)
            _LOGGER.error("  → Error type: %s", type(err).__name__)
            return None

    async def get_device_info(self) -> dict[str, Any] | None:
        """Get device information."""
        return await self._send_command(CMD_GET_DEVICE)

    async def get_wifi_status(self) -> dict[str, Any] | None:
        """Get WiFi status."""
        return await self._send_command(CMD_WIFI_STATUS)

    async def get_ble_status(self) -> dict[str, Any] | None:
        """Get Bluetooth status."""
        return await self._send_command(CMD_BLE_STATUS)

    async def get_battery_status(self) -> dict[str, Any] | None:
        """Get battery status."""
        return await self._send_command(CMD_BAT_STATUS, {"id": 0})

    async def get_pv_status(self) -> dict[str, Any] | None:
        """Get PV status."""
        return await self._send_command(CMD_PV_STATUS, {"id": 0})

    async def get_es_status(self) -> dict[str, Any] | None:
        """Get energy storage status."""
        return await self._send_command(CMD_ES_STATUS, {"id": 0})

    async def get_es_mode(self) -> dict[str, Any] | None:
        """Get energy storage mode and all related data."""
        result = await self._send_command(CMD_ES_GET_MODE, {"id": 0})
        return result

    async def set_es_mode(self, mode: str, config: dict[str, Any] | None = None) -> bool:
        """Set energy storage mode.

        Args:
            mode: Mode name (Auto, AI, Manual, Passive)
            config: Optional mode-specific configuration

        Returns:
            True if successful, False otherwise
        """
        # Build the configuration based on mode
        if config is None:
            config = {}

        # Prepare mode-specific configuration
        mode_config = {"mode": mode}

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

        # Check if the result indicates success
        if result and result.get("set_result") is True:
            return True

        return False

    async def get_all_data(self) -> dict[str, Any]:
        """Get all data from the device.

        Only fetches data from commands that are known to work with VenusE 3.0:
        - Marstek.GetDevice
        - Bat.GetStatus
        - ES.GetMode
        """
        _LOGGER.debug("Fetching all data from device...")

        # Only use commands that work with VenusE 3.0
        data = {
            "device": await self.get_device_info(),
            "battery": await self.get_battery_status(),
            "es_mode": await self.get_es_mode(),
        }

        _LOGGER.debug("Data fetch complete. Successful: %s/%s",
                     sum(1 for v in data.values() if v is not None),
                     len(data))

        return data


