"""report.yaml persistence + SoT feedback: the closed loop's last arrow."""

from __future__ import annotations

import datetime

import yaml

from autonetops_orchestrator.dispatch import DispatchReport, write_report
from autonetops_orchestrator.feedback import record_dispatch
from autonetops_orchestrator.strategy import Decision

from test_dispatch import _dispatch, _plan  # reuse the harness

UTC = datetime.timezone.utc


def test_status_derivation():
    base = dict(plan_id="plan-x")
    assert DispatchReport(**base).status == "succeeded"
    assert DispatchReport(**base, check_mode=True).status == "checked"
    assert DispatchReport(**base, failures=1).status == "failed"
    assert DispatchReport(**base, aborted="gate failed").status == "aborted"
    assert DispatchReport(**base, waiting=True, failures=1).status == "waiting"


def test_dispatch_stamps_lifecycle_timestamps():
    report, _, _ = _dispatch(_plan())
    assert report.started_at is not None and report.finished_at is not None
    assert report.finished_at >= report.started_at
    # timestamps survive the abort path too (finally-block, not happy path)
    decision = Decision(mode="needs_approval", approvals_required=["lead"])
    aborted, _, _ = _dispatch(_plan(), decision=decision)
    assert aborted.aborted and aborted.finished_at is not None


def test_write_report_roundtrips(tmp_path):
    report, _, _ = _dispatch(_plan())
    path = write_report(tmp_path, report)
    assert path.name == "report.yaml"
    loaded = yaml.safe_load(path.read_text())
    assert loaded["plan_id"] == report.plan_id
    assert loaded["status"] == "succeeded"  # computed field is serialized
    assert [s["name"] for s in loaded["stages"]] == ["stage-1", "stage-2"]
    assert loaded["stages"][0]["outcomes"] == {"pe-1": "applied"}


class _FakeClient:
    def __init__(self, fail: bool = False):
        self.fail = fail
        self.calls: list[dict] = []

    def execute_graphql(self, query: str, variables: dict):
        if self.fail:
            raise RuntimeError("Unknown type OpsPlanRecord")  # schema not loaded
        self.calls.append(variables)
        return {"OpsPlanRecordUpsert": {"ok": True, "object": {"id": "rec-1"}}}


def _record(client) -> tuple[bool, list, list]:
    report, _, _ = _dispatch(_plan())
    evidence: list = []
    log: list[str] = []
    ok = record_dispatch(client, _plan(), Decision(mode="immediate"), report,
                         emit=evidence.append, echo=log.append)
    return ok, evidence, log


def test_feedback_upserts_plan_record():
    client = _FakeClient()
    ok, evidence, _ = _record(client)
    assert ok
    variables = client.calls[0]
    assert variables["status"] == "succeeded"
    assert variables["blast_radius"] == "low"
    assert variables["device_count"] == 2
    assert "stage-1[pe-1:applied;gate=pass]" in variables["detail"]
    assert evidence[-1]["operation"] == "sot_feedback"
    assert evidence[-1]["success"] is True


def test_feedback_degrades_loudly_without_schema():
    """A SoT without OpsPlanRecord must never turn a green dispatch red."""
    ok, evidence, log = _record(_FakeClient(fail=True))
    assert ok is False
    assert evidence[-1]["success"] is False
    assert any("SKIPPED" in line for line in log)
