"""Button platform - cycle acknowledge."""
from __future__ import annotations

import logging
from homeassistant.components.button import ButtonEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers import device_registry as dr

from .const import (
    DOMAIN,
    CONF_CYCLE_TYPE,
    CYCLE_TYPE_AUTO,
    CYCLE_STATE_IDLE,
    CYCLE_STATE_FINISHED,
)

_LOGGER = logging.getLogger(__name__)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    devices: list[dict] = entry.options.get("devices", [])
    device_refs = hass.data[DOMAIN][entry.entry_id].setdefault("device_refs", {})
    entities = []

    for device in devices:
        device_name = device["name"]
        cycle_type = device.get(CONF_CYCLE_TYPE, "none")
        if cycle_type == CYCLE_TYPE_AUTO:
            button = CycleAcknowledgeButton(hass, entry, device_name)
            entities.append(button)
            refs = device_refs.setdefault(device_name, {})
            refs["ack_button"] = button

    if entities:
        async_add_entities(entities, True)


class CycleAcknowledgeButton(ButtonEntity):
    """Button to acknowledge a finished cycle, moving it back to idle."""

    _attr_icon = "mdi:check-circle-outline"
    _attr_has_entity_name = True

    def __init__(self, hass: HomeAssistant, entry: ConfigEntry, device_name: str) -> None:
        self._hass = hass
        self._entry = entry
        self._device_name = device_name
        slug = _slugify(device_name)
        self._attr_unique_id = f"{entry.entry_id}_{slug}_cycle_acknowledge"
        self._attr_name = "Acquitter le cycle"
        self._cycle_manager = None  # Set by CycleManager after init

    @property
    def device_info(self) -> dr.DeviceInfo:
        slug = _slugify(self._device_name)
        return dr.DeviceInfo(identifiers={(DOMAIN, f"{self._entry.entry_id}_{slug}")})

    def set_cycle_manager(self, manager) -> None:
        self._cycle_manager = manager

    async def async_press(self) -> None:
        if self._cycle_manager:
            self._cycle_manager.acknowledge()
        else:
            _LOGGER.warning("No cycle manager attached to acknowledge button for %s", self._device_name)


def _slugify(name: str) -> str:
    return name.lower().replace(" ", "_").replace("-", "_")
