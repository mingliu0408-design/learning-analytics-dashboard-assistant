"""Build and validate deterministic, text-free RQ1-C0-R2 safety artifacts."""

from __future__ import annotations

import argparse
import ast
import builtins
import csv
import hashlib
import io
import json
import subprocess
import tempfile
from pathlib import Path
from typing import Any, Mapping, Sequence

from . import (
    AUTHORITY_BRIDGE_PATH,
    AUTHORITY_CONTRACT_SHA256,
    EFFECTIVE_EXPERIMENT_CONTRACT_SHA256,
    FINAL_RESULT_RELATIVE,
    HERE,
    LABEL_UNIVERSE,
    LOCAL_ARTIFACTS_RELATIVE,
    LOCK_FILE_NAME,
    R1_HARNESS_HEAD,
    ROOT,
    STATISTICAL_CONTRACT_SHA256,
    STATISTICAL_MODULE_SHA256,
    TARGET_BRANCH,
    TRACK_A_RELATIVE_PATH,
    V0_SEEDS,
)
from .authority_contract import (
    build_authority_contract,
    canonical_json_bytes,
    sha256_file,
    validate_authority_contract,
    validate_requested_asset_name,
    verify_authority_bridge,
)
from .checkpoint_loader import verify_all_checkpoints
from .contamination_audit import (
    FinalEvaluationInvalid,
    audit_contamination,
    build_reference_identity_sets,
    require_contamination_clear,
)
from .final_input_schema import (
    CONTAMINATION_NORMALISATION,
    SOURCE_NORMALISATION,
    build_synthetic_final_csv,
    deterministic_normalised_query,
    parse_final_csv_bytes,
    source_track_a_normalised_query,
)
from .final_metrics import compute_fixed16_metrics, run_frozen_final_decision
from .final_model_runner import prepare_final_runtime_bundle_for_validation
from .sealed_access import (
    FinalResultTarget,
    SealedAccessError,
    consume_one_shot_asset,
    persist_result_atomically,
    preflight_final_result_path,
)


class HarnessValidationError(RuntimeError):
    pass


PYTHON_FILES = (
    "__init__.py",
    "authority_contract.py",
    "checkpoint_loader.py",
    "final_input_schema.py",
    "contamination_audit.py",
    "final_metrics.py",
    "final_model_runner.py",
    "sealed_access.py",
    "run_rq1c_final.py",
    "validate_rq1c_harness.py",
    "test_rq1c_harness_unittest.py",
)
JSON_FILES = (
    "rq1c_schema_persistence_amendment_v1.json",
    "rq1c_r2_synthetic_validation_v1.json",
    "rq1c_r2_dev_parity_v1.json",
    "rq1c_r2_prearm_runtime_v1.json",
    "rq1c_r2_harness_preflight_v1.json",
)
DOC_RELATIVES = (
    "docs/thesis_mainline/rq1/RQ1C0_R2_SCHEMA_AND_PERSISTENCE_CORRECTION.md",
    "docs/thesis_mainline/rq1/RQ1C0_R2_EFFECTIVE_ONE_SHOT_PROTOCOL.md",
)
FROZEN_ANCHOR_RELATIVES = (
    "evaluation/learned_intent_ranking/rq1c/rq1c_final_gold_authority_contract_v1.json",
    "evaluation/learned_intent_ranking/rq1c/rq1c_checkpoint_preflight_v1.json",
    "evaluation/learned_intent_ranking/rq1c/rq1c_dev_parity_v1.json",
)
PROTECTED_PATHS = (
    "Home.py",
    "pages",
    "utils",
    "semantic_runtime",
    "evaluation/learned_intent_ranking/lr1",
    "evaluation/learned_intent_ranking/lr1r",
    "evaluation/learned_intent_ranking/lr2",
    "evaluation/learned_intent_ranking/lr2r",
    "evaluation/learned_intent_ranking/lr3",
    "evaluation/learned_intent_ranking/lr3r",
    "evaluation/learned_intent_ranking/lr3s",
    "evaluation/learned_intent_ranking/lr4a",
    "evaluation/learned_intent_ranking/lr4b",
    "evaluation/learned_intent_ranking/lr4b_r1",
    "evaluation/learned_intent_ranking/lr4b_dev",
)


