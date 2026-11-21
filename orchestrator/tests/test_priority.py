"""Plan priority is inherited from the intents whose contracts touch the plan."""

from __future__ import annotations

from autonetops_orchestrator.priority import CONTRACT_DEVICES_QUERY, intent_priority_for


def contract(name: str, intent: tuple[str, str] | None, pe=(), ce=()) -> dict:
    """One IntentRoutingContract edge, shaped as the SoT returns it."""
    def side(names):
        return {"edges": [{"node": {"name": {"value": n}}} for n in names]}

    node = {"name": {"value": name}, "pe_devices": side(pe), "ce_devices": side(ce)}
    if intent is not None:
        intent_name, priority = intent
        node["intent"] = {"node": {"name": {"value": intent_name},
                                   "priority": {"value": priority}}}
    return {"node": node}


class FakeClient:
    def __init__(self, *edges: dict):
        self._edges = list(edges)
        self.calls: list[dict] = []

    def execute_graphql(self, query: str, branch_name: str = "main") -> dict:
        self.calls.append({"query": query, "branch_name": branch_name})
        return {"IntentRoutingContract": {"edges": self._edges}}


CUSTC = contract("custc-ce-to-pe", ("custc-l3vpn-connectivity", "high"),
                 pe=["pe-emea-01", "pe-emea-02"], ce=["ce-custc-01"])
CORE = contract("ibgp-core-rr", ("provider-core-transport", "critical"),
                pe=["core-rr-01"], ce=["pe-emea-01", "pe-emea-02"])
PEERING = contract("inet-peering-emea", ("provider-internet-peering", "high"),
                   pe=["pe-emea-01"], ce=["inet-peer-01"])


def test_query_walks_contract_to_intent_in_one_hop():
    # The contract generic links straight to its intent; the old
    # contract -> policy -> intent grouping hop no longer exists in the SoT
    # schema, so selecting it fails the whole query.
    assert "policy" not in CONTRACT_DEVICES_QUERY
    assert "intent {" in CONTRACT_DEVICES_QUERY


def test_highest_priority_among_touching_contracts_wins():
    client = FakeClient(CUSTC, CORE, PEERING)
    assert intent_priority_for(client, {"pe-emea-01"}) == (
        "critical", ["provider-core-transport"])


def test_contracts_on_other_devices_lend_nothing():
    client = FakeClient(CUSTC, CORE, PEERING)
    assert intent_priority_for(client, {"ce-custc-01"}) == (
        "high", ["custc-l3vpn-connectivity"])


def test_equal_priorities_name_every_intent_once():
    twin = contract("custc-ce-to-pe-backup", ("custc-l3vpn-connectivity", "high"),
                    pe=["pe-emea-01"])
    client = FakeClient(CUSTC, twin, PEERING)
    assert intent_priority_for(client, {"pe-emea-01"}) == (
        "high", ["custc-l3vpn-connectivity", "provider-internet-peering"])


def test_no_touching_contract_defaults_to_medium():
    client = FakeClient(CUSTC, CORE)
    assert intent_priority_for(client, {"unrelated-device"}) == ("medium", [])
    assert intent_priority_for(FakeClient(), {"pe-emea-01"}) == ("medium", [])


def test_low_priority_intent_never_lowers_the_default():
    low = contract("lab-scratch", ("lab-experiments", "low"), pe=["pe-emea-01"])
    assert intent_priority_for(FakeClient(low), {"pe-emea-01"}) == ("medium", [])


def test_reads_the_candidate_branch():
    client = FakeClient(CUSTC)
    intent_priority_for(client, {"pe-emea-01"}, branch="add-site-3")
    assert client.calls[0]["branch_name"] == "add-site-3"
