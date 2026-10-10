"""Run the frozen RQ2-V2 Stage 4J P1 Hybrid analysis offline.

The builder reads only frozen DEV artifacts already present in the repository.
It has no provider client, network path, TEST adapter, learned classifier, or
production integration.  Policy definitions and selection ordering come from
the immutable Stage 4J-0 files and :mod:`p1_protocol`.
"""

from __future__ import annotations

import argparse
from collections import Counter, defaultdict
import csv
from dataclasses import dataclass
from decimal import Decimal
import hashlib
import json
from pathlib import Path
import re
import subprocess
from typing import Any, Iterable, Mapping, Sequence

from . import p1_protocol as p1


TRACK_DIR = Path(__file__).resolve().parent
STAGE4_DIR = TRACK_DIR.parent
REPO_ROOT = TRACK_DIR.parents[2]
DEV_DIR = STAGE4_DIR / "dev_protocol"
TRACK_G_DIR = STAGE4_DIR / "track_g_b0_b1"
TRACK_H_DIR = STAGE4_DIR / "track_h_b2_b3"
TRACK_I_DIR = STAGE4_DIR / "track_i_b4"

STAGE4J_STARTING_HEAD = "92795f1d0bb92e1046b087bd843a415208fff6ae"
HISTORICAL_SOURCE_COMMIT = "fa3ba58fbd7abaecb0f7332312aade99bb2fc870"
SUCCESSFUL_SOURCE_COMMIT = "0382a3560137f0e0dece7845ed6da4446f307692"
HISTORICAL_INTEGRATED_COMMIT = "e497b20e1e4b5382e2f62351fd3affa91314fa09"
SUCCESSFUL_INTEGRATED_COMMIT = "22e5f0a174afb0552fea2b3804ce71ef5881a590"

FROZEN_STAGE4J0_HASHES = {
    "p1_candidate_policies_frozen_v1.json": "33de16b95f90847f0788c50914b32fbe403b952dc216b9c4f7a43ae14c7859cd",
    "p1_nested_selection_protocol_v1.json": "d62d9b6bceb435334effb4111d92434488b74d67f6552ea25376a5af6a23c90a",
    "p1_input_contract_v1.json": "93261a05a03d9b4a3889c2960f01309a69716dc266b1d8f4e55166dbcd10a434",
    "p1_output_contract_v1.json": "14a58b6c90965091a69d3da531966d97d201c52a7476b8b723281325abef4d4f",
    "P1_POLICY_METHOD.md": "6d7431092c07cb579072432102511b40a0f623ff6c28768dc6b35fbeb8a94b51",
}

B4_REQUIRED_HASHES = {
    "b4_dev_predictions_v2.csv": "f0e776492779341fd4e1feb6d11f2a915246162697f222b1c7c933882e552d39",
    "b4_dev_terminal_results_v2.jsonl": "867e62817d8cb4342eb7071532803af2bc8e96e65b05d70743f0304f59473abc",
    "b4_dev_attempt_records_v2.jsonl": "a8e8a66394d159e1af88a153654c63437176ba869dbf0c02f12c43ec1138b1a7",
    "b4_dev_usage_and_cost_v2.json": "503d079b8bebdd613eaaede7c10b7ff31e32e227c02f759a642efe29a8b84c1d",
    "b4_dev_metrics_v2.json": "50b9c2a6340daef5583d295c27f008cd2e8010f86addca34c2fa844aeffc3cb4",
    "b4_final_frozen_configuration_v2.json": "12a75dd33298f6e1078b326e7c922eb92f2675ee87c7f7858fdf19494072d470",
    "b4_response_schema_v2.json": "8017f1677e3ddc0bdd5042cff1c87e1e8ef4053da10b5c86da2cf45c35319876",
}

B4_IMMUTABLE_CONTEXT_HASHES = {
    "b4_prompt_template_frozen_v1.txt": "62dd0072b40f812bea9d2400bf5053c1d727187c47cab3c8777a341e0a185541",
    "b4_response_schema_v1.json": "9f364e920cfcca07a90580000196c85a6f801ef2e75c9c907bf820eea6a9aba2",
    "b4_fold_examples_v1.csv": "5834833e0d9af6520e858fc1061477ff80ff026b5ea42bbfd0133f51faf8916c",
    "b4_final_dev_examples_v1.csv": "34f12e80a654bb79a7103e35a14c5df058e4a54c8831c27d73756355754fb5b3",
    "b4_fold_prompt_hashes_v1.json": "d4a7f9084745a9a4c6eab19ea20d6006f23e619404cf698392e3bcacb93f0699",
    "b4_final_full_dev_prompt_package_v1.json": "245a4f74d2428017ab36fc5eaba41c6f617b5ec01c099153b23524a0d33734d5",
}

SOURCE_HASHES = {
    "dev_capability_gold_v1.csv": "8d3422198a99422b3e314c60819f3553ff27cd42394ed2d9f68c0eb3ce858b56",
    "dev_atomic_group_map_v1.csv": "f1ac8973c590155ee3730de194b4c2afd6d05531744bef70a163be2428d4bd6f",
    "dev_cv_folds_v1.csv": "2a3a4161c81bddfcfe51b238ac5940c64df87a25beed26e54671b64c76c5ab46",
    "b0_core_oof_predictions_v1.csv": "2dcf2f4e0694b45e53d9f79c7cdbb6b6eeb59cae7c28b399a4a02cfee13f1a58",
    "b1_core_oof_predictions_v1.csv": "3a0037363872df892561fae926f5f10fef67ac3ef327611af0c96dde138a0b6e",
    "b2_nested_oof_predictions_v1.csv": "1e82d8f5f30528b5334cd89ff9427c6a157a6b0ab42bc779d358ac4a5351ca76",
    "b3_nested_oof_predictions_v1.csv": "ccd013ee6157858f1508f4fac823fc4a339f530cc27bce3908600ce49a7df00f",
    "b3_nested_oof_probabilities_v1.csv": "8063d7949252316320f8ac2a2cdcea6239308886e143ce0ff33d97caf4121a40",
    "clarification_gate_frozen_v1.json": "ca411f9ef8711811b3aa5408b79e28463cef432fe3fc31bf106d3fa80a350438",
    "clarification_oof_predictions_v1.csv": "792308cbd4382466778721b6eafebd023a516e684ee19cd39483af1cbde72aa8",
}

EXPECTED_MODEL = "gpt-4o-mini-2024-07-18"
EXPECTED_PROMPT_SHA256 = "62dd0072b40f812bea9d2400bf5053c1d727187c47cab3c8777a341e0a185541"
EXPECTED_SCHEMA_V1_SHA256 = "9f364e920cfcca07a90580000196c85a6f801ef2e75c9c907bf820eea6a9aba2"
EXPECTED_SCHEMA_V2_SHA256 = B4_REQUIRED_HASHES["b4_response_schema_v2.json"]
EXPECTED_B4_STATUS = "FROZEN_AFTER_DEV_EXECUTION"

INPUT_PRICE_PER_MILLION = Decimal("0.15")
OUTPUT_PRICE_PER_MILLION = Decimal("0.60")
CAPABILITIES = p1.CAPABILITY_ORDER
CAPABILITY_SHORT = ("rag", "memory", "planning")
TEST_IDENTIFIER_PATTERN = re.compile(
    r"(?:^|[-_])(?:TEST|TST)(?:$|[-_])", re.IGNORECASE
)

GENERATED_OUTPUT_NAMES = (
    "p1_input_contract_v2.json",
    "p1_normalized_dev_records_v1.csv",
    "p1_normalized_dev_records_v1.jsonl",
    "p1_policy_case_matrix_v1.csv",
    "p1_outer_training_policy_metrics_v1.csv",
    "p1_outer_fold_policy_selection_v1.csv",
    "p1_nested_oof_predictions_v1.csv",
    "p1_nested_oof_case_audit_v1.csv",
    "p1_nested_metrics_v1.json",
    "p1_full_dev_policy_results_v1.csv",
    "p1_final_policy_frozen_v1.json",
    "p1_counterfactual_cost_v1.json",
    "p1_model_comparison_v1.csv",
    "p1_end_to_end_oof_predictions_v1.csv",
    "P1_DEV_RESULTS.md",
    "P1_HYBRID_COLLAPSE_AUDIT.md",
    "STATUS.md",
    "p1_output_manifest_v1.json",
)


class AnalysisError(RuntimeError):
    """Raised when any frozen Stage 4J input or invariant differs."""


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _load_json(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise AnalysisError(f"expected one JSON object: {path}")
    return value


def _load_jsonl(path: Path) -> list[dict[str, Any]]:
    return [
        json.loads(line)
        for line in path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]


def _load_csv(path: Path) -> list[dict[str, str]]:
    with path.open("r", encoding="utf-8", newline="") as handle:
        return list(csv.DictReader(handle))


def _atomic_write_text(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + ".tmp")
    temporary.write_text(text, encoding="utf-8")
    temporary.replace(path)


def _write_json(path: Path, value: Mapping[str, Any]) -> None:
    _atomic_write_text(path, json.dumps(value, indent=2, sort_keys=True) + "\n")


def _write_jsonl(path: Path, rows: Iterable[Mapping[str, Any]]) -> None:
    _atomic_write_text(
        path,
        "".join(
            json.dumps(dict(row), sort_keys=True, separators=(",", ":")) + "\n"
            for row in rows
        ),
    )


def _write_csv(
    path: Path, fieldnames: Sequence[str], rows: Iterable[Mapping[str, Any]]
) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + ".tmp")
    with temporary.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames, lineterminator="\n")
        writer.writeheader()
        writer.writerows(rows)
    temporary.replace(path)


def _parse_bool(value: Any) -> bool:
    if type(value) is bool:
        return value
    normalized = str(value).strip().lower()
    if normalized in {"true", "1", "yes"}:
        return True
    if normalized in {"false", "0", "no"}:
        return False
    raise AnalysisError(f"expected boolean value, observed {value!r}")


def _bool_text(value: bool) -> str:
    return "true" if value else "false"


def _signature(values: Sequence[bool]) -> p1.CapabilitySignature:
    if len(values) != 3:
        raise AnalysisError("complete capability signature must have three bits")
    return p1.CapabilitySignature(*values)


def _signature_text(signature: p1.CapabilitySignature) -> str:
    return "".join("1" if value else "0" for value in signature.bits)


def _safe_div(numerator: int | float, denominator: int | float) -> float:
    return round(float(numerator) / float(denominator), 12) if denominator else 0.0


def _decimal_cost(input_tokens: int, output_tokens: int) -> Decimal:
    return (
        Decimal(input_tokens) * INPUT_PRICE_PER_MILLION
        + Decimal(output_tokens) * OUTPUT_PRICE_PER_MILLION
    ) / Decimal(1_000_000)


def _format_cost(value: Decimal) -> str:
    return format(value, ".8f")


def _unique_by_id(
    rows: Sequence[Mapping[str, Any]], source_name: str
) -> dict[str, Mapping[str, Any]]:
    result: dict[str, Mapping[str, Any]] = {}
    for row in rows:
        case_id = str(row["annotation_case_id"])
        if not case_id or TEST_IDENTIFIER_PATTERN.search(case_id):
            raise AnalysisError(f"prohibited or empty case ID in {source_name}")
        if case_id in result:
            raise AnalysisError(f"duplicate case ID in {source_name}: {case_id}")
        result[case_id] = row
    return result


def _git(*arguments: str) -> str:
    result = subprocess.run(
        ["git", *arguments],
        cwd=REPO_ROOT,
        check=True,
        capture_output=True,
        text=True,
    )
    return result.stdout.strip()


def _patch_id(commit: str) -> str:
    shown = subprocess.run(
        ["git", "show", "--pretty=format:", "--binary", commit],
        cwd=REPO_ROOT,
        check=True,
        capture_output=True,
    )
    patched = subprocess.run(
        ["git", "patch-id", "--stable"],
        cwd=REPO_ROOT,
        input=shown.stdout,
        check=True,
        capture_output=True,
    )
    return patched.stdout.decode("utf-8").split()[0]


def verify_git_integration() -> dict[str, Any]:
    history = _git("rev-list", "--reverse", f"{STAGE4J_STARTING_HEAD}..HEAD").splitlines()
    if history[:2] != [HISTORICAL_INTEGRATED_COMMIT, SUCCESSFUL_INTEGRATED_COMMIT]:
        raise AnalysisError("Track I commits are not the first two commits in the required order")
    if _git("rev-parse", f"{HISTORICAL_INTEGRATED_COMMIT}^") != STAGE4J_STARTING_HEAD:
        raise AnalysisError("historical Track I integration parent differs")
    if _git("rev-parse", f"{SUCCESSFUL_INTEGRATED_COMMIT}^") != HISTORICAL_INTEGRATED_COMMIT:
        raise AnalysisError("successful Track I integration does not follow historical attempt")
    pairs = (
        (HISTORICAL_SOURCE_COMMIT, HISTORICAL_INTEGRATED_COMMIT),
        (SUCCESSFUL_SOURCE_COMMIT, SUCCESSFUL_INTEGRATED_COMMIT),
    )
    patch_ids = []
    for source, integrated in pairs:
        source_patch = _patch_id(source)
        integrated_patch = _patch_id(integrated)
        if source_patch != integrated_patch:
            raise AnalysisError(f"integrated patch differs from authorized source: {source}")
        patch_ids.append(
            {
                "source_commit": source,
                "integrated_commit": integrated,
                "stable_patch_id": source_patch,
            }
        )
    return {"status": "PASS", "ordered_integrations": patch_ids}


def verify_frozen_stage4j0() -> dict[str, Any]:
    files = []
    for name, expected in FROZEN_STAGE4J0_HASHES.items():
        observed = sha256_file(TRACK_DIR / name)
        if observed != expected:
            raise AnalysisError(f"frozen Stage 4J-0 hash mismatch: {name}")
        files.append({"name": name, "sha256": observed})
    candidates = _load_json(TRACK_DIR / "p1_candidate_policies_frozen_v1.json")
    eligible = candidates["eligible_policies"]
    diagnostics = candidates["diagnostic_policies"]
    if [row["policy_id"] for row in eligible] != list(p1.ELIGIBLE_POLICY_IDS):
        raise AnalysisError("eligible policy IDs differ from the frozen reference")
    if len(eligible) != 9 or len(diagnostics) != 1:
        raise AnalysisError("frozen policy inventory differs")
    if diagnostics[0]["policy_id"] != p1.DIAGNOSTIC_POLICY_ID:
        raise AnalysisError("diagnostic policy differs")
    return {"status": "PASS", "files": files, "eligible": 9, "diagnostic": 1}


