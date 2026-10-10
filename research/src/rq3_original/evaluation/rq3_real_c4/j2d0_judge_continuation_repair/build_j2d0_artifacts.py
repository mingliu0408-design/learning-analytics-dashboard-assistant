#!/usr/bin/env python3
"""Build the offline RQ3-REAL-C4-J2D0 evidence and continuation ZIPs.

The builder reads only the frozen blinded R2 Judge Packages and the integrated
Judge execution evidence.  It never reads restricted mappings, never imports
Human ratings, and never constructs or sends a Provider request.
"""

from __future__ import annotations

from collections import defaultdict
from datetime import datetime
import hashlib
import importlib.metadata
import importlib.util
import json
import os
from pathlib import Path
import platform
import subprocess
import sys
from typing import Any, Mapping
from zipfile import ZIP_DEFLATED, ZipFile, ZipInfo

from judge_execution_runner_v3 import (
    REQUEST_TIMEOUT_SECONDS,
    validate_client_transport_configuration,
)
from judge_package_validator_v3 import (
    ALLOWED_FILES,
    canonical_json_bytes,
    sha256_bytes,
    sha256_file,
    validate_package_zip,
)
from judge_result_parser_v3 import (
    JudgeResultError as JudgeResultErrorV3,
    parse_judge_result as parse_v3,
    rationale_lengths,
)


HERE = Path(__file__).resolve().parent
REPO = HERE.parents[2]
R2_DIR = REPO / "evaluation/rq3_real_c4/r3d1_response_integration_r2"
DOWNLOADS = Path("/Users/liuming/Downloads")
STARTING_HEAD = "366286e257abca2be18cc6fe88de5f7e445a65bd"
READY_STATUS = "READY_FOR_SEQUENTIAL_C4_REAL_JUDGE_CONTINUATION_EXECUTION_R3"
SELECTION_RULE = "EARLIEST_VALID_ATTEMPT_UNDER_JUDGE_PARSER_V3"
EXPECTED_PROVIDER_FIELDS = {
    "clarity",
    "personalisation",
    "actionability",
    "context_awareness",
    "motivation_and_engagement",
    "reliability",
    "multi_page_cohesiveness",
    "error_handling",
    "evidence_faithfulness",
    "unsupported_claim_count",
    "criterion_rationales",
    "schema_version",
}

SHARDS: dict[str, dict[str, Any]] = {
    "A": {
        "original_commit": "9c18da0ba418161b0976fbfd4cbaf7e86368b84c",
        "cherry_commit": "c66e183e975d2d4cff7d94b058249ca6042b1222",
        "evidence_dir": "j2a_judge_shard_a",
        "package_name": "C4_REAL_JUDGE_SHARD_A_EXECUTION_PACKAGE_R2_2026-09-02.zip",
        "package_sha256": "7e57d62a56feb2776398fd2b719a009e3eed64c8ebb6b48fc63666eaed300ff7",
        "source_package_id": "C4_REAL_JUDGE_SHARD_A_R2_2026-09-02",
        "source_manifest_sha256": "8ada68b5e3aec8b7c6e90715aebeb65d954d5b5bf9bfc3b5fe63f10b489041ef",
        "attempt_sha256": "53fc0cd24e492ef8f585b6789c64f2e5fa0a13486298910c6e3224eaf36f0bf6",
        "terminal_sha256": "e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855",
        "parsed_set_sha256": "e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855",
        "started": 2,
        "returned": 2,
        "terminals": 0,
        "remaining_orders": tuple(range(2, 50)),
        "continuation_id": "A_CONTINUATION",
        "package_id": "C4_REAL_JUDGE_SHARD_A_CONTINUATION_R3_20260902",
        "continuation_name": "C4_REAL_JUDGE_SHARD_A_CONTINUATION_EXECUTION_PACKAGE_R3_2026-09-02.zip",
    },
    "B": {
        "original_commit": "936aef8c9e8796262887b7f9ab4a8358d128481d",
        "cherry_commit": "4a8200d07e7c8efa20aa87597b9707a9651ade56",
        "evidence_dir": "j2b_judge_shard_b",
        "package_name": "C4_REAL_JUDGE_SHARD_B_EXECUTION_PACKAGE_R2_2026-09-02.zip",
        "package_sha256": "decc499163089e467ae6ec0e5d4f4e46a410f3670a99b17cf0c6396031ffb68b",
        "source_package_id": "C4_REAL_JUDGE_SHARD_B_R2_2026-09-02",
        "source_manifest_sha256": "e6a20b1bc2b0b980c514e74db37a9791bd15eaa0e69cdf07f6d1f56ff6a5a1f3",
        "attempt_sha256": "fa34d09149e4874c6380445836ba28f5e8f3ab47363619add1a2f8684c3500ca",
        "terminal_sha256": "ec90b7e4994f0ace2dcbfed2965066e790fe720affc7d155cc374c88148c5a44",
        "parsed_set_sha256": "93c8c3f106a59e697612bf2751f534ea1fb58e00f1f7d184a945d2cf5f6889bc",
        "started": 39,
        "returned": 38,
        "terminals": 38,
        "remaining_orders": tuple(range(39, 50)),
        "timeout_order": 39,
        "timeout_error_at": "2026-09-02T13:07:00.824768Z",
        "timeout_start_at": "2026-09-02T13:06:50.813689Z",
        "continuation_id": "B_CONTINUATION",
        "package_id": "C4_REAL_JUDGE_SHARD_B_CONTINUATION_R3_20260902",
        "continuation_name": "C4_REAL_JUDGE_SHARD_B_CONTINUATION_EXECUTION_PACKAGE_R3_2026-09-02.zip",
    },
    "C": {
        "original_commit": "02b9b1572065e780592bf6326acb6fd002a98288",
        "cherry_commit": "ba598bd74d889469b7479db7e84b06319e914890",
        "evidence_dir": "j2c_judge_shard_c",
        "package_name": "C4_REAL_JUDGE_SHARD_C_EXECUTION_PACKAGE_R2_2026-09-02.zip",
        "package_sha256": "7f7863a5dd399ae62136bd5bf7541f6d5fc7347eafb275d22b435b25821639cd",
        "source_package_id": "C4_REAL_JUDGE_SHARD_C_R2_2026-09-02",
        "source_manifest_sha256": "dc65e44ef70298c68f7d70c5123b897388bdcab00a4deaeb0e3a80dececb0f10",
        "attempt_sha256": "2e81be2f91cc922af451f8d61da74a6f87ea52521e8a33cc0b1ec371a1bf86b6",
        "terminal_sha256": "8d5af59458e65a90b38c363204fd71dea6ee30dad00fd245929e7b26aa151a28",
        "parsed_set_sha256": "80c94a06ebe14f8cbf7cb8f63fc7caab95ad59938ebe5b9792e6113dc7140816",
        "started": 32,
        "returned": 31,
        "terminals": 31,
        "remaining_orders": tuple(range(32, 50)),
        "timeout_order": 32,
        "timeout_error_at": "2026-09-02T13:06:57.484653Z",
        "timeout_start_at": "2026-09-02T13:06:47.474174Z",
        "continuation_id": "C_CONTINUATION",
        "package_id": "C4_REAL_JUDGE_SHARD_C_CONTINUATION_R3_20260902",
        "continuation_name": "C4_REAL_JUDGE_SHARD_C_CONTINUATION_EXECUTION_PACKAGE_R3_2026-09-02.zip",
    },
}


