"""Electricity Cost integration."""
from __future__ import annotations

import logging
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers import entity_registry as er, device_registry as dr

from .const import (
    DOMAIN,
    PLATFORMS,
    CONF_CYCLE_TYPE,
    CYCLE_TYPE_MANUAL,
    CYCLE_TYPE_AUTO,
)
from .cycle_manager import CycleManager

_LOGGER = logging.getLogger(__name__)


async def async_setup(hass: HomeAssistant, config: dict) -> bool:
    hass.data.setdefault(DOMAIN, {})
    return True


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    hass.data.setdefault(DOMAIN, {})
    hass.data[DOMAIN][entry.entry_id] = {
        "data": dict(entry.data),
        "cycle_managers": [],
        "device_refs": {},  # device_name -> runtime sensor/entity refs
    }

    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)

    # Initialize cycle managers after platforms are set up
    devices: list[dict] = entry.options.get("devices", [])
    device_refs = hass.data[DOMAIN][entry.entry_id]["device_refs"]
    managers = []
    for device in devices:
        device_name = device["name"]
        cycle_type = device.get(CONF_CYCLE_TYPE, "none")
        refs = device_refs.get(device_name, {})

        if cycle_type in (CYCLE_TYPE_MANUAL, CYCLE_TYPE_AUTO):
            try:
                manager = CycleManager(hass, entry, device)

                # Connect meters for manual cycles (needed for reset)
                if cycle_type == CYCLE_TYPE_MANUAL:
                    meters = refs.get("meters", [])
                    if meters:
                        manager.set_meters(meters)

                # Connect sensors for auto cycles
                if cycle_type == CYCLE_TYPE_AUTO:
                    cycle_sensors = refs.get("cycle_sensors")
                    if cycle_sensors:
                        manager.set_sensors(
                            state_sensor=cycle_sensors["state"],
                            duration_sensor=cycle_sensors["duration"],
                            cost_sensor=cycle_sensors["cost"],
                            start_sensor=cycle_sensors["start"],
                            end_sensor=cycle_sensors["end"],
                            meters=cycle_sensors["meters"],
                            cost_sensors=cycle_sensors["cost_sensors"],
                        )
                    alert_sensor = refs.get("alert_sensor")
                    if alert_sensor:
                        manager.set_alert_sensor(alert_sensor)
                    ack_button = refs.get("ack_button")
                    if ack_button:
                        manager.set_ack_button(ack_button)

                await manager.async_start()
                managers.append(manager)
            except Exception:
                _LOGGER.exception(
                    "Failed to initialize cycle manager for %s", device_name,
                )

    hass.data[DOMAIN][entry.entry_id]["cycle_managers"] = managers

    entry.async_on_unload(entry.add_update_listener(async_update_listener))
    return True


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    # Stop cycle managers
    entry_data = hass.data[DOMAIN].get(entry.entry_id, {})
    for manager in entry_data.get("cycle_managers", []):
        await manager.async_stop()

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