def verify_b4_binding() -> dict[str, Any]:
    artifact_rows = []
    for name, expected in {
        **B4_REQUIRED_HASHES,
        **B4_IMMUTABLE_CONTEXT_HASHES,
    }.items():
        path = TRACK_I_DIR / name
        if not path.is_file():
            raise AnalysisError(f"required B4 artifact missing: {name}")
        observed = sha256_file(path)
        if observed != expected:
            raise AnalysisError(f"required B4 artifact hash mismatch: {name}")
        artifact_rows.append(
            {"name": name, "sha256": observed, "size_bytes": path.stat().st_size}
        )

    config = _load_json(TRACK_I_DIR / "b4_final_frozen_configuration_v2.json")
    metrics = _load_json(TRACK_I_DIR / "b4_dev_metrics_v2.json")
    usage = _load_json(TRACK_I_DIR / "b4_dev_usage_and_cost_v2.json")
    schema_v1 = _load_json(TRACK_I_DIR / "b4_response_schema_v1.json")
    schema_v2 = _load_json(TRACK_I_DIR / "b4_response_schema_v2.json")
    predictions = _load_csv(TRACK_I_DIR / "b4_dev_predictions_v2.csv")
    terminals = _load_jsonl(TRACK_I_DIR / "b4_dev_terminal_results_v2.jsonl")
    attempts = _load_jsonl(TRACK_I_DIR / "b4_dev_attempt_records_v2.jsonl")

    if config.get("B4_MODEL_STATUS") != EXPECTED_B4_STATUS:
        raise AnalysisError("B4 status differs")
    if config.get("model_snapshot") != EXPECTED_MODEL:
        raise AnalysisError("B4 model snapshot differs")
    if config.get("prompt_sha256") != EXPECTED_PROMPT_SHA256:
        raise AnalysisError("B4 prompt hash differs")
    if config.get("response_schema_v2_sha256") != EXPECTED_SCHEMA_V2_SHA256:
        raise AnalysisError("B4 schema V2 binding differs")
    fold_registry = _load_json(TRACK_I_DIR / "b4_fold_prompt_hashes_v1.json")
    configured_fold_examples = config.get("fold_specific_examples")
    if configured_fold_examples != fold_registry.get("folds"):
        raise AnalysisError("B4 fold example or prompt-package binding differs")
    if config.get("full_dev_examples") != fold_registry.get("full_dev"):
        raise AnalysisError("B4 full-DEV example or prompt-package binding differs")
    if len(predictions) != 64 or len(terminals) != 64 or len(attempts) != 64:
        raise AnalysisError("successful B4 artifact count differs from 64")
    if len(_unique_by_id(predictions, "B4 predictions")) != 64:
        raise AnalysisError("B4 prediction IDs differ")
    if any(row["terminal_status"] != "VALID_PREDICTION" for row in predictions):
        raise AnalysisError("one or more B4 predictions is invalid")
    if any(row["returned_model"] != EXPECTED_MODEL for row in predictions):
        raise AnalysisError("one or more returned B4 models differs")
    if any(record["terminal_status"] != "VALID_PREDICTION" for record in terminals):
        raise AnalysisError("one or more terminal B4 results is invalid")
    if any(record.get("provider_error") for record in terminals):
        raise AnalysisError("successful B4 run contains a provider error")
    coverage = metrics["coverage"]
    if (
        coverage["valid_predictions"] != 64
        or coverage["invalid_structured_output_count"] != 0
        or coverage["provider_error_count"] != 0
    ):
        raise AnalysisError("B4 metrics coverage differs")

    semantic_keys = {"type", "properties", "required", "additionalProperties"}
    if {key: schema_v1[key] for key in semantic_keys} != schema_v2:
        raise AnalysisError("schema V2 changes the three-boolean semantic output")
    removed = sorted(set(schema_v1) - set(schema_v2))
    if removed != ["$schema", "maxProperties", "minProperties", "title"]:
        raise AnalysisError("schema V2 repair differs from declared metadata removal")
    historical = _load_json(
        TRACK_I_DIR / "b4_historical_failed_run_preservation_v1.json"
    )
    if (
        historical.get("historical_classification")
        != "PRE_MODEL_REQUEST_CONFIGURATION_FAILURE"
        or historical.get("historical_model_response_present") is not False
        or historical.get("included_in_r1_performance_metrics") is not False
    ):
        raise AnalysisError("historical failed request classification differs")
    all_strings = json.dumps(
        {"predictions": predictions, "terminals": terminals, "attempts": attempts},
        sort_keys=True,
    )
    if re.search(r"R2V2-(?:TEST|TST)-[A-Za-z0-9]", all_strings, re.IGNORECASE):
        raise AnalysisError("B4 artifacts contain a TEST identifier")

    actual_usage = usage["actual_provider_usage_new_r1_run_only"]
    summed_input = sum(int(record["input_tokens"]) for record in attempts)
    summed_output = sum(int(record["output_tokens"]) for record in attempts)
    summed_total = sum(int(record["total_tokens"]) for record in attempts)
    if (
        summed_input != int(actual_usage["input_tokens"])
        or summed_output != int(actual_usage["output_tokens"])
        or summed_total != int(actual_usage["total_tokens"])
        or summed_input + summed_output != summed_total
        or _decimal_cost(summed_input, summed_output)
        != Decimal(str(usage["approximate_cost_usd"]["total"]))
    ):
        raise AnalysisError("B4 attempt-token or cost summation differs")
    return {
        "status": "PASS",
        "artifacts": artifact_rows,
        "model_snapshot": EXPECTED_MODEL,
        "prompt_sha256": EXPECTED_PROMPT_SHA256,
        "schema_v1_sha256": EXPECTED_SCHEMA_V1_SHA256,
        "schema_v2_sha256": EXPECTED_SCHEMA_V2_SHA256,
        "schema_metadata_removed": removed,
        "valid_predictions": 64,
        "invalid_structured_outputs": 0,
        "provider_errors": 0,
        "execution_status": EXPECTED_B4_STATUS,
        "actual_successful_run_usage": actual_usage,
        "actual_successful_run_cost_usd": usage["approximate_cost_usd"]["total"],
        "historical_failed_request": {
            "classification": historical["historical_classification"],
            "physical_attempts": historical["historical_physical_attempts"],
            "counted_as_prediction": False,
            "counted_in_metrics": False,
            "counted_in_successful_cost": False,
        },
    }


@dataclass(frozen=True)
class DevRecord:
    annotation_case_id: str
    scenario_family_id: str
    outer_fold: str
    current_page: str
    dev_atomic_component_id: str
    dev_contrast_group_id: str
    dev_contrast_axis: str
    gold: p1.CapabilitySignature
    b0: p1.CapabilitySignature
    b1: p1.CapabilitySignature
    b2: p1.CapabilitySignature
    b3: p1.CapabilitySignature
    b3_probabilities: tuple[float, float, float]
    b3_thresholds: tuple[float, float, float]
    b4: p1.CapabilitySignature
    b4_terminal_status: str
    b4_attempts_used: int
    b4_input_tokens: int
    b4_output_tokens: int
    b4_total_tokens: int
    b4_cost_usd: Decimal
    b4_returned_model: str

    def p1_case(self) -> p1.P1Case:
        return p1.P1Case(
            annotation_case_id=self.annotation_case_id,
            outer_fold=self.outer_fold,
            gold=self.gold,
            b0=self.b0,
            b2=self.b2,
            b3=self.b3,
            b3_probabilities=self.b3_probabilities,
            b3_thresholds=self.b3_thresholds,
            b4=self.b4,
            b4_valid=True,
            b4_terminal_status="VALID",
            scenario_family_id=self.scenario_family_id,
            current_page=self.current_page,
        )


@dataclass(frozen=True)
class AnalysedDecision:
    record: DevRecord
    policy_id: str
    fallback_triggered: bool
    trigger_reason: str
    selected_router: str
    output: p1.CapabilitySignature
    fallback_status: str


def _source_paths() -> dict[str, Path]:
    return {
        "dev_capability_gold_v1.csv": DEV_DIR / "dev_capability_gold_v1.csv",
        "dev_atomic_group_map_v1.csv": DEV_DIR / "dev_atomic_group_map_v1.csv",
        "dev_cv_folds_v1.csv": DEV_DIR / "dev_cv_folds_v1.csv",
        "b0_core_oof_predictions_v1.csv": TRACK_G_DIR / "b0_core_oof_predictions_v1.csv",
        "b1_core_oof_predictions_v1.csv": TRACK_G_DIR / "b1_core_oof_predictions_v1.csv",
        "b2_nested_oof_predictions_v1.csv": TRACK_H_DIR / "b2_nested_oof_predictions_v1.csv",
        "b3_nested_oof_predictions_v1.csv": TRACK_H_DIR / "b3_nested_oof_predictions_v1.csv",
        "b3_nested_oof_probabilities_v1.csv": TRACK_H_DIR / "b3_nested_oof_probabilities_v1.csv",
        "clarification_gate_frozen_v1.json": TRACK_G_DIR / "clarification_gate_frozen_v1.json",
        "clarification_oof_predictions_v1.csv": TRACK_G_DIR / "clarification_oof_predictions_v1.csv",
    }


def verify_source_hashes() -> list[dict[str, Any]]:
    result = []
    for name, path in _source_paths().items():
        observed = sha256_file(path)
        if observed != SOURCE_HASHES[name]:
            raise AnalysisError(f"source prediction or protocol hash changed: {name}")
        result.append(
            {
                "name": name,
                "path": path.relative_to(REPO_ROOT).as_posix(),
                "sha256": observed,
                "size_bytes": path.stat().st_size,
            }
        )
    return result


def _row_signature(
    row: Mapping[str, Any], fields: Sequence[str]
) -> p1.CapabilitySignature:
    return _signature([_parse_bool(row[field]) for field in fields])


