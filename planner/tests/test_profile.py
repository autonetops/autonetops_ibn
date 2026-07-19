"""Intent profile (ADR-0016) tests: merge rules, checksum identity, the
closed-vocabulary gates, the builtin==legacy golden guarantee, and the
zero-baseline-change-classes pin."""

from pathlib import Path

import pytest
import yaml

from autonetops_planner.artifact_source import DEFINITION_FORMATS, StaticArtifactSource
from autonetops_planner.blast_radius import Thresholds, compute_blast_radius
from autonetops_planner.diffing import diff_artifacts
from autonetops_planner.models import BlastRadiusClass
from autonetops_planner.plan_builder import (
    PLATFORM_DRIVERS,
    PLATFORM_ROLLBACK,
    DEFAULT_ABORT_CRITERIA,
    PlanBuildError,
    build_plan,
)
from autonetops_planner.policies import (
    DEFAULT_DELIVERY_PREFERENCES,
    DEFAULT_STRATEGIES,
    select_strategy,
)
from autonetops_planner.profile import (
    ProfileError,
    load_profile,
)

FIXTURE = Path(__file__).parent / "fixtures" / "artifacts.json"
REFERENCE_PACK = Path(__file__).parents[1] / "policies"


@pytest.fixture()
def changeset():
    source = StaticArtifactSource(FIXTURE)
    return diff_artifacts(
        source.list_artifacts("main"),
        source.list_artifacts("add-customer-c"),
        "main",
        "add-customer-c",
    )


def write_pack(tmp_path: Path, profile: dict, **files: str) -> Path:
    pack = tmp_path / "pack"
    pack.mkdir(parents=True, exist_ok=True)
    (pack / "profile.yaml").write_text(yaml.safe_dump(profile))
    for name, content in files.items():
        (pack / name.replace("__", ".")).write_text(content)
    return pack


def minimal_pack_doc(**overrides) -> dict:
    doc = {
        "profile_version": 1,
        "meta": {"tenant": "acme", "name": "acme-prod", "version": "1.0.0"},
        "extends": "builtin:baseline",
    }
    doc.update(overrides)
    return doc


# -- builtin:baseline --------------------------------------------------------


def test_builtin_baseline_loads_with_provenance():
    profile = load_profile(None)
    assert profile.ref.source == "builtin"
    assert profile.ref.tenant == "_platform"
    assert profile.ref.name == "baseline"
    assert profile.ref.checksum.startswith("sha256:")
    assert profile.strict is False
    assert profile.load_assumptions == []


def test_baseline_pack_matches_builtin_constants():
    """The shipped pack IS the old constants: pinned equal so neither can
    drift from the other (replaces the deleted delivery-prefs drift test
    with a stronger, whole-pack pin)."""
    profile = load_profile(None)
    assert profile.thresholds == Thresholds()
    assert profile.abort_criteria == DEFAULT_ABORT_CRITERIA
    assert profile.definition_formats == DEFINITION_FORMATS
    assert profile.delivery_preferences["platforms"] == (
        DEFAULT_DELIVERY_PREFERENCES["platforms"]
    )
    by_name = {s.name: s for s in profile.strategies}
    assert set(by_name) == {s.name for s in DEFAULT_STRATEGIES}
    for default in DEFAULT_STRATEGIES:
        loaded = by_name[default.name]
        assert loaded.applies_to == default.applies_to
        assert loaded.requires_approvals == default.requires_approvals
        assert [(s.select, s.soak_minutes, s.gate) for s in loaded.stages] == [
            (s.select, s.soak_minutes, s.gate) for s in default.stages
        ]
    for platform, driver in PLATFORM_DRIVERS.items():
        assert profile.platforms[platform].driver == driver
    for platform, rollback in PLATFORM_ROLLBACK.items():
        assert profile.platforms[platform].rollback == rollback


def test_baseline_ships_zero_change_classes():
    """CI pin (ADR-0016): auto-approval authority can never originate from
    the platform. If this test ever needs changing, that is the review."""
    profile = load_profile(None)
    assert profile.change_classes.classes == []
    baseline_dir = (
        Path(__file__).parents[1] / "src" / "autonetops_planner" / "packs" / "baseline"
    )
    doc = yaml.safe_load((baseline_dir / "profile.yaml").read_text())
    assert (doc.get("files") or {}).get("change_classes") is None
    assert not (baseline_dir / "change_classes.yaml").exists()


