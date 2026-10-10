#!/usr/bin/env python3
"""Build blinded, deterministic R3D0 repair artifacts without external calls."""

from __future__ import annotations

import argparse
from collections import Counter, defaultdict
import hashlib
import importlib.util
import json
from pathlib import Path
import subprocess
from typing import Any, Iterable, Mapping
import zipfile


HERE = Path(__file__).resolve().parent
REPO = HERE.parents[2]
RQ3 = REPO / "evaluation" / "rq3_real_c4"
G2D0 = RQ3 / "g2d0_response_format_repair"
I1 = RQ3 / "i1_route_integration"
RESTRICTED = I1 / "restricted_internal"
ORIGINAL_C_PACKAGE = Path(
    "/Users/liuming/Downloads/C4_REAL_GENERATION_SHARD_C_EXECUTION_PACKAGE_R3_2026-09-01.zip"
)
ORIGINAL_C_PACKAGE_SHA256 = "16215b04bb875ec8b9b9627df7fb018eff14edf46f5a294049f0dd8442952699"
ORIGINAL_C_MANIFEST_SHA256 = "2bc12fbdf114cda1f52f3438820e2ec706bf60e1c8f0965c4ce610d9853f7ea1"

SHARDS = {
    "A": RQ3 / "r3a_response_regeneration_shard_a",
    "B": RQ3 / "r3b_response_regeneration_shard_b",
    "C": RQ3 / "r3c_response_regeneration_shard_c",
}
EXPECTED_ATTEMPTS = {"A": 51, "B": 50, "C": 5}
EXPECTED_CANONICAL = {"A": 50, "B": 50, "C": 4}
EXPECTED_EXECUTION_IDENTITY = {
    "A": {
        "logical_requests": 50,
        "physical_attempts": 51,
        "retries": 1,
        "reported_valid_terminals": 50,
        "terminal_journal_sha256": "bddc59c161540abafc5b287bd1e8cff00c2512417ee2390923ad6e395889ec0a",
        "answer_set_sha256": "6b78607363c4d0a0908507472b83a047a28773c3a948046bf9776ed71c1d1851",
    },
    "B": {
        "logical_requests": 50,
        "physical_attempts": 50,
        "retries": 0,
        "reported_valid_terminals": 50,
        "terminal_journal_sha256": "0a3c731fa00f596b9c80c3f463faf8f0563ca741dbe58942dbbc1bb0b36e7585",
        "answer_set_sha256": "b035aa4f18025a4d6592489b9ed94394a4872cbca31788ee31dba5574e88ac8c",
    },
    "C": {
        "frozen_requests": 47,
        "logical_requests_reached": 4,
        "physical_attempts": 5,
        "retries": 1,
        "reported_valid_terminals": 3,
        "incomplete_logical_order": 4,
        "unattempted_logical_requests": 43,
        "terminal_journal_sha256": "9ab653b18743e95c7c777327c8742e3fe3bebbf64c72cc61a547141081be66bb",
        "answer_set_sha256": "0affb1b3f7f84496eccbd1e04c417dd8e3d39242c92b39c3396c15d6e289c456",
    },
}
COMMIT_MAPPING = [
    {
        "sequence": 1,
        "shard": "A",
        "original_commit": "740d67ad16c2c830b1b07940f5e7438daa06638d",
        "cherry_picked_commit": "cd2d9f2b285bd410420fbec4ac301c2f5bf84263",
    },
    {
        "sequence": 2,
        "shard": "B",
        "original_commit": "d421468fe1076df9a92d0c7a70e136bada95ac63",
        "cherry_picked_commit": "2b6d3f0cb52171c8d3db0680795089469435ce17",
    },
    {
        "sequence": 3,
        "shard": "C",
        "original_commit": "5e667e8045e77bf1588e1f6dabb6104a0cd79aa0",
        "cherry_picked_commit": "6a9a362d280acd53aa0398b82a754360fd28d082",
    },
]
RESTRICTED_PRESERVATION_FILES = (
    "c4_real_i1_blinding_hmac_key.bin",
    "c4_real_condition_generation_payload_registry_frozen_v3.jsonl",
    "c4_real_condition_to_unique_request_mapping_frozen_v3.csv",
    "c4_real_response_to_condition_mapping_frozen_v3.csv",
    "c4_real_response_to_mode_mapping_frozen_v3.csv",
    "c4_real_response_to_scenario_mapping_frozen_v3.csv",
)


def sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def canonical_bytes(value: Any) -> bytes:
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    ).encode("utf-8")


def write_json(path: Path, value: Any) -> None:
    path.write_text(
        json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def write_jsonl(path: Path, rows: Iterable[Mapping[str, Any]]) -> None:
    path.write_text(
        "".join(
            json.dumps(dict(row), ensure_ascii=False, sort_keys=True, separators=(",", ":"))
            + "\n"
            for row in rows
        ),
        encoding="utf-8",
    )


def load_module(name: str, path: Path) -> Any:
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"cannot import {path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def load_jsonl(path: Path) -> list[dict[str, Any]]:
    rows = []
    for line_number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        if not line.strip():
            continue
        value = json.loads(line)
        if not isinstance(value, dict):
            raise ValueError(f"{path}:{line_number} is not an object")
        rows.append(value)
    return rows


def git(*arguments: str) -> str:
    return subprocess.check_output(
        ["git", *arguments], cwd=REPO, text=True, encoding="utf-8"
    ).strip()


def _file_identity(path: Path) -> dict[str, Any]:
    return {
        "path": path.relative_to(REPO).as_posix(),
        "bytes": path.stat().st_size,
        "sha256": sha256_file(path),
    }


def collect_original_r3_files() -> list[dict[str, Any]]:
    paths: list[Path] = []
    for directory in SHARDS.values():
        paths.extend(path for path in directory.rglob("*") if path.is_file())
    return [_file_identity(path) for path in sorted(paths)]


def collect_restricted_identities() -> list[dict[str, Any]]:
    paths = [RESTRICTED / name for name in RESTRICTED_PRESERVATION_FILES]
    if not all(path.is_file() for path in paths):
        raise FileNotFoundError("required ignored HMAC/V3 mapping material is absent")
    return [_file_identity(path) for path in paths]


def _verify_execution_identity() -> None:
    for shard, directory in SHARDS.items():
        output = directory / "execution_output_v1"
        attempts = load_jsonl(output / "GENERATION_ATTEMPT_JOURNAL.jsonl")
        terminals = load_jsonl(output / "GENERATION_TERMINAL_JOURNAL.jsonl")
        if len(attempts) != EXPECTED_ATTEMPTS[shard]:
            raise ValueError(f"Shard {shard} attempt count changed")
        if sha256_file(output / "GENERATION_TERMINAL_JOURNAL.jsonl") != EXPECTED_EXECUTION_IDENTITY[
            shard
        ]["terminal_journal_sha256"]:
            raise ValueError(f"Shard {shard} terminal journal identity changed")
        audit = json.loads((directory / "generation_execution_audit_v1.json").read_text())
        if shard == "C":
            observed_answer_set = audit["hashes"]["answer_set_sha256"]
        else:
            observed_answer_set = audit["answer_set_sha256"]
        if observed_answer_set != EXPECTED_EXECUTION_IDENTITY[shard]["answer_set_sha256"]:
            raise ValueError(f"Shard {shard} historical answer-set identity changed")
        if shard in ("A", "B") and len(terminals) != 50:
            raise ValueError(f"Shard {shard} terminal count changed")
        if shard == "C" and len(terminals) != 4:
            raise ValueError("Shard C historical terminal count changed")


def build_preservation_before() -> dict[str, Any]:
    _verify_execution_identity()
    if sha256_file(ORIGINAL_C_PACKAGE) != ORIGINAL_C_PACKAGE_SHA256:
        raise ValueError("original Shard-C R3 package identity changed")
    with zipfile.ZipFile(ORIGINAL_C_PACKAGE) as archive:
        manifest_hash = sha256_bytes(archive.read("BLINDED_REQUESTS.jsonl"))
    if manifest_hash != ORIGINAL_C_MANIFEST_SHA256:
        raise ValueError("original Shard-C blinded manifest identity changed")
    manifest = {
        "schema_version": "c4-real-r3d0-source-preservation-before-v1",
        "status": "PASS_BASELINE_FROZEN",
        "phase": "AFTER_AUTHORIZED_R3_CHERRY_PICKS_BEFORE_R3D0_DERIVED_ARTIFACT_BUILD",
        "starting_head": "e647bb42d270b4f24ad543f9f6010e6b43ee4ed4",
        "integrated_head": git("rev-parse", "HEAD"),
        "integrated_commit_mapping": COMMIT_MAPPING,
        "original_r3_file_count": sum(1 for directory in SHARDS.values() for path in directory.rglob("*") if path.is_file()),
        "original_r3_files": collect_original_r3_files(),
        "historical_execution_identity": EXPECTED_EXECUTION_IDENTITY,
        "original_shard_c_package": {
            "path": str(ORIGINAL_C_PACKAGE),
            "sha256": ORIGINAL_C_PACKAGE_SHA256,
            "blinded_manifest_sha256": ORIGINAL_C_MANIFEST_SHA256,
        },
        "restricted_identity_only_check": {
            "content_opened_or_unblinded": False,
            "files": collect_restricted_identities(),
        },
    }
    write_json(HERE / "c4_real_r3_source_preservation_manifest_before_v1.json", manifest)
    write_json(
        HERE / "c4_real_r3_commit_integration_mapping_v1.json",
        {
            "schema_version": "c4-real-r3-commit-integration-mapping-v1",
            "status": "PASS_CLEAN_INDEPENDENT_DIRECTORY_CHERRY_PICKS",
            "starting_head": "e647bb42d270b4f24ad543f9f6010e6b43ee4ed4",
            "mapping": COMMIT_MAPPING,
            "conflicts": 0,
            "existing_artifacts_modified_during_cherry_pick": 0,
        },
    )
    return manifest


def _extract_outer_answer(row: Mapping[str, Any]) -> tuple[object, bool]:
    raw = row.get("raw_response_content")
    if not isinstance(raw, str):
        return None, False
    try:
        parsed = json.loads(raw)
    except json.JSONDecodeError:
        return None, False
    valid = isinstance(parsed, dict) and set(parsed) == {"answer_text"} and isinstance(
        parsed.get("answer_text"), str
    )
    return parsed.get("answer_text") if valid else None, valid


def build_reclassification_and_selection() -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    v1 = load_module(
        "r3d0_validator_v1",
        G2D0 / "c4_real_student_facing_response_validator_v1.py",
    )
    v2 = load_module(
        "r3d0_validator_v2",
        HERE / "c4_real_student_facing_response_validator_v2.py",
    )
    rows_by_request: dict[tuple[str, str], list[dict[str, Any]]] = defaultdict(list)
    reclassified: list[dict[str, Any]] = []
    v1_counts: Counter[str] = Counter()
    v2_counts: Counter[str] = Counter()
    changed_by_shard: Counter[str] = Counter()
    counts_by_shard: Counter[str] = Counter()

    for shard, directory in SHARDS.items():
        attempts_path = directory / "execution_output_v1" / "GENERATION_ATTEMPT_JOURNAL.jsonl"
        attempts = load_jsonl(attempts_path)
        if len(attempts) != EXPECTED_ATTEMPTS[shard]:
            raise ValueError(f"Shard {shard} attempt population mismatch")
        for row in attempts:
            answer_text, outer_valid = _extract_outer_answer(row)
            observed_outer_valid = row.get("outer_schema_validation_status") == "VALID"
            if outer_valid != observed_outer_valid:
                raise ValueError("outer schema reconstruction differs from frozen attempt record")
            v1_status = v1.validate_answer_text(answer_text)
            v2_status = v2.validate_answer_text(answer_text)
            if v1_status != row.get("student_facing_validation_status"):
                raise ValueError("reproduced V1 classification differs from frozen attempt record")
            changed = v1_status != v2_status
            output = {
                "schema_version": "c4-real-r3-existing-attempt-format-reclassification-v2",
                "shard": shard,
                "logical_order": row["logical_order"],
                "logical_generation_request_id": row["logical_generation_request_id"],
                "response_blind_id": row["response_blind_id"],
                "attempt_number": row["attempt_number"],
                "outer_schema_status": row["outer_schema_validation_status"],
                "raw_response_source_sha256": sha256_bytes(row["raw_response_content"].encode("utf-8")),
                "answer_text_sha256": sha256_bytes(answer_text.encode("utf-8"))
                if isinstance(answer_text, str)
                else None,
                "v1_classification": v1_status,
                "v2_classification": v2_status,
                "classification_changed": changed,
                "answer_quality_assessment_performed": False,
                "condition_mode_route_or_expected_outcome_accessed": False,
            }
            reclassified.append(output)
            enriched = dict(row)
            enriched["_answer_text"] = answer_text
            enriched["_v2_status"] = v2_status
            enriched["_raw_response_source_sha256"] = output["raw_response_source_sha256"]
            rows_by_request[(shard, row["logical_generation_request_id"])].append(enriched)
            v1_counts[v1_status] += 1
            v2_counts[v2_status] += 1
            counts_by_shard[shard] += 1
            if changed:
                changed_by_shard[shard] += 1

    if len(reclassified) != 106 or dict(counts_by_shard) != EXPECTED_ATTEMPTS:
        raise ValueError("total existing attempt population mismatch")
    changed = [row for row in reclassified if row["classification_changed"]]
    changed_keys = {
        (row["shard"], row["logical_order"], row["attempt_number"]) for row in changed
    }
    expected_changed = {("A", 40, 1), ("C", 4, 1), ("C", 4, 2)}
    if changed_keys != expected_changed:
        raise ValueError(f"unexpected V1/V2 classification-change set: {sorted(changed_keys)}")
    write_jsonl(HERE / "r3_existing_attempt_format_reclassification_v2.jsonl", reclassified)
    summary = {
        "schema_version": "c4-real-r3-existing-attempt-format-reclassification-summary-v2",
        "status": "PASS_BLIND_MECHANICAL_RECLASSIFICATION",
        "operation_order": "COMPLETED_BEFORE_ANY_CONDITION_OR_MODE_MAPPING_ACCESS",
        "attempt_count": len(reclassified),
        "attempt_counts_by_shard": dict(sorted(counts_by_shard.items())),
        "v1_classification_counts": dict(sorted(v1_counts.items())),
        "v2_classification_counts": dict(sorted(v2_counts.items())),
        "classification_changed_count": len(changed),
        "classification_changed_counts_by_shard": dict(sorted(changed_by_shard.items())),
        "changed_attempts": [
            {
                "shard": row["shard"],
                "logical_order": row["logical_order"],
                "attempt_number": row["attempt_number"],
                "v1_classification": row["v1_classification"],
                "v2_classification": row["v2_classification"],
            }
            for row in changed
        ],
        "unexpected_classification_changes": 0,
        "answer_quality_assessments": 0,
        "condition_mode_route_gold_or_expected_outcome_accesses": 0,
    }
    write_json(HERE / "r3_existing_attempt_format_reclassification_summary_v2.json", summary)

    rule = {
        "schema_version": "c4-real-r3-canonical-attempt-selection-rule-v1",
        "rule_id": "C4_REAL_R3_CANONICAL_ATTEMPT_SELECTION_RULE_V1",
        "status": "FROZEN_UNIFORM_BLIND_MECHANICAL_RULE",
        "applies_to_shards": ["A", "B", "C"],
        "steps": [
            "Sort attempts by attempt_number ascending.",
            "Require outer JSON and schema validity.",
            "Apply student-facing Validator V2.",
            "Select the earliest attempt classified VALID_STUDENT_FACING_RESPONSE.",
            "Never select based on factual quality, length, style, score, mode, condition, route, or expected result.",
            "If no existing attempt passes, leave the request incomplete.",
        ],
        "answer_quality_assessment_performed": False,
    }
    write_json(HERE / "C4_REAL_R3_CANONICAL_ATTEMPT_SELECTION_RULE_V1.json", rule)

    terminal_by_request: dict[tuple[str, str], dict[str, Any]] = {}
    for shard, directory in SHARDS.items():
        for terminal in load_jsonl(
            directory / "execution_output_v1" / "GENERATION_TERMINAL_JOURNAL.jsonl"
        ):
            terminal_by_request[(shard, terminal["logical_generation_request_id"])] = terminal

    selected: list[dict[str, Any]] = []
    dispositions: list[dict[str, Any]] = []
    selected_counts: Counter[str] = Counter()
    for key in sorted(rows_by_request, key=lambda item: (item[0], rows_by_request[item][0]["logical_order"])):
        attempts = sorted(rows_by_request[key], key=lambda row: row["attempt_number"])
        eligible = [
            row
            for row in attempts
            if row["outer_schema_validation_status"] == "VALID"
            and row["_v2_status"] == v2.VALID_STUDENT_FACING_RESPONSE
        ]
        if not eligible:
            continue
        chosen = eligible[0]
        terminal = terminal_by_request[key]
        if terminal.get("terminal_status") == "VALID_STUDENT_FACING_RESPONSE":
            terminal_raw = terminal.get("raw_response_content")
            if terminal_raw == chosen["raw_response_content"]:
                relationship = "MATCHES_ORIGINAL_VALID_TERMINAL_SELECTION"
            else:
                relationship = (
                    "SUPERSEDES_LATER_ORIGINAL_VALID_TERMINAL_AFTER_V1_FALSE_POSITIVE"
                )
        else:
            relationship = "RECOVERS_ORIGINAL_INCOMPLETE_REQUEST_AFTER_V1_FALSE_POSITIVE"
        answer_text = chosen["_answer_text"]
        if not isinstance(answer_text, str):
            raise ValueError("selected response lacks answer_text")
        selected.append(
            {
                "shard": key[0],
                "logical_order": chosen["logical_order"],
                "logical_generation_request_id": chosen["logical_generation_request_id"],
                "response_blind_id": chosen["response_blind_id"],
                "selected_attempt_number": chosen["attempt_number"],
                "raw_response_source_sha256": chosen["_raw_response_source_sha256"],
                "answer_text": answer_text,
                "answer_text_sha256": sha256_bytes(answer_text.encode("utf-8")),
                "v2_format_status": chosen["_v2_status"],
                "original_terminal_selection_relationship": relationship,
            }
        )
        selected_counts[key[0]] += 1
        for attempt in attempts:
            if attempt["attempt_number"] == chosen["attempt_number"]:
                disposition = "SELECTED_EARLIEST_VALID_V2"
            elif attempt["attempt_number"] > chosen["attempt_number"]:
                disposition = "NOT_SELECTED_REDUNDANT_RETRY_AFTER_V1_FALSE_POSITIVE"
            else:
                disposition = "NOT_SELECTED_NO_EARLIER_V2_VALID_RESPONSE"
            dispositions.append(
                {
                    "shard": key[0],
                    "logical_order": attempt["logical_order"],
                    "logical_generation_request_id": attempt["logical_generation_request_id"],
                    "response_blind_id": attempt["response_blind_id"],
                    "attempt_number": attempt["attempt_number"],
                    "v2_format_status": attempt["_v2_status"],
                    "selection_disposition": disposition,
                }
            )
    if dict(selected_counts) != EXPECTED_CANONICAL or len(selected) != 104:
        raise ValueError(f"canonical selection counts mismatch: {selected_counts}")
    special = {(row["shard"], row["logical_order"]): row for row in selected}
    if special[("A", 40)]["selected_attempt_number"] != 1:
        raise ValueError("Shard A logical order 40 did not select attempt 1")
    if special[("C", 4)]["selected_attempt_number"] != 1:
        raise ValueError("Shard C logical order 4 did not select attempt 1")
    redundant = [
        row
        for row in dispositions
        if row["selection_disposition"]
        == "NOT_SELECTED_REDUNDANT_RETRY_AFTER_V1_FALSE_POSITIVE"
    ]
    if {(row["shard"], row["logical_order"], row["attempt_number"]) for row in redundant} != {
        ("A", 40, 2),
        ("C", 4, 2),
    }:
        raise ValueError("redundant retry disposition set mismatch")
    write_jsonl(HERE / "c4_real_r3_existing_canonical_response_selection_v1.jsonl", selected)
    write_json(
        HERE / "c4_real_r3_canonical_attempt_selection_audit_v1.json",
        {
            "schema_version": "c4-real-r3-canonical-attempt-selection-audit-v1",
            "status": "PASS_UNIFORM_EARLIEST_VALID_V2",
            "attempt_count": len(dispositions),
            "selected_response_count": len(selected),
            "selected_counts_by_shard": dict(sorted(selected_counts.items())),
            "redundant_retry_count": len(redundant),
            "redundant_retries": redundant,
            "attempt_dispositions": dispositions,
            "answer_quality_assessments": 0,
            "condition_mode_route_gold_or_expected_outcome_accesses": 0,
        },
    )
    return reclassified, selected


def build_continuation_and_boundary(selected: list[dict[str, Any]]) -> list[dict[str, Any]]:
    if sha256_file(ORIGINAL_C_PACKAGE) != ORIGINAL_C_PACKAGE_SHA256:
        raise ValueError("original Shard-C package hash mismatch")
    with zipfile.ZipFile(ORIGINAL_C_PACKAGE) as archive:
        source_bytes = archive.read("BLINDED_REQUESTS.jsonl")
        prompt_bytes = archive.read("GENERATION_PROMPT.txt")
        schema_bytes = archive.read("GENERATION_SCHEMA.json")
        configuration_bytes = archive.read("GENERATION_CONFIGURATION.json")
    if sha256_bytes(source_bytes) != ORIGINAL_C_MANIFEST_SHA256:
        raise ValueError("original Shard-C manifest hash mismatch")
    source_lines = source_bytes.splitlines(keepends=True)
    if len(source_lines) != 47 or any(not line.strip() for line in source_lines):
        raise ValueError("original Shard-C manifest does not have exactly 47 nonblank rows")
    source_rows = [json.loads(line) for line in source_lines]
    remaining_lines = source_lines[4:]
    remaining_rows = source_rows[4:]
    remaining_bytes = b"".join(remaining_lines)
    if len(remaining_rows) != 43:
        raise ValueError("remaining Shard-C population is not 43")
    (HERE / "c4_real_r3c_remaining_request_manifest_v1.jsonl").write_bytes(remaining_bytes)
    row_audit = []
    for offset, (source_line, row) in enumerate(zip(remaining_lines, remaining_rows), 5):
        payload_hash = sha256_bytes(canonical_bytes(row["provider_payload"]))
        if payload_hash != row["provider_payload_sha256"]:
            raise ValueError(f"source payload hash mismatch at original order {offset}")
        row_audit.append(
            {
                "original_shard_c_logical_order": offset,
                "continuation_subset_order": offset - 4,
                "logical_generation_request_id": row["logical_generation_request_id"],
                "response_blind_id": row["response_blind_id"],
                "provider_payload_sha256": row["provider_payload_sha256"],
                "source_full_row_sha256": sha256_bytes(source_line.rstrip(b"\r\n")),
                "source_full_row_byte_identity_preserved": True,
                "provider_payload_canonical_byte_identity_preserved": True,
            }
        )
    source_audit = {
        "schema_version": "c4-real-r3c-continuation-source-audit-v1",
        "status": "PASS_EXACT_UNATTEMPTED_SOURCE_SUBSET",
        "only_source_package_used": str(ORIGINAL_C_PACKAGE),
        "source_package_sha256": ORIGINAL_C_PACKAGE_SHA256,
        "source_blinded_manifest_sha256": ORIGINAL_C_MANIFEST_SHA256,
        "source_request_count": 47,
        "excluded_original_logical_orders": [1, 2, 3, 4],
        "retained_original_logical_order_range": [5, 47],
        "retained_request_count": 43,
        "continuation_manifest_sha256": sha256_bytes(remaining_bytes),
        "full_source_row_bytes_preserved": True,
        "opaque_ids_regenerated": False,
        "provider_payloads_modified": False,
        "request_relative_order_preserved": True,
        "source_generation_prompt_sha256": sha256_bytes(prompt_bytes),
        "source_generation_schema_sha256": sha256_bytes(schema_bytes),
        "source_generation_configuration_sha256": sha256_bytes(configuration_bytes),
        "row_identity_audit": row_audit,
    }
    write_json(HERE / "c4_real_r3c_continuation_source_audit_v1.json", source_audit)

    universe_rows = load_jsonl(I1 / "c4_real_unique_generation_request_manifest_frozen_v3.jsonl")
    universe_ids = {row["logical_generation_request_id"] for row in universe_rows}
    universe_response_ids = {row["response_blind_id"] for row in universe_rows}
    selected_ids = {row["logical_generation_request_id"] for row in selected}
    selected_response_ids = {row["response_blind_id"] for row in selected}
    remaining_ids = {row["logical_generation_request_id"] for row in remaining_rows}
    remaining_response_ids = {row["response_blind_id"] for row in remaining_rows}
    checks = {
        "frozen_universe_count_147": len(universe_rows) == 147 == len(universe_ids),
        "selected_count_104": len(selected) == 104 == len(selected_ids),
        "remaining_count_43": len(remaining_rows) == 43 == len(remaining_ids),
        "selected_remaining_logical_ids_disjoint": selected_ids.isdisjoint(remaining_ids),
        "selected_remaining_response_ids_disjoint": selected_response_ids.isdisjoint(
            remaining_response_ids
        ),
        "logical_id_union_equals_frozen_universe": selected_ids | remaining_ids == universe_ids,
        "response_id_union_equals_frozen_universe": selected_response_ids | remaining_response_ids
        == universe_response_ids,
        "no_missing_or_extra_opaque_id": (selected_ids | remaining_ids) == universe_ids,
    }
    if not all(checks.values()):
        raise ValueError(f"primary response completion boundary mismatch: {checks}")
    write_json(
        HERE / "c4_real_r3_primary_response_completion_boundary_v1.json",
        {
            "schema_version": "c4-real-r3-primary-response-completion-boundary-v1",
            "status": "PASS_EXACT_147_REQUEST_PARTITION",
            "frozen_request_universe_count": len(universe_rows),
            "existing_canonical_selected_response_count": len(selected),
            "remaining_unattempted_request_count": len(remaining_rows),
            "remaining_shard_c_original_logical_order_range": [5, 47],
            "checks": checks,
            "responses_unblinded": False,
            "judge_requests_created": 0,
            "restricted_mapping_content_accessed": False,
        },
    )
    return remaining_rows


def build_preservation_after() -> dict[str, Any]:
    before_path = HERE / "c4_real_r3_source_preservation_manifest_before_v1.json"
    before = json.loads(before_path.read_text(encoding="utf-8"))
    _verify_execution_identity()
    original_files = collect_original_r3_files()
    restricted_files = collect_restricted_identities()
    with zipfile.ZipFile(ORIGINAL_C_PACKAGE) as archive:
        source_manifest_hash = sha256_bytes(archive.read("BLINDED_REQUESTS.jsonl"))
    checks = {
        "original_r3_file_count_unchanged": len(original_files)
        == before["original_r3_file_count"],
        "original_r3_file_hashes_unchanged": original_files == before["original_r3_files"],
        "original_shard_c_package_unchanged": sha256_file(ORIGINAL_C_PACKAGE)
        == before["original_shard_c_package"]["sha256"],
        "original_shard_c_manifest_unchanged": source_manifest_hash
        == before["original_shard_c_package"]["blinded_manifest_sha256"],
        "hmac_and_v3_restricted_mapping_hashes_unchanged": restricted_files
        == before["restricted_identity_only_check"]["files"],
    }
    if not all(checks.values()):
        raise ValueError(f"source preservation comparison failed: {checks}")
    after = {
        "schema_version": "c4-real-r3d0-source-preservation-after-v1",
        "status": "PASS_ALL_ORIGINAL_R3_AND_RESTRICTED_IDENTITIES_UNCHANGED",
        "before_manifest_sha256": sha256_file(before_path),
        "checks": checks,
        "original_r3_file_count": len(original_files),
        "original_r3_files": original_files,
        "historical_execution_identity": EXPECTED_EXECUTION_IDENTITY,
        "original_shard_c_package": {
            "path": str(ORIGINAL_C_PACKAGE),
            "sha256": sha256_file(ORIGINAL_C_PACKAGE),
            "blinded_manifest_sha256": source_manifest_hash,
        },
        "restricted_identity_only_check": {
            "content_opened_or_unblinded": False,
            "files": restricted_files,
        },
    }
    write_json(HERE / "c4_real_r3_source_preservation_manifest_after_v1.json", after)
    return after


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "phase",
        choices=("before", "derived", "after", "all"),
        help="Build the preservation baseline, derived artifacts, or final comparison.",
    )
    args = parser.parse_args()
    if args.phase in ("before", "all"):
        build_preservation_before()
    if args.phase in ("derived", "all"):
        _, selected = build_reclassification_and_selection()
        build_continuation_and_boundary(selected)
    if args.phase in ("after", "all"):
        build_preservation_after()
    print(json.dumps({"status": "PASS", "phase": args.phase}, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
