"""Inventory: control_point -> connection details, resolved from the SoT.

Infrahub owns device identity (ADR-0001); nothing in this repo keeps its own
device list. Credentials still arrive from the environment - the SoT knows
WHERE a device is, never how to log in.
"""

from __future__ import annotations

from typing import Any

# netmiko device_type / platform slug -> executor driver name. The interim
# capability lookup until SoT capability records land (ADR-0011).
PLATFORM_DRIVERS: dict[str, str] = {
    "nokia_srl": "srlinux",
    "nokia_srlinux": "srlinux",
    "srlinux": "srlinux",
    "arista_eos": "eos",
    "eos": "eos",
}

DEVICE_QUERY = """
query Device($name: String!) {
  DcimDevice(name__value: $name) {
    edges {
      node {
        name { value }
        primary_address { node { address { value } } }
        platform { node { name { value } netmiko_device_type { value } } }
      }
    }
  }
}
"""


class SotInventory:
    """Resolve connection details and artifact content from Infrahub.

    ``platform_drivers`` injects the intent profile's reviewed platform ->
    driver bindings (ADR-0016), keyed exactly as the SoT spells platforms;
    the module-level slug map stays the fail-closed fallback."""

    def __init__(
        self,
        address: str,
        token: str,
        username: str,
        password: str,
        platform_drivers: dict[str, str] | None = None,
    ):
        try:
            from infrahub_sdk import Config, InfrahubClientSync
        except ImportError as exc:  # pragma: no cover
            raise RuntimeError(
                "infrahub-sdk is not installed; use "
                "`pip install autonetops-executor[infrahub]`"
            ) from exc
        self._client = InfrahubClientSync(address=address, config=Config(api_token=token))
        self._username = username
        self._password = password
        self._platform_drivers = platform_drivers or {}

    def connection_for(self, control_point: str) -> dict[str, Any]:
        result = self._client.execute_graphql(
            query=DEVICE_QUERY, variables={"name": control_point}
        )
        edges = result["DcimDevice"]["edges"]
        if not edges:
            raise KeyError(f"control point {control_point!r} not found in the SoT")
        node = edges[0]["node"]
        primary = (node.get("primary_address") or {}).get("node")
        if not primary:
            raise KeyError(f"{control_point} has no primary_address in the SoT")
        return {
            "host": primary["address"]["value"].split("/")[0],
            "username": self._username,
            "password": self._password,
        }

    def driver_for(self, control_point: str) -> str | None:
        """Executor driver for a device that is NOT in the plan (gates observe
        unchanged neighbors - a CE-only plan is proven on its PEs). None when
        the SoT has no platform mapping; the caller reports unverifiable."""
        try:
            result = self._client.execute_graphql(
                query=DEVICE_QUERY, variables={"name": control_point}
            )
            edges = result["DcimDevice"]["edges"]
            if not edges:
                return None
            platform = (edges[0]["node"].get("platform") or {}).get("node") or {}
            for key in ("name", "netmiko_device_type"):
                spelled = (platform.get(key) or {}).get("value") or ""
                if spelled in self._platform_drivers:  # profile binding, exact
                    return self._platform_drivers[spelled]
            for key in ("netmiko_device_type", "name"):
                slug = ((platform.get(key) or {}).get("value") or "").lower()
                if slug in PLATFORM_DRIVERS:
                    return PLATFORM_DRIVERS[slug]
            return None
        except Exception:  # noqa: BLE001 - unverifiable, not fatal
            return None

    def fetch_content(self, storage_id: str) -> str:
        return self._client.object_store.get(identifier=storage_id)