def test_builtin_profile_plan_matches_legacy_plan(changeset):
    """The bit-identical guarantee: profile=None and profile=builtin:baseline
    produce the same rollout. Only the provenance fields may differ."""
    profile = load_profile(None)
    strategy = select_strategy(
        profile.strategies, compute_blast_radius(changeset).classification
    )
    legacy = build_plan(changeset, strategy)
    builtin = build_plan(changeset, strategy, profile=profile)

    legacy_doc = legacy.model_dump(mode="json", by_alias=True)
    builtin_doc = builtin.model_dump(mode="json", by_alias=True)
    for doc in (legacy_doc, builtin_doc):
        doc["policy_evaluation"].pop("profile")
        doc["policy_evaluation"].pop("assumptions")
    assert legacy_doc == builtin_doc
    assert legacy.id == builtin.id  # provenance never enters the plan id

    assert builtin.policy_evaluation.profile is not None
    assert builtin.policy_evaluation.profile.source == "builtin"
    # the fixture's unbound platform/definitions are recorded, never silent
    assert any("device-config" in a for a in builtin.policy_evaluation.assumptions)


# -- the reference pack ------------------------------------------------------


def test_reference_pack_loads_strict():
    profile = load_profile(REFERENCE_PACK)
    assert profile.ref.source == "pack"
    assert profile.ref.tenant == "autonetops"
    assert profile.strict is True
    # inherits baseline strategies; adds the one reviewed change class
    assert {s.name for s in profile.strategies} == {s.name for s in DEFAULT_STRATEGIES}
    assert [c.name for c in profile.change_classes.classes] == [
        "interface-descriptions"
    ]


# -- customer pack resolution ------------------------------------------------


def test_customer_pack_overrides_and_merges(tmp_path):
    pack = write_pack(
        tmp_path,
        minimal_pack_doc(
            meta={
                "tenant": "meridian",
                "name": "meridian-production",
                "version": "1.4.0",
                "conformance": "full",
            },
            sot={
                "device_kind": "MeridianDevice",
                "role_path": "device_role__node__slug__value",
                "platform_path": "platform__node__name__value",
                "region_path": "site__node__hall__value",
            },
            blast_radius={
                "thresholds": {
                    "low_max_devices": 5,
                    "high_min_devices": 25,
                    "high_min_regions": 2,
                }
            },
            approvals={"floors": {"moderate": ["meridian-netops"],
                                  "high": ["meridian-netops", "meridian-change-board"]}},
            platforms={
                "Juniper JunOS": {"driver": "junos", "rollback": "commit_confirmed"},
            },
            artifacts={
                "definitions": {
                    "device-config": {"content_format": "cli-text"},
                    "wan-openconfig": {"content_format": "openconfig-json"},
                }
            },
            rollback={"confirm_timeout_minutes": 15},
            abort_criteria=["gate failure", "manual NOC abort"],
            files={"canary_strategies": "canary_strategies.yaml"},
        ),
        canary_strategies__yaml=yaml.safe_dump(
            {
                "version": 1,
                "strategies": [
                    {
                        # override the baseline entry BY NAME: full replacement
                        "name": "builtin-single-target-canary",
                        "applies_to_blast_radius": ["low"],
                        "stages": [
                            {"select": "one_target", "soak_minutes": 5},
                            {"select": "remainder"},
                        ],
                    },
                    {
                        "name": "meridian-wave",
                        "applies_to_blast_radius": ["moderate"],
                        "requires_approvals": ["meridian-netops"],
                        "stages": [
                            {"select": "one_per_role", "soak_minutes": 10},
                            {"select": "remainder"},
                        ],
                    },
                ],
            }
        ),
    )
    profile = load_profile(pack)
    assert profile.ref.tenant == "meridian"
    assert profile.strict is True
    assert profile.thresholds == Thresholds(
        low_max_devices=5, high_min_devices=25, high_min_regions=2
    )
    # per-key platform merge: baseline keys survive, SoT-spelled key added
    assert profile.platforms["Juniper JunOS"].driver == "junos"
    assert profile.platforms["eos"].driver == "eos"
    # artifacts replace wholesale: baseline's device-configuration is gone
    assert set(profile.definition_formats) == {"device-config", "wan-openconfig"}
    # strategy merge by name: override replaced, new appended, rest inherited
    by_name = {s.name: s for s in profile.strategies}
    assert by_name["builtin-single-target-canary"].stages[0].soak_minutes == 5
    assert by_name["builtin-single-target-canary"].applies_to == [BlastRadiusClass.LOW]
    assert "meridian-wave" in by_name
    assert "builtin-high-blast-radius" in by_name  # inherited, keeps approvals
    assert profile.rollback_defaults.confirm_timeout_minutes == 15
    assert profile.abort_criteria == ["gate failure", "manual NOC abort"]
    assert profile.floors.high == ["meridian-change-board", "meridian-netops"]


