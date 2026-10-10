"""Deterministic, toy-only RQ2-V2 Stage 1 integration checks."""

from __future__ import annotations

from contextlib import ExitStack
from copy import deepcopy
import json
from pathlib import Path
import re
import socket
from typing import Any, Callable, Mapping, Sequence
from unittest.mock import patch

import numpy as np

from evaluation.capability_routing_rq2_v2_stage0 import CAPABILITY_FIELDS, MODEL_IDS
from evaluation.capability_routing_rq2_v2_stage0.contracts import (
    validate_case,
    validate_prediction,
)
from evaluation.capability_routing_rq2_v2_stage1.track_b_b0_b1.b0_rule_router import (
    B0RuleRouter,
)
from evaluation.capability_routing_rq2_v2_stage1.track_b_b0_b1.b1_legacy_intent_adapter import (
    B1LegacyIntentRouter,
)
from evaluation.capability_routing_rq2_v2_stage1.track_c_b2_b3 import (
    PRIMARY_FEATURE_FIELDS,
    PRIMARY_FEATURE_PROFILE,
    OvRLogisticRouter,
    PrototypeRouter,
)
from evaluation.capability_routing_rq2_v2_stage1.track_d_b4_p1 import (
    B4OfflineHarness,
    DeterministicMockProvider,
    P1HybridRouter,
    PRIMARY_SEMANTIC_INPUT_FIELDS,
    PRIMARY_SEMANTIC_INPUT_PROFILE,
    build_b4_prompt,
)
from evaluation.capability_routing_rq2_v2_stage1.track_d_b4_p1.b4 import (
    FEW_SHOT_PLACEHOLDER,
)


PACKAGE_ROOT = Path(__file__).resolve().parent
STAGE1_ROOT = PACKAGE_ROOT.parent
TRACK_A_ROOT = STAGE1_ROOT / "track_a_dataset"
TRACK_B_ROOT = STAGE1_ROOT / "track_b_b0_b1"
TRACK_C_ROOT = STAGE1_ROOT / "track_c_b2_b3"
PRIMARY_PROFILE_NAME = "R2V2_PRIMARY_SEMANTIC_INPUT_V1"
PRIMARY_FIELDS = (
    "current_query",
    "current_page",
    "dashboard_context",
    "visible_conversation_history",
)
TOY_THRESHOLDS = {field: 0.5 for field in CAPABILITY_FIELDS}
TOY_MARGINS = {field: 0.05 for field in CAPABILITY_FIELDS}


class IntegrationCheckError(AssertionError):
    """Raised when an integration invariant fails."""


class ToyEmbeddingAdapter:
    """Three-axis deterministic encoder with no model or network dependency."""

    model_id = "rq2-v2-integration-toy-axis-embedding-v1"
    dimension = 3

    def encode(self, texts: Sequence[str]) -> np.ndarray:
        vectors = []
        for text in texts:
            match = re.search(r"\[CURRENT_QUERY\]\n([^\n]+)", text)
            query = match.group(1) if match else ""
            bits = re.fullmatch(r"TOY_VECTOR_([01]{3})", query)
            if bits:
                vector = [1.0 if value == "1" else -1.0 for value in bits.group(1)]
            elif query == "TOY_VECTOR_UNCERTAIN":
                vector = [0.0, -1.0, 1.0]
            else:
                raise ValueError(f"unknown toy query: {query!r}")
            vectors.append(vector)
        return np.asarray(vectors, dtype=np.float64)


def _model_input(query: str) -> dict[str, Any]:
    return {
        "current_query": query,
        "current_page": "Overview",
        "dashboard_context": "Toy dashboard evidence only.",
        "visible_conversation_history": [],
        "rag_context_state": "UNKNOWN",
        "memory_context_state": "VISIBLE_HISTORY_ONLY",
    }


def canonical_toy_answer_case(
    query: str = "TOY_VECTOR_101",
    *,
    case_id: str = "TOY-INTEGRATION-ANSWER",
) -> dict[str, Any]:
    case = {
        "schema_version": "rq2-v2-case-v1",
        "case_id": case_id,
        "scenario_family_id": "TOY-INTEGRATION-FAMILY",
        "utterance_id": f"{case_id}-U1",
        "provenance": {
            "type": "RESEARCHER_SYNTHETIC",
            "source_asset_id": "RQ2_V2_STAGE1_INTEGRATION_TOY",
            "prior_exposure_to_model_selection": True,
            "human_verified": False,
        },
        "partition": "DEV",
        "model_input": _model_input(query),
        "gold": {
            "dialogue_action": "ANSWER",
            "rag_required": True,
            "memory_required": False,
            "planning_required": True,
        },
        "governance": {
            "final_test_eligible": False,
            "fixture_only": True,
            "authentic_student_data_claim": False,
            "contains_restricted_data": False,
        },
    }
    validate_case(case)
    return case


