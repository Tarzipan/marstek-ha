"""Config flow for Marstek integration."""
from __future__ import annotations

import asyncio
import logging
from typing import Any

import voluptuous as vol

from homeassistant import config_entries
from homeassistant.const import CONF_HOST, CONF_PORT
from homeassistant.core import HomeAssistant, callback
from homeassistant.data_entry_flow import FlowResult
from homeassistant.helpers import config_validation as cv

from .const import (
    CONF_DEVICE_IP,
    CONF_DEVICE_PORT,
    DEFAULT_PORT,
    DOMAIN,
)
from .marstek_api import MarstekAPI

_LOGGER = logging.getLogger(__name__)


async def validate_input(hass: HomeAssistant, data: dict[str, Any]) -> dict[str, Any]:
    """Validate the user input allows us to connect."""
    host = data[CONF_DEVICE_IP]
    port = data.get(CONF_DEVICE_PORT, DEFAULT_PORT)

    api = MarstekAPI(host, port, port)

    try:
        # connect() already calls get_device_info() internally to verify
        if not await api.connect():
            raise CannotConnect("Failed to connect to device")

        # Fetch device info for metadata (connect verified reachability,
        # but we need the response data for unique ID and title)
        device_info = await api.get_device_info()

        if not device_info:
            raise InvalidDevice("Device connected but did not return valid information")

        device_name = device_info.get("device", "Marstek Device")
        ble_mac = device_info.get("ble_mac", "unknown")

        return {
            "title": device_name,
            "serial": ble_mac,
            "model": device_name,
        }
    except (CannotConnect, InvalidDevice):
        raise
    except asyncio.TimeoutError as err:
        raise CannotConnect("Connection timeout") from err
    except ConnectionRefusedError as err:
        raise CannotConnect("Connection refused") from err
    except OSError as err:
        raise CannotConnect(f"Network error: {err}") from err
    finally:
        await api.disconnect()


class MarstekConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    """Handle a config flow for Marstek."""

    VERSION = 1

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        """Handle the initial step."""
        errors: dict[str, str] = {}

        if user_input is not None:
            try:
                info = await validate_input(self.hass, user_input)
            except CannotConnect:
                errors["base"] = "cannot_connect"
            except InvalidDevice:
                errors["base"] = "invalid_device"
            except Exception:  # pylint: disable=broad-except
                _LOGGER.exception("Unexpected exception during validation")
                errors["base"] = "unknown"
            else:
                await self.async_set_unique_id(info["serial"])
                self._abort_if_unique_id_configured()

                return self.async_create_entry(
                    title=info["title"],
                    data=user_input,
                )

        # Show manual configuration form
        data_schema = vol.Schema(
            {
                vol.Required(CONF_DEVICE_IP): str,
                vol.Optional(CONF_DEVICE_PORT, default=DEFAULT_PORT): cv.port,
            }
        )

        return self.async_show_form(
            step_id="user",
            data_schema=data_schema,
            errors=errors,
        )


class CannotConnect(Exception):
    """Error to indicate we cannot connect."""


class InvalidDevice(Exception):
    """Error to indicate the device is invalid or not responding correctly."""