def test_floors_union_never_removes(tmp_path):
    """A child can add approvers, never remove the base's (a lower bar than
    baseline is unrepresentable, not merely invalid)."""
    from autonetops_planner.profile import (
        ApprovalFloors,
        ApprovalsSection,
        IntentProfileDoc,
        ProfileMeta,
        _merge,
    )

    base = IntentProfileDoc(
        meta=ProfileMeta(tenant="_platform", name="b", version="1"),
        extends=None,
        approvals=ApprovalsSection(floors=ApprovalFloors(high=["platform-lead"])),
    )
    child = IntentProfileDoc(
        meta=ProfileMeta(tenant="acme", name="c", version="1"),
        approvals=ApprovalsSection(floors=ApprovalFloors(high=["acme-board"], low=["ops"])),
    )
    merged = _merge(base, child)
    assert merged.approvals.floors.high == ["acme-board", "platform-lead"]
    assert merged.approvals.floors.low == ["ops"]


def test_strategy_enabled_false_removes_inherited(tmp_path):
    pack = write_pack(
        tmp_path,
        minimal_pack_doc(
            approvals={"floors": {"high": ["acme-board"]}},
            files={"canary_strategies": "canary_strategies.yaml"},
        ),
        canary_strategies__yaml=yaml.safe_dump(
            {
                "strategies": [
                    {"name": "builtin-high-blast-radius", "enabled": False},
                    {
                        "name": "acme-high",
                        "applies_to_blast_radius": ["high"],
                        "requires_approvals": ["acme-board"],
                        "stages": [
                            {"select": "one_target", "soak_minutes": 30},
                            {"select": "remainder"},
                        ],
                    },
                ]
            }
        ),
    )
    profile = load_profile(pack)
    names = {s.name for s in profile.strategies}
    assert "builtin-high-blast-radius" not in names
    assert "acme-high" in names


# -- validation gates --------------------------------------------------------


def test_coverage_gap_is_a_load_error(tmp_path):
    pack = write_pack(
        tmp_path,
        minimal_pack_doc(files={"canary_strategies": "canary_strategies.yaml"}),
        canary_strategies__yaml=yaml.safe_dump(
            {"strategies": [{"name": "builtin-high-blast-radius", "enabled": False}]}
        ),
    )
    with pytest.raises(ProfileError, match="blast radius 'high'"):
        load_profile(pack)


def test_f9_high_without_approvals_rejected(tmp_path):
    pack = write_pack(
        tmp_path,
        minimal_pack_doc(files={"canary_strategies": "canary_strategies.yaml"}),
        canary_strategies__yaml=yaml.safe_dump(
            {
                "strategies": [
                    {
                        "name": "builtin-high-blast-radius",
                        "applies_to_blast_radius": ["high"],
                        "requires_approvals": [],
                        "stages": [{"select": "remainder"}],
                    }
                ]
            }
        ),
    )
    with pytest.raises(ProfileError, match="F9"):
        load_profile(pack)


def test_unknown_vocabulary_rejected_at_load(tmp_path):
    pack = write_pack(
        tmp_path,
        minimal_pack_doc(
            platforms={"junos": {"driver": "junos", "rollback": "wishful-undo"}},
            files={"canary_strategies": "canary_strategies.yaml"},
        ),
        canary_strategies__yaml=yaml.safe_dump(
            {
                "strategies": [
                    {
                        "name": "weird",
                        "applies_to_blast_radius": ["low"],
                        "stages": [
                            {"select": "one_per_site"},
                            {"select": "remainder", "gate": "acme.custom_gate"},
                        ],
                    }
                ]
            }
        ),
    )
    with pytest.raises(ProfileError) as excinfo:
        load_profile(pack)
    message = str(excinfo.value)
    assert "one_per_site" in message
    assert "acme.custom_gate" in message
    assert "wishful-undo" in message


def test_unknown_keys_rejected(tmp_path):
    pack = write_pack(
        tmp_path,
        minimal_pack_doc(files={"canary_strategies": "canary_strategies.yaml"}),
        canary_strategies__yaml=yaml.safe_dump(
            {"strategies": [{"name": "x", "applies_to_blast": ["low"],
                             "stages": [{"select": "remainder"}]}]}
        ),
    )
    with pytest.raises(ProfileError, match="applies_to_blast"):
        load_profile(pack)


