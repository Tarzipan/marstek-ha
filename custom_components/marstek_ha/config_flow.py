"""Config flow for Marstek integration."""
from __future__ import annotations

import asyncio
import logging
from typing import Any

import voluptuous as vol

from homeassistant import config_entries
from homeassistant.core import HomeAssistant
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


async def _async_test_connection(host: str, port: int) -> dict[str, Any]:
    """Test connection to device and return device info.

    Raises CannotConnect or InvalidDevice on failure.
    """
    api = MarstekAPI(host, port, port)

    try:
        if not await api.connect():
            raise CannotConnect("Failed to connect to device")

        device_info = await api.get_device_info()

        if not device_info:
            raise InvalidDevice("Device connected but did not return valid information")

        return {
            "title": device_info.get("device", "Marstek Device"),
            "serial": device_info.get("ble_mac", "unknown"),
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

    VERSION = 2

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        """Handle the initial step."""
        errors: dict[str, str] = {}

        if user_input is not None:
            try:
                info = await _async_test_connection(
                    user_input[CONF_DEVICE_IP],
                    user_input.get(CONF_DEVICE_PORT, DEFAULT_PORT),
                )
            except CannotConnect:
                errors["base"] = "cannot_connect"
            except InvalidDevice:
                errors["base"] = "invalid_device"
            except Exception:
                _LOGGER.exception("Unexpected exception during validation")
                errors["base"] = "unknown"
            else:
                await self.async_set_unique_id(info["serial"])
                self._abort_if_unique_id_configured()

                return self.async_create_entry(
                    title=info["title"],
                    data=user_input,
                )

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

    async def async_step_reconfigure(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        """Handle reconfiguration of the device IP/port."""
        entry = self.hass.config_entries.async_get_entry(self.context["entry_id"])
        assert entry is not None

        errors: dict[str, str] = {}

        if user_input is not None:
            try:
                await _async_test_connection(
                    user_input[CONF_DEVICE_IP],
                    user_input.get(CONF_DEVICE_PORT, DEFAULT_PORT),
                )
            except CannotConnect:
                errors["base"] = "cannot_connect"
            except InvalidDevice:
                errors["base"] = "invalid_device"
            except Exception:
                _LOGGER.exception("Unexpected exception during reconfigure validation")
                errors["base"] = "unknown"
            else:
                return self.async_update_reload_and_abort(
                    entry,
                    data={**entry.data, **user_input},
                )

        data_schema = vol.Schema(
            {
                vol.Required(
                    CONF_DEVICE_IP, default=entry.data.get(CONF_DEVICE_IP, "")
                ): str,
                vol.Optional(
                    CONF_DEVICE_PORT, default=entry.data.get(CONF_DEVICE_PORT, DEFAULT_PORT)
                ): cv.port,
            }
        )

        return self.async_show_form(
            step_id="reconfigure",
            data_schema=data_schema,
            errors=errors,
        )


class CannotConnect(Exception):
    """Error to indicate we cannot connect."""


class InvalidDevice(Exception):
    """Error to indicate the device is invalid or not responding correctly."""
