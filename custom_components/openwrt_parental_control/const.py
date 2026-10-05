"""Constants for the OpenWrt Parental Controls integration."""

from enum import Enum

DOMAIN = "openwrt_parental_control"

# Configuration Keys
CONF_HOST = "host"
CONF_PORT = "port"
CONF_SSL = "ssl"
CONF_USERNAME = "username"
CONF_PASSWORD = "password"
CONF_VERIFY_SSL = "verify_ssl"
CONF_POLL_INTERVAL = "poll_interval"

# Default values
DEFAULT_PORT = 80
DEFAULT_PORT_SSL = 443
DEFAULT_POLL_INTERVAL = 30  # seconds

# Storage Constants
STORAGE_KEY = "openwrt_parental_control_store"
STORAGE_VERSION = 1


# Block Reasons
class BlockReason(str, Enum):
    """Reasons why a device or profile is currently blocked."""
    MANUAL_PAUSE = "manual_pause"
    SCHEDULE = "schedule"


# Pause Durations
class PauseDuration(str, Enum):
    """Presets for pausing internet access."""
    MINUTES_15 = "15m"
    MINUTES_30 = "30m"
    MINUTES_60 = "60m"
    UNTIL_TOMORROW = "until_tomorrow"
    INDEFINITE = "indefinite"


# Activity Event Types
class ActivityEventType(str, Enum):
    """Audit log activity event types."""
    PROFILE_CREATED = "profile_created"
    PROFILE_UPDATED = "profile_updated"
    PROFILE_DELETED = "profile_deleted"
    PAUSED = "paused"
    RESUMED = "resumed"
    SCHEDULE_BLOCKED = "schedule_blocked"
    SCHEDULE_RESUMED = "schedule_resumed"