def load_normalized_records() -> list[DevRecord]:
    verify_source_hashes()
    gold_rows = [
        row
        for row in _load_csv(DEV_DIR / "dev_capability_gold_v1.csv")
        if row["partition"] == "DEV" and row["final_dialogue_action"] == "ANSWER"
    ]
    gold = _unique_by_id(gold_rows, "DEV Gold")
    if len(gold) != 64:
        raise AnalysisError("human DEV Gold is not exactly 64 ANSWER cases")

    groups = _unique_by_id(
        [
            row
            for row in _load_csv(DEV_DIR / "dev_atomic_group_map_v1.csv")
            if row["annotation_case_id"] in gold
        ],
        "DEV grouping",
    )
    fold_rows = _load_csv(DEV_DIR / "dev_cv_folds_v1.csv")
    validation_rows = [
        row
        for row in fold_rows
        if row["fold_role"] == "VALIDATION" and row["annotation_case_id"] in gold
    ]
    folds = _unique_by_id(validation_rows, "DEV outer-fold validation assignments")

    b0 = _unique_by_id(_load_csv(TRACK_G_DIR / "b0_core_oof_predictions_v1.csv"), "B0")
    b1 = _unique_by_id(_load_csv(TRACK_G_DIR / "b1_core_oof_predictions_v1.csv"), "B1")
    b2 = _unique_by_id(_load_csv(TRACK_H_DIR / "b2_nested_oof_predictions_v1.csv"), "B2")
    b3 = _unique_by_id(_load_csv(TRACK_H_DIR / "b3_nested_oof_predictions_v1.csv"), "B3")
    b3_prob = _unique_by_id(
        _load_csv(TRACK_H_DIR / "b3_nested_oof_probabilities_v1.csv"), "B3 probabilities"
    )
    b4 = _unique_by_id(_load_csv(TRACK_I_DIR / "b4_dev_predictions_v2.csv"), "B4")
    terminals = _unique_by_id(
        _load_jsonl(TRACK_I_DIR / "b4_dev_terminal_results_v2.jsonl"),
        "B4 terminal results",
    )
    attempt_rows = _load_jsonl(TRACK_I_DIR / "b4_dev_attempt_records_v2.jsonl")
    attempts_by_case: dict[str, list[Mapping[str, Any]]] = defaultdict(list)
    for row in attempt_rows:
        attempts_by_case[str(row["annotation_case_id"])].append(row)

    expected_ids = set(gold)
    sources = {
        "grouping": groups,
        "folds": folds,
        "B0": b0,
        "B1": b1,
        "B2": b2,
        "B3": b3,
        "B3 probabilities": b3_prob,
        "B4": b4,
        "B4 terminal results": terminals,
        "B4 attempts": attempts_by_case,
    }
    for name, source in sources.items():
        if set(source) != expected_ids:
            raise AnalysisError(f"64-case join mismatch for {name}")

    records: list[DevRecord] = []
    for case_id in sorted(expected_ids, key=lambda value: value.encode("utf-8")):
        gold_row = gold[case_id]
        group_row = groups[case_id]
        fold_row = folds[case_id]
        b0_row = b0[case_id]
        b1_row = b1[case_id]
        b2_row = b2[case_id]
        b3_row = b3[case_id]
        probability_row = b3_prob[case_id]
        b4_row = b4[case_id]
        terminal_row = terminals[case_id]
        attempts = attempts_by_case[case_id]

        family_values = {
            str(row["scenario_family_id"])
            for row in (gold_row, group_row, fold_row, b0_row, b1_row, b2_row, b3_row, probability_row)
        }
        page_values = {
            str(row["current_page"])
            for row in (gold_row, group_row, fold_row, b0_row, b1_row, b2_row, b3_row, probability_row)
        }
        fold_values = {
            str(fold_row["fold_id"]),
            str(b0_row["outer_fold"]),
            str(b1_row["outer_fold"]),
            str(b2_row["outer_fold"]),
            str(b3_row["outer_fold"]),
            str(probability_row["outer_fold"]),
            str(b4_row["fold_id"]),
            str(terminal_row["fold_id"]),
        }
        if len(family_values) != 1 or len(page_values) != 1 or len(fold_values) != 1:
            raise AnalysisError(f"metadata mismatch for joined case: {case_id}")
        outer_fold = next(iter(fold_values))
        if outer_fold not in p1.OUTER_FOLDS:
            raise AnalysisError(f"unknown outer fold for case: {case_id}")

        gold_signature = _row_signature(
            gold_row,
            ("final_rag_required", "final_memory_required", "final_planning_required"),
        )
        b0_signature = _row_signature(
            b0_row,
            ("predicted_rag_required", "predicted_memory_required", "predicted_planning_required"),
        )
        b1_signature = _row_signature(
            b1_row,
            ("predicted_rag_required", "predicted_memory_required", "predicted_planning_required"),
        )
        b2_signature = _row_signature(
            b2_row, ("predicted_rag", "predicted_memory", "predicted_planning")
        )
        b3_signature = _row_signature(
            b3_row, ("predicted_rag", "predicted_memory", "predicted_planning")
        )
        probabilities = tuple(
            float(probability_row[f"{name}_probability"]) for name in CAPABILITY_SHORT
        )
        thresholds = tuple(
            float(probability_row[f"{name}_threshold"]) for name in CAPABILITY_SHORT
        )
        probability_prediction = _signature(
            [
                _parse_bool(probability_row[f"{name}_prediction"])
                for name in CAPABILITY_SHORT
            ]
        )
        threshold_prediction = _signature(
            [probability >= threshold for probability, threshold in zip(probabilities, thresholds, strict=True)]
        )
        if probability_prediction != b3_signature or threshold_prediction != b3_signature:
            raise AnalysisError(f"B3 probability/threshold prediction mismatch: {case_id}")

        for source_row, field_names in (
            (b0_row, ("gold_rag_required", "gold_memory_required", "gold_planning_required")),
            (b1_row, ("gold_rag_required", "gold_memory_required", "gold_planning_required")),
            (b2_row, ("gold_rag", "gold_memory", "gold_planning")),
            (b3_row, ("gold_rag", "gold_memory", "gold_planning")),
        ):
            if _row_signature(source_row, field_names) != gold_signature:
                raise AnalysisError(f"source Gold mismatch for case: {case_id}")

        if (
            b4_row["terminal_status"] != "VALID_PREDICTION"
            or terminal_row["terminal_status"] != "VALID_PREDICTION"
            or terminal_row.get("provider_error")
            or b4_row["returned_model"] != EXPECTED_MODEL
        ):
            raise AnalysisError(f"invalid B4 result for case: {case_id}")
        b4_signature = _row_signature(
            b4_row, ("rag_required", "memory_required", "planning_required")
        )
        terminal_prediction = terminal_row["prediction"]
        if _signature([bool(terminal_prediction[name]) for name in CAPABILITIES]) != b4_signature:
            raise AnalysisError(f"B4 terminal/prediction mismatch: {case_id}")
        if len(attempts) != int(terminal_row["attempts_used"]):
            raise AnalysisError(f"B4 attempt count mismatch: {case_id}")
        input_tokens = sum(int(row["input_tokens"]) for row in attempts)
        output_tokens = sum(int(row["output_tokens"]) for row in attempts)
        total_tokens = sum(int(row["total_tokens"]) for row in attempts)
        if input_tokens + output_tokens != total_tokens:
            raise AnalysisError(f"B4 token arithmetic mismatch: {case_id}")

        records.append(
            DevRecord(
                annotation_case_id=case_id,
                scenario_family_id=next(iter(family_values)),
                outer_fold=outer_fold,
                current_page=next(iter(page_values)),
                dev_atomic_component_id=str(group_row["dev_atomic_component_id"]),
                dev_contrast_group_id=str(group_row["dev_contrast_group_id"]),
                dev_contrast_axis=str(group_row["dev_contrast_axis"]),
                gold=gold_signature,
                b0=b0_signature,
                b1=b1_signature,
                b2=b2_signature,
                b3=b3_signature,
                b3_probabilities=probabilities,  # type: ignore[arg-type]
                b3_thresholds=thresholds,  # type: ignore[arg-type]
                b4=b4_signature,
                b4_terminal_status="VALID_PREDICTION",
                b4_attempts_used=len(attempts),
                b4_input_tokens=input_tokens,
                b4_output_tokens=output_tokens,
                b4_total_tokens=total_tokens,
                b4_cost_usd=_decimal_cost(input_tokens, output_tokens),
                b4_returned_model=str(b4_row["returned_model"]),
            )
        )
    if Counter(record.outer_fold for record in records) != Counter(
        {fold: 16 for fold in p1.OUTER_FOLDS}
    ):
        raise AnalysisError("outer-fold ANSWER counts differ from 16 each")
    return records


def _margin_hits(record: DevRecord, width: Decimal) -> list[str]:
    hits = []
    for capability, probability, threshold in zip(
        CAPABILITIES,
        record.b3_probabilities,
        record.b3_thresholds,
        strict=True,
    ):
        if abs(Decimal(str(probability)) - Decimal(str(threshold))) <= width:
            hits.append(capability)
    return hits


def trigger_reason(policy_id: str, record: DevRecord) -> str:
    if policy_id == "P1-C00-B3-DIRECT":
        return "NEVER_FALLBACK"
    if policy_id in p1.MARGIN_WIDTHS:
        width = p1.MARGIN_WIDTHS[policy_id]
        hits = _margin_hits(record, width)
        suffix = str(width).replace("0.", "")
        return (
            f"ANY_LABEL_MARGIN_{suffix}:" + "|".join(hits)
            if hits
            else f"NO_LABEL_MARGIN_{suffix}"
        )
    if policy_id == "P1-C04-B2-B3-DISAGREEMENT":
        differences = [
            capability
            for capability, left, right in zip(
                CAPABILITIES, record.b2.bits, record.b3.bits, strict=True
            )
            if left != right
        ]
        return (
            "B2_B3_DISAGREEMENT:" + "|".join(differences)
            if differences
            else "B2_B3_IDENTICAL"
        )
    if policy_id == "P1-C05-B0-B3-DISAGREEMENT":
        differences = [
            capability
            for capability, left, right in zip(
                CAPABILITIES, record.b0.bits, record.b3.bits, strict=True
            )
            if left != right
        ]
        return (
            "B0_B3_DISAGREEMENT:" + "|".join(differences)
            if differences
            else "B0_B3_IDENTICAL"
        )
    if policy_id == "P1-C06-MARGIN010-OR-B2B3":
        reasons = []
        hits = _margin_hits(record, Decimal("0.10"))
        if hits:
            reasons.append("MARGIN010:" + "|".join(hits))
        if record.b2 != record.b3:
            reasons.append("B2_B3_DISAGREEMENT")
        return ";".join(reasons) if reasons else "NO_MARGIN010_OR_B2B3_DISAGREEMENT"
    if policy_id == "P1-C07-MARGIN010-OR-B0B3":
        reasons = []
        hits = _margin_hits(record, Decimal("0.10"))
        if hits:
            reasons.append("MARGIN010:" + "|".join(hits))
        if record.b0 != record.b3:
            reasons.append("B0_B3_DISAGREEMENT")
        return ";".join(reasons) if reasons else "NO_MARGIN010_OR_B0B3_DISAGREEMENT"
    if policy_id == "P1-C08-NONUNANIMOUS":
        if record.b0 == record.b2 == record.b3:
            return "B0_B2_B3_UNANIMOUS"
        return (
            f"NONUNANIMOUS:B0={_signature_text(record.b0)};"
            f"B2={_signature_text(record.b2)};B3={_signature_text(record.b3)}"
        )
    if policy_id == p1.DIAGNOSTIC_POLICY_ID:
        return "ALL_B4_DIAGNOSTIC"
    raise AnalysisError(f"unknown frozen policy: {policy_id}")


def analyse_policy(policy_id: str, record: DevRecord) -> AnalysedDecision:
    decision = p1.apply_policy(policy_id, record.p1_case())
    reason = trigger_reason(policy_id, record)
    if decision.fallback_triggered != p1.should_fallback(policy_id, record.p1_case()):
        raise AnalysisError("trigger implementation differs from frozen semantics")
    if decision.output not in {record.b3, record.b4}:
        raise AnalysisError("label-level B3/B4 mixing detected")
    return AnalysedDecision(
        record=record,
        policy_id=policy_id,
        fallback_triggered=decision.fallback_triggered,
        trigger_reason=reason,
        selected_router=decision.selected_router,
        output=decision.output,
        fallback_status=decision.fallback_outcome,
    )


def _prediction_map(
    decisions: Sequence[AnalysedDecision],
) -> dict[str, p1.CapabilitySignature]:
    result = {decision.record.annotation_case_id: decision.output for decision in decisions}
    if len(result) != len(decisions):
        raise AnalysisError("duplicate decision case IDs")
    return result


def core_metrics(
    records: Sequence[DevRecord],
    predictions: Mapping[str, p1.CapabilitySignature],
) -> dict[str, Any]:
    if not records:
        return {
            "status": "NOT_COMPUTABLE_EMPTY_SUBSET",
            "case_count": 0,
            "macro_f1": None,
            "micro_f1": None,
            "micro_precision": None,
            "micro_recall": None,
            "per_label": {
                capability: {
                    "tp": 0,
                    "fp": 0,
                    "fn": 0,
                    "tn": 0,
                    "precision": None,
                    "recall": None,
                    "f1": None,
                }
                for capability in CAPABILITIES
            },
            "exact_capability_set_match": None,
            "exact_capability_set_correct_count": 0,
            "example_based_f1": None,
            "jaccard": None,
            "hamming_loss": None,
            "under_routing": {
                "case_count": 0,
                "case_rate": None,
                "label_decision_count": 0,
                "label_decision_rate": None,
            },
            "over_routing": {
                "case_count": 0,
                "case_rate": None,
                "label_decision_count": 0,
                "label_decision_rate": None,
            },
        }
    ids = [record.annotation_case_id for record in records]
    if set(ids) != set(predictions):
        raise AnalysisError("metric predictions do not exactly match metric records")
    per_label: dict[str, Any] = {}
    pooled_tp = pooled_fp = pooled_fn = pooled_tn = 0
    for column, capability in enumerate(CAPABILITIES):
        tp = fp = fn = tn = 0
        for record in records:
            truth = record.gold.bits[column]
            predicted = predictions[record.annotation_case_id].bits[column]
            if truth and predicted:
                tp += 1
            elif not truth and predicted:
                fp += 1
            elif truth and not predicted:
                fn += 1
            else:
                tn += 1
        precision = _safe_div(tp, tp + fp)
        recall = _safe_div(tp, tp + fn)
        f1 = _safe_div(2 * precision * recall, precision + recall)
        per_label[capability] = {
            "tp": tp,
            "fp": fp,
            "fn": fn,
            "tn": tn,
            "precision": precision,
            "recall": recall,
            "f1": f1,
        }
        pooled_tp += tp
        pooled_fp += fp
        pooled_fn += fn
        pooled_tn += tn

    exact = hamming_errors = under_cases = over_cases = 0
    under_labels = over_labels = 0
    example_f1_values: list[float] = []
    jaccard_values: list[float] = []
    for record in records:
        prediction = predictions[record.annotation_case_id]
        exact += int(prediction == record.gold)
        gold_set = {index for index, value in enumerate(record.gold.bits) if value}
        pred_set = {index for index, value in enumerate(prediction.bits) if value}
        intersection = len(gold_set & pred_set)
        combined = len(gold_set) + len(pred_set)
        union = len(gold_set | pred_set)
        example_f1_values.append(1.0 if not combined else 2.0 * intersection / combined)
        jaccard_values.append(1.0 if not union else intersection / union)
        misses = len(gold_set - pred_set)
        extras = len(pred_set - gold_set)
        hamming_errors += misses + extras
        under_labels += misses
        over_labels += extras
        under_cases += int(misses > 0)
        over_cases += int(extras > 0)

    micro_precision = _safe_div(pooled_tp, pooled_tp + pooled_fp)
    micro_recall = _safe_div(pooled_tp, pooled_tp + pooled_fn)
    return {
        "status": "COMPUTED",
        "case_count": len(records),
        "macro_f1": round(sum(row["f1"] for row in per_label.values()) / 3, 12),
        "micro_f1": _safe_div(
            2 * micro_precision * micro_recall, micro_precision + micro_recall
        ),
        "micro_precision": micro_precision,
        "micro_recall": micro_recall,
        "per_label": per_label,
        "exact_capability_set_match": _safe_div(exact, len(records)),
        "exact_capability_set_correct_count": exact,
        "example_based_f1": round(sum(example_f1_values) / len(records), 12),
        "jaccard": round(sum(jaccard_values) / len(records), 12),
        "hamming_loss": _safe_div(hamming_errors, len(records) * 3),
        "under_routing": {
            "case_count": under_cases,
            "case_rate": _safe_div(under_cases, len(records)),
            "label_decision_count": under_labels,
            "label_decision_rate": _safe_div(under_labels, len(records) * 3),
        },
        "over_routing": {
            "case_count": over_cases,
            "case_rate": _safe_div(over_cases, len(records)),
            "label_decision_count": over_labels,
            "label_decision_rate": _safe_div(over_labels, len(records) * 3),
        },
    }


def family_metrics(
    records: Sequence[DevRecord],
    predictions: Mapping[str, p1.CapabilitySignature],
) -> dict[str, Any]:
    families: dict[str, list[DevRecord]] = defaultdict(list)
    for record in records:
        families[record.scenario_family_id].append(record)
    malformed = [family for family, rows in families.items() if len(rows) != 2]
    if malformed:
        raise AnalysisError("family metric population contains incomplete families")
    both_exact = consistent = 0
    for rows in families.values():
        signatures = {predictions[row.annotation_case_id] for row in rows}
        consistent += int(len(signatures) == 1)
        both_exact += int(
            all(predictions[row.annotation_case_id] == row.gold for row in rows)
        )
    count = len(families)
    return {
        "family_count": count,
        "both_utterances_exact_correct_count": both_exact,
        "both_utterances_exact_correct_rate": _safe_div(both_exact, count),
        "prediction_consistent_count": consistent,
        "prediction_consistency_rate": _safe_div(consistent, count),
    }


