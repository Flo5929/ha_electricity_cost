"""
Sensor platform - integrated utility meters + cost sensors.

For each configured device, we create:
    - N EnergyMeterSensor: kWh counter per tariff (replaces external utility_meter)
    - N ElectricityCostSensor: cost EUR = kWh x price_input_number

EnergyMeterSensor instances:
    - Accumulate consumption only when the active tariff matches
    - Support manual reset
    - Persist their value via RestoreEntity

The active tariff selection is read from the integration global select,
resolved via the entity registry from its unique_id.
"""
from __future__ import annotations

import logging

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, callback, Event
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.components.sensor import (
    SensorEntity,
    SensorDeviceClass,
    SensorStateClass,
)
from homeassistant.helpers.event import async_track_state_change_event
from homeassistant.helpers.restore_state import RestoreEntity
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers import entity_registry as er
from homeassistant.helpers.entity_platform import async_get_current_platform
from homeassistant.const import STATE_UNAVAILABLE, STATE_UNKNOWN

from .const import (
    DOMAIN,
    CONF_TARIFFS,
    CONF_PRICE_ENTITIES,
    CONF_RESET_ENTITY,
    TARIFF_SELECT_UNIQUE_ID,
)

_LOGGER = logging.getLogger(__name__)


def _get_select_entity_id(hass: HomeAssistant, entry: ConfigEntry) -> str | None:
    """
    Resolve the global select entity_id via the entity registry.
    Much more reliable than guessing the entity_id from the name.
    """
    entity_registry = er.async_get(hass)
    unique_id = f"{entry.entry_id}_{TARIFF_SELECT_UNIQUE_ID}"
    entity = entity_registry.async_get_entity_id("select", DOMAIN, unique_id)
    return entity


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    tariffs: list[str] = entry.data[CONF_TARIFFS]
    price_entities: dict[str, str] = entry.data[CONF_PRICE_ENTITIES]
    devices: list[dict] = entry.options.get("devices", [])

    entities = _build_entities(hass, entry, tariffs, price_entities, devices)
    if entities:
        async_add_entities(entities, True)

    platform = async_get_current_platform()
    platform.async_register_entity_service("reset", {}, "reset")

    entry.async_on_unload(
        entry.add_update_listener(
            lambda h, e: _on_options_update(h, e, async_add_entities, tariffs, price_entities)
        )
    )


def _register_device(
    hass: HomeAssistant,
    entry: ConfigEntry,
    device: dict,
) -> str:
    device_registry = dr.async_get(hass)
    slug = _slugify(device["name"])
    device_unique = f"{entry.entry_id}_{slug}"

    device_entry = device_registry.async_get_or_create(
        config_entry_id=entry.entry_id,
        identifiers={(DOMAIN, device_unique)},
        name=device["name"],
        manufacturer="Electricity Cost",
        model="Energy Monitor",
    )
    return device_entry.id


def _build_entities(
    hass: HomeAssistant,
    entry: ConfigEntry,
    tariffs: list[str],
    price_entities: dict[str, str],
    devices: list[dict],
) -> list[SensorEntity]:
    entities: list[SensorEntity] = []

    for device in devices:
        device_id = _register_device(hass, entry, device)
        reset_entity_id: str | None = device.get(CONF_RESET_ENTITY)

        meters: list[EnergyMeterSensor] = []
        for tariff in tariffs:
            meter = EnergyMeterSensor(
                hass=hass,
                entry=entry,
                device_name=device["name"],
                device_id=device_id,
                tariff=tariff,
                source_entity_id=device["source"],
                all_tariffs=tariffs,
                reset_entity_id=reset_entity_id,
            )
            meters.append(meter)
            entities.append(meter)

        for tariff in tariffs:
            meter_for_tariff = next(m for m in meters if m.tariff == tariff)
            entities.append(
                ElectricityCostSensor(
                    hass=hass,
                    entry=entry,
                    device_name=device["name"],
                    device_id=device_id,
                    tariff=tariff,
                    price_entity_id=price_entities[tariff],
                    meter_sensor=meter_for_tariff,
                )
            )

    return entities


async def _on_options_update(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
    tariffs: list[str],
    price_entities: dict[str, str],
) -> None:
    devices = entry.options.get("devices", [])
    new_entities = _build_entities(hass, entry, tariffs, price_entities, devices)
    if new_entities:
        async_add_entities(new_entities, True)


# ---------------------------------------------------------------------------
# EnergyMeterSensor - kWh counter per tariff (replaces external utility_meter)
# ---------------------------------------------------------------------------

