"""RenderedArtifactSource: rendered artifacts straight from the SoT repo.

Infrahub's own artifact store only refreshes when the Git repository sync
runs; the orchestrator cannot depend on that timing to see a branch. So it
renders exactly the way the server would: the branch's data through the
repo's own GraphQL queries and transform classes, in-process. Same query,
same renderer, same bytes - just without waiting for a sync.

Implements the planner's ArtifactSource protocol, so diff_artifacts() and
build_plan() consume it unchanged. Rendered content is kept in memory and
persisted next to the plan, becoming the checksum-verified payload the
dispatcher pushes.
"""

from __future__ import annotations

import asyncio
import hashlib
import importlib.util
import sys
from pathlib import Path

from autonetops_planner.models import ContentFormat, TargetArtifact

DEVICES_QUERY = """
query Devices {
  DcimDevice {
    edges {
      node {
        name { value }
        role { value }
        platform { node { name { value } } }
      }
    }
  }
}
"""

CONTRACTS_QUERY = """
query Contracts {
  IntentRoutingContract {
    edges { node { name { value } } }
  }
}
"""


def _load_class(repo: Path, file_path: str, class_name: str):
    """Import a transform class from the SoT repo checkout."""
    path = repo / file_path
    module_name = f"_sot_{path.stem}"
    if module_name in sys.modules:
        return getattr(sys.modules[module_name], class_name)
    spec = importlib.util.spec_from_file_location(module_name, path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[module_name] = module
    spec.loader.exec_module(module)
    return getattr(module, class_name)


def _render(transform_cls, data) -> str:
    # The transform's transform() is a pure function of the query result;
    # skip the SDK constructor (it demands a live client this render
    # deliberately does not need).
    instance = transform_cls.__new__(transform_cls)
    return asyncio.run(instance.transform(data))


class RenderedArtifactSource:
    """Render device-configuration (and contract-expectations) per branch."""

    definition = "device-configuration"

    def __init__(self, client, repo: str | Path):
        self._client = client
        self._repo = Path(repo)
        self._content: dict[tuple[str, str], str] = {}  # (branch, target) -> text

    def _query_text(self, name: str) -> str:
        return (self._repo / "queries" / f"{name}.gql").read_text()

    # -- ArtifactSource protocol ----------------------------------------------

    def list_artifacts(self, branch: str) -> list[TargetArtifact]:
        transform_cls = _load_class(
            self._repo, "transforms/device_config.py", "DeviceConfigTransform"
        )
        query = self._query_text("device_config")
        devices = self._client.execute_graphql(
            query=DEVICES_QUERY, branch_name=branch
        )["DcimDevice"]["edges"]

        artifacts: list[TargetArtifact] = []
        for edge in devices:
            node = edge["node"]
            name = node["name"]["value"]
            platform = ((node.get("platform") or {}).get("node") or {})
            data = self._client.execute_graphql(
                query=query, variables={"device": name}, branch_name=branch
            )
            content = _render(transform_cls, data)
            self._content[(branch, name)] = content
            artifacts.append(TargetArtifact(
                target=name,
                definition=self.definition,
                checksum=hashlib.sha256(content.encode()).hexdigest(),
                platform=(platform.get("name") or {}).get("value"),
                role=(node.get("role") or {}).get("value"),
                content_format=ContentFormat.CLI_TEXT,
            ))
        return artifacts

    def fetch_content(self, artifact: TargetArtifact, branch: str | None = None) -> str:
        key = (branch, artifact.target)
        if key not in self._content:
            raise KeyError(f"no rendered content for {artifact.target!r} on {branch!r}")
        return self._content[key]

    # -- expectations (validator input) ---------------------------------------

    def render_expectations(self, branch: str) -> dict[str, str]:
        """contract name -> rendered ContractExpectations YAML."""
        transform_cls = _load_class(
            self._repo, "transforms/contract_expectations.py",
            "ContractExpectationsTransform",
        )
        query = self._query_text("contract_expectations")
        contracts = self._client.execute_graphql(
            query=CONTRACTS_QUERY, branch_name=branch
        )["IntentRoutingContract"]["edges"]

        rendered: dict[str, str] = {}
        for edge in contracts:
            name = edge["node"]["name"]["value"]
            data = self._client.execute_graphql(
                query=query, variables={"contract": name}, branch_name=branch
            )
            rendered[name] = _render(transform_cls, data)
        return rendered
