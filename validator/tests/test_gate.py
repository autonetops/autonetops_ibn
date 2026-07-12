"""ExpectationSet parsing + the sessions gate."""

from __future__ import annotations

from autonetops_validator import ExpectationSet, evaluate_sessions, failing_keys

EXPECTATIONS_YAML = """\
apiVersion: expectations.networking.autonetops/v1
kind: ContractExpectations
metadata:
  name: customer-c-edge
spec:
  bgp:
    sessions:
      - device: pe-emea-01
        neighborIp: 10.20.0.2
        neighborDevice: ce-custc-01
        mustBe: {sessionState: established, minUptimeSeconds: 300}
      - device: pe-emea-02
        neighborIp: 10.20.1.2
        neighborDevice: ce-custc-02
        mustBe: {sessionState: established, minUptimeSeconds: 300}
      - device: core-rr-01
        neighborIp: 10.255.0.11
        neighborDevice: pe-emea-01
        mustBe: {sessionState: established, minUptimeSeconds: 300}
"""


def test_parse_expectations():
    exp = ExpectationSet.from_artifacts([EXPECTATIONS_YAML])
    assert len(exp.sessions) == 3
    assert exp.sessions[0].contract == "customer-c-edge"
    assert exp.sessions[0].must_state == "established"


def test_for_devices_scopes():
    exp = ExpectationSet.from_artifacts([EXPECTATIONS_YAML])
    scoped = exp.for_devices({"pe-emea-01"})
    assert [s.device for s in scoped.sessions] == ["pe-emea-01"]


def test_for_devices_include_neighbors():
    # changing ce-custc-01 must pull in the PE-side session that faces it
    exp = ExpectationSet.from_artifacts([EXPECTATIONS_YAML])
    assert not exp.for_devices({"ce-custc-01"}).sessions
    scoped = exp.for_devices({"ce-custc-01"}, include_neighbors=True)
    assert [(s.device, s.neighbor_device) for s in scoped.sessions] == [
        ("pe-emea-01", "ce-custc-01")]


def test_gate_pass_fail_unverifiable():
    exp = ExpectationSet.from_artifacts([EXPECTATIONS_YAML])
    facts = {
        "pe-emea-01": {"bgp_neighbors": {"10.20.0.2": "established"}},
        "pe-emea-02": {"bgp_neighbors": {"10.20.1.2": "active"}},
        "core-rr-01": None,  # no driver / unreachable
    }
    result = evaluate_sessions(exp, facts)
    by_device = {c.device: c.status for c in result.checks}
    assert by_device == {
        "pe-emea-01": "pass",
        "pe-emea-02": "fail",
        "core-rr-01": "unverifiable",
    }
    assert not result.passed  # the fail sinks it; unverifiable alone would not


def test_gate_absent_session_fails():
    exp = ExpectationSet.from_artifacts([EXPECTATIONS_YAML]).for_devices({"pe-emea-01"})
    result = evaluate_sessions(exp, {"pe-emea-01": {"bgp_neighbors": {}}})
    assert result.checks[0].status == "fail"
    assert result.checks[0].actual == "absent"


def test_gate_blocks_regressions_not_history():
    exp = ExpectationSet.from_artifacts([EXPECTATIONS_YAML]).for_devices(
        {"pe-emea-01", "pe-emea-02"})
    down = {
        "pe-emea-01": {"bgp_neighbors": {"10.20.0.2": "established"}},
        "pe-emea-02": {"bgp_neighbors": {"10.20.1.2": "active"}},
    }
    baseline = failing_keys(evaluate_sessions(exp, down))
    assert baseline == {("customer-c-edge", "pe-emea-02", "10.20.1.2")}

    # same failure after the change: pre-existing, gate passes
    after = evaluate_sessions(exp, down, baseline=baseline)
    by_device = {c.device: c.status for c in after.checks}
    assert by_device["pe-emea-02"] == "pre_existing"
    assert after.passed

    # a NEW failure is a regression and blocks, baseline or not
    regressed = {
        "pe-emea-01": {"bgp_neighbors": {"10.20.0.2": "idle"}},
        "pe-emea-02": {"bgp_neighbors": {"10.20.1.2": "active"}},
    }
    result = evaluate_sessions(exp, regressed, baseline=baseline)
    assert not result.passed
    assert {c.status for c in result.checks} == {"fail", "pre_existing"}


def test_gate_unverifiable_does_not_pass_silently():
    exp = ExpectationSet.from_artifacts([EXPECTATIONS_YAML]).for_devices({"core-rr-01"})
    result = evaluate_sessions(exp, {})
    assert result.passed  # nothing failed...
    assert result.checks[0].status == "unverifiable"  # ...but it is on the record
    assert "unverifiable" in result.summary
