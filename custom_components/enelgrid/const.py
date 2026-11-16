"""Constants for the enelgrid integration."""

from datetime import timedelta
from zoneinfo import ZoneInfo

DOMAIN = "enelgrid"

CONF_POD = "pod"
CONF_USER_NUMBER = "user_number"
CONF_USERNAME = "username"
CONF_PASSWORD = "password"
CONF_PRICE_PER_KWH = "price_per_kwh"

# Keys used by config entries created before v2.0.0 (config entry version < 5).
LEGACY_CONF_POD = "pod: IT1234567890"
LEGACY_CONF_USER_NUMBER = "numero utente"

# Internal flags stored in entry.data
DATA_HISTORICAL_FETCH_NEEDED = "historical_fetch_needed"
DATA_HISTORICAL_FETCH_COMPLETED = "historical_fetch_completed"

DEFAULT_PRICE_PER_KWH = 0.33

# Enel publishes data with a ~3 day delay: polling more than a few times a day is useless.
UPDATE_INTERVAL = timedelta(hours=12)

# Upper bound for the historical import (Enel keeps roughly 2-3 years online).
HISTORICAL_MAX_MONTHS = 48
HISTORICAL_FETCH_RETRIES = 3

# Enel timestamps are always Italian local time, regardless of the HA time zone.
ENEL_TZ = ZoneInfo("Europe/Rome")
