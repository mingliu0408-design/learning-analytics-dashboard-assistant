"""Static, fail-closed validation for RQ2-V2 Stage 4N.

The validator never executes a Router, imports a provider SDK, scores TEST, or
opens TEST Gold.  It validates raw hashes, schemas, unexecuted manifests,
deterministic regeneration, ZIP allowlists, and zero-execution evidence.
"""

from __future__ import annotations

import argparse
import ast
import json
from pathlib import Path, PurePosixPath
import subprocess
import tempfile
from typing import Any, Mapping
import zipfile

from .build_final_integration import (
    build_all,
    read_json,
    sha256_file,
    verify_embedded_identities,
    verify_frozen_sources,
    verify_test_inputs,
)
from .build_packages import package_specs
from .constants import (
    B4_MODEL,
    DETERMINISTIC_METHOD_IDS,
    EXPECTED_SOURCE_HASHES,
    EXPECTED_TEST_INPUT_HASHES,
    FORBIDDEN_TEST_FIELD_NAMES,
    INTEGRATION_DIR,
    METHOD_IDS,
    PACKAGE_PATHS,
    PRIMARY_FIELDS,
    PROVIDER_STREAMS,
    READY_STATUS,
    REPORTING_TIERS,
    REPOSITORY_ROOT,
    SOURCE_STAGE_HEAD,
    TEST_INPUT_DIR,
    TEST_INPUT_FIELDS,
)
from .validate_execution_package import validate as validate_zip


class ValidationError(RuntimeError):
    """Raised when one Stage 4N invariant differs."""


def _require(condition: bool, label: str) -> None:
    if not condition:
        raise ValidationError(label)


def _load_jsonl(path: Path) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line:
            continue
        value = json.loads(line)
        _require(isinstance(value, dict), f"JSONL record is not an object: {path.name}")
        rows.append(value)
    return rows


def _forbidden_keys(value: Any) -> set[str]:
    found: set[str] = set()
    if isinstance(value, Mapping):
        for key, nested in value.items():
            normalized = str(key).casefold()
            if normalized in FORBIDDEN_TEST_FIELD_NAMES or normalized.startswith("gold_"):
                found.add(str(key))
            found.update(_forbidden_keys(nested))
    elif isinstance(value, list):
        for nested in value:
            found.update(_forbidden_keys(nested))
    return found


def _git(*args: str) -> str:
    result = subprocess.run(
        ["git", *args], cwd=REPOSITORY_ROOT, check=True,
        capture_output=True, text=True,
    )
    return result.stdout.strip()


