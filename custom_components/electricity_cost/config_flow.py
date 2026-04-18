"""Config flow for Electricity Cost integration."""
from __future__ import annotations

import json
import logging
from functools import lru_cache
from pathlib import Path
import voluptuous as vol
from typing import Any

from homeassistant import config_entries
from homeassistant.core import callback
from homeassistant.helpers import selector

from .const import (
    DOMAIN,
    CONF_TARIFFS,
    CONF_PRICE_ENTITIES,
    CONF_DEVICE_NAME,
    CONF_SOURCE_SENSOR,
    CONF_RESET_ENTITY,
)

_LOGGER = logging.getLogger(__name__)


@lru_cache(maxsize=8)
def _load_tariff_examples_from_translation(language: str) -> tuple[str, str] | None:
    """Load tariff examples from translations/<language>.json."""
    path = Path(__file__).parent / "translations" / f"{language}.json"
    if not path.is_file():
        return None

    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None

    user_step = data.get("config", {}).get("step", {}).get("user", {})
    suggested_value = user_step.get("suggested_value")
    description_example = user_step.get("example")

    if isinstance(suggested_value, str) and isinstance(description_example, str):
        return suggested_value, description_example
    return None


def _tariff_examples_for_language(language: str | None) -> tuple[str, str]:
    """Return (suggested_value, description_example) using localization files."""
    lang = (language or "en").split("-")[0].lower()
    localized = _load_tariff_examples_from_translation(lang)
    if localized:
        return localized

    fallback = _load_tariff_examples_from_translation("en")
    if fallback:
        return fallback

    return "Off-Peak, Peak", "Off-Peak, Peak, Weekend"


class ElectricityCostConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    """
    Step 1: tariff names (e.g. Off-Peak, Peak)
    Step 2: one input_number entity per tariff for pricing

    Only one config entry is allowed.
    """

    VERSION = 1

    def __init__(self) -> None:
        self._tariffs: list[str] = []

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> config_entries.FlowResult:
        await self.async_set_unique_id(DOMAIN)
        self._abort_if_unique_id_configured(updates={})

        suggested_value, description_example = _tariff_examples_for_language(
            self.hass.config.language
        )

        errors: dict[str, str] = {}

        if user_input is not None:
            raw = user_input.get("tariffs_raw", "")
            tariffs = [t.strip() for t in raw.split(",") if t.strip()]

            if len(tariffs) < 1:
                errors["tariffs_raw"] = "at_least_one_tariff"
            elif len(tariffs) != len(set(tariffs)):
                errors["tariffs_raw"] = "duplicate_tariffs"
            else:
                self._tariffs = tariffs
                return await self.async_step_price_entities()

        return self.async_show_form(
            step_id="user",
            data_schema=vol.Schema(
                {
                    vol.Required(
                        "tariffs_raw",
                        description={"suggested_value": suggested_value},
                    ): str,
                }
            ),
            description_placeholders={"example": description_example},
            errors=errors,
        )

    async def async_step_price_entities(
        self, user_input: dict[str, Any] | None = None
    ) -> config_entries.FlowResult:
        errors: dict[str, str] = {}

        if user_input is not None:
            price_entities: dict[str, str] = {}
            valid = True

            for tariff in self._tariffs:
                key = f"price_entity_{_safe_key(tariff)}"
                entity_id = user_input.get(key, "").strip()
                if not entity_id:
                    errors[key] = "required_entity"
                    valid = False
                else:
                    price_entities[tariff] = entity_id

            if valid:
                return self.async_create_entry(
                    title="Electricity Cost",
                    data={
                        CONF_TARIFFS: self._tariffs,
                        CONF_PRICE_ENTITIES: price_entities,
                    },
                )

        # Dynamic label per tariff via vol description["name"]
        schema_dict: dict = {}
        for tariff in self._tariffs:
            key = f"price_entity_{_safe_key(tariff)}"
            schema_dict[
                vol.Required(key, description={"name": f"Price entity — {tariff}"})
            ] = selector.EntitySelector(
                selector.EntitySelectorConfig(domain="input_number")
            )

        return self.async_show_form(
            step_id="price_entities",
            data_schema=vol.Schema(schema_dict),
            description_placeholders={"tariffs": ", ".join(self._tariffs)},
            errors=errors,
        )

    @staticmethod
    @callback
    def async_get_options_flow(
        config_entry: config_entries.ConfigEntry,
    ) -> ElectricityCostOptionsFlow:
        return ElectricityCostOptionsFlow(config_entry)


