"""Select platform for OpenWrt Parental Controls."""

from __future__ import annotations

import logging
from typing import Any

from homeassistant.components.select import SelectEntity
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

DAY_PRESETS: dict[str, list[int]] = {
    "weekdays": [0, 1, 2, 3, 4],
    "everyday": [0, 1, 2, 3, 4, 5, 6],
}

PRESET_OPTIONS = ["weekdays", "everyday"]


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up parental control select entities."""
    coordinator: ParentalDataUpdateCoordinator = hass.data[DOMAIN][entry.entry_id]
    entities: dict[str, SelectEntity] = {}

    @callback
    def _update_entities() -> None:
        new_entities: list[SelectEntity] = []
        for profile_id in coordinator.storage.profiles:
            key = f"{profile_id}_schedule_days"
            if key not in entities:
                entity = ProfileScheduleDaysSelectEntity(
                    coordinator, entry.entry_id, profile_id
                )
                entities[key] = entity
                new_entities.append(entity)

        wanted = {
            f"{profile_id}_schedule_days"
            for profile_id in coordinator.storage.profiles
        }
        for key in entities.keys() - wanted:
            entity = entities.pop(key)
            hass.async_create_task(entity.async_remove())

        if new_entities:
            async_add_entities(new_entities)

    entry.async_on_unload(coordinator.async_add_listener(_update_entities))
    _update_entities()


class ProfileScheduleDaysSelectEntity(
    CoordinatorEntity[ParentalDataUpdateCoordinator], SelectEntity
):
    """Select entity for schedule active days preset."""

    _attr_entity_category = EntityCategory.CONFIG

    def __init__(
        self,
        coordinator: ParentalDataUpdateCoordinator,
        entry_id: str,
        profile_id: str,
    ) -> None:
        """Initialize schedule days select entity."""
        super().__init__(coordinator)
        self._entry_id = entry_id
        self._profile_id = profile_id
        self._attr_unique_id = f"{entry_id}_{profile_id}_schedule_days"
        self._attr_has_entity_name = True
        self._attr_translation_key = "profile_schedule_days"
        self._attr_icon = "mdi:calendar-repeat"
        self._attr_options = PRESET_OPTIONS

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
        """Link select entity to the profile device."""
        p = self.profile
        name = p.name if p else "Parental Profile"
        return DeviceInfo(
            identifiers={(DOMAIN, f"{self._entry_id}_{self._profile_id}")},
            via_device=(DOMAIN, self._entry_id),
            name=name,
            manufacturer="OpenWrt Parental Controls",
            model="Parental Profile",
        )

    @property
    def current_option(self) -> str | None:
        """Return the current active days preset."""
        if not self.profile or not self.profile.schedule:
            return "weekdays"

        current_days = sorted(self.profile.schedule.active_days)
        if current_days == DAY_PRESETS["everyday"]:
            return "everyday"
        return "weekdays"

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """Return active days numbers."""
        if not self.profile or not self.profile.schedule:
            return {}
        return {
            "active_days": self.profile.schedule.active_days,
        }

    async def async_select_option(self, option: str) -> None:
        """Select a new active days preset."""
        if option in DAY_PRESETS:
            await self.coordinator.async_set_profile_schedule_days(
                self._profile_id, DAY_PRESETS[option]
            )