def validate_repository(*, regeneration: bool = True) -> list[str]:
    passed: list[str] = []

    def check(label: str, condition: bool = True) -> None:
        _require(condition, label)
        passed.append(label)

    source_rows, external_rows = verify_frozen_sources()
    check("Stage 4M source commit object exists", bool(_git("cat-file", "-t", SOURCE_STAGE_HEAD) == "commit"))
    check("all frozen repository source hashes match", len(source_rows) == len(EXPECTED_SOURCE_HASHES))
    check("all frozen external C0/MPNet hashes match", len(external_rows) == 8)
    verify_embedded_identities()
    check("all embedded frozen method identities match")

    frozen_diff = _git("diff", "--name-only", SOURCE_STAGE_HEAD, "--", "evaluation/capability_routing_rq2_v2_stage4")
    changed_existing = [
        name for name in frozen_diff.splitlines()
        if name and not name.startswith("evaluation/capability_routing_rq2_v2_stage4/final_integration/")
    ]
    check("no pre-Stage4N Stage-4 artifact changed", not changed_existing)

    allowed_extracted = set(EXPECTED_TEST_INPUT_HASHES)
    extracted = {path.name for path in TEST_INPUT_DIR.iterdir() if path.is_file()}
    check("only four allowlisted escrow members are extracted", extracted == allowed_extracted)
    input_rows = verify_test_inputs()
    check("TEST input population is exactly 36 unique rows and IDs", len(input_rows) == 36 and len({row["annotation_case_id"] for row in input_rows}) == 36)
    check("TEST inputs use exactly the four semantic fields plus annotation ID", all(set(row) == set(TEST_INPUT_FIELDS) for row in input_rows))
    check("visible-history JSON is valid for all TEST rows", all(isinstance(row["visible_conversation_history"], list) for row in input_rows))
    check("TEST inputs have no labels IDs Gold or partition features", all(not _forbidden_keys(row) for row in input_rows))

    verification = read_json(INTEGRATION_DIR / "test_input_verification_v1.json")
    check("TEST input status is FROZEN_UNSCORED_INPUTS", verification.get("TEST_INPUT_STATUS") == "FROZEN_UNSCORED_INPUTS")
    check("TEST Gold non-access/non-extraction evidence is explicit", verification.get("TEST_Gold_opened") is False and verification.get("TEST_Gold_extracted") is False)

    registry = read_json(INTEGRATION_DIR / "final_method_registry_v1.json")
    methods = registry.get("methods") or []
    method_ids = [item.get("method_id") for item in methods]
    check("final method universe has exactly 14 methods", registry.get("method_count") == 14 and len(methods) == 14)
    check("final method IDs and order are exact", tuple(method_ids) == METHOD_IDS)
    check("all methods remain TEST NOT_EXECUTED", all(item.get("TEST_status") == "NOT_EXECUTED" for item in methods))
    check("reporting tiers are exact", registry.get("reporting_tiers") == REPORTING_TIERS)
    p4 = next(item for item in methods if item["method_id"] == "R2V2-P4_MEMORY_SPECIALIST_COMPOSITION")
    check("P4 remains post-DEV exploratory", p4.get("method_tier") == "TIER_3_POST_DEV_EXPLORATORY" and p4.get("confirmatory_exploratory_role") == "EXPLORATORY_FACTORIAL_ABLATION")
    check("no TEST winner is designated", registry.get("winner_designated") is False)
    exact_sources = [source for method in methods for source in method.get("exact_source_files") or []]
    check("method source references carry exact frozen hashes", all(EXPECTED_SOURCE_HASHES.get(item.get("path")) == item.get("sha256") for item in exact_sources))

    source_registry = read_json(INTEGRATION_DIR / "frozen_source_hash_registry_v1.json")
    check("frozen source registry passes all bindings", source_registry.get("registry_status") == "PASS_ALL_FROZEN_SOURCE_BINDINGS")
    check("frozen source registry binds Stage 4M HEAD", source_registry.get("source_stage_head") == SOURCE_STAGE_HEAD)
    deterministic_registry = read_json(INTEGRATION_DIR / "deterministic_source_hash_registry_v1.json")
    deterministic_paths = {item["path"] for item in deterministic_registry.get("source_files") or []}
    check("deterministic source registry is method-scoped", deterministic_registry.get("method_ids") == list(DETERMINISTIC_METHOD_IDS) and deterministic_paths < set(EXPECTED_SOURCE_HASHES))

    deterministic_path = INTEGRATION_DIR / "deterministic_test_execution_manifest_v1.jsonl"
    deterministic = _load_jsonl(deterministic_path)
    deterministic_allowed = {"logical_case_id", "annotation_case_id", *PRIMARY_FIELDS, "execution_status"}
    check("deterministic manifest has exactly 36 records", len(deterministic) == 36)
    check("deterministic manifest fields/status are exact", all(set(row) == deterministic_allowed and row["execution_status"] == "NOT_EXECUTED" for row in deterministic))
    base_ids = {row["annotation_case_id"] for row in deterministic}

    for stream, spec in PROVIDER_STREAMS.items():
        records = _load_jsonl(INTEGRATION_DIR / spec["manifest"])
        check(f"{stream} manifest has exactly 36 records", len(records) == 36)
        check(f"{stream} annotation population matches deterministic manifest", {row["annotation_case_id"] for row in records} == base_ids)
        check(f"{stream} model prompt schema and examples are preserved", all(
            row.get("model_snapshot") == B4_MODEL
            and row.get("prompt_template_sha256") == spec["prompt_sha256"]
            and row.get("response_schema_sha256") == spec["schema_sha256"]
            and row.get("final_full_dev_example_set_sha256") == spec["example_set_sha256"]
            and len(row.get("final_full_dev_example_ids_in_order") or []) == 8
            for row in records
        ))
        check(f"{stream} retry and token controls are frozen", all(
            row.get("execution_controls") == {
                "temperature": 0,
                "max_output_tokens": spec["max_output_tokens"],
                "sdk_transport_retries": 0,
                "manual_retry_max": 1,
                "manual_retry_only_after": ["INVALID_JSON", "STRICT_SCHEMA_VALIDATION_FAILED"],
                "prompt_change_on_retry": False,
            }
            for row in records
        ))
        payloads_valid = True
        for row in records:
            payload = row.get("provider_request_payload")
            if not isinstance(payload, dict) or _forbidden_keys(payload):
                payloads_valid = False
                break
            messages = payload.get("messages") or []
            try:
                current_input = json.loads(messages[-1]["content"])
            except (IndexError, KeyError, TypeError, json.JSONDecodeError):
                payloads_valid = False
                break
            if set(current_input) != set(PRIMARY_FIELDS) or current_input != {field: row[field] for field in PRIMARY_FIELDS}:
                payloads_valid = False
                break
        check(f"{stream} provider payloads contain only Gold-free TEST semantic input", payloads_valid)
        check(f"{stream} has zero TEST predictions", all(
            row.get("execution_status") == "NOT_EXECUTED"
            and not ({"prediction", "terminal_result", "score"} & set(row))
            for row in records
        ))

    population = read_json(INTEGRATION_DIR / "test_execution_population_v1.json")
    check("future logical call counts are exact", population.get("provider_totals", {}).get("logical_calls") == 108 and population.get("deterministic", {}).get("method_outputs") == 252)
    check("future physical attempt ceilings are exact", population.get("provider_totals", {}).get("physical_attempt_ceiling") == 216 and all(population.get(name, {}).get("physical_attempt_ceiling") == 72 for name in PROVIDER_STREAMS))
    check("Stage 4N records zero predictions calls and scores", population.get("actual_stage4n") == {"predictions": 0, "provider_calls": 0, "scores": 0})

    scoring = read_json(INTEGRATION_DIR / "final_test_scoring_protocol_v1.json")
    check("scoring gate opens Gold only after predictions freeze", scoring.get("gold_access_gate", {}).get("open_TEST_Gold_only_after_all_prediction_files_are_frozen") is True)
    check("core and end-to-end scoring populations are exact", scoring.get("core_capability_scoring", {}).get("population") == "GOLD_ANSWER_CASES_ONLY_DERIVED_AT_SCORING_TIME" and scoring.get("end_to_end_scoring", {}).get("population") == "ALL_36_TEST_INPUTS")
    check("actual and counterfactual call reporting are separated", scoring.get("call_and_cost_reporting", {}).get("actual_experimental_provider_calls_reported") is True and scoring.get("call_and_cost_reporting", {}).get("counterfactual_deployment_calls_and_costs_reported_separately") is True)
    hierarchy = read_json(INTEGRATION_DIR / "comparison_hierarchy_v1.json")
    check("comparison hierarchy and P4 role are frozen", hierarchy.get("P4_role") == "EXPLORATORY_POST_DEV_ABLATION" and hierarchy.get("winner_designated") is False)
    uncertainty = read_json(INTEGRATION_DIR / "uncertainty_reporting_plan_v1.json")
    check("family-clustered uncertainty plan is exact", uncertainty.get("resampling_unit") == "scenario_family_id" and uncertainty.get("seed") == 20260831 and uncertainty.get("bootstrap_replicates") == 10000 and uncertainty.get("interval") == {"level": 0.95, "method": "PERCENTILE"})
    check("uncertainty is descriptive and cannot alter methods", uncertainty.get("interpretation") == "DESCRIPTIVE_UNCERTAINTY_NOT_SIGNIFICANCE_TESTING" and uncertainty.get("may_change_methods_thresholds_prompts_or_tiers") is False and uncertainty.get("statistical_significance_promised") is False)

    status = (INTEGRATION_DIR / "STATUS.md").read_text(encoding="utf-8")
    check("final READY status is set", READY_STATUS in status)
    check("status explicitly records zero execution and Gold access", "Provider calls made in Stage 4N: 0" in status and "TEST Gold opened or extracted in Stage 4N: no" in status)

    generated = read_json(INTEGRATION_DIR / "STAGE4N_GENERATED_SHA256_MANIFEST.json")
    generated_ok = all(
        (INTEGRATION_DIR / item["path"]).is_file()
        and sha256_file(INTEGRATION_DIR / item["path"]) == item["sha256"]
        for item in generated.get("files") or []
    )
    check("generated-artifact SHA-256 manifest verifies", generated_ok)

    provider_tree = ast.parse((INTEGRATION_DIR / "execute_provider_test.py").read_text(encoding="utf-8"))
    top_imports = [node for node in provider_tree.body if isinstance(node, (ast.Import, ast.ImportFrom))]
    check("provider SDK is not imported at module load", all(
        not (
            isinstance(node, ast.Import) and any(alias.name == "openai" for alias in node.names)
        ) and not (
            isinstance(node, ast.ImportFrom) and node.module == "openai"
        )
        for node in top_imports
    ))
    check("future runners require a separate literal authorization token", all(
        "RQ2_V2_FINAL_TEST_PREDICTION_EXECUTION_AUTHORIZED" in (INTEGRATION_DIR / name).read_text(encoding="utf-8")
        for name in ("execute_provider_test.py", "execute_deterministic_test.py")
    ))

    actual_prediction_files = [
        path for path in INTEGRATION_DIR.rglob("*")
        if path.is_file() and (
            "terminal_result" in path.name.casefold()
            or path.name.casefold().endswith("_predictions_v1.csv")
            or path.name.casefold().endswith("_predictions_v1.jsonl")
        )
    ]
    check("no TEST terminal-result or prediction file exists", not actual_prediction_files)

    if regeneration:
        with tempfile.TemporaryDirectory(prefix="rq2-v2-stage4n-regeneration-") as temporary:
            regenerated = Path(temporary)
            build_all(regenerated)
            names = [
                "final_method_registry_v1.json",
                "deterministic_test_execution_manifest_v1.jsonl",
                *[spec["manifest"] for spec in PROVIDER_STREAMS.values()],
                "final_test_scoring_protocol_v1.json",
            ]
            identical = all(
                (INTEGRATION_DIR / name).read_bytes() == (regenerated / name).read_bytes()
                for name in names
            )
        check("registry/manifests/scoring regenerate byte-identically", identical)
    return passed


