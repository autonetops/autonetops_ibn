"""Blast radius computation and classification.

Thresholds are deliberately conservative defaults; they will move into
planner/policies/ once the policy schema settles.
"""

from __future__ import annotations

from dataclasses import dataclass

from .models import BlastRadius, BlastRadiusClass, ChangeSet


@dataclass(frozen=True)
class Thresholds:
    low_max_devices: int = 2
    high_min_devices: int = 10
    high_min_regions: int = 2


def compute_blast_radius(changes: ChangeSet, thresholds: Thresholds = Thresholds()) -> BlastRadius:
    devices = sorted({i.device for i in changes.deployable})
    roles = sorted({i.role for i in changes.deployable if i.role})
    regions = sorted({i.region for i in changes.deployable if i.region})

    if len(devices) >= thresholds.high_min_devices or len(regions) >= thresholds.high_min_regions:
        classification = BlastRadiusClass.HIGH
    elif len(devices) <= thresholds.low_max_devices:
        classification = BlastRadiusClass.LOW
    else:
        classification = BlastRadiusClass.MODERATE

    return BlastRadius(
        classification=classification,
        device_count=len(devices),
        devices=devices,
        roles=roles,
        regions=regions,
    )