def contrast_metrics(
    records: Sequence[DevRecord],
    predictions: Mapping[str, p1.CapabilitySignature],
) -> dict[str, Any]:
    groups: dict[tuple[str, str], list[DevRecord]] = defaultdict(list)
    for record in records:
        if record.dev_contrast_group_id and record.dev_contrast_axis in {
            "RAG",
            "MEMORY",
            "PLANNING",
        }:
            groups[(record.dev_contrast_group_id, record.dev_contrast_axis)].append(record)
    details = []
    within_family_consistent = consistent = gold_pattern = 0
    for (group_id, axis), rows in sorted(groups.items()):
        families: dict[str, list[DevRecord]] = defaultdict(list)
        for record in rows:
            families[record.scenario_family_id].append(record)
        if len(families) != 2 or any(len(items) != 2 for items in families.values()):
            raise AnalysisError(f"malformed capability contrast group: {group_id}")
        predicted_family: dict[str, p1.CapabilitySignature] = {}
        gold_family: dict[str, p1.CapabilitySignature] = {}
        internally_consistent = True
        for family, items in families.items():
            signatures = {
                predictions[item.annotation_case_id] for item in items
            }
            gold_signatures = {item.gold for item in items}
            if len(signatures) != 1 or len(gold_signatures) != 1:
                internally_consistent = False
            else:
                predicted_family[family] = next(iter(signatures))
                gold_family[family] = next(iter(gold_signatures))
        within_family_consistent += int(internally_consistent)
        contrast_matched = False
        if internally_consistent:
            left, right = sorted(families)
            gold_delta = tuple(
                int(right_value) - int(left_value)
                for left_value, right_value in zip(
                    gold_family[left].bits, gold_family[right].bits, strict=True
                )
            )
            predicted_delta = tuple(
                int(right_value) - int(left_value)
                for left_value, right_value in zip(
                    predicted_family[left].bits,
                    predicted_family[right].bits,
                    strict=True,
                )
            )
            contrast_matched = predicted_delta == gold_delta
        consistent += int(contrast_matched)
        matched = internally_consistent and predicted_family == gold_family
        gold_pattern += int(matched)
        details.append(
            {
                "contrast_group_id": group_id,
                "axis": axis,
                "family_count": len(families),
                "utterance_count": len(rows),
                "predicted_within_family_consistent": internally_consistent,
                "gold_contrast_change_vector_matched": contrast_matched,
                "gold_family_pattern_matched": matched,
            }
        )
    total = len(groups)
    return {
        "definition": (
            "Capability-axis groups only. Contrast consistency requires internally "
            "consistent family predictions and an exact match to the frozen pairwise "
            "capability-change vector; Gold-pattern match additionally requires both "
            "complete family signatures to equal frozen Gold."
        ),
        "eligible_contrast_groups": total,
        "within_family_prediction_consistent_groups": within_family_consistent,
        "within_family_prediction_consistency_rate": _safe_div(
            within_family_consistent, total
        ),
        "consistent_contrast_groups": consistent,
        "contrast_consistency_rate": _safe_div(consistent, total),
        "gold_pattern_matched_groups": gold_pattern,
        "gold_pattern_match_rate": _safe_div(gold_pattern, total),
        "groups": details,
    }


def prediction_distribution(
    predictions: Mapping[str, p1.CapabilitySignature],
) -> dict[str, Any]:
    signature_counts = Counter(_signature_text(value) for value in predictions.values())
    capability_counts = [sum(value.bits) for value in predictions.values()]
    return {
        "case_count": len(predictions),
        "mean_predicted_capability_count": round(
            sum(capability_counts) / len(capability_counts), 12
        ),
        "capability_count_distribution": {
            str(value): capability_counts.count(value) for value in range(4)
        },
        "signature_distribution": {
            signature: signature_counts.get(signature, 0)
            for signature in (f"{value:03b}" for value in range(8))
        },
    }


def stratified_metrics(
    records: Sequence[DevRecord],
    predictions: Mapping[str, p1.CapabilitySignature],
    attribute: str,
) -> dict[str, Any]:
    groups: dict[str, list[DevRecord]] = defaultdict(list)
    for record in records:
        groups[str(getattr(record, attribute))].append(record)
    return {
        name: core_metrics(
            rows,
            {row.annotation_case_id: predictions[row.annotation_case_id] for row in rows},
        )
        for name, rows in sorted(groups.items())
    }


def full_metrics(
    records: Sequence[DevRecord], decisions: Sequence[AnalysedDecision]
) -> dict[str, Any]:
    predictions = _prediction_map(decisions)
    core = core_metrics(records, predictions)
    fallback_count = sum(decision.fallback_triggered for decision in decisions)
    valid_b4 = sum(
        decision.fallback_triggered and decision.selected_router == "B4"
        for decision in decisions
    )
    failed = sum(
        decision.fallback_status == "FALLBACK_FAILED_USED_B3" for decision in decisions
    )
    direct_records = [
        decision.record for decision in decisions if not decision.fallback_triggered
    ]
    fallback_records = [
        decision.record for decision in decisions if decision.fallback_triggered
    ]
    valid_fallback_records = [
        decision.record
        for decision in decisions
        if decision.fallback_triggered and decision.selected_router == "B4"
    ]
    failed_records = [
        decision.record
        for decision in decisions
        if decision.fallback_status == "FALLBACK_FAILED_USED_B3"
    ]

    def subset_metrics(subset: Sequence[DevRecord]) -> dict[str, Any]:
        subset_predictions = {
            record.annotation_case_id: predictions[record.annotation_case_id]
            for record in subset
        }
        return core_metrics(subset, subset_predictions)

    result = dict(core)
    result.update(
        {
            "fallback_count": fallback_count,
            "fallback_rate": _safe_div(fallback_count, len(records)),
            "valid_b4_fallback_count": valid_b4,
            "valid_b4_fallback_coverage": (
                _safe_div(valid_b4, fallback_count) if fallback_count else None
            ),
            "failed_fallback_count": failed,
            "direct_b3_count": len(records) - fallback_count,
            "family_metrics": family_metrics(records, predictions),
            "contrast_metrics": contrast_metrics(records, predictions),
            "page_stratified_metrics": stratified_metrics(
                records, predictions, "current_page"
            ),
            "fold_stratified_metrics": stratified_metrics(
                records, predictions, "outer_fold"
            ),
            "prediction_distribution": prediction_distribution(predictions),
            "subset_metrics": {
                "direct_b3": subset_metrics(direct_records),
                "b4_fallback": subset_metrics(fallback_records),
                "valid_b4_fallback": subset_metrics(valid_fallback_records),
                "failed_fallback": subset_metrics(failed_records),
            },
        }
    )
    return result


def score_policy(
    records: Sequence[DevRecord], policy_id: str
) -> tuple[dict[str, Any], list[AnalysedDecision]]:
    decisions = [analyse_policy(policy_id, record) for record in records]
    metrics = full_metrics(records, decisions)
    selection_metrics = {
        "macro_f1": metrics["macro_f1"],
        "exact_capability_set_match": metrics["exact_capability_set_match"],
        "jaccard": metrics["jaccard"],
        "under_routing_rate": metrics["under_routing"]["case_rate"],
        "over_routing_rate": metrics["over_routing"]["case_rate"],
        "fallback_rate": metrics["fallback_rate"],
    }
    return {
        "policy_id": policy_id,
        "selection_metrics": selection_metrics,
        "metrics": metrics,
    }, decisions


def select_policy_on_training_records(
    training_records: Sequence[DevRecord], held_out_fold: str
) -> tuple[str, dict[str, dict[str, Any]]]:
    if held_out_fold not in p1.OUTER_FOLDS:
        raise AnalysisError("unknown held-out fold")
    if any(record.outer_fold == held_out_fold for record in training_records):
        raise AnalysisError("outer-validation record passed to policy selection")
    if len(training_records) != 48:
        raise AnalysisError("outer policy selection requires exactly 48 training records")
    if {record.outer_fold for record in training_records} != {
        fold for fold in p1.OUTER_FOLDS if fold != held_out_fold
    }:
        raise AnalysisError("outer policy selection does not contain exactly three folds")
    scores: dict[str, dict[str, Any]] = {}
    selection_view: dict[str, Mapping[str, Any]] = {}
    for policy_id in p1.ELIGIBLE_POLICY_IDS:
        score, _ = score_policy(training_records, policy_id)
        scores[policy_id] = score
        selection_view[policy_id] = score["selection_metrics"]
    selected = p1.select_policy(selection_view)
    return selected, scores


def run_nested_selection(records: Sequence[DevRecord]) -> dict[str, Any]:
    outer_results = []
    training_metric_rows = []
    nested_decisions: list[AnalysedDecision] = []
    for held_out_fold in p1.OUTER_FOLDS:
        training = [record for record in records if record.outer_fold != held_out_fold]
        selected_policy, scores = select_policy_on_training_records(
            training, held_out_fold
        )
        for policy_id in p1.ELIGIBLE_POLICY_IDS:
            training_metric_rows.append(
                _policy_metric_row(
                    scores[policy_id],
                    scope="OUTER_TRAINING",
                    outer_fold=held_out_fold,
                    selection_fold_ids="|".join(
                        fold for fold in p1.OUTER_FOLDS if fold != held_out_fold
                    ),
                )
            )

        # The held-out records, including their Gold and B4 fields, are first
        # materialized only after the policy ID has been fixed above.
        validation = [
            record for record in records if record.outer_fold == held_out_fold
        ]
        validation_decisions = [
            analyse_policy(selected_policy, record) for record in validation
        ]
        validation_metrics = full_metrics(validation, validation_decisions)
        selected_training = scores[selected_policy]["metrics"]
        outer_results.append(
            {
                "outer_fold": held_out_fold,
                "selection_fold_ids": [
                    fold for fold in p1.OUTER_FOLDS if fold != held_out_fold
                ],
                "selection_case_count": 48,
                "outer_validation_case_count": 16,
                "outer_validation_gold_passed_to_selection": False,
                "outer_validation_b4_passed_to_selection": False,
                "selected_policy_id": selected_policy,
                "selected_training_metrics": selected_training,
                "outer_validation_metrics": validation_metrics,
            }
        )
        nested_decisions.extend(validation_decisions)
    nested_decisions.sort(
        key=lambda decision: decision.record.annotation_case_id.encode("utf-8")
    )
    if len(nested_decisions) != 64 or len(
        {decision.record.annotation_case_id for decision in nested_decisions}
    ) != 64:
        raise AnalysisError("nested evaluation does not contain one prediction per case")
    return {
        "outer_results": outer_results,
        "training_metric_rows": training_metric_rows,
        "nested_decisions": nested_decisions,
        "nested_metrics": full_metrics(records, nested_decisions),
    }


def _policy_metric_row(
    score: Mapping[str, Any],
    *,
    scope: str,
    outer_fold: str = "",
    selection_fold_ids: str = "",
) -> dict[str, Any]:
    metrics = score["metrics"]
    row: dict[str, Any] = {
        "schema_version": "rq2-v2-stage4j-p1-policy-metrics-v1",
        "scope": scope,
        "outer_fold": outer_fold,
        "selection_fold_ids": selection_fold_ids,
        "policy_id": score["policy_id"],
        "simplicity_order": p1.POLICY_SIMPLICITY_ORDER[score["policy_id"]],
        "case_count": metrics["case_count"],
        "macro_f1": metrics["macro_f1"],
        "micro_f1": metrics["micro_f1"],
        "exact_capability_set_match": metrics["exact_capability_set_match"],
        "jaccard": metrics["jaccard"],
        "hamming_loss": metrics["hamming_loss"],
        "under_routing_rate": metrics["under_routing"]["case_rate"],
        "over_routing_rate": metrics["over_routing"]["case_rate"],
        "fallback_count": metrics["fallback_count"],
        "fallback_rate": metrics["fallback_rate"],
        "valid_b4_fallback_coverage": (
            ""
            if metrics["valid_b4_fallback_coverage"] is None
            else metrics["valid_b4_fallback_coverage"]
        ),
        "failed_fallback_count": metrics["failed_fallback_count"],
    }
    for capability in CAPABILITIES:
        prefix = capability.removesuffix("_required")
        for metric in ("precision", "recall", "f1"):
            row[f"{prefix}_{metric}"] = metrics["per_label"][capability][metric]
    return row


def _normalized_json_record(record: DevRecord) -> dict[str, Any]:
    return {
        "schema_version": "rq2-v2-stage4j-p1-normalized-dev-record-v1",
        "annotation_case_id": record.annotation_case_id,
        "scenario_family_id": record.scenario_family_id,
        "outer_fold": record.outer_fold,
        "current_page": record.current_page,
        "dev_atomic_component_id": record.dev_atomic_component_id,
        "dev_contrast_group_id": record.dev_contrast_group_id,
        "dev_contrast_axis": record.dev_contrast_axis,
        "audit_only_fields_not_runtime_triggers": [
            "annotation_case_id",
            "scenario_family_id",
            "outer_fold",
            "current_page",
            "dev_atomic_component_id",
            "dev_contrast_group_id",
            "dev_contrast_axis",
            "gold",
            "b4_usage",
        ],
        "gold": record.gold.as_dict(),
        "gold_capability_signature": _signature_text(record.gold),
        "b0": record.b0.as_dict(),
        "b0_capability_signature": _signature_text(record.b0),
        "b2": record.b2.as_dict(),
        "b2_capability_signature": _signature_text(record.b2),
        "b3": record.b3.as_dict(),
        "b3_capability_signature": _signature_text(record.b3),
        "b3_probabilities": dict(zip(CAPABILITIES, record.b3_probabilities, strict=True)),
        "b3_thresholds": dict(zip(CAPABILITIES, record.b3_thresholds, strict=True)),
        "b4": record.b4.as_dict(),
        "b4_capability_signature": _signature_text(record.b4),
        "b4_terminal_status": record.b4_terminal_status,
        "b4_returned_model": record.b4_returned_model,
        "b4_usage": {
            "attempts_used": record.b4_attempts_used,
            "input_tokens": record.b4_input_tokens,
            "output_tokens": record.b4_output_tokens,
            "total_tokens": record.b4_total_tokens,
            "approximate_cost_usd": _format_cost(record.b4_cost_usd),
        },
    }


