"""Binary sensor platform - cycle alert."""
from __future__ import annotations

import logging
from homeassistant.components.binary_sensor import (
    BinarySensorEntity,
    BinarySensorDeviceClass,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.restore_state import RestoreEntity
from homeassistant.helpers import device_registry as dr
from homeassistant.const import STATE_UNAVAILABLE, STATE_UNKNOWN

from .const import (
    DOMAIN,
    CONF_CYCLE_TYPE,
    CONF_CYCLE_ALERT_ENABLED,
    CYCLE_TYPE_AUTO,
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
        alert_enabled = device.get(CONF_CYCLE_ALERT_ENABLED, False)
        if cycle_type == CYCLE_TYPE_AUTO and alert_enabled:
            sensor = CycleAlertBinarySensor(hass, entry, device_name)
            entities.append(sensor)
            refs = device_refs.setdefault(device_name, {})
            refs["alert_sensor"] = sensor

    if entities:
        async_add_entities(entities, True)


class CycleAlertBinarySensor(BinarySensorEntity, RestoreEntity):
    """Binary sensor ON when cycle is finished (alert active)."""

    _attr_device_class = BinarySensorDeviceClass.PROBLEM
    _attr_icon = "mdi:alert-circle"
    _attr_has_entity_name = True

    def __init__(self, hass: HomeAssistant, entry: ConfigEntry, device_name: str) -> None:
        self._entry = entry
        self._device_name = device_name
        self._is_on: bool = False
        slug = _slugify(device_name)
        self._attr_unique_id = f"{entry.entry_id}_{slug}_cycle_alert"
        self._attr_name = "Alerte cycle"

    @property
    def device_info(self) -> dr.DeviceInfo:
        slug = _slugify(self._device_name)
        return dr.DeviceInfo(identifiers={(DOMAIN, f"{self._entry.entry_id}_{slug}")})

    @property
    def is_on(self) -> bool:
        return self._is_on

    def set_alert(self, on: bool) -> None:
        self._is_on = on
        self.async_write_ha_state()

    async def async_added_to_hass(self) -> None:
        await super().async_added_to_hass()
        last_state = await self.async_get_last_state()
        if last_state and last_state.state not in (STATE_UNAVAILABLE, STATE_UNKNOWN):
            self._is_on = last_state.state == "on"


def _slugify(name: str) -> str:
    return name.lower().replace(" ", "_").replace("-", "_")