class EnergyMeterSensor(SensorEntity, RestoreEntity):
    """
    kWh counter for one device on one tariff.
    Only accumulates when the global tariff select matches this tariff.
    Supports manual reset and optional auto-reset on a rising edge (OFF→ON).
    """

    _attr_device_class = SensorDeviceClass.ENERGY
    _attr_state_class = SensorStateClass.TOTAL_INCREASING
    _attr_native_unit_of_measurement = "kWh"
    _attr_icon = "mdi:counter"
    _attr_has_entity_name = True

    def __init__(
        self,
        hass: HomeAssistant,
        entry: ConfigEntry,
        device_name: str,
        device_id: str,
        tariff: str,
        source_entity_id: str,
        all_tariffs: list[str],
        reset_entity_id: str | None,
    ) -> None:
        self._hass = hass
        self._entry = entry
        self._device_name = device_name
        self._device_id = device_id
        self._tariff = tariff
        self._source_entity_id = source_entity_id
        self._all_tariffs = all_tariffs
        self._reset_entity_id = reset_entity_id

        self._accumulated: float = 0.0
        self._last_source_value: float | None = None
        self._select_entity_id: str | None = None  # resolved at runtime
        self._on_value_updated: list[callback] = []  # push callbacks to ElectricityCostSensor

        slug = _slugify(device_name)
        tariff_slug = _slugify(tariff)
        self._attr_unique_id = f"{entry.entry_id}_{slug}_{tariff_slug}_meter"
        self._attr_name = f"Énergie {tariff}"

    @property
    def tariff(self) -> str:
        return self._tariff

    @property
    def device_info(self) -> dr.DeviceInfo:
        slug = _slugify(self._device_name)
        return dr.DeviceInfo(
            identifiers={(DOMAIN, f"{self._entry.entry_id}_{slug}")},
        )

    @property
    def native_value(self) -> float:
        return round(self._accumulated, 4)

    @property
    def extra_state_attributes(self) -> dict:
        return {
            "tariff": self._tariff,
            "source_entity": self._source_entity_id,
            "last_source_value": self._last_source_value,
            "active_tariff_entity": self._select_entity_id,
        }

    def _resolve_select_entity_id(self) -> str | None:
        """Resolve the global select entity_id via the entity registry."""
        if self._select_entity_id:
            return self._select_entity_id
        entity_id = _get_select_entity_id(self.hass, self._entry)
        if entity_id:
            self._select_entity_id = entity_id
        return entity_id

    def _get_active_tariff(self) -> str | None:
        select_entity_id = self._resolve_select_entity_id()
        if not select_entity_id:
            return None
        state = self.hass.states.get(select_entity_id)
        if state and state.state not in (STATE_UNAVAILABLE, STATE_UNKNOWN):
            return state.state
        return None

    def _is_my_tariff_active(self) -> bool:
        return self._get_active_tariff() == self._tariff

    def _get_source_value(self) -> float | None:
        state = self.hass.states.get(self._source_entity_id)
        if state and state.state not in (STATE_UNAVAILABLE, STATE_UNKNOWN):
            try:
                return float(state.state)
            except ValueError:
                pass
        return None

    def register_update_listener(self, cb: callback) -> None:
        """Register a callback called immediately after each value update."""
        self._on_value_updated.append(cb)

    def _notify_listeners(self) -> None:
        for cb in self._on_value_updated:
            cb()

    @callback
    def reset(self) -> None:
        """Reset the counter to zero and reinitialize the source value."""
        _LOGGER.info("Reset du compteur %s — %s", self._device_name, self._tariff)
        self._accumulated = 0.0
        self._last_source_value = self._get_source_value()
        self.async_write_ha_state()
        self._notify_listeners()

    @callback
    def _handle_source_change(self, event: Event) -> None:
        """Accumulate consumption only when this tariff is active."""
        new_state = event.data.get("new_state")
        if new_state is None or new_state.state in (STATE_UNAVAILABLE, STATE_UNKNOWN):
            return

        try:
            new_value = float(new_state.state)
        except ValueError:
            return

        if self._last_source_value is None:
            # First reading: just anchor the baseline, never accumulate.
            self._last_source_value = new_value
            return

        delta = new_value - self._last_source_value
        # Always advance the baseline so inactive periods are never accumulated
        # when this tariff becomes active again.
        self._last_source_value = new_value

        if not self._is_my_tariff_active():
            return

        if delta > 0:
            self._accumulated += delta
            self.async_write_ha_state()
            self._notify_listeners()  # instant cost update
        elif delta < -0.001:
            _LOGGER.debug(
                "Reset détecté sur la source %s (delta=%.4f)",
                self._source_entity_id, delta,
            )

    @callback
    def _handle_reset_entity_change(self, event: Event) -> None:
        """Reset on OFF->ON rising edge."""
        old_state = event.data.get("old_state")
        new_state = event.data.get("new_state")
        if old_state is None or new_state is None:
            return
        was_off = old_state.state.lower() not in ("on", "true", "1")
        is_now_on = new_state.state.lower() in ("on", "true", "1")
        if was_off and is_now_on:
            self.reset()

    async def async_added_to_hass(self) -> None:
        await super().async_added_to_hass()

        last_state = await self.async_get_last_state()
        if last_state and last_state.state not in (STATE_UNAVAILABLE, STATE_UNKNOWN):
            try:
                self._accumulated = float(last_state.state)
            except ValueError:
                pass
            if last_state.attributes.get("last_source_value") is not None:
                try:
                    self._last_source_value = float(last_state.attributes["last_source_value"])
                except (ValueError, TypeError):
                    pass

        self.async_on_remove(
            async_track_state_change_event(
                self.hass,
                [self._source_entity_id],
                self._handle_source_change,
            )
        )

        if self._reset_entity_id:
            self.async_on_remove(
                async_track_state_change_event(
                    self.hass,
                    [self._reset_entity_id],
                    self._handle_reset_entity_change,
                )
            )

        if self._last_source_value is None:
            self._last_source_value = self._get_source_value()


