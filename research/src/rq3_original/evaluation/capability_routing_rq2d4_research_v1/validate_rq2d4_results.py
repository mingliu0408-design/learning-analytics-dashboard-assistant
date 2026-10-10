"""Post-result validation and governed-text leak scan for RQ2-D4."""

from __future__ import annotations

import csv
import io
import json
from pathlib import Path
import subprocess
from typing import Any, Iterable

from . import (
    CAPABILITIES,
    FEATURE_VIEW_RELATIVE,
    HERE,
    LOCAL_RESULTS_RELATIVE,
    METHODS,
    PREDICTION_RELATIVES,
    ROOT,
    START_HEAD,
    jsonl_rows_from_bytes,
    sha256_file,
)
from .run_rq2d4_research_evaluation import DOC_NAMES, FIGURE_NAMES, PYTHON_NAMES
from .score_capability_predictions import LOCAL_RESULT_NAMES


FORBIDDEN_TRACKED_KEYS = {
    "review_case_id",
    "current_query",
    "necessary_conversation_history",
    "conversation_history",
    "student_id",
    "source_raw_id",
    "reviewer_rationale",
    "adjudicator_rationale",
}


def _walk_keys(value: Any) -> Iterable[str]:
    if isinstance(value, dict):
        for key, item in value.items():
            yield str(key)
            yield from _walk_keys(item)
    elif isinstance(value, list):
        for item in value:
            yield from _walk_keys(item)


def _raw_strings(value: Any) -> Iterable[str]:
    if isinstance(value, str):
        if len(value.strip()) >= 8:
            yield value
    elif isinstance(value, dict):
        for item in value.values():
            yield from _raw_strings(item)
    elif isinstance(value, list):
        for item in value:
            yield from _raw_strings(item)


def _checksum_entries() -> list[tuple[str, Path]]:
    manifest = HERE / "rq2d4_output_checksums_v1.sha256"
    entries: list[tuple[str, Path]] = []
    for line in manifest.read_text(encoding="utf-8").splitlines():
        digest, relative = line.split("  ", 1)
        path = Path(relative)
        if path.is_absolute() or ".." in path.parts:
            raise RuntimeError("BLOCKED_RQ2_D4_TEST_FAILURE")
        entries.append((digest, ROOT / path))
    return entries