def validate_packages() -> list[str]:
    passed: list[str] = []

    def check(label: str, condition: bool = True) -> None:
        _require(condition, label)
        passed.append(label)

    specs = package_specs()
    package_hashes = read_json(INTEGRATION_DIR / "package_hashes_v1.json")
    check("package hash registry reports all audits passed", package_hashes.get("status") == "PASS_ALL_PACKAGE_AUDITS")
    for role, items in specs.items():
        path = PACKAGE_PATHS[role]
        audit = validate_zip(path)
        check(f"{role} ZIP CRC and internal member hashes pass", audit.get("crc_status") == "PASS")
        expected_names = [*sorted(items), "PACKAGE_MANIFEST.json"]
        with zipfile.ZipFile(path) as archive:
            names = archive.namelist()
            safe = all(not PurePosixPath(name).is_absolute() and ".." not in PurePosixPath(name).parts for name in names)
        check(f"{role} ZIP exact allowlist passes", names == expected_names and safe)
        check(f"{role} ZIP contains no TEST Gold member", all("gold" not in PurePosixPath(name).name.casefold() for name in names))
        recorded = package_hashes.get("packages", {}).get(role, {})
        check(f"{role} external ZIP hash is recorded exactly", recorded.get("path") == str(path) and recorded.get("sha256") == sha256_file(path))

    b4_names = set(zipfile.ZipFile(PACKAGE_PATHS["B4"]).namelist())
    rag_names = set(zipfile.ZipFile(PACKAGE_PATHS["RAG_SPECIALIST"]).namelist())
    memory_names = set(zipfile.ZipFile(PACKAGE_PATHS["MEMORY_SPECIALIST"]).namelist())
    check("B4 execution ZIP contains only B4 frozen sources", not any("rag_specialist" in name or "memory_specialist" in name for name in b4_names))
    check("RAG Specialist ZIP excludes B4 and Memory frozen sources", not any("track_i_b4" in name or "memory_specialist" in name for name in rag_names))
    check("Memory Specialist ZIP excludes B4 and RAG frozen sources", not any("track_i_b4" in name or "rag_specialist" in name for name in memory_names))
    return passed


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--skip-packages", action="store_true")
    parser.add_argument("--skip-regeneration", action="store_true")
    args = parser.parse_args()
    checks = validate_repository(regeneration=not args.skip_regeneration)
    if not args.skip_packages:
        checks.extend(validate_packages())
    for index, label in enumerate(checks, start=1):
        print(f"PASS {index:03d} {label}")
    print(f"SUMMARY {len(checks)}/{len(checks)} PASS; 0 FAIL")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
