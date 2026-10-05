"""OpenWrt ubus JSON-RPC client for Home Assistant."""

from __future__ import annotations

import asyncio
import logging
from typing import Any
import aiohttp

from .models import ClientDevice, normalize_mac

_LOGGER = logging.getLogger(__name__)


class OpenWrtApiError(Exception):
    """Base exception for OpenWrt API errors."""


class OpenWrtAuthError(OpenWrtApiError):
    """Authentication failure or invalid credentials."""


class OpenWrtConnectionError(OpenWrtApiError):
    """Network connection or timeout error."""


class OpenWrtApiClient:
    """Communicates with OpenWrt router via ubus JSON-RPC."""

    def __init__(
        self,
        host: str,
        port: int = 80,
        ssl: bool = False,
        username: str = "root",
        password: str = "",
        verify_ssl: bool = False,
        session: aiohttp.ClientSession | None = None,
    ) -> None:
        """Initialize the client."""
        self.host = host
        self.port = port
        self.ssl = ssl
        self.username = username
        self.password = password
        self.verify_ssl = verify_ssl
        self._session = session
        self._owns_session = False
        self._ubus_session: str | None = None
        self._capabilities: dict[str, bool] = {}
        self._has_wireless: bool | None = None
        self._has_nlbwmon: bool | None = None

    @property
    def base_url(self) -> str:
        """Construct the base RPC URL."""
        scheme = "https" if self.ssl else "http"
        return f"{scheme}://{self.host}:{self.port}/ubus"

    async def _get_session(self) -> aiohttp.ClientSession:
        """Get or create an aiohttp client session."""
        if self._session is None or self._session.closed:
            self._session = aiohttp.ClientSession(
                connector=aiohttp.TCPConnector(ssl=self.verify_ssl)
            )
            self._owns_session = True
        return self._session

    async def close(self) -> None:
        """Close the underlying session if owned."""
        if self._owns_session and self._session and not self._session.closed:
            await self._session.close()

    async def async_login(self) -> bool:
        """Authenticate with OpenWrt and obtain a ubus session token."""
        session = await self._get_session()
        payload = {
            "jsonrpc": "2.0",
            "id": 1,
            "method": "call",
            "params": [
                "00000000000000000000000000000000",
                "session",
                "login",
                {"username": self.username, "password": self.password},
            ],
        }

        try:
            async with session.post(
                self.base_url,
                json=payload,
                timeout=aiohttp.ClientTimeout(total=10),
            ) as resp:
                if resp.status != 200:
                    raise OpenWrtConnectionError(f"HTTP {resp.status} on login")
                data = await resp.json()
        except asyncio.TimeoutError as err:
            raise OpenWrtConnectionError("Timeout while connecting to router") from err
        except aiohttp.ClientError as err:
            raise OpenWrtConnectionError(f"Connection failed: {err}") from err

        result = data.get("result")
        if isinstance(result, list) and len(result) > 1 and result[0] == 0:
            session_data = result[1]
            if isinstance(session_data, dict) and "ubus_rpc_session" in session_data:
                self._ubus_session = session_data["ubus_rpc_session"]
                _LOGGER.debug("ubus session acquired successfully")
                return True

        raise OpenWrtAuthError("Invalid username or password")

    async def async_call(
        self,
        object_name: str,
        method: str,
        params: dict[str, Any] | None = None,
        _retry_auth: bool = True,
    ) -> Any:
        """Make an authenticated ubus RPC call with automatic session renewal."""
        if not self._ubus_session:
            await self.async_login()

        session = await self._get_session()
        call_params = [self._ubus_session, object_name, method, params or {}]
        payload = {"jsonrpc": "2.0", "id": 1, "method": "call", "params": call_params}

        try:
            async with session.post(
                self.base_url,
                json=payload,
                timeout=aiohttp.ClientTimeout(total=12),
            ) as resp:
                if resp.status != 200:
                    raise OpenWrtConnectionError(f"HTTP {resp.status} on {object_name}.{method}")
                data = await resp.json()
        except asyncio.TimeoutError as err:
            raise OpenWrtConnectionError(f"Timeout on {object_name}.{method}") from err
        except aiohttp.ClientError as err:
            raise OpenWrtConnectionError(f"Client error on {object_name}.{method}: {err}") from err

        error = data.get("error")
        if error:
            err_code = error.get("code") if isinstance(error, dict) else None
            err_msg = str(error.get("message", "") if isinstance(error, dict) else error)
            # -32002: Access denied (ubus session expired or invalid token)
            if (err_code == -32002 or "Access denied" in err_msg) and _retry_auth:
                _LOGGER.debug("ubus session token expired (-32002), re-authenticating...")
                await self.async_login()
                return await self.async_call(
                    object_name, method, params, _retry_auth=False
                )
            raise OpenWrtApiError(f"RPC {object_name}.{method} error: {error}")

        result = data.get("result")
        if isinstance(result, list) and len(result) > 0:
            code = result[0]
            if code == 6:  # Access denied / token expired
                if _retry_auth:
                    _LOGGER.debug("ubus token may be expired (code 6), re-authenticating...")
                    await self.async_login()
                    return await self.async_call(
                        object_name, method, params, _retry_auth=False
                    )
                raise OpenWrtApiError(
                    f"RPC {object_name}.{method} access denied (code 6)"
                )
            if code != 0:
                raise OpenWrtApiError(f"RPC {object_name}.{method} failed with code {code}")
            return result[1] if len(result) > 1 else None

        return None

    async def async_probe_capabilities(self) -> dict[str, bool]:
        """Discover available ubus methods and system capabilities."""
        caps = {
            "uci_read": False,
            "dhcp_leases": False,
            "host_hints": False,
            "wireless": False,
            "nlbwmon": False,
            "client_discovery": False,
            "traffic_counters": False,
        }

        try:
            # Test UCI read access
            await self.async_call("uci", "get", {"config": "firewall"})
            caps["uci_read"] = True
        except Exception:
            caps["uci_read"] = False

        try:
            # Test DHCP leases
            await self.async_call("luci-rpc", "getDHCPLeases")
            caps["dhcp_leases"] = True
        except Exception:
            caps["dhcp_leases"] = False

        try:
            # Test Host hints
            await self.async_call("luci-rpc", "getHostHints")
            caps["host_hints"] = True
        except Exception:
            caps["host_hints"] = False

        try:
            # Test wireless capability
            w = await self.async_call("luci-rpc", "getWirelessDevices")
            caps["wireless"] = bool(w)
            self._has_wireless = bool(w)
        except Exception:
            caps["wireless"] = False
            self._has_wireless = False

        try:
            # Test nlbwmon capability
            n = await self.async_call("nlbwmon", "status")
            caps["nlbwmon"] = bool(n is not None)
            self._has_nlbwmon = bool(n is not None)
        except Exception:
            caps["nlbwmon"] = False
            self._has_nlbwmon = False

        try:
            clients = await self.async_fetch_clients()
            caps["client_discovery"] = len(clients) > 0
            caps["traffic_counters"] = any(
                client.rx_bytes is not None and client.tx_bytes is not None
                for client in clients
            )
        except Exception:
            pass

        self._capabilities = caps
        _LOGGER.debug("Discovered capabilities: %s", caps)
        return caps

    @property
    def capabilities(self) -> dict[str, bool]:
        """Return the last probed, read-only capability summary."""
        return dict(self._capabilities)

    async def async_get_board_info(self) -> dict[str, Any]:
        """Fetch OpenWrt system board information."""
        try:
            data = await self.async_call("system", "board")
            if isinstance(data, dict):
                return data
        except Exception as err:
            _LOGGER.debug("Could not fetch system board info: %s", err)
        return {}

    async def async_fetch_clients(self) -> list[ClientDevice]:
        """Fetch clients from DHCP, host hints, and associated wireless stations."""
        clients: dict[str, ClientDevice] = {}
        successful_sources = 0

        # 1. Fetch DHCP Leases
        try:
            leases = await self.async_call("luci-rpc", "getDHCPLeases")
            successful_sources += 1
            if isinstance(leases, dict):
                raw_leases = leases.get("dhcp_leases", leases.get("lease", []))
                if isinstance(raw_leases, list):
                    for lease in raw_leases:
                        if not isinstance(lease, dict):
                            continue
                        mac = normalize_mac(lease.get("macaddr", ""))
                        if not mac:
                            continue
                        clients[mac] = ClientDevice(
                            mac=mac,
                            ip=lease.get("ipaddr"),
                            hostname=lease.get("hostname"),
                            is_online=False,
                        )
                raw_dhcp6_leases = leases.get("dhcp6_leases", [])
                if isinstance(raw_dhcp6_leases, list):
                    for lease in raw_dhcp6_leases:
                        if not isinstance(lease, dict):
                            continue
                        mac = normalize_mac(
                            lease.get("macaddr", lease.get("mac", ""))
                        )
                        if not mac:
                            continue
                        client = clients.setdefault(mac, ClientDevice(mac=mac))
                        client.ip = client.ip or lease.get("ip6addr")
                        client.hostname = client.hostname or lease.get("hostname")
        except Exception as err:
            _LOGGER.debug("Could not fetch DHCP leases via luci-rpc: %s", err)

        # 2. Fetch Host Hints
        try:
            hints = await self.async_call("luci-rpc", "getHostHints")
            successful_sources += 1
            if isinstance(hints, dict):
                for mac_raw, info in hints.items():
                    mac = normalize_mac(mac_raw)
                    if not mac:
                        continue
                    name = info.get("name") if isinstance(info, dict) else None
                    ips = info.get("ipaddrs") if isinstance(info, dict) else []
                    ip = ips[0] if isinstance(ips, list) and ips else None

                    if mac in clients:
                        if not clients[mac].hostname and name:
                            clients[mac].hostname = name
                        if not clients[mac].ip and ip:
                            clients[mac].ip = ip
                    else:
                        clients[mac] = ClientDevice(mac=mac, ip=ip, hostname=name)
        except Exception as err:
            _LOGGER.debug("Could not fetch host hints: %s", err)

        # 3. Discover wireless interfaces (skipped if router has no wireless hardware)
        if self._has_wireless is not False:
            try:
                wireless = await self.async_call("luci-rpc", "getWirelessDevices")
                self._has_wireless = True
                interfaces: set[str] = set()
                if isinstance(wireless, dict):
                    for radio in wireless.values():
                        if not isinstance(radio, dict):
                            continue
                        raw_ifaces = radio.get("interfaces", [])
                        if isinstance(raw_ifaces, dict):
                            raw_ifaces = raw_ifaces.values()
                        if isinstance(raw_ifaces, (list, tuple, set)):
                            for iface in raw_ifaces:
                                if isinstance(iface, dict) and iface.get("ifname"):
                                    interfaces.add(str(iface["ifname"]))

                for interface in interfaces:
                    try:
                        stations = await self.async_call(
                            "iwinfo", "assoclist", {"device": interface}
                        )
                    except OpenWrtApiError as err:
                        _LOGGER.debug(
                            "Could not fetch wireless stations for %s: %s",
                            interface,
                            err,
                        )
                        continue
                    successful_sources += 1
                    raw_results = stations.get("results", []) if isinstance(stations, dict) else []
                    if isinstance(raw_results, dict):
                        station_items = [
                            ({"mac": mac, **station} if isinstance(station, dict) else {"mac": mac})
                            for mac, station in raw_results.items()
                        ]
                    elif isinstance(raw_results, list):
                        station_items = raw_results
                    else:
                        station_items = []

                    for station in station_items:
                        if not isinstance(station, dict):
                            continue
                        mac = normalize_mac(
                            station.get("mac", station.get("macaddr", ""))
                        )
                        if mac:
                            client = clients.setdefault(mac, ClientDevice(mac=mac))
                            client.is_online = True
                            client.is_wireless = True
                            client.iface = interface
                            rx_bytes = station.get("rx_bytes")
                            tx_bytes = station.get("tx_bytes")
                            if rx_bytes is not None and tx_bytes is not None:
                                client.rx_bytes = int(rx_bytes)
                                client.tx_bytes = int(tx_bytes)
                            if station.get("inactive") is not None:
                                try:
                                    client.inactive_ms = int(station["inactive"])
                                except (ValueError, TypeError):
                                    pass
            except Exception as err:
                if self._has_wireless is None:
                    self._has_wireless = False
                    _LOGGER.debug(
                        "Router does not have wireless subsystem (e.g. wired router); skipping wireless queries: %s",
                        err,
                    )
                else:
                    _LOGGER.debug("Could not discover wireless clients: %s", err)

        # 4. Fetch per-client traffic counters from nlbwmon if available
        if self._has_nlbwmon is not False:
            try:
                nlbw_dump = await self.async_call("nlbwmon", "dump", {"grouped": False})
                self._has_nlbwmon = True
                if isinstance(nlbw_dump, dict):
                    rows = nlbw_dump.get("rows", [])
                    columns = nlbw_dump.get("columns", [])
                    mac_idx = columns.index("mac") if "mac" in columns else 2
                    rx_idx = columns.index("rx_bytes") if "rx_bytes" in columns else 3
                    tx_idx = columns.index("tx_bytes") if "tx_bytes" in columns else 4
                    for r in rows:
                        if isinstance(r, list) and len(r) > max(mac_idx, rx_idx, tx_idx):
                            mac = normalize_mac(r[mac_idx])
                            if mac:
                                client = clients.setdefault(mac, ClientDevice(mac=mac))
                                client.is_online = True
                                rx_val = r[rx_idx]
                                tx_val = r[tx_idx]
                                if rx_val is not None and tx_val is not None:
                                    client.rx_bytes = int(rx_val)
                                    client.tx_bytes = int(tx_val)
                    if rows:
                        successful_sources += 1
            except Exception as err:
                if self._has_nlbwmon is None:
                    self._has_nlbwmon = False
                _LOGGER.debug("Could not fetch traffic from nlbwmon: %s", err)

        if successful_sources == 0:
            raise OpenWrtConnectionError("All client discovery sources failed")

        return list(clients.values())

    async def async_sync_firewall_blocks(self, blocked_macs: list[str]) -> bool:
        """Enforce WAN blocking rules for all designated MACs via UCI firewall."""
        rule_name = "parentcontrol_block"
        macs_upper = [m.upper().replace("-", ":") for m in blocked_macs if m]

        try:
            # 1. Inspect existing firewall rules
            res = await self.async_call("uci", "get", {"config": "firewall"})
            values = (res.get("values") if isinstance(res, dict) else {}) or {}

            target_sec = None
            for sec_key, sec in values.items():
                if isinstance(sec, dict):
                    if (
                        sec_key == rule_name
                        or sec.get(".name") == rule_name
                        or sec.get("name") == rule_name
                    ):
                        target_sec = sec_key
                        break

            if not macs_upper:
                # No devices need to be blocked: remove the rule if it exists
                if target_sec:
                    await self.async_call(
                        "uci", "delete", {"config": "firewall", "section": target_sec}
                    )
                    await self.async_call("uci", "commit", {"config": "firewall"})
                    await self._async_reload_firewall()
                return True

            rule_values = {
                "name": rule_name,
                "src": "lan",
                "dest": "wan",
                "src_mac": macs_upper,
                "target": "REJECT",
                "enabled": "1",
            }

            if not target_sec:
                # Add new firewall reject rule as a named section
                await self.async_call(
                    "uci",
                    "add",
                    {
                        "config": "firewall",
                        "type": "rule",
                        "name": rule_name,
                        "values": rule_values,
                    },
                )
            else:
                # Update existing rule
                await self.async_call(
                    "uci",
                    "set",
                    {
                        "config": "firewall",
                        "section": target_sec,
                        "values": rule_values,
                    },
                )

            await self.async_call("uci", "commit", {"config": "firewall"})
            await self._async_reload_firewall()
            _LOGGER.info("Firewall block enforced for MACs: %s", macs_upper)
            return True
        except Exception as err:
            _LOGGER.error("Failed to sync firewall block rules: %s", err)
            return False

    async def _async_reload_firewall(self) -> None:
        """Reload firewall service via rpcd rc."""
        try:
            await self.async_call("rc", "init", {"name": "firewall", "action": "reload"})
        except Exception as err:
            _LOGGER.debug("Firewall reload via rc failed, trying restart: %s", err)
            try:
                await self.async_call("rc", "init", {"name": "firewall", "action": "restart"})
            except Exception as restart_err:
                _LOGGER.warning("Could not reload or restart firewall via rc: %s", restart_err)