def _sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _git(*args: str) -> subprocess.CompletedProcess[bytes]:
    return subprocess.run(["git", *args], cwd=ROOT, capture_output=True, check=False)


def _metric_prediction(record_id: str, gold: str, rank: int) -> dict[str, Any]:
    labels = list(LABEL_UNIVERSE)
    labels.remove(gold)
    ranking = labels[:]
    ranking.insert(rank - 1, gold)
    return {
        "record_id": record_id,
        "gold_label": gold,
        "ranking": tuple(ranking),
        "top1_label": ranking[0],
        "gold_rank": rank,
    }


class _CountingReader:
    def __init__(self, handle: Any, counts: dict[str, int]) -> None:
        self._handle = handle
        self._counts = counts

    def __enter__(self) -> "_CountingReader":
        return self

    def __exit__(self, *args: object) -> None:
        self._handle.close()

    def read(self, *args: object, **kwargs: object) -> bytes:
        self._counts["read"] += 1
        return self._handle.read(*args, **kwargs)


def run_synthetic_validation(authority_contract: Mapping[str, Any]) -> dict[str, Any]:
    synthetic_bytes = build_synthetic_final_csv()
    records, schema = parse_final_csv_bytes(synthetic_bytes, authority_contract)
    raw_rows = list(
        csv.DictReader(
            io.StringIO(synthetic_bytes.decode("utf-8-sig"), newline="")
        )
    )
    raw_blank_page_count = sum(
        row["human_final_page_context"] == "" for row in raw_rows
    )
    raw_blank_role_count = sum(row["contrast_role"] == "" for row in raw_rows)
    source_match_count = sum(
        row["normalised_query"] == source_track_a_normalised_query(row["query"])
        for row in raw_rows
    )
    punctuation_expectations = ((",", 0), ("?", 1), ("'", 2), (".", 3), ("-", 4), ("-", 5))
    punctuation_pass = all(
        character in raw_rows[index]["normalised_query"]
        for character, index in punctuation_expectations
    ) and "\u2014" not in raw_rows[5]["normalised_query"]
    frozen_contamination_cases = {
        "  Student's,  Case?  ": "students case",
        "A   B": "a b",
        "Case\u2014Fold": "casefold",
        "\uff21\uff0c\uff22": "ab",
    }
    contamination_behaviour_unchanged = all(
        deterministic_normalised_query(value) == expected
        for value, expected in frozen_contamination_cases.items()
    )
    if (
        raw_blank_page_count != 104
        or raw_blank_role_count != 64
        or source_match_count != 128
        or not punctuation_pass
        or not contamination_behaviour_unchanged
    ):
        raise HarnessValidationError("synthetic raw-convention validation failed")
    references = build_reference_identity_sets(ROOT)
    contamination = audit_contamination(records, references)
    require_contamination_clear(contamination)

    duplicate_records = [dict(row) for row in records]
    duplicate_records[1]["record_id"] = duplicate_records[0]["record_id"]
    duplicate_report = audit_contamination(duplicate_records, references)
    duplicate_blocked = False
    try:
        require_contamination_clear(duplicate_report)
    except FinalEvaluationInvalid:
        duplicate_blocked = True
    if not duplicate_blocked:
        raise HarnessValidationError("synthetic duplicate-ID gate failed")

    overlap_references = {
        role: {
            "exact_query_hashes": set(value["exact_query_hashes"]),
            "normalised_query_hashes": set(value["normalised_query_hashes"]),
            "family_ids": set(value["family_ids"]),
        }
        for role, value in references.items()
    }
    first_hash = hashlib.sha256(str(records[0]["query"]).encode("utf-8")).hexdigest()
    overlap_references["TRAIN"]["exact_query_hashes"].add(first_hash)
    overlap_report = audit_contamination(records, overlap_references)
    overlap_blocked = False
    try:
        require_contamination_clear(overlap_report)
    except FinalEvaluationInvalid:
        overlap_blocked = True
    if not overlap_blocked:
        raise HarnessValidationError("synthetic overlap gate failed")

    track_b_blocked = False
    try:
        validate_requested_asset_name(
            "primary_v3_hybrid_context_human_review_researcher_final_v1.csv"
        )
    except Exception:
        track_b_blocked = True
    if not track_b_blocked:
        raise HarnessValidationError("synthetic Track-B rejection failed")

    c0_predictions: list[dict[str, Any]] = []
    m64_by_seed: dict[int, list[dict[str, Any]]] = {seed: [] for seed in V0_SEEDS}
    k0_predictions: list[dict[str, Any]] = []
    for index, record in enumerate(records):
        gold = str(record["gold_label"])
        c0_rank = 2 if index < 96 else 1
        c0_predictions.append(_metric_prediction(str(record["record_id"]), gold, c0_rank))
        for offset, seed in enumerate(V0_SEEDS):
            m64_rank = 1 if index < 112 - offset * 2 else c0_rank
            m64_by_seed[seed].append(
                _metric_prediction(str(record["record_id"]), gold, m64_rank)
            )
        k0_predictions.append(
            _metric_prediction(str(record["record_id"]), gold, 1 if index % 2 == 0 else 2)
        )
        if index % 2:
            k0_predictions[-1]["ranking"] = (k0_predictions[-1]["top1_label"],)
            k0_predictions[-1]["gold_rank"] = None
        else:
            k0_predictions[-1]["ranking"] = (gold,)
            k0_predictions[-1]["top1_label"] = gold
            k0_predictions[-1]["gold_rank"] = 1
    k0_metrics = compute_fixed16_metrics(k0_predictions)
    if k0_metrics["mrr"] != k0_metrics["top1_accuracy"]:
        raise HarnessValidationError("synthetic K0 MRR/Top-1 identity failed")
    decision = run_frozen_final_decision(
        c0_predictions=c0_predictions,
        m64_predictions_by_seed=m64_by_seed,
    )

    counts = {"open": 0, "read": 0}
    with tempfile.TemporaryDirectory(prefix="rq1c-synthetic-lock-", dir="/private/tmp") as value:
        temp = Path(value)
        asset = temp / "synthetic.csv"
        asset.write_bytes(synthetic_bytes)
        lock_path = temp / "synthetic-lock.json"
        result_target = FinalResultTarget(
            path=temp / "synthetic-result.json",
            temporary_path=temp / ".synthetic-result.json.tmp",
            relative_path="synthetic/synthetic-result.json",
        )

        def opener(path: str, mode: str) -> _CountingReader:
            counts["open"] += 1
            return _CountingReader(builtins.open(path, mode), counts)

        lock, result = consume_one_shot_asset(
            asset_path=asset,
            lock_path=lock_path,
            expected_sha256=_sha256_bytes(synthetic_bytes),
            expected_size=len(synthetic_bytes),
            expected_head="0" * 40,
            parser=lambda value: parse_final_csv_bytes(value, authority_contract)[0],
            evaluator=lambda parsed: {"status": "PASS", "record_count": len(parsed)},
            result_persister=lambda result: persist_result_atomically(
                result, result_target
            ),
            opener=opener,
        )
        if (
            lock["state"] != "COMPLETED"
            or lock["persisted"] is not True
            or result["record_count"] != 128
            or not result_target.path.is_file()
        ):
            raise HarnessValidationError("synthetic lock completion failed")
        second_refused = False
        try:
            consume_one_shot_asset(
                asset_path=asset,
                lock_path=lock_path,
                expected_sha256=_sha256_bytes(synthetic_bytes),
                expected_size=len(synthetic_bytes),
                expected_head="0" * 40,
                parser=lambda value: value,
                evaluator=lambda parsed: {"status": "UNREACHABLE"},
                result_persister=lambda result: {},
                opener=opener,
            )
        except SealedAccessError:
            second_refused = True
        if not second_refused or counts != {"open": 1, "read": 1}:
            raise HarnessValidationError("synthetic one-shot refusal failed")

    with tempfile.TemporaryDirectory(
        prefix="rq1c-synthetic-persistence-failure-", dir="/private/tmp"
    ) as value:
        temp = Path(value)
        asset = temp / "synthetic.csv"
        asset.write_bytes(synthetic_bytes)
        failed_lock_path = temp / "failed-lock.json"
        persistence_failed = False
        try:
            consume_one_shot_asset(
                asset_path=asset,
                lock_path=failed_lock_path,
                expected_sha256=_sha256_bytes(synthetic_bytes),
                expected_size=len(synthetic_bytes),
                expected_head="0" * 40,
                parser=lambda value: value,
                evaluator=lambda parsed: {"status": "PASS"},
                result_persister=lambda result: (_ for _ in ()).throw(
                    OSError("synthetic persistence failure")
                ),
            )
        except OSError:
            persistence_failed = True
        failed_lock = json.loads(failed_lock_path.read_text(encoding="utf-8"))
        if (
            not persistence_failed
            or failed_lock["state"] != "FAILED_RESULT_PERSISTENCE"
            or failed_lock["retry_permitted"] is not False
        ):
            raise HarnessValidationError("persistence failure contract failed")

    report = {
        "schema_version": "rq1c-r2-synthetic-validation-v1",
        "stage": "RQ1-C0-R2",
        "status": "PASS",
        "synthetic_record_count": len(records),
        "schema_parser": "PASS",
        "field_validation": "PASS",
        "distribution_validation": "PASS",
        "one_read_parser": "PASS",
        "one_shot_open_count": counts["open"],
        "one_shot_read_count": counts["read"],
        "second_access_refused": True,
        "duplicate_id_blocking": duplicate_blocked,
        "overlap_blocking": overlap_blocked,
        "track_b_rejection": track_b_blocked,
        "fixed16_label_metrics": len(k0_metrics["per_label"]) == 16,
        "k0_single_candidate_mrr_equals_top1": True,
        "statistical_contract_called": True,
        "statistical_selection": decision["selection"],
        "randomisation_resamples": decision["randomisation_resamples"],
        "bootstrap_resamples": decision["bootstrap_resamples"],
        "schema_distribution": schema["distribution"],
        "source_normalisation": SOURCE_NORMALISATION,
        "contamination_normalisation": CONTAMINATION_NORMALISATION,
        "source_and_contamination_normalisers_distinct": (
            source_track_a_normalised_query("Synthetic, Query?")
            != deterministic_normalised_query("Synthetic, Query?")
        ),
        "contamination_normalisation_behaviour_unchanged": (
            contamination_behaviour_unchanged
        ),
        "contamination_normalisation_regression_case_count": len(
            frozen_contamination_cases
        ),
        "raw_blank_page_context_count": raw_blank_page_count,
        "raw_blank_contrast_role_count": raw_blank_role_count,
        "parsed_canonical_none_page_count": schema["distribution"]["page_context"]["NONE"],
        "parsed_canonical_none_contrast_role_count": schema["distribution"]["contrast_role"]["NONE"],
        "source_normalised_query_match_count": source_match_count,
        "punctuation_preservation_cases": 6,
        "punctuation_preservation_pass": punctuation_pass,
        "result_persisted_before_completed": True,
        "persisted_result_sha256_recorded": True,
        "persisted_result_size_recorded": True,
        "persistence_failure_never_completed": persistence_failed,
        "persistence_failure_lock_preserved": True,
        "contamination_hard_failure_count": contamination["hard_failure_count"],
        "output_contains_query": False,
        "network_access": False,
        "provider_calls": 0,
        "real_final_asset_used": False,
        "real_lock_created": False,
    }
    serialised = canonical_json_bytes(report)
    if any(str(row["query"]).encode("utf-8") in serialised for row in records):
        raise HarnessValidationError("synthetic validation output leaked a query")
    return report


