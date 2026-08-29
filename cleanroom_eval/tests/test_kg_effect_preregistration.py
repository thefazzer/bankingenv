from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path


ASSET = (
    Path(__file__).resolve().parents[1]
    / "assets"
    / "kg_effect"
    / "preregistration.v1.json"
)
ARM_IDS = [f"E{index}" for index in range(8)]


def _load() -> dict:
    return json.loads(ASSET.read_text(encoding="utf-8"))


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


def test_protocol_has_a_valid_canonical_self_digest() -> None:
    protocol = _load()
    assert protocol["self_sha256"] == _canonical_digest(protocol)


def test_all_eight_arms_are_registered_and_primary_estimand_is_kg_vs_flat() -> None:
    protocol = _load()
    arms = protocol["arms"]
    assert [arm["id"] for arm in arms] == ARM_IDS
    assert len({arm["name"] for arm in arms}) == 8
    assert protocol["estimand"] == {
        "id": "delta_kg",
        "treatment_arm": "E4",
        "control_arm": "E1",
        "contrast": "E4-E1",
        "interpretation": (
            "The incremental effect of graph topology, canonical archetypes and "
            "graph traversal over budget-matched flat retrieval from the same "
            "clean-room evidence universe."
        ),
        "unit": "scenario",
        "paired": True,
    }
    assert next(arm for arm in arms if arm["id"] == "E4")["graph_enabled"] is True
    assert next(arm for arm in arms if arm["id"] == "E1")["graph_enabled"] is False


def test_population_is_500_scenarios_in_ten_precommitted_strata() -> None:
    population = _load()["scenario_population"]
    strata = population["strata"]
    assert len(strata) == 10
    assert len({row["id"] for row in strata}) == 10
    assert sum(row["target"] for row in strata) == population["target_scenarios"] == 500
    assert sum(row["smoke"] for row in strata) == population["smoke_scenarios"] == 20
    assert population["target_arm_calls"] == 500 * 8
    assert population["harness_smoke_arm_calls"] == 20 * 4
    assert population["confirmatory_smoke_arm_calls"] == 20 * 8

    supported = sum(
        row["target"] for row in strata if row["support_class"] == "supported"
    )
    unsupported = sum(
        row["target"] for row in strata if row["support_class"] == "unsupported"
    )
    assert supported == population["supported_scenarios"] == 400
    assert unsupported == population["unsupported_scenarios"] == 100
    assert {row["id"]: row["target"] for row in strata} == {
        "people_employment_seniority_reporting": 46,
        "client_account_product_counterparty_resolution": 46,
        "trade_booking_allocation_fix_lifecycle": 46,
        "reconciliation_breaks_ownership_escalation": 45,
        "settlement_reference_confirmation": 45,
        "collateral_margin_valuation": 45,
        "permissions_segregation_release": 38,
        "temporal_causality_effective_dating": 45,
        "provenance_contradiction_duplicates_uncertainty_refusal": 100,
        "cross_case_concentration_motifs_dependencies_risk": 44,
    }
    assert {row["id"]: row["smoke"] for row in strata} == {
        "people_employment_seniority_reporting": 2,
        "client_account_product_counterparty_resolution": 2,
        "trade_booking_allocation_fix_lifecycle": 2,
        "reconciliation_breaks_ownership_escalation": 2,
        "settlement_reference_confirmation": 2,
        "collateral_margin_valuation": 2,
        "permissions_segregation_release": 1,
        "temporal_causality_effective_dating": 1,
        "provenance_contradiction_duplicates_uncertainty_refusal": 4,
        "cross_case_concentration_motifs_dependencies_risk": 2,
    }
    assert {row["id"] for row in strata} == {
        "people_employment_seniority_reporting",
        "client_account_product_counterparty_resolution",
        "trade_booking_allocation_fix_lifecycle",
        "reconciliation_breaks_ownership_escalation",
        "settlement_reference_confirmation",
        "collateral_margin_valuation",
        "permissions_segregation_release",
        "temporal_causality_effective_dating",
        "provenance_contradiction_duplicates_uncertainty_refusal",
        "cross_case_concentration_motifs_dependencies_risk",
    }


