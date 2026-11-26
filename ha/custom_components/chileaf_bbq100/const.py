"""Constants for the Chileaf BBQ100 integration."""

DOMAIN = "chileaf_bbq100"
MANUFACTURER = "Chileaf"
MODEL = "BBQ100"

# Re-read every probe's full state this often while connected. The thermometer
# pushes temperatures by itself; this keeps mode, timer and alarm fresh in case
# it does not push those.
CHANNEL_REFRESH_INTERVAL = 30  # seconds

# With no notification for this long the link is treated as dead and dropped.
SILENCE_TIMEOUT = 90  # seconds

CONNECT_ATTEMPTS = 3
