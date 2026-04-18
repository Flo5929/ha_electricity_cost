"""Global tariff select entity for Electricity Cost."""
from __future__ import annotations

import logging
from homeassistant.components.select import SelectEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.restore_state import RestoreEntity
from homeassistant.helpers import device_registry as dr

from .const import DOMAIN, CONF_TARIFFS, TARIFF_SELECT_UNIQUE_ID, TARIFF_SELECT_NAME

_LOGGER = logging.getLogger(__name__)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    tariffs: list[str] = entry.data[CONF_TARIFFS]
    async_add_entities([ElectricityTariffSelect(hass, entry, tariffs)], True)


class ElectricityTariffSelect(SelectEntity, RestoreEntity):
    """
    Global tariff selector.
    Its state is read directly by EnergyMeterSensor instances to decide
    whether to accumulate — no active notification needed.
    """

    _attr_has_entity_name = True
    _attr_icon = "mdi:lightning-bolt"

    def __init__(
        self,
        hass: HomeAssistant,
        entry: ConfigEntry,
        tariffs: list[str],
    ) -> None:
        self._hass = hass
        self._entry = entry
        self._tariffs = tariffs
        self._current_tariff: str = tariffs[0]

        self._attr_unique_id = f"{entry.entry_id}_{TARIFF_SELECT_UNIQUE_ID}"
        self._attr_name = TARIFF_SELECT_NAME
        self._attr_options = tariffs

    @property
    def device_info(self) -> dr.DeviceInfo:
        return dr.DeviceInfo(
            identifiers={(DOMAIN, f"{self._entry.entry_id}_global")},
            name="Electricity Cost",
            manufacturer="Electricity Cost",
            model="Tariff Controller",
        )

    @property
    def current_option(self) -> str:
        return self._current_tariff

    async def async_select_option(self, option: str) -> None:
        if option not in self._tariffs:
            _LOGGER.error("Unknown tariff: %s", option)
            return
        self._current_tariff = option
        self.async_write_ha_state()
        # EnergyMeterSensor instances read this entity state directly
        # via hass.states.get() on each source change -> no notification needed

    async def async_added_to_hass(self) -> None:
        await super().async_added_to_hass()
        last_state = await self.async_get_last_state()
        if last_state and last_state.state in self._tariffs:
            self._current_tariff = last_state.state


def _slugify(name: str) -> str:
    return name.lower().replace(" ", "_").replace("-", "_")