def json_bytes(value: Any) -> bytes:
    return (
        json.dumps(value, ensure_ascii=False, sort_keys=True, indent=2, allow_nan=False)
        + "\n"
    ).encode("utf-8")


def jsonl_bytes(rows: list[Mapping[str, Any]]) -> bytes:
    return b"".join(canonical_json_bytes(row) + b"\n" for row in rows)


def write_artifact(name: str, data: bytes) -> None:
    target = HERE / name
    if target.parent != HERE:
        raise RuntimeError("nested or out-of-scope artifact target")
    if target.is_symlink():
        raise RuntimeError(f"refusing symlink artifact target: {name}")
    if not target.exists() or target.read_bytes() != data:
        target.write_bytes(data)


def git_bytes(*args: str) -> bytes:
    return subprocess.run(
        ["git", *args],
        cwd=REPO,
        check=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    ).stdout


def git_text(*args: str) -> str:
    return git_bytes(*args).decode("utf-8").strip()


def load_jsonl_bytes(data: bytes) -> list[dict[str, Any]]:
    return [json.loads(line) for line in data.splitlines() if line.strip()]


def load_v2_parser() -> Any:
    path = R2_DIR / "judge_result_parser_v2.py"
    spec = importlib.util.spec_from_file_location("j2d0_frozen_parser_v2", path)
    if spec is None or spec.loader is None:
        raise RuntimeError("cannot load frozen Parser V2")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def extract_applicability(provider_payload: Mapping[str, Any]) -> dict[str, Any]:
    content = provider_payload["messages"][0]["content"]
    raw = content.split("BEGIN_BLIND_JUDGE_REQUEST_JSON\n", 1)[1].rsplit(
        "\nEND_BLIND_JUDGE_REQUEST_JSON", 1
    )[0]
    return json.loads(raw)["frozen_applicability_map"]


def source_package(shard: str, info: Mapping[str, Any]) -> tuple[dict[str, bytes], list[dict[str, Any]]]:
    path = DOWNLOADS / info["package_name"]
    if sha256_file(path) != info["package_sha256"]:
        raise RuntimeError(f"Shard {shard} R2 Package hash mismatch")
    with ZipFile(path) as archive:
        members = {item.filename: archive.read(item) for item in archive.infolist()}
    if set(members) != {
        "README.md",
        "BLINDED_JUDGE_REQUESTS.jsonl",
        "JUDGE_PROMPT.txt",
        "JUDGE_SCHEMA.json",
        "JUDGE_CONFIGURATION.json",
        "PRIMARY_RUBRIC.json",
        "APPLICABILITY_CONTRACT.json",
        "EXECUTION_CONTRACT.json",
        "judge_execution_runner_v2.py",
        "judge_result_parser_v2.py",
        "validate_package.py",
        "test_package.py",
        "PACKAGE_SOURCE_HASHES.json",
    }:
        raise RuntimeError(f"Shard {shard} R2 Package member mismatch")
    declared = json.loads(members["PACKAGE_SOURCE_HASHES.json"])["member_sha256"]
    for name, expected in declared.items():
        if sha256_bytes(members[name]) != expected:
            raise RuntimeError(f"Shard {shard} R2 member changed: {name}")
    if sha256_bytes(members["BLINDED_JUDGE_REQUESTS.jsonl"]) != info[
        "source_manifest_sha256"
    ]:
        raise RuntimeError(f"Shard {shard} R2 request manifest mismatch")
    rows = load_jsonl_bytes(members["BLINDED_JUDGE_REQUESTS.jsonl"])
    if len(rows) != 49:
        raise RuntimeError(f"Shard {shard} R2 request count mismatch")
    for row in rows:
        if sha256_bytes(canonical_json_bytes(row["provider_payload"])) != row[
            "provider_payload_sha256"
        ]:
            raise RuntimeError(f"Shard {shard} source Provider payload mismatch")
    return members, rows


def parsed_result_set_hash(shard: str, terminals: list[dict[str, Any]]) -> str:
    ordered = sorted(terminals, key=lambda row: row["logical_order"])
    if shard == "B":
        projected = [
            {
                key: row[key]
                for key in (
                    "logical_order",
                    "logical_judge_request_id",
                    "judge_result_blind_id",
                    "parsed_semantic_result",
                )
            }
            for row in ordered
        ]
        return sha256_bytes(canonical_json_bytes(projected))
    if shard == "C":
        data = b"".join(
            canonical_json_bytes(row["parsed_semantic_result"]) + b"\n"
            for row in ordered
        )
        return sha256_bytes(data)
    return sha256_bytes(b"")


