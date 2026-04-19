"""Cycle management logic for automatic and manual cycles."""
from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone

from homeassistant.core import HomeAssistant, callback, Event
from homeassistant.config_entries import ConfigEntry
from homeassistant.helpers.event import (
    async_track_state_change_event,
    async_call_later,
)
from homeassistant.const import STATE_UNAVAILABLE, STATE_UNKNOWN

from .const import (
    DOMAIN,
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
    CYCLE_TYPE_MANUAL,
    CYCLE_TYPE_AUTO,
    CYCLE_STATE_IDLE,
    CYCLE_STATE_RUNNING,
    CYCLE_STATE_FINISHED,
)

_LOGGER = logging.getLogger(__name__)


class CycleManager:
    """Manages cycle detection for a single device."""

    def __init__(
        self,
        hass: HomeAssistant,
        entry: ConfigEntry,
        device: dict,
    ) -> None:
        self._hass = hass
        self._entry = entry
        self._device = device
        self._device_name: str = device["name"]
        self._cycle_type: str = device.get(CONF_CYCLE_TYPE, "none")

        self._unsub_listeners: list[callable] = []

        # Auto cycle state
        self._start_threshold_since: datetime | None = None
        self._end_threshold_since: datetime | None = None
        self._start_timer_unsub: callable | None = None
        self._end_timer_unsub: callable | None = None
        self._duration_update_unsub: callable | None = None

        # Sensor references (set via set_sensors)
        self._state_sensor = None
        self._duration_sensor = None
        self._cost_sensor = None
        self._start_sensor = None
        self._end_sensor = None
        self._meters: list = []
        self._cost_sensors: list = []
        self._alert_sensor = None
        self._ack_button = None

    def set_sensors(
        self, state_sensor, duration_sensor, cost_sensor,
        start_sensor, end_sensor, meters, cost_sensors,
    ) -> None:
        self._state_sensor = state_sensor
        self._duration_sensor = duration_sensor
        self._cost_sensor = cost_sensor
        self._start_sensor = start_sensor
        self._end_sensor = end_sensor
        self._meters = meters
        self._cost_sensors = cost_sensors

    def set_meters(self, meters: list) -> None:
        """Set energy meters (used for manual cycle type)."""
        self._meters = meters

    def set_alert_sensor(self, alert_sensor) -> None:
        self._alert_sensor = alert_sensor

    def set_ack_button(self, button) -> None:
        self._ack_button = button
        if button:
            button.set_cycle_manager(self)

    async def async_start(self) -> None:
        """Start listening for cycle events."""
        if self._cycle_type == CYCLE_TYPE_MANUAL:
            await self._setup_manual()
        elif self._cycle_type == CYCLE_TYPE_AUTO:
            await self._setup_auto()

    async def async_stop(self) -> None:
        """Remove all listeners."""
        for unsub in self._unsub_listeners:
            unsub()
        self._unsub_listeners.clear()
        self._cancel_start_timer()
        self._cancel_end_timer()
        self._cancel_duration_update()

    # ------------------------------------------------------------------
    # Manual cycle
    # ------------------------------------------------------------------
    async def _setup_manual(self) -> None:
        trigger_id = self._device.get(CONF_CYCLE_MANUAL_TRIGGER)
        if not trigger_id:
            return

        self._unsub_listeners.append(
            async_track_state_change_event(
                self._hass, [trigger_id], self._handle_manual_trigger,
            )
        )

    @callback
    def _handle_manual_trigger(self, event: Event) -> None:
        old_state = event.data.get("old_state")
        new_state = event.data.get("new_state")
        if old_state is None or new_state is None:
            return
        was_off = old_state.state.lower() not in ("on", "true", "1")
        is_now_on = new_state.state.lower() in ("on", "true", "1")
        if was_off and is_now_on:
            _LOGGER.info("Manual cycle trigger for %s — resetting meters", self._device_name)
            self._reset_meters()

    # ------------------------------------------------------------------
    # Auto cycle
    # ------------------------------------------------------------------
    async def _setup_auto(self) -> None:
        power_sensor_id = self._device.get(CONF_CYCLE_POWER_SENSOR)
        if not power_sensor_id:
            return

        self._unsub_listeners.append(
            async_track_state_change_event(
                self._hass, [power_sensor_id], self._handle_power_change,
            )
        )

    @callback
    def _handle_power_change(self, event: Event) -> None:
        new_state = event.data.get("new_state")
        if new_state is None or new_state.state in (STATE_UNAVAILABLE, STATE_UNKNOWN):
            return

        try:
            power = float(new_state.state)
        except ValueError:
            return

        current_state = self._get_cycle_state()
        start_threshold = float(self._device.get(CONF_CYCLE_START_THRESHOLD, 0))
        start_duration = float(self._device.get(CONF_CYCLE_START_DURATION, 0))
        end_threshold = float(self._device.get(CONF_CYCLE_END_THRESHOLD, 0))
        end_duration = float(self._device.get(CONF_CYCLE_END_DURATION, 0))

        # --- Start detection ---
        if current_state in (CYCLE_STATE_IDLE, CYCLE_STATE_FINISHED):
            if power > start_threshold:
                if self._start_threshold_since is None:
                    self._start_threshold_since = datetime.now(timezone.utc)
                    self._schedule_start_timer(start_duration)
            else:
                self._start_threshold_since = None
                self._cancel_start_timer()

        # --- End detection ---
        if current_state == CYCLE_STATE_RUNNING:
            # Update duration in real-time
            self._update_live_duration()
            # Update cost in real-time
            if self._cost_sensor:
                self._cost_sensor.recompute()

            if power < end_threshold:
                if self._end_threshold_since is None:
                    self._end_threshold_since = datetime.now(timezone.utc)
                    self._schedule_end_timer(end_duration)
            else:
                self._end_threshold_since = None
                self._cancel_end_timer()

    def _schedule_start_timer(self, duration_s: float) -> None:
        self._cancel_start_timer()

        @callback
        def _on_start_timer(_now) -> None:
            self._start_timer_unsub = None
            if self._start_threshold_since is None:
                return
            current_state = self._get_cycle_state()
            if current_state not in (CYCLE_STATE_IDLE, CYCLE_STATE_FINISHED):
                return
            self._trigger_cycle_start()

        self._start_timer_unsub = async_call_later(
            self._hass, duration_s, _on_start_timer,
        )

    def _schedule_end_timer(self, duration_s: float) -> None:
        self._cancel_end_timer()

        @callback
        def _on_end_timer(_now) -> None:
            self._end_timer_unsub = None
            if self._end_threshold_since is None:
                return
            current_state = self._get_cycle_state()
            if current_state != CYCLE_STATE_RUNNING:
                return
            self._trigger_cycle_end()

        self._end_timer_unsub = async_call_later(
            self._hass, duration_s, _on_end_timer,
        )

    def _cancel_start_timer(self) -> None:
        if self._start_timer_unsub:
            self._start_timer_unsub()
            self._start_timer_unsub = None

    def _cancel_end_timer(self) -> None:
        if self._end_timer_unsub:
            self._end_timer_unsub()
            self._end_timer_unsub = None

    def _cancel_duration_update(self) -> None:
        if self._duration_update_unsub:
            self._duration_update_unsub()
            self._duration_update_unsub = None

    # ------------------------------------------------------------------
    # Cycle triggers
    # ------------------------------------------------------------------
    def _trigger_cycle_start(self) -> None:
        start_duration = float(self._device.get(CONF_CYCLE_START_DURATION, 0))
        start_time = datetime.now(timezone.utc) - timedelta(seconds=start_duration)

        _LOGGER.info("Auto cycle START for %s", self._device_name)

        # Reset all meters
        self._reset_meters()

        # Update sensors
        if self._state_sensor:
            self._state_sensor.set_state(CYCLE_STATE_RUNNING)
        if self._start_sensor:
            self._start_sensor.set_timestamp(start_time)
        if self._end_sensor:
            self._end_sensor.set_timestamp(None)
        if self._duration_sensor:
            self._duration_sensor.set_duration(start_duration)
        if self._cost_sensor:
            self._cost_sensor.recompute()
        if self._alert_sensor:
            self._alert_sensor.set_alert(False)

        # Reset threshold trackers
        self._start_threshold_since = None
        self._end_threshold_since = None
        self._cancel_start_timer()

        # Start live duration updates
        self._schedule_duration_update()

    def _trigger_cycle_end(self) -> None:
        end_duration = float(self._device.get(CONF_CYCLE_END_DURATION, 0))
        end_time = datetime.now(timezone.utc) - timedelta(seconds=end_duration)

        _LOGGER.info("Auto cycle END for %s", self._device_name)

        # Update sensors
        if self._state_sensor:
            self._state_sensor.set_state(CYCLE_STATE_FINISHED)
        if self._end_sensor:
            self._end_sensor.set_timestamp(end_time)

        # Final duration
        if self._start_sensor and self._duration_sensor:
            start_dt = self._start_sensor.native_value
            if start_dt:
                total_seconds = (end_time - start_dt).total_seconds()
                self._duration_sensor.set_duration(max(0, total_seconds))

        # Final cost
        if self._cost_sensor:
            self._cost_sensor.recompute()

        # Stop live updates
        self._cancel_duration_update()

        # Reset threshold trackers
        self._end_threshold_since = None
        self._cancel_end_timer()

        # Send notifications
        self._hass.async_create_task(self._send_notifications())

        # Alert
        if self._alert_sensor:
            self._alert_sensor.set_alert(True)

    # ------------------------------------------------------------------
    # Acknowledge
    # ------------------------------------------------------------------
    @callback
    def acknowledge(self) -> None:
        """Acknowledge the cycle: move back to idle, turn off alert."""
        current_state = self._get_cycle_state()
        if current_state != CYCLE_STATE_FINISHED:
            _LOGGER.debug("Acknowledge ignored, state is %s", current_state)
            return

        _LOGGER.info("Cycle acknowledged for %s", self._device_name)
        if self._state_sensor:
            self._state_sensor.set_state(CYCLE_STATE_IDLE)
        if self._alert_sensor:
            self._alert_sensor.set_alert(False)

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------
    def _get_cycle_state(self) -> str:
        if self._state_sensor:
            return self._state_sensor.native_value or CYCLE_STATE_IDLE
        return CYCLE_STATE_IDLE

    def _reset_meters(self) -> None:
        for meter in self._meters:
            meter.reset()

    def _update_live_duration(self) -> None:
        if not self._start_sensor or not self._duration_sensor:
            return
        start_dt = self._start_sensor.native_value
        if not start_dt:
            return
        elapsed = (datetime.now(timezone.utc) - start_dt).total_seconds()
        self._duration_sensor.set_duration(max(0, elapsed))

    def _schedule_duration_update(self) -> None:
        """Periodically update duration while cycle is running."""
        self._cancel_duration_update()

        @callback
        def _update(_now) -> None:
            if self._get_cycle_state() != CYCLE_STATE_RUNNING:
                self._cancel_duration_update()
                return
            self._update_live_duration()
            if self._cost_sensor:
                self._cost_sensor.recompute()
            self._schedule_duration_update()

        self._duration_update_unsub = async_call_later(self._hass, 30, _update)

    async def _send_notifications(self) -> None:
        """Send notifications to configured notifiers."""
        notifiers = self._device.get(CONF_CYCLE_NOTIFIERS) or []
        if not notifiers:
            return

        title = self._device.get(CONF_CYCLE_NOTIFICATION_TITLE, "")
        message = self._device.get(CONF_CYCLE_NOTIFICATION_MESSAGE, "")

        if not message:
            return

        # Build template context
        duration_s = self._duration_sensor.extra_state_attributes.get("seconds", 0) if self._duration_sensor else 0
        cost = self._cost_sensor.native_value if self._cost_sensor else 0
        energy_total = sum(
            (m.native_value or 0) for m in self._meters
        )

        context = {
            "duration": _format_duration(int(duration_s or 0)),
            "cost": _fmt(cost or 0, 2),
            "energy_total": _fmt(energy_total, 4),
        }

        # Add per-tariff energy and cost values
        for meter in self._meters:
            tariff_slug = meter.tariff.lower().replace(" ", "_").replace("-", "_")
            context[f"energy_{tariff_slug}"] = _fmt(meter.native_value or 0, 4)

        for cs in self._cost_sensors:
            tariff_slug = cs.tariff.lower().replace(" ", "_").replace("-", "_")
            context[f"cost_{tariff_slug}"] = _fmt(cs.native_value or 0, 2)

        # Simple template replacement
        rendered_title = _render_template(title, context)
        rendered_message = _render_template(message, context)

        for notifier in notifiers:
            # notifier can be:
            # - "notify.mobile_app_iphone" → direct service call: notify.mobile_app_iphone
            # - "script.my_script" → direct service call: script.my_script
            try:
                parts = notifier.split(".", 1)
                if len(parts) != 2:
                    _LOGGER.warning("Invalid notifier format: %s", notifier)
                    continue
                domain, service = parts
                if domain == "notify":
                    await self._hass.services.async_call(
                        "notify",
                        service,
                        {
                            "message": rendered_message,
                            "title": rendered_title,
                        },
                    )
                elif domain == "script":
                    await self._hass.services.async_call(
                        "script",
                        service,
                        {
                            "message": rendered_message,
                            "title": rendered_title,
                        },
                    )
                else:
                    _LOGGER.warning("Unsupported notifier domain: %s", domain)
            except Exception:
                _LOGGER.exception(
                    "Failed to send cycle notification to %s", notifier,
                )


