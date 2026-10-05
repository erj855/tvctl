"""Data models for OpenWrt Parental Controls."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, time
import re
import uuid
from typing import Any

from .const import BlockReason


def normalize_mac(value: Any) -> str:
    """Return a canonical lowercase MAC, or an empty string if invalid."""
    mac = str(value).strip().lower().replace("-", ":")
    if not re.fullmatch(r"(?:[0-9a-f]{2}:){5}[0-9a-f]{2}", mac):
        return ""
    if mac == "00:00:00:00:00:00":
        return ""
    return mac


@dataclass
class TimeSchedule:
    """Recurring block schedule."""

    active_days: list[int] = field(default_factory=lambda: [0, 1, 2, 3, 4])  # 0=Mon ... 6=Sun
    start_time: str = "21:30"
    stop_time: str = "06:30"
    enabled: bool = True

    def is_in_block_window(self, dt: datetime) -> bool:
        """Return True if the given local datetime falls within the block window."""
        if not self.enabled or not self.active_days:
            return False

        weekday = dt.weekday()  # 0=Monday ... 6=Sunday
        cur_min = dt.hour * 60 + dt.minute

        try:
            s_h, s_m = map(int, self.start_time.split(":"))
            e_h, e_m = map(int, self.stop_time.split(":"))
        except (ValueError, AttributeError):
            return False

        start_min = s_h * 60 + s_m
        stop_min = e_h * 60 + e_m

        if start_min < stop_min:
            # Daytime block window: e.g. 14:00 to 18:00 on active days
            if weekday in self.active_days:
                return start_min <= cur_min < stop_min
            return False
        elif start_min > stop_min:
            # Overnight block window: e.g. 21:30 (today) to 06:30 (tomorrow)
            yesterday_weekday = (weekday - 1) % 7
            if cur_min >= start_min and weekday in self.active_days:
                return True
            if cur_min < stop_min and yesterday_weekday in self.active_days:
                return True
            return False
        else:
            # Equal times = 24-hour block on active days
            return weekday in self.active_days

    def to_dict(self) -> dict[str, Any]:
        """Convert schedule to dictionary."""
        return {
            "active_days": self.active_days,
            "start_time": self.start_time,
            "stop_time": self.stop_time,
            "enabled": self.enabled,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> TimeSchedule:
        """Create schedule from dictionary."""
        return cls(
            active_days=data.get("active_days", [0, 1, 2, 3, 4]),
            start_time=data.get("start_time", "21:30"),
            stop_time=data.get("stop_time", "06:30"),
            enabled=data.get("enabled", True),
        )


@dataclass
class ParentalProfile:
    """Represents a member or device group profile."""

    id: str = field(default_factory=lambda: uuid.uuid4().hex[:8])
    name: str = "New Member"
    mac_addresses: list[str] = field(default_factory=list)
    is_paused: bool = False
    pause_expires_at: str | None = None  # ISO format UTC timestamp string
    is_enabled: bool = True  # True=rules enforced, False=rules bypassed
    schedule: TimeSchedule | None = field(default_factory=TimeSchedule)

    @property
    def has_schedule(self) -> bool:
        """Whether a recurring schedule is configured."""
        return self.schedule is not None and self.schedule.enabled

    def to_dict(self) -> dict[str, Any]:
        """Convert profile to serializable dictionary."""
        return {
            "id": self.id,
            "name": self.name,
            "mac_addresses": [m.lower() for m in self.mac_addresses],
            "is_paused": self.is_paused,
            "pause_expires_at": self.pause_expires_at,
            "is_enabled": self.is_enabled,
            "schedule": self.schedule.to_dict() if self.schedule else None,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> ParentalProfile:
        """Create profile from dictionary."""
        sched_data = data.get("schedule")
        schedule = TimeSchedule.from_dict(sched_data) if sched_data else TimeSchedule()

        raw_macs = data.get("mac_addresses", [])
        clean_macs = [str(m).lower() for m in raw_macs]

        return cls(
            id=data.get("id", uuid.uuid4().hex[:8]),
            name=data.get("name", "New Member"),
            mac_addresses=clean_macs,
            is_paused=data.get("is_paused", False),
            pause_expires_at=data.get("pause_expires_at"),
            is_enabled=data.get("is_enabled", True),
            schedule=schedule,
        )


@dataclass
class ClientDevice:
    """Represents a discovered network client."""

    mac: str
    ip: str | None = None
    hostname: str | None = None
    iface: str | None = None
    rx_bytes: int | None = None
    tx_bytes: int | None = None
    is_wireless: bool = False
    is_online: bool = False
    inactive_ms: int | None = None

    @property
    def display_name(self) -> str:
        """Return friendly display label."""
        return self.hostname or self.ip or self.mac


@dataclass
class ActivityEvent:
    """Audit event for activity logging."""

    profile_id: str
    profile_name: str
    event_type: str
    timestamp: str  # ISO string
    detail: str | None = None

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary."""
        return {
            "profile_id": self.profile_id,
            "profile_name": self.profile_name,
            "event_type": self.event_type,
            "timestamp": self.timestamp,
            "detail": self.detail,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> ActivityEvent:
        """Create event from dictionary."""
        return cls(
            profile_id=data.get("profile_id", ""),
            profile_name=data.get("profile_name", ""),
            event_type=data.get("event_type", ""),
            timestamp=data.get("timestamp", ""),
            detail=data.get("detail"),
        )
