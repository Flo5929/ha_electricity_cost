"""Electricity Cost integration."""
from __future__ import annotations

import logging
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers import entity_registry as er, device_registry as dr

from .const import DOMAIN, PLATFORMS

_LOGGER = logging.getLogger(__name__)


async def async_setup(hass: HomeAssistant, config: dict) -> bool:
    hass.data.setdefault(DOMAIN, {})
    return True


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    hass.data.setdefault(DOMAIN, {})
    hass.data[DOMAIN][entry.entry_id] = dict(entry.data)

    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    entry.async_on_unload(entry.add_update_listener(async_update_listener))
    return True


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    unload_ok = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
    if unload_ok:
        hass.data[DOMAIN].pop(entry.entry_id)
    return unload_ok


async def async_update_listener(hass: HomeAssistant, entry: ConfigEntry) -> None:
    """
    Called when options change (device added or removed).
    Cleans up entities and devices no longer present in options before reloading.
    """
    current_device_names = {
        d["name"] for d in entry.options.get("devices", [])
    }

    device_reg = dr.async_get(hass)
    entity_reg = er.async_get(hass)

    for device in dr.async_entries_for_config_entry(device_reg, entry.entry_id):
        # Skip the global "Tariff Controller" device
        if any(
            ident[1].endswith("_global")
            for ident in device.identifiers
            if ident[0] == DOMAIN
        ):
            continue

        # Resolve device slug from its identifier: "{entry_id}_{slug}"
        device_slug = None
        for ident in device.identifiers:
            if ident[0] == DOMAIN:
                device_slug = ident[1].replace(f"{entry.entry_id}_", "", 1)
                break

        still_exists = any(
            _slugify(name) == device_slug
            for name in current_device_names
        )

        if not still_exists:
            _LOGGER.info("Removing device '%s' and all its entities", device.name)
            for entity in er.async_entries_for_device(
                entity_reg, device.id, include_disabled_entities=True
            ):
                entity_reg.async_remove(entity.entity_id)
            device_reg.async_remove_device(device.id)

    await hass.config_entries.async_reload(entry.entry_id)


def _slugify(name: str) -> str:
    return name.lower().replace(" ", "_").replace("-", "_")
