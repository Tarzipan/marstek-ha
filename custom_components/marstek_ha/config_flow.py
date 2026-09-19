"""Config flow for the Marstek integration."""
from __future__ import annotations

import logging
from typing import Any

import voluptuous as vol

from homeassistant.config_entries import (
    ConfigEntry,
    ConfigFlow,
    ConfigFlowResult,
    OptionsFlow,
)
from homeassistant.core import callback
from homeassistant.helpers import config_validation as cv
from homeassistant.helpers.selector import (
    BooleanSelector,
    NumberSelector,
    NumberSelectorConfig,
    NumberSelectorMode,
)

from .const import (
    CONF_DEVICE_IP,
    CONF_DEVICE_PORT,
    CONF_MIN_WRITE_INTERVAL,
    CONF_MODBUS_ENABLED,
    CONF_MODBUS_PORT,
    CONF_MODBUS_UNIT_ID,
    CONF_SCAN_INTERVAL,
    DEFAULT_MIN_WRITE_INTERVAL,
    DEFAULT_PORT,
    DEFAULT_SCAN_INTERVAL,
    DOMAIN,
    MAX_SCAN_INTERVAL,
    MIN_SCAN_INTERVAL,
    MIN_WRITE_INTERVAL_MAX,
    MIN_WRITE_INTERVAL_MIN,
    MODBUS_DEFAULT_PORT,
    MODBUS_DEFAULT_UNIT_ID,
)
from .marstek_api import MarstekAPI, async_discover_devices

_LOGGER = logging.getLogger(__name__)


class CannotConnect(Exception):
    """The device did not answer."""


class InvalidDevice(Exception):
    """The device answered but did not look like a Marstek device."""


async def _async_probe(host: str, port: int) -> dict[str, Any]:
    """Probe a device and return its title and unique identifier."""
    api = MarstekAPI(host, port)
    device_info = await api.async_probe()

    if not device_info:
        raise CannotConnect(f"No response from {host}:{port}")

    ble_mac = device_info.get("ble_mac")
    if not ble_mac:
        raise InvalidDevice("Response did not contain a device identifier")

    return {
        "title": device_info.get("device") or "Marstek Device",
        "unique_id": str(ble_mac),
    }


def _connection_schema(host: str = "", port: int = DEFAULT_PORT) -> vol.Schema:
    """Build the host/port form schema."""
    return vol.Schema(
        {
            vol.Required(CONF_DEVICE_IP, default=host): str,
            vol.Optional(CONF_DEVICE_PORT, default=port): cv.port,
        }
    )


