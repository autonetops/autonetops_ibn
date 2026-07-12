"""Pre-approved change classes (ADR-0014): golden match/refuse tests.

Every class in planner/policies/change_classes.yaml must have both kinds of
test here: a diff it matches AND diffs it must refuse — the class definition
is only reviewable if its boundary is pinned.
"""

from pathlib import Path

from autonetops_planner.change_classes import (
    ChangeClass,
    ChangeClassPolicy,
    classify_changes,
    load_change_classes,
)
from autonetops_planner.models import (
    BlastRadiusClass,
    ChangeItem,
    ChangeSet,
    ContentFormat,
    PreApproval,
)

POLICIES_DIR = Path(__file__).parents[1] / "policies"

BEFORE = """interface eth1
 description old uplink
 mtu 9000
interface eth2
 description peering
"""
AFTER_DESC_ONLY = BEFORE.replace("old uplink", "new uplink to spine-2")
AFTER_MIXED = AFTER_DESC_ONLY.replace("mtu 9000", "mtu 9100")

DESCRIPTIONS = ChangeClass(
    name="interface-descriptions",
    artifact_definitions=["device-configuration"],
    cli_text_allow=[r"^\s*interface \S+$", r"^\s*description .+$"],
    model_paths_allow=["/interfaces/interface[*]/config/description"],
    max_blast_radius=BlastRadiusClass.HIGH,
)
POLICY = ChangeClassPolicy(version="1", classes=[DESCRIPTIONS])


def _item(target="pe-1", **overrides) -> ChangeItem:
    fields = dict(
        target=target,
        definition="device-configuration",
        checksum_before="before",
        checksum_after="after",
        content_format=ContentFormat.CLI_TEXT,
    )
    fields.update(overrides)
    return ChangeItem(**fields)


def _changeset(*items) -> ChangeSet:
    return ChangeSet(base_branch="main", candidate_branch="chg", items=list(items))


def _content(mapping):
    return lambda item: mapping.get(item.target)


def test_description_only_diff_matches():
    result = classify_changes(
        _changeset(_item()), BlastRadiusClass.MODERATE, POLICY,
        _content({"pe-1": (BEFORE, AFTER_DESC_ONLY)}),
    )
    assert result is not None
    assert result.change_class.name == "interface-descriptions"
    assert result.policy_version == "1"


def test_one_foreign_line_refuses_the_item():
    # a description change bundled with an MTU change must NOT match
    result = classify_changes(
        _changeset(_item()), BlastRadiusClass.MODERATE, POLICY,
        _content({"pe-1": (BEFORE, AFTER_MIXED)}),
    )
    assert result is None


def test_one_unmatched_item_refuses_the_whole_changeset():
    result = classify_changes(
        _changeset(_item("pe-1"), _item("pe-2")), BlastRadiusClass.MODERATE, POLICY,
        _content({"pe-1": (BEFORE, AFTER_DESC_ONLY),
                  "pe-2": (BEFORE, AFTER_MIXED)}),
    )
    assert result is None


def test_added_artifacts_are_never_routine():
    added = _item(checksum_before=None)
    result = classify_changes(
        _changeset(added), BlastRadiusClass.LOW, POLICY,
        _content({"pe-1": ("", AFTER_DESC_ONLY)}),
    )
    assert result is None


def test_removals_disqualify_the_whole_changeset():
    removed = _item("old-rr", checksum_after=None)
    result = classify_changes(
        _changeset(_item("pe-1"), removed), BlastRadiusClass.MODERATE, POLICY,
        _content({"pe-1": (BEFORE, AFTER_DESC_ONLY)}),
    )
    assert result is None


def test_blast_ceiling_is_enforced():
    ceiling_moderate = ChangeClassPolicy(version="1", classes=[
        ChangeClass(
            name="descriptions-small",
            cli_text_allow=DESCRIPTIONS.cli_text_allow,
            max_blast_radius=BlastRadiusClass.MODERATE,
        )
    ])
    content = _content({"pe-1": (BEFORE, AFTER_DESC_ONLY)})
    assert classify_changes(
        _changeset(_item()), BlastRadiusClass.HIGH, ceiling_moderate, content
    ) is None
    assert classify_changes(
        _changeset(_item()), BlastRadiusClass.MODERATE, ceiling_moderate, content
    ) is not None


