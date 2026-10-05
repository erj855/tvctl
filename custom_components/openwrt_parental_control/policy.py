"""Policy evaluation engine for OpenWrt Parental Controls."""

from __future__ import annotations

from datetime import datetime, timezone
import logging

from .const import BlockReason
from .models import ParentalProfile
from .storage import ParentalStorage

_LOGGER = logging.getLogger(__name__)


class PolicyEngine:
    """Evaluates schedules and manual pause rules to coordinate blocking reasons."""

    def __init__(self, storage: ParentalStorage) -> None:
        """Initialize the policy engine."""
        self.storage = storage

    def get_profiles_for_mac(self, mac: str) -> list[ParentalProfile]:
        """Find all profiles that contain this MAC address."""
        mac_lower = mac.lower()
        return [
            profile
            for profile in self.storage.profiles.values()
            if any(m.lower() == mac_lower for m in profile.mac_addresses)
        ]

    def evaluate_mac_block_reasons(
        self, mac: str, now: datetime
    ) -> set[BlockReason]:
        """Evaluate all blocking reasons that apply to a MAC address across all profiles."""
        reasons: set[BlockReason] = set()
        mac_lower = mac.lower()
        profiles = self.get_profiles_for_mac(mac_lower)

        for profile in profiles:
            # 1. Evaluate Manual Pause
            if profile.is_paused:
                if profile.pause_expires_at:
                    try:
                        exp_dt = datetime.fromisoformat(profile.pause_expires_at)
                        if exp_dt.tzinfo is None:
                            exp_dt = exp_dt.replace(tzinfo=timezone.utc)
                        else:
                            exp_dt = exp_dt.astimezone(timezone.utc)

                        now_utc = (
                            now.astimezone(timezone.utc)
                            if now.tzinfo is not None
                            else now.replace(tzinfo=timezone.utc)
                        )

                        if now_utc < exp_dt:
                            reasons.add(BlockReason.MANUAL_PAUSE)
                        else:
                            # Timed pause has expired
                            profile.is_paused = False
                            profile.pause_expires_at = None
                    except (ValueError, TypeError) as err:
                        _LOGGER.warning("Error parsing pause_expires_at: %s", err)
                        reasons.add(BlockReason.MANUAL_PAUSE)
                else:
                    reasons.add(BlockReason.MANUAL_PAUSE)

            # 2. Evaluate Time Schedule (bedtime / study hours)
            if profile.has_schedule and profile.schedule:
                if profile.schedule.is_in_block_window(now):
                    reasons.add(BlockReason.SCHEDULE)

        return reasons
