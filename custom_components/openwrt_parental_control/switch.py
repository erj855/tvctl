"""Switch platform for OpenWrt Parental Controls."""

from __future__ import annotations

import logging
from typing import Any

from homeassistant.components.switch import SwitchEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import EntityCategory
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.entity import DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DOMAIN, PauseDuration
from .coordinator import ParentalDataUpdateCoordinator
from .models import ParentalProfile

_LOGGER = logging.getLogger(__name__)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up parental control switches."""
    coordinator: ParentalDataUpdateCoordinator = hass.data[DOMAIN][entry.entry_id]
    entities: dict[str, SwitchEntity] = {}

    # Migrate any existing profile_schedule switch entity_category to CONFIG in registry
    try:
        from homeassistant.helpers import entity_registry as er

        ent_reg = er.async_get(hass)
        for profile_id in coordinator.storage.profiles:
            uid = f"{entry.entry_id}_{profile_id}_schedule"
            eid = ent_reg.async_get_entity_id("switch", DOMAIN, uid)
            if eid:
                reg_entry = ent_reg.async_get(eid)
                if reg_entry and reg_entry.entity_category != EntityCategory.CONFIG:
                    ent_reg.async_update_entity(eid, entity_category=EntityCategory.CONFIG)
    except Exception as err:
        _LOGGER.debug("Error updating schedule switch entity category: %s", err)

    @callback
    def _update_entities() -> None:
        new_entities: list[SwitchEntity] = []
        for profile_id in coordinator.storage.profiles:
            for suffix, entity_class in (
                ("pause", ProfilePauseSwitch),
                ("schedule", ProfileScheduleSwitch),
            ):
                key = f"{profile_id}_{suffix}"
                if key not in entities:
                    entity = entity_class(coordinator, entry.entry_id, profile_id)
                    entities[key] = entity
                    new_entities.append(entity)

        wanted = {
            f"{profile_id}_{suffix}"
            for profile_id in coordinator.storage.profiles
            for suffix in ("schedule", "pause")
        }
        for key in entities.keys() - wanted:
            entity = entities.pop(key)
            hass.async_create_task(entity.async_remove())

        if new_entities:
            async_add_entities(new_entities)

    entry.async_on_unload(coordinator.async_add_listener(_update_entities))
    _update_entities()


class BaseProfileEntity(CoordinatorEntity[ParentalDataUpdateCoordinator]):
    """Base class for entities tied to a parental profile."""

    def __init__(
        self,
        coordinator: ParentalDataUpdateCoordinator,
        entry_id: str,
        profile_id: str,
    ) -> None:
        """Initialize the base profile entity."""
        super().__init__(coordinator)
        self._entry_id = entry_id
        self._profile_id = profile_id

    @property
    def profile(self) -> ParentalProfile | None:
        """Get the current profile from coordinator storage."""
        return self.coordinator.storage.profiles.get(self._profile_id)

    @property
    def available(self) -> bool:
        """Return True if profile exists and coordinator is available."""
        return super().available and self.profile is not None

    @property
    def device_info(self) -> DeviceInfo:
        """Link profile entities to a profile device under the router."""
        p = self.profile
        name = p.name if p else "Parental Profile"
        return DeviceInfo(
            identifiers={(DOMAIN, f"{self._entry_id}_{self._profile_id}")},
            via_device=(DOMAIN, self._entry_id),
            name=name,
            manufacturer="OpenWrt Parental Controls",
            model="Parental Profile",
        )


class ProfileScheduleSwitch(BaseProfileEntity, SwitchEntity):
    """Switch to enable or bypass scheduled bedtime rules for a profile."""

    _attr_entity_category = EntityCategory.CONFIG

    def __init__(
        self,
        coordinator: ParentalDataUpdateCoordinator,
        entry_id: str,
        profile_id: str,
    ) -> None:
        """Initialize the schedule switch."""
        super().__init__(coordinator, entry_id, profile_id)
        self._attr_unique_id = f"{entry_id}_{profile_id}_schedule"
        self._attr_has_entity_name = True
        self._attr_translation_key = "profile_schedule"

    @property
    def is_on(self) -> bool:
        """Return True if schedule rules are currently active (enforced)."""
        return bool(
            self.profile
            and self.profile.schedule
            and self.profile.schedule.enabled
        )

    @property
    def icon(self) -> str:
        """Return icon depending on state."""
        return "mdi:calendar-clock" if self.is_on else "mdi:clock-outline"

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """Return extra state attributes."""
        if not self.profile:
            return {}
        p = self.profile
        s = p.schedule
        return {
            "profile_id": p.id,
            "mac_addresses": p.mac_addresses,
            "has_schedule": p.has_schedule,
            "start_time": s.start_time if s else None,
            "stop_time": s.stop_time if s else None,
            "active_days": s.active_days if s else [],
        }

    async def async_turn_on(self, **kwargs: Any) -> None:
        """Enable scheduled blocking rules."""
        await self.coordinator.async_set_profile_schedule_enabled(self._profile_id, True)

    async def async_turn_off(self, **kwargs: Any) -> None:
        """Disable scheduled blocking rules."""
        await self.coordinator.async_set_profile_schedule_enabled(self._profile_id, False)


class ProfilePauseSwitch(BaseProfileEntity, SwitchEntity):
    """Switch to pause/resume internet access for a profile."""

    def __init__(
        self,
        coordinator: ParentalDataUpdateCoordinator,
        entry_id: str,
        profile_id: str,
    ) -> None:
        """Initialize the pause switch."""
        super().__init__(coordinator, entry_id, profile_id)
        self._attr_unique_id = f"{entry_id}_{profile_id}_pause"
        self._attr_has_entity_name = True
        self._attr_translation_key = "profile_pause"

    @property
    def is_on(self) -> bool:
        """Return True if internet is currently paused."""
        return self.profile.is_paused if self.profile else False

    @property
    def icon(self) -> str:
        """Return icon depending on state."""
        return "mdi:pause-circle" if self.is_on else "mdi:play-circle-outline"

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """Return extra state attributes."""
        if not self.profile:
            return {}
        p = self.profile
        return {
            "profile_id": p.id,
            "pause_expires_at": p.pause_expires_at,
            "mac_addresses": p.mac_addresses,
        }

    async def async_turn_on(self, **kwargs: Any) -> None:
        """Pause internet access indefinitely (or until resumed)."""
        await self.coordinator.async_pause_profile(
            self._profile_id, PauseDuration.INDEFINITE.value
        )

    async def async_turn_off(self, **kwargs: Any) -> None:
        """Resume internet access."""
        await self.coordinator.async_resume_profile(self._profile_id)

