"""Validate the frozen RQ2-V2 Stage 4-0 DEV-only protocol artifacts."""

from __future__ import annotations

import argparse
from collections import Counter, defaultdict
import csv
from dataclasses import dataclass
import io
import json
from pathlib import Path
from typing import Any, Mapping, Sequence

from . import (
    ANSWER_SIGNATURES,
    DEV_ALLOWED_MEMBERS,
    DEV_RELEASE_SHA256,
    FOLD_IDS,
    LAD_PAGES,
    MODEL_IDS,
    PACKAGE_ROOT,
    READY_STATUS,
    ROUTING_SIGNATURES,
    STAGE3C_RELEASE_SHA256,
)
from .build_dev_protocol import (
    DEFAULT_DEV_ZIP,
    DEFAULT_STAGE3C_ZIP,
    FOLD_FIELDS,
    GROUP_FIELDS,
    REVIEW_ARCHIVE_FILES,
    REVIEW_PAYLOAD_FILES,
    SHA256_MANIFEST_NAME,
    build_components,
    build_families,
    build_optimization_report,
    load_dev_release,
    rebuild_cv_artifacts_from_frozen_files,
    sha256_bytes,
    sha256_file,
    signature_from_dev_row,
    validate_dev_rows,
)
from .protocol_contract import project_model_features


class ProtocolValidationError(AssertionError):
    """Raised when a frozen artifact violates the Stage 4-0 contract."""


@dataclass(frozen=True)
class ValidationCheck:
    name: str
    detail: str


def _require(condition: bool, message: str) -> None:
    if not condition:
        raise ProtocolValidationError(message)


def _load_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def _load_jsonl(path: Path) -> list[dict[str, Any]]:
    rows = []
    for line_number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        if not line.strip():
            continue
        value = json.loads(line)
        _require(isinstance(value, dict), f"{path.name}:{line_number} is not an object")
        rows.append(value)
    return rows


def _load_csv(path: Path) -> tuple[tuple[str, ...], list[dict[str, str]]]:
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        reader = csv.DictReader(handle)
        return tuple(reader.fieldnames or ()), [dict(row) for row in reader]


def _normalise_group_json_row(row: Mapping[str, Any]) -> dict[str, str]:
    return {field: str(row.get(field, "")) for field in GROUP_FIELDS}


def _record(
    checks: list[ValidationCheck], name: str, condition: bool, detail: str
) -> None:
    _require(condition, f"{name}: {detail}")
    checks.append(ValidationCheck(name=name, detail=detail))


def _validate_sha_manifest(root: Path) -> None:
    manifest = _load_json(root / SHA256_MANIFEST_NAME)
    entries = manifest.get("files")
    _require(isinstance(entries, list), "protocol SHA-256 manifest files is not a list")
    _require(
        [entry.get("name") for entry in entries] == list(REVIEW_PAYLOAD_FILES),
        "protocol SHA-256 manifest allowlist differs",
    )
    for entry in entries:
        path = root / str(entry["name"])
        _require(path.is_file() and not path.is_symlink(), f"unsafe or missing file: {path.name}")
        _require(sha256_file(path) == entry.get("sha256"), f"hash mismatch: {path.name}")
        _require(path.stat().st_size == entry.get("size_bytes"), f"size mismatch: {path.name}")