# ---------------------------------------------------------------------------
# ElectricityCostSensor - EUR cost per tariff
# ---------------------------------------------------------------------------

class ElectricityCostSensor(SensorEntity, RestoreEntity):
    """
    Cost sensor for one device + one tariff.
    Formula: cost (EUR) = meter.accumulated_kwh x price_input_number.
    Reactive to both sources.
    """

    _attr_device_class = SensorDeviceClass.MONETARY
    _attr_state_class = SensorStateClass.TOTAL
    _attr_native_unit_of_measurement = "EUR"
    _attr_icon = "mdi:currency-eur"
    _attr_has_entity_name = True

    def __init__(
        self,
        hass: HomeAssistant,
        entry: ConfigEntry,
        device_name: str,
        device_id: str,
        tariff: str,
        price_entity_id: str,
        meter_sensor: EnergyMeterSensor,
    ) -> None:
        self._hass = hass
        self._entry = entry
        self._device_name = device_name
        self._device_id = device_id
        self._tariff = tariff
        self._price_entity_id = price_entity_id
        self._meter_sensor = meter_sensor
        self._cost: float | None = None

        slug = _slugify(device_name)
        tariff_slug = _slugify(tariff)
        self._attr_unique_id = f"{entry.entry_id}_{slug}_{tariff_slug}_cost"
        self._attr_name = f"Coût {tariff}"

    @property
    def device_info(self) -> dr.DeviceInfo:
        slug = _slugify(self._device_name)
        return dr.DeviceInfo(
            identifiers={(DOMAIN, f"{self._entry.entry_id}_{slug}")},
        )

    def _get_price(self) -> float | None:
        state = self.hass.states.get(self._price_entity_id)
        if state and state.state not in (STATE_UNAVAILABLE, STATE_UNKNOWN):
            try:
                return float(state.state)
            except ValueError:
                pass
        return None

    def _recompute(self) -> None:
        price = self._get_price()
        kwh = self._meter_sensor.native_value
        if price is not None and kwh is not None:
            self._cost = round(kwh * price, 4)

    @property
    def native_value(self) -> float | None:
        return self._cost

    @property
    def extra_state_attributes(self) -> dict:
        return {
            "tariff": self._tariff,
            "price_entity": self._price_entity_id,
            "current_price_eur_kwh": self._get_price(),
            "current_kwh": self._meter_sensor.native_value,
        }

    @callback
    def reset(self) -> None:
        """No-op: cost sensors cannot be reset directly."""

    @callback
    def _handle_price_change(self, event: Event) -> None:
        self._recompute()
        self.async_write_ha_state()

    @callback
    def _on_meter_updated(self) -> None:
        """Called directly by the meter as soon as it accumulates - zero delay."""
        self._recompute()
        self.async_write_ha_state()

    async def async_added_to_hass(self) -> None:
        await super().async_added_to_hass()

        last_state = await self.async_get_last_state()
        if last_state and last_state.state not in (STATE_UNAVAILABLE, STATE_UNKNOWN):
            try:
                self._cost = float(last_state.state)
            except ValueError:
                pass

        # Instant update via meter push callback
        self._meter_sensor.register_update_listener(self._on_meter_updated)

        # Update when the price changes
        self.async_on_remove(
            async_track_state_change_event(
                self.hass,
                [self._price_entity_id],
                self._handle_price_change,
            )
        )

        # Initial calculation
        self._recompute()


def _slugify(name: str) -> str:
    return name.lower().replace(" ", "_").replace("-", "_")
