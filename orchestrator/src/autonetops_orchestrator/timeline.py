"""Timeline evaluation: fit a Plan's stages into change windows.

The planner says in what ORDER the network changes; this module says WHEN.
Stages are scheduled sequentially - a stage may not start before the
previous stage's soak has finished, and every stage must fit inside an
eligible maintenance window for its blast radius and device scope.
"""

from __future__ import annotations

import datetime

from pydantic import BaseModel, Field

from .windows import ChangeWindow, next_slot

# Conservative per-step estimate: snapshot + dry_run + apply + facts on a
# CLI transport. Only used to check window FIT; execution runs as fast as
# the devices allow.
PER_STEP_MINUTES = 3


class StageSchedule(BaseModel):
    stage: str
    window: str | None = None
    starts_at: datetime.datetime | None = None
    ends_by: datetime.datetime | None = None
    soak_until: datetime.datetime | None = None
    devices: list[str] = Field(default_factory=list)
    notes: list[str] = Field(default_factory=list)


class Timeline(BaseModel):
    evaluated_at: datetime.datetime
    feasible: bool = True
    entries: list[StageSchedule] = Field(default_factory=list)
    reasons: list[str] = Field(default_factory=list)

    @property
    def first_start(self) -> datetime.datetime | None:
        return self.entries[0].starts_at if self.entries else None

    @property
    def completes_by(self) -> datetime.datetime | None:
        return self.entries[-1].soak_until if self.entries else None


def evaluate_timeline(
    plan,
    windows: list[ChangeWindow],
    *,
    now: datetime.datetime,
    per_step_minutes: int = PER_STEP_MINUTES,
    horizon_days: int = 14,
) -> Timeline:
    timeline = Timeline(evaluated_at=now)
    blast = plan.blast_radius.classification.value
    cursor = now

    for stage in plan.stages:
        devices = sorted({
            device
            for step in stage.steps
            for device in (step.target.affected_devices or [step.target.control_point])
        })
        need_minutes = max(len(stage.steps) * per_step_minutes, 1)
        slot = next_slot(
            windows, set(devices), blast, cursor,
            need_minutes=need_minutes, horizon_days=horizon_days,
        )
        if slot is None:
            timeline.feasible = False
            timeline.reasons.append(
                f"stage {stage.name!r}: no maintenance window within "
                f"{horizon_days} days admits blast radius {blast!r} for "
                f"devices {', '.join(devices)}"
            )
            timeline.entries.append(StageSchedule(
                stage=stage.name, devices=devices,
                notes=["unschedulable within horizon"],
            ))
            break

        window, start, _end = slot
        ends_by = start + datetime.timedelta(minutes=need_minutes)
        soak_until = ends_by + datetime.timedelta(minutes=stage.gate.soak_minutes)
        notes = []
        if start > cursor:
            notes.append(f"deferred {_human_delta(start - cursor)} to enter {window.name!r}")
        timeline.entries.append(StageSchedule(
            stage=stage.name,
            window=window.name,
            starts_at=start,
            ends_by=ends_by,
            soak_until=soak_until,
            devices=devices,
            notes=notes,
        ))
        cursor = soak_until

    return timeline


def _human_delta(delta: datetime.timedelta) -> str:
    minutes = int(delta.total_seconds() // 60)
    if minutes < 60:
        return f"{minutes}m"
    hours, minutes = divmod(minutes, 60)
    if hours < 48:
        return f"{hours}h{minutes:02d}m"
    days, hours = divmod(hours, 24)
    return f"{days}d{hours}h"
