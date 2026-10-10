"""Offline structural validator for the frozen RQ3-0B4 protocol package."""

from __future__ import annotations

import ast
import json
from pathlib import Path
from typing import Callable

from .rq3_judge_request_builder import PRIMARY_CRITERIA
from .run_toy_harness import run_toy_harness


ROOT = Path(__file__).resolve().parent


class ValidationLedger:
    def __init__(self) -> None:
        self.passed: list[str] = []
        self.failed: list[str] = []

    def check(self, name: str, predicate: bool) -> None:
        (self.passed if predicate else self.failed).append(name)

    def run(self, name: str, operation: Callable[[], bool]) -> None:
        try:
            self.check(name, bool(operation()))
        except Exception:
            self.failed.append(name)


def _load(name: str):
    return json.loads((ROOT / name).read_text(encoding="utf-8"))


def validate() -> dict[str, object]:
    ledger = ValidationLedger()
    required = {
        "rq3_primary_eight_criterion_rubric_v1.json",
        "RQ3_PRIMARY_RUBRIC.md",
        "rq3_dimension_applicability_v1.json",
        "rq3_judge_prompt_frozen_v1.txt",
        "rq3_judge_response_schema_v1.json",
        "rq3_blinding_and_randomisation_protocol_v1.json",
        "rq3_statistical_analysis_contract_v1.json",
        "human_rating_packet_schema_v1.json",
        "HUMAN_RATER_GUIDE.md",
        "human_rater_attestation_A.md",
        "human_rater_attestation_B.md",
        "rq3_judge_request_builder.py",
        "rq3_judge_response_parser.py",
        "rq3_human_agreement.py",
        "rq3_human_packet_builder.py",
        "RQ3_EVALUATION_METHOD.md",
        "STATUS.md",
        "RQ3_0B4_OUTPUT_SHA256_MANIFEST.sha256",
    }
    ledger.check("required_outputs_exist", all((ROOT / name).is_file() for name in required))

    json_names = sorted(path.name for path in ROOT.glob("*.json"))
    for name in json_names:
        ledger.run(f"json_parse:{name}", lambda name=name: isinstance(_load(name), dict))

    rubric = _load("rq3_primary_eight_criterion_rubric_v1.json")
    ledger.check("exact_eight_criteria", tuple(rubric["criterion_order"]) == PRIMARY_CRITERIA)
    ledger.check("exact_eight_dimension_records", len(rubric["criteria"]) == 8)
    ledger.check(
        "all_five_anchors_present",
        all(set(item["behavioural_anchors"]) == {"1", "2", "3", "4", "5"} for item in rubric["criteria"]),
    )
    ledger.check(
        "always_applicable_exact",
        {
            item["criterion_name"]
            for item in rubric["criteria"]
            if item["applicability_class"] == "ALWAYS_APPLICABLE"
        }
        == {"CLARITY", "CONTEXT_AWARENESS", "RELIABILITY"},
    )
    ledger.check(
        "primary_mean_excludes_audits",
        rubric["secondary_technical_audits"]["excluded_from_primary_mean"] is True,
    )
    ledger.check(
        "unsupported_claim_count_is_integer_contract",
        rubric["secondary_technical_audits"]["UNSUPPORTED_CLAIM_COUNT"]["type"]
        == "non_negative_integer",
    )

    applicability = _load("rq3_dimension_applicability_v1.json")
    ledger.check("applicability_forbids_candidate", "candidate_response" in applicability["forbidden_derivation_inputs"])
    ledger.check("applicability_minimum_three", applicability["output_contract"]["minimum_applicable_primary_count"] == 3)

    schema = _load("rq3_judge_response_schema_v1.json")
    ledger.check("judge_schema_additional_properties_false", schema["additionalProperties"] is False)
    ledger.check("judge_schema_exact_fields", len(schema["required"]) == 14)
    ledger.check("judge_schema_count_nonnegative", schema["properties"]["unsupported_claim_count"]["minimum"] == 0)

    prompt = (ROOT / "rq3_judge_prompt_frozen_v1.txt").read_text(encoding="utf-8")
    ledger.check("one_prompt_placeholder", prompt.count("{{BLIND_JUDGE_REQUEST_JSON}}") == 1)
    ledger.check("prompt_no_verbosity_reward", "Do not reward length" in prompt)
    ledger.check("prompt_no_missing_evidence_assumption", "Do not assume missing RAG" in prompt)

    blinding = _load("rq3_blinding_and_randomisation_protocol_v1.json")
    ledger.check("judge_seed_exact", blinding["judge_randomisation_seed"] == 20260901)
    ledger.check("no_real_blinding_key", blinding["actual_blinding_key_status"] == "NOT_CREATED_OR_AUTHORIZED_IN_RQ3_0B4")
    ledger.check("lexical_condition_order_forbidden", blinding["answer_order_randomisation"]["lexical_condition_order_permitted"] is False)

    statistics = _load("rq3_statistical_analysis_contract_v1.json")
    ledger.check("family_cluster_unit", statistics["clustering_and_resampling_unit"] == "scenario_family_id")
    ledger.check("bootstrap_10000", statistics["interval_estimation"]["replicates"] == 10000)
    ledger.check("holm_frozen", statistics["multiplicity"]["method"].startswith("Holm"))
    ledger.check("oracle_guard_exact", statistics["oracle_gain_retention"]["near_zero_denominator_guard"]["absolute_threshold_rubric_points"] == 0.05)
    ledger.check("human_family_target", statistics["human_validation_sampling"]["minimum_eligible_families"] == 10)
    ledger.check("no_actual_human_ids", statistics["human_validation_sampling"]["actual_response_ids_selected_in_rq3_0b4"] == 0)

    forbidden_import_roots = {"openai", "anthropic", "requests", "httpx", "urllib3", "aiohttp"}
    imported_roots: set[str] = set()
    for path in ROOT.glob("*.py"):
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                imported_roots.update(alias.name.split(".")[0] for alias in node.names)
            elif isinstance(node, ast.ImportFrom) and node.module:
                imported_roots.add(node.module.split(".")[0])
    ledger.check("zero_provider_client_imports", not (imported_roots & forbidden_import_roots))

    harness = run_toy_harness()
    ledger.check("toy_harness_pass", harness["harness_status"] == "PASS_SYNTHETIC_TOY_ONLY")
    ledger.check("toy_zero_generation", harness["student_facing_responses_generated"] == 0)
    ledger.check("toy_zero_judge_calls", harness["llm_judge_calls"] == 0)
    ledger.check("toy_zero_provider_calls", harness["provider_calls"] == 0)
    ledger.check("toy_zero_human_ratings", harness["human_ratings_collected"] == 0)
    ledger.check("toy_zero_real_scores", harness["real_rq3_scores_read_or_computed"] == 0)

    return {
        "status": "PASS" if not ledger.failed else "FAIL",
        "passed": len(ledger.passed),
        "failed": len(ledger.failed),
        "total": len(ledger.passed) + len(ledger.failed),
        "failed_checks": ledger.failed,
    }


def main() -> int:
    result = validate()
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0 if result["status"] == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