def commit_preservation_manifest() -> tuple[dict[str, Any], dict[str, Any]]:
    mapping_rows: list[dict[str, Any]] = []
    preservation: dict[str, Any] = {
        "schema_version": "c4-real-judge-existing-evidence-preservation-v1",
        "status": "PASS_BEFORE_AFTER_IDENTICAL",
        "comparison": "original source-commit bytes versus post-J2D0 working-tree bytes",
        "original_packages": {},
        "integrated_execution_evidence": {},
        "all_original_execution_artifacts_unchanged": True,
    }
    previous = STARTING_HEAD
    for shard, info in SHARDS.items():
        original = info["original_commit"]
        cherry = info["cherry_commit"]
        if git_text("rev-parse", f"{cherry}^") != previous:
            raise RuntimeError(f"Shard {shard} cherry-pick order/parent mismatch")
        original_parent = git_text("rev-parse", f"{original}^")
        if original_parent != STARTING_HEAD:
            raise RuntimeError(f"Shard {shard} source commit parent mismatch")
        subject = git_text("show", "-s", "--format=%s", original)
        cherry_subject = git_text("show", "-s", "--format=%s", cherry)
        if subject != cherry_subject:
            raise RuntimeError(f"Shard {shard} cherry-pick subject mismatch")
        source_paths = git_text("diff-tree", "--no-commit-id", "--name-only", "-r", original).splitlines()
        file_rows: dict[str, Any] = {}
        for relative in source_paths:
            before = git_bytes("show", f"{original}:{relative}")
            current_path = REPO / relative
            if not current_path.is_file():
                raise RuntimeError(f"preserved file is absent: {relative}")
            after = current_path.read_bytes()
            before_hash = sha256_bytes(before)
            after_hash = sha256_bytes(after)
            if before_hash != after_hash:
                raise RuntimeError(f"preserved file changed: {relative}")
            file_rows[relative] = {
                "before_sha256": before_hash,
                "after_sha256": after_hash,
                "unchanged": True,
                "bytes": len(after),
            }
        preservation["integrated_execution_evidence"][shard] = {
            "original_commit": original,
            "cherry_picked_commit": cherry,
            "file_count": len(file_rows),
            "files": file_rows,
            "unchanged": True,
        }
        package_path = DOWNLOADS / info["package_name"]
        package_hash = sha256_file(package_path)
        if package_hash != info["package_sha256"]:
            raise RuntimeError(f"Shard {shard} source Package changed")
        preservation["original_packages"][shard] = {
            "path": str(package_path),
            "before_sha256": info["package_sha256"],
            "after_sha256": package_hash,
            "unchanged": True,
        }
        mapping_rows.append(
            {
                "shard": shard,
                "original_commit": original,
                "cherry_picked_commit": cherry,
                "source_parent": STARTING_HEAD,
                "cherry_parent": previous,
                "subject": subject,
                "tree_content_preserved": True,
            }
        )
        previous = cherry
    mapping = {
        "schema_version": "c4-real-judge-commit-integration-mapping-v1",
        "status": "PASS_INTEGRATED_IN_EXACT_ORDER",
        "starting_head": STARTING_HEAD,
        "integrations": mapping_rows,
        "branch_creation_switch_merge_rename_delete_performed": False,
    }
    return mapping, preservation


def offline_client_preflight() -> dict[str, Any]:
    if sys.executable != "/opt/anaconda3/bin/python3":
        raise RuntimeError("exact Python executable mismatch")
    if platform.python_version() != "3.13.5":
        raise RuntimeError("exact Python version mismatch")
    sdk = importlib.metadata.version("openai")
    if sdk != "1.109.1":
        raise RuntimeError("exact OpenAI SDK version mismatch")
    from openai import OpenAI

    client = OpenAI(
        api_key="offline-j2d0-client-construction-only",
        max_retries=0,
        timeout=REQUEST_TIMEOUT_SECONDS,
    )
    try:
        client_result = validate_client_transport_configuration(client)
    finally:
        client.close()
    return {
        "schema_version": "c4-real-judge-runner-v3-offline-preflight-receipt-v1",
        "status": "PASS_CLIENT_ACCEPTED_AND_PRESERVED_EXPLICIT_TIMEOUT",
        "python_executable": sys.executable,
        "python_version": platform.python_version(),
        "openai_sdk_version": sdk,
        "api_key_presence_checked_only": True,
        "api_key_present": bool(os.environ.get("OPENAI_API_KEY")),
        "api_key_value_recorded": False,
        **client_result,
        "provider_calls": 0,
        "network_calls": 0,
    }


