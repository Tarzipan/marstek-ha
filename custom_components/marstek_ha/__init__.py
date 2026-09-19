"""The Marstek integration."""
from __future__ import annotations

import logging

import voluptuous as vol

from homeassistant.config_entries import ConfigEntryState
from homeassistant.const import Platform
from homeassistant.core import HomeAssistant, ServiceCall
from homeassistant.exceptions import HomeAssistantError, ServiceValidationError
from homeassistant.helpers import config_validation as cv, device_registry as dr
from homeassistant.helpers import entity_registry as er

from .const import (
    ATTR_CD_TIME,
    ATTR_POWER,
    DOMAIN,
    PASSIVE_CD_TIME_MAX,
    PASSIVE_CD_TIME_MIN,
    PASSIVE_POWER_MAX,
    PASSIVE_POWER_MIN,
    SERVICE_SET_PASSIVE_POWER,
)
from .coordinator import MarstekConfigEntry, MarstekDataUpdateCoordinator

_LOGGER = logging.getLogger(__name__)

PLATFORMS: list[Platform] = [
    Platform.BINARY_SENSOR,
    Platform.NUMBER,
    Platform.SELECT,
    Platform.SENSOR,
    Platform.SWITCH,
]

SET_PASSIVE_POWER_SCHEMA = vol.Schema(
    {
        vol.Required("device_id"): vol.All(cv.ensure_list, [cv.string]),
        vol.Required(ATTR_POWER): vol.All(
            vol.Coerce(int), vol.Range(min=PASSIVE_POWER_MIN, max=PASSIVE_POWER_MAX)
        ),
        vol.Required(ATTR_CD_TIME): vol.All(
            vol.Coerce(int), vol.Range(min=PASSIVE_CD_TIME_MIN, max=PASSIVE_CD_TIME_MAX)
        ),
    }
)


async def async_migrate_entry(hass: HomeAssistant, entry: MarstekConfigEntry) -> bool:
    """Migrate a config entry to the current version."""
    if entry.version < 2:
        _LOGGER.info("Migrating Marstek config entry from version %s to 2", entry.version)
        hass.config_entries.async_update_entry(entry, version=2)
    return True


async def _async_migrate_unique_ids(
    hass: HomeAssistant, entry: MarstekConfigEntry
) -> None:
    """Migrate entity unique IDs from entry_id based to BLE MAC based."""
    if not entry.unique_id:
        return

    old_prefix = f"{entry.entry_id}_"
    new_prefix = f"{entry.unique_id}_"
    if old_prefix == new_prefix:
        return

    registry = er.async_get(hass)
    for entity in er.async_entries_for_config_entry(registry, entry.entry_id):
        if entity.unique_id.startswith(old_prefix):
            new_unique_id = entity.unique_id.replace(old_prefix, new_prefix, 1)
            _LOGGER.debug(
                "Migrating %s unique_id: %s -> %s",
                entity.entity_id, entity.unique_id, new_unique_id,
            )
            registry.async_update_entity(entity.entity_id, new_unique_id=new_unique_id)


def _resolve_coordinators(
    hass: HomeAssistant, device_ids: list[str]
) -> list[MarstekDataUpdateCoordinator]:
    """Map the service call's target devices onto their coordinators."""
    device_registry = dr.async_get(hass)
    coordinators: list[MarstekDataUpdateCoordinator] = []

    for device_id in device_ids:
        device = device_registry.async_get(device_id)
        if device is None:
            raise ServiceValidationError(f"Unknown device: {device_id}")

        for entry_id in device.config_entries:
            entry = hass.config_entries.async_get_entry(entry_id)
            if entry is not None and entry.domain == DOMAIN:
                coordinator = getattr(entry, "runtime_data", None)
                if coordinator is not None:
                    coordinators.append(coordinator)
                break

    if not coordinators:
        raise ServiceValidationError(
            "No loaded Marstek device matched the service target"
        )
    return coordinators


async def _async_register_services(hass: HomeAssistant) -> None:
    """Register integration-level services once."""
    if hass.services.has_service(DOMAIN, SERVICE_SET_PASSIVE_POWER):
        return

    async def _async_set_passive_power(call: ServiceCall) -> None:
        """Set Passive mode, setpoint and countdown in a single command.

        This is the integration's main write path for load sharing between
        several storage units: the countdown makes the device fall back on its
        own if Home Assistant goes quiet, so no watchdog is needed here.
        """
        power = call.data[ATTR_POWER]
        cd_time = call.data[ATTR_CD_TIME]

        for coordinator in _resolve_coordinators(hass, call.data["device_id"]):
            if not await coordinator.async_set_passive_power(power, cd_time):
                raise HomeAssistantError(
                    f"Failed to set passive power on {coordinator.api.host}"
                )

    hass.services.async_register(
        DOMAIN,
        SERVICE_SET_PASSIVE_POWER,
        _async_set_passive_power,
        schema=SET_PASSIVE_POWER_SCHEMA,
    )


async def async_setup_entry(hass: HomeAssistant, entry: MarstekConfigEntry) -> bool:
    """Set up Marstek from a config entry."""
    await _async_migrate_unique_ids(hass, entry)

    coordinator = MarstekDataUpdateCoordinator(hass, entry)
    await coordinator.async_config_entry_first_refresh()

    entry.runtime_data = coordinator

    await _async_register_services(hass)
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)

    entry.async_on_unload(entry.add_update_listener(_async_options_updated))

    return True


async def _async_options_updated(
    hass: HomeAssistant, entry: MarstekConfigEntry
) -> None:
    """Apply changed options, reloading only when that is unavoidable."""
    coordinator = entry.runtime_data

    # Whether the Modbus power limit entities exist, and which endpoint they
    # talk to, is decided when the platforms are set up. Changing that needs a
    # reload; everything else can be applied in place.
    if coordinator.modbus_settings_changed:
        await hass.config_entries.async_reload(entry.entry_id)
        return

    coordinator.async_update_interval()
    await coordinator.async_request_refresh()


async def async_unload_entry(hass: HomeAssistant, entry: MarstekConfigEntry) -> bool:
    """Unload a config entry."""
    if unload_ok := await hass.config_entries.async_unload_platforms(entry, PLATFORMS):
        await entry.runtime_data.async_shutdown()

        # Drop the service once the last entry goes away.
        loaded = [
            other
            for other in hass.config_entries.async_entries(DOMAIN)
            if other.entry_id != entry.entry_id
            and other.state is ConfigEntryState.LOADED
        ]
        if not loaded:
            hass.services.async_remove(DOMAIN, SERVICE_SET_PASSIVE_POWER)

    return unload_ok
