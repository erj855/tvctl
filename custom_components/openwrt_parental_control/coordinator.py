"""DataUpdateCoordinator for OpenWrt Parental Controls."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
import logging
from typing import Any

from homeassistant.core import HomeAssistant
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed
import homeassistant.util.dt as dt_util

from .api import OpenWrtApiClient, OpenWrtApiError
from .const import (
    ActivityEventType,
    CONF_POLL_INTERVAL,
    DEFAULT_POLL_INTERVAL,
    DOMAIN,
    PauseDuration,
)
from .models import ClientDevice, ParentalProfile, TimeSchedule
from .policy import PolicyEngine
from .storage import ParentalStorage

_LOGGER = logging.getLogger(__name__)


class ParentalDataUpdateCoordinator(DataUpdateCoordinator[dict[str, Any]]):
    """Coordinates fetching data from OpenWrt and running the policy engine."""

    def __init__(
        self,
        hass: HomeAssistant,
        api: OpenWrtApiClient,
        storage: ParentalStorage,
        entry_config: dict[str, Any],
    ) -> None:
        """Initialize the coordinator."""
        poll_interval = entry_config.get(CONF_POLL_INTERVAL, DEFAULT_POLL_INTERVAL)
        super().__init__(
            hass,
            _LOGGER,
            name=DOMAIN,
            update_interval=timedelta(seconds=poll_interval),
        )
        self.api = api
        self.storage = storage
        self.entry_id = storage._entry_id
        self.policy = PolicyEngine(storage)
        self._last_blocked_macs: set[str] | None = None
        self._applied_blocked_macs: set[str] = set()
        self.clients_by_mac: dict[str, ClientDevice] = {}

    async def _async_update_data(self) -> dict[str, Any]:
        """Fetch clients, evaluate rules (schedules and manual pauses), and sync firewall rules."""
        now = dt_util.now()

        # 1. Fetch clients from OpenWrt
        try:
            clients = await self.api.async_fetch_clients()
            self.clients_by_mac = {c.mac.lower(): c for c in clients}
        except OpenWrtApiError as err:
            raise UpdateFailed(f"Error fetching clients from router: {err}") from err

        # Ensure any MAC assigned to a profile exists in clients_by_mac
        for profile in self.storage.profiles.values():
            for m in profile.mac_addresses:
                m_lower = m.lower()
                if m_lower not in self.clients_by_mac:
                    self.clients_by_mac[m_lower] = ClientDevice(mac=m_lower, is_online=False)

        # 2. Evaluate blocking reasons for all MACs across all profiles (Schedule & Manual Pause)
        all_macs: set[str] = set()
        for profile in self.storage.profiles.values():
            if not profile.mac_addresses and (
                profile.is_paused
                or (
                    profile.has_schedule
                    and profile.schedule
                    and profile.schedule.is_in_block_window(now)
                )
            ):
                _LOGGER.warning(
                    "Profile '%s' is paused or within scheduled block window, but has no MAC addresses assigned; no firewall rule will be generated",
                    profile.name,
                )
            for m in profile.mac_addresses:
                all_macs.add(m.lower())

        blocked_macs: set[str] = set()
        mac_reasons: dict[str, set[str]] = {}

        for mac in all_macs:
            reasons = self.policy.evaluate_mac_block_reasons(mac, now)
            if reasons:
                blocked_macs.add(mac)
                mac_reasons[mac] = {r.value for r in reasons}

        # 3. Sync with OpenWrt Firewall if blocked list changed
        if self._last_blocked_macs is None or blocked_macs != self._last_blocked_macs:
            _LOGGER.info(
                "Syncing firewall blocklist: %s -> %s",
                self._last_blocked_macs,
                blocked_macs,
            )
            success = await self.api.async_sync_firewall_blocks(list(blocked_macs))
            if success:
                self._last_blocked_macs = set(blocked_macs)
                self._applied_blocked_macs = set(blocked_macs)
            else:
                _LOGGER.warning("Firewall sync failed, will retry next cycle")

        # 4. Save persistent state
        await self.storage.async_save()

        # 5. Return state for entities
        return {
            "profiles": self.storage.profiles,
            "clients": self.clients_by_mac,
            "capabilities": self.api.capabilities,
            "blocked_macs": blocked_macs,
            "applied_blocked_macs": set(self._applied_blocked_macs),
            "firewall_sync_success": self._last_blocked_macs == blocked_macs,
            "mac_reasons": mac_reasons,
        }


    # ── Service Methods ───────────────────────────────────────────────────────

    async def async_pause_profile(self, profile_id: str, duration: str) -> None:
        """Pause internet access for a profile with a specified duration."""
        profile = self.storage.profiles.get(profile_id)
        if not profile:
            raise ValueError(f"Profile {profile_id} not found")

        now = dt_util.now()
        expires_at: str | None = None

        if duration == PauseDuration.MINUTES_15.value:
            expires_at = (now + timedelta(minutes=15)).astimezone(timezone.utc).isoformat()
        elif duration == PauseDuration.MINUTES_30.value:
            expires_at = (now + timedelta(minutes=30)).astimezone(timezone.utc).isoformat()
        elif duration == PauseDuration.MINUTES_60.value:
            expires_at = (now + timedelta(hours=1)).astimezone(timezone.utc).isoformat()
        elif duration == PauseDuration.UNTIL_TOMORROW.value:
            tomorrow_7am = (now + timedelta(days=1)).replace(
                hour=7, minute=0, second=0, microsecond=0
            )
            expires_at = tomorrow_7am.astimezone(timezone.utc).isoformat()
        elif duration == PauseDuration.INDEFINITE.value:
            expires_at = None  # Indefinite
        else:
            raise ValueError(f"Unsupported pause duration: {duration}")

        profile.is_paused = True
        profile.pause_expires_at = expires_at

        self.storage.log_event(
            profile.id,
            profile.name,
            ActivityEventType.PAUSED.value,
            detail=f"Duration: {duration}",
        )
        await self.async_refresh()

    async def async_resume_profile(self, profile_id: str) -> None:
        """Clear manual pause for a profile."""
        profile = self.storage.profiles.get(profile_id)
        if not profile:
            raise ValueError(f"Profile {profile_id} not found")

        profile.is_paused = False
        profile.pause_expires_at = None

        self.storage.log_event(
            profile.id,
            profile.name,
            ActivityEventType.RESUMED.value,
        )
        await self.async_refresh()

    async def async_set_profile_enabled(self, profile_id: str, enabled: bool) -> None:
        """Toggle profile rules enabled/bypassed."""
        profile = self.storage.profiles.get(profile_id)
        if not profile:
            raise ValueError(f"Profile {profile_id} not found")

        profile.is_enabled = enabled
        if profile.schedule:
            profile.schedule.enabled = enabled
        self.storage.log_event(
            profile.id,
            profile.name,
            ActivityEventType.PROFILE_UPDATED.value,
            detail="Rules Enabled" if enabled else "Rules Bypassed",
        )
        await self.storage.async_save()
        await self.async_refresh()

    async def async_set_profile_schedule_enabled(self, profile_id: str, enabled: bool) -> None:
        """Toggle profile schedule control enabled/disabled."""
        profile = self.storage.profiles.get(profile_id)
        if not profile:
            raise ValueError(f"Profile {profile_id} not found")

        if not profile.schedule:
            profile.schedule = TimeSchedule()
        profile.schedule.enabled = enabled
        if enabled:
            profile.is_enabled = True
        self.storage.log_event(
            profile.id,
            profile.name,
            ActivityEventType.PROFILE_UPDATED.value,
            detail="Schedule Enabled" if enabled else "Schedule Disabled",
        )
        await self.storage.async_save()
        await self.async_refresh()

    async def async_set_profile_schedule_times(
        self, profile_id: str, start_time: str | None = None, stop_time: str | None = None
    ) -> None:
        """Update profile schedule start/stop times."""
        profile = self.storage.profiles.get(profile_id)
        if not profile:
            raise ValueError(f"Profile {profile_id} not found")

        if not profile.schedule:
            profile.schedule = TimeSchedule()
        if start_time:
            profile.schedule.start_time = start_time
        if stop_time:
            profile.schedule.stop_time = stop_time
        self.storage.log_event(
            profile.id,
            profile.name,
            ActivityEventType.PROFILE_UPDATED.value,
            detail=f"Schedule Time: {profile.schedule.start_time} - {profile.schedule.stop_time}",
        )
        await self.storage.async_save()
        await self.async_refresh()

    async def async_set_profile_schedule_days(self, profile_id: str, days: list[int]) -> None:
        """Update profile schedule active days."""
        profile = self.storage.profiles.get(profile_id)
        if not profile:
            raise ValueError(f"Profile {profile_id} not found")

        if not profile.schedule:
            profile.schedule = TimeSchedule()
        profile.schedule.active_days = days
        self.storage.log_event(
            profile.id,
            profile.name,
            ActivityEventType.PROFILE_UPDATED.value,
            detail=f"Schedule Days: {days}",
        )
        await self.storage.async_save()
        await self.async_refresh()

    async def async_save_profile(self, profile: ParentalProfile) -> None:
        """Create or update a parental profile."""
        existing = self.storage.profiles.get(profile.id)
        is_new = existing is None
        if existing is not None and existing is not profile:
            profile.is_paused = existing.is_paused
            profile.pause_expires_at = existing.pause_expires_at
        self.storage.profiles[profile.id] = profile
        self.storage.log_event(
            profile.id,
            profile.name,
            ActivityEventType.PROFILE_CREATED.value if is_new else ActivityEventType.PROFILE_UPDATED.value,
        )
        await self.storage.async_save()
        await self.async_refresh()

    async def async_delete_profile(
        self, profile_id: str, cleanup_device: bool = True
    ) -> None:
        """Delete a profile and optionally clean up device registry."""
        profile = self.storage.profiles.pop(profile_id, None)
        if profile:
            self.storage.log_event(
                profile.id,
                profile.name,
                ActivityEventType.PROFILE_DELETED.value,
            )
            if cleanup_device and hasattr(self, "hass") and self.hass is not None:
                try:
                    from homeassistant.helpers import device_registry as dr
                    dev_reg = dr.async_get(self.hass)
                    device = dev_reg.async_get_device(
                        identifiers={(DOMAIN, f"{self.entry_id}_{profile_id}")}
                    )
                    if device:
                        dev_reg.async_remove_device(device.id)
                except Exception as err:
                    _LOGGER.debug("Could not remove device for profile %s: %s", profile_id, err)

            await self.storage.async_save()
            await self.async_refresh()