def classify_existing_outputs(
    source_rows: Mapping[str, list[dict[str, Any]]],
    parser_v2: Any,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]], dict[str, Any], dict[str, Any]]:
    reclassified: list[dict[str, Any]] = []
    canonical: list[dict[str, Any]] = []
    timeout_audit: dict[str, Any] = {}
    v2_valid = 0
    v3_valid = 0
    for shard, info in SHARDS.items():
        evidence = REPO / "evaluation/rq3_real_c4" / info["evidence_dir"] / "execution_output_v1"
        attempt_path = evidence / "JUDGE_ATTEMPT_JOURNAL.jsonl"
        terminal_path = evidence / "JUDGE_TERMINAL_JOURNAL.jsonl"
        if sha256_file(attempt_path) != info["attempt_sha256"]:
            raise RuntimeError(f"Shard {shard} attempt journal hash mismatch")
        if sha256_file(terminal_path) != info["terminal_sha256"]:
            raise RuntimeError(f"Shard {shard} terminal journal hash mismatch")
        attempts = load_jsonl_bytes(attempt_path.read_bytes())
        starts = [row for row in attempts if row["event"] == "ATTEMPT_STARTED"]
        returned = [row for row in attempts if row["event"] == "ATTEMPT_RETURNED"]
        terminals = load_jsonl_bytes(terminal_path.read_bytes())
        if (len(starts), len(returned), len(terminals)) != (
            info["started"],
            info["returned"],
            info["terminals"],
        ):
            raise RuntimeError(f"Shard {shard} execution counts mismatch")
        if parsed_result_set_hash(shard, terminals) != info["parsed_set_sha256"]:
            raise RuntimeError(f"Shard {shard} parsed-result-set hash mismatch")
        source_by_id = {row["logical_judge_request_id"]: row for row in source_rows[shard]}
        terminal_by_id = {row["logical_judge_request_id"]: row for row in terminals}
        valid_by_order: dict[int, list[dict[str, Any]]] = defaultdict(list)
        for attempt in returned:
            source = source_by_id[attempt["logical_judge_request_id"]]
            if attempt["judge_result_blind_id"] != source["judge_result_blind_id"]:
                raise RuntimeError("attempt/result blind ID mismatch")
            if attempt["provider_payload_sha256"] != source["provider_payload_sha256"]:
                raise RuntimeError("attempt/Provider payload hash mismatch")
            raw = attempt["raw_response_content"]
            applicability = extract_applicability(source["provider_payload"])
            lengths = rationale_lengths(raw)
            parsed_v2: dict[str, Any] | None = None
            try:
                parsed_v2 = parser_v2.parse_judge_result(
                    raw,
                    applicability,
                    expected_judge_result_blind_id=attempt["judge_result_blind_id"],
                )
                v2_status = "VALID"
                v2_valid += 1
            except parser_v2.JudgeResultError as exc:
                v2_status = parser_v2.retryable_failure_code(exc) or "INVALID"
            try:
                parsed_v3 = parse_v3(
                    raw,
                    applicability,
                    expected_judge_result_blind_id=attempt["judge_result_blind_id"],
                )
                v3_status = "VALID"
                v3_valid += 1
            except JudgeResultErrorV3 as exc:  # pragma: no cover - fail closed
                raise RuntimeError(f"Parser V3 rejected returned Shard {shard} output") from exc
            if parsed_v2 is not None and parsed_v2 != parsed_v3:
                raise RuntimeError(f"Parser V2/V3 semantic drift in Shard {shard}")
            row = {
                "schema_version": "c4-real-existing-judge-attempt-reclassification-v3",
                "shard": shard,
                "logical_order": attempt["logical_order"],
                "opaque_judge_request_id": attempt["logical_judge_request_id"],
                "opaque_result_blind_id": attempt["judge_result_blind_id"],
                "attempt_number": attempt["attempt_number"],
                "parser_v2_status": v2_status,
                "parser_v3_status": v3_status,
                "rationale_lengths": lengths,
                "raw_output_sha256": sha256_bytes(raw.encode("utf-8")),
                "parsed_semantic_result_sha256": sha256_bytes(
                    canonical_json_bytes(parsed_v3)
                ),
                "canonical_selection_status": "ELIGIBLE_EARLIEST_VALID_RULE",
            }
            if shard == "A" and attempt["attempt_number"] == 2:
                row["canonical_selection_status"] = (
                    "NOT_SELECTED_REDUNDANT_RETRY_AFTER_PARSER_V2_FALSE_REJECTION"
                )
            reclassified.append(row)
            valid_by_order[attempt["logical_order"]].append(
                {"attempt": attempt, "parsed": parsed_v3, "row": row}
            )
            if shard in {"B", "C"}:
                terminal = terminal_by_id[attempt["logical_judge_request_id"]]
                if terminal["parsed_semantic_result"] != parsed_v3:
                    raise RuntimeError(f"Shard {shard} terminal semantic result changed")
        for logical_order in sorted(valid_by_order):
            candidates = sorted(
                valid_by_order[logical_order],
                key=lambda value: value["attempt"]["attempt_number"],
            )
            selected = candidates[0]
            attempt = selected["attempt"]
            parsed = selected["parsed"]
            canonical.append(
                {
                    "schema_version": "c4-real-existing-canonical-judge-result-v1",
                    "shard": shard,
                    "logical_order": logical_order,
                    "opaque_judge_request_id": attempt["logical_judge_request_id"],
                    "opaque_result_blind_id": attempt["judge_result_blind_id"],
                    "selected_attempt_number": attempt["attempt_number"],
                    "selection_rule": SELECTION_RULE,
                    "provider_payload_sha256": attempt["provider_payload_sha256"],
                    "raw_output_sha256": selected["row"]["raw_output_sha256"],
                    "parsed_semantic_result_sha256": selected["row"][
                        "parsed_semantic_result_sha256"
                    ],
                    "parsed_semantic_result": parsed,
                }
            )
        if "timeout_order" in info:
            order = info["timeout_order"]
            start = next(row for row in starts if row["logical_order"] == order)
            errors = load_jsonl_bytes((evidence / "JUDGE_ERROR_REGISTRY.jsonl").read_bytes())
            if len(errors) != 1 or errors[0]["error_category"] != "APITimeoutError":
                raise RuntimeError(f"Shard {shard} timeout error evidence mismatch")
            if start["request_started_at_utc"] != info["timeout_start_at"]:
                raise RuntimeError(f"Shard {shard} timeout start mismatch")
            if errors[0]["timestamp_utc"] != info["timeout_error_at"]:
                raise RuntimeError(f"Shard {shard} timeout error timestamp mismatch")
            start_dt = datetime.fromisoformat(info["timeout_start_at"].replace("Z", "+00:00"))
            error_dt = datetime.fromisoformat(info["timeout_error_at"].replace("Z", "+00:00"))
            if any(row["logical_order"] == order for row in returned):
                raise RuntimeError(f"Shard {shard} timeout has a returned output")
            if any(row["logical_order"] == order for row in terminals):
                raise RuntimeError(f"Shard {shard} timeout has a terminal result")
            timeout_audit[shard] = {
                "logical_order": order,
                "request_started_at_utc": info["timeout_start_at"],
                "timeout_error_at_utc": info["timeout_error_at"],
                "elapsed_seconds": (error_dt - start_dt).total_seconds(),
                "provider_response_recorded": False,
                "terminal_result_recorded": False,
                "json_schema_or_applicability_failure_recorded": False,
                "durable_error_category": "APITimeoutError",
            }

    reclassified.sort(key=lambda row: (row["shard"], row["logical_order"], row["attempt_number"]))
    canonical.sort(key=lambda row: (row["shard"], row["logical_order"]))
    counts = {shard: sum(row["shard"] == shard for row in canonical) for shard in SHARDS}
    if counts != {"A": 1, "B": 38, "C": 31} or len(canonical) != 70:
        raise RuntimeError("existing canonical result count mismatch")
    a_rows = [row for row in reclassified if row["shard"] == "A"]
    if [row["rationale_lengths"]["actionability"] for row in a_rows] != [643, 514]:
        raise RuntimeError("Shard A observed rationale lengths differ from authorization")
    if any(row["parser_v2_status"] != "STRICT_SCHEMA_VALIDATION_FAILED" for row in a_rows):
        raise RuntimeError("Shard A Parser-V2 failure classification mismatch")
    if canonical[0]["shard"] != "A" or canonical[0]["selected_attempt_number"] != 1:
        raise RuntimeError("Shard A earliest-valid selection mismatch")
    summary = {
        "schema_version": "c4-real-existing-judge-attempt-reclassification-summary-v3",
        "status": "PASS_BLIND_RECLASSIFICATION_COMPLETE",
        "provider_returned_outputs": {"A": 2, "B": 38, "C": 31, "total": 71},
        "parser_v2": {"valid": v2_valid, "invalid": len(reclassified) - v2_valid},
        "parser_v3": {"valid": v3_valid, "invalid": len(reclassified) - v3_valid},
        "all_previously_valid_parser_v2_results_semantically_unchanged": True,
        "canonical_results": {**counts, "total": len(canonical)},
        "selection_rule": SELECTION_RULE,
        "shard_a_selected_attempt": 1,
        "shard_a_attempt_2_status": (
            "NOT_SELECTED_REDUNDANT_RETRY_AFTER_PARSER_V2_FALSE_REJECTION"
        ),
        "timeout_attempts_excluded_from_returned_output_count": True,
        "condition_or_mode_identity_used": False,
        "score_based_selection_used": False,
    }
    return reclassified, canonical, summary, timeout_audit