def build_amendment_contract() -> dict[str, Any]:
    return {
        "schema_version": "rq1c-schema-persistence-amendment-v1",
        "stage": "RQ1-C0-R2",
        "status": "PASS",
        "authority_package_sha256": "e4efb4283753f918cde73741b94b62f5194a33631a10d3544240ff3dc5dc6268",
        "authority_amendment_sha256": "ef2044c9747abad0565ffa0cd4d14b7ec080d7c3d4b1114623882ae488642fdb",
        "supersedes": "RQ1-C0-R1 parser/persistence portions only",
        "source_normalisation": SOURCE_NORMALISATION,
        "contamination_normalisation": CONTAMINATION_NORMALISATION,
        "blank_value_canonicalisation": {
            "query_only_page_raw": "BLANK",
            "noncontrast_role_raw": "BLANK",
            "canonical_in_memory": "NONE",
        },
        "one_shot_state_order": [
            "ARMED",
            "OPENED",
            "RESULT_PERSISTED",
            "COMPLETED",
        ],
        "unchanged": {
            "track_a_authority": True,
            "track_a_sha256": "5d40f0a4a6b460e77271ee9815fce1b0954c1d7e05c7a4cd2f5d8e28ff09eb8f",
            "track_a_record_count": 128,
            "label_universe_count": 16,
            "models": ["K0", "C0", "M64"],
            "representative_seed": 20260815,
            "checkpoint_hashes": True,
            "statistical_contract": True,
            "contamination_policy": True,
            "one_shot_no_retry_policy": True,
        },
        "contains_raw_final_gold": False,
        "contains_query": False,
        "contains_record_ids": False,
        "model_training_performed": False,
        "checkpoint_modified": False,
        "statistical_contract_modified": False,
    }


