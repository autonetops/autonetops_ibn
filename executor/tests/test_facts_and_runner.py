"""facts parsing + the shared step runner against the mock driver."""

from __future__ import annotations

import hashlib

from autonetops_executor import parse_bgp_neighbor_states, run_step
from autonetops_planner.models import ContentFormat, RollbackSpec, Step, StepTarget

EOS_SUMMARY = """\
BGP summary information for VRF customer-c
Router identifier 10.255.0.11, local AS number 65000
Neighbor Status Codes: m - Under maintenance
  Neighbor    V AS      MsgRcvd MsgSent InQ OutQ Up/Down  State    PfxRcd PfxAcc
  10.20.0.2   4 65101       35      38    0    0 00:25:52 Estab    2      2
  10.20.1.2   4 65101       12      14    0    0 00:02:11 Active
"""

SRL_NEIGHBORS = """\
+------------+-----------+----------+-------+---------+-------------+--------+
|  Net-Inst  |   Peer    |  Group   | Flags | Peer-AS |    State    | Uptime |
+============+===========+==========+=======+=========+=============+========+
| default    | 10.20.0.1 | to-pe    | S     | 65000   | established | 0d:1h  |
| default    | 10.99.0.1 | to-pe    | S     | 65000   | idle        | -      |
+------------+-----------+----------+-------+---------+-------------+--------+
"""


def test_parse_eos_summary():
    states = parse_bgp_neighbor_states(EOS_SUMMARY)
    assert states == {"10.20.0.2": "established", "10.20.1.2": "active"}


def test_parse_srlinux_table():
    states = parse_bgp_neighbor_states(SRL_NEIGHBORS)
    assert states == {"10.20.0.1": "established", "10.99.0.1": "idle"}


def test_parse_ignores_noise():
    assert parse_bgp_neighbor_states("Router identifier 1.2.3.4, AS 65000\n") == {}


# -- run_step -----------------------------------------------------------------


def _step(content: str, driver: str = "mock") -> Step:
    return Step(
        target=StepTarget(control_point="dev-1"),
        driver=driver,
        platform="mock",
        artifact_definition="device-configuration",
        content_format=ContentFormat.CLI_TEXT,
        checksum_after=hashlib.sha256(content.encode()).hexdigest(),
        rollback=RollbackSpec(strategy="commit_confirmed"),
    )


def test_run_step_applies_and_confirms():
    evidence = []
    outcome = run_step(_step("hostname dev-1\n"), {"initial_config": ""},
                       "hostname dev-1\n", emit=evidence.append)
    assert outcome.status == "applied"
    assert outcome.ok
    operations = [e.operation for e in evidence]
    assert operations == ["snapshot", "dry_run", "apply", "confirm"]


def test_run_step_converged_short_circuits():
    outcome = run_step(_step("same\n"), {"initial_config": "same\n"}, "same\n")
    assert outcome.status == "converged"
    assert outcome.ok


def test_run_step_check_never_applies():
    evidence = []
    outcome = run_step(_step("new\n"), {"initial_config": "old\n"}, "new\n",
                       check=True, emit=evidence.append)
    assert outcome.status == "checked"
    assert "new" in outcome.diff
    assert "apply" not in [e.operation for e in evidence]


def test_run_step_rejects_checksum_mismatch():
    step = _step("expected\n")
    outcome = run_step(step, {}, "tampered\n")
    assert outcome.status == "failed"
    assert not outcome.ok


def test_run_step_skips_unknown_driver():
    records = []
    outcome = run_step(_step("x\n", driver="does-not-exist"), {}, "x\n",
                       emit=records.append)
    assert outcome.status == "skipped"
    assert not outcome.ok
    assert records and records[0]["operation"] == "skip"
