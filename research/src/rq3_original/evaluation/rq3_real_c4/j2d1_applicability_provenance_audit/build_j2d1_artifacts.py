#!/usr/bin/env python3
"""Build the offline RQ3-REAL-C4-J2D1 audit and blind review artifacts.

This builder is deliberately non-executing: it does not import a Provider SDK,
does not call a model, does not score a response, and does not read Human
rating content.  The only Provider-returned fields inspected are the two
order-40 outputs expressly authorised for applicability-failure reproduction.
"""

from __future__ import annotations

import ast
from collections import Counter, defaultdict
import csv
import hashlib
import hmac
import io
import json
import os
from pathlib import Path
import re
import subprocess
import sys
from typing import Any, Iterable, Mapping, Sequence

from jsonschema import Draft202012Validator

_SCRIPT_HERE = Path(__file__).resolve().parent
_SCRIPT_ROOT = _SCRIPT_HERE.parents[2]
if str(_SCRIPT_ROOT) not in sys.path:
    sys.path.insert(0, str(_SCRIPT_ROOT))

from evaluation.rq3_real_c4.j2d0_judge_continuation_repair.judge_result_parser_v3 import (
    JudgeResultError,
    PRIMARY_CRITERIA,
    SCORE_FIELDS,
    parse_judge_result,
)


HERE = _SCRIPT_HERE
ROOT = _SCRIPT_ROOT
EVALUATION = ROOT / "evaluation"
C4 = EVALUATION / "rq3_real_c4"
I0 = C4 / "i0_integration"
I1 = C4 / "i1_route_integration"
TRACK_D = C4 / "track_d_dataset"
J2D0 = C4 / "j2d0_judge_continuation_repair"
J3B = C4 / "j3b_judge_continuation_b"
J3C = C4 / "j3c_judge_continuation_c"
RUBRIC_DIR = EVALUATION / "rq3_v2" / "rq3_0b4_evaluation_protocol"
RESTRICTED = I1 / "restricted_internal"

STARTING_HEAD = "3e125353993ad4813e96ed6690e708f932da0d29"
AUDIT_PARENT_HEAD = "8de7c8c37be6bbeac31d0047c3da7a0bd67fad3f"
EXPECTED_BRANCH = "research/rq3-real-c4-i1-route-integration"
INTEGRATIONS = (
    (
        1,
        "ace2cf9bc8874808050380e529afb7af80a0865c",
        "b992cdbaadcad939c045c814894b52c16b316b2f",
        "Judge-B historical billing failure",
    ),
    (
        2,
        "3751ea31f9dadf716063235088320f7d307628e9",
        "57435458f7fcdc24742677b57408f8c82e68578f",
        "Judge-B successful billing-recovery execution",
    ),
    (
        3,
        "53f33526ad51b08af7d4af35160a98bf5c009671",
        "44bd0bfb6a3d72afc01fcc312f96769a1a1b49c9",
        "Judge-C historical billing failure",
    ),
    (
        4,
        "90cc2059c1cbe7a2205077ff1cb7ffb97689603f",
        "8de7c8c37be6bbeac31d0047c3da7a0bd67fad3f",
        "Judge-C partial V2 execution",
    ),
)
EXPECTED_PLANNING_FALSE_NEGATIVES = {
    "U013",
    "U015",
    "U016",
    "U017",
    "U021",
    "U023",
    "U058",
}
EXPECTED_PLANNING_FALSE_POSITIVES = {"U029"}
PAGE_NAMES = {"overview", "lecture", "resources", "debate", "reflection"}
CONDITIONAL_CRITERIA = (
    "PERSONALISATION",
    "ACTIONABILITY",
    "MOTIVATION_AND_ENGAGEMENT",
    "MULTI_PAGE_COHESIVENESS",
    "ERROR_HANDLING",
)

SOURCE_PATHS = {
    "frozen_62_scenario_dataset": Path(
        "/Users/liuming/Downloads/duteaiapp_cfull_semantic_integrated_v1_副本3/"
        "evaluation/unified_benchmark_scenarios.jsonl"
    ),
    "scenario_identity": TRACK_D / "final_62_scenario_identity_v1.json",
    "memory_registry": TRACK_D / "memory_scenario_registry_v1.csv",
    "semantic_input_manifest": I0 / "c4_real_p3_route_input_manifest_v1.jsonl",
    "clarification_decisions": I0 / "c4_real_clarification_decisions_frozen_v1.csv",
    "applicability_maps": I1 / "c4_real_condition_applicability_maps_frozen_v1.jsonl",
    "mechanism_records": I1 / "c4_real_condition_mechanism_records_frozen_v1.jsonl",
    "dashboard_records": I1 / "c4_real_condition_dashboard_evidence_frozen_v1.jsonl",
    "rag_records": I1 / "c4_real_condition_rag_results_frozen_v1.jsonl",
    "memory_records": I1 / "c4_real_condition_memory_results_frozen_v1.jsonl",
    "planner_records": I1 / "c4_real_condition_planner_results_frozen_v1.jsonl",
    "applicability_contract": RUBRIC_DIR / "rq3_dimension_applicability_v1.json",
    "rubric": RUBRIC_DIR / "rq3_primary_eight_criterion_rubric_v1.json",
    "i1_builder": I1 / "build_i1_artifacts.py",
    "judge_c_manifest": J2D0 / "c4_real_judge_shard_c_remaining_manifest_v1.jsonl",
    "judge_c_attempts_v2": J3C / "execution_output_v2/JUDGE_ATTEMPT_JOURNAL.jsonl",
    "judge_c_terminals_v2": J3C / "execution_output_v2/JUDGE_TERMINAL_JOURNAL.jsonl",
    "judge_b_terminals_v2": J3B / "execution_output_v2/JUDGE_TERMINAL_JOURNAL.jsonl",
    "existing_canonical_judge_results": J2D0 / "c4_real_existing_canonical_judge_results_v1.jsonl",
    "judge_mapping": RESTRICTED / "c4_real_condition_to_unique_judge_request_mapping_v1.csv",
    "human_mapping": RESTRICTED / "c4_real_human_rating_item_to_condition_mapping_frozen_r2.csv",
    "hmac_key": RESTRICTED / "c4_real_i1_blinding_hmac_key.bin",
}
EXPECTED_SOURCE_HASHES = {
    "frozen_62_scenario_dataset": "2df88a153101b39872154ed1ef339d6639e3ea28fac7df0eb42dd8bc9d998ce4",
    "scenario_identity": "17e9d3a34c2d080a855246fe05b7150c9e7c5b2a64b9fcc7e47c043e9ff82c9a",
    "memory_registry": "a058780f81a46997d545f364f44eb9acba0c564bfb684870c7ddc000343d1d5c",
    "semantic_input_manifest": "b042e454a9508fac4348ce7ba1f2595ca2882227098696589c5e4e214710e326",
    "applicability_maps": "1f5b159b3d80506c32265624a8f4e5866af4dba996dd0f62abf53dff93f31084",
    "judge_mapping": "0102f1686c27865c57a7544d71fa8b0bdc023af30ad0a65e094f4d0dfccfd6c7",
    "human_mapping": "cbad7ed6beace28dcdfc7e48de13c4ac533e20e614faad5aacba7970bead6287",
    "hmac_key": "REDACTED_AUTHENTICATION_KEY",
}

HUMAN_SOURCES = (
    Path("/Users/liuming/Downloads/human_rating_packet_A_completed.csv"),
    Path("/Users/liuming/Downloads/human_rating_packet_B_completed.csv"),
    Path("/Users/liuming/Downloads/human_rater_attestation_A_completed.md"),
    Path("/Users/liuming/Downloads/human_rater_attestation_B_completed.md"),
)


def require(condition: bool, message: str) -> None:
    if not condition:
        raise RuntimeError(message)


def sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def canonical_json_bytes(value: Any) -> bytes:
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    ).encode("utf-8")


def load_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def load_jsonl(path: Path) -> list[dict[str, Any]]:
    return [
        json.loads(line)
        for line in path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]


