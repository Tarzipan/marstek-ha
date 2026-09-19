"""Diagnostics for the Marstek integration.

Dumps the last raw answer of every polled endpoint. The point is to make
questions about scaling and field availability answerable from a file rather
than from guesswork: whether a counter sits at zero because the device reports
zero or because the integration mis-reads it, which fields a given firmware
omits, and what scaling a value actually arrives in.
"""
from __future__ import annotations

from typing import Any

from homeassistant.core import HomeAssistant

from .const import (
    CONF_DEVICE_IP,
    CONF_MODBUS_ENABLED,
    MODBUS_REG_MAX_CHARGE_POWER,
    MODBUS_REG_MAX_DISCHARGE_POWER,
)
from .coordinator import MarstekConfigEntry

# Fields that identify the physical unit rather than describe its state.
TO_REDACT = {"ble_mac", "wifi_mac", "sta_ip", "sta_mac", "ssid", "wifi_name"}


def _redact(value: Any) -> Any:
    """Recursively replace identifying fields with a placeholder."""
    if isinstance(value, dict):
        return {
            key: "**REDACTED**" if key in TO_REDACT else _redact(inner)
            for key, inner in value.items()
        }
    if isinstance(value, list):
        return [_redact(item) for item in value]
    return value


async def async_get_config_entry_diagnostics(
    hass: HomeAssistant, entry: MarstekConfigEntry
) -> dict[str, Any]:
    """Return diagnostics for a config entry."""
    coordinator = entry.runtime_data

    modbus: dict[str, Any] = {"enabled": entry.options.get(CONF_MODBUS_ENABLED, False)}
    if coordinator.modbus is not None:
        # Whatever was read at startup or written since -- deliberately not a
        # fresh read, so collecting diagnostics never opens a Modbus session.
        modbus["max_charge_power"] = coordinator.modbus.known_value(
            MODBUS_REG_MAX_CHARGE_POWER
        )
        modbus["max_discharge_power"] = coordinator.modbus.known_value(
            MODBUS_REG_MAX_DISCHARGE_POWER
        )

    return {
        "entry": {
            "version": entry.version,
            "options": dict(entry.options),
            "host_configured": bool(entry.data.get(CONF_DEVICE_IP)),
        },
        "coordinator": {
            "last_update_success": coordinator.last_update_success,
            "scan_interval": coordinator.scan_interval,
            "min_write_interval": coordinator.min_write_interval,
            "current_mode": coordinator.current_mode,
            "passive_power": coordinator.passive_power,
            "passive_cd_time": coordinator.passive_cd_time,
        },
        "modbus": modbus,
        # The raw, unscaled payloads. This is the part worth reading.
        "raw_data": _redact(coordinator.data or {}),
    }