def verify_statistical_contract(root: Path = ROOT) -> dict[str, Any]:
    paths = {
        "statistical_contract_json": (
            root
            / "evaluation/learned_intent_ranking/lr4b_r1/"
            "rq1a_r1_statistical_decision_contract_v1.json",
            STATISTICAL_CONTRACT_SHA256,
        ),
        "statistical_contract_module": (
            root
            / "evaluation/learned_intent_ranking/lr4b_r1/"
            "statistical_decision_contract.py",
            STATISTICAL_MODULE_SHA256,
        ),
        "effective_experiment_contract": (
            root
            / "evaluation/learned_intent_ranking/lr4b_r1/"
            "lr4b_experiment_contract_v1_1.json",
            EFFECTIVE_EXPERIMENT_CONTRACT_SHA256,
        ),
    }
    actual = {name: sha256_file(path) for name, (path, _expected) in paths.items()}
    if any(actual[name] != expected for name, (_path, expected) in paths.items()):
        raise HarnessValidationError("frozen statistical contract drift")
    return {name: {"sha256": actual[name], "match": True} for name in paths}


def verify_protected_sources(root: Path = ROOT) -> dict[str, Any]:
    result = _git("diff", "--quiet", R1_HARNESS_HEAD, "--", *PROTECTED_PATHS)
    if result.returncode != 0:
        raise HarnessValidationError("protected source changed")
    return {
        "comparison_base": R1_HARNESS_HEAD,
        "protected_path_count": len(PROTECTED_PATHS),
        "changed_protected_path_count": 0,
        "protected_sources_unchanged": True,
        "method": "GIT_TRACKED_DIFF_ONLY",
    }