def test_disabled_class_never_matches():
    disabled = ChangeClassPolicy(version="1", classes=[
        ChangeClass(name="off", enabled=False,
                    cli_text_allow=DESCRIPTIONS.cli_text_allow,
                    max_blast_radius=BlastRadiusClass.HIGH),
    ])
    result = classify_changes(
        _changeset(_item()), BlastRadiusClass.LOW, disabled,
        _content({"pe-1": (BEFORE, AFTER_DESC_ONLY)}),
    )
    assert result is None


def test_unfetchable_content_fails_closed():
    assert classify_changes(
        _changeset(_item()), BlastRadiusClass.LOW, POLICY, _content({})
    ) is None


def test_formats_without_matchers_fail_closed():
    xml_item = _item(content_format=ContentFormat.IETF_XML)
    result = classify_changes(
        _changeset(xml_item), BlastRadiusClass.LOW, POLICY,
        _content({"pe-1": ("<a/>", "<b/>")}),
    )
    assert result is None


def test_openconfig_paths_match_and_refuse():
    before = """{"interfaces": {"interface": [
        {"name": "eth1", "config": {"description": "old", "mtu": 9000}},
        {"name": "eth2", "config": {"description": "peer"}}]}}"""
    desc_only = before.replace('"old"', '"new uplink"')
    mixed = desc_only.replace("9000", "9100")
    added_interface = desc_only.replace(
        "]}}", ', {"name": "eth3", "config": {"description": "x"}}]}}'
    )
    item = _item(content_format=ContentFormat.OPENCONFIG_JSON)

    def run(after):
        return classify_changes(
            _changeset(item), BlastRadiusClass.LOW, POLICY,
            _content({"pe-1": (before, after)}),
        )

    assert run(desc_only) is not None
    assert run(mixed) is None            # mtu path is not allowed
    assert run(added_interface) is None  # a new interface is not a description


def test_shipped_policy_file_loads_and_pins_the_descriptions_class():
    """policy-validate seed: the committed YAML must parse, compile, and
    behave exactly like the class pinned above."""
    policy = load_change_classes(POLICIES_DIR)
    assert policy.version == "1"
    by_name = {c.name: c for c in policy.classes}
    shipped = by_name["interface-descriptions"]
    assert shipped.enabled
    assert shipped.artifact_definitions == ["device-configuration"]
    assert shipped.max_blast_radius == BlastRadiusClass.HIGH
    assert shipped.max_plans_per_hour == 10

    result = classify_changes(
        _changeset(_item()), BlastRadiusClass.HIGH, policy,
        _content({"pe-1": (BEFORE, AFTER_DESC_ONLY)}),
    )
    assert result is not None and result.change_class.name == "interface-descriptions"
    assert classify_changes(
        _changeset(_item()), BlastRadiusClass.HIGH, policy,
        _content({"pe-1": (BEFORE, AFTER_MIXED)}),
    ) is None


def test_no_policy_dir_means_no_pre_approval():
    assert load_change_classes(None).classes == []


def test_pre_approval_is_metadata_not_identity():
    """The pre_approved annotation must not perturb the content-addressed id
    and must serialize with the 'class' alias."""
    from autonetops_planner.blast_radius import compute_blast_radius
    from autonetops_planner.plan_builder import build_plan
    from autonetops_planner.policies import load_canary_strategies, select_strategy

    changes = _changeset(_item(platform="junos"))
    strategy = select_strategy(
        load_canary_strategies(None), compute_blast_radius(changes).classification
    )
    plain = build_plan(changes, strategy)
    approved = build_plan(
        changes, strategy,
        pre_approved=PreApproval(class_name="interface-descriptions",
                                 policy_version="1"),
    )
    assert plain.id == approved.id
    dumped = approved.model_dump(mode="json", by_alias=True)
    assert dumped["policy_evaluation"]["pre_approved"] == {
        "class": "interface-descriptions", "policy_version": "1"}
    assert plain.model_dump(mode="json")["policy_evaluation"]["pre_approved"] is None
