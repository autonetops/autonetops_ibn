"""Diff two branches' artifact listings into a ChangeSet."""

from __future__ import annotations

from .models import ChangeItem, ChangeSet, DeviceArtifact


def _index(artifacts: list[DeviceArtifact]) -> dict[tuple[str, str], DeviceArtifact]:
    return {(a.device, a.definition): a for a in artifacts}


def diff_artifacts(
    base: list[DeviceArtifact],
    candidate: list[DeviceArtifact],
    base_branch: str,
    candidate_branch: str,
) -> ChangeSet:
    base_idx = _index(base)
    cand_idx = _index(candidate)
    items: list[ChangeItem] = []

    for key in sorted(base_idx.keys() | cand_idx.keys()):
        before, after = base_idx.get(key), cand_idx.get(key)
        if before and after and before.checksum == after.checksum:
            continue
        meta = after or before
        assert meta is not None
        items.append(
            ChangeItem(
                device=key[0],
                definition=key[1],
                checksum_before=before.checksum if before else None,
                checksum_after=after.checksum if after else None,
                storage_id_after=after.storage_id if after else None,
                platform=meta.platform,
                role=meta.role,
                region=meta.region,
            )
        )

    return ChangeSet(base_branch=base_branch, candidate_branch=candidate_branch, items=items)
