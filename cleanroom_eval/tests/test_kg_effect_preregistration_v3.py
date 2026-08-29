from __future__ import annotations

import hashlib
import json
from pathlib import Path


ASSET_DIR = Path(__file__).resolve().parents[1] / "assets" / "kg_effect"
V2_ASSET = ASSET_DIR / "preregistration.v2.json"
V3_ASSET = ASSET_DIR / "preregistration.v3.json"
V2_FILE_SHA256 = "98b4098ad926191d2b9e475701d84b0e570ad3f859869430aac214b674eeb765"
V2_SELF_SHA256 = "1f376963604aaaa3523541edad7df441264332cb8ec0d260af9a9c97f6d8ad01"


def _reject_duplicate_keys(pairs: list[tuple[str, object]]) -> dict:
    value: dict = {}
    for key, item in pairs:
        if key in value:
            raise ValueError(f"duplicate JSON key: {key}")
        value[key] = item
    return value


def _load(path: Path) -> dict:
    return json.loads(
        path.read_text(encoding="utf-8"),
        object_pairs_hook=_reject_duplicate_keys,
    )


def _canonical_digest(document: dict) -> str:
    payload = dict(document)
    payload.pop("self_sha256", None)
    canonical = json.dumps(
        payload,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
    ).encode("utf-8")
    return hashlib.sha256(canonical).hexdigest()


def test_v3_is_a_content_bound_amendment_and_v2_remains_unchanged() -> None:
    protocol = _load(V3_ASSET)
    base = protocol["base_protocol"]

    assert protocol["schema"] == "cleanroom.kg-effect-preregistration/v3"
    assert protocol["preregistration_id"] == "ficta_cleanroom_kg_effect_v3"
    assert protocol["supersedes_for_future_runs"] == "ficta_cleanroom_kg_effect_v2"
    assert protocol["self_sha256"] == _canonical_digest(protocol)
    assert hashlib.sha256(V2_ASSET.read_bytes()).hexdigest() == V2_FILE_SHA256
    assert base["file_sha256"] == V2_FILE_SHA256
    assert base["canonical_self_sha256"] == V2_SELF_SHA256
    assert _load(V2_ASSET)["self_sha256"] == V2_SELF_SHA256
    assert "except scenario_population.transfer_partitions" in base["inheritance"]


def test_v2_transfer_interpretation_is_inadmissible_before_execution() -> None:
    disposition = _load(V3_ASSET)["v2_transfer_disposition"]

    assert disposition["status"] == "INADMISSIBLE_PREEXECUTION_NO_PROVIDER_CALLS_ALLOWED"
    assert disposition["known_component_count"] == 1
    assert disposition["largest_known_component"] == 500
    assert disposition["registered_maximum_partition"] == 350
    assert disposition["largest_known_component"] > disposition[
        "registered_maximum_partition"
    ]
    assert "No v2 result may be reported" in disposition["interpretation"]


def test_v3_targets_and_focal_transfer_dimensions_are_exact_and_not_weakened() -> None:
    contract = _load(V3_ASSET)["transfer_partition_contract"]
    targets = contract["targets"]
    semantics = contract["holdout_semantics"]

    assert contract["population"] == 500
    assert targets == {
        "sealed_iid": 350,
        "unseen_clients": 40,
        "unseen_products": 30,
        "unseen_staff_hierarchies": 30,
        "unseen_scenario_families": 50,
    }
    assert sum(targets.values()) == contract["population"]
    assert "canonical client identity cluster" in semantics["unseen_clients"]
    assert "canonical product entity identity" in semantics["unseen_products"]
    assert "complete reports_to lineage" in semantics["unseen_staff_hierarchies"]
    assert "committed latent scenario-family cluster" in semantics[
        "unseen_scenario_families"
    ]


def test_event_closure_is_focal_subject_only_and_shared_context_is_explicit() -> None:
    boundary = _load(V3_ASSET)["transfer_partition_contract"]["focal_boundary"]

    assert "whose subject is the focal business root" in boundary["event_chain"]
    assert "never connect unrelated roots" in boundary["event_chain"]
    assert "Shared actors" in boundary["event_chain"]
    assert "shared operator" in boundary["permitted_shared_context"]
    assert "cannot be promoted into the held-out focal identity" in boundary[
        "permitted_shared_context"
    ]
    assert "Every call is isolated" in boundary["provider_state"]


def test_v3_closure_and_thread_evidence_are_fail_closed() -> None:
    contract = _load(V3_ASSET)["transfer_partition_contract"]
    invariants = contract["closure_invariants"]
    fields = set(contract["fail_closed_fields"])

    assert "No focal source record crosses transfer partitions." in invariants
    assert "No focal exact-duplicate or near-duplicate cluster crosses transfer partitions." in invariants
    assert "No explicit focal message-thread cluster crosses transfer partitions." in invariants
    assert any("Alias closure" in rule for rule in invariants)
    assert any("must exactly match" in rule for rule in invariants)
    assert any("Subject-line similarity" in rule for rule in invariants)
    assert {
        "focal root identity",
        "focal alias closure",
        "focal source-record closure",
        "focal exact and near-duplicate closure",
        "explicit message-thread closure",
        "typed identity eligibility",
        "exact target counts",
    } == fields


def test_current_focal_pack_is_exact_but_not_admissible_without_threads() -> None:
    assessment = _load(V3_ASSET)["preexecution_assessment"]
    contract = _load(V3_ASSET)["transfer_partition_contract"]

    assert assessment["known_component_count"] == 421
    assert assessment["largest_known_component"] == 6
    assert assessment["known_constraints_exactly_packable"] is True
    assert assessment["provisional_counts"] == contract["targets"]
    assert assessment["explicit_thread_closure"] is False
    assert assessment["focal_message_artifacts_without_explicit_thread_metadata"] == 381
    assert assessment["admissible"] is False
    assert assessment["status"] == (
        "PACKABLE_BUT_INADMISSIBLE_MISSING_EXPLICIT_THREAD_METADATA"
    )
    assert "no smoke or target provider call" in assessment["consequence"]


def test_provider_calls_remain_prohibited_until_all_preexecution_gates_pass() -> None:
    protocol = _load(V3_ASSET)
    hard_gates = protocol["additional_preexecution_commitments"]["hard_gates"]
    lock = protocol["analysis_lock"]

    assert hard_gates == {
        "exact_partition_counts": True,
        "focal_closure_crossings": 0,
        "missing_explicit_thread_ids": 0,
        "typed_identity_assignment_failures": 0,
        "provider_cross_call_state_reuse": 0,
    }
    assert lock["v2_results_permitted"] is False
    assert lock["v3_calls_before_thread_gate"] is False
    assert lock["target_counts_may_change_after_execution"] is False
    assert lock["focal_boundary_may_change_after_execution"] is False