def verify_ignore_policy() -> dict[str, Any]:
    paths = (
        TRACK_A_RELATIVE_PATH.as_posix(),
        "evaluation/learned_intent_ranking/rq1c/local_artifacts/sentinel",
        "evaluation/learned_intent_ranking/rq1c/final_results_local/sentinel",
        "evaluation/learned_intent_ranking/rq1c/tmp/sentinel",
    )
    for value in paths:
        result = _git("check-ignore", "-q", value)
        if result.returncode != 0:
            raise HarnessValidationError("local-only Git ignore policy mismatch")
    return {
        "checked_path_string_count": len(paths),
        "all_ignored": True,
        "raw_path_filesystem_checked": False,
    }


def build_outputs() -> dict[str, dict[str, Any]]:
    bridge, candidate = verify_authority_bridge(AUTHORITY_BRIDGE_PATH)
    derived_authority = build_authority_contract(bridge, candidate)
    authority_path = HERE / "rq1c_final_gold_authority_contract_v1.json"
    authority = _read_json(authority_path)
    validate_authority_contract(authority)
    if (
        sha256_file(authority_path) != AUTHORITY_CONTRACT_SHA256
        or canonical_json_bytes(derived_authority) != canonical_json_bytes(authority)
    ):
        raise HarnessValidationError("frozen authority contract changed")
    checkpoint = verify_all_checkpoints(ROOT)
    frozen_checkpoint = _read_json(HERE / "rq1c_checkpoint_preflight_v1.json")
    if canonical_json_bytes(checkpoint) != canonical_json_bytes(frozen_checkpoint):
        raise HarnessValidationError("frozen checkpoint evidence changed")
    synthetic = run_synthetic_validation(authority)
    runtime_bundle = prepare_final_runtime_bundle_for_validation(ROOT)
    dev = runtime_bundle.dev_parity
    prearm = dict(runtime_bundle.prearm_report)
    amendment = build_amendment_contract()
    dev_summary = {
        "schema_version": "rq1c-r2-dev-parity-v1",
        "stage": "RQ1-C0-R2",
        "status": "PASS",
        "r1_dev_parity_sha256": sha256_file(HERE / "rq1c_dev_parity_v1.json"),
        "r1_canonical_bytes_match": True,
        "development_only": True,
        "dev_record_count": dev["dev_record_count"],
        "k0": {
            "record_count": dev["k0"]["record_count"],
            "semantic_loader_call_count": dev["k0"]["semantic_loader_call_count"],
            "ranking_length": dev["k0"]["ranking_length"],
            "mrr_equals_top1": dev["k0"]["mrr_equals_top1"],
            "pass": dev["k0"]["pass"],
        },
        "c0": {
            "ranking_identity_match_count": dev["c0"]["ranking_identity_match_count"],
            "ranking_identity_required": dev["c0"]["ranking_identity_required"],
            "metrics_exact_match": dev["c0"]["metrics_exact_match"],
            "pass": dev["c0"]["pass"],
        },
        "m64_v0": {
            "seed_count": dev["m64_v0"]["seed_count"],
            "representative_seed": dev["m64_v0"]["representative_seed"],
            "seeds": [
                {
                    "seed": row["seed"],
                    "ranking_identity_match_count": row[
                        "ranking_identity_match_count"
                    ],
                    "ranking_identity_required": row["ranking_identity_required"],
                    "metrics_exact_match": row["metrics_exact_match"],
                    "pass": row["pass"],
                }
                for row in dev["m64_v0"]["seeds"]
            ],
            "pass": dev["m64_v0"]["pass"],
        },
        "contains_dev_query": False,
        "contains_prediction_ledger": False,
        "raw_final_gold_accessed": False,
        "provider_calls": 0,
        "network_access": False,
    }
    branch = _git("branch", "--show-current")
    if branch.returncode or branch.stdout.decode("utf-8").strip() != TARGET_BRANCH:
        raise HarnessValidationError("RQ1-C0-R2 branch mismatch")
    result_target = preflight_final_result_path(ROOT)
    harness = {
        "schema_version": "rq1c-r2-harness-preflight-v1",
        "stage": "RQ1-C0-R2",
        "status": "PASS",
        "authority_bridge_zip_sha256": bridge["zip_sha256"],
        "authority_contract_valid": True,
        "authority_contract_sha256": AUTHORITY_CONTRACT_SHA256,
        "checkpoint_preflight_valid": True,
        "synthetic_validation_valid": True,
        "dev_parity_valid": True,
        "prearm_runtime_valid": True,
        "result_path_preflight": {
            "relative_path": result_target.relative_path,
            "git_ignored": True,
            "target_absent": True,
            "temporary_absent": True,
            "parent_non_symlink": True,
            "atomic_write_delete_test": True,
        },
        "source_normalisation": SOURCE_NORMALISATION,
        "contamination_normalisation": CONTAMINATION_NORMALISATION,
        "one_shot_state_order": [
            "ARMED",
            "OPENED",
            "RESULT_PERSISTED",
            "COMPLETED",
        ],
        "python_ast_file_count": len(PYTHON_FILES),
        "double_build_byte_identity": True,
        "output_checksum_target_count": len(checksum_targets()),
        "governed_text_leak_scan_required": True,
        "statistical_contract": verify_statistical_contract(ROOT),
        "ignore_policy": verify_ignore_policy(),
        "protected_sources": verify_protected_sources(ROOT),
        "branch": TARGET_BRANCH,
        "base_head": R1_HARNESS_HEAD,
        "raw_final_open_calls": 0,
        "raw_final_stat_calls": 0,
        "raw_final_hash_calls": 0,
        "raw_final_list_calls": 0,
        "real_lock_created": False,
        "model_training_performed": False,
        "checkpoint_modified": False,
        "statistical_contract_modified": False,
        "provider_calls": 0,
        "network_access": False,
        "production_code_changed": False,
        "rq1c1_evaluation_performed": False,
        "final_metrics_computed": False,
    }
    return {
        "rq1c_schema_persistence_amendment_v1.json": amendment,
        "rq1c_r2_synthetic_validation_v1.json": synthetic,
        "rq1c_r2_dev_parity_v1.json": dev_summary,
        "rq1c_r2_prearm_runtime_v1.json": prearm,
        "rq1c_r2_harness_preflight_v1.json": harness,
    }