def _render_template(template: str, context: dict[str, str]) -> str:
    """Replace {{ key }} patterns with context values and handle \\n line breaks."""
    result = template
    for key, value in context.items():
        result = result.replace("{{ " + key + " }}", str(value))
        result = result.replace("{{" + key + "}}", str(value))
    # Convert literal \n (user typed in config field) to real newline
    result = result.replace("\\n", "\n")
    return result


def _fmt(value: float, decimals: int = 4) -> str:
    """Format float stripping trailing zeros. e.g. 3.4600 -> '3.46', 0.30 -> '0.3'."""
    return f"{value:.{decimals}f}".rstrip("0").rstrip(".")


def _format_duration(seconds: int) -> str:
    """Format seconds as human-readable French string."""
    seconds = int(seconds)
    hours = seconds // 3600
    minutes = (seconds % 3600) // 60
    if hours > 0:
        h_label = "heures" if hours > 1 else "heure"
        m_label = "minutes" if minutes > 1 else "minute"
        return f"{hours} {h_label} et {minutes} {m_label}"
    elif minutes > 0:
        m_label = "minutes" if minutes > 1 else "minute"
        return f"{minutes} {m_label}"
    else:
        s_label = "secondes" if seconds > 1 else "seconde"
        return f"{seconds} {s_label}"
