"""Sensor platform for OpenWrt Parental Controls."""

from __future__ import annotations

import logging
from typing import Any

from homeassistant.components.sensor import (
    SensorEntity,
    SensorStateClass,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity import DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DOMAIN
from .coordinator import ParentalDataUpdateCoordinator

_LOGGER = logging.getLogger(__name__)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up parental control sensors."""
    coordinator: ParentalDataUpdateCoordinator = hass.data[DOMAIN][entry.entry_id]

    # Router-level summary sensor
    router_entities: list[SensorEntity] = [
        RouterBlockedCountSensor(coordinator, entry.entry_id)
    ]
    async_add_entities(router_entities)

    # Clean up any legacy sensors from prior integration versions
    try:
        from homeassistant.helpers import entity_registry as er

        ent_reg = er.async_get(hass)
        for profile in coordinator.storage.profiles.values():
            profile_uid = f"{entry.entry_id}_{profile.id}_daily_usage"
            eid = ent_reg.async_get_entity_id("sensor", DOMAIN, profile_uid)
            if eid:
                _LOGGER.debug("Removing legacy profile usage sensor: %s", eid)
                ent_reg.async_remove(eid)

            for mac in profile.mac_addresses:
                mac_clean = mac.lower().replace(":", "").replace("-", "")
                for suffix in ("daily_usage", "remaining", "usage"):
                    for prefix in (f"{entry.entry_id}_{mac_clean}", f"{entry.entry_id}_{profile.id}_{mac_clean}"):
                        uid = f"{prefix}_{suffix}"
                        eid = ent_reg.async_get_entity_id("sensor", DOMAIN, uid)
                        if eid:
                            _LOGGER.debug("Removing legacy device sensor: %s", eid)
                            ent_reg.async_remove(eid)
    except Exception as err:
        _LOGGER.debug("Error cleaning up legacy sensors: %s", err)


class RouterBlockedCountSensor(
    CoordinatorEntity[ParentalDataUpdateCoordinator], SensorEntity
):
    """Sensor reporting the total count of currently blocked devices."""

    _attr_state_class = SensorStateClass.MEASUREMENT
    _attr_icon = "mdi:shield-alert-outline"

    def __init__(
        self,
        coordinator: ParentalDataUpdateCoordinator,
        entry_id: str,
    ) -> None:
        """Initialize the router summary sensor."""
        super().__init__(coordinator)
        self._entry_id = entry_id
        self._attr_unique_id = f"{entry_id}_blocked_device_count"
        self._attr_has_entity_name = True
        self._attr_translation_key = "router_blocked_count"

    @property
    def native_value(self) -> int:
        """Return number of blocked devices."""
        blocked = self.coordinator.data.get("applied_blocked_macs", set())
        return len(blocked)

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """Return list of blocked MACs."""
        return {
            "blocked_macs": sorted(
                list(self.coordinator.data.get("applied_blocked_macs", set()))
            ),
            "desired_blocked_macs": sorted(
                list(self.coordinator.data.get("blocked_macs", set()))
            ),
            "firewall_sync_success": self.coordinator.data.get(
                "firewall_sync_success", False
            ),
        }

    @property
    def device_info(self) -> DeviceInfo:
        """Associate with router."""
        return DeviceInfo(
            identifiers={(DOMAIN, self._entry_id)},
            name="OpenWrt Router",
            manufacturer="OpenWrt",
        )
