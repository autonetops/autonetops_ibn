"""Close the loop: write the dispatch outcome back into the SoT.

The architecture's feedback arrow (README "closed loop") made real: after a
dispatch, an ``OpsPlanRecord`` node is upserted in Infrahub so compliance
state lives next to the intent that caused the change - not only in
report.yaml and evidence.jsonl on one operator's disk.

Schema: infrahub/schemas/ops_plan_record.yml (load with
``infrahubctl schema load`` or repo sync). Feature-detected: a SoT without
the kind degrades to a loud skip, never a failed dispatch - feedback must
not be able to break the rollout it describes.
"""

from __future__ import annotations

from typing import Any, Callable

from .dispatch import DispatchReport
from .strategy import Decision

UPSERT_MUTATION = """
mutation RecordPlan(
  $plan_id: String!, $status: String!, $mode: String!,
  $blast_radius: String!, $device_count: BigInt!,
  $base_branch: String!, $candidate_branch: String!,
  $dispatched_at: String!, $emergency_override: Boolean!,
  $detail: String!
) {
  OpsPlanRecordUpsert(data: {
    plan_id: {value: $plan_id},
    status: {value: $status},
    mode: {value: $mode},
    blast_radius: {value: $blast_radius},
    device_count: {value: $device_count},
    base_branch: {value: $base_branch},
    candidate_branch: {value: $candidate_branch},
    dispatched_at: {value: $dispatched_at},
    emergency_override: {value: $emergency_override},
    detail: {value: $detail}
  }) {
    ok
    object { id }
  }
}
"""


def _detail_line(report: DispatchReport) -> str:
    """One human-scannable line: per-stage outcomes + gate verdicts."""
    parts = []
    for stage in report.stages:
        outcomes = ",".join(f"{t}:{s}" for t, s in stage.outcomes.items()) or "-"
        gate = ("gate=pass" if stage.gate_passed
                else "gate=FAIL" if stage.gate_passed is False else "gate=n/a")
        parts.append(f"{stage.name}[{outcomes};{gate}]")
    if report.aborted:
        parts.append(f"aborted: {report.aborted}")
    return " ".join(parts)[:2000] or "no stages executed"


def record_dispatch(
    client,
    plan,
    decision: Decision,
    report: DispatchReport,
    *,
    emit: Callable[[Any], None],
    echo: Callable[[str], None],
) -> bool:
    """Upsert the OpsPlanRecord for this dispatch; True when the SoT took it.

    Never raises: the rollout outcome is already decided by the time this
    runs, and a feedback failure must not turn a green dispatch red. It is
    recorded in evidence either way."""
    variables = {
        "plan_id": plan.id,
        "status": report.status,
        "mode": decision.mode,
        "blast_radius": plan.blast_radius.classification.value,
        "device_count": plan.blast_radius.device_count,
        "base_branch": plan.source.base_branch,
        "candidate_branch": plan.source.candidate_branch,
        "dispatched_at": (report.finished_at.isoformat()
                          if report.finished_at else ""),
        "emergency_override": decision.emergency_override,
        "detail": _detail_line(report),
    }
    try:
        result = client.execute_graphql(query=UPSERT_MUTATION, variables=variables)
        ok = bool(result["OpsPlanRecordUpsert"]["ok"])
        emit({"operation": "sot_feedback", "target": plan.id, "success": ok,
              "detail": {"status": report.status,
                         "record_id": result["OpsPlanRecordUpsert"]["object"]["id"]}})
        echo(f"SoT feedback: OpsPlanRecord {plan.id} -> {report.status}")
        return ok
    except Exception as exc:  # noqa: BLE001 - feedback must not break dispatch
        emit({"operation": "sot_feedback", "target": plan.id, "success": False,
              "detail": {"error": str(exc)[:400], "status": report.status}})
        echo("SoT feedback SKIPPED (is infrahub/schemas/ops_plan_record.yml "
             f"loaded?): {str(exc)[:160]}")
        return False
