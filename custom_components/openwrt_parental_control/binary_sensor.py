"""Binary sensor platform for OpenWrt Parental Controls."""

from __future__ import annotations

import logging
from typing import Any

from homeassistant.components.binary_sensor import (
    BinarySensorDeviceClass,
    BinarySensorEntity,
)
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
    """Set up parental control binary sensors."""
    coordinator: ParentalDataUpdateCoordinator = hass.data[DOMAIN][entry.entry_id]
    entities: dict[tuple[str, ...], BinarySensorEntity] = {}

    # Clean up any legacy router-level binary sensors from prior integration versions
    try:
        from homeassistant.helpers import entity_registry as er

        ent_reg = er.async_get(hass)
        for profile in coordinator.storage.profiles.values():
            for mac in profile.mac_addresses:
                mac_clean = mac.lower().replace(":", "").replace("-", "")
                legacy_uid = f"{entry.entry_id}_{mac_clean}_blocked"
                eid = ent_reg.async_get_entity_id("binary_sensor", DOMAIN, legacy_uid)
                if eid:
                    _LOGGER.debug("Removing legacy router binary sensor entity: %s", eid)
                    ent_reg.async_remove(eid)

        # Migrate profile_blocked binary sensors from DIAGNOSTIC to None (Sensors) in registry
        for profile_id in coordinator.storage.profiles:
            uid = f"{entry.entry_id}_{profile_id}_blocked"
            eid = ent_reg.async_get_entity_id("binary_sensor", DOMAIN, uid)
            if eid:
                reg_entry = ent_reg.async_get(eid)
                if reg_entry and reg_entry.entity_category is not None:
                    ent_reg.async_update_entity(eid, entity_category=None)
    except Exception as err:
        _LOGGER.debug("Error cleaning up / updating binary sensors: %s", err)

    @callback
    def _update_entities() -> None:
        new_entities: list[BinarySensorEntity] = []
        wanted: set[tuple[str, ...]] = set()

        # 1. Profile blocked binary sensors
        for profile_id in coordinator.storage.profiles:
            key = ("profile", profile_id)
            wanted.add(key)
            if key not in entities:
                entity = ProfileBlockedBinarySensor(coordinator, entry.entry_id, profile_id)
                entities[key] = entity
                new_entities.append(entity)

        # 2. Per-device blocked binary sensors attached to each profile
        for profile_id, profile in coordinator.storage.profiles.items():
            for mac in profile.mac_addresses:
                mac_lower = mac.lower()
                key = ("device", profile_id, mac_lower.replace(":", "").replace("-", ""))
                wanted.add(key)
                if key not in entities:
                    entity = DeviceBlockedBinarySensor(
                        coordinator, entry.entry_id, profile_id, mac_lower
                    )
                    entities[key] = entity
                    new_entities.append(entity)

        for key in entities.keys() - wanted:
            entity = entities.pop(key)
            hass.async_create_task(entity.async_remove())

        if new_entities:
            async_add_entities(new_entities)

    entry.async_on_unload(coordinator.async_add_listener(_update_entities))
    _update_entities()


