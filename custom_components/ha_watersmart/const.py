"""WaterSmart constants."""

from datetime import timedelta

DOMAIN = "ha_watersmart"
NAME = "HA WaterSmart"
CONF_ACCOUNT_NUMBER = "account_number"
DEFAULT_URL = "https://milpitas.watersmart.com"
UPDATE_INTERVAL = timedelta(minutes=30)
STORAGE_VERSION = 1
