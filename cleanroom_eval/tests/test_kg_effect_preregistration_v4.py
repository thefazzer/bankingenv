from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path


ASSET_DIR = Path(__file__).resolve().parents[1] / "assets" / "kg_effect"
V3_ASSET = ASSET_DIR / "preregistration.v3.json"
V4_ASSET = ASSET_DIR / "preregistration.v4.json"
V3_FILE_SHA256 = "466e03d935501da242ba690d83f93259a7dfba4ccd82941fa93c0ae99794c28d"
V3_SELF_SHA256 = "b1603f58dc95bbdca0d26f74afbe0429caf4df3c6cebbd20898b3a9cb6e0175f"


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
    unsigned = dict(document)
    unsigned.pop("self_sha256", None)
    payload = json.dumps(
        unsigned,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
    ).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def test_v4_binds_and_supersedes_the_unchanged_v3_transfer_gate() -> None:
    protocol = _load(V4_ASSET)
    base = protocol["base_protocol"]

    assert protocol["schema"] == "cleanroom.kg-effect-preregistration/v4"
    assert protocol["preregistration_id"] == "ficta_cleanroom_kg_effect_v4"
    assert protocol["supersedes_for_future_runs"] == "ficta_cleanroom_kg_effect_v3"
    assert protocol["self_sha256"] == _canonical_digest(protocol)
    assert hashlib.sha256(V3_ASSET.read_bytes()).hexdigest() == V3_FILE_SHA256
    assert _load(V3_ASSET)["self_sha256"] == V3_SELF_SHA256
    assert base["file_sha256"] == V3_FILE_SHA256
    assert base["canonical_self_sha256"] == V3_SELF_SHA256
    assert "exact item/byte/token equality" in base["inheritance"]
    assert "Arms, questions, metrics, model plan" in base["inheritance"]


def test_v8_source_and_communication_contract_close_the_genuine_thread_gap() -> None:
    protocol = _load(V4_ASSET)
    source = protocol["v8_source_bundle"]
    threads = protocol["communication_thread_contract"]

    assert source["release_id"] == "ficta-4181-institution-v8"
    assert source["seed"] == 4181
    assert source["source_verification_status"] == "PASS"
    assert source["institution_scale_status"] == "PASS"
    assert source["sealed_v7_mutated"] is False
    assert threads["assignment_phase"] == "hidden-world-render-before-artifact-bytes"
    assert threads["communication_artifacts"] == 2901
    assert threads["distinct_messages"] == 2701
    assert threads["explicit_threads"] == 920
    assert threads["duplicate_lineages"] == 400
    assert threads["missing_explicit_thread_ids"] == 0
    assert threads["thread_root_crossings"] == 0
    assert threads["verification_status"] == "PASS"
    assert "No subject" in threads["assignment_basis"]


def test_v8_sealed_population_and_exact_focal_transfer_are_content_bound() -> None:
    protocol = _load(V4_ASSET)
    population = protocol["sealed_population_commitments"]
    transfer = protocol["focal_transfer_commitments"]

    assert population["scenario_manifest"]["scenario_count"] == 500
    assert population["provider_projection"]["scenario_count"] == 500
    assert population["held_out_paraphrases"]["scenario_count"] == 500
    assert population["held_out_paraphrases"]["truth_preserving"] is True
    assert population["held_out_paraphrases"]["source_cluster_retained"] is True
    assert population["adversarial_mutations"]["mutation_count"] == 500
    assert population["adversarial_mutations"]["family_counts"] == {
        "entity_swap": 100,
        "date_shift": 100,
        "polarity_reversal": 100,
        "contradiction_injection": 100,
        "unsupported_addition": 100,
    }
    assert transfer["counts"] == {
        "sealed_iid": 350,
        "unseen_clients": 40,
        "unseen_products": 30,
        "unseen_staff_hierarchies": 30,
        "unseen_scenario_families": 50,
    }
    assert sum(transfer["counts"].values()) == 500
    assert transfer["component_count"] == 414
    assert transfer["largest_component"] == 25
    assert transfer["closure_crossings"] == 0
    assert transfer["typed_identity_assignment_failures"] == 0
    assert transfer["admissible"] is True
    assert transfer["status"] == "PROVEN_ADMISSIBLE"

    serialized = json.dumps({"population": population, "transfer": transfer})
    digests = re.findall(r"\b[0-9a-f]{64}\b", serialized)
    assert len(digests) == 14
    assert len(set(digests)) == len(digests)


def test_v4_replaces_impossible_exact_equality_with_common_ceiling() -> None:
    budget = _load(V4_ASSET)["budget_contract_amendment"]
    ceiling = budget["shared_provider_token_ceiling"]
    integrity = budget["record_integrity"]
    reporting = budget["reporting"]
    gate = budget["feasibility_gate"]

    assert "not generally attainable" in budget["feasibility_finding"]
    assert budget["superseded_v2_fields"] == [
        "budget_contract.exact_match_set",
        "budget_contract.exact_equal_fields_within_scenario_model_and_variant",
        "budget_contract.material_fit",
        "budget_contract.failure_policy",
    ]
    assert "One numeric ceiling" in ceiling["rule"]
    assert "whole-record inclusion" in ceiling["selection"]
    assert ceiling["numeric_ceiling_status"] == "REQUIRED_NOT_YET_BOUND"
    assert ceiling["post_execution_change_allowed"] is False
    assert integrity == {
        "whole_semantic_records_only": True,
        "semantic_or_byte_truncation": "PROHIBITED",
        "padding_or_filler": "PROHIBITED",
        "partial_record_inclusion": "PROHIBITED",
    }
    assert reporting["actual_counts_reported_for_every_call"] == [
        "provider_token_count",
        "item_count",
        "utf8_byte_count",
    ]
    assert "covariates" in reporting["length_sensitivity"]
    assert "manufactured equality" in reporting["length_sensitivity"]
    assert gate["exact_tokenizer_binding_verified"] is True
    assert gate["numeric_ceiling_bound"] is False
    assert gate["whole_record_material_matrix_built"] is False
    assert gate["provider_execution_allowed"] is False


def test_v4_closes_only_transfer_and_does_not_authorize_provider_calls() -> None:
    lock = _load(V4_ASSET)["execution_lock"]

    assert lock["provider_calls_made_under_v4"] == 0
    assert lock["transfer_gate_passed"] is True
    assert lock["provider_execution_authorized_by_this_amendment"] is False
    assert "Provider calls remain prohibited" in lock["reason"]
    assert "requires preregistration v5" in lock["change_rule"]