def _toy_training_cases() -> list[dict[str, Any]]:
    rows = []
    for value in range(8):
        bits = f"{value:03b}"
        labels = {
            field: bits[position] == "1"
            for position, field in enumerate(CAPABILITY_FIELDS)
        }
        rows.append(
            {
                "case_id": f"TOY-TRAIN-{bits}",
                "scenario_family_id": f"TOY-TRAIN-FAMILY-{bits}",
                "partition": "DEV",
                "model_input": _model_input(f"TOY_VECTOR_{bits}"),
                "development_labels": {"dialogue_action": "ANSWER", **labels},
            }
        )
    return rows


def _load_json(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise IntegrationCheckError(f"expected JSON object: {path}")
    return value


def verify_six_model_interfaces() -> dict[str, Any]:
    observed = (
        B0RuleRouter.model_id,
        B1LegacyIntentRouter.model_id,
        PrototypeRouter.model_id,
        OvRLogisticRouter.model_id,
        B4OfflineHarness.model_id,
        P1HybridRouter.model_id,
    )
    if observed != MODEL_IDS:
        raise IntegrationCheckError(f"model IDs differ: {observed}")
    return {"model_ids": list(observed), "interface_count": len(observed)}


def verify_unfrozen_research_choices() -> dict[str, Any]:
    mapping = _load_json(
        TRACK_B_ROOT / "config" / "b1_intent_to_capability_mapping_unfrozen_v1.json"
    )
    entries = mapping.get("mappings")
    if mapping.get("mapping_status") != "UNFROZEN" or not isinstance(entries, list):
        raise IntegrationCheckError("B1 mapping is not UNFROZEN")
    selected = sum(
        entry.get(field) is not None
        for entry in entries
        for field in ("proposed_rag", "proposed_memory", "proposed_planning")
    )
    track_c = _load_json(TRACK_C_ROOT / "config" / "track_c_defaults_v1.json")
    development = track_c.get("development_only") or {}
    prompt = build_b4_prompt(canonical_toy_answer_case()["model_input"])
    if len(entries) != 16 or selected or development.get("winner_claim") is not False:
        raise IntegrationCheckError("an unfrozen development choice was selected")
    if FEW_SHOT_PLACEHOLDER not in prompt:
        raise IntegrationCheckError("B4 few-shot placeholder was replaced")
    return {
        "b1_mapping_status": "UNFROZEN",
        "b1_mapping_rows": 16,
        "b1_selected_capability_values": 0,
        "b4_few_shot_status": "PLACEHOLDER_ONLY_NOT_SELECTED",
        "b2_b3_threshold_status": "DEVELOPMENT_DEFAULTS_NOT_FINAL_SELECTION",
        "p1_threshold_status": "CALLER_SUPPLIED_TOY_VALUES_NOT_FINAL_SELECTION",
    }


def verify_writer_amendment() -> dict[str, Any]:
    guide = (TRACK_A_ROOT / "HUMAN_WRITER_GUIDE.md").read_text(encoding="utf-8")
    attestation = (TRACK_A_ROOT / "WRITER_COMPLETION_ATTESTATION.md").read_text(
        encoding="utf-8"
    )
    required = (
        "All queries must be written in\nEnglish",
        "every assigned row must be completed",
        "ChatGPT, Codex, Copilot",
        "Do not view, request, or discuss the other writer's packet or answers",
        "refer to it only\n   indirectly",
        "Edit only `natural_student_query`",
    )
    if any(text not in guide for text in required):
        raise IntegrationCheckError("writer guide amendment is incomplete")
    if "completed all assigned queries independently, in English" not in attestation:
        raise IntegrationCheckError("writer attestation is incomplete")
    return {"guide_requirements_verified": len(required), "attestation_present": True}


def _probabilities(values: Mapping[str, Any]) -> dict[str, float]:
    if set(values) != set(CAPABILITY_FIELDS):
        raise IntegrationCheckError("B3 probability label axis differs")
    result = {field: float(values[field]) for field in CAPABILITY_FIELDS}
    if any(not 0.0 <= value <= 1.0 for value in result.values()):
        raise IntegrationCheckError("B3 probability outside [0, 1]")
    return result


def run_toy_b3_to_p1_smoke() -> dict[str, Any]:
    direct_case = canonical_toy_answer_case()
    uncertain_case = canonical_toy_answer_case(
        "TOY_VECTOR_UNCERTAIN", case_id="TOY-INTEGRATION-UNCERTAIN"
    )
    b3 = OvRLogisticRouter(
        ToyEmbeddingAdapter(), thresholds=TOY_THRESHOLDS, random_seed=20260830
    ).fit(_toy_training_cases())
    direct_probabilities = _probabilities(b3.predict_proba(direct_case))
    uncertain_probabilities = _probabilities(b3.predict_proba(uncertain_case))
    b3_prediction = b3.predict(direct_case)
    validate_prediction(b3_prediction)

    provider = DeterministicMockProvider(
        json.dumps(
            {
                "rag_required": False,
                "memory_required": False,
                "planning_required": True,
                "reason_code": "TOY_UNCERTAIN_FALLBACK",
            },
            sort_keys=True,
        )
    )
    p1 = P1HybridRouter(B4OfflineHarness(provider))
    network_attempts: list[str] = []

    def blocked(*_args: Any, **_kwargs: Any) -> Any:
        network_attempts.append("socket")
        raise IntegrationCheckError("network access attempted")

    with ExitStack() as stack:
        stack.enter_context(patch("socket.create_connection", blocked))
        stack.enter_context(patch.object(socket.socket, "connect", blocked))
        stack.enter_context(patch.object(socket.socket, "connect_ex", blocked))
        direct = p1.predict(
            case_id=direct_case["case_id"],
            model_input=direct_case["model_input"],
            base_probabilities=direct_probabilities,
            thresholds=TOY_THRESHOLDS,
            uncertainty_margins=TOY_MARGINS,
        ).to_dict()
        calls_after_direct = provider.call_count
        fallback = p1.predict(
            case_id=uncertain_case["case_id"],
            model_input=uncertain_case["model_input"],
            base_probabilities=uncertain_probabilities,
            thresholds=TOY_THRESHOLDS,
            uncertainty_margins=TOY_MARGINS,
        ).to_dict()
    validate_prediction(direct)
    validate_prediction(fallback)

    if direct["metadata"]["fallback_triggered"] or calls_after_direct != 0:
        raise IntegrationCheckError("confident path did not remain on B3")
    if not fallback["metadata"]["fallback_triggered"] or provider.call_count != 1:
        raise IntegrationCheckError("uncertain path did not make exactly one B4 call")
    if network_attempts or provider.network_call_count or provider.real_provider_call_count:
        raise IntegrationCheckError("external activity detected")

    b0 = B0RuleRouter()
    b0_prediction = b0.predict(direct_case).to_dict()
    context_variant = deepcopy(direct_case)
    context_variant["model_input"]["rag_context_state"] = "RETRIEVAL_UNAVAILABLE"
    context_variant["model_input"]["memory_context_state"] = (
        "LONG_TERM_MEMORY_UNAVAILABLE"
    )
    if b0.predict(context_variant).to_dict() != b0_prediction:
        raise IntegrationCheckError("B0 used a compatibility-only context state")
    if tuple(b0_prediction["metadata"]["model_visible_fields_used"]) != PRIMARY_FIELDS:
        raise IntegrationCheckError("B0 primary field surface differs")

    profile_values = {
        PRIMARY_FEATURE_PROFILE,
        PRIMARY_SEMANTIC_INPUT_PROFILE,
        b3_prediction["metadata"]["primary_feature_profile"],
        direct["metadata"]["input_profile"],
        fallback["metadata"]["input_profile"],
    }
    if profile_values != {PRIMARY_PROFILE_NAME}:
        raise IntegrationCheckError(f"primary profile differs: {profile_values}")
    if tuple(PRIMARY_FEATURE_FIELDS) != PRIMARY_FIELDS:
        raise IntegrationCheckError("Track C primary fields differ")
    if tuple(PRIMARY_SEMANTIC_INPUT_FIELDS) != PRIMARY_FIELDS:
        raise IntegrationCheckError("Track D primary fields differ")
    if build_b4_prompt(context_variant["model_input"]) != build_b4_prompt(
        direct_case["model_input"]
    ):
        raise IntegrationCheckError("B4 prompt used a compatibility-only state")

    return {
        "status": "PASS",
        "case_dialogue_action": "ANSWER",
        "fixture_only": True,
        "toy_b3_fit_performed": True,
        "real_or_future_benchmark_training_records": 0,
        "direct_b3_probabilities": direct_probabilities,
        "uncertain_b3_probabilities": uncertain_probabilities,
        "toy_thresholds": dict(TOY_THRESHOLDS),
        "direct_path": {
            "final_prediction_source": direct["metadata"]["final_prediction_source"],
            "fallback_triggered": False,
            "mock_provider_calls": calls_after_direct,
            "canonical_prediction_schema": True,
        },
        "uncertain_path": {
            "final_prediction_source": fallback["metadata"]["final_prediction_source"],
            "fallback_triggered": True,
            "mock_provider_calls": provider.call_count,
            "canonical_prediction_schema": True,
        },
        "primary_feature_profile": PRIMARY_PROFILE_NAME,
        "primary_fields": list(PRIMARY_FIELDS),
        "b0_context_state_invariant": True,
        "b4_prompt_context_state_invariant": True,
        "network_attempts": len(network_attempts),
        "network_calls": provider.network_call_count,
        "real_provider_calls": provider.real_provider_call_count,
        "paid_provider_calls": 0,
    }


def run_checks() -> dict[str, Any]:
    checks: dict[str, str] = {}
    details: dict[str, Any] = {}
    failures: list[dict[str, str]] = []

    def check(name: str, function: Callable[[], Any]) -> None:
        try:
            details[name] = function()
            checks[name] = "PASS"
        except Exception as exc:
            checks[name] = "FAIL"
            failures.append({"check": name, "error": f"{type(exc).__name__}: {exc}"})

    check("six_model_interfaces_coexist", verify_six_model_interfaces)
    check("unfrozen_research_choices_preserved", verify_unfrozen_research_choices)
    check("writer_documentation_amendment", verify_writer_amendment)
    check("toy_b3_to_p1_end_to_end", run_toy_b3_to_p1_smoke)

    smoke = details.get("toy_b3_to_p1_end_to_end")
    derived = {
        "canonical_answer_fixture": bool(smoke)
        and smoke["case_dialogue_action"] == "ANSWER"
        and smoke["fixture_only"],
        "canonical_b3_probability_axis": bool(smoke)
        and set(smoke["direct_b3_probabilities"]) == set(CAPABILITY_FIELDS),
        "confident_direct_b3_path": bool(smoke)
        and smoke["direct_path"]["final_prediction_source"] == "R2V2-B3_OVR"
        and smoke["direct_path"]["mock_provider_calls"] == 0,
        "uncertain_single_b4_fallback": bool(smoke)
        and smoke["uncertain_path"]["final_prediction_source"] == "R2V2-B4_LLM"
        and smoke["uncertain_path"]["mock_provider_calls"] == 1,
        "shared_primary_feature_profile": bool(smoke)
        and smoke["primary_feature_profile"] == PRIMARY_PROFILE_NAME
        and tuple(smoke["primary_fields"]) == PRIMARY_FIELDS,
        "zero_network_and_real_provider_calls": bool(smoke)
        and not any(
            smoke[field]
            for field in (
                "network_attempts",
                "network_calls",
                "real_provider_calls",
                "paid_provider_calls",
            )
        ),
    }
    for name, passed in derived.items():
        checks[name] = "PASS" if passed else "FAIL"
        if not passed:
            failures.append({"check": name, "error": "derived invariant failed"})

    return {
        "schema_version": "rq2-v2-stage1-integration-check-report-v1",
        "status": "PASS" if not failures else "FAIL",
        "check_count": len(checks),
        "pass_count": sum(value == "PASS" for value in checks.values()),
        "failure_count": len(failures),
        "checks": checks,
        "failures": failures,
        "details": details,
        "final_test_executed": False,
        "rq3_executed": False,
        "dataset_intake_performed": False,
        "human_queries_written": 0,
    }


def main() -> int:
    report = run_checks()
    print(json.dumps(report, indent=2, sort_keys=True))
    return 0 if report["status"] == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
