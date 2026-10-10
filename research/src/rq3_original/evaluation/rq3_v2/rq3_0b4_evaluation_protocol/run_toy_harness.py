"""Run the deterministic RQ3-0B4 harness using only hard-coded synthetic data."""

from __future__ import annotations

import json
from typing import Any

from .rq3_human_agreement import human_and_llm_agreement_bundle
from .rq3_human_packet_builder import build_blank_human_rating_packet
from .rq3_judge_request_builder import (
    PRIMARY_CRITERIA,
    SCORE_FIELDS,
    build_judge_request,
    deterministic_response_order,
    freeze_applicability,
)
from .rq3_judge_response_parser import parse_judge_response


TOY_BLINDING_KEY = b"RQ3-0B4-toy-key-never-use-for-real-data"


def _toy_metadata() -> dict[str, Any]:
    return {
        "applicability_metadata_version": "rq3-applicability-source-metadata-v1",
        "student_specific_data_relevant": True,
        "long_term_memory_relevant": True,
        "request_requires_advice": True,
        "gold_planning_required": True,
        "student_facing_support_appropriate": True,
        "material_lad_pages": ["TOY_ENGAGEMENT_PAGE", "TOY_REFLECTION_PAGE"],
        "ambiguity_relevant": False,
        "missing_evidence_relevant": True,
        "insufficiency_relevant": False,
        "conflict_relevant": False,
        "boundary_handling_relevant": True,
    }


def _toy_score_record(blind_id: str, scores: list[int]) -> dict[str, Any]:
    return {
        "response_blind_id": blind_id,
        "criterion_scores": {
            SCORE_FIELDS[criterion]: score
            for criterion, score in zip(PRIMARY_CRITERIA, scores)
        },
    }


def run_toy_harness() -> dict[str, Any]:
    applicability = freeze_applicability(_toy_metadata())
    restricted_schedule = deterministic_response_order(
        [
            {"scenario_family_id": "TOY_FAMILY_ALPHA", "response_source_key": "TOY_SOURCE_01"},
            {"scenario_family_id": "TOY_FAMILY_ALPHA", "response_source_key": "TOY_SOURCE_02"},
            {"scenario_family_id": "TOY_FAMILY_BETA", "response_source_key": "TOY_SOURCE_03"},
            {"scenario_family_id": "TOY_FAMILY_BETA", "response_source_key": "TOY_SOURCE_04"},
            {"scenario_family_id": "TOY_FAMILY_GAMMA", "response_source_key": "TOY_SOURCE_05"},
            {"scenario_family_id": "TOY_FAMILY_GAMMA", "response_source_key": "TOY_SOURCE_06"},
        ],
        TOY_BLINDING_KEY,
    )
    blind_id = restricted_schedule[0]["response_blind_id"]
    judge_request = build_judge_request(
        response_blind_id=blind_id,
        student_query="In this synthetic example, what should I do next?",
        current_lad_page="TOY_ENGAGEMENT_PAGE",
        visible_conversation_history=["Student: This is a wholly synthetic test turn."],
        frozen_dashboard_evidence={"toy_metric": 4, "provenance": "SYNTHETIC_ONLY"},
        course_evidence_available_in_condition={
            "availability": "AVAILABLE",
            "toy_fact": "Synthetic seminar practice is scheduled in week 2."
        },
        long_term_memory_available_in_condition={
            "availability": "AVAILABLE",
            "toy_preference": "Prefers short study blocks."
        },
        planning_support_available_in_condition={
            "availability": "AVAILABLE",
            "toy_steps": ["Review the toy note", "Try the toy exercise"]
        },
        candidate_response=(
            "Using only this synthetic evidence, review the toy note in a short block, "
            "then try the toy exercise and check the example metric."
        ),
        frozen_applicability_map=applicability,
    )
    score_values = [5, 4, 5, 5, 4, 5, 5, 4]
    synthetic_judge_output = {
        "response_blind_id": blind_id,
        **{
            SCORE_FIELDS[criterion]: score
            for criterion, score in zip(PRIMARY_CRITERIA, score_values)
        },
        "evidence_faithfulness": 5,
        "unsupported_claim_count": 0,
        "overall_applicable_mean": sum(score_values) / len(score_values),
        "criterion_rationales": {
            SCORE_FIELDS[criterion]: "Synthetic rationale for deterministic parser validation."
            for criterion in PRIMARY_CRITERIA
        },
        "schema_version": "rq3-judge-response-v1",
    }
    validated_score = parse_judge_response(
        synthetic_judge_output,
        applicability,
        expected_response_blind_id=blind_id,
    )
    human_a_packet = build_blank_human_rating_packet(
        packet_blind_id="HRP-TOY-A",
        rater_role="A",
        judge_requests=[judge_request],
    )
    human_b_packet = build_blank_human_rating_packet(
        packet_blind_id="HRP-TOY-B",
        rater_role="B",
        judge_requests=[judge_request],
    )

    toy_a = [_toy_score_record(blind_id, [5, 4, 5, 4, 4, 5, 5, 4])]
    toy_b = [_toy_score_record(blind_id, [4, 4, 5, 5, 4, 5, 4, 4])]
    toy_llm = [_toy_score_record(blind_id, score_values)]
    agreement = human_and_llm_agreement_bundle(toy_a, toy_b, toy_llm)
    return {
        "harness_status": "PASS_SYNTHETIC_TOY_ONLY",
        "blind_schedule_records": len(restricted_schedule),
        "blind_ids_unique": len({row["response_blind_id"] for row in restricted_schedule})
        == len(restricted_schedule),
        "judge_requests_built": 1,
        "synthetic_judge_records_locally_validated": 1,
        "locally_recomputed_overall_applicable_mean": validated_score[
            "overall_applicable_mean"
        ],
        "blank_toy_human_packets_built": 2,
        "blank_toy_human_packet_items": len(human_a_packet["items"])
        + len(human_b_packet["items"]),
        "toy_human_human_pooled_n": agreement["human_a_vs_human_b"]["pooled"]["n"],
        "toy_human_human_pooled_exact_agreement": agreement["human_a_vs_human_b"][
            "pooled"
        ]["exact_agreement"],
        "toy_pooled_human_llm_n": agreement["pooled_human_observations_vs_llm_judge"][
            "pooled"
        ]["n"],
        "toy_pooled_human_llm_mean_absolute_score_difference": agreement[
            "pooled_human_observations_vs_llm_judge"
        ]["pooled"]["mean_absolute_score_difference"],
        "student_facing_responses_generated": 0,
        "llm_judge_calls": 0,
        "provider_calls": 0,
        "human_ratings_collected": 0,
        "real_rq3_scores_read_or_computed": 0,
    }


def main() -> int:
    print(json.dumps(run_toy_harness(), ensure_ascii=False, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
