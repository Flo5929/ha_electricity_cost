"""Constants for Electricity Cost integration."""

DOMAIN = "electricity_cost"
PLATFORMS = ["sensor", "select"]

# Config keys
CONF_TARIFFS = "tariffs"
CONF_PRICE_ENTITIES = "price_entities"  # dict { tariff_name -> input_number entity_id }

# Device config keys
CONF_DEVICE_NAME = "device_name"
CONF_SOURCE_SENSOR = "source_sensor"
CONF_RESET_ENTITY = "reset_entity"  # optional: on/off entity that resets meters on OFF→ON

# Select entity
TARIFF_SELECT_UNIQUE_ID = "electricity_active_tariff"
TARIFF_SELECT_NAME = "Electricity Active Tariff"