class ProfileBlockedBinarySensor(
    CoordinatorEntity[ParentalDataUpdateCoordinator], BinarySensorEntity
):
    """Indicates whether a profile is currently blocked."""

    def __init__(
        self,
        coordinator: ParentalDataUpdateCoordinator,
        entry_id: str,
        profile_id: str,
    ) -> None:
        """Initialize the sensor."""
        super().__init__(coordinator)
        self._entry_id = entry_id
        self._profile_id = profile_id
        self._attr_unique_id = f"{entry_id}_{profile_id}_blocked"
        self._attr_has_entity_name = True
        self._attr_translation_key = "profile_blocked"

    @property
    def profile(self) -> ParentalProfile | None:
        """Return the associated profile."""
        return self.coordinator.storage.profiles.get(self._profile_id)

    @property
    def available(self) -> bool:
        """Return True if profile exists and coordinator is available."""
        return super().available and self.profile is not None

    @property
    def is_on(self) -> bool:
        """Return True if profile is paused or any of its devices are blocked."""
        p = self.profile
        if not p:
            return False
        if not p.mac_addresses:
            return False
        blocked_macs = self.coordinator.data.get("applied_blocked_macs", set())
        return any(m.lower() in blocked_macs for m in p.mac_addresses)

    @property
    def icon(self) -> str:
        """Return icon depending on state."""
        return "mdi:account-cancel" if self.is_on else "mdi:account-check"

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """Return reasons and details for the block."""
        p = self.profile
        if not p:
            return {}

        applied_blocked_macs = self.coordinator.data.get("applied_blocked_macs", set())
        desired_blocked_macs = self.coordinator.data.get("blocked_macs", set())
        mac_reasons = self.coordinator.data.get("mac_reasons", {})

        profile_blocked_macs = [
            m for m in p.mac_addresses if m.lower() in applied_blocked_macs
        ]
        collected_reasons: set[str] = set()
        for m in profile_blocked_macs:
            collected_reasons.update(mac_reasons.get(m.lower(), []))

        return {
            "profile_id": p.id,
            "blocked_reasons": sorted(list(collected_reasons)),
            "blocked_macs": profile_blocked_macs,
            "desired_blocked_macs": [
                m for m in p.mac_addresses if m.lower() in desired_blocked_macs
            ],
            "firewall_sync_success": self.coordinator.data.get(
                "firewall_sync_success", False
            ),
            "total_assigned_devices": len(p.mac_addresses),
            "is_paused": p.is_paused,
            "pause_expires_at": p.pause_expires_at,
        }

    @property
    def device_info(self) -> DeviceInfo:
        """Associate sensor with profile device."""
        p = self.profile
        name = p.name if p else "Parental Profile"
        return DeviceInfo(
            identifiers={(DOMAIN, f"{self._entry_id}_{self._profile_id}")},
            via_device=(DOMAIN, self._entry_id),
            name=name,
            manufacturer="OpenWrt Parental Controls",
            model="Parental Profile",
        )


class DeviceBlockedBinarySensor(
    CoordinatorEntity[ParentalDataUpdateCoordinator], BinarySensorEntity
):
    """Indicates whether a specific network MAC address is blocked."""

    _attr_entity_category = EntityCategory.DIAGNOSTIC

    def __init__(
        self,
        coordinator: ParentalDataUpdateCoordinator,
        entry_id: str,
        profile_id: str,
        mac: str,
    ) -> None:
        """Initialize the device sensor."""
        super().__init__(coordinator)
        self._entry_id = entry_id
        self._profile_id = profile_id
        self._mac = mac.lower()
        mac_clean = self._mac.replace(":", "").replace("-", "")
        self._attr_unique_id = f"{entry_id}_{profile_id}_{mac_clean}_blocked"
        self._attr_has_entity_name = True
        self._attr_translation_key = "device_blocked"

    @property
    def profile(self) -> ParentalProfile | None:
        """Return the associated profile."""
        return self.coordinator.storage.profiles.get(self._profile_id)

    @property
    def available(self) -> bool:
        """Return True if profile exists and MAC is assigned."""
        p = self.profile
        return (
            super().available
            and p is not None
            and self._mac in [m.lower() for m in p.mac_addresses]
        )

    @property
    def translation_placeholders(self) -> dict[str, str]:
        """Return translation placeholders."""
        client = self.coordinator.clients_by_mac.get(self._mac)
        label = client.hostname if client and client.hostname else self._mac
        return {"device_name": label}

    @property
    def is_on(self) -> bool:
        """Return True if the MAC is currently in the firewall drop list."""
        blocked_macs = self.coordinator.data.get("applied_blocked_macs", set())
        return self._mac in blocked_macs

    @property
    def icon(self) -> str:
        """Return icon depending on state."""
        return "mdi:web-off" if self.is_on else "mdi:web"

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """Return active reasons and network details."""
        client = self.coordinator.clients_by_mac.get(self._mac)
        mac_reasons = self.coordinator.data.get("mac_reasons", {})
        return {
            "profile_id": self._profile_id,
            "mac": self._mac,
            "ip": client.ip if client else None,
            "hostname": client.hostname if client else None,
            "reasons": sorted(list(mac_reasons.get(self._mac, []))),
            "desired_blocked": self._mac in self.coordinator.data.get(
                "blocked_macs", set()
            ),
            "firewall_sync_success": self.coordinator.data.get(
                "firewall_sync_success", False
            ),
            "rx_bytes": client.rx_bytes if client else 0,
            "tx_bytes": client.tx_bytes if client else 0,
        }

    @property
    def device_info(self) -> DeviceInfo:
        """Attach sensor to the parent profile."""
        p = self.profile
        name = p.name if p else "Parental Profile"
        return DeviceInfo(
            identifiers={(DOMAIN, f"{self._entry_id}_{self._profile_id}")},
            via_device=(DOMAIN, self._entry_id),
            name=name,
            manufacturer="OpenWrt Parental Controls",
            model="Parental Profile",
        )