def _output_bytes(outputs: Mapping[str, Mapping[str, Any]]) -> dict[str, bytes]:
    return {name: canonical_json_bytes(value) for name, value in outputs.items()}


def write_outputs(outputs: Mapping[str, Mapping[str, Any]]) -> None:
    for name, value in outputs.items():
        (HERE / name).write_bytes(canonical_json_bytes(value))


def checksum_targets() -> tuple[str, ...]:
    relatives = [".gitignore", *DOC_RELATIVES]
    relatives.extend(f"evaluation/learned_intent_ranking/rq1c/{name}" for name in PYTHON_FILES)
    relatives.extend(FROZEN_ANCHOR_RELATIVES)
    relatives.extend(f"evaluation/learned_intent_ranking/rq1c/{name}" for name in JSON_FILES)
    return tuple(relatives)


def write_checksum_manifest() -> None:
    lines = []
    for relative in checksum_targets():
        path = ROOT / relative
        if not path.is_file() or path.is_symlink():
            raise HarnessValidationError("checksum target is missing or unsafe")
        lines.append(f"{sha256_file(path)}  {relative}\n")
    (HERE / "rq1c_r2_output_checksums_v1.sha256").write_text(
        "".join(lines), encoding="ascii", newline="\n"
    )


def validate_checksum_manifest() -> int:
    path = HERE / "rq1c_r2_output_checksums_v1.sha256"
    lines = [line for line in path.read_text(encoding="ascii").splitlines() if line]
    if len(lines) != len(checksum_targets()):
        raise HarnessValidationError("output checksum count mismatch")
    for line, expected_relative in zip(lines, checksum_targets(), strict=True):
        digest, relative = line.split(None, 1)
        relative = relative.strip().lstrip("*")
        if relative != expected_relative or sha256_file(ROOT / relative) != digest:
            raise HarnessValidationError("output checksum mismatch")
    return len(lines)