class MarstekConfigFlow(ConfigFlow, domain=DOMAIN):
    """Handle a config flow for Marstek."""

    VERSION = 2

    def __init__(self) -> None:
        """Initialize the flow."""
        self._discovered: list[dict[str, Any]] = []

    @staticmethod
    @callback
    def async_get_options_flow(entry: ConfigEntry) -> MarstekOptionsFlow:
        """Return the options flow handler."""
        return MarstekOptionsFlow()

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Offer discovered devices, or fall back to manual entry."""
        if user_input is not None:
            return await self.async_step_manual(user_input)

        self._discovered = [
            device
            for device in await async_discover_devices()
            if device.get("ble_mac")
            and str(device["ble_mac"]) not in self._async_current_ids()
        ]

        if not self._discovered:
            return await self.async_step_manual()

        return await self.async_step_pick_device()

    async def async_step_pick_device(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Let the user choose one of the devices found by broadcast."""
        if user_input is not None:
            if user_input[CONF_DEVICE_IP] == "manual":
                return await self.async_step_manual()
            return await self.async_step_manual(
                {
                    CONF_DEVICE_IP: user_input[CONF_DEVICE_IP],
                    CONF_DEVICE_PORT: DEFAULT_PORT,
                }
            )

        options = {
            device["ip"]: f"{device.get('device', 'Marstek')} ({device['ip']})"
            for device in self._discovered
        }
        options["manual"] = "Enter the address manually"

        return self.async_show_form(
            step_id="pick_device",
            data_schema=vol.Schema({vol.Required(CONF_DEVICE_IP): vol.In(options)}),
        )

    async def async_step_manual(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Add a device by address."""
        errors: dict[str, str] = {}

        if user_input is not None:
            host = user_input[CONF_DEVICE_IP]
            port = user_input.get(CONF_DEVICE_PORT, DEFAULT_PORT)
            try:
                info = await _async_probe(host, port)
            except CannotConnect:
                errors["base"] = "cannot_connect"
            except InvalidDevice:
                errors["base"] = "invalid_device"
            except Exception:  # noqa: BLE001
                _LOGGER.exception("Unexpected error probing %s", host)
                errors["base"] = "unknown"
            else:
                await self.async_set_unique_id(info["unique_id"])
                self._abort_if_unique_id_configured(
                    updates={CONF_DEVICE_IP: host, CONF_DEVICE_PORT: port}
                )
                return self.async_create_entry(
                    title=info["title"],
                    data={CONF_DEVICE_IP: host, CONF_DEVICE_PORT: port},
                )

            return self.async_show_form(
                step_id="manual",
                data_schema=_connection_schema(host, port),
                errors=errors,
            )

        return self.async_show_form(
            step_id="manual", data_schema=_connection_schema(), errors=errors
        )

    async def async_step_reconfigure(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Change the address of an already configured device."""
        entry = self._get_reconfigure_entry()
        errors: dict[str, str] = {}

        if user_input is not None:
            host = user_input[CONF_DEVICE_IP]
            port = user_input.get(CONF_DEVICE_PORT, DEFAULT_PORT)
            try:
                info = await _async_probe(host, port)
            except CannotConnect:
                errors["base"] = "cannot_connect"
            except InvalidDevice:
                errors["base"] = "invalid_device"
            except Exception:  # noqa: BLE001
                _LOGGER.exception("Unexpected error probing %s", host)
                errors["base"] = "unknown"
            else:
                # Refuse to point this entry at a different physical device --
                # that would silently mix two units' history into one device.
                await self.async_set_unique_id(info["unique_id"])
                self._abort_if_unique_id_mismatch(reason="wrong_device")
                return self.async_update_reload_and_abort(
                    entry,
                    data_updates={CONF_DEVICE_IP: host, CONF_DEVICE_PORT: port},
                )

        return self.async_show_form(
            step_id="reconfigure",
            data_schema=_connection_schema(
                entry.data.get(CONF_DEVICE_IP, ""),
                entry.data.get(CONF_DEVICE_PORT, DEFAULT_PORT),
            ),
            errors=errors,
        )


class MarstekOptionsFlow(OptionsFlow):
    """Handle polling and write-rate options."""

    async def async_step_init(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Manage the options."""
        if user_input is not None:
            return self.async_create_entry(
                data={
                    CONF_SCAN_INTERVAL: int(user_input[CONF_SCAN_INTERVAL]),
                    CONF_MIN_WRITE_INTERVAL: int(user_input[CONF_MIN_WRITE_INTERVAL]),
                    CONF_MODBUS_ENABLED: bool(user_input[CONF_MODBUS_ENABLED]),
                    CONF_MODBUS_PORT: int(user_input[CONF_MODBUS_PORT]),
                    CONF_MODBUS_UNIT_ID: int(user_input[CONF_MODBUS_UNIT_ID]),
                }
            )

        options = self.config_entry.options
        schema = vol.Schema(
            {
                vol.Required(
                    CONF_SCAN_INTERVAL,
                    default=options.get(CONF_SCAN_INTERVAL, DEFAULT_SCAN_INTERVAL),
                ): NumberSelector(
                    NumberSelectorConfig(
                        min=MIN_SCAN_INTERVAL,
                        max=MAX_SCAN_INTERVAL,
                        step=1,
                        unit_of_measurement="s",
                        mode=NumberSelectorMode.BOX,
                    )
                ),
                vol.Required(
                    CONF_MIN_WRITE_INTERVAL,
                    default=options.get(
                        CONF_MIN_WRITE_INTERVAL, DEFAULT_MIN_WRITE_INTERVAL
                    ),
                ): NumberSelector(
                    NumberSelectorConfig(
                        min=MIN_WRITE_INTERVAL_MIN,
                        max=MIN_WRITE_INTERVAL_MAX,
                        step=1,
                        unit_of_measurement="s",
                        mode=NumberSelectorMode.BOX,
                    )
                ),
                # The Modbus channel exists solely for the charge and discharge
                # power limits, which the UDP Open API does not expose. Off by
                # default: the device serves only one Modbus session and is
                # known to lock up under frequent access, so it is not something
                # to enable without meaning to. See modbus.py.
                vol.Required(
                    CONF_MODBUS_ENABLED,
                    default=options.get(CONF_MODBUS_ENABLED, False),
                ): BooleanSelector(),
                vol.Required(
                    CONF_MODBUS_PORT,
                    default=options.get(CONF_MODBUS_PORT, MODBUS_DEFAULT_PORT),
                ): cv.port,
                vol.Required(
                    CONF_MODBUS_UNIT_ID,
                    default=options.get(CONF_MODBUS_UNIT_ID, MODBUS_DEFAULT_UNIT_ID),
                ): vol.All(vol.Coerce(int), vol.Range(min=1, max=255)),
            }
        )

        return self.async_show_form(step_id="init", data_schema=schema)
