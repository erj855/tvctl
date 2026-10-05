"""OpenWrt Parental Controls integration for Home Assistant."""

from __future__ import annotations

import logging
import re
from typing import Any

import voluptuous as vol

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import Platform
from homeassistant.core import HomeAssistant, ServiceCall
from homeassistant.helpers import device_registry as dr
import homeassistant.helpers.config_validation as cv

from .api import OpenWrtApiClient
from .const import (
    CONF_HOST,
    CONF_PASSWORD,
    CONF_PORT,
    CONF_SSL,
    CONF_USERNAME,
    CONF_VERIFY_SSL,
    DOMAIN,
    PauseDuration,
)
from .coordinator import ParentalDataUpdateCoordinator
from .models import ParentalProfile, TimeSchedule
from .storage import ParentalStorage

_LOGGER = logging.getLogger(__name__)

PLATFORMS: list[Platform] = [
    Platform.SWITCH,
    Platform.SELECT,
    Platform.TIME,
    Platform.BINARY_SENSOR,
    Platform.SENSOR,
]

# Service Names
SERVICE_PAUSE_PROFILE = "pause_profile"
SERVICE_RESUME_PROFILE = "resume_profile"
SERVICE_SET_PROFILE_ENABLED = "set_profile_enabled"
SERVICE_SAVE_PROFILE = "save_profile"
SERVICE_DELETE_PROFILE = "delete_profile"
SERVICE_NAMES = (
    SERVICE_PAUSE_PROFILE,
    SERVICE_RESUME_PROFILE,
    SERVICE_SET_PROFILE_ENABLED,
    SERVICE_SAVE_PROFILE,
    SERVICE_DELETE_PROFILE,
)


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Set up OpenWrt Parental Controls from a config entry."""
    hass.data.setdefault(DOMAIN, {})

    config = {**entry.data, **entry.options}
    host = config[CONF_HOST]
    port = config[CONF_PORT]
    ssl = config[CONF_SSL]
    username = config[CONF_USERNAME]
    password = config[CONF_PASSWORD]
    verify_ssl = config.get(CONF_VERIFY_SSL, False)

    api = OpenWrtApiClient(
        host=host,
        port=port,
        ssl=ssl,
        username=username,
        password=password,
        verify_ssl=verify_ssl,
    )

    storage = ParentalStorage(hass, entry.entry_id)
    await storage.async_load()

    try:
        # Discover capabilities
        await api.async_probe_capabilities()

        coordinator = ParentalDataUpdateCoordinator(hass, api, storage, config)
        await coordinator.async_config_entry_first_refresh()
        hass.data[DOMAIN][entry.entry_id] = coordinator

        # Set up entity platforms
        try:
            await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
        except Exception:
            hass.data[DOMAIN].pop(entry.entry_id, None)
            await api.async_sync_firewall_blocks([])
            raise

        # Clean up any legacy number entities from prior versions
        try:
            from homeassistant.helpers import entity_registry as er

            ent_reg = er.async_get(hass)
            for profile_id in coordinator.storage.profiles:
                uid = f"{entry.entry_id}_{profile_id}_daily_limit"
                eid = ent_reg.async_get_entity_id("number", DOMAIN, uid)
                if eid:
                    ent_reg.async_remove(eid)
        except Exception:
            pass
    except Exception:
        await api.close()
        raise

    # Register integration services once
    _async_register_services(hass)

    entry.async_on_unload(entry.add_update_listener(async_reload_entry))
    return True


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Unload a config entry."""
    coordinator: ParentalDataUpdateCoordinator = hass.data[DOMAIN][entry.entry_id]
    if not await coordinator.api.async_sync_firewall_blocks([]):
        _LOGGER.error(
            "Cannot unload %s because its firewall rules could not be cleared",
            entry.entry_id,
        )
        return False

    unload_ok = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
    if unload_ok:
        hass.data[DOMAIN].pop(entry.entry_id, None)
        await coordinator.api.close()
        if not hass.data[DOMAIN]:
            for service_name in SERVICE_NAMES:
                hass.services.async_remove(DOMAIN, service_name)
            hass.data.pop(DOMAIN, None)

    return unload_ok


async def async_remove_config_entry_device(
    hass: HomeAssistant, config_entry: ConfigEntry, device_entry: dr.DeviceEntry
) -> bool:
    """Remove a config entry from a device."""
    coordinator: ParentalDataUpdateCoordinator = hass.data.get(DOMAIN, {}).get(
        config_entry.entry_id
    )
    if not coordinator:
        return False

    prefix = f"{config_entry.entry_id}_"
    for domain, identifier in device_entry.identifiers:
        if domain == DOMAIN and identifier.startswith(prefix):
            profile_id = identifier[len(prefix):]
            if profile_id in coordinator.storage.profiles:
                _LOGGER.info("Removing profile %s via device removal", profile_id)
                await coordinator.async_delete_profile(profile_id, cleanup_device=False)
                return True
    return False


async def async_reload_entry(hass: HomeAssistant, entry: ConfigEntry) -> None:
    """Reload config entry after options update."""
    await hass.config_entries.async_reload(entry.entry_id)


