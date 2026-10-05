"""Config flow for OpenWrt Parental Controls integration."""

from __future__ import annotations

import logging
import re
from typing import Any

import voluptuous as vol

from homeassistant import config_entries
from homeassistant.core import callback
from homeassistant.data_entry_flow import FlowResult
import homeassistant.helpers.config_validation as cv

from .api import OpenWrtApiClient, OpenWrtAuthError, OpenWrtConnectionError
from .const import (
    CONF_HOST,
    CONF_PASSWORD,
    CONF_POLL_INTERVAL,
    CONF_PORT,
    CONF_SSL,
    CONF_USERNAME,
    CONF_VERIFY_SSL,
    DEFAULT_POLL_INTERVAL,
    DEFAULT_PORT,
    DEFAULT_PORT_SSL,
    DOMAIN,
)
from .models import ParentalProfile, TimeSchedule

_LOGGER = logging.getLogger(__name__)


_MAC_PATTERN = re.compile(r"(?:[0-9a-fA-F]{2}:){5}[0-9a-fA-F]{2}\Z")


STEP_USER_DATA_SCHEMA = vol.Schema(
    {
        vol.Required(CONF_HOST, default="192.168.1.1"): cv.string,
        vol.Required(CONF_PORT, default=DEFAULT_PORT): cv.port,
        vol.Required(CONF_SSL, default=False): cv.boolean,
        vol.Required(CONF_USERNAME, default="root"): cv.string,
        vol.Required(CONF_PASSWORD, default=""): cv.string,
        vol.Optional(CONF_VERIFY_SSL, default=False): cv.boolean,
    }
)


class ParentalConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    """Handle a config flow for OpenWrt Parental Controls."""

    VERSION = 1

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        """Handle the initial setup step."""
        errors: dict[str, str] = {}

        if user_input is not None:
            host = user_input[CONF_HOST].strip()
            port = user_input[CONF_PORT]
            ssl = user_input[CONF_SSL]
            username = user_input[CONF_USERNAME].strip()
            password = user_input[CONF_PASSWORD]
            verify_ssl = user_input.get(CONF_VERIFY_SSL, False)

            await self.async_set_unique_id(f"{host}:{port}")
            self._abort_if_unique_id_configured()

            client = OpenWrtApiClient(
                host=host,
                port=port,
                ssl=ssl,
                username=username,
                password=password,
                verify_ssl=verify_ssl,
            )

            try:
                await client.async_login()
                board_info = await client.async_get_board_info()
                model = (
                    board_info.get("model")
                    or board_info.get("board_name")
                    or "OpenWrt Router"
                )
            except OpenWrtAuthError:
                errors["base"] = "invalid_auth"
            except OpenWrtConnectionError:
                errors["base"] = "cannot_connect"
            except Exception as err:
                _LOGGER.exception("Unexpected exception during connection test: %s", err)
                errors["base"] = "unknown"
            else:
                return self.async_create_entry(
                    title=f"{model} ({host})",
                    data=user_input,
                )
            finally:
                await client.close()

        return self.async_show_form(
            step_id="user",
            data_schema=STEP_USER_DATA_SCHEMA,
            errors=errors,
        )

    @staticmethod
    @callback
    def async_get_options_flow(
        config_entry: config_entries.ConfigEntry,
    ) -> config_entries.OptionsFlow:
        """Get the options flow handler for this entry."""
        return ParentalOptionsFlowHandler(config_entry)