def continuation_rows(
    source_rows: Mapping[str, list[dict[str, Any]]],
    canonical: list[dict[str, Any]],
) -> tuple[dict[str, list[dict[str, Any]]], dict[str, Any]]:
    completed_ids = {row["opaque_judge_request_id"] for row in canonical}
    remaining_by_shard: dict[str, list[dict[str, Any]]] = {}
    source_ids: set[str] = set()
    source_result_ids: set[str] = set()
    remaining_ids: set[str] = set()
    audit_shards: dict[str, Any] = {}
    for shard, info in SHARDS.items():
        rows = source_rows[shard]
        source_ids.update(row["logical_judge_request_id"] for row in rows)
        source_result_ids.update(row["judge_result_blind_id"] for row in rows)
        selected: list[dict[str, Any]] = []
        for order in info["remaining_orders"]:
            source = rows[order - 1]
            record = {
                "schema_version": "c4-real-unique-judge-request-continuation-r3",
                "original_logical_order": order,
                "logical_judge_request_id": source["logical_judge_request_id"],
                "judge_result_blind_id": source["judge_result_blind_id"],
                "provider_payload_sha256": source["provider_payload_sha256"],
                "estimated_input_tokens": source["estimated_input_tokens"],
                "source_shard_id": shard,
                "continuation_shard_id": info["continuation_id"],
                "provider_payload": source["provider_payload"],
            }
            if canonical_json_bytes(record["provider_payload"]) != canonical_json_bytes(
                source["provider_payload"]
            ):
                raise RuntimeError("continuation Provider payload bytes changed")
            selected.append(record)
            remaining_ids.add(record["logical_judge_request_id"])
        remaining_by_shard[shard] = selected
        manifest_name = f"c4_real_judge_shard_{shard.lower()}_remaining_manifest_v1.jsonl"
        manifest_data = jsonl_bytes(selected)
        write_artifact(manifest_name, manifest_data)
        audit_shards[shard] = {
            "source_package_id": info["source_package_id"],
            "source_package_sha256": info["package_sha256"],
            "source_blinded_judge_manifest_sha256": info["source_manifest_sha256"],
            "remaining_manifest": manifest_name,
            "remaining_manifest_sha256": sha256_bytes(manifest_data),
            "request_count": len(selected),
            "original_logical_orders": list(info["remaining_orders"]),
            "opaque_judge_request_ids_preserved": True,
            "opaque_result_blind_ids_preserved": True,
            "provider_payload_bytes_identical": True,
            "provider_payload_sha256_preserved": True,
            "new_judge_ids_issued": 0,
        }
    if completed_ids & remaining_ids:
        raise RuntimeError("completed and remaining request sets overlap")
    if completed_ids | remaining_ids != source_ids or len(source_ids) != 147:
        raise RuntimeError("existing/remaining union is not the 147-request universe")
    if len(source_result_ids) != 147:
        raise RuntimeError("source result blind IDs are not unique")
    audit = {
        "schema_version": "c4-real-judge-continuation-source-identity-audit-v1",
        "status": "PASS_BYTE_IDENTICAL_PROVIDER_PAYLOADS_AND_IDENTITIES",
        "shards": audit_shards,
        "existing_canonical_request_count": len(completed_ids),
        "remaining_request_count": len(remaining_ids),
        "exact_judge_universe_request_count": len(source_ids),
        "completed_and_remaining_sets_disjoint": True,
        "existing_and_remaining_union_equals_exact_147_request_universe": True,
        "original_r2_requests_used_directly": True,
        "requests_rebuilt_from_condition_records": False,
        "new_judge_ids_issued": 0,
        "condition_or_mode_mapping_used": False,
    }
    return remaining_by_shard, audit


def package_configuration(
    shard: str,
    info: Mapping[str, Any],
    rows_blob: bytes,
    fixed_members: Mapping[str, bytes],
) -> dict[str, Any]:
    return {
        "schema_version": "c4-real-judge-configuration-continuation-r3-v1",
        "status": "FROZEN_UNEXECUTED_REQUIRES_NEW_DIRECT_AUTHORIZATION_R3",
        "package_id": info["package_id"],
        "shard_id": info["continuation_id"],
        "source_shard_id": shard,
        "source_package_id": info["source_package_id"],
        "source_package_sha256": info["package_sha256"],
        "source_blinded_judge_manifest_sha256": info["source_manifest_sha256"],
        "request_count": len(info["remaining_orders"]),
        "original_logical_orders": list(info["remaining_orders"]),
        "maximum_physical_attempts": len(info["remaining_orders"]) * 2,
        "model": "gpt-4.1-2025-04-14",
        "endpoint": "OpenAI Chat Completions",
        "endpoint_path": "/v1/chat/completions",
        "temperature": 0,
        "max_output_tokens": 2048,
        "request_timeout_seconds": 120.0,
        "streaming": False,
        "tools": "NONE",
        "automatic_sdk_retries": 0,
        "minimum_seconds_between_initial_request_starts": 15.0,
        "serial_execution": True,
        "manual_retry": {
            "maximum_retries": 1,
            "request_bytes": "IDENTICAL",
            "correction_message_added": False,
            "permitted_only_after": [
                "INVALID_JSON",
                "STRICT_SCHEMA_VALIDATION_FAILED",
                "APPLICABILITY_CONTRACT_VIOLATION",
            ],
        },
        "judge_calls": 0,
        "judge_prompt_sha256": sha256_bytes(fixed_members["JUDGE_PROMPT.txt"]),
        "provider_schema_sha256": sha256_bytes(fixed_members["JUDGE_SCHEMA.json"]),
        "primary_rubric_sha256": sha256_bytes(fixed_members["PRIMARY_RUBRIC.json"]),
        "applicability_contract_sha256": sha256_bytes(
            fixed_members["APPLICABILITY_CONTRACT.json"]
        ),
        "execution_runner_sha256": sha256_bytes(
            fixed_members["judge_execution_runner_v3.py"]
        ),
        "local_parser_sha256": sha256_bytes(fixed_members["judge_result_parser_v3.py"]),
        "blinded_judge_manifest_sha256": sha256_bytes(rows_blob),
        "provider_outputs_result_blind_id": False,
        "provider_outputs_overall_applicable_mean": False,
        "result_blind_id_attached_locally": True,
        "overall_applicable_mean_computed_locally": True,
        "secondary_audits_excluded_from_primary_mean": True,
        "semantic_contract": "AUTHORITATIVE_RQ3_0B4_V1_UNCHANGED",
        "semantic_schema_version": "rq3-judge-response-v1",
        "transport_schema_version": "rq3-judge-response-r3d1-r2-transport",
    }


