"""Artifact sources: where the planner reads rendered artifacts from.

Two implementations:
- StaticArtifactSource: JSON fixture files (tests, offline development).
- InfrahubArtifactSource: live Infrahub via infrahub-sdk (optional dependency).

The Infrahub query is rendered from the profile's SoT binding (ADR-0016):
the customer declares their device kind and the attribute/relationship
paths for role, platform and region, and the engine builds the inline
fragment from them — no per-customer query code.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Protocol

from .models import ContentFormat, TargetArtifact
from .profile import SotBinding

# Which artifact definitions the planner treats as deployable device config,
# and what their bytes are, when no profile binds them (legacy/builtin
# fallback — packs/baseline/profile.yaml mirrors this). Everything else
# Infrahub renders (expectations, alert rules, dashboards) flows to its own
# consumer, not to the executor.
DEFINITION_FORMATS: dict[str, ContentFormat] = {
    "device-configuration": ContentFormat.CLI_TEXT,
    # future compilers (ADR-0012): "device-openconfig": ContentFormat.OPENCONFIG_JSON,
}


class ArtifactSource(Protocol):
    def list_artifacts(self, branch: str) -> list[TargetArtifact]:
        """Return all rendered artifacts on the given branch."""
        ...

    def fetch_content(self, artifact: TargetArtifact, branch: str | None = None) -> str:
        """Return the artifact's bytes (change-class matching, bundling)."""
        ...


class UnknownArtifactDefinition(KeyError):
    """A strict profile refuses to guess an artifact's content format."""


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


def _render_path(path: str) -> str:
    """A SoT binding path as a GraphQL selection. Exactly two shapes
    (validated at pack load): ``attr__value`` and ``rel__node__attr__value``."""
    parts = path.split("__")
    if len(parts) == 2:
        return f"{parts[0]} {{ value }}"
    return f"{parts[0]} {{ node {{ {parts[2]} {{ value }} }} }}"


def _walk_path(obj: dict, path: str):
    """Read the value a rendered path produced from the response object."""
    parts = path.split("__")
    if len(parts) == 2:
        return ((obj.get(parts[0]) or {}) or {}).get("value")
    node = ((obj.get(parts[0]) or {}).get("node") or {})
    return ((node.get(parts[2]) or {}) or {}).get("value")


class InfrahubArtifactSource:
    """Reads artifact listings AND content from a live Infrahub instance.

    Verified against Infrahub 1.10: artifact targets are polymorphic
    (devices, contracts, tenants...), so the object is matched loosely -
    devices contribute role/platform/region via the profile's SoT binding
    paths, anything else just its display label. Content is fetched from
    object storage by storage_id.

    Requires `pip install autonetops-planner[infrahub]`.
    """

    ARTIFACT_QUERY_TEMPLATE = """
    query Artifacts {{
      CoreArtifact {{
        edges {{
          node {{
            name {{ value }}
            checksum {{ value }}
            storage_id {{ value }}
            definition {{ node {{ artifact_name {{ value }} }} }}
            object {{
              node {{
                __typename
                display_label
                ... on {device_kind} {{
                  name {{ value }}
                  {selections}
                }}
              }}
            }}
          }}
        }}
      }}
    }}
    """

    def __init__(
        self,
        address: str,
        token: str,
        *,
        sot: SotBinding | None = None,
        definition_formats: dict[str, ContentFormat] | None = None,
        strict: bool = False,
    ):
        try:
            from infrahub_sdk import Config, InfrahubClientSync
        except ImportError as exc:  # pragma: no cover
            raise RuntimeError(
                "infrahub-sdk is not installed; use "
                "`pip install autonetops-planner[infrahub]`"
            ) from exc
        self._client = InfrahubClientSync(address=address, config=Config(api_token=token))
        self._sot = sot or SotBinding()
        self._definition_formats = (
            definition_formats if definition_formats is not None else DEFINITION_FORMATS
        )
        self._strict = strict

    @property
    def query(self) -> str:
        sot = self._sot
        paths = [sot.role_path, sot.platform_path]
        if sot.region_path:
            paths.append(sot.region_path)
        selections = "\n                  ".join(_render_path(p) for p in paths)
        return self.ARTIFACT_QUERY_TEMPLATE.format(
            device_kind=sot.device_kind, selections=selections
        )

    def _format_for(self, definition: str) -> ContentFormat:
        try:
            return self._definition_formats[definition]
        except KeyError:
            if self._strict:
                raise UnknownArtifactDefinition(
                    f"artifact definition {definition!r} is not bound in the "
                    f"profile's artifacts section (strict profile: no guessed "
                    f"content format)"
                ) from None
            return ContentFormat.CLI_TEXT

    def list_artifacts(self, branch: str) -> list[TargetArtifact]:
        # TODO(ADR-0011): map control-point kind + managed devices once the
        # control_point schema lands in infrahub/schemas/; until then every
        # Infrahub artifact target is treated as a direct device.
        result = self._client.execute_graphql(query=self.query, branch_name=branch)
        sot = self._sot
        artifacts: list[TargetArtifact] = []
        for edge in result["CoreArtifact"]["edges"]:
            node = edge["node"]
            definition = node["definition"]["node"]["artifact_name"]["value"]
            obj = node["object"]["node"]
            name = (obj.get("name") or {}).get("value") or obj["display_label"]
            artifacts.append(
                TargetArtifact(
                    target=name,
                    definition=definition,
                    checksum=node["checksum"]["value"],
                    storage_id=node["storage_id"]["value"],
                    platform=_walk_path(obj, sot.platform_path),
                    role=_walk_path(obj, sot.role_path),
                    region=(
                        _walk_path(obj, sot.region_path) if sot.region_path else None
                    ),
                    content_format=self._format_for(definition),
                )
            )
        return artifacts

    def fetch_content(self, artifact: TargetArtifact, branch: str | None = None) -> str:
        """Artifact bytes from Infrahub object storage, by storage_id."""
        if not artifact.storage_id:
            raise KeyError(f"artifact {artifact.target}/{artifact.definition} has no storage_id")
        return self._client.object_store.get(identifier=artifact.storage_id)
