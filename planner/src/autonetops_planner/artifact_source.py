"""Artifact sources: where the planner reads rendered artifacts from.

Two implementations:
- StaticArtifactSource: JSON fixture files (tests, offline development).
- InfrahubArtifactSource: live Infrahub via infrahub-sdk (optional dependency).
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Protocol

from .models import ContentFormat, TargetArtifact

# Which artifact definitions the planner treats as deployable device config,
# and what their bytes are. Everything else Infrahub renders (expectations,
# alert rules, dashboards) flows to its own consumer, not to the executor.
DEFINITION_FORMATS: dict[str, ContentFormat] = {
    "device-configuration": ContentFormat.CLI_TEXT,
    # future compilers (ADR-0012): "device-openconfig": ContentFormat.OPENCONFIG_JSON,
}


class ArtifactSource(Protocol):
    def list_artifacts(self, branch: str) -> list[TargetArtifact]:
        """Return all rendered artifacts on the given branch."""
        ...


class StaticArtifactSource:
    """Reads artifacts from a JSON fixture: {"<branch>": [TargetArtifact, ...]}.

    Optionally serves artifact content from a sibling mapping:
    {"<branch>__content": {"<target>/<definition>": "<text>"}} or from a
    directory of files via content_dir (``<target>.cfg``).
    """

    def __init__(self, path: str | Path, content_dir: str | Path | None = None):
        self._data = json.loads(Path(path).read_text())
        self._content_dir = Path(content_dir) if content_dir else None

    def list_artifacts(self, branch: str) -> list[TargetArtifact]:
        if branch not in self._data:
            raise KeyError(f"branch {branch!r} not present in fixture")
        return [TargetArtifact.model_validate(item) for item in self._data[branch]]

    def fetch_content(self, artifact: TargetArtifact, branch: str | None = None) -> str:
        if branch is not None:
            table = self._data.get(f"{branch}__content") or {}
            key = f"{artifact.target}/{artifact.definition}"
            if key in table:
                return table[key]
        if self._content_dir is not None:
            path = self._content_dir / f"{artifact.target}.cfg"
            if path.exists():
                return path.read_text()
        raise KeyError(f"no content for {artifact.target}/{artifact.definition}")


class InfrahubArtifactSource:
    """Reads artifact listings AND content from a live Infrahub instance.

    Verified against Infrahub 1.10: artifact targets are polymorphic
    (devices, contracts, tenants...), so the object is matched loosely -
    devices contribute platform/role, anything else just its display label.
    Content is fetched from object storage by storage_id.

    Requires `pip install autonetops-planner[infrahub]`.
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
                __typename
                display_label
                ... on DcimGenericDevice {
                  name { value }
                  role { value }
                  platform { node { name { value } } }
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
            from infrahub_sdk import Config, InfrahubClientSync
        except ImportError as exc:  # pragma: no cover
            raise RuntimeError(
                "infrahub-sdk is not installed; use "
                "`pip install autonetops-planner[infrahub]`"
            ) from exc
        self._client = InfrahubClientSync(address=address, config=Config(api_token=token))

    def list_artifacts(self, branch: str) -> list[TargetArtifact]:
        # TODO(ADR-0011): map control-point kind + managed devices once the
        # control_point schema lands in infrahub/schemas/; until then every
        # Infrahub artifact target is treated as a direct device.
        result = self._client.execute_graphql(query=self.ARTIFACT_QUERY, branch_name=branch)
        artifacts: list[TargetArtifact] = []
        for edge in result["CoreArtifact"]["edges"]:
            node = edge["node"]
            definition = node["definition"]["node"]["artifact_name"]["value"]
            obj = node["object"]["node"]
            name = (obj.get("name") or {}).get("value") or obj["display_label"]
            platform = ((obj.get("platform") or {}).get("node") or {})
            artifacts.append(
                TargetArtifact(
                    target=name,
                    definition=definition,
                    checksum=node["checksum"]["value"],
                    storage_id=node["storage_id"]["value"],
                    platform=(platform.get("name") or {}).get("value"),
                    role=((obj.get("role") or {}) or {}).get("value"),
                    content_format=DEFINITION_FORMATS.get(
                        definition, ContentFormat.CLI_TEXT
                    ),
                )
            )
        return artifacts

    def fetch_content(self, artifact: TargetArtifact, branch: str | None = None) -> str:
        """Artifact bytes from Infrahub object storage, by storage_id."""
        if not artifact.storage_id:
            raise KeyError(f"artifact {artifact.target}/{artifact.definition} has no storage_id")
        return self._client.object_store.get(identifier=artifact.storage_id)