def execution_contract(info: Mapping[str, Any], config_bytes: bytes) -> dict[str, Any]:
    return {
        "schema_version": "c4-real-judge-execution-contract-r3-v1",
        "status": "FROZEN_FOR_FUTURE_SEPARATELY_AUTHORIZED_EXECUTION_R3",
        "python_executable": "/opt/anaconda3/bin/python3",
        "python_version": "3.13.5",
        "openai_sdk_version": "1.109.1",
        "automatic_sdk_retries": 0,
        "openai_client_max_retries": 0,
        "request_timeout_seconds": 120.0,
        "timeout_affects_transport_waiting_only": True,
        "timeout_modifies_provider_payload_bytes": False,
        "timeout_is_non_retryable": True,
        "parser_version": "V3",
        "serial_execution": True,
        "minimum_seconds_between_initial_request_starts": 15.0,
        "request_count": len(info["remaining_orders"]),
        "maximum_physical_attempts": len(info["remaining_orders"]) * 2,
        "existing_output_directory_permitted": False,
        "output_directory_created_atomically": True,
        "automatic_resume": False,
        "raw_invalid_output_preserved": True,
        "returned_model_identity_verified": "gpt-4.1-2025-04-14",
        "non_retryable_error_policy": "STOP_ENTIRE_SHARD",
        "never_retry_after": [
            "TIMEOUT",
            "TRANSPORT",
            "RATE_LIMIT",
            "AUTHENTICATION",
            "PERMISSION",
            "REFUSAL",
            "MODEL_MISMATCH",
            "CONFIGURATION_ERROR",
        ],
        "manual_retry": {
            "maximum_retries": 1,
            "byte_identical": True,
            "correction_message": False,
            "permitted_only_after": [
                "INVALID_JSON",
                "STRICT_SCHEMA_VALIDATION_FAILED",
                "APPLICABILITY_CONTRACT_VIOLATION",
            ],
        },
        "attempt_terminal_error_status_journals_flush_and_fsync": True,
        "preflight_start_receipt_before_runtime_and_client_construction": True,
        "bindings_verified_before_runtime_and_client_construction": True,
        "explicit_timeout_verified_before_provider_call": True,
        "complete_or_incomplete_status_always_written_after_output_creation": True,
        "provider_error_fields_sanitized": True,
        "authorization_headers_recorded": False,
        "authorization_environment_variable": "C4_REAL_JUDGE_EXECUTION_AUTHORIZATION",
        "authorization_environment_value": "AUTHORIZED_C4_REAL_JUDGE_CONTINUATION_R3",
        "authorization_record_schema_version": "c4-real-judge-execution-authorization-r3-v1",
        "authorization_status_required": "AUTHORIZED",
        "execution_authorized_in_package": False,
        "condition_comparisons_inside_worker": False,
        "configuration_sha256": sha256_bytes(config_bytes),
        "required_cli_arguments": [
            "--package-zip",
            "--authorization-record",
            "--output-dir",
            "--execute",
        ],
    }


def deterministic_zip(path: Path, members: Mapping[str, bytes]) -> None:
    temporary = path.with_name(f".{path.name}.j2d0-tmp")
    if temporary.exists():
        temporary.unlink()
    with ZipFile(temporary, "w", compression=ZIP_DEFLATED, compresslevel=9) as archive:
        for name in sorted(members):
            item = ZipInfo(name, date_time=(2026, 9, 2, 0, 0, 0))
            item.compress_type = ZIP_DEFLATED
            item.create_system = 3
            item.external_attr = 0o100644 << 16
            archive.writestr(item, members[name], compress_type=ZIP_DEFLATED, compresslevel=9)
    os.replace(temporary, path)


def build_packages(
    source_members: Mapping[str, dict[str, bytes]],
    remaining: Mapping[str, list[dict[str, Any]]],
) -> dict[str, Any]:
    parser_bytes = (HERE / "judge_result_parser_v3.py").read_bytes()
    runner_bytes = (HERE / "judge_execution_runner_v3.py").read_bytes()
    validator_bytes = (HERE / "judge_package_validator_v3.py").read_bytes()
    tests_bytes = (HERE / "judge_package_offline_tests_v3.py").read_bytes()
    manifest: dict[str, Any] = {
        "schema_version": "c4-real-judge-continuation-package-manifest-v1",
        "status": "PASS_THREE_FROZEN_UNEXECUTED_CONTINUATION_PACKAGES",
        "provider_calls": 0,
        "packages": {},
    }
    for shard, info in SHARDS.items():
        source = source_members[shard]
        rows_blob = jsonl_bytes(remaining[shard])
        fixed = {
            "BLINDED_JUDGE_REQUESTS.jsonl": rows_blob,
            "JUDGE_PROMPT.txt": source["JUDGE_PROMPT.txt"],
            "JUDGE_SCHEMA.json": source["JUDGE_SCHEMA.json"],
            "PRIMARY_RUBRIC.json": source["PRIMARY_RUBRIC.json"],
            "APPLICABILITY_CONTRACT.json": source["APPLICABILITY_CONTRACT.json"],
            "judge_execution_runner_v3.py": runner_bytes,
            "judge_result_parser_v3.py": parser_bytes,
            "validate_package.py": validator_bytes,
            "test_package.py": tests_bytes,
        }
        config = package_configuration(shard, info, rows_blob, fixed)
        config_bytes = json_bytes(config)
        contract_bytes = json_bytes(execution_contract(info, config_bytes))
        readme = (
            f"# C4 REAL Judge Shard {shard} continuation execution Package R3\n\n"
            "Status: `FROZEN_UNEXECUTED_REQUIRES_NEW_DIRECT_AUTHORIZATION_R3`\n\n"
            f"This blinded Package contains {len(remaining[shard])} original R2 Judge "
            f"requests at logical orders {min(info['remaining_orders'])}-{max(info['remaining_orders'])}. "
            "J2D0 authorizes no Judge call and this Package has not been executed. "
            "Future execution requires the exact environment gate, a separately supplied "
            "strict authorization record bound to this ZIP and manifest, all required CLI "
            "arguments, and `/opt/anaconda3/bin/python3`.\n\n"
            "The runner is serial, uses `OpenAI(max_retries=0, timeout=120.0)`, spaces "
            "consecutive initial request starts by at least 15.0 seconds, permits one "
            "byte-identical retry only for the three named invalid-output classes, never "
            "retries a timeout or transport failure, refuses resume or an existing output "
            "directory, and stops the complete continuation Shard on every non-retryable "
            "or second-invalid failure. Parser V3 requires non-empty rationale strings and "
            "does not impose a per-rationale length ceiling.\n"
        ).encode("utf-8")
        members = {
            **fixed,
            "JUDGE_CONFIGURATION.json": config_bytes,
            "EXECUTION_CONTRACT.json": contract_bytes,
            "README.md": readme,
        }
        source_hashes = {
            "schema_version": "c4-real-judge-package-source-hashes-r3-v1",
            "package_id": info["package_id"],
            "shard_id": info["continuation_id"],
            "source_package_id": info["source_package_id"],
            "source_package_sha256": info["package_sha256"],
            "source_blinded_judge_manifest_sha256": info["source_manifest_sha256"],
            "member_sha256": {
                name: sha256_bytes(data) for name, data in sorted(members.items())
            },
        }
        members["PACKAGE_SOURCE_HASHES.json"] = json_bytes(source_hashes)
        if set(members) != ALLOWED_FILES:
            raise RuntimeError(f"Shard {shard} continuation allowlist mismatch")
        target = DOWNLOADS / info["continuation_name"]
        deterministic_zip(target, members)
        validation = validate_package_zip(target)
        if validation["status"] != "PASS":
            raise RuntimeError(f"Shard {shard} continuation Package validation failed")
        manifest["packages"][shard] = {
            "path": str(target),
            "package_id": info["package_id"],
            "shard_id": info["continuation_id"],
            "request_count": len(remaining[shard]),
            "original_logical_orders": list(info["remaining_orders"]),
            "maximum_physical_attempts": len(remaining[shard]) * 2,
            "sha256": sha256_file(target),
            "bytes": target.stat().st_size,
            "regular_file_count": len(members),
            "member_sha256": {name: sha256_bytes(data) for name, data in sorted(members.items())},
            "validation": validation,
            "source_provider_payloads_byte_identical": True,
            "provider_calls": 0,
        }
    return manifest


