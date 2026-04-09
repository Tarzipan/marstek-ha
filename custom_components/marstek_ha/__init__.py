"""The Marstek integration."""
from __future__ import annotations

import logging

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import Platform
from homeassistant.core import HomeAssistant
from homeassistant.helpers import entity_registry as er

from .const import DOMAIN
from .coordinator import MarstekDataUpdateCoordinator

_LOGGER = logging.getLogger(__name__)

PLATFORMS: list[Platform] = [
    Platform.SENSOR,
    Platform.BINARY_SENSOR,
    Platform.SELECT,
    Platform.NUMBER,
    Platform.SWITCH,
]


async def async_migrate_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Migrate config entry to current version."""
    if entry.version < 2:
        _LOGGER.info("Migrating Marstek config entry from version %s to 2", entry.version)
        hass.config_entries.async_update_entry(entry, version=2)
    return True


async def _async_migrate_unique_ids(hass: HomeAssistant, entry: ConfigEntry) -> None:
    """Migrate entity unique IDs from entry_id to BLE MAC based IDs."""
    if not entry.unique_id:
        return

    ble_mac = entry.unique_id
    old_prefix = f"{entry.entry_id}_"
    new_prefix = f"{ble_mac}_"

    if old_prefix == new_prefix:
        return

    registry = er.async_get(hass)
    entities = er.async_entries_for_config_entry(registry, entry.entry_id)

    for entity in entities:
        if entity.unique_id.startswith(old_prefix):
            new_unique_id = entity.unique_id.replace(old_prefix, new_prefix, 1)
            _LOGGER.debug(
                "Migrating entity %s unique_id: %s -> %s",
                entity.entity_id, entity.unique_id, new_unique_id,
            )
            registry.async_update_entity(entity.entity_id, new_unique_id=new_unique_id)


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Set up Marstek from a config entry."""
    # Migrate old entity unique IDs to BLE MAC based IDs
    await _async_migrate_unique_ids(hass, entry)

    coordinator = MarstekDataUpdateCoordinator(hass, entry)

    await coordinator.async_config_entry_first_refresh()

    hass.data.setdefault(DOMAIN, {})
    hass.data[DOMAIN][entry.entry_id] = coordinator

    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)

    return True


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Unload a config entry."""
    if unload_ok := await hass.config_entries.async_unload_platforms(entry, PLATFORMS):
        coordinator: MarstekDataUpdateCoordinator = hass.data[DOMAIN].pop(entry.entry_id)
        await coordinator.async_shutdown()

    return unload_ok