NORMALIZED_CSV_FIELDS = (
    "schema_version",
    "annotation_case_id",
    "scenario_family_id",
    "outer_fold",
    "current_page",
    "dev_atomic_component_id",
    "dev_contrast_group_id",
    "dev_contrast_axis",
    "gold_capability_signature",
    "gold_rag_required",
    "gold_memory_required",
    "gold_planning_required",
    "b0_capability_signature",
    "b0_rag_required",
    "b0_memory_required",
    "b0_planning_required",
    "b2_capability_signature",
    "b2_rag_required",
    "b2_memory_required",
    "b2_planning_required",
    "b3_capability_signature",
    "b3_rag_required",
    "b3_memory_required",
    "b3_planning_required",
    "b3_rag_probability",
    "b3_rag_threshold",
    "b3_memory_probability",
    "b3_memory_threshold",
    "b3_planning_probability",
    "b3_planning_threshold",
    "b4_capability_signature",
    "b4_rag_required",
    "b4_memory_required",
    "b4_planning_required",
    "b4_terminal_status",
    "b4_returned_model",
    "b4_attempts_used",
    "b4_input_tokens",
    "b4_output_tokens",
    "b4_total_tokens",
    "b4_approximate_cost_usd",
)


def _normalized_csv_record(record: DevRecord) -> dict[str, Any]:
    row: dict[str, Any] = {
        "schema_version": "rq2-v2-stage4j-p1-normalized-dev-record-v1",
        "annotation_case_id": record.annotation_case_id,
        "scenario_family_id": record.scenario_family_id,
        "outer_fold": record.outer_fold,
        "current_page": record.current_page,
        "dev_atomic_component_id": record.dev_atomic_component_id,
        "dev_contrast_group_id": record.dev_contrast_group_id,
        "dev_contrast_axis": record.dev_contrast_axis,
        "b4_terminal_status": record.b4_terminal_status,
        "b4_returned_model": record.b4_returned_model,
        "b4_attempts_used": record.b4_attempts_used,
        "b4_input_tokens": record.b4_input_tokens,
        "b4_output_tokens": record.b4_output_tokens,
        "b4_total_tokens": record.b4_total_tokens,
        "b4_approximate_cost_usd": _format_cost(record.b4_cost_usd),
    }
    for prefix, signature in (
        ("gold", record.gold),
        ("b0", record.b0),
        ("b2", record.b2),
        ("b3", record.b3),
        ("b4", record.b4),
    ):
        row[f"{prefix}_capability_signature"] = _signature_text(signature)
        for short, value in zip(CAPABILITY_SHORT, signature.bits, strict=True):
            row[f"{prefix}_{short}_required"] = _bool_text(value)
    for short, probability, threshold in zip(
        CAPABILITY_SHORT,
        record.b3_probabilities,
        record.b3_thresholds,
        strict=True,
    ):
        row[f"b3_{short}_probability"] = format(probability, ".17g")
        row[f"b3_{short}_threshold"] = format(threshold, ".17g")
    return row


POLICY_MATRIX_FIELDS = (
    "schema_version",
    "annotation_case_id",
    "outer_fold",
    "policy_id",
    "eligible",
    "simplicity_order",
    "triggered",
    "trigger_reason",
    "selected_router",
    "final_capability_signature",
    "final_rag_required",
    "final_memory_required",
    "final_planning_required",
    "fallback_status",
)


def policy_case_matrix(records: Sequence[DevRecord]) -> tuple[list[dict[str, Any]], dict[str, int]]:
    rows = []
    counts: Counter[str] = Counter()
    policy_ids = (*p1.ELIGIBLE_POLICY_IDS, p1.DIAGNOSTIC_POLICY_ID)
    for record in records:
        for policy_id in policy_ids:
            decision = analyse_policy(policy_id, record)
            counts[policy_id] += int(decision.fallback_triggered)
            rows.append(
                {
                    "schema_version": "rq2-v2-stage4j-p1-policy-case-matrix-v1",
                    "annotation_case_id": record.annotation_case_id,
                    "outer_fold": record.outer_fold,
                    "policy_id": policy_id,
                    "eligible": _bool_text(policy_id in p1.ELIGIBLE_POLICY_IDS),
                    "simplicity_order": (
                        p1.POLICY_SIMPLICITY_ORDER[policy_id]
                        if policy_id in p1.POLICY_SIMPLICITY_ORDER
                        else ""
                    ),
                    "triggered": _bool_text(decision.fallback_triggered),
                    "trigger_reason": decision.trigger_reason,
                    "selected_router": decision.selected_router,
                    "final_capability_signature": _signature_text(decision.output),
                    "final_rag_required": _bool_text(decision.output.rag_required),
                    "final_memory_required": _bool_text(decision.output.memory_required),
                    "final_planning_required": _bool_text(decision.output.planning_required),
                    "fallback_status": decision.fallback_status,
                }
            )
    return rows, {policy_id: counts[policy_id] for policy_id in policy_ids}


def _decision_prediction_row(decision: AnalysedDecision) -> dict[str, Any]:
    record = decision.record
    return {
        "schema_version": "rq2-v2-stage4j-p1-nested-oof-prediction-v1",
        "annotation_case_id": record.annotation_case_id,
        "scenario_family_id": record.scenario_family_id,
        "outer_fold": record.outer_fold,
        "current_page": record.current_page,
        "selected_policy_id": decision.policy_id,
        "fallback_triggered": _bool_text(decision.fallback_triggered),
        "trigger_reason": decision.trigger_reason,
        "selected_router": decision.selected_router,
        "fallback_status": decision.fallback_status,
        "fallback_outcome": decision.fallback_status,
        "b4_valid_for_triggered_case": (
            "true" if decision.fallback_triggered else "NOT_APPLICABLE"
        ),
        "estimated_logical_b4_calls": int(decision.fallback_triggered),
        "b4_physical_attempt_count": (
            record.b4_attempts_used if decision.fallback_triggered else 0
        ),
        "gold_capability_signature": _signature_text(record.gold),
        "predicted_capability_signature": _signature_text(decision.output),
        "predicted_rag_required": _bool_text(decision.output.rag_required),
        "predicted_memory_required": _bool_text(decision.output.memory_required),
        "predicted_planning_required": _bool_text(decision.output.planning_required),
    }


NESTED_PREDICTION_FIELDS = tuple(
    _decision_prediction_row(
        AnalysedDecision(
            record=DevRecord(
                annotation_case_id="TOY",
                scenario_family_id="TOY",
                outer_fold=p1.OUTER_FOLDS[0],
                current_page="TOY",
                dev_atomic_component_id="",
                dev_contrast_group_id="",
                dev_contrast_axis="",
                gold=_signature((False, False, False)),
                b0=_signature((False, False, False)),
                b1=_signature((False, False, False)),
                b2=_signature((False, False, False)),
                b3=_signature((False, False, False)),
                b3_probabilities=(0.0, 0.0, 0.0),
                b3_thresholds=(0.5, 0.5, 0.5),
                b4=_signature((False, False, False)),
                b4_terminal_status="VALID_PREDICTION",
                b4_attempts_used=1,
                b4_input_tokens=0,
                b4_output_tokens=0,
                b4_total_tokens=0,
                b4_cost_usd=Decimal("0"),
                b4_returned_model=EXPECTED_MODEL,
            ),
            policy_id="P1-C00-B3-DIRECT",
            fallback_triggered=False,
            trigger_reason="NEVER_FALLBACK",
            selected_router="B3",
            output=_signature((False, False, False)),
            fallback_status="NOT_TRIGGERED_USED_B3",
        )
    ).keys()
)


def _nested_audit_row(
    decision: AnalysedDecision, outer_result: Mapping[str, Any]
) -> dict[str, Any]:
    record = decision.record
    gold_set = {index for index, value in enumerate(record.gold.bits) if value}
    pred_set = {index for index, value in enumerate(decision.output.bits) if value}
    return {
        "schema_version": "rq2-v2-stage4j-p1-nested-oof-case-audit-v1",
        "annotation_case_id": record.annotation_case_id,
        "outer_fold": record.outer_fold,
        "selection_fold_ids": "|".join(outer_result["selection_fold_ids"]),
        "selection_case_count": outer_result["selection_case_count"],
        "outer_validation_gold_passed_to_selection": "false",
        "outer_validation_b4_passed_to_selection": "false",
        "selected_policy_id": decision.policy_id,
        "b3_capability_signature": _signature_text(record.b3),
        "b4_capability_signature": _signature_text(record.b4),
        "final_capability_signature": _signature_text(decision.output),
        "gold_capability_signature": _signature_text(record.gold),
        "fallback_triggered": _bool_text(decision.fallback_triggered),
        "trigger_reason": decision.trigger_reason,
        "fallback_status": decision.fallback_status,
        "exact_capability_set": _bool_text(decision.output == record.gold),
        "under_routed": _bool_text(bool(gold_set - pred_set)),
        "over_routed": _bool_text(bool(pred_set - gold_set)),
    }


def counterfactual_cost(
    records: Sequence[DevRecord], decisions: Sequence[AnalysedDecision]
) -> dict[str, Any]:
    triggered = [decision.record for decision in decisions if decision.fallback_triggered]
    input_tokens = sum(record.b4_input_tokens for record in triggered)
    output_tokens = sum(record.b4_output_tokens for record in triggered)
    cost = sum((record.b4_cost_usd for record in triggered), Decimal("0"))
    return {
        "counterfactual_logical_b4_calls": len(triggered),
        "counterfactual_physical_attempts": sum(
            record.b4_attempts_used for record in triggered
        ),
        "counterfactual_input_tokens": input_tokens,
        "counterfactual_output_tokens": output_tokens,
        "counterfactual_total_tokens": input_tokens + output_tokens,
        "counterfactual_approximate_cost_usd": _format_cost(cost),
        "triggered_annotation_case_ids": [
            record.annotation_case_id
            for record in sorted(
                triggered, key=lambda value: value.annotation_case_id.encode("utf-8")
            )
        ],
        "cost_interpretation": (
            "Counterfactual policy-time usage computed from frozen per-case B4 records; "
            "not actual refunded, recovered, or avoided historical billing."
        ),
    }


def _reduction(value: int | Decimal, baseline: int | Decimal) -> float:
    if not baseline:
        return 0.0
    return round(float((baseline - value) / baseline * 100), 12)


def build_cost_report(
    records: Sequence[DevRecord],
    nested_decisions: Sequence[AnalysedDecision],
    final_decisions: Sequence[AnalysedDecision],
) -> dict[str, Any]:
    baseline_input = sum(record.b4_input_tokens for record in records)
    baseline_output = sum(record.b4_output_tokens for record in records)
    baseline_cost = sum((record.b4_cost_usd for record in records), Decimal("0"))
    baseline = {
        "actual_historical_b4_dev_generation_calls": 64,
        "actual_historical_b4_dev_physical_attempts_successful_run": 64,
        "actual_historical_input_tokens": baseline_input,
        "actual_historical_output_tokens": baseline_output,
        "actual_historical_total_tokens": baseline_input + baseline_output,
        "actual_historical_approximate_cost_usd": _format_cost(baseline_cost),
        "historical_failed_request_configuration_attempt": {
            "count": 1,
            "classification": "PRE_MODEL_REQUEST_CONFIGURATION_FAILURE",
            "counted_as_b4_prediction": False,
            "included_in_successful_run_tokens_or_cost": False,
        },
    }
    result: dict[str, Any] = {
        "schema_version": "rq2-v2-stage4j-p1-counterfactual-cost-v1",
        "pricing_reference": {
            "input_usd_per_1m_tokens": str(INPUT_PRICE_PER_MILLION),
            "output_usd_per_1m_tokens": str(OUTPUT_PRICE_PER_MILLION),
            "source": "FROZEN_B4_USAGE_AND_COST_V2",
        },
        "all_b4_actual_historical_baseline": baseline,
        "stage4j_new_provider_calls": 0,
    }
    for key, decisions in (
        ("nested_p1_counterfactual", nested_decisions),
        ("final_selected_policy_counterfactual", final_decisions),
    ):
        summary = counterfactual_cost(records, decisions)
        summary["percentage_reduction_vs_all_b4"] = {
            "logical_calls": _reduction(summary["counterfactual_logical_b4_calls"], 64),
            "input_tokens": _reduction(
                summary["counterfactual_input_tokens"], baseline_input
            ),
            "output_tokens": _reduction(
                summary["counterfactual_output_tokens"], baseline_output
            ),
            "approximate_cost": _reduction(
                Decimal(summary["counterfactual_approximate_cost_usd"]), baseline_cost
            ),
        }
        result[key] = summary
    return result


def hybrid_collapse_audit(
    records: Sequence[DevRecord],
    final_policy_id: str,
    final_decisions: Sequence[AnalysedDecision],
) -> dict[str, Any]:
    decisions = {decision.record.annotation_case_id: decision for decision in final_decisions}
    fallback_count = sum(decision.fallback_triggered for decision in final_decisions)

    def ids_where(predicate: Any) -> list[str]:
        return [
            record.annotation_case_id
            for record in records
            if predicate(record, decisions[record.annotation_case_id])
        ]

    differs_b4 = ids_where(lambda record, decision: decision.output != record.b4)
    differs_b3 = ids_where(lambda record, decision: decision.output != record.b3)
    b4_exact_b3_not = ids_where(
        lambda record, _decision: record.b4 == record.gold and record.b3 != record.gold
    )
    b3_exact_b4_not = ids_where(
        lambda record, _decision: record.b3 == record.gold and record.b4 != record.gold
    )
    direct_improves = ids_where(
        lambda record, decision: (
            not decision.fallback_triggered
            and record.b3 == record.gold
            and record.b4 != record.gold
            and decision.output == record.gold
        )
    )
    direct_harms = ids_where(
        lambda record, decision: (
            not decision.fallback_triggered
            and record.b3 != record.gold
            and record.b4 == record.gold
            and decision.output != record.gold
        )
    )
    fallback_rate = _safe_div(fallback_count, len(records))
    statuses = []
    if fallback_rate >= 0.9:
        statuses.append("NEAR_ALWAYS_B4_FALLBACK")
    if not differs_b4:
        statuses.append("BEHAVIORALLY_IDENTICAL_TO_B4_ON_DEV")
    if not statuses:
        statuses.append("SELECTIVE_HYBRID_NOT_COLLAPSED_TO_B4_ON_DEV")
    return {
        "schema_version": "rq2-v2-stage4j-p1-hybrid-collapse-audit-v1",
        "final_policy_id": final_policy_id,
        "fallback_count": fallback_count,
        "fallback_rate": fallback_rate,
        "statuses": statuses,
        "diagnostic_changed_selection": False,
        "p1_differs_from_b4": {"count": len(differs_b4), "case_ids": differs_b4},
        "p1_differs_from_b3": {"count": len(differs_b3), "case_ids": differs_b3},
        "b4_exact_b3_not": {"count": len(b4_exact_b3_not), "case_ids": b4_exact_b3_not},
        "b3_exact_b4_not": {"count": len(b3_exact_b4_not), "case_ids": b3_exact_b4_not},
        "direct_b3_improves_final_p1": {
            "count": len(direct_improves),
            "case_ids": direct_improves,
        },
        "direct_b3_harms_final_p1": {
            "count": len(direct_harms),
            "case_ids": direct_harms,
        },
    }