def test_primary_metric_is_strict_binary_intention_to_treat() -> None:
    protocol = _load()
    metric = protocol["primary_metric"]
    population = protocol["scenario_population"]
    assert metric["id"] == "strict_banking_scenario_success_rate"
    assert metric["type"] == "binary_per_scenario"
    assert metric["denominator"] == "all 500 precommitted scenarios"
    assert metric["missing_result_score"] == 0
    assert "may not be excluded" in population["missing_result_policy"]
    assert len(metric["supported_success_requires_all"]) >= 6
    assert len(metric["unsupported_success_requires_all"]) >= 4


def test_primary_pair_has_equal_budget_ceilings_without_semantic_padding() -> None:
    matched = _load()["matched_execution"]
    pair = matched["primary_pair"]
    assert pair["arms"] == ["E1", "E4"]
    assert pair["token_budget_ceiling_equal"] is True
    assert pair["item_budget_ceiling_equal"] is True
    assert pair["retrieved_evidence_token_budget"] > 0
    assert pair["retrieved_evidence_item_budget"] > 0
    assert pair["same_cleanroom_evidence_universe"] is True
    assert pair["tokenizer_identity_must_match_model"] is True
    assert pair["padding_prohibited"] is True
    assert pair["actual_token_and_item_usage_reported"] is True
    for key in (
        "base_model_identity_equal_across_arms",
        "inference_configuration_equal_across_arms",
        "question_bytes_equal_across_arms",
        "seed_schedule_equal_across_arms",
        "response_schema_equal_across_arms",
    ):
        assert matched[key] is True


def test_model_and_scorer_are_blind_to_treatment_and_gold() -> None:
    blinding = _load()["blinding"]
    exclusions = set(blinding["model_request_excludes"])
    assert {
        "arm identity",
        "gold answer",
        "expected evidence IDs",
        "scoring rubric",
        "support class",
        "enabled or ablated labels",
    } <= exclusions
    assert "arm" not in {field.lower() for field in blinding["provider_receives_only"]}
    assert "after" in blinding["scorer_blinding"]


def test_hard_gates_block_inadmissible_results() -> None:
    gates = _load()["hard_gates"]
    assert gates["minimum_completed_call_rate"] >= 0.99
    assert gates["minimum_completed_scenario_block_rate"] >= 0.99
    assert gates["schema_valid_citation_object_rate"] == 1.0
    for key in (
        "citations_outside_supplied_evidence_set",
        "unsupported_additions",
        "uncited_refusals",
        "gold_or_arm_identity_leaks",
        "post_execution_scenario_exclusions",
        "budget_match_violations_for_E1_E4",
        "scenario_partition_leaks",
    ):
        assert gates[key] == 0
    assert gates["semantic_grounding_noninferiority"]["contrast"] == "E4-E1"
    assert "INADMISSIBLE" in gates["failure_disposition"]


def test_inference_is_paired_cluster_bootstrap_with_locked_decision_rules() -> None:
    protocol = _load()
    inference = protocol["inference"]
    rules = protocol["decision_rules"]
    assert inference["primary_contrast"] == "E4-E1"
    assert inference["method"] == "paired cluster bootstrap"
    assert inference["bootstrap_samples"] == 10000
    assert inference["confidence_level"] == 0.95
    assert inference["resampling_unit"] == "scenario_family_cluster"
    assert set(rules) >= {
        "POSITIVE",
        "NEGATIVE",
        "NULL",
        "INADMISSIBLE",
    }
    assert "lower 95%" in rules["POSITIVE"]
    assert "upper 95%" in rules["NEGATIVE"]
    assert "includes zero" in rules["NULL"]
    assert "hard gates fail" in rules["INADMISSIBLE"]


def test_run_commitments_are_required_but_not_faked_in_the_protocol() -> None:
    protocol = _load()
    commitments = protocol["commitment_protocol"]
    assert commitments["status"] == "SPECIFICATION_ONLY_UNBOUND"
    assert commitments["run_values_present_in_this_document"] is False
    assert len(commitments["required_sha256_commitments"]) >= 16
    assert all(
        name.endswith("_sha256")
        for name in commitments["required_sha256_commitments"]
    )
    assert "Before the first" in commitments["binding_deadline"]
    assert "signed" in commitments["binding_artifact"]

    without_self_digest = dict(protocol)
    without_self_digest.pop("self_sha256")
    serialized = json.dumps(without_self_digest, sort_keys=True)
    assert re.search(r"\b[0-9a-f]{64}\b", serialized) is None
    assert "invented 64-character placeholder hashes" in commitments["prohibited"]