def jsonl_lines(path: Path) -> list[str]:
    return [line for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def projected_jsonl_string_field(path: Path, field: str) -> list[str]:
    """Project one simple top-level string without decoding unrelated fields.

    This is used for Judge result files so score and rationale values are not
    deserialised during preservation or identity-impact analysis.
    """

    pattern = re.compile(rf'"{re.escape(field)}"\s*:\s*"([^"\\]+)"')
    output = []
    for line in jsonl_lines(path):
        matches = pattern.findall(line)
        require(len(matches) == 1, f"expected one top-level {field} projection")
        output.append(matches[0])
    return output


def load_csv(path: Path) -> list[dict[str, str]]:
    with path.open(encoding="utf-8", newline="") as handle:
        return list(csv.DictReader(handle))


def json_text(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n"


def write_text(path: Path, value: str) -> None:
    path.write_text(value, encoding="utf-8", newline="\n")


def write_json(path: Path, value: Any) -> None:
    write_text(path, json_text(value))


def csv_bytes(fieldnames: Sequence[str], rows: Iterable[Mapping[str, Any]]) -> bytes:
    buffer = io.StringIO(newline="")
    writer = csv.DictWriter(buffer, fieldnames=fieldnames, lineterminator="\n")
    writer.writeheader()
    for row in rows:
        writer.writerow({name: row.get(name, "") for name in fieldnames})
    return buffer.getvalue().encode("utf-8")


def write_csv(path: Path, fieldnames: Sequence[str], rows: Iterable[Mapping[str, Any]]) -> None:
    path.write_bytes(csv_bytes(fieldnames, rows))


def git(*args: str) -> str:
    result = subprocess.run(
        ["git", *args],
        cwd=ROOT,
        check=True,
        capture_output=True,
        text=True,
    )
    return result.stdout.strip()


def verify_sources() -> dict[str, dict[str, Any]]:
    require(ROOT == Path("/Users/liuming/Downloads/rq2_v2_parallel/rq3-real-c4-i1-route-integration"), "wrong working tree")
    require(git("branch", "--show-current") == EXPECTED_BRANCH, "wrong branch")
    require(git("merge-base", "--is-ancestor", AUDIT_PARENT_HEAD, "HEAD") == "", "audit parent is not an ancestor")
    for name, path in SOURCE_PATHS.items():
        require(path.is_file(), f"missing source: {name}")
    require(SOURCE_PATHS["hmac_key"].stat().st_size == 32, "HMAC key is not 32 bytes")
    hashes = {name: sha256_file(path) for name, path in SOURCE_PATHS.items()}
    for name, expected in EXPECTED_SOURCE_HASHES.items():
        require(hashes[name] == expected, f"source hash mismatch: {name}")
    return {
        name: {
            "path": (
                str(path.relative_to(ROOT))
                if path.is_relative_to(ROOT)
                else path.name
            ),
            "sha256": hashes[name],
            "byte_count": path.stat().st_size,
        }
        for name, path in SOURCE_PATHS.items()
        if name != "hmac_key"
    }


def normalise_history(value: Any) -> list[Any]:
    if isinstance(value, str):
        decoded = json.loads(value)
        require(isinstance(decoded, list), "visible history string did not decode to a list")
        return decoded
    require(isinstance(value, list), "visible history is not a list")
    return value


def page_candidates(value: Mapping[str, Any]) -> list[str]:
    pages = [str(value["current_page"])]
    context = value["dashboard_context"]
    if isinstance(context, Mapping):
        for key in context:
            if str(key).casefold() in PAGE_NAMES:
                candidate = str(key).title()
                if candidate not in pages:
                    pages.append(candidate)
    return pages


def source_function_identity(path: Path, function_name: str) -> dict[str, Any]:
    raw = path.read_bytes()
    text = raw.decode("utf-8")
    tree = ast.parse(text)
    node = next(
        item
        for item in tree.body
        if isinstance(item, (ast.FunctionDef, ast.AsyncFunctionDef))
        and item.name == function_name
    )
    lines = text.splitlines(keepends=True)
    function_bytes = "".join(lines[node.lineno - 1 : node.end_lineno]).encode("utf-8")
    return {
        "path": str(path.relative_to(ROOT)),
        "full_file_sha256": sha256_bytes(raw),
        "function_name": function_name,
        "line_start": node.lineno,
        "line_end": node.end_lineno,
        "exact_function_source_sha256": sha256_bytes(function_bytes),
    }


def verify_integrations() -> dict[str, Any]:
    mappings = []
    previous = STARTING_HEAD
    for order, original, picked, label in INTEGRATIONS:
        require(git("rev-parse", f"{picked}^") == previous, f"integration parent mismatch at {order}")
        require(git("show", "-s", "--format=%s", original) == git("show", "-s", "--format=%s", picked), f"subject mismatch at {order}")
        original_patch = git("show", "--pretty=format:", "--binary", original)
        picked_patch = git("show", "--pretty=format:", "--binary", picked)
        require(original_patch == picked_patch, f"cherry-pick patch differs at {order}")
        mappings.append(
            {
                "order": order,
                "history": label,
                "original_commit": original,
                "cherry_picked_commit": picked,
                "cherry_picked_parent": previous,
                "patch_byte_identical": True,
                "conflict_resolution": "NONE",
            }
        )
        previous = picked
    require(previous == AUDIT_PARENT_HEAD, "unexpected integration head")
    return {
        "starting_head": STARTING_HEAD,
        "audit_parent_head": AUDIT_PARENT_HEAD,
        "exact_order_verified": True,
        "conflicts": 0,
        "mappings": mappings,
    }


def verify_judge_preservation() -> dict[str, Any]:
    protected_paths = (
        "evaluation/rq3_real_c4/j2a_judge_shard_a",
        "evaluation/rq3_real_c4/j2b_judge_shard_b",
        "evaluation/rq3_real_c4/j2c_judge_shard_c",
        "evaluation/rq3_real_c4/j2d0_judge_continuation_repair",
    )
    tree_checks = []
    for path in protected_paths:
        before = git("rev-parse", f"{STARTING_HEAD}:{path}")
        after = git("rev-parse", f"HEAD:{path}")
        require(before == after, f"protected Judge tree changed: {path}")
        tree_checks.append({"path": path, "baseline_tree": before, "current_tree": after, "byte_identical": True})

    integrated_tree_sources = (
        (
            "evaluation/rq3_real_c4/j3b_judge_continuation_b",
            "3751ea31f9dadf716063235088320f7d307628e9",
        ),
        (
            "evaluation/rq3_real_c4/j3c_judge_continuation_c",
            "90cc2059c1cbe7a2205077ff1cb7ffb97689603f",
        ),
    )
    for path, source_commit in integrated_tree_sources:
        before = git("rev-parse", f"{source_commit}:{path}")
        after = git("rev-parse", f"HEAD:{path}")
        require(before == after, f"integrated Judge tree differs: {path}")
        tree_checks.append({"path": path, "source_tree": before, "current_tree": after, "byte_identical": True})

    canonical_shards = projected_jsonl_string_field(
        SOURCE_PATHS["existing_canonical_judge_results"], "shard"
    )
    canonical_counts = Counter(canonical_shards)
    require(canonical_counts == Counter({"A": 1, "B": 38, "C": 31}), "J2D0 canonical counts changed")
    b_audit = load_json(J3B / "judge_continuation_execution_audit_v2.json")
    c_audit = load_json(J3C / "judge_continuation_execution_audit_v2.json")
    b_terminal_hash = sha256_file(SOURCE_PATHS["judge_b_terminals_v2"])
    c_attempt_hash = sha256_file(SOURCE_PATHS["judge_c_attempts_v2"])
    c_terminal_hash = sha256_file(SOURCE_PATHS["judge_c_terminals_v2"])
    require(b_terminal_hash == "c7cdcb0124aaa1a1f2137f2e17dac48c075cc1c888fbe92305bcf6f90642a268", "Judge-B terminal hash changed")
    require(b_audit["hashes"]["parsed_result_set_v2_sha256"] == "b51928e34e693464cf3dc421404108fb2ea160f2b2bff723054c704f50c9865b", "Judge-B result-set hash changed")
    require(c_attempt_hash == "8d9877e5744b605282b367209bc8cc9fbb1f318fb863b0f4e77cb11a2268943b", "Judge-C attempt hash changed")
    require(c_terminal_hash == "03560d2a8d5a9c2a39d15442eb6c2648376ffa125e375db1cd389fa7798a6de6", "Judge-C terminal hash changed")
    require(c_audit["hashes"]["parsed_result_set_sha256"] == "9f2615b5913e6fa32be3b942446440b60301c3191d3ba6db9b58224dc0e946ff", "Judge-C result-set hash changed")
    require(b_audit["execution_v2"]["valid_terminal_count"] == 11, "Judge-B terminal count changed")
    require(c_audit["result_counts"]["valid_judge_results"] == 8, "Judge-C terminal count changed")
    require(c_audit["execution_summary"]["physical_attempts"] == 10, "Judge-C attempt count changed")
    require(c_audit["execution_summary"]["later_unattempted_requests"] == 9, "Judge-C unattempted count changed")
    return {
        "status": "PASS_ALL_ORIGINAL_JUDGE_ARTIFACTS_BYTE_IDENTICAL",
        "tree_identity_checks": tree_checks,
        "j2d0_canonical": {
            "shard_counts": dict(sorted(canonical_counts.items())),
            "total": len(canonical_shards),
        },
        "judge_b_v2": {
            "scientific_source": "execution_output_v2",
            "valid_results": 11,
            "request_count": 11,
            "terminal_journal_sha256": b_terminal_hash,
            "parsed_result_set_sha256": b_audit["hashes"]["parsed_result_set_v2_sha256"],
        },
        "judge_c_v2": {
            "valid_original_logical_orders": "32-39",
            "valid_results": 8,
            "physical_attempts": 10,
            "order_40_returned_outputs": 2,
            "order_40_failure": "APPLICABILITY_CONTRACT_VIOLATION",
            "unattempted_original_logical_orders": "41-49",
            "attempt_journal_sha256": c_attempt_hash,
            "terminal_journal_sha256": c_terminal_hash,
            "parsed_result_set_sha256": c_audit["hashes"]["parsed_result_set_sha256"],
        },
        "provisional_preserved_result_counts": {"A": 1, "B": 49, "C": 39, "total": 89},
        "finality": "PRESERVED_NOT_DECLARED_FINAL_PENDING_APPLICABILITY_REVIEW_AND_REPAIR",
        "score_or_rationale_analysis_performed": False,
    }


def extract_blind_request(prompt: str) -> dict[str, Any]:
    begin = "BEGIN_BLIND_JUDGE_REQUEST_JSON\n"
    end = "\nEND_BLIND_JUDGE_REQUEST_JSON"
    require(prompt.count(begin) == 1 and prompt.count(end) == 1, "blind request markers changed")
    payload = prompt.split(begin, 1)[1].split(end, 1)[0]
    value = json.loads(payload)
    require(isinstance(value, dict), "blind request is not an object")
    return value


def reproduce_order_40() -> dict[str, Any]:
    request_lines = [
        line
        for line in jsonl_lines(SOURCE_PATHS["judge_c_manifest"])
        if re.search(r'"original_logical_order"\s*:\s*40(?:[,}])', line)
    ]
    require(len(request_lines) == 1, "order-40 frozen request population changed")
    request_row = json.loads(request_lines[0])
    payload = request_row["provider_payload"]
    require(len(payload["messages"]) == 1 and payload["messages"][0]["role"] == "system", "order-40 message envelope changed")
    blind = extract_blind_request(payload["messages"][0]["content"])
    expected_map = {
        "ACTIONABILITY": False,
        "CLARITY": True,
        "PERSONALISATION": True,
        "CONTEXT_AWARENESS": True,
        "MOTIVATION_AND_ENGAGEMENT": True,
        "RELIABILITY": True,
        "MULTI_PAGE_COHESIVENESS": True,
        "ERROR_HANDLING": True,
    }
    require(blind["student_query"] == "How can I perform better in this aspect?", "order-40 query changed")
    require(blind["frozen_applicability_map"]["criteria"] == expected_map, "order-40 applicability changed")
    schema = payload["response_format"]["json_schema"]["schema"]
    validator = Draft202012Validator(schema)
    attempt_lines = [
        line
        for line in jsonl_lines(SOURCE_PATHS["judge_c_attempts_v2"])
        if re.search(r'"logical_order"\s*:\s*40(?:[,}])', line)
        and re.search(r'"event"\s*:\s*"ATTEMPT_RETURNED"', line)
    ]
    attempts = [json.loads(line) for line in attempt_lines]
    require([row["attempt_number"] for row in attempts] == [1, 2], "order-40 attempts changed")
    findings = []
    exact_error = "APPLICABILITY_CONTRACT_VIOLATION: actionability must be NA"
    for row in attempts:
        raw = row["raw_response_content"]
        decoded = json.loads(raw)
        schema_errors = list(validator.iter_errors(decoded))
        require(not schema_errors, "order-40 output fails Provider schema")
        require(decoded["actionability"] == "3", "order-40 actionability token changed")
        parser_error = None
        try:
            parse_judge_result(
                raw,
                blind["frozen_applicability_map"],
                expected_judge_result_blind_id=request_row["judge_result_blind_id"],
            )
        except JudgeResultError as exc:
            parser_error = str(exc)
        require(parser_error == exact_error, "unexpected Parser-V3 failure")
        require(row["failure_code"] == "APPLICABILITY_CONTRACT_VIOLATION", "journal failure code changed")
        require(row["finish_reason"] == "stop", "Provider did not return normally")
        require(bool(row["provider_response_id"]) and bool(row["returned_model"]), "Provider metadata missing")
        applicable_fields = [
            SCORE_FIELDS[name]
            for name in PRIMARY_CRITERIA
            if blind["frozen_applicability_map"]["criteria"][name]
        ]
        currently_applicable_numeric = all(decoded[field] in {"1", "2", "3", "4", "5"} for field in applicable_fields)
        findings.append(
            {
                "attempt_number": row["attempt_number"],
                "raw_output_sha256": sha256_bytes(raw.encode("utf-8")),
                "provider_schema_json_valid": True,
                "provider_schema_valid": True,
                "actionability_token": "3",
                "parser_v3_error": parser_error,
                "finish_reason": "stop",
                "provider_response_received": True,
                "currently_applicable_primary_fields_numeric": currently_applicable_numeric,
                "currently_applicable_primary_field_count": len(applicable_fields),
            }
        )
    require(findings[0]["currently_applicable_primary_fields_numeric"], "attempt 1 lacks numeric applicable fields")
    return {
        "status": "REPRODUCED_WITHOUT_PROVIDER_CALL_OR_CANONICAL_RESULT",
        "original_logical_order": 40,
        "logical_judge_request_id": request_row["logical_judge_request_id"],
        "judge_result_blind_id": request_row["judge_result_blind_id"],
        "provider_payload_sha256": request_row["provider_payload_sha256"],
        "student_query": blind["student_query"],
        "frozen_applicability_criteria": expected_map,
        "attempts": findings,
        "absence_of_other_failure_classes": {
            "provider_error": True,
            "timeout": True,
            "invalid_json": True,
            "outer_schema_error": True,
            "refusal": True,
            "returned_model_error": True,
        },
        "canonical_result_created": False,
        "score_preference_evaluated": False,
    }


def error_reason_records(
    applicability_rows: Sequence[Mapping[str, Any]],
    clarification_by_scenario: Mapping[str, Mapping[str, str]],
    dashboard_by_key: Mapping[tuple[str, str], Mapping[str, Any]],
    rag_by_key: Mapping[tuple[str, str], Mapping[str, Any]],
    memory_by_key: Mapping[tuple[str, str], Mapping[str, Any]],
    planner_by_key: Mapping[tuple[str, str], Mapping[str, Any]],
) -> tuple[list[dict[str, Any]], dict[tuple[str, str], dict[str, Any]]]:
    records = []
    by_key: dict[tuple[str, str], dict[str, Any]] = {}
    for current in applicability_rows:
        sid, mode = str(current["scenario_id"]), str(current["mode"])
        key = (sid, mode)
        dashboard = dashboard_by_key[key]
        rag = rag_by_key[key]
        memory = memory_by_key[key]
        planner = planner_by_key[key]
        reasons = []
        ambiguity = clarification_by_scenario[sid]["dialogue_action"] != "ANSWER"
        if ambiguity:
            reasons.append("FROZEN_CLARIFICATION_REQUIRED")
        dashboard_empty = bool(
            dashboard["activation"]
            and dashboard["status"] == "FROZEN_TYPED_EMPTY_OUTPUT_LEVEL_PACK"
        )
        if dashboard_empty:
            reasons.append("DASHBOARD_TYPED_EMPTY")
        rag_no_result = bool(rag["activation"] and rag["status"] == "NO_RESULT")
        if rag_no_result:
            reasons.append("RAG_NO_RESULT")
        memory_no_match = bool(memory["activation"] and memory["status"] == "NO_MATCH")
        if memory_no_match:
            reasons.append("MEMORY_NO_MATCH")
        planner_insufficient = bool(
            planner["activation"] and planner["status"] == "INSUFFICIENT_EVIDENCE"
        )
        if planner_insufficient:
            reasons.append("PLANNER_INSUFFICIENT_EVIDENCE")
        planner_conflict = bool(
            planner["activation"] and planner["status"] == "UNSUPPORTED_OR_INCONSISTENT"
        )
        if planner_conflict:
            reasons.append("PLANNER_EVIDENCE_CONFLICT")
        bounded_metadata = bool(
            rag["activation"]
            and rag["result"]
            and any(
                source["evidence_strength"] in {"TITLE_AND_METADATA_ONLY", "LINK_ONLY"}
                for source in rag["result"]["sources"]
            )
        )
        if bounded_metadata:
            reasons.append("RAG_METADATA_OR_LINK_ONLY_BOUNDARY")
        draft = bool(reasons)
        current_value = bool(current["frozen_applicability_map"]["criteria"]["ERROR_HANDLING"])
        record = {
            "scenario_id": sid,
            "mode": mode,
            "mechanical_reason_flags": {
                "ambiguity_relevant": ambiguity,
                "dashboard_typed_empty": dashboard_empty,
                "rag_no_result": rag_no_result,
                "memory_no_match": memory_no_match,
                "planner_insufficiency": planner_insufficient,
                "planner_conflict": planner_conflict,
                "bounded_metadata_or_link_only_evidence": bounded_metadata,
            },
            "mechanical_reason_codes": reasons,
            "current_error_handling_applicable": current_value,
            "draft_error_handling_applicable": draft,
            "discrepancy": (
                "FALSE_POSITIVE_CURRENT_TRUE_WITHOUT_REASON"
                if current_value and not draft
                else "FALSE_NEGATIVE_CURRENT_FALSE_WITH_REASON"
                if draft and not current_value
                else "NONE"
            ),
            "draft_only_not_a_corrected_map": True,
        }
        records.append(record)
        by_key[key] = record
    return records, by_key


def reviewer_definitions() -> dict[str, dict[str, str]]:
    rubric = load_json(SOURCE_PATHS["rubric"])
    wanted = {
        row["criterion_name"]: {
            "definition": row["original_meaning_preserved"],
            "source_na_rule": row["na_rule"],
        }
        for row in rubric["criteria"]
        if row["criterion_name"] in CONDITIONAL_CRITERIA
    }
    operational = {
        "PERSONALISATION": "Answer YES when student-specific data, context, preferences, constraints, visible prior information, or relevant long-term Memory is genuinely relevant. Answer NO only when none is relevant.",
        "ACTIONABILITY": "Answer YES when the student's request genuinely calls for advice, a plan, strategies, or next steps. Decide independently of every predicted route and whether Planning was enabled or called. Answer NO only when advice or Planning is not genuinely needed.",
        "MOTIVATION_AND_ENGAGEMENT": "Answer YES when student-facing motivational support is appropriate. Answer NO only when such support is not appropriate; poor tone could never itself make the criterion non-applicable.",
        "MULTI_PAGE_COHESIVENESS": "List every materially involved visible LAD page. The criterion is applicable when at least two distinct listed pages are material; page availability alone does not establish materiality.",
    }
    for name, rule in operational.items():
        wanted[name]["response_blind_reviewer_rule"] = rule
    return wanted


def build_audits(source_manifest: Mapping[str, Any]) -> dict[str, Any]:
    identity_document = load_json(SOURCE_PATHS["scenario_identity"])
    identity_rows = identity_document["rows"]
    identities = {str(row["scenario_id"]): row for row in identity_rows}
    inputs = {
        str(row["scenario_id"]): row["semantic_input"]
        for row in load_jsonl(SOURCE_PATHS["semantic_input_manifest"])
    }
    memory_registry = {row["unified_scenario_id"]: row for row in load_csv(SOURCE_PATHS["memory_registry"])}
    persistent_scenarios = {
        sid
        for sid, row in memory_registry.items()
        if row["persistent_replay_eligible"] == "YES"
    }
    applicability_rows = load_jsonl(SOURCE_PATHS["applicability_maps"])
    require(len(identity_rows) == 62 and len(inputs) == 62 and len(applicability_rows) == 558, "population mismatch")
    current_by_scenario: dict[str, Mapping[str, Any]] = {}
    for row in applicability_rows:
        sid = str(row["scenario_id"])
        if sid in current_by_scenario:
            for name in (
                "student_specific_data_relevant",
                "long_term_memory_relevant",
                "request_requires_advice",
                "gold_planning_required",
                "student_facing_support_appropriate",
                "material_lad_pages",
            ):
                require(row["source_metadata"][name] == current_by_scenario[sid]["source_metadata"][name], f"scenario-level metadata varies: {sid} {name}")
        else:
            current_by_scenario[sid] = row

    clarification_rows = load_csv(SOURCE_PATHS["clarification_decisions"])
    clarification_by_scenario = {row["scenario_id"]: row for row in clarification_rows}
    require(len(clarification_by_scenario) == 62, "clarification population mismatch")
    dashboard_by_key = {(row["scenario_id"], row["mode"]): row for row in load_jsonl(SOURCE_PATHS["dashboard_records"])}
    rag_by_key = {(row["scenario_id"], row["mode"]): row for row in load_jsonl(SOURCE_PATHS["rag_records"])}
    memory_by_key = {(row["scenario_id"], row["mode"]): row for row in load_jsonl(SOURCE_PATHS["memory_records"])}
    planner_by_key = {(row["scenario_id"], row["mode"]): row for row in load_jsonl(SOURCE_PATHS["planner_records"])}
    error_records, error_by_key = error_reason_records(
        applicability_rows,
        clarification_by_scenario,
        dashboard_by_key,
        rag_by_key,
        memory_by_key,
        planner_by_key,
    )

    scenario_rows = []
    scenario_drafts: dict[str, dict[str, Any]] = {}
    planning_false_negatives: set[str] = set()
    planning_false_positives: set[str] = set()
    long_memory_disagreements: set[str] = set()
    personalisation_changes: set[str] = set()
    multi_page_review: set[str] = set()
    for sid in sorted(identities):
        identity = identities[sid]
        value = inputs[sid]
        history = normalise_history(value["visible_conversation_history"])
        candidates = page_candidates(value)
        current = current_by_scenario[sid]
        metadata = current["source_metadata"]
        criteria = current["frozen_applicability_map"]["criteria"]
        reference_planning = "recommendation_planning" in identity["required_capabilities"]
        draft_student_specific = bool(value["dashboard_context"]) or bool(history)
        draft_long_memory = sid in persistent_scenarios
        draft_personalisation = draft_student_specific or draft_long_memory
        draft_actionability = reference_planning
        draft_motivation = True
        draft_multi_page = len(set(candidates)) > 1
        if not criteria["ACTIONABILITY"] and reference_planning:
            planning_false_negatives.add(sid)
        if criteria["ACTIONABILITY"] and not reference_planning:
            planning_false_positives.add(sid)
        if bool(metadata["long_term_memory_relevant"]) != draft_long_memory:
            long_memory_disagreements.add(sid)
        if bool(criteria["PERSONALISATION"]) != draft_personalisation:
            personalisation_changes.add(sid)
        if len(candidates) > 1:
            multi_page_review.add(sid)
        scenario_drafts[sid] = {
            "PERSONALISATION": draft_personalisation,
            "ACTIONABILITY": draft_actionability,
            "MOTIVATION_AND_ENGAGEMENT": draft_motivation,
            "MULTI_PAGE_COHESIVENESS": draft_multi_page,
        }
        planning_assessment = (
            "REFERENCE_PLANNING_LISTED_CURRENT_ACTIONABILITY_FALSE"
            if reference_planning and not criteria["ACTIONABILITY"]
            else "REFERENCE_PLANNING_NOT_LISTED_CURRENT_ACTIONABILITY_TRUE"
            if not reference_planning and criteria["ACTIONABILITY"]
            else "MATCH"
        )
        personal_provenance = (
            "P3_MEMORY_DEPENDENT_SOURCE_FIELD_BUT_FINAL_CRITERION_UNCHANGED"
            if bool(metadata["long_term_memory_relevant"]) != draft_long_memory
            else "INDEPENDENT_REFERENCE_BASIS_MATCH"
        )
        scenario_rows.append(
            {
                "scenario_id": sid,
                "current_lad_page": value["current_page"],
                "scenario_group": identity["scenario_group"],
                "reference_required_capabilities": "|".join(identity["required_capabilities"]),
                "dashboard_context_present": str(bool(value["dashboard_context"])).lower(),
                "visible_history_turn_count": len(history),
                "persistent_memory_design_relevant": str(draft_long_memory).lower(),
                "persistent_memory_control_status": memory_registry.get(sid, {}).get("control_status", "NOT_IN_MEMORY_REGISTRY"),
                "current_student_specific_data_relevant": str(bool(metadata["student_specific_data_relevant"])).lower(),
                "draft_independent_student_specific_data_relevant": str(draft_student_specific).lower(),
                "student_specific_provenance_assessment": "MATCH_PRE_RESPONSE_DASHBOARD_OR_VISIBLE_HISTORY",
                "current_long_term_memory_relevant": str(bool(metadata["long_term_memory_relevant"])).lower(),
                "draft_independent_long_term_memory_relevant": str(draft_long_memory).lower(),
                "long_term_memory_provenance_assessment": personal_provenance,
                "current_request_requires_advice": str(bool(metadata["request_requires_advice"])).lower(),
                "current_gold_planning_required": str(bool(metadata["gold_planning_required"])).lower(),
                "reference_recommendation_planning_listed": str(reference_planning).lower(),
                "planning_reference_assessment": planning_assessment,
                "current_personalisation_applicable": str(bool(criteria["PERSONALISATION"])).lower(),
                "draft_independent_personalisation_applicable": str(draft_personalisation).lower(),
                "personalisation_applicability_assessment": (
                    "DRAFT_CHANGE_SIGNAL"
                    if bool(criteria["PERSONALISATION"]) != draft_personalisation
                    else "CRITERION_VALUE_UNCHANGED"
                ),
                "current_actionability_applicable": str(bool(criteria["ACTIONABILITY"])).lower(),
                "draft_reference_rule_actionability_applicable": str(draft_actionability).lower(),
                "actionability_applicability_assessment": planning_assessment,
                "current_student_facing_support_appropriate": str(bool(metadata["student_facing_support_appropriate"])).lower(),
                "draft_student_facing_support_appropriate": "true",
                "motivation_applicability_assessment": "CRITERION_VALUE_UNCHANGED",
                "current_material_lad_pages": "|".join(metadata["material_lad_pages"]),
                "pre_response_material_lad_page_candidates": "|".join(candidates),
                "material_page_provenance_assessment": (
                    "MULTIPLE_VISIBLE_CANDIDATES_MATERIALITY_REQUIRES_RESEARCHER_REVIEW"
                    if len(candidates) > 1
                    else "SINGLE_VISIBLE_CANDIDATE"
                ),
                "current_multi_page_cohesiveness_applicable": str(bool(criteria["MULTI_PAGE_COHESIVENESS"])).lower(),
                "draft_candidate_count_multi_page_signal": str(draft_multi_page).lower(),
                "multi_page_applicability_assessment": (
                    "CURRENT_VALUE_MATCHES_CANDIDATE_COUNT_BUT_MATERIALITY_REVIEW_REQUIRED"
                    if len(candidates) > 1
                    else "CURRENT_FALSE_MATCHES_SINGLE_CANDIDATE"
                ),
                "final_decision_status": "NOT_MADE_RESEARCHER_REVIEW_REQUIRED",
            }
        )

    require(planning_false_negatives == EXPECTED_PLANNING_FALSE_NEGATIVES, "planning false-negative set differs")
    require(planning_false_positives == EXPECTED_PLANNING_FALSE_POSITIVES, "planning false-positive set differs")
    require(not personalisation_changes, "unexpected Personalisation draft change")

    condition_rows = []
    condition_changed_criteria: dict[tuple[str, str], set[str]] = {}
    for current in applicability_rows:
        sid, mode = str(current["scenario_id"]), str(current["mode"])
        value = inputs[sid]
        history = normalise_history(value["visible_conversation_history"])
        criteria = current["frozen_applicability_map"]["criteria"]
        metadata = current["source_metadata"]
        draft = scenario_drafts[sid]
        error = error_by_key[(sid, mode)]
        changed = {
            name
            for name in scenario_drafts[sid]
            if bool(criteria[name]) != bool(draft[name])
        }
        if bool(criteria["ERROR_HANDLING"]) != bool(error["draft_error_handling_applicable"]):
            changed.add("ERROR_HANDLING")
        condition_changed_criteria[(sid, mode)] = changed
        condition_rows.append(
            {
                "scenario_id": sid,
                "mode": mode,
                "current_source_metadata": {
                    name: metadata[name]
                    for name in (
                        "student_specific_data_relevant",
                        "long_term_memory_relevant",
                        "request_requires_advice",
                        "gold_planning_required",
                        "student_facing_support_appropriate",
                        "material_lad_pages",
                        "ambiguity_relevant",
                        "missing_evidence_relevant",
                        "insufficiency_relevant",
                        "conflict_relevant",
                        "boundary_handling_relevant",
                    )
                },
                "independent_pre_response_dependency_draft": {
                    "student_specific_data_relevant": bool(value["dashboard_context"]) or bool(history),
                    "long_term_memory_relevant": sid in persistent_scenarios,
                    "request_requires_advice": "recommendation_planning" in identities[sid]["required_capabilities"],
                    "gold_planning_required": "NOT_USED_IN_DRAFT_REFERENCE_RULE",
                    "student_facing_support_appropriate": True,
                    "material_lad_page_candidates": page_candidates(value),
                    "error_handling_reason_codes": error["mechanical_reason_codes"],
                },
                "p3_prediction_dependency_detected": {
                    "student_specific_data_relevant": True,
                    "long_term_memory_relevant": True,
                    "request_requires_advice": True,
                    "gold_planning_required_constant_false": True,
                },
                "draft_conditional_criterion_change_signals": sorted(changed),
                "final_applicability_decision_made": False,
                "corrected_map_written": False,
            }
        )

    judge_mapping = load_csv(SOURCE_PATHS["judge_mapping"])
    human_mapping = load_csv(SOURCE_PATHS["human_mapping"])
    judge_request_changes: dict[str, set[str]] = defaultdict(set)
    for row in judge_mapping:
        judge_request_changes[row["judge_logical_request_id"]].update(
            condition_changed_criteria[(row["scenario_id"], row["mode_id"])]
        )
    judge_request_changes = {key: value for key, value in judge_request_changes.items() if value}
    all_judge_requests = {row["judge_logical_request_id"] for row in judge_mapping}
    attempted = set(
        projected_jsonl_string_field(
            SOURCE_PATHS["existing_canonical_judge_results"],
            "opaque_judge_request_id",
        )
    )
    attempted.update(
        projected_jsonl_string_field(
            SOURCE_PATHS["judge_b_terminals_v2"],
            "logical_judge_request_id",
        )
    )
    attempted.update(
        projected_jsonl_string_field(
            SOURCE_PATHS["judge_c_terminals_v2"],
            "logical_judge_request_id",
        )
    )
    require(len(all_judge_requests) == 147 and len(attempted) == 89 and attempted <= all_judge_requests, "Judge identity population mismatch")
    affected_judge = set(judge_request_changes)
    human_item_changes: dict[str, set[str]] = defaultdict(set)
    for row in human_mapping:
        human_item_changes[row["r2_rating_item_id"]].update(
            condition_changed_criteria[(row["scenario_id"], row["mode_id"])]
        )
    all_human_items = {row["r2_rating_item_id"] for row in human_mapping}
    human_item_changes = {key: value for key, value in human_item_changes.items() if value}
    require(len(all_human_items) == 44, "Human item population mismatch")
    judge_criterion_counts = {
        name: sum(name in changes for changes in judge_request_changes.values())
        for name in CONDITIONAL_CRITERIA
    }
    human_criterion_counts = {
        name: sum(name in changes for changes in human_item_changes.values())
        for name in CONDITIONAL_CRITERIA
    }
    impact = {
        "identity_only_analysis": True,
        "score_values_accessed": False,
        "rationales_accessed": False,
        "total_unique_judge_requests": len(all_judge_requests),
        "total_preserved_judge_outputs": len(attempted),
        "total_currently_unattempted_judge_requests": len(all_judge_requests - attempted),
        "potentially_changed_unique_judge_requests": len(affected_judge),
        "potentially_changed_currently_unattempted": len(affected_judge - attempted),
        "potentially_changed_with_preserved_outputs": len(affected_judge & attempted),
        "preserved_outputs_requiring_rejudge_if_draft_changes_are_confirmed": len(affected_judge & attempted),
        "judge_request_criterion_amendment_counts": judge_criterion_counts,
        "total_unique_human_visible_items": len(all_human_items),
        "potentially_affected_human_items": len(human_item_changes),
        "potentially_affected_human_item_criterion_pairs": sum(len(value) for value in human_item_changes.values()),
        "human_item_criterion_amendment_counts": human_criterion_counts,
        "scope": "POTENTIAL_DRAFT_IDENTITY_IMPACT_ONLY_NOT_A_REPAIR_DECISION",
    }
    require(
        impact["potentially_changed_unique_judge_requests"] == 24
        and impact["potentially_changed_currently_unattempted"] == 15
        and impact["potentially_changed_with_preserved_outputs"] == 9
        and impact["potentially_affected_human_items"] == 6
        and impact["potentially_affected_human_item_criterion_pairs"] == 6,
        "impact identity counts differ",
    )

    error_false_positive = [row for row in error_records if row["discrepancy"] == "FALSE_POSITIVE_CURRENT_TRUE_WITHOUT_REASON"]
    error_false_negative = [row for row in error_records if row["discrepancy"] == "FALSE_NEGATIVE_CURRENT_FALSE_WITH_REASON"]
    reason_counts = Counter(code for row in error_records for code in row["mechanical_reason_codes"])
    error_audit = {
        "schema_version": "c4-real-error-handling-applicability-audit-v1",
        "status": "DRAFT_MECHANICAL_AUDIT_ONLY_FROZEN_V1_UNCHANGED",
        "condition_count": len(error_records),
        "mechanical_rule": "ERROR_HANDLING draft is true iff a frozen clarification, Dashboard typed-empty, activated RAG NO_RESULT, activated Memory NO_MATCH, Planner insufficiency/conflict, or activated metadata/link-only RAG boundary exists.",
        "source_hashes": {
            name: source_manifest[name]["sha256"]
            for name in (
                "clarification_decisions",
                "dashboard_records",
                "rag_records",
                "memory_records",
                "planner_records",
                "applicability_maps",
            )
        },
        "reason_code_counts": dict(sorted(reason_counts.items())),
        "current_true_without_reason_count": len(error_false_positive),
        "current_false_with_reason_count": len(error_false_negative),
        "frozen_v1_maps_overwritten": False,
        "records": error_records,
    }

    definitions = reviewer_definitions()
    key = SOURCE_PATHS["hmac_key"].read_bytes()
    require(len(key) == 32, "invalid HMAC key")
    packet_rows = []
    restricted_rows = []
    for sid in sorted(identities):
        value = inputs[sid]
        history = normalise_history(value["visible_conversation_history"])
        candidates = page_candidates(value)
        review_id = "APR-" + hmac.new(
            key,
            f"C4_REAL_J2D1_APPLICABILITY_REVIEW_V1|{sid}|{source_manifest['semantic_input_manifest']['sha256']}".encode("utf-8"),
            hashlib.sha256,
        ).hexdigest()[:24].upper()
        persistent = sid in persistent_scenarios
        dashboard_pages = [str(key).title() for key in value["dashboard_context"]] if isinstance(value["dashboard_context"], Mapping) else []
        context_description = (
            f"Reviewed Dashboard context is available for: {'|'.join(dashboard_pages)}. "
            if dashboard_pages
            else "No non-empty reviewed Dashboard context is present. "
        ) + f"Visible conversation history contains {len(history)} turn(s)."
        packet_rows.append(
            {
                "applicability_review_id": review_id,
                "student_query": value["current_query"],
                "current_lad_page": value["current_page"],
                "visible_conversation_history": json.dumps(history, ensure_ascii=False, separators=(",", ":")),
                "student_specific_context_available_or_relevant": context_description,
                "persistent_memory_relevance_information": (
                    "YES — frozen scenario design marks persistent-Memory replay as relevant, including a possible no-match control."
                    if persistent
                    else "NO — scenario is not in the frozen persistent-Memory replay cohort."
                ),
                "pre_response_material_lad_page_candidates": "|".join(candidates),
                "personalisation_definition": definitions["PERSONALISATION"]["definition"],
                "personalisation_na_rule": definitions["PERSONALISATION"]["response_blind_reviewer_rule"],
                "actionability_definition": definitions["ACTIONABILITY"]["definition"],
                "actionability_na_rule": definitions["ACTIONABILITY"]["response_blind_reviewer_rule"],
                "motivation_and_engagement_definition": definitions["MOTIVATION_AND_ENGAGEMENT"]["definition"],
                "motivation_and_engagement_na_rule": definitions["MOTIVATION_AND_ENGAGEMENT"]["response_blind_reviewer_rule"],
                "multi_page_cohesiveness_definition": definitions["MULTI_PAGE_COHESIVENESS"]["definition"],
                "multi_page_cohesiveness_na_rule": definitions["MULTI_PAGE_COHESIVENESS"]["response_blind_reviewer_rule"],
                "researcher_personalisation_applicable": "",
                "researcher_actionability_applicable": "",
                "researcher_motivation_and_engagement_applicable": "",
                "researcher_material_lad_pages": "",
                "researcher_notes": "",
            }
        )
        restricted_rows.append(
            {
                "applicability_review_id": review_id,
                "scenario_id": sid,
                "semantic_input_sha256": next(
                    row["semantic_input_sha256"]
                    for row in load_jsonl(SOURCE_PATHS["semantic_input_manifest"])
                    if row["scenario_id"] == sid
                ),
            }
        )
    packet_rows.sort(key=lambda row: row["applicability_review_id"])
    restricted_rows.sort(key=lambda row: row["applicability_review_id"])
    mapping_path = RESTRICTED / "c4_real_j2d1_applicability_review_id_to_scenario_mapping_v1.csv"
    mapping_payload = csv_bytes(
        ("applicability_review_id", "scenario_id", "semantic_input_sha256"),
        restricted_rows,
    )
    if mapping_path.exists():
        require(mapping_path.read_bytes() == mapping_payload, "existing reviewer mapping differs")
    else:
        descriptor = os.open(mapping_path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        with os.fdopen(descriptor, "wb") as handle:
            handle.write(mapping_payload)
            handle.flush()
            os.fsync(handle.fileno())
    os.chmod(mapping_path, 0o600)
    require(git("check-ignore", str(mapping_path.relative_to(ROOT))) != "", "review mapping is not ignored")

    human_readiness = []
    for path in HUMAN_SOURCES:
        require(path.is_file(), f"missing external Human source: {path.name}")
        human_readiness.append(
            {
                "filename": path.name,
                "present": True,
                "byte_count": path.stat().st_size,
                "sha256": sha256_file(path),
                "content_imported": False,
                "rating_or_attestation_content_inspected": False,
            }
        )

    return {
        "identities": identities,
        "inputs": inputs,
        "scenario_rows": scenario_rows,
        "condition_rows": condition_rows,
        "error_audit": error_audit,
        "packet_rows": packet_rows,
        "definitions": definitions,
        "planning_false_negatives": sorted(planning_false_negatives),
        "planning_false_positives": sorted(planning_false_positives),
        "long_memory_disagreements": sorted(long_memory_disagreements),
        "personalisation_changes": sorted(personalisation_changes),
        "multi_page_review": sorted(multi_page_review),
        "impact": impact,
        "human_readiness": human_readiness,
        "restricted_mapping": {
            "filename": mapping_path.name,
            "row_count": len(restricted_rows),
            "sha256": sha256_bytes(mapping_payload),
            "ignored": True,
            "tracked": False,
            "included_in_review_zip": False,
        },
    }


def markdown_order_40(order40: Mapping[str, Any], parser_identity: Mapping[str, Any]) -> str:
    attempts = order40["attempts"]
    return f"""# C4 REAL order-40 applicability failure analysis

Status: **REPRODUCED OFFLINE — NO CANONICAL RESULT CREATED**

## Frozen input

- Original logical order: `40`
- Student query: `{order40['student_query']}`
- Provider payload SHA-256: `{order40['provider_payload_sha256']}`
- Parser V3 file SHA-256: `{parser_identity['full_file_sha256']}`
- Frozen criteria: ACTIONABILITY is `false`; CLARITY, PERSONALISATION, CONTEXT_AWARENESS, MOTIVATION_AND_ENGAGEMENT, RELIABILITY, MULTI_PAGE_COHESIVENESS, and ERROR_HANDLING are `true`.

## Independent reproduction

Both returned bodies parse as JSON objects and validate against the exact strict Provider response schema embedded in the frozen request. Both encode `actionability` as the JSON string `"3"`. Parser V3 consequently rejects each with the exact error:

`APPLICABILITY_CONTRACT_VIOLATION: actionability must be NA`

Attempt 1 otherwise supplies numeric-string values in the allowed `1`–`5` set for all {attempts[0]['currently_applicable_primary_field_count']} currently applicable primary criteria. This is a contract reproduction only; it does not evaluate or compare the values.

| Attempt | Raw-output SHA-256 | Provider-schema JSON | Normal Provider return | Parser V3 result |
|---:|---|---|---|---|
| 1 | `{attempts[0]['raw_output_sha256']}` | PASS | PASS (`finish_reason=stop`) | `actionability must be NA` |
| 2 | `{attempts[1]['raw_output_sha256']}` | PASS | PASS (`finish_reason=stop`) | `actionability must be NA` |

No Provider, timeout, JSON, outer-schema, refusal, or returned-model error occurred. No Provider call was made in J2D1, neither attempt was promoted to a canonical result, and no preference between their scores was assessed.
"""


def markdown_provenance(audit: Mapping[str, Any]) -> str:
    impl = audit["implementation_audit"]
    scenario = audit["scenario_audit_summary"]
    return f"""# C4 REAL applicability provenance audit

Status: **METHODOLOGICAL DEFECT CONFIRMED; FROZEN V1 MAPS PRESERVED**

## Exact committed implementation

`build_i1_artifacts.py::freeze_applicability_maps` (lines {impl['line_start']}–{impl['line_end']}) constructs the relevant source metadata as follows:

```python
student_specific_data_relevant = bool(dashboard_context) or route["memory_required"]
long_term_memory_relevant = route["memory_required"]
request_requires_advice = route["planning_required"]
gold_planning_required = False
material_lad_pages = current page plus recognised top-level Dashboard-context page keys
```

- Full code-file SHA-256: `{impl['full_file_sha256']}`
- Exact function-source SHA-256: `{impl['exact_function_source_sha256']}`
- Frozen 558-map artifact SHA-256: `{audit['source_manifest']['applicability_maps']['sha256']}`

## Why this is circular

The map used to judge response quality is partly defined by P3's predicted route bits. A Planning false negative can therefore turn ACTIONABILITY into `NA`; a Memory route decision can change the recorded learner-context provenance; and a routing failure can exclude the response consequence from the very criterion intended to measure it. This conflicts with the frozen applicability invariant that capability absence or route error must not make a genuine student need non-applicable.

## Response-blind scenario audit

The independent draft uses only pre-response scenario identity, query/page/history, reviewed Dashboard-context presence, reference capability metadata, frozen persistent-Memory design, and frozen mechanism status/source metadata. It creates review signals, not corrected maps.

- Planning-reference disagreements: **{scenario['planning_reference_disagreement_count']}** (7 current false/reference true; 1 current true/reference not listed).
- Complete current-false/reference-true set: `{', '.join(scenario['planning_false_negatives'])}`.
- Complete current-true/reference-not-listed set: `{', '.join(scenario['planning_false_positives'])}`.
- `long_term_memory_relevant` provenance disagreements with frozen persistent-replay design: **{scenario['long_term_memory_provenance_disagreement_count']}** scenarios.
- Direction of those provenance disagreements: **{scenario['long_term_memory_current_true_reference_false_count']}** current true/reference false and **{scenario['long_term_memory_current_false_reference_true_count']}** current false/reference true.
- PERSONALISATION criterion changes under the independent Boolean draft: **{scenario['personalisation_draft_change_count']}**. Its final Boolean happens to remain unchanged, but 24 long-term-Memory source fields have circular or inaccurate provenance and must not be reused as an independent definition.
- Current multi-page true scenarios: **{scenario['current_multi_page_true_scenario_count']}**. All **{scenario['material_page_candidate_list_match_count']}** current page lists equal the visible pre-response candidate lists, but top-level key presence alone does not establish materiality; all {scenario['multi_page_materiality_review_count']} multi-candidate scenarios are sent for independent material-page review.

## Condition-specific ERROR_HANDLING

The 558-condition mechanical audit found {audit['error_handling_summary']['current_true_without_reason_count']} current-true cases without a frozen reason and {audit['error_handling_summary']['current_false_with_reason_count']} current-false cases despite a frozen reason. It does not overwrite V1.

## Boundaries

No response text, Judge score/rationale, Human score/rationale, observed condition performance, or expected winner was used for the 62-scenario audit or reviewer packet. The only Provider output inspection in J2D1 is the separately documented, expressly authorised order-40 contract reproduction. No corrected applicability decision is final until the independent researcher returns the blank packet.
"""


def reviewer_guide(definitions: Mapping[str, Mapping[str, str]]) -> str:
    blocks = []
    for name in (
        "PERSONALISATION",
        "ACTIONABILITY",
        "MOTIVATION_AND_ENGAGEMENT",
        "MULTI_PAGE_COHESIVENESS",
    ):
        blocks.append(
            f"### {name}\n\nDefinition: {definitions[name]['definition']}\n\nResponse-blind applicability/NA rule: {definitions[name]['response_blind_reviewer_rule']}"
        )
    return """# Independent applicability reviewer guide

## Purpose and blindness

Review whether four conditional response-quality criteria are genuinely applicable to each student request **before seeing any candidate response**. This is applicability review, not response scoring. The packet contains 62 opaque rows and intentionally omits scenario IDs, groups, routes, modes, current/draft decisions, response/Judge identifiers, candidate responses, Judge outputs, Human ratings, and expected outcomes.

Use only the row's student query, current LAD page, visible conversation history, concise context-availability description, persistent-Memory design relevance, and visible page candidates. Do not infer which system capability was enabled or called.

## Decision procedure

1. Enter exactly `YES` or `NO` in each of the three applicability fields.
2. In `researcher_material_lad_pages`, list only the materially involved visible LAD pages, separated by `|`. Choose only from the row's page candidates; do not list a page merely because it is available.
3. Use `researcher_notes` for a short rationale, especially for borderline decisions.
4. Do not score any criterion and do not seek or request response text.

""" + "\n\n".join(blocks) + """

## Return and attestation

Complete all 62 rows, leave all source columns unchanged, sign the separate attestation, and return both files. Do not attempt to identify opaque IDs.
"""


def impact_markdown(impact: Mapping[str, Any]) -> str:
    jc = impact["judge_request_criterion_amendment_counts"]
    hc = impact["human_item_criterion_amendment_counts"]
    return f"""# C4 REAL applicability repair impact preview

Status: **IDENTITY-ONLY DRAFT — NO SCORES OR RATIONALES READ**

Under the candidate independent provenance rules, **{impact['potentially_changed_unique_judge_requests']} of {impact['total_unique_judge_requests']}** unique Judge requests could change applicability. Of those, **{impact['potentially_changed_currently_unattempted']}** are currently unattempted and **{impact['potentially_changed_with_preserved_outputs']}** have preserved Judge outputs. If the independent decisions confirm those changes, all **{impact['preserved_outputs_requiring_rejudge_if_draft_changes_are_confirmed']}** preserved affected outputs would remain preserved but be excluded from the primary result and rejudged under the corrected map.

Of the **{impact['total_unique_human_visible_items']}** unique Human-visible items, **{impact['potentially_affected_human_items']}** could require a blind supplemental applicability amendment, covering **{impact['potentially_affected_human_item_criterion_pairs']}** item/criterion pairs. No completed Human packet was imported or analysed.

| Criterion | Potential Judge requests | Potential Human items |
|---|---:|---:|
""" + "".join(
        f"| {name} | {jc[name]} | {hc[name]} |\n" for name in CONDITIONAL_CRITERIA
    ) + """

These counts are joins over frozen scenario/condition/request/item identities only. They are neither repaired applicability decisions nor response-quality results. No Judge score, Human score, rationale, mode mean, condition comparison, favourable/unfavourable direction, or final statistic was inspected or reported.
"""


def repair_policy() -> str:
    return """# C4 REAL applicability repair policy — draft

Status: **POLICY FROZEN FOR LATER AUTHORISED REPAIR; DECISIONS NOT FROZEN**

1. Applicability is defined independently of P3 predictions.
2. Applicability is defined independently of whether a module was enabled or called.
3. A routing failure cannot turn a genuine need into `NA`.
4. If a Judge request's applicability map changes, its old Judge output remains preserved but is excluded from the primary result and that request is rejudged under the corrected map.
5. Existing Judge results with byte-identical unchanged applicability remain eligible.
6. Human ratings for unchanged item/criterion pairs remain eligible.
7. Human raters receive a supplemental blind amendment packet only for changed criterion applicability.
8. No Human rater is shown the previous score, the other rater's score, Judge output, mode, or expected outcome.
9. Exact condition comparisons remain prohibited until all corrected Judge and Human records are frozen.

J2D1 does not implement corrected maps, build Judge execution packages, create a Human amendment packet, or authorise any execution.
"""


def main() -> None:
    HERE.mkdir(parents=True, exist_ok=True)
    source_manifest = verify_sources()
    integration = verify_integrations()
    judge_preservation = verify_judge_preservation()
    implementation = source_function_identity(SOURCE_PATHS["i1_builder"], "freeze_applicability_maps")
    parser_identity = source_function_identity(
        J2D0 / "judge_result_parser_v3.py", "parse_judge_result"
    )
    order40 = reproduce_order_40()
    built = build_audits(source_manifest)

    scenario_fieldnames = (
        "scenario_id",
        "current_lad_page",
        "scenario_group",
        "reference_required_capabilities",
        "dashboard_context_present",
        "visible_history_turn_count",
        "persistent_memory_design_relevant",
        "persistent_memory_control_status",
        "current_student_specific_data_relevant",
        "draft_independent_student_specific_data_relevant",
        "student_specific_provenance_assessment",
        "current_long_term_memory_relevant",
        "draft_independent_long_term_memory_relevant",
        "long_term_memory_provenance_assessment",
        "current_request_requires_advice",
        "current_gold_planning_required",
        "reference_recommendation_planning_listed",
        "planning_reference_assessment",
        "current_personalisation_applicable",
        "draft_independent_personalisation_applicable",
        "personalisation_applicability_assessment",
        "current_actionability_applicable",
        "draft_reference_rule_actionability_applicable",
        "actionability_applicability_assessment",
        "current_student_facing_support_appropriate",
        "draft_student_facing_support_appropriate",
        "motivation_applicability_assessment",
        "current_material_lad_pages",
        "pre_response_material_lad_page_candidates",
        "material_page_provenance_assessment",
        "current_multi_page_cohesiveness_applicable",
        "draft_candidate_count_multi_page_signal",
        "multi_page_applicability_assessment",
        "final_decision_status",
    )
    write_csv(HERE / "c4_real_62_scenario_applicability_audit_v1.csv", scenario_fieldnames, built["scenario_rows"])
    write_json(
        HERE / "c4_real_558_condition_applicability_dependency_audit_v1.json",
        {
            "schema_version": "c4-real-558-condition-applicability-dependency-audit-v1",
            "status": "DRAFT_DEPENDENCY_AUDIT_ONLY_NO_CORRECTED_MAP",
            "condition_count": len(built["condition_rows"]),
            "candidate_response_accessed": False,
            "judge_score_or_rationale_accessed": False,
            "human_score_or_rationale_accessed": False,
            "records": built["condition_rows"],
        },
    )
    write_json(HERE / "c4_real_error_handling_applicability_audit_v1.json", built["error_audit"])

    packet_fieldnames = (
        "applicability_review_id",
        "student_query",
        "current_lad_page",
        "visible_conversation_history",
        "student_specific_context_available_or_relevant",
        "persistent_memory_relevance_information",
        "pre_response_material_lad_page_candidates",
        "personalisation_definition",
        "personalisation_na_rule",
        "actionability_definition",
        "actionability_na_rule",
        "motivation_and_engagement_definition",
        "motivation_and_engagement_na_rule",
        "multi_page_cohesiveness_definition",
        "multi_page_cohesiveness_na_rule",
        "researcher_personalisation_applicable",
        "researcher_actionability_applicable",
        "researcher_motivation_and_engagement_applicable",
        "researcher_material_lad_pages",
        "researcher_notes",
    )
    write_csv(HERE / "applicability_researcher_review_packet.csv", packet_fieldnames, built["packet_rows"])

    scenario_summary = {
        "scenario_count": 62,
        "planning_reference_disagreement_count": len(built["planning_false_negatives"]) + len(built["planning_false_positives"]),
        "planning_false_negatives": built["planning_false_negatives"],
        "planning_false_positives": built["planning_false_positives"],
        "planning_disagreement_set_complete": True,
        "long_term_memory_provenance_disagreement_count": len(built["long_memory_disagreements"]),
        "long_term_memory_provenance_disagreement_scenarios": built["long_memory_disagreements"],
        "long_term_memory_current_true_reference_false_count": sum(
            row["current_long_term_memory_relevant"] == "true"
            and row["draft_independent_long_term_memory_relevant"] == "false"
            for row in built["scenario_rows"]
        ),
        "long_term_memory_current_false_reference_true_count": sum(
            row["current_long_term_memory_relevant"] == "false"
            and row["draft_independent_long_term_memory_relevant"] == "true"
            for row in built["scenario_rows"]
        ),
        "student_specific_data_provenance_disagreement_count": sum(
            row["current_student_specific_data_relevant"]
            != row["draft_independent_student_specific_data_relevant"]
            for row in built["scenario_rows"]
        ),
        "personalisation_draft_change_count": len(built["personalisation_changes"]),
        "current_personalisation_true_scenario_count": sum(row["current_personalisation_applicable"] == "true" for row in built["scenario_rows"]),
        "current_multi_page_true_scenario_count": sum(row["current_multi_page_cohesiveness_applicable"] == "true" for row in built["scenario_rows"]),
        "multi_page_materiality_review_count": len(built["multi_page_review"]),
        "multi_page_materiality_review_scenarios": built["multi_page_review"],
        "material_page_candidate_list_match_count": sum(
            row["current_material_lad_pages"]
            == row["pre_response_material_lad_page_candidates"]
            for row in built["scenario_rows"]
        ),
        "final_discretionary_decisions_made": False,
    }
    audit = {
        "schema_version": "c4-real-applicability-provenance-audit-v1",
        "status": "READY_FOR_INDEPENDENT_RESEARCHER_APPLICABILITY_REVIEW",
        "authorization_id": "RQ3-REAL-C4-J2D1",
        "working_directory": str(ROOT),
        "branch": EXPECTED_BRANCH,
        "starting_head": STARTING_HEAD,
        "audit_parent_head": AUDIT_PARENT_HEAD,
        "commit_integration": integration,
        "judge_execution_preservation": judge_preservation,
        "order_40_reproduction": order40,
        "implementation_audit": implementation,
        "source_manifest": source_manifest,
        "scenario_audit_summary": scenario_summary,
        "error_handling_summary": {
            "condition_count": built["error_audit"]["condition_count"],
            "reason_code_counts": built["error_audit"]["reason_code_counts"],
            "current_true_without_reason_count": built["error_audit"]["current_true_without_reason_count"],
            "current_false_with_reason_count": built["error_audit"]["current_false_with_reason_count"],
        },
        "researcher_packet": {
            "row_count": len(built["packet_rows"]),
            "opaque_ids_unique": len({row["applicability_review_id"] for row in built["packet_rows"]}) == 62,
            "all_final_fields_blank": all(
                not row[name]
                for row in built["packet_rows"]
                for name in (
                    "researcher_personalisation_applicable",
                    "researcher_actionability_applicable",
                    "researcher_motivation_and_engagement_applicable",
                    "researcher_material_lad_pages",
                    "researcher_notes",
                )
            ),
            "restricted_mapping": built["restricted_mapping"],
            "candidate_response_or_score_source_used": False,
        },
        "impact_assessment": built["impact"],
        "human_source_readiness": {
            "status": "READY_EXTERNAL_COMPLETED_SOURCES_PRESENT_HASHED_ONLY",
            "sources": built["human_readiness"],
            "completed_rating_content_imported": False,
            "completed_score_or_rationale_content_inspected": False,
            "full_repeat_requested": False,
            "amendment_packet_created": False,
        },
        "execution_counters": {
            "provider_calls": 0,
            "judge_calls": 0,
            "response_generation_calls": 0,
            "response_quality_scoring_calls": 0,
            "human_rating_calculations": 0,
            "human_agreement_calculations": 0,
            "mode_or_condition_comparisons": 0,
            "final_statistical_analyses": 0,
            "rag_calls": 0,
            "memory_calls": 0,
            "planning_calls": 0,
            "evidence_synthesis_calls": 0,
            "p3_calls": 0,
            "streamlit_launches": 0,
            "network_calls": 0,
        },
        "repair_boundaries": {
            "corrected_applicability_maps_written": False,
            "judge_package_rebuilt": False,
            "human_rating_modified": False,
            "human_amendment_packet_created": False,
            "existing_hmac_key_modified": False,
            "existing_restricted_mapping_modified": False,
        },
    }
    write_json(HERE / "c4_real_applicability_provenance_audit_v1.json", audit)
    write_text(HERE / "C4_REAL_ORDER40_APPLICABILITY_FAILURE_ANALYSIS.md", markdown_order_40(order40, parser_identity))
    write_text(HERE / "C4_REAL_APPLICABILITY_PROVENANCE_AUDIT.md", markdown_provenance(audit))
    write_text(HERE / "APPLICABILITY_REVIEWER_GUIDE.md", reviewer_guide(built["definitions"]))
    write_text(
        HERE / "applicability_researcher_attestation.md",
        """# Independent applicability researcher attestation

Applicability reviewer name or code: ______________________________

Completion date (UTC): ______________________________

- [ ] I reviewed exactly 62 opaque applicability rows.
- [ ] I did not receive or seek candidate responses, current/draft applicability decisions, P3 routes, modes, Judge outputs, Human ratings, or expected outcomes.
- [ ] I decided applicability from the pre-response information supplied in each row.
- [ ] I treated capability absence and route error as unable, by themselves, to make a genuine student need non-applicable.
- [ ] I entered only `YES` or `NO` in the three applicability fields and used pipe-delimited visible page names for material LAD pages.
- [ ] I did not score response quality or attempt to identify opaque review IDs.

Signature: ______________________________
""",
    )
    write_text(HERE / "C4_REAL_APPLICABILITY_REPAIR_IMPACT_PREVIEW.md", impact_markdown(built["impact"]))
    write_text(HERE / "C4_REAL_APPLICABILITY_REPAIR_POLICY_DRAFT.md", repair_policy())
    write_text(
        HERE / "STATUS.md",
        f"""# RQ3-REAL-C4-J2D1 status

`RQ3_REAL_J2D1_STATUS = READY_FOR_INDEPENDENT_RESEARCHER_APPLICABILITY_REVIEW`

- Starting HEAD: `{STARTING_HEAD}`
- Audit parent after exact B/C history integration: `{AUDIT_PARENT_HEAD}`
- Original Judge artifacts: byte-identical and preserved.
- Provisional preserved Judge results: A=1, B=49, C=39, total=89; not declared final.
- Order 40: reproduced offline as an applicability-contract failure; no canonical result created.
- Scenario audit: 62/62; planning-reference disagreements=8; final decisions not made.
- Condition dependency and ERROR_HANDLING audits: 558/558; frozen V1 maps unchanged.
- Blind researcher packet: 62 rows; all final fields blank; restricted mapping ignored and excluded.
- Identity-only potential impact: Judge requests=24 (9 preserved, 15 unattempted); Human items=6; item/criterion pairs=6.
- External completed Human sources: presence/size/SHA-256 recorded only; content not imported or analysed.
- Provider/Judge/scoring/Human-rating/network/Streamlit activity in J2D1: zero.
- Corrected applicability maps, Judge packages, Human amendment packets, and final statistics: not created.
""",
    )
    print(json.dumps({
        "status": audit["status"],
        "scenario_rows": len(built["scenario_rows"]),
        "condition_rows": len(built["condition_rows"]),
        "review_rows": len(built["packet_rows"]),
        "planning_disagreements": scenario_summary["planning_reference_disagreement_count"],
        "affected_judge_requests": built["impact"]["potentially_changed_unique_judge_requests"],
        "affected_human_items": built["impact"]["potentially_affected_human_items"],
    }, sort_keys=True))


if __name__ == "__main__":
    main()