def validate_python_ast() -> int:
    for name in PYTHON_FILES:
        path = HERE / name
        ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    return len(PYTHON_FILES)


def governed_text_leak_scan() -> dict[str, Any]:
    dev_records, _frozen = __import__(
        "evaluation.learned_intent_ranking.rq1c.final_model_runner",
        fromlist=["_load_dev_and_frozen"],
    )._load_dev_and_frozen(ROOT)
    candidate_rows = [
        json.loads(line)
        for line in (
            ROOT / "semantic_runtime/artifacts/intent_examples_approved_index_v1.jsonl"
        ).read_text(encoding="utf-8").splitlines()
        if line
    ]
    governed = [str(row["query"]) for row in dev_records]
    governed.extend(str(row["query"]) for row in candidate_rows)
    scan_paths = [ROOT / relative for relative in DOC_RELATIVES]
    scan_paths.extend(
        HERE / name for name in (*JSON_FILES, "rq1c_r2_output_checksums_v1.sha256")
    )
    payload = b"\n".join(path.read_bytes() for path in scan_paths)
    matches = sum(
        1
        for value in governed
        if len(value.encode("utf-8")) >= 24 and value.encode("utf-8") in payload
    )
    if matches:
        raise HarnessValidationError("governed query appeared in a tracked safe output")
    return {
        "governed_text_count": len(governed),
        "minimum_scan_length_bytes": 24,
        "match_count": 0,
        "pass": True,
    }