MODEL_COMPARISON_FIELDS = (
    "schema_version",
    "model_id",
    "evaluation_role",
    "case_count",
    "macro_f1",
    "micro_f1",
    "exact_capability_set_match",
    "example_based_f1",
    "jaccard",
    "hamming_loss",
    "under_routing_rate",
    "over_routing_rate",
    "estimated_b4_calls",
    "estimated_b4_call_reduction_vs_all_b4",
)


def build_model_comparison(
    records: Sequence[DevRecord], nested_decisions: Sequence[AnalysedDecision]
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    none_signature = _signature((False, False, False))
    all_signature = _signature((True, True, True))
    sources: list[tuple[str, str, Mapping[str, p1.CapabilitySignature], int]] = [
        ("NESTED_P1", "PRIMARY_NESTED_META_POLICY_ESTIMATE", _prediction_map(nested_decisions), sum(d.fallback_triggered for d in nested_decisions)),
        ("B0", "FROZEN_BASELINE", {r.annotation_case_id: r.b0 for r in records}, 0),
        ("B1", "FROZEN_BASELINE", {r.annotation_case_id: r.b1 for r in records}, 0),
        ("B2", "FROZEN_BASELINE", {r.annotation_case_id: r.b2 for r in records}, 0),
        ("B3", "FROZEN_BASE_ROUTER", {r.annotation_case_id: r.b3 for r in records}, 0),
        ("B4", "FROZEN_ALL_B4_DIAGNOSTIC", {r.annotation_case_id: r.b4 for r in records}, 64),
        ("ALWAYS_ON", "DETERMINISTIC_SANITY_BASELINE", {r.annotation_case_id: all_signature for r in records}, 0),
        ("NEVER_ON", "DETERMINISTIC_SANITY_BASELINE", {r.annotation_case_id: none_signature for r in records}, 0),
    ]
    rows: list[dict[str, Any]] = []
    metric_by_id: dict[str, dict[str, Any]] = {}
    for model_id, role, predictions, estimated_calls in sources:
        metrics = core_metrics(records, predictions)
        metric_by_id[model_id] = metrics
        rows.append(
            {
                "schema_version": "rq2-v2-stage4j-p1-model-comparison-v1",
                "model_id": model_id,
                "evaluation_role": role,
                "case_count": len(records),
                "macro_f1": metrics["macro_f1"],
                "micro_f1": metrics["micro_f1"],
                "exact_capability_set_match": metrics["exact_capability_set_match"],
                "example_based_f1": metrics["example_based_f1"],
                "jaccard": metrics["jaccard"],
                "hamming_loss": metrics["hamming_loss"],
                "under_routing_rate": metrics["under_routing"]["case_rate"],
                "over_routing_rate": metrics["over_routing"]["case_rate"],
                "estimated_b4_calls": estimated_calls,
                "estimated_b4_call_reduction_vs_all_b4": 64 - estimated_calls,
            }
        )
    nested = metric_by_id["NESTED_P1"]
    b4 = metric_by_id["B4"]
    calls = rows[0]["estimated_b4_calls"]
    differences = {
        "macro_f1": round(nested["macro_f1"] - b4["macro_f1"], 12),
        "exact_capability_set_match": round(
            nested["exact_capability_set_match"] - b4["exact_capability_set_match"],
            12,
        ),
        "jaccard": round(nested["jaccard"] - b4["jaccard"], 12),
        "under_routing_rate": round(
            nested["under_routing"]["case_rate"] - b4["under_routing"]["case_rate"],
            12,
        ),
        "over_routing_rate": round(
            nested["over_routing"]["case_rate"] - b4["over_routing"]["case_rate"],
            12,
        ),
        "estimated_b4_call_reduction_count": 64 - calls,
        "estimated_b4_call_reduction_rate": _safe_div(64 - calls, 64),
        "significance_testing": "NOT_PLANNED_NOT_PERFORMED",
    }
    return rows, differences


END_TO_END_FIELDS = (
    "schema_version",
    "annotation_case_id",
    "scenario_family_id",
    "outer_fold",
    "current_page",
    "dev_atomic_component_id",
    "dev_contrast_group_id",
    "dev_contrast_axis",
    "gold_dialogue_action",
    "predicted_dialogue_action",
    "core_p1_executed",
    "selected_policy_id",
    "fallback_triggered",
    "selected_router",
    "gold_route_signature",
    "predicted_route_signature",
    "gold_rag_required",
    "gold_memory_required",
    "gold_planning_required",
    "predicted_rag_required",
    "predicted_memory_required",
    "predicted_planning_required",
    "full_route_exact",
)


def _binary_action_metrics(rows: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    per_class: dict[str, Any] = {}
    for action in ("ANSWER", "CLARIFY"):
        tp = sum(r["gold_dialogue_action"] == action and r["predicted_dialogue_action"] == action for r in rows)
        fp = sum(r["gold_dialogue_action"] != action and r["predicted_dialogue_action"] == action for r in rows)
        fn = sum(r["gold_dialogue_action"] == action and r["predicted_dialogue_action"] != action for r in rows)
        precision = _safe_div(tp, tp + fp)
        recall = _safe_div(tp, tp + fn)
        per_class[action] = {
            "tp": tp,
            "fp": fp,
            "fn": fn,
            "precision": precision,
            "recall": recall,
            "f1": _safe_div(2 * precision * recall, precision + recall),
        }
    correct = sum(r["gold_dialogue_action"] == r["predicted_dialogue_action"] for r in rows)
    return {
        "accuracy": _safe_div(correct, len(rows)),
        "macro_f1": round(sum(value["f1"] for value in per_class.values()) / 2, 12),
        "per_class": per_class,
    }


def _end_to_end_contrast_metrics(rows: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    groups: dict[tuple[str, str], list[Mapping[str, Any]]] = defaultdict(list)
    for row in rows:
        group = str(row["dev_contrast_group_id"])
        axis = str(row["dev_contrast_axis"])
        if group and axis in {"RAG", "MEMORY", "PLANNING", "CLARIFICATION"}:
            groups[(group, axis)].append(row)
    details = []
    internally_consistent = gold_pattern_matched = 0
    for (group_id, axis), items in sorted(groups.items()):
        families: dict[str, list[Mapping[str, Any]]] = defaultdict(list)
        for row in items:
            families[str(row["scenario_family_id"])].append(row)
        if len(families) != 2 or any(len(values) != 2 for values in families.values()):
            raise AnalysisError(f"malformed end-to-end contrast group: {group_id}")
        predicted: dict[str, str] = {}
        gold: dict[str, str] = {}
        consistent = True
        for family, values in families.items():
            predicted_values = {str(value["predicted_route_signature"]) for value in values}
            gold_values = {str(value["gold_route_signature"]) for value in values}
            if len(predicted_values) != 1 or len(gold_values) != 1:
                consistent = False
            else:
                predicted[family] = next(iter(predicted_values))
                gold[family] = next(iter(gold_values))
        matched = consistent and predicted == gold
        internally_consistent += int(consistent)
        gold_pattern_matched += int(matched)
        details.append(
            {
                "contrast_group_id": group_id,
                "axis": axis,
                "within_family_prediction_consistent": consistent,
                "gold_route_pattern_matched": matched,
            }
        )
    count = len(groups)
    return {
        "definition": "Full route signatures, including CLARIFY, must be internally consistent within both families; Gold-pattern match additionally requires both family signatures to equal frozen Gold.",
        "eligible_contrast_groups": count,
        "within_family_consistent_groups": internally_consistent,
        "within_family_consistency_rate": _safe_div(internally_consistent, count),
        "gold_pattern_matched_groups": gold_pattern_matched,
        "gold_pattern_match_rate": _safe_div(gold_pattern_matched, count),
        "groups": details,
    }


def build_end_to_end(
    records: Sequence[DevRecord], nested_decisions: Sequence[AnalysedDecision]
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    gold_rows = _unique_by_id(_load_csv(DEV_DIR / "dev_capability_gold_v1.csv"), "all DEV Gold")
    group_rows = _unique_by_id(_load_csv(DEV_DIR / "dev_atomic_group_map_v1.csv"), "all DEV grouping")
    clarification_rows = _unique_by_id(
        _load_csv(TRACK_G_DIR / "clarification_oof_predictions_v1.csv"),
        "clarification OOF predictions",
    )
    if set(gold_rows) != set(group_rows) or set(gold_rows) != set(clarification_rows) or len(gold_rows) != 72:
        raise AnalysisError("end-to-end 72-case join differs")
    nested = {decision.record.annotation_case_id: decision for decision in nested_decisions}
    record_by_id = {record.annotation_case_id: record for record in records}
    rows: list[dict[str, Any]] = []
    for case_id in sorted(gold_rows, key=lambda value: value.encode("utf-8")):
        gold = gold_rows[case_id]
        grouping = group_rows[case_id]
        clarification = clarification_rows[case_id]
        if gold["partition"] != "DEV" or clarification["gold_dialogue_action"] != gold["final_dialogue_action"]:
            raise AnalysisError(f"end-to-end Gold mismatch: {case_id}")
        if any(
            clarification[key] != gold[source_key]
            for key, source_key in (
                ("scenario_family_id", "scenario_family_id"),
                ("current_page", "current_page"),
            )
        ):
            raise AnalysisError(f"end-to-end metadata mismatch: {case_id}")
        predicted_action = clarification["predicted_dialogue_action"]
        gold_action = gold["final_dialogue_action"]
        if predicted_action not in {"ANSWER", "CLARIFY"}:
            raise AnalysisError(f"unknown clarification-gate result: {case_id}")
        if gold_action == "CLARIFY":
            gold_signature = "CLARIFY"
            gold_bits = ("NOT_APPLICABLE",) * 3
        else:
            gold_capability = _row_signature(
                gold,
                ("final_rag_required", "final_memory_required", "final_planning_required"),
            )
            gold_signature = _signature_text(gold_capability)
            gold_bits = tuple(_bool_text(value) for value in gold_capability.bits)
        if predicted_action == "CLARIFY":
            predicted_signature = "CLARIFY"
            predicted_bits = ("NOT_APPLICABLE",) * 3
            executed = False
            selected_policy = fallback = router = "NOT_APPLICABLE"
        else:
            if case_id not in nested or case_id not in record_by_id:
                raise AnalysisError(f"predicted ANSWER lacks one nested P1 output: {case_id}")
            decision = nested[case_id]
            predicted_signature = _signature_text(decision.output)
            predicted_bits = tuple(_bool_text(value) for value in decision.output.bits)
            executed = True
            selected_policy = decision.policy_id
            fallback = _bool_text(decision.fallback_triggered)
            router = decision.selected_router
        row = {
            "schema_version": "rq2-v2-stage4j-p1-end-to-end-oof-v1",
            "annotation_case_id": case_id,
            "scenario_family_id": gold["scenario_family_id"],
            "outer_fold": clarification["outer_fold"],
            "current_page": gold["current_page"],
            "dev_atomic_component_id": grouping["dev_atomic_component_id"],
            "dev_contrast_group_id": grouping["dev_contrast_group_id"],
            "dev_contrast_axis": grouping["dev_contrast_axis"],
            "gold_dialogue_action": gold_action,
            "predicted_dialogue_action": predicted_action,
            "core_p1_executed": _bool_text(executed),
            "selected_policy_id": selected_policy,
            "fallback_triggered": fallback,
            "selected_router": router,
            "gold_route_signature": gold_signature,
            "predicted_route_signature": predicted_signature,
            "gold_rag_required": gold_bits[0],
            "gold_memory_required": gold_bits[1],
            "gold_planning_required": gold_bits[2],
            "predicted_rag_required": predicted_bits[0],
            "predicted_memory_required": predicted_bits[1],
            "predicted_planning_required": predicted_bits[2],
            "full_route_exact": _bool_text(gold_signature == predicted_signature),
        }
        rows.append(row)
    families: dict[str, list[Mapping[str, Any]]] = defaultdict(list)
    for row in rows:
        families[str(row["scenario_family_id"])].append(row)
    if len(families) != 36 or any(len(values) != 2 for values in families.values()):
        raise AnalysisError("end-to-end family structure differs from 36 pairs")
    family_correct = sum(
        all(value["gold_route_signature"] == value["predicted_route_signature"] for value in values)
        for values in families.values()
    )
    metrics = {
        "population_count": 72,
        "full_route_signature_exact_count": sum(row["full_route_exact"] == "true" for row in rows),
        "full_route_signature_exact_match": _safe_div(sum(row["full_route_exact"] == "true" for row in rows), 72),
        "dialogue_action": _binary_action_metrics(rows),
        "predicted_clarify_count": sum(row["predicted_dialogue_action"] == "CLARIFY" for row in rows),
        "core_p1_executed_count": sum(row["core_p1_executed"] == "true" for row in rows),
        "family_both_correct": {
            "family_count": 36,
            "correct_count": family_correct,
            "rate": _safe_div(family_correct, 36),
        },
        "contrast_consistency": _end_to_end_contrast_metrics(rows),
    }
    return rows, metrics


def _repo_path(path: Path) -> str:
    return path.relative_to(REPO_ROOT).as_posix()


def build_input_contract_v2(
    b4_binding: Mapping[str, Any], source_artifacts: Sequence[Mapping[str, Any]]
) -> dict[str, Any]:
    b4_roles = {
        "b4_dev_predictions_v2.csv": "B4_VALID_DEV_PREDICTIONS",
        "b4_dev_terminal_results_v2.jsonl": "B4_TERMINAL_RESULTS",
        "b4_dev_attempt_records_v2.jsonl": "B4_ATTEMPT_RECORDS",
        "b4_dev_usage_and_cost_v2.json": "B4_USAGE_AND_COST",
        "b4_final_frozen_configuration_v2.json": "B4_FROZEN_CONFIGURATION",
        "b4_response_schema_v2.json": "B4_RESPONSE_SCHEMA_V2",
    }
    artifacts = []
    for name, role in b4_roles.items():
        artifacts.append(
            {
                "role": role,
                "path": _repo_path(TRACK_I_DIR / name),
                "sha256": B4_REQUIRED_HASHES[name],
            }
        )
    return {
        "schema_version": "rq2-v2-stage4j-p1-input-contract-v2",
        "status": "BOUND_TO_VALID_FROZEN_B4_DEV_RESULTS",
        "binding_status": "BOUND_TO_VALID_FROZEN_B4_DEV_RESULTS",
        "hash_algorithm": "SHA-256",
        "path_base": "REPOSITORY_ROOT",
        "successful_b4_execution": {
            "authorized_source_commit": SUCCESSFUL_SOURCE_COMMIT,
            "integrated_commit": SUCCESSFUL_INTEGRATED_COMMIT,
            "depends_on_historical_failure_source_commit": HISTORICAL_SOURCE_COMMIT,
            "historical_failure_integrated_commit": HISTORICAL_INTEGRATED_COMMIT,
            "model_snapshot": b4_binding["model_snapshot"],
            "valid_prediction_count": b4_binding["valid_predictions"],
            "invalid_structured_output_count": b4_binding["invalid_structured_outputs"],
            "provider_error_count": b4_binding["provider_errors"],
            "execution_status": b4_binding["execution_status"],
        },
        "b4_bound_artifacts": artifacts,
        "schema_lineage": {
            "stage4j0_pre_execution_schema_v1_sha256": EXPECTED_SCHEMA_V1_SHA256,
            "successful_b4_schema_v2_sha256": EXPECTED_SCHEMA_V2_SHA256,
            "semantic_output_unchanged": True,
            "semantic_output": {
                "type": "object",
                "required_boolean_fields": list(CAPABILITIES),
                "additional_properties": False,
            },
            "removed_unsupported_or_redundant_metadata": b4_binding["schema_metadata_removed"],
            "policy_or_selection_rule_changed": False,
        },
        "population_contract": {
            "partition": "DEV",
            "dialogue_action": "ANSWER",
            "utterance_count": 64,
            "outer_fold_ids": list(p1.OUTER_FOLDS),
            "answer_utterances_per_outer_fold": 16,
            "unique_annotation_case_id_required": True,
            "test_identifier_count": 0,
        },
        "normalized_join": {
            "key": "annotation_case_id",
            "required_identical_case_count": 64,
            "runtime_trigger_inputs_only": [
                "b0_complete_signature",
                "b2_complete_signature",
                "b3_complete_signature",
                "b3_probabilities",
                "b3_case_specific_thresholds",
            ],
            "fallback_output_only": ["b4_complete_signature", "b4_terminal_status"],
            "audit_or_metric_only_not_runtime_triggers": [
                "annotation_case_id",
                "scenario_family_id",
                "current_page",
                "outer_fold",
                "gold",
                "cost",
                "contrast_metadata",
            ],
        },
        "frozen_p1_protocol": {
            "candidate_grid_sha256": FROZEN_STAGE4J0_HASHES["p1_candidate_policies_frozen_v1.json"],
            "nested_selection_protocol_sha256": FROZEN_STAGE4J0_HASHES["p1_nested_selection_protocol_v1.json"],
            "eligible_policy_count": 9,
            "diagnostic_policy_count": 1,
            "policy_or_tie_break_changed_for_v2_binding": False,
        },
        "source_artifacts": list(source_artifacts),
        "governance": {
            "stage4j_new_provider_calls": 0,
            "test_access": False,
            "rq3_access": False,
            "production_integration": False,
        },
    }


OUTER_SELECTION_FIELDS = (
    "schema_version",
    "outer_fold",
    "selection_fold_ids",
    "selection_case_count",
    "outer_validation_case_count",
    "outer_validation_gold_passed_to_selection",
    "outer_validation_b4_passed_to_selection",
    "selected_policy_id",
    "selected_training_macro_f1",
    "selected_training_exact_capability_set_match",
    "selected_training_jaccard",
    "selected_training_under_routing_rate",
    "selected_training_over_routing_rate",
    "selected_training_fallback_count",
    "selected_training_fallback_rate",
    "outer_validation_macro_f1",
    "outer_validation_exact_capability_set_match",
    "outer_validation_jaccard",
    "outer_validation_under_routing_rate",
    "outer_validation_over_routing_rate",
    "outer_validation_fallback_count",
    "outer_validation_fallback_rate",
)


def _outer_selection_row(result: Mapping[str, Any]) -> dict[str, Any]:
    training = result["selected_training_metrics"]
    validation = result["outer_validation_metrics"]
    return {
        "schema_version": "rq2-v2-stage4j-p1-outer-fold-selection-v1",
        "outer_fold": result["outer_fold"],
        "selection_fold_ids": "|".join(result["selection_fold_ids"]),
        "selection_case_count": result["selection_case_count"],
        "outer_validation_case_count": result["outer_validation_case_count"],
        "outer_validation_gold_passed_to_selection": "false",
        "outer_validation_b4_passed_to_selection": "false",
        "selected_policy_id": result["selected_policy_id"],
        "selected_training_macro_f1": training["macro_f1"],
        "selected_training_exact_capability_set_match": training["exact_capability_set_match"],
        "selected_training_jaccard": training["jaccard"],
        "selected_training_under_routing_rate": training["under_routing"]["case_rate"],
        "selected_training_over_routing_rate": training["over_routing"]["case_rate"],
        "selected_training_fallback_count": training["fallback_count"],
        "selected_training_fallback_rate": training["fallback_rate"],
        "outer_validation_macro_f1": validation["macro_f1"],
        "outer_validation_exact_capability_set_match": validation["exact_capability_set_match"],
        "outer_validation_jaccard": validation["jaccard"],
        "outer_validation_under_routing_rate": validation["under_routing"]["case_rate"],
        "outer_validation_over_routing_rate": validation["over_routing"]["case_rate"],
        "outer_validation_fallback_count": validation["fallback_count"],
        "outer_validation_fallback_rate": validation["fallback_rate"],
    }


NESTED_AUDIT_FIELDS = (
    "schema_version",
    "annotation_case_id",
    "outer_fold",
    "selection_fold_ids",
    "selection_case_count",
    "outer_validation_gold_passed_to_selection",
    "outer_validation_b4_passed_to_selection",
    "selected_policy_id",
    "b3_capability_signature",
    "b4_capability_signature",
    "final_capability_signature",
    "gold_capability_signature",
    "fallback_triggered",
    "trigger_reason",
    "fallback_status",
    "exact_capability_set",
    "under_routed",
    "over_routed",
)


def build_final_policy_freeze(
    final_policy_id: str,
    final_metrics: Mapping[str, Any],
    final_decisions: Sequence[AnalysedDecision],
    cost_report: Mapping[str, Any],
) -> dict[str, Any]:
    candidates = _load_json(TRACK_DIR / "p1_candidate_policies_frozen_v1.json")
    candidate = next(
        row for row in candidates["eligible_policies"] if row["policy_id"] == final_policy_id
    )
    cost = cost_report["final_selected_policy_counterfactual"]
    return {
        "schema_version": "rq2-v2-stage4j-p1-final-policy-frozen-v1",
        "P1_MODEL_STATUS": "FROZEN_AFTER_DEV_SELECTION",
        "scientific_interpretation": "FINAL_POLICY_SELECTED_ON_CROSS_FITTED_DEV_NOT_INDEPENDENT_TEST_PERFORMANCE",
        "final_policy_id": final_policy_id,
        "frozen_simplicity_order": candidate["simplicity_order"],
        "complete_trigger_definition": candidate["trigger"],
        "fallback_definition": candidate["trigger"],
        "case_level_complete_signature_switch": True,
        "label_level_b3_b4_mixing": False,
        "fallback_count": final_metrics["fallback_count"],
        "fallback_rate": final_metrics["fallback_rate"],
        "direct_b3_count": final_metrics["direct_b3_count"],
        "valid_b4_fallback_count": final_metrics["valid_b4_fallback_count"],
        "failed_fallback_count": final_metrics["failed_fallback_count"],
        "estimated_b4_calls": cost["counterfactual_logical_b4_calls"],
        "counterfactual_usage": cost,
        "frozen_input_hashes": {
            "b0_input_sha256": SOURCE_HASHES["b0_core_oof_predictions_v1.csv"],
            "b2_input_sha256": SOURCE_HASHES["b2_nested_oof_predictions_v1.csv"],
            "b3_prediction_sha256": SOURCE_HASHES["b3_nested_oof_predictions_v1.csv"],
            "b3_probability_and_threshold_sha256": SOURCE_HASHES["b3_nested_oof_probabilities_v1.csv"],
            "b3_probability_sha256": SOURCE_HASHES["b3_nested_oof_probabilities_v1.csv"],
            "b4_prediction_sha256": B4_REQUIRED_HASHES["b4_dev_predictions_v2.csv"],
            "b4_result_sha256": B4_REQUIRED_HASHES["b4_dev_predictions_v2.csv"],
            "b4_configuration_sha256": B4_REQUIRED_HASHES["b4_final_frozen_configuration_v2.json"],
            "clarification_gate_sha256": SOURCE_HASHES["clarification_gate_frozen_v1.json"],
            "p1_candidate_grid_sha256": FROZEN_STAGE4J0_HASHES["p1_candidate_policies_frozen_v1.json"],
            "p1_selection_protocol_sha256": FROZEN_STAGE4J0_HASHES["p1_nested_selection_protocol_v1.json"],
        },
        "selection": {
            "population": "ALL_64_CROSS_FITTED_DEV_OOF_ANSWER_RECORDS",
            "eligible_policy_count": 9,
            "diagnostic_eligible": False,
            "tie_break": list(p1.SELECTION_METRICS) + [
                "frozen_simplicity_order",
                "utf8_policy_id",
            ],
            "selection_tie_break_id": "P1_FROZEN_LEXICOGRAPHIC_TIE_BREAK_V1",
            "test_performance_used": False,
        },
        "decision_count": len(final_decisions),
        "governance": {
            "new_provider_calls": 0,
            "test_access": False,
            "rq3_access": False,
            "future_stage4_integration_executed": False,
        },
    }


def _metric_text(value: Any) -> str:
    return "N/A" if value is None else f"{float(value):.6f}"


def build_collapse_markdown(audit: Mapping[str, Any]) -> str:
    def case_line(key: str) -> str:
        value = audit[key]
        ids = ", ".join(f"`{case_id}`" for case_id in value["case_ids"])
        return f"- {key}: {value['count']}" + (f" ({ids})" if ids else "")

    lines = [
        "# P1 Hybrid Collapse Audit",
        "",
        f"Final policy: `{audit['final_policy_id']}`",
        "",
        f"Fallback: {audit['fallback_count']}/64 ({audit['fallback_rate']:.6f}).",
        "",
        "Statuses: " + ", ".join(f"`{value}`" for value in audit["statuses"]),
        "",
        "The non-eligible ALL-B4 diagnostic did not participate in selection.",
        "",
        "## Case audit",
        "",
        case_line("p1_differs_from_b4"),
        case_line("p1_differs_from_b3"),
        case_line("b4_exact_b3_not"),
        case_line("b3_exact_b4_not"),
        case_line("direct_b3_improves_final_p1"),
        case_line("direct_b3_harms_final_p1"),
        "",
        "This is a DEV diagnostic only and did not change the frozen policy grid or tie-break.",
        "",
    ]
    return "\n".join(lines)


def build_results_markdown(
    *,
    nested: Mapping[str, Any],
    final_policy_id: str,
    final_metrics: Mapping[str, Any],
    collapse: Mapping[str, Any],
    cost: Mapping[str, Any],
    p1_minus_b4: Mapping[str, Any],
    end_to_end: Mapping[str, Any],
    b4_binding: Mapping[str, Any],
) -> str:
    nested_metrics = nested["nested_metrics"]
    nested_cost = cost["nested_p1_counterfactual"]
    final_cost = cost["final_selected_policy_counterfactual"]
    lines = [
        "# RQ2-V2 Stage 4J P1 Hybrid DEV Results",
        "",
        "Status: `READY_FOR_RQ2_V2_STAGE_4_INTEGRATION`",
        "",
        "This is a nested cross-fitted DEV estimate and final DEV policy selection, not independent TEST evidence.",
        "",
        "## B4 binding",
        "",
        f"- Model: `{b4_binding['model_snapshot']}`",
        f"- Valid predictions: {b4_binding['valid_predictions']}/64",
        f"- Successful-run execution status: `{b4_binding['execution_status']}`",
        f"- Prompt SHA-256: `{b4_binding['prompt_sha256']}`",
        f"- Schema V2 SHA-256: `{b4_binding['schema_v2_sha256']}`",
        "- Historical HTTP-400 request: preserved as `PRE_MODEL_REQUEST_CONFIGURATION_FAILURE`; excluded from predictions, metrics, and successful-run cost.",
        "",
        "## Outer-fold selections",
        "",
        "| Held-out fold | Selected policy | Validation fallback | Validation Macro-F1 | Validation Exact Set |",
        "|---|---|---:|---:|---:|",
    ]
    for result in nested["outer_results"]:
        metrics = result["outer_validation_metrics"]
        lines.append(
            f"| {result['outer_fold']} | `{result['selected_policy_id']}` | "
            f"{metrics['fallback_count']}/16 | {_metric_text(metrics['macro_f1'])} | "
            f"{_metric_text(metrics['exact_capability_set_match'])} |"
        )
    lines.extend(
        [
            "",
            "## Nested P1 estimate",
            "",
            f"- Macro-F1: {_metric_text(nested_metrics['macro_f1'])}",
            f"- Micro-F1: {_metric_text(nested_metrics['micro_f1'])}",
            f"- Exact Capability Set Match: {_metric_text(nested_metrics['exact_capability_set_match'])}",
            f"- Example-based F1: {_metric_text(nested_metrics['example_based_f1'])}",
            f"- Jaccard: {_metric_text(nested_metrics['jaccard'])}",
            f"- Hamming Loss: {_metric_text(nested_metrics['hamming_loss'])}",
            f"- Under-routing case rate: {_metric_text(nested_metrics['under_routing']['case_rate'])}",
            f"- Over-routing case rate: {_metric_text(nested_metrics['over_routing']['case_rate'])}",
            f"- Fallback: {nested_metrics['fallback_count']}/64 ({nested_metrics['fallback_rate']:.6f})",
            f"- Direct B3: {nested_metrics['direct_b3_count']}; valid B4 fallback: {nested_metrics['valid_b4_fallback_count']}; failed fallback: {nested_metrics['failed_fallback_count']}",
            "",
            "## Final full-DEV freeze",
            "",
            f"- Selected policy: `{final_policy_id}`",
            f"- Macro-F1 on full cross-fitted DEV: {_metric_text(final_metrics['macro_f1'])}",
            f"- Exact Set: {_metric_text(final_metrics['exact_capability_set_match'])}",
            f"- Fallback: {final_metrics['fallback_count']}/64 ({final_metrics['fallback_rate']:.6f})",
            "- Status: `FROZEN_AFTER_DEV_SELECTION`",
            "",
            "## Hybrid-collapse audit",
            "",
            "- " + ", ".join(f"`{value}`" for value in collapse["statuses"]),
            f"- P1 differs from B4 on {collapse['p1_differs_from_b4']['count']} cases and from B3 on {collapse['p1_differs_from_b3']['count']} cases.",
            "",
            "## Nested P1 minus B4",
            "",
            f"- Macro-F1: {p1_minus_b4['macro_f1']:+.6f}",
            f"- Exact Set: {p1_minus_b4['exact_capability_set_match']:+.6f}",
            f"- Jaccard: {p1_minus_b4['jaccard']:+.6f}",
            f"- Under-routing rate: {p1_minus_b4['under_routing_rate']:+.6f}",
            f"- Over-routing rate: {p1_minus_b4['over_routing_rate']:+.6f}",
            f"- Estimated B4-call reduction: {p1_minus_b4['estimated_b4_call_reduction_count']}/64 ({p1_minus_b4['estimated_b4_call_reduction_rate']:.6f})",
            "- No significance test was planned or performed.",
            "",
            "## Counterfactual cost",
            "",
            f"- Actual historical successful B4 DEV generation: 64 calls, {cost['all_b4_actual_historical_baseline']['actual_historical_total_tokens']} tokens, USD {cost['all_b4_actual_historical_baseline']['actual_historical_approximate_cost_usd']}.",
            f"- Nested P1: {nested_cost['counterfactual_logical_b4_calls']} calls, {nested_cost['counterfactual_total_tokens']} tokens, USD {nested_cost['counterfactual_approximate_cost_usd']}.",
            f"- Final selected policy: {final_cost['counterfactual_logical_b4_calls']} calls, {final_cost['counterfactual_total_tokens']} tokens, USD {final_cost['counterfactual_approximate_cost_usd']}.",
            "- These are policy-time counterfactuals from frozen per-case usage, not refunded or recovered historical money.",
            "",
            "## End-to-end 72-case routing",
            "",
            f"- Full route-signature exact match: {_metric_text(end_to_end['full_route_signature_exact_match'])}",
            f"- Dialogue-action accuracy: {_metric_text(end_to_end['dialogue_action']['accuracy'])}",
            f"- Dialogue-action Macro-F1: {_metric_text(end_to_end['dialogue_action']['macro_f1'])}",
            f"- Family both correct: {end_to_end['family_both_correct']['correct_count']}/36 ({end_to_end['family_both_correct']['rate']:.6f})",
            f"- End-to-end contrast Gold-pattern match: {end_to_end['contrast_consistency']['gold_pattern_matched_groups']}/{end_to_end['contrast_consistency']['eligible_contrast_groups']} ({end_to_end['contrast_consistency']['gold_pattern_match_rate']:.6f})",
            "",
            "## Boundary",
            "",
            "Stage 4J made zero provider calls and performed no TEST, TEST escrow, RQ3, production, or Stage 4 integration execution. Stop at the review handoff.",
            "",
        ]
    )
    return "\n".join(lines)


def build_status_markdown(final_policy_id: str) -> str:
    return f"""# RQ2-V2 Stage 4J Status

Status: `READY_FOR_RQ2_V2_STAGE_4_INTEGRATION`

The authorized P1 Hybrid nested DEV evaluation, full-DEV selection, and policy freeze completed deterministically from frozen local inputs. Final policy: `{final_policy_id}`.

## Lineage

- Stage 4J-0 prior status: `READY_FOR_STAGE_4J_AFTER_VALID_B4_DEV_RESULTS`
- Historical Track I request-configuration failure integrated and preserved: `{HISTORICAL_INTEGRATED_COMMIT}`
- Successful Track I schema V2 repair and B4 DEV result integrated: `{SUCCESSFUL_INTEGRATED_COMMIT}`
- P1 status: `FROZEN_AFTER_DEV_SELECTION`

## Governance

- New Stage 4J provider calls: 0
- TEST identifiers, inputs, Gold, escrow, or performance accessed: 0
- RQ3 access or execution: 0
- Stage 4 Integration execution: 0
- Production integration or learned meta-classifier: 0

The outputs are DEV selection evidence, not independent TEST evidence. STOP before Stage 4 Integration or TEST.
"""


def build_output_manifest(output_dir: Path) -> dict[str, Any]:
    outputs = []
    for name in GENERATED_OUTPUT_NAMES:
        if name == "p1_output_manifest_v1.json":
            continue
        path = output_dir / name
        if not path.is_file():
            raise AnalysisError(f"generated output missing before manifest: {name}")
        outputs.append(
            {"path": name, "sha256": sha256_file(path), "size_bytes": path.stat().st_size}
        )
    implementation = []
    for path in (
        TRACK_DIR / "p1_protocol.py",
        TRACK_DIR / "run_p1_dev_selection.py",
        TRACK_DIR / "tests" / "test_p1_dev_selection.py",
    ):
        if path.is_file():
            implementation.append(
                {
                    "path": _repo_path(path),
                    "sha256": sha256_file(path),
                    "size_bytes": path.stat().st_size,
                }
            )
    return {
        "schema_version": "rq2-v2-stage4j-p1-output-manifest-v1",
        "status": "READY_FOR_RQ2_V2_STAGE_4_INTEGRATION",
        "hash_algorithm": "SHA-256",
        "generated_output_count_excluding_manifest": len(outputs),
        "generated_outputs": outputs,
        "implementation_artifacts": implementation,
        "stage4j_new_provider_calls": 0,
        "test_identifier_count": 0,
        "rq3_access_count": 0,
    }


def build(output_dir: Path = TRACK_DIR) -> dict[str, Any]:
    output_dir = output_dir.resolve()
    output_dir.mkdir(parents=True, exist_ok=True)

    git_integration = verify_git_integration()
    frozen_j0 = verify_frozen_stage4j0()
    b4_binding = verify_b4_binding()
    source_artifacts = verify_source_hashes()
    records = load_normalized_records()
    if len(records) != 64:
        raise AnalysisError("normalized record count differs from 64")

    matrix_rows, trigger_counts = policy_case_matrix(records)
    if len(matrix_rows) != 640:
        raise AnalysisError("policy case matrix is not 64 cases by 10 policies")
    nested = run_nested_selection(records)
    nested_decisions: list[AnalysedDecision] = nested["nested_decisions"]

    full_scores: dict[str, dict[str, Any]] = {}
    full_decisions: dict[str, list[AnalysedDecision]] = {}
    for policy_id in p1.ELIGIBLE_POLICY_IDS:
        score, decisions = score_policy(records, policy_id)
        full_scores[policy_id] = score
        full_decisions[policy_id] = decisions
    final_policy_id = p1.select_policy(
        {
            policy_id: score["selection_metrics"]
            for policy_id, score in full_scores.items()
        }
    )
    final_metrics = full_scores[final_policy_id]["metrics"]
    final_decisions = full_decisions[final_policy_id]
    cost_report = build_cost_report(records, nested_decisions, final_decisions)
    collapse = hybrid_collapse_audit(records, final_policy_id, final_decisions)
    comparison_rows, p1_minus_b4 = build_model_comparison(records, nested_decisions)
    end_to_end_rows, end_to_end_metrics = build_end_to_end(records, nested_decisions)
    input_contract = build_input_contract_v2(b4_binding, source_artifacts)
    final_freeze = build_final_policy_freeze(
        final_policy_id,
        final_metrics,
        final_decisions,
        cost_report,
    )

    _write_json(output_dir / "p1_input_contract_v2.json", input_contract)
    _write_csv(
        output_dir / "p1_normalized_dev_records_v1.csv",
        NORMALIZED_CSV_FIELDS,
        (_normalized_csv_record(record) for record in records),
    )
    _write_jsonl(
        output_dir / "p1_normalized_dev_records_v1.jsonl",
        (_normalized_json_record(record) for record in records),
    )
    _write_csv(
        output_dir / "p1_policy_case_matrix_v1.csv",
        POLICY_MATRIX_FIELDS,
        matrix_rows,
    )
    training_rows = nested["training_metric_rows"]
    _write_csv(
        output_dir / "p1_outer_training_policy_metrics_v1.csv",
        tuple(training_rows[0]),
        training_rows,
    )
    outer_selection_rows = [
        _outer_selection_row(result) for result in nested["outer_results"]
    ]
    _write_csv(
        output_dir / "p1_outer_fold_policy_selection_v1.csv",
        OUTER_SELECTION_FIELDS,
        outer_selection_rows,
    )
    _write_csv(
        output_dir / "p1_nested_oof_predictions_v1.csv",
        NESTED_PREDICTION_FIELDS,
        (_decision_prediction_row(decision) for decision in nested_decisions),
    )
    outer_by_fold = {
        result["outer_fold"]: result for result in nested["outer_results"]
    }
    audit_rows = [
        _nested_audit_row(decision, outer_by_fold[decision.record.outer_fold])
        for decision in nested_decisions
    ]
    _write_csv(
        output_dir / "p1_nested_oof_case_audit_v1.csv",
        NESTED_AUDIT_FIELDS,
        audit_rows,
    )
    nested_metrics_artifact = {
        "schema_version": "rq2-v2-stage4j-p1-nested-metrics-v1",
        "status": "COMPLETED_DEV_NESTED_EVALUATION",
        "scientific_interpretation": "NESTED_CROSS_FITTED_DEV_ESTIMATE_NOT_INDEPENDENT_TEST",
        "population": {
            "partition": "DEV",
            "dialogue_action": "ANSWER",
            "case_count": 64,
            "family_count": 32,
            "outer_fold_count": 4,
        },
        "outer_fold_policy_selection": [
            {
                "outer_fold": result["outer_fold"],
                "selection_fold_ids": result["selection_fold_ids"],
                "selection_case_count": result["selection_case_count"],
                "selected_policy_id": result["selected_policy_id"],
                "outer_validation_case_count": result["outer_validation_case_count"],
                "outer_validation_gold_passed_to_selection": False,
                "outer_validation_b4_passed_to_selection": False,
                "outer_validation_metrics": result["outer_validation_metrics"],
            }
            for result in nested["outer_results"]
        ],
        "trigger_counts_all_64_by_policy": trigger_counts,
        "nested_primary_metrics": nested["nested_metrics"],
        "nested_p1_minus_b4": p1_minus_b4,
        "end_to_end_72_case_metrics": end_to_end_metrics,
        "b4_binding": b4_binding,
        "governance": {
            "new_provider_calls": 0,
            "test_access": False,
            "rq3_access": False,
            "diagnostic_policy_eligible_for_selection": False,
        },
    }
    _write_json(output_dir / "p1_nested_metrics_v1.json", nested_metrics_artifact)
    full_result_rows = [
        _policy_metric_row(full_scores[policy_id], scope="FULL_DEV_SELECTION")
        for policy_id in p1.ELIGIBLE_POLICY_IDS
    ]
    _write_csv(
        output_dir / "p1_full_dev_policy_results_v1.csv",
        tuple(full_result_rows[0]),
        full_result_rows,
    )
    _write_json(output_dir / "p1_final_policy_frozen_v1.json", final_freeze)
    _write_json(output_dir / "p1_counterfactual_cost_v1.json", cost_report)
    _write_csv(
        output_dir / "p1_model_comparison_v1.csv",
        MODEL_COMPARISON_FIELDS,
        comparison_rows,
    )
    _write_csv(
        output_dir / "p1_end_to_end_oof_predictions_v1.csv",
        END_TO_END_FIELDS,
        end_to_end_rows,
    )
    _atomic_write_text(
        output_dir / "P1_DEV_RESULTS.md",
        build_results_markdown(
            nested=nested,
            final_policy_id=final_policy_id,
            final_metrics=final_metrics,
            collapse=collapse,
            cost=cost_report,
            p1_minus_b4=p1_minus_b4,
            end_to_end=end_to_end_metrics,
            b4_binding=b4_binding,
        ),
    )
    _atomic_write_text(
        output_dir / "P1_HYBRID_COLLAPSE_AUDIT.md",
        build_collapse_markdown(collapse),
    )
    _atomic_write_text(output_dir / "STATUS.md", build_status_markdown(final_policy_id))

    # Fail closed if generation changed any source or any Stage 4J-0 frozen byte.
    verify_source_hashes()
    verify_frozen_stage4j0()
    verify_b4_binding()
    manifest = build_output_manifest(output_dir)
    _write_json(output_dir / "p1_output_manifest_v1.json", manifest)
    return {
        "status": "READY_FOR_RQ2_V2_STAGE_4_INTEGRATION",
        "git_integration": git_integration,
        "frozen_stage4j0": frozen_j0,
        "normalized_case_count": len(records),
        "policy_matrix_row_count": len(matrix_rows),
        "outer_selected_policies": {
            result["outer_fold"]: result["selected_policy_id"]
            for result in nested["outer_results"]
        },
        "nested_metrics": nested["nested_metrics"],
        "final_policy_id": final_policy_id,
        "final_metrics": final_metrics,
        "collapse_statuses": collapse["statuses"],
        "p1_minus_b4": p1_minus_b4,
        "counterfactual_cost": cost_report,
        "end_to_end_metrics": end_to_end_metrics,
        "output_count_including_manifest": len(GENERATED_OUTPUT_NAMES),
        "stage4j_new_provider_calls": 0,
    }


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Build the frozen RQ2-V2 Stage 4J P1 DEV analysis offline."
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=TRACK_DIR,
        help="Output directory; defaults to the Track J protocol directory.",
    )
    arguments = parser.parse_args(argv)
    summary = build(arguments.output_dir)
    print(json.dumps(summary, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
