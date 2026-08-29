from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path

import pytest


ASSET = (
    Path(__file__).resolve().parents[1]
    / "assets"
    / "kg_effect"
    / "preregistration.v2.json"
)
CORE_ARMS = [f"E{index}" for index in range(8)]
QUESTION_IDS = [f"Q{index:02d}" for index in range(1, 11)]


def _reject_duplicate_keys(pairs: list[tuple[str, object]]) -> dict:
    value: dict = {}
    for key, item in pairs:
        if key in value:
            raise ValueError(f"duplicate JSON key: {key}")
        value[key] = item
    return value


def _load() -> dict:
    return json.loads(
        ASSET.read_text(encoding="utf-8"),
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


def test_v2_is_new_frozen_protocol_with_unique_keys_and_valid_self_digest() -> None:
    protocol = _load()
    assert protocol["schema"] == "cleanroom.kg-effect-preregistration/v2"
    assert protocol["preregistration_id"] == "ficta_cleanroom_kg_effect_v2"
    assert protocol["supersedes_for_future_runs"] == "ficta_cleanroom_kg_effect_v1"
    assert protocol["status"] == "PROTOCOL_FROZEN_BEFORE_EXECUTION"
    assert protocol["self_sha256"] == _canonical_digest(protocol)

    unsigned = dict(protocol)
    unsigned.pop("self_sha256")
    serialized = json.dumps(unsigned, sort_keys=True)
    assert re.search(r"\b[0-9a-f]{64}\b", serialized) is None


def test_500_scenario_e0_e7_core_and_h1_hybrid_are_fully_registered() -> None:
    protocol = _load()
    population = protocol["scenario_population"]
    arms = protocol["arms"]
    assert [arm["id"] for arm in arms if arm["class"] == "core"] == CORE_ARMS
    assert [arm["id"] for arm in arms if arm["class"] == "diagnostic"] == ["H1"]
    assert population["sealed_original_scenarios"] == 500
    assert sum(row["target"] for row in population["strata"]) == 500
    assert sum(row["target"] for row in population["transfer_partitions"]) == 500
    assert population["supported_scenarios"] == 400
    assert population["unsupported_scenarios"] == 100

    h1 = next(arm for arm in arms if arm["id"] == "H1")
    assert "Graph-planned" in h1["material"]
    assert "original clean-room source passages" in h1["material"]
    assert protocol["material_construction"]["h1_hybrid_rule"]["channels"] == [
        "graph-derived canonical claims and paths",
        "original clean-room source passages resolved from graph provenance",
    ]
    hybrid = protocol["material_construction"]["h1_hybrid_rule"]
    assert "at least one graph-derived item" in hybrid["channel_requirement"]
    assert "at least one" in hybrid["channel_requirement"]
    assert "reported separately" in hybrid["channel_audit"]


def test_execution_arithmetic_has_repeats_variants_mutations_and_matched_model() -> None:
    protocol = _load()
    plan = protocol["model_and_execution_plan"]
    panels = {panel["id"]: panel for panel in plan["panels"]}
    assert plan["economical_model"]["core_provider_repeats"] == 3
    assert plan["stronger_model"]["comparison_provider_repeats"] == 1
    assert panels["economical_core"]["arms"] == CORE_ARMS
    assert panels["economical_core"]["planned_calls"] == 500 * 8 * 3
    assert panels["economical_hybrid"]["planned_calls"] == 500 * 1 * 3
    assert panels["paraphrase_transfer"]["planned_calls"] == 500 * 3
    assert panels["adversarial_mutation"]["planned_calls"] == 500 * 3
    assert panels["stronger_model_matched"]["planned_calls"] == 500 * 3
    assert panels["live_copilot_six"]["planned_calls"] == 6 * 3
    assert plan["total_planned_calls"] == sum(
        panel["planned_calls"] for panel in panels.values()
    ) == 18018
    assert plan["smoke_prefix"]["included_in_target_denominator"] is True
    assert "not an adaptive pilot" in plan["smoke_prefix"]["rule"]
    assert "identical request digest" in plan["retry_policy"]

    variants = protocol["variant_panels"]
    assert variants["held_out_paraphrases"]["target_variants"] == 500
    mutations = variants["adversarial_mutations"]
    assert mutations["target_mutations"] == 500
    assert {row["id"]: row["target"] for row in mutations["families"]} == {
        "entity_swap": 100,
        "date_shift": 100,
        "polarity_reversal": 100,
        "contradiction_injection": 100,
        "unsupported_addition": 100,
    }


def test_semantic_strict_is_primary_and_harness_strict_is_not_mislabelled() -> None:
    metrics = _load()["metric_contract"]
    primary = metrics["primary_metric"]
    reported = {row["id"]: row for row in metrics["reported_metrics"]}
    assert primary["id"] == "semantic_strict_success"
    assert primary["display_name"] == "Semantic Strict"
    assert len(primary["supported_success_requires_all"]) >= 9
    assert len(primary["unsupported_success_requires_all"]) >= 5
    assert reported["decision_tuple_success"]["display_name"] == "Decision tuple"
    assert reported["harness_strict_success"]["display_name"] == "Harness Strict"
    assert "does not assert semantic entailment" in reported[
        "harness_strict_success"
    ]["definition"]

    validator = metrics["semantic_validator_contract"]
    assert validator["known_bad_fixture_rejection_rate"] == 1.0
    assert validator["unsupported_addition_disposition"] == "Semantic Strict failure"
    assert validator["uncited_refusal_disposition"] == "Semantic Strict failure"
    assert validator["prompt_only_or_id_membership_scoring_prohibited"] is True
    assert {"polarity", "qualifiers", "effective time", "grounded refusal scope"} <= set(
        validator["checks"]
    )


def test_controls_are_question_free_or_full_universe_and_budgets_are_exact() -> None:
    protocol = _load()
    materials = protocol["material_construction"]
    budget = protocol["budget_contract"]

    e5 = materials["e5_full_universe_rule"]
    assert "complete E4 candidate graph universe" in e5["order"][0]
    assert "only then" in e5["order"][-1]
    assert "before destroying" in e5["prohibited"]

    for control in ("e6_question_free_rule", "e7_question_free_rule"):
        rule = materials[control]
        assert "question text" in rule["selection_excludes"]
        assert "gold answer" in rule["selection_excludes"]
        assert "answer vocabulary" in rule["selection_excludes"]
        assert all("question" not in field for field in rule["selection_inputs"])

    assert budget["required_measurements_per_call"] == [
        "item_count",
        "utf8_byte_count",
        "provider_token_count",
        "payload_sha256",
    ]
    assert budget["exact_match_set"] == [*CORE_ARMS[1:], "H1"]
    assert budget["exact_equal_fields_within_scenario_model_and_variant"] == [
        "item_count",
        "utf8_byte_count",
        "provider_token_count",
    ]
    assert budget["semantic_padding_or_filler"] == "PROHIBITED"
    assert "exact provider tokenizer" in budget["tokenizer"].lower()
    assert "heuristic token estimates cannot satisfy" in budget["tokenizer"]
    assert "fails preexecution" in budget["failure_policy"]


def test_stronger_model_is_outcome_blind_and_material_matched() -> None:
    protocol = _load()
    plan = protocol["model_and_execution_plan"]
    stronger = plan["stronger_model"]
    assert "before execution" in stronger["designation_rule"]
    assert "never observed evaluation outcomes" in stronger["designation_rule"]
    panel = next(
        row for row in plan["panels"] if row["id"] == "stronger_model_matched"
    )
    assert panel["arms"] == ["E1", "E4", "H1"]
    assert "byte-identical material and questions" in protocol["budget_contract"][
        "cross_model_rule"
    ]
    capacity = protocol["statistical_analysis"]["model_capacity_analysis"]
    assert capacity["primary_interaction"] == (
        "(E4-E1)_stronger minus (E4-E1)_economical"
    )


def test_inference_uses_clustered_intervals_and_corrects_multiple_comparisons() -> None:
    analysis = _load()["statistical_analysis"]
    ci = analysis["confidence_interval"]
    policy = analysis["multiple_comparison_policy"]
    assert analysis["primary_contrast"] == "E4-E1 on Semantic Strict in economical_core"
    assert ci["method"] == "hierarchical paired cluster bootstrap"
    assert ci["bootstrap_samples"] >= 10000
    assert ci["outer_resampling_unit"] == "scenario_family_cluster"
    assert ci["inner_resampling_unit"] == "provider repeat seed within sampled scenario"
    assert len(analysis["confirmatory_secondary_family"]) == 6
    assert "Holm-Bonferroni" in policy["confirmatory_secondary"]
    assert "simultaneous" in policy["confirmatory_secondary"]
    assert "Holm-Bonferroni" in policy["question_subgroups"]
    assert "Benjamini-Hochberg" in policy["question_subgroups"]
    assert "not treated as independent scenarios" in analysis["repeatability"][
        "independence_guard"
    ]


def test_all_ten_questions_are_mapped_to_panels_arms_metrics_and_analysis() -> None:
    protocol = _load()
    questions = protocol["evaluation_questions"]
    assert [row["id"] for row in questions] == QUESTION_IDS
    assert protocol["question_answer_contract"]["required_question_ids"] == QUESTION_IDS
    registered_panels = {
        row["id"] for row in protocol["model_and_execution_plan"]["panels"]
    }
    registered_arms = {row["id"] for row in protocol["arms"]}
    registered_metrics = {
        protocol["metric_contract"]["primary_metric"]["id"],
        *(row["id"] for row in protocol["metric_contract"]["reported_metrics"]),
    }
    for row in questions:
        assert row["panels"] and set(row["panels"]) <= registered_panels
        assert row["arms"] and set(row["arms"]) <= registered_arms
        assert row["metrics"] and set(row["metrics"]) <= registered_metrics
        assert row["analysis"].strip()

    by_id = {row["id"]: row for row in questions}
    assert {"economical_core", "paraphrase_transfer"} <= set(by_id["Q01"]["panels"])
    assert set(CORE_ARMS) <= set(by_id["Q02"]["arms"])
    assert set(by_id["Q03"]["arms"]) == {"E1", "E4", "H1"}
    assert "effective-time" in by_id["Q05"]["question"]
    assert "stronger_model_matched" in by_id["Q07"]["panels"]
    assert "three-repeat" in by_id["Q08"]["analysis"].casefold()
    assert by_id["Q09"]["panels"] == ["live_copilot_six"]
    assert "stage-evidence taxonomy" in by_id["Q10"]["analysis"]


def test_failure_taxonomy_makes_missing_data_the_last_demonstrated_cause() -> None:
    taxonomy = _load()["failure_taxonomy"]
    labels = taxonomy["classification_order"]
    assert labels == [
        "evaluation_contract",
        "provider_or_runtime",
        "preprocessing_or_modelling",
        "retrieval_or_query_planning",
        "negative_evidence_or_grounding",
        "model_reasoning",
        "semantic_postprocessing",
        "rendering_or_product_integration",
        "genuine_source_coverage_gap",
        "no_failure",
    ]
    assert labels.index("genuine_source_coverage_gap") > labels.index("model_reasoning")
    gate = taxonomy["more_data_gate"].casefold()
    assert "complete source universe" in gate
    assert "proved absent" in gate
    assert len(taxonomy["required_stage_evidence"]) >= 9


def test_hard_gates_and_commitments_fail_closed_before_provider_execution() -> None:
    protocol = _load()
    gates = protocol["hard_gates"]
    assert gates["minimum_completed_call_rate"] >= 0.99
    assert gates["schema_valid_citation_selection_rate_on_completed_calls"] == 1.0
    for field in (
        "citations_outside_supplied_evidence_set",
        "known_bad_semantic_fixtures_accepted",
        "gold_or_arm_identity_leaks",
        "post_execution_exclusions",
        "budget_match_violations",
        "question_text_reads_by_E6_or_E7",
        "E5_pre_scramble_question_aware_selections",
        "hybrid_single_channel_collapses",
        "scenario_partition_leaks",
        "material_or_model_changes_after_smoke",
    ):
        assert gates[field] == 0
    assert "Semantic Strict 0" in gates["failure_disposition"]

    commitments = protocol["commitment_protocol"]
    assert commitments["status"] == "SPECIFICATION_ONLY_UNBOUND"
    assert commitments["run_values_present_in_this_document"] is False
    assert len(commitments["required_sha256_commitments"]) >= 30
    assert all(
        field.endswith("_sha256")
        for field in commitments["required_sha256_commitments"]
    )
    assert "Before the first" in commitments["binding_deadline"]
    assert "Ed25519-signed" in commitments["binding_artifact"]
    assert any(
        "planned call count" in binding
        for binding in commitments["required_bindings"]
    )


@pytest.mark.parametrize("question_id", QUESTION_IDS)
def test_each_answer_requires_content_addressed_evidence(question_id: str) -> None:
    contract = _load()["question_answer_contract"]
    assert question_id in contract["required_question_ids"]
    assert "evidence_artifact_paths" in contract["required_answer_fields"]
    assert "evidence_artifact_sha256s" in contract["required_answer_fields"]
    assert "content-addressed result" in contract["rule"]
