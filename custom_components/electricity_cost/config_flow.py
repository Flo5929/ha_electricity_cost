"""Config flow for Electricity Cost integration."""
from __future__ import annotations

import json
import logging
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
    CONF_CYCLE_TYPE,
    CONF_CYCLE_MANUAL_TRIGGER,
    CONF_CYCLE_POWER_SENSOR,
    CONF_CYCLE_START_THRESHOLD,
    CONF_CYCLE_START_DURATION,
    CONF_CYCLE_END_THRESHOLD,
    CONF_CYCLE_END_DURATION,
    CONF_CYCLE_NOTIFIERS,
    CONF_CYCLE_NOTIFICATION_TITLE,
    CONF_CYCLE_NOTIFICATION_MESSAGE,
    CONF_CYCLE_ALERT_ENABLED,
    CONF_CYCLE_ALERT_ENTITY,
    CYCLE_TYPE_NONE,
    CYCLE_TYPE_MANUAL,
    CYCLE_TYPE_AUTO,
)

_LOGGER = logging.getLogger(__name__)


_translation_cache: dict[str, tuple[str, str] | None] = {}


def _load_tariff_examples_sync(language: str) -> tuple[str, str] | None:
    """Load tariff examples from translations/<language>.json (sync, for executor)."""
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


async def _tariff_examples_for_language(
    hass, language: str | None,
) -> tuple[str, str]:
    """Return (suggested_value, description_example) using localization files."""
    lang = (language or "en").split("-")[0].lower()

    if lang not in _translation_cache:
        _translation_cache[lang] = await hass.async_add_executor_job(
            _load_tariff_examples_sync, lang,
        )
    if _translation_cache[lang]:
        return _translation_cache[lang]

    if "en" not in _translation_cache:
        _translation_cache["en"] = await hass.async_add_executor_job(
            _load_tariff_examples_sync, "en",
        )
    fallback = _translation_cache.get("en")
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

        suggested_value, description_example = await _tariff_examples_for_language(
            self.hass, self.hass.config.language,
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
        self._pending_device: dict | None = None
        self._editing_device_name: str | None = None

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
            if action == "edit":
                return await self.async_step_edit_device()
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
                                {"value": "edit", "label": "Edit a device"},
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
            cycle_type = user_input.get(CONF_CYCLE_TYPE, CYCLE_TYPE_NONE)

            if not device_name:
                errors[CONF_DEVICE_NAME] = "empty_device_name"
            else:
                existing = dict(self._config_entry.options)
                devices: list[dict] = list(existing.get("devices", []))

                if any(d["name"] == device_name for d in devices):
                    errors[CONF_DEVICE_NAME] = "duplicate_device_name"
                else:
                    device_entry: dict = {"name": device_name, "source": source_sensor}
                    device_entry[CONF_CYCLE_TYPE] = cycle_type

                    if cycle_type == CYCLE_TYPE_MANUAL:
                        self._pending_device = device_entry
                        return await self.async_step_cycle_manual()
                    elif cycle_type == CYCLE_TYPE_AUTO:
                        self._pending_device = device_entry
                        return await self.async_step_cycle_auto()
                    else:
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
                    vol.Optional(
                        CONF_CYCLE_TYPE, default=CYCLE_TYPE_NONE
                    ): selector.SelectSelector(
                        selector.SelectSelectorConfig(
                            options=[
                                {"value": CYCLE_TYPE_NONE, "label": "None"},
                                {"value": CYCLE_TYPE_MANUAL, "label": "Manual"},
                                {"value": CYCLE_TYPE_AUTO, "label": "Automatic"},
                            ],
                            mode=selector.SelectSelectorMode.DROPDOWN,
                        )
                    ),
                }
            ),
            description_placeholders={"tariffs": ", ".join(tariffs)},
            errors=errors,
        )

    # ------------------------------------------------------------------
    # Cycle manual
    # ------------------------------------------------------------------
    async def async_step_cycle_manual(
        self, user_input: dict[str, Any] | None = None
    ) -> config_entries.FlowResult:
        if user_input is not None:
            trigger = user_input.get(CONF_CYCLE_MANUAL_TRIGGER) or None
            if trigger:
                self._pending_device[CONF_CYCLE_MANUAL_TRIGGER] = trigger
            else:
                self._pending_device.pop(CONF_CYCLE_MANUAL_TRIGGER, None)

            return self._save_pending_device()

        existing_trigger = (
            self._pending_device.get(CONF_CYCLE_MANUAL_TRIGGER)
            if self._pending_device else None
        )
        schema_fields: dict = {}
        if existing_trigger:
            schema_fields[vol.Optional(
                CONF_CYCLE_MANUAL_TRIGGER, default=existing_trigger,
            )] = selector.EntitySelector(
                selector.EntitySelectorConfig(
                    domain=["switch", "input_boolean", "binary_sensor"],
                    multiple=False,
                )
            )
        else:
            schema_fields[vol.Optional(
                CONF_CYCLE_MANUAL_TRIGGER,
            )] = selector.EntitySelector(
                selector.EntitySelectorConfig(
                    domain=["switch", "input_boolean", "binary_sensor"],
                    multiple=False,
                )
            )

        return self.async_show_form(
            step_id="cycle_manual",
            data_schema=vol.Schema(schema_fields),
        )

    # ------------------------------------------------------------------
    # Cycle auto - thresholds
    # ------------------------------------------------------------------
    async def async_step_cycle_auto(
        self, user_input: dict[str, Any] | None = None
    ) -> config_entries.FlowResult:
        errors: dict[str, str] = {}

        if user_input is not None:
            self._pending_device[CONF_CYCLE_POWER_SENSOR] = user_input[CONF_CYCLE_POWER_SENSOR]
            self._pending_device[CONF_CYCLE_START_THRESHOLD] = user_input[CONF_CYCLE_START_THRESHOLD]
            self._pending_device[CONF_CYCLE_START_DURATION] = user_input[CONF_CYCLE_START_DURATION]
            self._pending_device[CONF_CYCLE_END_THRESHOLD] = user_input[CONF_CYCLE_END_THRESHOLD]
            self._pending_device[CONF_CYCLE_END_DURATION] = user_input[CONF_CYCLE_END_DURATION]
            return await self.async_step_cycle_notifications()

        return self.async_show_form(
            step_id="cycle_auto",
            data_schema=vol.Schema(
                {
                    vol.Required(CONF_CYCLE_POWER_SENSOR): selector.EntitySelector(
                        selector.EntitySelectorConfig(
                            domain="sensor",
                            device_class="power",
                        )
                    ),
                    vol.Required(
                        CONF_CYCLE_START_THRESHOLD, default=50
                    ): selector.NumberSelector(
                        selector.NumberSelectorConfig(
                            min=0, max=10000, step=1, unit_of_measurement="W",
                            mode=selector.NumberSelectorMode.BOX,
                        )
                    ),
                    vol.Required(
                        CONF_CYCLE_START_DURATION, default=60
                    ): selector.NumberSelector(
                        selector.NumberSelectorConfig(
                            min=1, max=3600, step=1, unit_of_measurement="s",
                            mode=selector.NumberSelectorMode.BOX,
                        )
                    ),
                    vol.Required(
                        CONF_CYCLE_END_THRESHOLD, default=10
                    ): selector.NumberSelector(
                        selector.NumberSelectorConfig(
                            min=0, max=10000, step=1, unit_of_measurement="W",
                            mode=selector.NumberSelectorMode.BOX,
                        )
                    ),
                    vol.Required(
                        CONF_CYCLE_END_DURATION, default=60
                    ): selector.NumberSelector(
                        selector.NumberSelectorConfig(
                            min=1, max=3600, step=1, unit_of_measurement="s",
                            mode=selector.NumberSelectorMode.BOX,
                        )
                    ),
                }
            ),
            errors=errors,
        )

    # ------------------------------------------------------------------
    # Cycle auto - notifications (optional)
    # ------------------------------------------------------------------
    async def async_step_cycle_notifications(
        self, user_input: dict[str, Any] | None = None
    ) -> config_entries.FlowResult:
        if user_input is not None:
            notifiers = user_input.get(CONF_CYCLE_NOTIFIERS) or []
            if isinstance(notifiers, str):
                # backward compat: plain text input
                notifiers = [n.strip() for n in notifiers.split(",") if n.strip()]
            self._pending_device[CONF_CYCLE_NOTIFIERS] = notifiers
            title = user_input.get(CONF_CYCLE_NOTIFICATION_TITLE) or ""
            if title:
                self._pending_device[CONF_CYCLE_NOTIFICATION_TITLE] = title
            message = user_input.get(CONF_CYCLE_NOTIFICATION_MESSAGE) or ""
            if message:
                self._pending_device[CONF_CYCLE_NOTIFICATION_MESSAGE] = message
            alert = user_input.get(CONF_CYCLE_ALERT_ENABLED, False)
            self._pending_device[CONF_CYCLE_ALERT_ENABLED] = alert
            alert_entity = user_input.get(CONF_CYCLE_ALERT_ENTITY) or None
            if alert_entity:
                self._pending_device[CONF_CYCLE_ALERT_ENTITY] = alert_entity
            else:
                self._pending_device.pop(CONF_CYCLE_ALERT_ENTITY, None)

            return self._save_pending_device()

        # Build dynamic list of notify.* and script.* services
        notify_services = sorted(
            f"notify.{svc}"
            for svc in self.hass.services.async_services_for_domain("notify")
        )
        script_services = sorted(
            f"script.{svc}"
            for svc in self.hass.services.async_services_for_domain("script")
        )
        service_options = [
            {"value": s, "label": s}
            for s in notify_services + script_services
        ]

        # Pre-fill with existing values if editing
        existing_notifiers: list[str] = []
        existing_title = ""
        existing_message = ""
        existing_alert = False
        existing_alert_entity = None
        if self._pending_device:
            notif_list = self._pending_device.get(CONF_CYCLE_NOTIFIERS, [])
            if isinstance(notif_list, list):
                existing_notifiers = notif_list
            elif isinstance(notif_list, str):
                existing_notifiers = [n.strip() for n in notif_list.split(",") if n.strip()]
            existing_title = self._pending_device.get(CONF_CYCLE_NOTIFICATION_TITLE, "")
            existing_message = self._pending_device.get(CONF_CYCLE_NOTIFICATION_MESSAGE, "")
            existing_alert = self._pending_device.get(CONF_CYCLE_ALERT_ENABLED, False)
            existing_alert_entity = self._pending_device.get(CONF_CYCLE_ALERT_ENTITY)

        return self.async_show_form(
            step_id="cycle_notifications",
            data_schema=vol.Schema(
                {
                    vol.Optional(
                        CONF_CYCLE_NOTIFIERS, default=existing_notifiers,
                    ): selector.SelectSelector(
                        selector.SelectSelectorConfig(
                            options=service_options,
                            multiple=True,
                            custom_value=True,
                            mode=selector.SelectSelectorMode.DROPDOWN,
                        )
                    ),
                    vol.Optional(CONF_CYCLE_NOTIFICATION_TITLE, default=existing_title): str,
                    vol.Optional(CONF_CYCLE_NOTIFICATION_MESSAGE, default=existing_message): str,
                    vol.Optional(CONF_CYCLE_ALERT_ENABLED, default=existing_alert): bool,
                    vol.Optional(
                        CONF_CYCLE_ALERT_ENTITY,
                        **({
                            "default": existing_alert_entity,
                        } if existing_alert_entity else {}),
                    ): selector.EntitySelector(
                        selector.EntitySelectorConfig(
                            domain="alert",
                            multiple=False,
                        )
                    ),
                }
            ),
            description_placeholders={
                "templates": "{{ duration }}, {{ cost }}, {{ energy_total }}, {{ energy_<tariff> }}, {{ cost_<tariff> }} — retours à la ligne : \\n",
            },
        )

    def _save_pending_device(self) -> config_entries.FlowResult:
        """Save the pending device and return the entry."""
        existing = dict(self._config_entry.options)
        devices: list[dict] = list(existing.get("devices", []))
        # If editing, replace the existing device
        if self._editing_device_name:
            devices = [
                d for d in devices if d["name"] != self._editing_device_name
            ]
            self._editing_device_name = None
        devices.append(self._pending_device)
        existing["devices"] = devices
        self._pending_device = None
        return self.async_create_entry(title="", data=existing)

    # ------------------------------------------------------------------
    # Edit a device
    # ------------------------------------------------------------------
    async def async_step_edit_device(
        self, user_input: dict[str, Any] | None = None
    ) -> config_entries.FlowResult:
        devices: list[dict] = self._config_entry.options.get("devices", [])

        if user_input is not None:
            name = user_input.get("device_to_edit")
            device = next((d for d in devices if d["name"] == name), None)
            if device:
                self._pending_device = dict(device)
                self._editing_device_name = name
                cycle_type = device.get(CONF_CYCLE_TYPE, CYCLE_TYPE_NONE)
                if cycle_type == CYCLE_TYPE_MANUAL:
                    return await self.async_step_cycle_manual()
                elif cycle_type == CYCLE_TYPE_AUTO:
                    return await self.async_step_edit_auto_thresholds()
                else:
                    return self._save_pending_device()

        device_options = [
            {"value": d["name"], "label": d["name"]}
            for d in devices
        ]
        return self.async_show_form(
            step_id="edit_device",
            data_schema=vol.Schema(
                {
                    vol.Required("device_to_edit"): selector.SelectSelector(
                        selector.SelectSelectorConfig(
                            options=device_options,
                            mode=selector.SelectSelectorMode.LIST,
                        )
                    )
                }
            ),
        )

    async def async_step_edit_auto_thresholds(
        self, user_input: dict[str, Any] | None = None
    ) -> config_entries.FlowResult:
        if user_input is not None:
            self._pending_device[CONF_CYCLE_POWER_SENSOR] = user_input[CONF_CYCLE_POWER_SENSOR]
            self._pending_device[CONF_CYCLE_START_THRESHOLD] = user_input[CONF_CYCLE_START_THRESHOLD]
            self._pending_device[CONF_CYCLE_START_DURATION] = user_input[CONF_CYCLE_START_DURATION]
            self._pending_device[CONF_CYCLE_END_THRESHOLD] = user_input[CONF_CYCLE_END_THRESHOLD]
            self._pending_device[CONF_CYCLE_END_DURATION] = user_input[CONF_CYCLE_END_DURATION]
            return await self.async_step_cycle_notifications()

        dev = self._pending_device
        return self.async_show_form(
            step_id="edit_auto_thresholds",
            data_schema=vol.Schema(
                {
                    vol.Required(
                        CONF_CYCLE_POWER_SENSOR,
                        default=dev.get(CONF_CYCLE_POWER_SENSOR),
                    ): selector.EntitySelector(
                        selector.EntitySelectorConfig(
                            domain="sensor", device_class="power",
                        )
                    ),
                    vol.Required(
                        CONF_CYCLE_START_THRESHOLD,
                        default=dev.get(CONF_CYCLE_START_THRESHOLD, 50),
                    ): selector.NumberSelector(
                        selector.NumberSelectorConfig(
                            min=0, max=10000, step=1, unit_of_measurement="W",
                            mode=selector.NumberSelectorMode.BOX,
                        )
                    ),
                    vol.Required(
                        CONF_CYCLE_START_DURATION,
                        default=dev.get(CONF_CYCLE_START_DURATION, 60),
                    ): selector.NumberSelector(
                        selector.NumberSelectorConfig(
                            min=1, max=3600, step=1, unit_of_measurement="s",
                            mode=selector.NumberSelectorMode.BOX,
                        )
                    ),
                    vol.Required(
                        CONF_CYCLE_END_THRESHOLD,
                        default=dev.get(CONF_CYCLE_END_THRESHOLD, 10),
                    ): selector.NumberSelector(
                        selector.NumberSelectorConfig(
                            min=0, max=10000, step=1, unit_of_measurement="W",
                            mode=selector.NumberSelectorMode.BOX,
                        )
                    ),
                    vol.Required(
                        CONF_CYCLE_END_DURATION,
                        default=dev.get(CONF_CYCLE_END_DURATION, 60),
                    ): selector.NumberSelector(
                        selector.NumberSelectorConfig(
                            min=1, max=3600, step=1, unit_of_measurement="s",
                            mode=selector.NumberSelectorMode.BOX,
                        )
                    ),
                }
            ),
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