def validate_protocol(
    root: Path = PACKAGE_ROOT,
    *,
    verify_source_zips: bool = False,
    dev_zip: Path = DEFAULT_DEV_ZIP,
    stage3c_zip: Path = DEFAULT_STAGE3C_ZIP,
) -> list[ValidationCheck]:
    root = Path(root)
    checks: list[ValidationCheck] = []

    actual_files = {path.name for path in root.iterdir() if path.is_file()}
    _record(
        checks,
        "artifact_allowlist",
        actual_files == set(REVIEW_ARCHIVE_FILES),
        f"{len(actual_files)} allowlisted protocol files",
    )
    _record(
        checks,
        "no_symlinks_or_nested_data",
        all(not path.is_symlink() for path in root.iterdir())
        and not any(path.is_file() for path in root.iterdir() if path.name.startswith(".")),
        "all protocol artifacts are regular visible files",
    )
    _validate_sha_manifest(root)
    _record(
        checks,
        "protocol_sha256_manifest",
        True,
        f"all {len(REVIEW_PAYLOAD_FILES)} payload hashes and sizes match",
    )

    source_manifest = _load_json(root / "DEV_SOURCE_MANIFEST.json")
    source_package = source_manifest["dev_source_package"]
    _record(
        checks,
        "dev_source_hash_commitment",
        source_package["sha256"] == DEV_RELEASE_SHA256,
        "authorized DEV ZIP SHA-256 is frozen",
    )
    member_entries = source_package["members"]
    _record(
        checks,
        "dev_member_allowlist",
        [entry["name"] for entry in member_entries] == list(DEV_ALLOWED_MEMBERS),
        "DEV package contains exactly the four authorized members",
    )
    for entry in member_entries:
        path = root / entry["name"]
        _require(sha256_file(path) == entry["sha256"], f"copied DEV hash differs: {path.name}")
        _require(path.stat().st_size == entry["size_bytes"], f"copied DEV size differs: {path.name}")
    _record(
        checks,
        "dev_members_copied_unchanged",
        True,
        "four authorized DEV members match the local source manifest",
    )
    grouping_source = source_manifest["grouping_metadata_source"]
    _record(
        checks,
        "stage3c_source_hash_commitment",
        grouping_source["sha256"] == STAGE3C_RELEASE_SHA256,
        "authorized Stage 3C ZIP SHA-256 is frozen",
    )
    _record(
        checks,
        "restricted_assignment_not_retained",
        grouping_source["non_dev_rows_retained"] == 0
        and grouping_source["writer_identity_retained"] is False
        and grouping_source["full_split_assignment_retained"] is False
        and not (root / "split_assignment_restricted_v1.csv").exists()
        and not (root / "split_assignment_restricted_v1.jsonl").exists(),
        "only the seven sanitized DEV grouping fields are retained",
    )

    dev_fields, dev_rows = _load_csv(root / "dev_capability_gold_v1.csv")
    jsonl_dev_rows = _load_jsonl(root / "dev_capability_gold_v1.jsonl")
    validate_dev_rows(dev_rows)
    _record(
        checks,
        "dev_csv_jsonl_equivalence",
        dev_rows == jsonl_dev_rows,
        "72 CSV and JSONL records are semantically identical",
    )
    family_counts = Counter(row["scenario_family_id"] for row in dev_rows)
    _record(
        checks,
        "dev_row_family_counts",
        len(dev_rows) == 72 and len(family_counts) == 36 and set(family_counts.values()) == {2},
        "72 utterances, 36 families, exactly two utterances per family",
    )
    actions = Counter(row["final_dialogue_action"] for row in dev_rows)
    _record(
        checks,
        "dev_dialogue_action_counts",
        actions == Counter({"ANSWER": 64, "CLARIFY": 8}),
        "64 ANSWER and 8 CLARIFY utterances",
    )
    _record(
        checks,
        "dev_unique_annotation_ids",
        len({row["annotation_case_id"] for row in dev_rows}) == 72,
        "zero duplicate annotation IDs",
    )
    _record(
        checks,
        "dev_family_utterance_uniqueness",
        source_manifest["verified_dev_structure"]["duplicate_family_utterance_combinations"] == 0,
        "zero duplicate Stage 3C DEV family/utterance pairs",
    )
    _record(
        checks,
        "dev_history_and_labels",
        all(signature_from_dev_row(row) in ROUTING_SIGNATURES for row in dev_rows),
        "visible histories and final human labels validate",
    )
    _record(
        checks,
        "dev_partition_only",
        {row["partition"] for row in dev_rows} == {"DEV"},
        "every copied data row is DEV",
    )

    group_fields, group_csv_rows = _load_csv(root / "dev_atomic_group_map_v1.csv")
    group_json_rows = _load_jsonl(root / "dev_atomic_group_map_v1.jsonl")
    _record(
        checks,
        "group_map_schema",
        group_fields == GROUP_FIELDS
        and all(set(row).issubset(GROUP_FIELDS) for row in group_json_rows),
        "only seven authorized grouping fields are present",
    )
    normalised_group_json = [_normalise_group_json_row(row) for row in group_json_rows]
    _record(
        checks,
        "group_map_csv_jsonl_equivalence",
        group_csv_rows == normalised_group_json,
        "72 sanitized grouping rows are byte-semantically equivalent",
    )
    dev_ids = {row["annotation_case_id"] for row in dev_rows}
    dev_families = {row["scenario_family_id"] for row in dev_rows}
    _record(
        checks,
        "group_map_dev_exact_join",
        {row["annotation_case_id"] for row in group_csv_rows} == dev_ids
        and {row["scenario_family_id"] for row in group_csv_rows} == dev_families,
        "grouping IDs are exactly the authorized DEV ID sets",
    )
    families = build_families(dev_rows, group_csv_rows)
    components = build_components(families)
    component_sizes = Counter(component.family_count for component in components)
    _record(
        checks,
        "dev_atomic_component_structure",
        len(components) == 24 and component_sizes == Counter({1: 12, 2: 12}),
        "24 components: 12 two-family contrast components and 12 singletons",
    )
    signature_counts = Counter(family.signature for family in families)
    _record(
        checks,
        "dev_family_signature_distribution",
        signature_counts == Counter({signature: 4 for signature in ROUTING_SIGNATURES}),
        "each of eight ANSWER signatures plus CLARIFY has four DEV families",
    )

    fold_fields, fold_csv_rows = _load_csv(root / "dev_cv_folds_v1.csv")
    fold_json_rows = _load_jsonl(root / "dev_cv_folds_v1.jsonl")
    _record(
        checks,
        "fold_ledger_schema",
        fold_fields == FOLD_FIELDS and all(set(row) == set(FOLD_FIELDS) for row in fold_json_rows),
        "only eight authorized CV ledger fields are present",
    )
    _record(
        checks,
        "fold_ledger_csv_jsonl_equivalence",
        fold_csv_rows == fold_json_rows,
        "288 expanded CV iteration rows are equivalent",
    )
    _record(
        checks,
        "fold_ledger_expansion",
        len(fold_csv_rows) == 288
        and Counter(row["annotation_case_id"] for row in fold_csv_rows) == Counter({case_id: 4 for case_id in dev_ids}),
        "each DEV case appears once in each of four fold iterations",
    )

    validation_by_fold: dict[str, list[dict[str, str]]] = {}
    training_by_fold: dict[str, list[dict[str, str]]] = {}
    for fold_id in FOLD_IDS:
        validation_by_fold[fold_id] = [
            row for row in fold_csv_rows if row["fold_id"] == fold_id and row["fold_role"] == "VALIDATION"
        ]
        training_by_fold[fold_id] = [
            row for row in fold_csv_rows if row["fold_id"] == fold_id and row["fold_role"] == "TRAINING"
        ]
    _record(
        checks,
        "fold_sizes",
        all(
            len(validation_by_fold[fold_id]) == 18
            and len({row["scenario_family_id"] for row in validation_by_fold[fold_id]}) == 9
            and len(training_by_fold[fold_id]) == 54
            for fold_id in FOLD_IDS
        ),
        "each fold has 18/9 validation utterances/families and 54 training utterances",
    )
    _record(
        checks,
        "one_validation_fold_per_case",
        all(
            Counter(row["fold_role"] for row in fold_csv_rows if row["annotation_case_id"] == case_id)
            == Counter({"VALIDATION": 1, "TRAINING": 3})
            for case_id in dev_ids
        ),
        "each case is validation once and training three times",
    )
    _record(
        checks,
        "atomic_fold_isolation",
        all(
            len(
                {
                    row["fold_id"]
                    for row in fold_csv_rows
                    if row["dev_atomic_component_id"] == component_id
                    and row["fold_role"] == "VALIDATION"
                }
            )
            == 1
            for component_id in {row["dev_atomic_component_id"] for row in group_csv_rows}
        ),
        "no family or atomic contrast component crosses validation folds",
    )
    _record(
        checks,
        "one_clarify_family_per_fold",
        all(
            len(
                {
                    row["scenario_family_id"]
                    for row in validation_by_fold[fold_id]
                    if row["final_dialogue_action"] == "CLARIFY"
                }
            )
            == 1
            for fold_id in FOLD_IDS
        ),
        "exactly one CLARIFY family per validation fold",
    )
    _record(
        checks,
        "validation_label_coverage",
        all(
            all(
                {row["final_routing_signature"][bit] for row in validation_by_fold[fold_id] if row["final_dialogue_action"] == "ANSWER"}
                == {"0", "1"}
                for bit in range(3)
            )
            for fold_id in FOLD_IDS
        ),
        "every validation fold has YES and NO families for all three capabilities",
    )
    _record(
        checks,
        "training_signature_coverage",
        all(
            {row["final_routing_signature"] for row in training_by_fold[fold_id] if row["final_dialogue_action"] == "ANSWER"}
            == set(ANSWER_SIGNATURES)
            for fold_id in FOLD_IDS
        ),
        "every training complement contains all eight ANSWER signatures",
    )
    _record(
        checks,
        "validation_page_coverage",
        all({row["current_page"] for row in validation_by_fold[fold_id]} == set(LAD_PAGES) for fold_id in FOLD_IDS),
        "all five LAD pages occur in every validation fold",
    )

    rebuilt, solution = rebuild_cv_artifacts_from_frozen_files(root)
    _record(
        checks,
        "fixed_seed_byte_identical_folds",
        all((root / name).read_bytes() == payload for name, payload in rebuilt.items()),
        "seed 20260831 reproduces CV ledgers, reports, and protocol bytes",
    )
    _record(
        checks,
        "cv_lexicographic_objective",
        solution.objective == (4, 80, 2),
        "global lexicographic objective is (4, 80, 2)",
    )
    optimization = _load_json(root / "DEV_CV_OPTIMIZATION_REPORT.json")
    _record(
        checks,
        "cv_feasibility_report",
        optimization == build_optimization_report(solution)
        and optimization["all_five_lad_pages_per_validation_fold_feasible"] is True,
        "feasibility and per-fold balance distributions match recomputation",
    )

    protocol = _load_json(root / "stage4_dev_protocol_v1.json")
    _record(
        checks,
        "protocol_status",
        protocol["status"] == READY_STATUS,
        READY_STATUS,
    )
    _record(
        checks,
        "protocol_artifact_hashes",
        protocol["dev_grouping_map"]["primary_sha256"]
        == sha256_file(root / "dev_atomic_group_map_v1.jsonl")
        and protocol["cross_validation"]["primary_sha256"]
        == sha256_file(root / "dev_cv_folds_v1.jsonl"),
        "canonical grouping-map and fold-assignment SHA-256 values match",
    )
    metrics = protocol["evaluation_metrics"]
    secondary_names = {item["name"] for item in metrics["secondary_core_capability_metrics"]}
    clarification_names = {item["name"] for item in metrics["shared_clarification_metrics"]}
    end_to_end_names = {item["name"] for item in metrics["end_to_end_metrics"]}
    _record(
        checks,
        "metric_contract",
        metrics["primary_core_capability_metric"]["name"] == "macro_f1"
        and secondary_names
        == {
            "micro_f1",
            "per_label_precision_recall_f1",
            "exact_capability_set_match",
            "example_based_f1",
            "jaccard",
            "hamming_loss",
            "under_routing_rate",
            "over_routing_rate",
            "family_both_utterances_correct_rate",
            "contrast_consistency",
            "page_stratified_metrics",
            "writer_a_vs_writer_b_performance",
        }
        and clarification_names
        == {
            "clarification_accuracy",
            "clarify_precision_recall_f1",
            "full_dialogue_action_exact_match",
        }
        and end_to_end_names
        == {"full_route_signature_exact_match", "family_level_full_route_consistency"}
        and metrics["performance_calculated_in_stage4_0"] is False,
        "primary, secondary, clarification, and end-to-end metrics are frozen without scores",
    )
    tie_breaks = protocol["model_selection_tie_breaks"]
    _record(
        checks,
        "tie_break_contract",
        [item["metric"] for item in tie_breaks["ordered_rules"]]
        == [
            "macro_f1",
            "exact_capability_set_match",
            "jaccard",
            "under_routing_rate",
            "over_routing_rate",
            "predeclared_simplicity_key",
            "config_id",
        ]
        and tie_breaks["test_performance_used"] is False,
        "seven ordered DEV-only selection rules match the authorization",
    )
    boundary = protocol["clarification_boundary"]
    _record(
        checks,
        "clarification_boundary",
        boundary["applies_to_model_ids"] == list(MODEL_IDS)
        and boundary["predicted_clarify_behavior"]["execute_core_capability_router"] is False
        and set(boundary["predicted_clarify_behavior"].values())
        == {False, "NOT_APPLICABLE"},
        "shared gate stops all core Routers and emits three NOT_APPLICABLE outputs",
    )
    first_dev = dev_rows[0]
    feature_keys = {
        model_id: set(project_model_features(first_dev, model_id)) for model_id in MODEL_IDS
    }
    _record(
        checks,
        "model_feature_profile",
        feature_keys["R2V2-B1_LEGACY_INTENT"] == {"current_query", "current_page"}
        and all(
            keys
            == {
                "current_query",
                "current_page",
                "dashboard_context",
                "visible_conversation_history",
            }
            for model_id, keys in feature_keys.items()
            if model_id != "R2V2-B1_LEGACY_INTENT"
        ),
        "primary semantic profile and historical B1 query/page boundary are exact",
    )
    forbidden_fields = set(protocol["feature_contract"]["forbidden_model_features"])
    _record(
        checks,
        "model_feature_leakage_exclusion",
        all(not (keys & forbidden_fields) for keys in feature_keys.values()),
        "IDs, labels, folds, contrasts, partitions, actions, and writer identity are excluded",
    )

    all_ledger_ids = {row["annotation_case_id"] for row in (*group_csv_rows, *fold_csv_rows)}
    all_ledger_families = {row["scenario_family_id"] for row in (*group_csv_rows, *fold_csv_rows)}
    _record(
        checks,
        "zero_unrecognized_identifier_leakage",
        all_ledger_ids <= dev_ids and all_ledger_families <= dev_families,
        "every output ledger identifier is a member of the exact DEV-only release",
    )
    forbidden_group_fields = {
        "partition",
        "writer_id",
        "utterance_id",
        "split_seed",
        "split_version",
        "split_status",
    }
    _record(
        checks,
        "zero_restricted_field_leakage",
        not (set(group_fields) & forbidden_group_fields)
        and "partition" not in fold_fields
        and all(row["fold_role"] in {"TRAINING", "VALIDATION"} for row in fold_csv_rows),
        "no writer, partition, full-assignment, or other restricted field enters output ledgers",
    )
    execution = protocol["stage4_0_execution"]
    _record(
        checks,
        "zero_model_or_test_execution",
        not any(execution.values())
        and not any(protocol["test_prohibition"].values())
        and protocol["primary_experiment_augmentation"]["synthetic_augmentation_allowed"] is False,
        "no training, Router/provider call, performance calculation, TEST execution, RQ3, or augmentation",
    )

    if verify_source_zips:
        payloads, source_rows = load_dev_release(dev_zip)
        _record(
            checks,
            "live_dev_source_zip",
            len(payloads) == 4 and source_rows == dev_rows,
            "live authorized DEV ZIP hash, allowlist, and copied bytes match",
        )
        _record(
            checks,
            "live_stage3c_source_zip_hash",
            Path(stage3c_zip).is_file() and sha256_file(stage3c_zip) == STAGE3C_RELEASE_SHA256,
            "live Stage 3C source ZIP hash matches without reopening restricted rows",
        )

    return checks


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=PACKAGE_ROOT)
    parser.add_argument("--verify-source-zips", action="store_true")
    parser.add_argument("--dev-zip", type=Path, default=DEFAULT_DEV_ZIP)
    parser.add_argument("--stage3c-zip", type=Path, default=DEFAULT_STAGE3C_ZIP)
    args = parser.parse_args(argv)
    checks = validate_protocol(
        args.root,
        verify_source_zips=args.verify_source_zips,
        dev_zip=args.dev_zip,
        stage3c_zip=args.stage3c_zip,
    )
    for check in checks:
        print(f"PASS {check.name}: {check.detail}")
    print(f"PASS SUMMARY: {len(checks)}/{len(checks)} checks passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