def test_inverted_ladder_rejected(tmp_path):
    pack = write_pack(
        tmp_path,
        minimal_pack_doc(
            blast_radius={"thresholds": {"low_max_devices": 50, "high_min_devices": 10}}
        ),
    )
    with pytest.raises(ProfileError, match="ladder"):
        load_profile(pack)


def test_declared_file_must_exist(tmp_path):
    pack = write_pack(
        tmp_path, minimal_pack_doc(files={"change_classes": "change_classes.yaml"})
    )
    with pytest.raises(ProfileError, match="does not exist"):
        load_profile(pack)


def test_conformance_baseline_rejects_higher_sections(tmp_path):
    pack = write_pack(
        tmp_path,
        minimal_pack_doc(
            meta={
                "tenant": "acme",
                "name": "small",
                "version": "1.0.0",
                "conformance": "baseline",
            },
            platforms={"junos": {"driver": "junos", "rollback": "commit_confirmed"}},
        ),
    )
    with pytest.raises(ProfileError, match="conformance 'baseline'"):
        load_profile(pack)


def test_strict_pack_requires_complete_platform_bindings(tmp_path):
    pack = write_pack(
        tmp_path, minimal_pack_doc(platforms={"junos": {"driver": "junos"}})
    )
    with pytest.raises(ProfileError, match="both driver and rollback"):
        load_profile(pack)


def test_ietf_xml_matcher_rejected_as_unsupported(tmp_path):
    pack = write_pack(
        tmp_path,
        minimal_pack_doc(files={"change_classes": "change_classes.yaml"}),
        change_classes__yaml=yaml.safe_dump(
            {
                "version": 1,
                "classes": [
                    {
                        "name": "junos-descriptions",
                        "match": {"ietf-xml": {"paths_allow": ["/config/int/desc"]}},
                    }
                ],
            }
        ),
    )
    with pytest.raises(ProfileError, match="ietf-xml matcher is unsupported"):
        load_profile(pack)


def test_tenant_guard(tmp_path):
    pack = write_pack(tmp_path, minimal_pack_doc())
    assert load_profile(pack, tenant="acme").ref.tenant == "acme"
    with pytest.raises(ProfileError, match="tenant guard"):
        load_profile(pack, tenant="meridian")
    # builtin and legacy profiles are exempt from the guard
    assert load_profile(None, tenant="meridian").ref.source == "builtin"


def test_reserved_tenant_rejected(tmp_path):
    pack = write_pack(
        tmp_path,
        minimal_pack_doc(
            meta={"tenant": "_platform", "name": "sneaky", "version": "1"}
        ),
    )
    with pytest.raises(ProfileError, match="reserved"):
        load_profile(pack)


def test_requires_planner_pin(tmp_path):
    pack = write_pack(tmp_path, minimal_pack_doc(requires_planner=">=99.0"))
    with pytest.raises(ProfileError, match="requires_planner"):
        load_profile(pack)
    ok = write_pack(tmp_path / "ok", minimal_pack_doc(requires_planner=">=0.1,<1.0"))
    assert load_profile(ok).ref.source == "pack"


# -- identity ----------------------------------------------------------------


def test_checksum_is_formatting_insensitive_and_content_sensitive(tmp_path):
    doc = minimal_pack_doc(
        blast_radius={"thresholds": {"low_max_devices": 3, "high_min_devices": 12,
                                     "high_min_regions": 2}}
    )
    pack_a = write_pack(tmp_path / "a", doc)
    # same content, different key order + a comment
    reordered = dict(reversed(list(doc.items())))
    pack_b = (tmp_path / "b" / "pack")
    pack_b.mkdir(parents=True)
    (pack_b / "profile.yaml").write_text(
        "# formatting differs, content does not\n" + yaml.safe_dump(reordered)
    )
    assert load_profile(pack_a).ref.checksum == load_profile(pack_b).ref.checksum

    changed = minimal_pack_doc(
        blast_radius={"thresholds": {"low_max_devices": 4, "high_min_devices": 12,
                                     "high_min_regions": 2}}
    )
    pack_c = write_pack(tmp_path / "c", changed)
    assert load_profile(pack_c).ref.checksum != load_profile(pack_a).ref.checksum