def validate_results() -> dict[str, Any]:
    required = [
        HERE / name for name in (*PYTHON_NAMES,
            "rq2d4_final_metrics_v1.json",
            "rq2d4_final_comparisons_v1.json",
            "rq2d4_final_error_summary_v1.json",
            "rq2d4_result_freeze_v1.json",
            "rq2d4_runtime_report_v1.json",
            "rq2d4_per_capability_metrics_v1.csv",
            "rq2d4_output_checksums_v1.sha256",
        )
    ]
    required += [ROOT / "docs/thesis_mainline/rq2" / name for name in DOC_NAMES]
    required += [ROOT / "docs/thesis_mainline/rq2/figures" / name for name in FIGURE_NAMES]
    if any(not path.is_file() or path.is_symlink() for path in required):
        raise RuntimeError("BLOCKED_RQ2_D4_TEST_FAILURE")

    checksum_entries = _checksum_entries()
    if len(checksum_entries) != 22 or len({path for _, path in checksum_entries}) != 22:
        raise RuntimeError("BLOCKED_RQ2_D4_TEST_FAILURE")
    for expected, path in checksum_entries:
        if not path.is_file() or path.is_symlink() or sha256_file(path) != expected:
            raise RuntimeError("BLOCKED_RQ2_D4_TEST_FAILURE")

    json_paths = [
        HERE / "rq2d4_final_metrics_v1.json",
        HERE / "rq2d4_final_comparisons_v1.json",
        HERE / "rq2d4_final_error_summary_v1.json",
        HERE / "rq2d4_result_freeze_v1.json",
        HERE / "rq2d4_runtime_report_v1.json",
    ]
    documents = [json.loads(path.read_text(encoding="utf-8")) for path in json_paths]
    if any(FORBIDDEN_TRACKED_KEYS & set(_walk_keys(document)) for document in documents):
        raise RuntimeError("BLOCKED_RQ2_D4_FEATURE_LABEL_LEAKAGE")
    metrics, comparisons, errors, freeze, runtime = documents
    if (
        set(metrics["methods"]) != set(METHODS)
        or set(comparisons["comparisons"]) != {"P1_VS_B1", "B1_VS_B0", "P1_VS_B0"}
        or metrics.get("p2_execution_count") != 0
        or runtime.get("track_b_prediction_execution_count") != 1
        or runtime.get("track_b_scoring_execution_count") != 1
        or runtime.get("development_parity", {}).get("prediction_mismatch_count") != 0
        or runtime.get("runtime_smoke", {}).get("status") != "PASS"
        or freeze.get("status") != "FROZEN"
    ):
        raise RuntimeError("BLOCKED_RQ2_D4_TEST_FAILURE")
    for method in METHODS:
        method_metrics = metrics["methods"][method]
        if set(method_metrics["per_capability"]) != set(CAPABILITIES):
            raise RuntimeError("BLOCKED_RQ2_D4_METRIC_OR_STATISTICAL_FAILURE")
    if (
        errors["context_subsets"]["CONTEXT_RESOLUTION_REQUIRED_YES"]["record_count"] != 39
        or errors["context_subsets"]["CONTEXT_RESOLUTION_REQUIRED_NO"]["record_count"] != 9
        or errors["clarification"]["gold_clarification_case_count"] != 4
    ):
        raise RuntimeError("BLOCKED_RQ2_D4_METRIC_OR_STATISTICAL_FAILURE")

    csv_payload = (HERE / "rq2d4_per_capability_metrics_v1.csv").read_text(encoding="utf-8")
    csv_rows = list(csv.DictReader(io.StringIO(csv_payload)))
    if len(csv_rows) != 18 or any("case" in key.lower() for key in csv_rows[0]):
        raise RuntimeError("BLOCKED_RQ2_D4_FEATURE_LABEL_LEAKAGE")

    feature_rows = jsonl_rows_from_bytes((ROOT / FEATURE_VIEW_RELATIVE).read_bytes())
    governed_strings: set[str] = set()
    for row in feature_rows:
        governed_strings.update(_raw_strings(row["current_query"]))
        governed_strings.update(_raw_strings(row["necessary_conversation_history"]))
    review_safe_paths = [
        path for path in required if not str(path).endswith(".py") and path.suffix != ".png"
    ]
    leak_count = 0
    for path in review_safe_paths:
        text = path.read_text(encoding="utf-8")
        if "/Users/" in text or "file://" in text:
            leak_count += 1
        leak_count += sum(raw in text for raw in governed_strings)
    if leak_count:
        raise RuntimeError("BLOCKED_RQ2_D4_FEATURE_LABEL_LEAKAGE")

    for relative in [FEATURE_VIEW_RELATIVE, *PREDICTION_RELATIVES.values(), LOCAL_RESULTS_RELATIVE]:
        completed = subprocess.run(
            ["git", "check-ignore", "-q", str(relative)], cwd=ROOT, check=False
        )
        if completed.returncode != 0:
            raise RuntimeError("BLOCKED_RQ2_D4_TEST_FAILURE")

    changed = set(
        subprocess.run(
            ["git", "status", "--porcelain=v1", "--untracked-files=all"],
            cwd=ROOT,
            text=True,
            check=True,
            capture_output=True,
        ).stdout.splitlines()
    )
    for line in changed:
        path = line[3:]
        if not (
            path.startswith("evaluation/capability_routing_rq2d4_research_v1/")
            or path.startswith("docs/thesis_mainline/rq2/RQ2D4_")
            or path.startswith("docs/thesis_mainline/rq2/figures/rq2d4_")
        ):
            raise RuntimeError("BLOCKED_RQ2_D4_TEST_FAILURE")
    tracked_old_changes = subprocess.run(
        ["git", "diff", "--name-only", START_HEAD, "--"],
        cwd=ROOT,
        text=True,
        check=True,
        capture_output=True,
    ).stdout.splitlines()
    if any(
        not (
            path.startswith("evaluation/capability_routing_rq2d4_research_v1/")
            or path.startswith("docs/thesis_mainline/rq2/RQ2D4_")
            or path.startswith("docs/thesis_mainline/rq2/figures/rq2d4_")
        )
        for path in tracked_old_changes
    ):
        raise RuntimeError("BLOCKED_RQ2_D4_TEST_FAILURE")

    return {
        "status": "PASS",
        "output_checksum_count": len(checksum_entries),
        "method_count": 3,
        "record_count_per_method": 48,
        "comparison_count": 3,
        "context_required_count": 39,
        "context_not_required_count": 9,
        "clarification_support": 4,
        "governed_text_leak_count": 0,
        "absolute_path_leak_count": 0,
        "local_artifacts_ignored": True,
        "protected_source_violation_count": 0,
        "p2_execution_count": 0,
        "provider_calls": 0,
        "network_access": False,
    }


def main() -> int:
    print(json.dumps(validate_results(), sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
