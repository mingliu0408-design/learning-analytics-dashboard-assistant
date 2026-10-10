#!/usr/bin/env python3
"""Freeze the G2 source binding and blind, mechanical pre-Judge format audit."""

from __future__ import annotations

import argparse
import csv
import hashlib
import io
import json
import subprocess
from collections import Counter
from pathlib import Path
from typing import Any

try:
    from .c4_real_student_facing_response_validator_v1 import (
        OTHER_NON_STUDENT_FACING_FORMAT,
        RAW_INTERNAL_STRUCTURE,
        SERIALIZED_JSON_OBJECT_OR_ARRAY,
        TRIVIAL_NONANSWER,
        VALID_STUDENT_FACING_RESPONSE,
        classify_answer_text,
    )
except ImportError:
    from c4_real_student_facing_response_validator_v1 import (
        OTHER_NON_STUDENT_FACING_FORMAT,
        RAW_INTERNAL_STRUCTURE,
        SERIALIZED_JSON_OBJECT_OR_ARRAY,
        TRIVIAL_NONANSWER,
        VALID_STUDENT_FACING_RESPONSE,
        classify_answer_text,
    )


REPO_ROOT = Path(__file__).resolve().parents[3]
DEFAULT_OUTPUT_DIR = Path(__file__).resolve().parent
I1_DIR = REPO_ROOT / "evaluation/rq3_real_c4/i1_route_integration"
STARTING_HEAD = "2fd113d7c2d64442bb939cbd7aee80cab0ab4178"
EXPECTED_MODEL = "gpt-4o-mini-2024-07-18"
OUTER_SCHEMA_SHA256 = "485dbdc6af48577808d3e6a51fc9811e54f7a8f670f50f92c5bbb64ee382f873"

SOURCES = (
    {
        "shard": "A",
        "source_commit": "cfd169dd6773a0eabec611c6324b757326da7ef4",
        "integrated_commit": "4602f1d092e90e3a2ca44f22e2b24905ffa72a8c",
        "relative_journal": "evaluation/rq3_real_c4/g2a_generation_shard_a/execution_output_v1/GENERATION_TERMINAL_JOURNAL.jsonl",
        "relative_attempt_journal": "evaluation/rq3_real_c4/g2a_generation_shard_a/execution_output_v1/GENERATION_ATTEMPT_JOURNAL.jsonl",
        "relative_error_registry": "evaluation/rq3_real_c4/g2a_generation_shard_a/execution_output_v1/GENERATION_ERROR_REGISTRY.jsonl",
        "expected_terminal_sha256": "a106e593a6cbb1b886634c4b349af50d072afa5d30801e469158fd38449979eb",
        "expected_count": 73,
    },
    {
        "shard": "B",
        "source_commit": "4038bd44eaabaf5ec99f5164494ddad16f6981f6",
        "integrated_commit": "61a94b7926f2da83764fbccc6159bbcd1a23d39d",
        "relative_journal": "evaluation/rq3_real_c4/g2b_generation_shard_b/execution_output_v1/GENERATION_TERMINAL_JOURNAL.jsonl",
        "relative_attempt_journal": "evaluation/rq3_real_c4/g2b_generation_shard_b/execution_output_v1/GENERATION_ATTEMPT_JOURNAL.jsonl",
        "relative_error_registry": "evaluation/rq3_real_c4/g2b_generation_shard_b/execution_output_v1/GENERATION_ERROR_REGISTRY.jsonl",
        "expected_terminal_sha256": "5ab86bb3a440ff907894c0b3afc6e1c0f985ac55ea5e2fcdcaffae3bff9d4858",
        "expected_count": 62,
    },
    {
        "shard": "C",
        "source_commit": "000f5e9cd88413967811f005944b60a5aa29d761",
        "integrated_commit": "2c1094d6486d5db8d01d8a4ef02e11f15d1813e9",
        "relative_journal": "evaluation/rq3_real_c4/g2c_generation_shard_c/execution_output_v1/GENERATION_TERMINAL_JOURNAL.jsonl",
        "relative_attempt_journal": "evaluation/rq3_real_c4/g2c_generation_shard_c/execution_output_v1/GENERATION_ATTEMPT_JOURNAL.jsonl",
        "relative_error_registry": "evaluation/rq3_real_c4/g2c_generation_shard_c/execution_output_v1/GENERATION_ERROR_REGISTRY.jsonl",
        "expected_terminal_sha256": "d91c60aebdcde9103b9bfec62ae0b8d387b79e7d1a275dc22c8ee034168786ef",
        "expected_count": 62,
    },
)

