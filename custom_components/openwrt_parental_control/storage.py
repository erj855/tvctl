"""Storage manager for OpenWrt Parental Controls."""

from __future__ import annotations

from datetime import datetime, timezone
import logging
from typing import Any

from homeassistant.core import HomeAssistant
from homeassistant.helpers.storage import Store

from .const import STORAGE_KEY, STORAGE_VERSION
from .models import ActivityEvent, ParentalProfile

_LOGGER = logging.getLogger(__name__)


class ParentalStorage:
    """Manages persistent state across Home Assistant restarts."""

    def __init__(self, hass: HomeAssistant, entry_id: str) -> None:
        """Initialize the storage manager."""
        self._hass = hass
        self._entry_id = entry_id
        self._store = Store(hass, STORAGE_VERSION, f"{STORAGE_KEY}_{entry_id}")
        self.profiles: dict[str, ParentalProfile] = {}
        self.activity_log: list[ActivityEvent] = []

    async def async_load(self) -> None:
        """Load stored data."""
        data = await self._store.async_load()
        if not data:
            _LOGGER.debug("No existing parental storage found for %s", self._entry_id)
            return

        try:
            # Load Profiles
            raw_profiles = data.get("profiles", {})
            self.profiles = {
                pid: ParentalProfile.from_dict(p_data)
                for pid, p_data in raw_profiles.items()
            }

            # Load Activity Log
            raw_log = data.get("activity_log", [])
            self.activity_log = [ActivityEvent.from_dict(e) for e in raw_log]

            _LOGGER.debug(
                "Loaded %d profiles from storage",
                len(self.profiles),
            )
        except Exception as err:
            _LOGGER.error("Failed to parse parental storage: %s", err)

    async def async_save(self) -> None:
        """Persist data to storage."""
        data = {
            "profiles": {pid: p.to_dict() for pid, p in self.profiles.items()},
            "activity_log": [e.to_dict() for e in self.activity_log[:100]],
        }
        await self._store.async_save(data)

    def log_event(
        self,
        profile_id: str,
        profile_name: str,
        event_type: str,
        detail: str | None = None,
    ) -> None:
        """Add an audit entry to the activity log."""
        event = ActivityEvent(
            profile_id=profile_id,
            profile_name=profile_name,
            event_type=event_type,
            timestamp=datetime.now(timezone.utc).isoformat(),
            detail=detail,
        )
        self.activity_log.insert(0, event)
        if len(self.activity_log) > 100:
            self.activity_log = self.activity_log[:100]
