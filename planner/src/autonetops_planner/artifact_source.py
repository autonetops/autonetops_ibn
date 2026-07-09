"""Artifact sources: where the planner reads rendered artifacts from.

Two implementations:
- StaticArtifactSource: JSON fixture files (tests, offline development).
- InfrahubArtifactSource: live Infrahub via infrahub-sdk (optional dependency).
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Protocol

from .models import DeviceArtifact


class ArtifactSource(Protocol):
    def list_artifacts(self, branch: str) -> list[DeviceArtifact]:
        """Return all rendered artifacts on the given branch."""
        ...


class StaticArtifactSource:
    """Reads artifacts from a JSON fixture: {"<branch>": [DeviceArtifact, ...]}."""

    def __init__(self, path: str | Path):
        self._data = json.loads(Path(path).read_text())

    def list_artifacts(self, branch: str) -> list[DeviceArtifact]:
        if branch not in self._data:
            raise KeyError(f"branch {branch!r} not present in fixture")
        return [DeviceArtifact.model_validate(item) for item in self._data[branch]]


class InfrahubArtifactSource:
    """Reads artifacts from a live Infrahub instance.

    NOTE: query shape not yet verified against a live instance — first
    integration milestone. Requires `pip install autonetops-planner[infrahub]`.
    """

    ARTIFACT_QUERY = """
    query Artifacts {
      CoreArtifact {
        edges {
          node {
            name { value }
            checksum { value }
            storage_id { value }
            definition { node { artifact_name { value } } }
            object {
              node {
                ... on InfraDevice {
                  name { value }
                  platform { node { name { value } } }
                  role { value }
                }
              }
            }
          }
        }
      }
    }
    """

    def __init__(self, address: str, token: str):
        try:
            from infrahub_sdk import InfrahubClientSync
        except ImportError as exc:  # pragma: no cover
            raise RuntimeError(
                "infrahub-sdk is not installed; use "
                "`pip install autonetops-planner[infrahub]`"
            ) from exc
        self._client = InfrahubClientSync(address=address, config={"api_token": token})

    def list_artifacts(self, branch: str) -> list[DeviceArtifact]:  # pragma: no cover
        result = self._client.execute_graphql(query=self.ARTIFACT_QUERY, branch_name=branch)
        artifacts: list[DeviceArtifact] = []
        for edge in result["CoreArtifact"]["edges"]:
            node = edge["node"]
            obj = node["object"]["node"]
            platform = (obj.get("platform") or {}).get("node") or {}
            artifacts.append(
                DeviceArtifact(
                    device=obj["name"]["value"],
                    definition=node["definition"]["node"]["artifact_name"]["value"],
                    checksum=node["checksum"]["value"],
                    storage_id=node["storage_id"]["value"],
                    platform=(platform.get("name") or {}).get("value"),
                    role=(obj.get("role") or {}).get("value"),
                )
            )
        return artifacts