AUDIT_CLASSIFICATION_BY_VALIDATOR_STATUS = {
    VALID_STUDENT_FACING_RESPONSE: "NATURAL_LANGUAGE_RESPONSE",
    TRIVIAL_NONANSWER: "TRIVIAL_NONANSWER",
    SERIALIZED_JSON_OBJECT_OR_ARRAY: "SERIALIZED_JSON_OBJECT_OR_ARRAY",
    RAW_INTERNAL_STRUCTURE: "RAW_EVIDENCE_OR_PLANNING_DUMP",
    OTHER_NON_STUDENT_FACING_FORMAT: "OTHER_NON_STUDENT_FACING_FORMAT",
}


def canonical_json_bytes(value: Any) -> bytes:
    return (json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n").encode("utf-8")


def pretty_json_bytes(value: Any) -> bytes:
    return (json.dumps(value, ensure_ascii=False, sort_keys=True, indent=2) + "\n").encode("utf-8")


def sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def git(*args: str) -> str:
    completed = subprocess.run(
        ["git", *args], cwd=REPO_ROOT, check=True, capture_output=True, text=True
    )
    return completed.stdout.strip()


def read_jsonl_bytes(raw: bytes) -> list[dict[str, Any]]:
    return [json.loads(line) for line in raw.decode("utf-8").splitlines() if line]


def committed_blob(commit: str, relative_path: str) -> bytes:
    completed = subprocess.run(
        ["git", "show", f"{commit}:{relative_path}"],
        cwd=REPO_ROOT,
        check=True,
        capture_output=True,
    )
    return completed.stdout


def answer_binding_sha256(records: list[dict[str, Any]]) -> str:
    bindings = []
    for record in records:
        answer_text = record["parsed_output"]["answer_text"]
        bindings.append(
            {
                "logical_generation_request_id": record["logical_generation_request_id"],
                "logical_order": record["logical_order"],
                "response_blind_id": record["response_blind_id"],
                "answer_text_sha256": sha256_bytes(answer_text.encode("utf-8")),
            }
        )
    return sha256_bytes(canonical_json_bytes(bindings))


def collect_sources() -> tuple[dict[str, Any], list[dict[str, Any]]]:
    all_records: list[dict[str, Any]] = []
    source_entries: list[dict[str, Any]] = []
    aggregate_usage: Counter[str] = Counter()

    if git("rev-parse", f"{STARTING_HEAD}^{{commit}}") != STARTING_HEAD:
        raise RuntimeError("starting commit is unavailable")

    for source in SOURCES:
        if git("rev-parse", f"{source['source_commit']}^") != STARTING_HEAD:
            raise RuntimeError(f"source parent mismatch for shard {source['shard']}")
        if git("rev-parse", f"{source['integrated_commit']}^") == source["integrated_commit"]:
            raise RuntimeError("impossible integrated commit parent")
        if subprocess.run(
            ["git", "merge-base", "--is-ancestor", source["integrated_commit"], "HEAD"],
            cwd=REPO_ROOT,
        ).returncode != 0:
            raise RuntimeError(f"integrated commit is not in HEAD history for shard {source['shard']}")

        terminal_path = REPO_ROOT / source["relative_journal"]
        terminal_bytes = terminal_path.read_bytes()
        actual_sha256 = sha256_bytes(terminal_bytes)
        if actual_sha256 != source["expected_terminal_sha256"]:
            raise RuntimeError(f"terminal journal hash mismatch for shard {source['shard']}")
        if terminal_bytes != committed_blob(source["source_commit"], source["relative_journal"]):
            raise RuntimeError(f"integrated terminal journal differs from original shard {source['shard']}")

        records = read_jsonl_bytes(terminal_bytes)
        if len(records) != source["expected_count"]:
            raise RuntimeError(f"terminal record count mismatch for shard {source['shard']}")
        if [record["logical_order"] for record in records] != list(range(1, len(records) + 1)):
            raise RuntimeError(f"logical order is not contiguous for shard {source['shard']}")

        attempt_path = REPO_ROOT / source["relative_attempt_journal"]
        attempt_bytes = attempt_path.read_bytes()
        if attempt_bytes != committed_blob(source["source_commit"], source["relative_attempt_journal"]):
            raise RuntimeError(f"integrated attempt journal differs from original shard {source['shard']}")
        attempt_records = read_jsonl_bytes(attempt_bytes)
        if len(attempt_records) != len(records):
            raise RuntimeError(f"physical-attempt count mismatch for shard {source['shard']}")

        error_path = REPO_ROOT / source["relative_error_registry"]
        error_bytes = error_path.read_bytes()
        if error_bytes != committed_blob(source["source_commit"], source["relative_error_registry"]):
            raise RuntimeError(f"integrated error registry differs from original shard {source['shard']}")
        if error_bytes.strip():
            raise RuntimeError(f"non-empty error registry for shard {source['shard']}")

        if any(record["physical_attempts"] != 1 for record in records):
            raise RuntimeError(f"retry observed for shard {source['shard']}")
        if any(record["terminal_status"] != "VALID_RESPONSE" for record in records):
            raise RuntimeError(f"invalid terminal status for shard {source['shard']}")
        if any(record["returned_model"] != EXPECTED_MODEL for record in records):
            raise RuntimeError(f"returned-model mismatch for shard {source['shard']}")
        if any(not isinstance(record["parsed_output"].get("answer_text"), str) for record in records):
            raise RuntimeError(f"outer-schema-invalid answer_text for shard {source['shard']}")

        for field in ("prompt_tokens", "cached_input_tokens", "completion_tokens", "total_tokens"):
            aggregate_usage[field] += sum(int(record[field]) for record in records)

        source_entries.append(
            {
                "answer_text_binding_sha256": answer_binding_sha256(records),
                "attempt_journal_sha256": sha256_bytes(attempt_bytes),
                "cherry_picked_commit": source["integrated_commit"],
                "error_registry_sha256": sha256_bytes(error_bytes),
                "original_generation_commit": source["source_commit"],
                "physical_attempt_count": len(attempt_records),
                "response_count": len(records),
                "shard": source["shard"],
                "terminal_journal_path": source["relative_journal"],
                "terminal_journal_sha256": actual_sha256,
            }
        )
        for record in records:
            all_records.append({"shard": source["shard"], **record})

    logical_ids = [record["logical_generation_request_id"] for record in all_records]
    response_ids = [record["response_blind_id"] for record in all_records]
    if len(all_records) != 197 or len(set(logical_ids)) != 197 or len(set(response_ids)) != 197:
        raise RuntimeError("G2 global uniqueness or population invariant failed")
    if aggregate_usage != Counter(
        prompt_tokens=120366,
        cached_input_tokens=5120,
        completion_tokens=25597,
        total_tokens=145963,
    ):
        raise RuntimeError(f"aggregate provider usage mismatch: {dict(aggregate_usage)}")

    manifest = {
        "aggregate_usage": dict(sorted(aggregate_usage.items())),
        "all_returned_models_identical": True,
        "error_totals": {
            "json_errors": 0,
            "model_identity_errors": 0,
            "outer_schema_errors": 0,
            "provider_errors": 0,
        },
        "expected_outer_response_schema_sha256": OUTER_SCHEMA_SHA256,
        "logical_request_count": len(all_records),
        "original_to_cherry_picked_commit_mapping": source_entries,
        "physical_attempt_count": len(all_records),
        "response_blind_id_count": len(set(response_ids)),
        "returned_model": EXPECTED_MODEL,
        "retry_count": 0,
        "schema_version": "c4-real-g2-response-source-manifest-v1",
        "source_freeze_date": "2026-09-01",
        "terminal_result_count": len(all_records),
        "terminal_result_population": "73 + 62 + 62 = 197",
        "terminal_status": "ALL_OUTER_SCHEMA_VALID",
        "unique_logical_request_id_count": len(set(logical_ids)),
        "unique_response_blind_id_count": len(set(response_ids)),
    }
    return manifest, all_records


def audit_records(records: list[dict[str, Any]]) -> list[dict[str, Any]]:
    rows = []
    for record in records:
        answer_text = record["parsed_output"]["answer_text"]
        validator_status = classify_answer_text(answer_text)
        rows.append(
            {
                "shard": record["shard"],
                "logical_order": record["logical_order"],
                "opaque_request_id": record["logical_generation_request_id"],
                "opaque_response_blind_id": record["response_blind_id"],
                "classification": AUDIT_CLASSIFICATION_BY_VALIDATOR_STATUS[validator_status],
                "answer_character_count": len(answer_text),
                "answer_word_count": len(__import__("re").findall(r"\b\w+\b", answer_text)),
                "completion_tokens": record["completion_tokens"],
                "finish_reason": record["finish_reason"],
            }
        )
    return rows


def csv_bytes(rows: list[dict[str, Any]]) -> bytes:
    output = io.StringIO(newline="")
    writer = csv.DictWriter(output, fieldnames=list(rows[0]), lineterminator="\n")
    writer.writeheader()
    writer.writerows(rows)
    return output.getvalue().encode("utf-8")


def audit_markdown(counts: Counter[str], non_student_count: int) -> bytes:
    lines = [
        "# C4 Real G2 Pre-Judge Format Audit",
        "",
        "Status: `BLIND_MECHANICAL_CLASSIFICATION_FROZEN`",
        "",
        "This audit applied only the frozen student-facing response-format contract. It did not use restricted condition mappings, calculate response-quality scores, call a Judge, or rate factual correctness, relevance, helpfulness, personalisation, actionability, or evidence quality.",
        "",
        "## Population",
        "",
        "- G2 terminal responses: 197",
        "- Unique opaque logical request IDs: 197",
        "- Unique opaque response blind IDs: 197",
        "- Shards: A=73, B=62, C=62",
        "",
        "## Mechanical classifications",
        "",
        "| Classification | Count |",
        "| --- | ---: |",
    ]
    for label in (
        "NATURAL_LANGUAGE_RESPONSE",
        "TRIVIAL_NONANSWER",
        "SERIALIZED_JSON_OBJECT_OR_ARRAY",
        "RAW_EVIDENCE_OR_PLANNING_DUMP",
        "OTHER_NON_STUDENT_FACING_FORMAT",
    ):
        lines.append(f"| `{label}` | {counts[label]} |")
    lines.extend(
        [
            "",
            f"Total non-student-facing responses: **{non_student_count}**.",
            "",
            "The classification was derived from the committed terminal journals and was not hard-coded from the independent audit estimate.",
            "",
            "No response-quality score is present in the CSV or JSON audit.",
        ]
    )
    return ("\n".join(lines) + "\n").encode("utf-8")


def render_outputs(output_dir: Path) -> dict[str, bytes]:
    manifest, records = collect_sources()
    rows = audit_records(records)
    counts = Counter(row["classification"] for row in rows)
    non_student_count = len(rows) - counts["NATURAL_LANGUAGE_RESPONSE"]
    if sum(counts.values()) != 197:
        raise RuntimeError("audit population mismatch")

    audit_json = {
        "audit_scope": "BLIND_MECHANICAL_STUDENT_FACING_FORMAT_ONLY",
        "classification_counts": dict(sorted(counts.items())),
        "format_contract": "c4_real_student_facing_response_format_contract_v1.json",
        "format_contract_sha256": sha256_bytes(
            (output_dir / "c4_real_student_facing_response_format_contract_v1.json").read_bytes()
        ),
        "non_student_facing_response_count": non_student_count,
        "quality_scores_calculated": False,
        "records": rows,
        "restricted_mapping_accessed": False,
        "schema_version": "c4-real-g2-prejudge-format-audit-v1",
        "student_facing_response_count": counts["NATURAL_LANGUAGE_RESPONSE"],
        "terminal_response_count": len(rows),
    }
    return {
        "c4_real_g2_response_source_manifest_v1.json": pretty_json_bytes(manifest),
        "c4_real_g2_prejudge_format_audit_v1.csv": csv_bytes(rows),
        "c4_real_g2_prejudge_format_audit_v1.json": pretty_json_bytes(audit_json),
        "C4_REAL_G2_PREJUDGE_FORMAT_AUDIT.md": audit_markdown(counts, non_student_count),
    }


def write_once(path: Path, data: bytes) -> None:
    if path.exists():
        raise RuntimeError(f"refusing to overwrite frozen output: {path}")
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_bytes(data)
    temporary.replace(path)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT_DIR)
    parser.add_argument("--verify-only", action="store_true")
    args = parser.parse_args()
    output_dir = args.output_dir.resolve()
    outputs = render_outputs(output_dir)

    if args.verify_only:
        for name, data in outputs.items():
            if (output_dir / name).read_bytes() != data:
                raise RuntimeError(f"frozen blind audit is not deterministic: {name}")
        receipt = json.loads((output_dir / "c4_real_g2_blind_format_audit_freeze_receipt_v1.json").read_text())
        for name, expected_hash in receipt["frozen_artifact_sha256"].items():
            if sha256_bytes((output_dir / name).read_bytes()) != expected_hash:
                raise RuntimeError(f"freeze receipt hash mismatch: {name}")
        print("BLIND_G2_FORMAT_AUDIT_VERIFIED")
        return 0

    output_dir.mkdir(parents=True, exist_ok=True)
    receipt_path = output_dir / "c4_real_g2_blind_format_audit_freeze_receipt_v1.json"
    if receipt_path.exists():
        raise RuntimeError("blind format audit is already frozen")
    for name, data in outputs.items():
        write_once(output_dir / name, data)

    frozen_names = [
        "c4_real_student_facing_response_format_contract_v1.json",
        *outputs.keys(),
    ]
    receipt = {
        "classification_frozen_before_restricted_mapping_access": True,
        "frozen_artifact_sha256": {
            name: sha256_bytes((output_dir / name).read_bytes()) for name in frozen_names
        },
        "freeze_date": "2026-09-01",
        "restricted_mapping_accessed_by_this_phase": False,
        "schema_version": "c4-real-g2-blind-format-audit-freeze-receipt-v1",
    }
    write_once(receipt_path, pretty_json_bytes(receipt))
    print("BLIND_G2_FORMAT_AUDIT_FROZEN")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