def test_nonexistent_policies_dir_fails_closed(tmp_path):
    """F14: a configured-but-missing pack (failed clone, path typo) must
    never quietly become the lenient legacy profile."""
    with pytest.raises(ProfileError, match="does not exist"):
        load_profile(tmp_path / "policy-pack-TYPO")


def test_duplicate_strategy_names_in_one_file_rejected(tmp_path):
    pack = write_pack(
        tmp_path,
        minimal_pack_doc(files={"canary_strategies": "canary_strategies.yaml"}),
        canary_strategies__yaml=yaml.safe_dump(
            {
                "strategies": [
                    {"name": "acme-canary", "applies_to_blast_radius": ["low"],
                     "stages": [{"select": "one_target", "soak_minutes": 60},
                                {"select": "remainder"}]},
                    {"name": "acme-canary", "applies_to_blast_radius": ["low"],
                     "stages": [{"select": "remainder"}]},
                ]
            }
        ),
    )
    with pytest.raises(ProfileError, match="defined twice in one file"):
        load_profile(pack)


# -- legacy mode -------------------------------------------------------------


def test_legacy_dir_without_profile_yaml(tmp_path):
    legacy = tmp_path / "legacy"
    legacy.mkdir()
    (legacy / "canary_strategies.yaml").write_text("version: draft\nstrategies: []\n")
    profile = load_profile(legacy)
    assert profile.ref.source == "legacy-policies-dir"
    assert profile.ref.tenant == "_legacy"
    assert profile.strict is False
    # lenient fallbacks preserved AND recorded
    assert {s.name for s in profile.strategies} == {s.name for s in DEFAULT_STRATEGIES}
    assert any("builtin defaults" in a for a in profile.load_assumptions)


# -- strict plan building ----------------------------------------------------


def test_strict_profile_refuses_to_guess(tmp_path, changeset):
    pack = write_pack(tmp_path, minimal_pack_doc())
    profile = load_profile(pack)
    strategy = select_strategy(
        profile.strategies,
        compute_blast_radius(changeset, profile.thresholds).classification,
    )
    with pytest.raises(PlanBuildError) as excinfo:
        build_plan(changeset, strategy, profile=profile)
    message = str(excinfo.value)
    # the fixture's definitions are not bound by the pack -> named findings
    assert "device-config" in message
    assert "fabric-intent" in message


def test_strict_profile_builds_when_fully_bound(tmp_path, changeset):
    pack = write_pack(
        tmp_path,
        minimal_pack_doc(
            meta={"tenant": "acme", "name": "acme", "version": "1",
                  "conformance": "full"},
            platforms={
                "junos": {"driver": "junos", "rollback": "commit_confirmed"},
                "cloudvision": {"driver": "cloudvision", "rollback": "controller_revision"},
            },
            artifacts={
                "definitions": {
                    "device-config": {"content_format": "cli-text"},
                    "fabric-intent": {"content_format": "cli-text"},
                }
            },
            approvals={"floors": {"high": ["acme-change-board"]}},
        ),
    )
    profile = load_profile(pack)
    blast = compute_blast_radius(changeset, profile.thresholds)
    strategy = select_strategy(profile.strategies, blast.classification)
    plan = build_plan(changeset, strategy, profile=profile)
    assert plan.policy_evaluation.profile is not None
    assert plan.policy_evaluation.profile.tenant == "acme"
    assert plan.policy_evaluation.assumptions == []
    # floors union the strategy's approvals into the recorded bar
    assert "acme-change-board" in plan.policy_evaluation.approvals_required
    for approval in strategy.requires_approvals:
        assert approval in plan.policy_evaluation.approvals_required
    # rollback comes from the reviewed binding, not a guess
    steps = {s.target.control_point: s for st in plan.stages for s in st.steps}
    assert steps["pe1-gru"].rollback.strategy == "commit_confirmed"


# -- schema drift ------------------------------------------------------------


def test_committed_profile_schema_matches_models():
    """CI drift gate: contracts/profile/v1/profile.schema.json is generated."""
    import json

    from autonetops_planner.profile import IntentProfileDoc

    committed = (
        Path(__file__).parents[2] / "contracts" / "profile" / "v1"
        / "profile.schema.json"
    )
    if not committed.exists():
        pytest.skip("schema not exported yet")
    schema = IntentProfileDoc.model_json_schema(by_alias=True)
    schema["$id"] = "https://autonetops.dev/contracts/profile/v1/profile.schema.json"
    assert json.loads(committed.read_text()) == schema