def _get_target_coordinator(
    hass: HomeAssistant, entry_id: str | None = None
) -> ParentalDataUpdateCoordinator:
    """Retrieve the requested coordinator, requiring an unambiguous target."""
    coordinators: dict[str, ParentalDataUpdateCoordinator] = hass.data.get(DOMAIN, {})
    if not coordinators:
        raise ValueError("No active OpenWrt Parental Controls instances found")

    if entry_id:
        if entry_id not in coordinators:
            raise ValueError(f"No active router config entry {entry_id!r}")
        return coordinators[entry_id]

    if len(coordinators) != 1:
        raise ValueError("entry_id is required when multiple routers are configured")
    return next(iter(coordinators.values()))


def _async_register_services(hass: HomeAssistant) -> None:
    """Register domain-level services."""
    if hass.services.has_service(DOMAIN, SERVICE_PAUSE_PROFILE):
        return

    async def async_handle_pause_profile(call: ServiceCall) -> None:
        profile_id = call.data["profile_id"]
        duration = call.data.get("duration", PauseDuration.INDEFINITE.value)
        entry_id = call.data.get("entry_id")
        coordinator = _get_target_coordinator(hass, entry_id)
        await coordinator.async_pause_profile(profile_id, duration)

    async def async_handle_resume_profile(call: ServiceCall) -> None:
        profile_id = call.data["profile_id"]
        entry_id = call.data.get("entry_id")
        coordinator = _get_target_coordinator(hass, entry_id)
        await coordinator.async_resume_profile(profile_id)

    async def async_handle_set_profile_enabled(call: ServiceCall) -> None:
        profile_id = call.data["profile_id"]
        enabled = call.data["enabled"]
        entry_id = call.data.get("entry_id")
        coordinator = _get_target_coordinator(hass, entry_id)
        await coordinator.async_set_profile_enabled(profile_id, enabled)

    async def async_handle_save_profile(call: ServiceCall) -> None:
        entry_id = call.data.get("entry_id")
        coordinator = _get_target_coordinator(hass, entry_id)

        profile_id = call.data.get("profile_id") or ParentalProfile().id
        existing = coordinator.storage.profiles.get(profile_id)
        schedule_data = call.data.get("schedule", existing.schedule if existing else None)
        schedule = (
            TimeSchedule.from_dict(schedule_data)
            if isinstance(schedule_data, dict)
            else schedule_data
        )
        raw_macs = call.data.get(
            "mac_addresses", existing.mac_addresses if existing else []
        )
        mac_addresses = []
        for value in raw_macs:
            mac = str(value).strip().lower().replace("-", ":")
            if not re.fullmatch(r"(?:[0-9a-f]{2}:){5}[0-9a-f]{2}", mac):
                raise vol.Invalid(f"Invalid MAC address: {value!r}")
            if mac not in mac_addresses:
                mac_addresses.append(mac)

        profile = ParentalProfile(
            id=profile_id,
            name=call.data["name"],
            mac_addresses=mac_addresses,
            is_paused=existing.is_paused if existing else False,
            pause_expires_at=existing.pause_expires_at if existing else None,
            is_enabled=call.data.get(
                "is_enabled", existing.is_enabled if existing else True
            ),
            schedule=schedule,
        )
        await coordinator.async_save_profile(profile)

    async def async_handle_delete_profile(call: ServiceCall) -> None:
        profile_id = call.data["profile_id"]
        entry_id = call.data.get("entry_id")
        coordinator = _get_target_coordinator(hass, entry_id)
        await coordinator.async_delete_profile(profile_id)

    hass.services.async_register(
        DOMAIN,
        SERVICE_PAUSE_PROFILE,
        async_handle_pause_profile,
        schema=vol.Schema(
            {
                vol.Required("profile_id"): cv.string,
                vol.Optional("duration", default=PauseDuration.INDEFINITE.value): cv.string,
                vol.Optional("entry_id"): cv.string,
            }
        ),
    )

    hass.services.async_register(
        DOMAIN,
        SERVICE_RESUME_PROFILE,
        async_handle_resume_profile,
        schema=vol.Schema(
            {
                vol.Required("profile_id"): cv.string,
                vol.Optional("entry_id"): cv.string,
            }
        ),
    )

    hass.services.async_register(
        DOMAIN,
        SERVICE_SET_PROFILE_ENABLED,
        async_handle_set_profile_enabled,
        schema=vol.Schema(
            {
                vol.Required("profile_id"): cv.string,
                vol.Required("enabled"): cv.boolean,
                vol.Optional("entry_id"): cv.string,
            }
        ),
    )

    hass.services.async_register(
        DOMAIN,
        SERVICE_SAVE_PROFILE,
        async_handle_save_profile,
        schema=vol.Schema(
            {
                vol.Optional("profile_id"): cv.string,
                vol.Required("name"): cv.string,
                vol.Optional("mac_addresses"): cv.ensure_list,
                vol.Optional("is_enabled"): cv.boolean,
                vol.Optional("schedule"): vol.Any(dict, None),
                vol.Optional("entry_id"): cv.string,
            }
        ),
    )

    hass.services.async_register(
        DOMAIN,
        SERVICE_DELETE_PROFILE,
        async_handle_delete_profile,
        schema=vol.Schema(
            {
                vol.Required("profile_id"): cv.string,
                vol.Optional("entry_id"): cv.string,
            }
        ),
    )