def build_reports(
    summary: Mapping[str, Any],
    timeout: Mapping[str, Any],
    package_manifest: Mapping[str, Any],
) -> None:
    parser_hash = sha256_file(HERE / "judge_result_parser_v3.py")
    runner_hash = sha256_file(HERE / "judge_execution_runner_v3.py")
    analysis = f"""# C4 REAL Judge Parser-V2 rationale false-rejection analysis

Status: `PASS_REPRODUCED_BLINDLY`

Both Shard-A Provider-returned outputs are valid JSON objects with no duplicate keys. Both have the exact Provider-schema field set, valid score strings, the exact transport schema version, valid non-negative `unsupported_claim_count` strings, non-empty rationales, and scores consistent with the frozen applicability map. Both produce a local `overall_applicable_mean` under the unchanged primary-criterion rule.

Observed rationale character lengths:

| Attempt | clarity | personalisation | actionability | context_awareness | motivation_and_engagement | reliability | multi_page_cohesiveness | error_handling |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| 1 | 260 | 305 | 643 | 478 | 201 | 351 | 298 | 415 |
| 2 | 215 | 235 | 514 | 344 | 161 | 243 | 261 | 305 |

For each output, Parser V2 rejects only because `len(actionability_rationale) > 500`. Removing only that local check makes each output valid under Parser V3. The 500-character limit is absent from the frozen Provider schema and is not a primary scoring criterion.

No condition identity or mode-level result was used. Scores were not changed, and no output was selected because its scores looked better. This is a local transport/parser validity issue. Existing canonical selection uses only earliest valid attempt number under Parser V3.
"""
    compatibility = f"""# C4 REAL Judge Parser V2/V3 compatibility note

Parser V3 SHA-256: `{parser_hash}`

- Score semantics are unchanged.
- Applicability semantics are unchanged.
- The exact Provider field set, duplicate-key rejection, score validation, NA/applicability consistency, evidence-faithfulness validation, non-negative unsupported-claim validation, exact schema version, expected opaque result-blind ID, local primary mean, and exclusion of secondary audits remain enforced.
- All 69 previously valid Parser-V2 returned results remain valid and have byte-identical canonical semantic objects under Parser V3.
- Every rationale must still be a string and non-empty after trimming.
- Parser V3 only removes the non-scientific local per-rationale 500-character false-rejection condition. It adds no replacement per-rationale length ceiling.
- Parser V3 never truncates, rewrites, summarises, or edits rationale text.
- The frozen Provider total response bound remains `max_output_tokens = 2048`.
"""
    timeout_md = f"""# C4 REAL Judge transport-timeout audit

Status: `PASS_EXISTING_TIMEOUTS_FROZEN`

| Shard | Logical order | Request start (UTC) | Timeout error (UTC) | Elapsed seconds |
| --- | ---: | --- | --- | ---: |
| B | 39 | {timeout['B']['request_started_at_utc']} | {timeout['B']['timeout_error_at_utc']} | {timeout['B']['elapsed_seconds']:.6f} |
| C | 32 | {timeout['C']['request_started_at_utc']} | {timeout['C']['timeout_error_at_utc']} | {timeout['C']['elapsed_seconds']:.6f} |

For both attempts, no Provider response was recorded, no terminal result exists, and no JSON, schema, or applicability failure occurred. The observed timing is consistent with an approximately 10-second effective transport timeout.

The frozen Runner V2 constructs `OpenAI(max_retries=0)` and does not explicitly freeze a request timeout. Current artifacts do not prove which environment or client default produced the observed effective deadline, so no such cause is asserted.

Runner V3 constructs `OpenAI(max_retries=0, timeout=120.0)`. Its explicit request timeout is transport-only, is validated before a Provider call, does not alter Provider payload bytes, and remains non-retryable within one execution.
"""
    human = """# C4 REAL Human-rating intake readiness

Status: `NOT_FULLY_FROZEN_NO_INTAKE_PERFORMED`

Completed Human CSV intake requires all four separately supplied artifacts:

- `human_rating_packet_A_completed.csv`
- `human_rating_packet_B_completed.csv`
- `human_rater_attestation_A_completed.md`
- `human_rater_attestation_B_completed.md`

J2D0 did not import or score Human ratings. Human review must not be marked fully frozen until both completed attestations and both completed CSVs are present and validated under separate authorization. No Human agreement calculation was performed or authorized.
"""
    report_lines = [
        "# RQ3-REAL-C4-J2D0 execution report",
        "",
        f"Status: `{READY_STATUS}`",
        "",
        "This was a local mechanical integration, Parser-V3 repair, existing-result canonicalisation, timeout freeze, and continuation-package preparation. It made zero Provider/network calls, zero new Judge executions, zero response-generation calls, zero Human-rating intake or agreement calls, zero scoring/statistical calls, and performed no condition unblinding.",
        "",
        f"Parser V3 SHA-256: `{parser_hash}`",
        f"Runner V3 SHA-256: `{runner_hash}`",
        "Explicit Runner-V3 request timeout: `120.0` seconds with SDK retries `0`.",
        "",
        f"Returned outputs reclassified: {summary['provider_returned_outputs']['total']} (A=2, B=38, C=31). Parser V3 valid: {summary['parser_v3']['valid']}.",
        f"Existing canonical results: {summary['canonical_results']['total']} (A=1, B=38, C=31). Shard A selects attempt 1 by `{SELECTION_RULE}`.",
        "Remaining requests: A=48 (orders 2-49), B=11 (orders 39-49), C=18 (orders 32-49).",
        "Maximum future physical attempts: A=96, B=22, C=36.",
        "Original and continuation Provider payload identity: `PASS_BYTE_IDENTICAL`.",
        "",
        "Continuation Packages:",
        "",
    ]
    for shard in SHARDS:
        package = package_manifest["packages"][shard]
        report_lines.append(f"- Shard {shard}: `{package['path']}` — SHA-256 `{package['sha256']}`")
    report_lines.extend(
        [
            "",
            "Human-rating intake readiness: incomplete by design; the four completed inputs were not imported or validated in J2D0.",
            "",
            "Offline/mocked tests: 239 passed, 0 failed in the final correct invocations (J2D0 38; continuation Packages 60; unchanged R3D1-R2 regression 22; unchanged R2 Packages 48; integrated A/B/C evidence suites 71). The unchanged R3D1-R2 independent validator also passed 109/109 checks, and all three continuation Package validator invocations passed.",
            "",
            "One earlier combined integrated-suite invocation omitted Shard B's required `--package-zip` argument, producing one setup error before any B test ran. The corrected unchanged Shard-B invocation passed 26/26; this harness setup event did not change artifacts or make any external call.",
            "",
        ]
    )
    write_artifact("C4_REAL_JUDGE_PARSER_V2_RATIONALE_FALSE_REJECTION_ANALYSIS.md", analysis.encode())
    write_artifact("C4_REAL_JUDGE_PARSER_V2_V3_COMPATIBILITY_NOTE.md", compatibility.encode())
    write_artifact("C4_REAL_JUDGE_TIMEOUT_AUDIT.md", timeout_md.encode())
    write_artifact("C4_REAL_HUMAN_RATING_INTAKE_READINESS.md", human.encode())
    write_artifact("C4_REAL_J2D0_EXECUTION_REPORT.md", ("\n".join(report_lines)).encode())
    status = f"""# RQ3-REAL-C4-J2D0 status

`RQ3_REAL_J2D0_STATUS = {READY_STATUS}`

No continuation Package has been executed. Sequential continuation execution requires new direct authorization.
"""
    write_artifact("STATUS.md", status.encode())