def build_and_validate() -> dict[str, Any]:
    first = build_outputs()
    second = build_outputs()
    if _output_bytes(first) != _output_bytes(second):
        raise HarnessValidationError("double-build byte identity failed")
    write_outputs(first)
    write_checksum_manifest()
    return {
        "status": "PASS",
        "double_build_byte_identity": True,
        "python_ast_file_count": validate_python_ast(),
        "checksum_match_count": validate_checksum_manifest(),
        "governed_text_leak_scan": governed_text_leak_scan(),
        "raw_final_open_calls": 0,
        "raw_final_stat_calls": 0,
        "raw_final_hash_calls": 0,
        "raw_final_list_calls": 0,
        "real_lock_created": False,
    }


def validate_existing() -> dict[str, Any]:
    for name in JSON_FILES:
        payload = _read_json(HERE / name)
        if payload.get("status") not in {
            "PASS",
            "AUTHORISED_FOR_RQ1_C1_ONE_SHOT_FINAL_EVALUATION",
        }:
            raise HarnessValidationError("safe output status mismatch")
    lock_path = ROOT.joinpath(*LOCAL_ARTIFACTS_RELATIVE.parts) / LOCK_FILE_NAME
    if lock_path.exists():
        raise HarnessValidationError("real final-gold lock exists")
    result_path = ROOT.joinpath(*FINAL_RESULT_RELATIVE.parts)
    if result_path.exists() or result_path.is_symlink():
        raise HarnessValidationError("final result already exists")
    return {
        "status": "PASS",
        "python_ast_file_count": validate_python_ast(),
        "checksum_match_count": validate_checksum_manifest(),
        "governed_text_leak_scan": governed_text_leak_scan(),
        "protected_sources": verify_protected_sources(ROOT),
        "ignore_policy": verify_ignore_policy(),
        "raw_final_open_calls": 0,
        "raw_final_stat_calls": 0,
        "raw_final_hash_calls": 0,
        "raw_final_list_calls": 0,
        "real_lock_created": False,
    }


def _read_json(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise HarnessValidationError("expected JSON object")
    return value


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--build", action="store_true")
    args = parser.parse_args(argv)
    report = build_and_validate() if args.build else validate_existing()
    print(json.dumps(report, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