class ParentalOptionsFlowHandler(config_entries.OptionsFlow):
    """Handle options flow for OpenWrt Parental Controls."""

    def __init__(self, config_entry: config_entries.ConfigEntry) -> None:
        """Initialize options flow."""
        self._config_entry = config_entry
        self._selected_profile_id: str | None = None

    async def async_step_init(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        """Show main options menu."""
        return self.async_show_menu(
            step_id="init",
            menu_options=["settings", "profile_select"],
        )

    async def async_step_settings(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        """Manage global monitoring settings."""
        if user_input is not None:
            return self.async_create_entry(title="", data=user_input)

        current_poll = self._config_entry.options.get(
            CONF_POLL_INTERVAL,
            self._config_entry.data.get(CONF_POLL_INTERVAL, DEFAULT_POLL_INTERVAL),
        )

        schema = vol.Schema(
            {
                vol.Required(CONF_POLL_INTERVAL, default=current_poll): vol.All(
                    vol.Coerce(int), vol.Range(min=5, max=300)
                ),
            }
        )

        return self.async_show_form(step_id="settings", data_schema=schema)

    async def async_step_profile_select(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        """Select an existing profile to edit or choose to create a new one."""
        coordinator = self.hass.data.get(DOMAIN, {}).get(self._config_entry.entry_id)
        if not coordinator:
            return self.async_abort(reason="not_ready")

        if user_input is not None:
            selection = user_input.get("profile_action")
            if selection == "new":
                self._selected_profile_id = None
                return await self.async_step_profile_edit()
            else:
                self._selected_profile_id = selection
                return await self.async_step_profile_edit()

        profile_choices = {"new": "+ 新增成员档案 / Add New Profile"}
        for pid, p in coordinator.storage.profiles.items():
            profile_choices[pid] = f"{p.name} ({len(p.mac_addresses)} 台设备 / devices)"

        schema = vol.Schema(
            {
                vol.Required("profile_action", default="new"): vol.In(profile_choices),
            }
        )
        return self.async_show_form(step_id="profile_select", data_schema=schema)

    async def async_step_profile_edit(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        """Edit or create a profile."""
        coordinator = self.hass.data[DOMAIN][self._config_entry.entry_id]
        existing = (
            coordinator.storage.profiles.get(self._selected_profile_id)
            if self._selected_profile_id
            else None
        )
        errors: dict[str, str] = {}

        if user_input is not None:
            # Check for delete request
            if user_input.get("delete_profile", False) and self._selected_profile_id:
                await coordinator.async_delete_profile(self._selected_profile_id)
                return self.async_create_entry(title="", data={})

            mac_input = user_input.get("mac_addresses", [])
            if isinstance(mac_input, str):
                mac_list = [
                    m.strip().lower().replace("-", ":")
                    for m in mac_input.replace("\n", ",").split(",")
                    if m.strip()
                ]
            else:
                mac_list = [
                    str(m).strip().lower().replace("-", ":")
                    for m in mac_input
                    if m
                ]

            manual_mac_str = user_input.get("manual_macs", "")
            if manual_mac_str:
                for part in re.split(r"[\s,;]+", manual_mac_str.strip()):
                    cleaned = part.strip().lower().replace("-", ":")
                    if cleaned:
                        if not _MAC_PATTERN.fullmatch(cleaned):
                            errors["manual_macs"] = "invalid_mac"
                        elif cleaned not in mac_list:
                            mac_list.append(cleaned)

            for mac in mac_list:
                if not _MAC_PATTERN.fullmatch(mac):
                    errors["manual_macs"] = "invalid_mac"
                    break

            if not errors:
                # Retain existing schedule or initialize default schedule
                schedule = (
                    existing.schedule
                    if existing and existing.schedule
                    else TimeSchedule()
                )

                profile = ParentalProfile(
                    id=self._selected_profile_id or ParentalProfile().id,
                    name=user_input.get("name", "New Member"),
                    mac_addresses=mac_list,
                    is_paused=existing.is_paused if existing else False,
                    pause_expires_at=existing.pause_expires_at if existing else None,
                    is_enabled=existing.is_enabled if existing else True,
                    schedule=schedule,
                )

                await coordinator.async_save_profile(profile)
                return self.async_create_entry(title="", data={})

        # Pre-populate defaults
        # Map MACs already assigned to OTHER profiles
        mac_to_other_profile: dict[str, str] = {}
        for pid, prof in coordinator.storage.profiles.items():
            if not existing or pid != existing.id:
                for m in prof.mac_addresses:
                    mac_to_other_profile[m.lower()] = prof.name

        existing_macs_lower = (
            {m.lower() for m in existing.mac_addresses} if existing else set()
        )

        raw_devices: dict[str, tuple[str, bool, bool]] = {}
        for mac, client in coordinator.clients_by_mac.items():
            mac_lower = mac.lower()
            is_mine = mac_lower in existing_macs_lower
            owner = mac_to_other_profile.get(mac_lower)

            host_str = client.hostname or "未命名设备"
            ip_str = f" ({client.ip})" if client.ip else ""
            owner_str = f" [已归属: {owner}]" if owner else ""
            label = f"{host_str}{ip_str} - {mac.upper()}{owner_str}"
            raw_devices[mac_lower] = (label, is_mine, bool(owner))

        # Also add any MACs in existing profile that may not currently be in discovery
        if existing:
            for mac in existing.mac_addresses:
                mac_lower = mac.lower()
                if mac_lower not in raw_devices:
                    raw_devices[mac_lower] = (
                        f"已绑定设备 - {mac.upper()}",
                        True,
                        False,
                    )

        # Clean sort:
        # 1. Currently assigned to this profile
        # 2. Unassigned devices
        # 3. Assigned to other profiles
        def sort_priority(item: tuple[str, tuple[str, bool, bool]]) -> tuple[int, int, str]:
            mac, (_, is_mine, is_other) = item
            return (
                0 if is_mine else 1,
                1 if is_other else 0,
                mac,
            )

        sorted_items = sorted(raw_devices.items(), key=sort_priority)
        available_devices: dict[str, str] = {
            mac: label for mac, (label, _, _) in sorted_items
        }

        default_macs = (
            user_input.get("mac_addresses", existing.mac_addresses if existing else [])
            if user_input is not None
            else (existing.mac_addresses if existing else [])
        )
        default_manual = (
            user_input.get("manual_macs", "")
            if user_input is not None
            else ""
        )
        default_name = (
            user_input.get("name", existing.name if existing else "Family Member")
            if user_input is not None
            else (existing.name if existing else "Family Member")
        )

        schema_fields: dict[Any, Any] = {
            vol.Required("name", default=default_name): cv.string,
            vol.Optional("mac_addresses", default=default_macs): cv.multi_select(
                available_devices
            ),
            vol.Optional("manual_macs", default=default_manual): cv.string,
        }

        if existing:
            schema_fields[vol.Optional("delete_profile", default=False)] = cv.boolean

        return self.async_show_form(
            step_id="profile_edit",
            data_schema=vol.Schema(schema_fields),
            errors=errors,
        )

