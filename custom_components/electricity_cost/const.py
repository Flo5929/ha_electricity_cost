"""Constants for Electricity Cost integration."""

DOMAIN = "electricity_cost"
PLATFORMS = ["sensor", "select", "binary_sensor", "button"]

# Config keys
CONF_TARIFFS = "tariffs"
CONF_PRICE_ENTITIES = "price_entities"  # dict { tariff_name -> input_number entity_id }

# Device config keys
CONF_DEVICE_NAME = "device_name"
CONF_SOURCE_SENSOR = "source_sensor"
CONF_RESET_ENTITY = "reset_entity"  # optional: on/off entity that resets meters on OFF→ON

# Cycle config keys
CONF_CYCLE_TYPE = "cycle_type"  # "none", "manual", "auto"
CONF_CYCLE_MANUAL_TRIGGER = "cycle_manual_trigger"
CONF_CYCLE_POWER_SENSOR = "cycle_power_sensor"
CONF_CYCLE_START_THRESHOLD = "cycle_start_threshold"
CONF_CYCLE_START_DURATION = "cycle_start_duration"
CONF_CYCLE_END_THRESHOLD = "cycle_end_threshold"
CONF_CYCLE_END_DURATION = "cycle_end_duration"
CONF_CYCLE_NOTIFIERS = "cycle_notifiers"
CONF_CYCLE_NOTIFICATION_TITLE = "cycle_notification_title"
CONF_CYCLE_NOTIFICATION_MESSAGE = "cycle_notification_message"
CONF_CYCLE_ALERT_ENABLED = "cycle_alert_enabled"
CONF_CYCLE_ALERT_ENTITY = "cycle_alert_entity"

# Cycle states
CYCLE_STATE_IDLE = "idle"
CYCLE_STATE_RUNNING = "running"
CYCLE_STATE_FINISHED = "finished"

CYCLE_TYPE_NONE = "none"
CYCLE_TYPE_MANUAL = "manual"
CYCLE_TYPE_AUTO = "auto"

# Select entity
TARIFF_SELECT_UNIQUE_ID = "electricity_active_tariff"
TARIFF_SELECT_NAME = "Electricity Active Tariff"