class ElectricityCostOptionsFlow(config_entries.OptionsFlow):
    """
    Options flow — accessible via the ⚙ button on the config entry.
    Menu: Add a device | Remove a device.
    """

    def __init__(self, config_entry: config_entries.ConfigEntry) -> None:
        self._config_entry = config_entry

    # ------------------------------------------------------------------
    # Main menu
    # ------------------------------------------------------------------
    async def async_step_init(
        self, user_input: dict[str, Any] | None = None
    ) -> config_entries.FlowResult:
        devices: list[dict] = self._config_entry.options.get("devices", [])

        if user_input is not None:
            action = user_input.get("action")
            if action == "add":
                return await self.async_step_add_device()
            if action == "remove":
                return await self.async_step_remove_device()

        # Skip menu if no devices yet
        if not devices:
            return await self.async_step_add_device()

        return self.async_show_form(
            step_id="init",
            data_schema=vol.Schema(
                {
                    vol.Required("action"): selector.SelectSelector(
                        selector.SelectSelectorConfig(
                            options=[
                                {"value": "add", "label": "Add a device"},
                                {"value": "remove", "label": "Remove a device"},
                            ],
                            mode=selector.SelectSelectorMode.LIST,
                        )
                    )
                }
            ),
        )

    # ------------------------------------------------------------------
    # Add a device
    # ------------------------------------------------------------------
    async def async_step_add_device(
        self, user_input: dict[str, Any] | None = None
    ) -> config_entries.FlowResult:
        errors: dict[str, str] = {}

        if user_input is not None:
            device_name = user_input[CONF_DEVICE_NAME].strip()
            source_sensor = user_input[CONF_SOURCE_SENSOR]
            reset_entity = user_input.get(CONF_RESET_ENTITY) or None

            if not device_name:
                errors[CONF_DEVICE_NAME] = "empty_device_name"
            else:
                existing = dict(self._config_entry.options)
                devices: list[dict] = list(existing.get("devices", []))

                if any(d["name"] == device_name for d in devices):
                    errors[CONF_DEVICE_NAME] = "duplicate_device_name"
                else:
                    device_entry: dict = {"name": device_name, "source": source_sensor}
                    if reset_entity:
                        device_entry[CONF_RESET_ENTITY] = reset_entity
                    devices.append(device_entry)
                    existing["devices"] = devices
                    return self.async_create_entry(title="", data=existing)

        tariffs = self._config_entry.data[CONF_TARIFFS]

        return self.async_show_form(
            step_id="add_device",
            data_schema=vol.Schema(
                {
                    vol.Required(CONF_DEVICE_NAME): str,
                    vol.Required(CONF_SOURCE_SENSOR): selector.EntitySelector(
                        selector.EntitySelectorConfig(
                            domain="sensor",
                            device_class="energy",
                        )
                    ),
                    vol.Optional(CONF_RESET_ENTITY): selector.EntitySelector(
                        selector.EntitySelectorConfig(
                            domain=["switch", "input_boolean", "binary_sensor"],
                            multiple=False,
                        )
                    ),
                }
            ),
            description_placeholders={"tariffs": ", ".join(tariffs)},
            errors=errors,
        )

    # ------------------------------------------------------------------
    # Remove a device
    # ------------------------------------------------------------------
    async def async_step_remove_device(
        self, user_input: dict[str, Any] | None = None
    ) -> config_entries.FlowResult:
        errors: dict[str, str] = {}
        devices: list[dict] = self._config_entry.options.get("devices", [])

        if user_input is not None:
            name_to_remove = user_input.get("device_to_remove")
            existing = dict(self._config_entry.options)
            existing["devices"] = [d for d in devices if d["name"] != name_to_remove]
            return self.async_create_entry(title="", data=existing)

        device_options = [
            {"value": d["name"], "label": d["name"]}
            for d in devices
        ]

        return self.async_show_form(
            step_id="remove_device",
            data_schema=vol.Schema(
                {
                    vol.Required("device_to_remove"): selector.SelectSelector(
                        selector.SelectSelectorConfig(
                            options=device_options,
                            mode=selector.SelectSelectorMode.LIST,
                        )
                    )
                }
            ),
            errors=errors,
        )


def _safe_key(name: str) -> str:
    return name.lower().replace(" ", "_").replace("-", "_")
