"""Time platform for OpenWrt Parental Controls."""

from __future__ import annotations

from datetime import time
import logging
from typing import Any

from homeassistant.components.time import TimeEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import EntityCategory
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.entity import DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DOMAIN
from .coordinator import ParentalDataUpdateCoordinator
from .models import ParentalProfile

_LOGGER = logging.getLogger(__name__)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up parental control time entities."""
    coordinator: ParentalDataUpdateCoordinator = hass.data[DOMAIN][entry.entry_id]
    entities: dict[str, TimeEntity] = {}

    @callback
    def _update_entities() -> None:
        new_entities: list[TimeEntity] = []
        for profile_id in coordinator.storage.profiles:
            for suffix, entity_class in (
                ("schedule_start", ProfileScheduleStartTimeEntity),
                ("schedule_stop", ProfileScheduleStopTimeEntity),
            ):
                key = f"{profile_id}_{suffix}"
                if key not in entities:
                    entity = entity_class(coordinator, entry.entry_id, profile_id)
                    entities[key] = entity
                    new_entities.append(entity)

        wanted = {
            f"{profile_id}_{suffix}"
            for profile_id in coordinator.storage.profiles
            for suffix in ("schedule_start", "schedule_stop")
        }
        for key in entities.keys() - wanted:
            entity = entities.pop(key)
            hass.async_create_task(entity.async_remove())

        if new_entities:
            async_add_entities(new_entities)

    entry.async_on_unload(coordinator.async_add_listener(_update_entities))
    _update_entities()


class BaseProfileTimeEntity(CoordinatorEntity[ParentalDataUpdateCoordinator], TimeEntity):
    """Base class for profile schedule time entities."""

    _attr_entity_category = EntityCategory.CONFIG

    def __init__(
        self,
        coordinator: ParentalDataUpdateCoordinator,
        entry_id: str,
        profile_id: str,
    ) -> None:
        """Initialize the time entity."""
        super().__init__(coordinator)
        self._entry_id = entry_id
        self._profile_id = profile_id

    @property
    def profile(self) -> ParentalProfile | None:
        """Get the profile from coordinator storage."""
        return self.coordinator.storage.profiles.get(self._profile_id)

    @property
    def available(self) -> bool:
        """Return True if profile and schedule exist."""
        return (
            super().available
            and self.profile is not None
            and self.profile.schedule is not None
        )

    @property
    def device_info(self) -> DeviceInfo:
        """Link time entity to the profile device."""
        p = self.profile
        name = p.name if p else "Parental Profile"
        return DeviceInfo(
            identifiers={(DOMAIN, f"{self._entry_id}_{self._profile_id}")},
            via_device=(DOMAIN, self._entry_id),
            name=name,
            manufacturer="OpenWrt Parental Controls",
            model="Parental Profile",
        )


class ProfileScheduleStartTimeEntity(BaseProfileTimeEntity):
    """Time entity for schedule start time (bedtime block begins)."""

    def __init__(
        self,
        coordinator: ParentalDataUpdateCoordinator,
        entry_id: str,
        profile_id: str,
    ) -> None:
        """Initialize start time entity."""
        super().__init__(coordinator, entry_id, profile_id)
        self._attr_unique_id = f"{entry_id}_{profile_id}_schedule_start"
        self._attr_has_entity_name = True
        self._attr_translation_key = "profile_schedule_start"
        self._attr_icon = "mdi:clock-start"

    @property
    def native_value(self) -> time | None:
        """Return the schedule start time."""
        if not self.profile or not self.profile.schedule:
            return time(21, 30)
        try:
            h, m = map(int, self.profile.schedule.start_time.split(":"))
            return time(h, m)
        except (ValueError, AttributeError):
            return time(21, 30)

    async def async_set_value(self, value: time) -> None:
        """Set new schedule start time."""
        time_str = f"{value.hour:02d}:{value.minute:02d}"
        await self.coordinator.async_set_profile_schedule_times(
            self._profile_id, start_time=time_str
        )


class ProfileScheduleStopTimeEntity(BaseProfileTimeEntity):
    """Time entity for schedule stop time (bedtime block ends)."""

    def __init__(
        self,
        coordinator: ParentalDataUpdateCoordinator,
        entry_id: str,
        profile_id: str,
    ) -> None:
        """Initialize stop time entity."""
        super().__init__(coordinator, entry_id, profile_id)
        self._attr_unique_id = f"{entry_id}_{profile_id}_schedule_stop"
        self._attr_has_entity_name = True
        self._attr_translation_key = "profile_schedule_stop"
        self._attr_icon = "mdi:clock-end"

    @property
    def native_value(self) -> time | None:
        """Return the schedule stop time."""
        if not self.profile or not self.profile.schedule:
            return time(6, 30)
        try:
            h, m = map(int, self.profile.schedule.stop_time.split(":"))
            return time(h, m)
        except (ValueError, AttributeError):
            return time(6, 30)

    async def async_set_value(self, value: time) -> None:
        """Set new schedule stop time."""
        time_str = f"{value.hour:02d}:{value.minute:02d}"
        await self.coordinator.async_set_profile_schedule_times(
            self._profile_id, stop_time=time_str
        )