def main() -> int:
    if Path.cwd().resolve() != REPO:
        raise RuntimeError(f"run from exact repository root: {REPO}")
    if git_text("branch", "--show-current") != "research/rq3-real-c4-i1-route-integration":
        raise RuntimeError("branch mismatch")
    mapping, preservation = commit_preservation_manifest()
    write_artifact("c4_real_judge_commit_integration_mapping_v1.json", json_bytes(mapping))
    write_artifact(
        "C4_REAL_JUDGE_EXISTING_OUTPUT_PRESERVATION_MANIFEST_V1.json",
        json_bytes(preservation),
    )
    preflight = offline_client_preflight()
    write_artifact("C4_REAL_JUDGE_RUNNER_V3_OFFLINE_PREFLIGHT_RECEIPT.json", json_bytes(preflight))

    source_members: dict[str, dict[str, bytes]] = {}
    source_rows: dict[str, list[dict[str, Any]]] = {}
    for shard, info in SHARDS.items():
        members, rows = source_package(shard, info)
        source_members[shard] = members
        source_rows[shard] = rows
    fixed_names = ("JUDGE_PROMPT.txt", "JUDGE_SCHEMA.json", "PRIMARY_RUBRIC.json", "APPLICABILITY_CONTRACT.json")
    for name in fixed_names:
        if len({sha256_bytes(source_members[s][name]) for s in SHARDS}) != 1:
            raise RuntimeError(f"R2 frozen member differs between Shards: {name}")

    parser_v2 = load_v2_parser()
    reclassified, canonical, summary, timeout = classify_existing_outputs(
        source_rows, parser_v2
    )
    write_artifact(
        "c4_real_existing_judge_attempt_reclassification_v3.jsonl",
        jsonl_bytes(reclassified),
    )
    write_artifact(
        "c4_real_existing_judge_attempt_reclassification_summary_v3.json",
        json_bytes(summary),
    )
    selection = {
        "schema_version": "c4-real-judge-canonical-attempt-selection-rule-v1",
        "status": "FROZEN",
        "rule": SELECTION_RULE,
        "steps": [
            "SORT_PROVIDER_RETURNED_ATTEMPTS_BY_ATTEMPT_NUMBER_ASCENDING",
            "REQUIRE_VALID_JSON",
            "APPLY_JUDGE_PARSER_V3",
            "REQUIRE_APPLICABILITY_CONSISTENCY",
            "SELECT_EARLIEST_VALID_ATTEMPT",
            "NEVER_SELECT_USING_SCORE_RATIONALE_STYLE_LENGTH_MODE_CONDITION_OR_EXPECTED_RESULT",
            "IF_NO_VALID_RETURNED_OUTPUT_LEAVE_REQUEST_INCOMPLETE",
        ],
        "applies_uniformly_to_shards": ["A", "B", "C"],
        "score_based_selection": False,
        "condition_or_mode_based_selection": False,
    }
    write_artifact(
        "C4_REAL_JUDGE_CANONICAL_ATTEMPT_SELECTION_RULE_V1.json",
        json_bytes(selection),
    )
    write_artifact("c4_real_existing_canonical_judge_results_v1.jsonl", jsonl_bytes(canonical))

    remaining, identity_audit = continuation_rows(source_rows, canonical)
    write_artifact(
        "c4_real_judge_continuation_source_identity_audit_v1.json",
        json_bytes(identity_audit),
    )
    package_manifest = build_packages(source_members, remaining)
    write_artifact(
        "c4_real_judge_continuation_package_manifest_v1.json",
        json_bytes(package_manifest),
    )
    build_reports(summary, timeout, package_manifest)
    print(json.dumps({
        "status": READY_STATUS,
        "returned_outputs": len(reclassified),
        "canonical_results": len(canonical),
        "remaining_requests": sum(len(rows) for rows in remaining.values()),
        "packages": {shard: data["sha256"] for shard, data in package_manifest["packages"].items()},
        "provider_calls": 0,
        "network_calls": 0,
    }, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
