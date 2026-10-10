#!/usr/bin/env python3
"""Build the RQ3 REAL C4 R3D1-R1 response and evaluation freeze.

This builder is offline and fail-closed. It reads immutable generation and
mapping artifacts, stages every derived artifact in memory, validates the
complete staged set, and only then performs write-once materialisation. It
contains no Provider transport and performs no scoring or rating.
"""

from __future__ import annotations

import ast
from collections import Counter, defaultdict
import csv
from fractions import Fraction
import hashlib
import hmac
import importlib.util
import io
import json
import math
import os
from pathlib import Path
import re
import stat
import subprocess
import tempfile
from typing import Any, Iterable, Mapping, Sequence
from zipfile import ZIP_DEFLATED, ZipFile, ZipInfo

try:
    from .judge_package_validator_v1 import validate_package_dir
except ImportError:  # pragma: no cover - direct-script execution
    from judge_package_validator_v1 import validate_package_dir


HERE = Path(__file__).resolve().parent
REPO = HERE.parents[2]
REAL = REPO / "evaluation/rq3_real_c4"
I1 = REAL / "i1_route_integration"
RESTRICTED = I1 / "restricted_internal"
R3D0 = REAL / "r3d0_validator_false_positive_repair"
PROTOCOL = REPO / "evaluation/rq3_v2/rq3_0b4_evaluation_protocol"
DOWNLOADS = Path("/Users/liuming/Downloads")

EXPECTED_BRANCH = "research/rq3-real-c4-i1-route-integration"
START_HEAD = "ebac41e4dfd1b3a54fd229cc92863b6ea5280673"
CONTINUATION_COMMIT = START_HEAD
HMAC_KEY_COMMITMENT = "199db23c86b0dd824edaff2d5b40da12761c9aa76bf2fb9d902952ab376481b5"
POLICY_ID = "C4_REAL_IDENTICAL_ANSWER_TEXT_POLICY_V1"
JUDGE_DOMAIN = "C4_REAL_JUDGE_R1"
HUMAN_DOMAIN = "C4_REAL_HUMAN_R1"
SEED = 20260901
JUDGE_MODEL = "gpt-4.1-2025-04-14"
JUDGE_MAX_OUTPUT_TOKENS = 2048
JUDGE_TEMPERATURE = 0
KNOWN_DUPLICATE_REQUEST_IDS = (
    "C4G3-27DB4E34907424BD1E55833D",
    "C4G3-6AD282636EFA8FFD87E204B3",
)
KNOWN_DUPLICATE_TEXT_SHA256 = (
    "3819287dff0aceb82f4fed793a6703a2b45fb331b39d9b522bb481e2aad70276"
)

R3_SOURCE_DIRS = {
    "A": REAL / "r3a_response_regeneration_shard_a",
    "B": REAL / "r3b_response_regeneration_shard_b",
    "C": REAL / "r3c_response_regeneration_shard_c",
    "C_CONTINUATION": REAL / "r3c1_response_continuation",
}

EXPECTED_SOURCE_IDENTITIES = {
    "A": {
        "logical_requests": 50,
        "physical_attempts": 51,
        "terminal_journal_sha256": "bddc59c161540abafc5b287bd1e8cff00c2512417ee2390923ad6e395889ec0a",
        "answer_set_sha256": "6b78607363c4d0a0908507472b83a047a28773c3a948046bf9776ed71c1d1851",
    },
    "B": {
        "logical_requests": 50,
        "physical_attempts": 50,
        "terminal_journal_sha256": "0a3c731fa00f596b9c80c3f463faf8f0563ca741dbe58942dbbc1bb0b36e7585",
        "answer_set_sha256": "b035aa4f18025a4d6592489b9ed94394a4872cbca31788ee31dba5574e88ac8c",
    },
    "C": {
        "logical_requests": 4,
        "physical_attempts": 5,
        "terminal_journal_sha256": "9ab653b18743e95c7c777327c8742e3fe3bebbf64c72cc61a547141081be66bb",
        "answer_set_sha256": "0affb1b3f7f84496eccbd1e04c417dd8e3d39242c92b39c3396c15d6e289c456",
    },
    "C_CONTINUATION": {
        "logical_requests": 43,
        "physical_attempts": 43,
        "terminal_journal_sha256": "46b5e72c7d6d120212e631f3490d53287d1f9246ea1b71469ef2fa6976e71717",
        "answer_set_sha256": "6afaa66f950d7c883f2a97c624925738b692d2b58df4c048ec644ffed0b05d74",
    },
}

EXPECTED_USAGE = {
    "A": {
        "logical_requests": 50,
        "physical_attempts": 51,
        "prompt_tokens": 43426,
        "cached_input_tokens": 4992,
        "completion_tokens": 7698,
        "total_tokens": 51124,
    },
    "B": {
        "logical_requests": 50,
        "physical_attempts": 50,
        "prompt_tokens": 41178,
        "cached_input_tokens": 3584,
        "completion_tokens": 8896,
        "total_tokens": 50074,
    },
    "C": {
        "logical_requests": 4,
        "physical_attempts": 5,
        "prompt_tokens": 5126,
        "cached_input_tokens": 0,
        "completion_tokens": 1005,
        "total_tokens": 6131,
    },
    "C_CONTINUATION": {
        "logical_requests": 43,
        "physical_attempts": 43,
        "prompt_tokens": 38032,
        "cached_input_tokens": 6144,
        "completion_tokens": 5969,
        "total_tokens": 44001,
    },
}

LEAKAGE_LITERALS = (
    "C0_ORIGINAL",
    "C1_EVIDENCE",
    "C2_EVIDENCE_RAG",
    "C3_EVIDENCE_MEMORY",
    "C4_EVIDENCE_PLANNING",
    "C5_FULL_C4",
    "C5_MINUS_RAG",
    "C5_MINUS_MEMORY",
    "C5_MINUS_PLANNING",
    "R2V2",
    "P3",
    "scenario_id",
    "condition_id",
    "mode_id",
    "route_id",
    "provider_payload_sha256",
)


class FreezeError(RuntimeError):
    """Raised when an immutable input or freeze invariant differs."""


def require(condition: bool, message: str) -> None:
    if not condition:
        raise FreezeError(message)


def canonical_json_bytes(value: Any) -> bytes:
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    ).encode("utf-8")


def pretty_json_bytes(value: Any) -> bytes:
    return (
        json.dumps(value, ensure_ascii=False, sort_keys=True, indent=2, allow_nan=False)
        + "\n"
    ).encode("utf-8")


def jsonl_bytes(rows: Iterable[Mapping[str, Any]]) -> bytes:
    return b"".join(canonical_json_bytes(dict(row)) + b"\n" for row in rows)


def csv_bytes(fieldnames: Sequence[str], rows: Iterable[Mapping[str, Any]]) -> bytes:
    buffer = io.StringIO(newline="")
    writer = csv.DictWriter(buffer, fieldnames=fieldnames, lineterminator="\n")
    writer.writeheader()
    for row in rows:
        writer.writerow({name: row.get(name, "") for name in fieldnames})
    return buffer.getvalue().encode("utf-8")


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def load_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def load_jsonl(path: Path) -> list[dict[str, Any]]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line]


def load_csv(path: Path) -> list[dict[str, str]]:
    with path.open(encoding="utf-8", newline="") as handle:
        return list(csv.DictReader(handle))


def git(*args: str, text: bool = True) -> str | bytes:
    result = subprocess.run(
        ["git", *args],
        cwd=REPO,
        check=True,
        capture_output=True,
        text=text,
    )
    return result.stdout


def load_module(name: str, path: Path) -> Any:
    spec = importlib.util.spec_from_file_location(name, path)
    require(spec is not None and spec.loader is not None, f"cannot load {path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def hmac_hex(key: bytes, domain: str, purpose: str, *parts: str) -> str:
    message = "\x00".join((domain, str(SEED), purpose, *parts)).encode("utf-8")
    return hmac.new(key, message, hashlib.sha256).hexdigest()


def opaque_id(
    key: bytes, domain: str, purpose: str, material: str, prefix: str, length: int
) -> str:
    return prefix + hmac_hex(key, domain, purpose, material)[:length].upper()


def zip_bytes(members: Mapping[str, bytes]) -> bytes:
    buffer = io.BytesIO()
    with ZipFile(buffer, "w", compression=ZIP_DEFLATED, compresslevel=9) as archive:
        for name in sorted(members):
            require(not name.startswith("/") and ".." not in Path(name).parts, "unsafe ZIP path")
            info = ZipInfo(name, date_time=(2026, 9, 2, 0, 0, 0))
            info.compress_type = ZIP_DEFLATED
            info.external_attr = (stat.S_IFREG | 0o644) << 16
            archive.writestr(info, members[name])
    return buffer.getvalue()


def assert_initial_and_immutable_state() -> dict[str, Any]:
    require(Path.cwd().resolve() == REPO.resolve(), "working directory changed")
    branch = str(git("branch", "--show-current")).strip()
    head = str(git("rev-parse", "HEAD")).strip()
    require(branch == EXPECTED_BRANCH, "branch changed")
    require(head == START_HEAD, "builder must run at the authorized starting HEAD")
    require(RESTRICTED.is_dir(), "restricted_internal is absent")
    policy = load_json(HERE / "c4_real_identical_answer_text_policy_v1.json")
    require(policy.get("policy_id") == POLICY_ID, "duplicate-text policy ID mismatch")
    require(
        policy.get("status") == "FROZEN_BEFORE_CONDITION_LEVEL_UNBLINDING",
        "duplicate-text policy was not frozen before mapping",
    )

    count = int(str(git("rev-list", "HEAD")).splitlines().count(CONTINUATION_COMMIT))
    require(count == 1, "continuation commit is not present exactly once")

    key_path = RESTRICTED / "c4_real_i1_blinding_hmac_key.bin"
    require(key_path.is_file(), "HMAC key absent")
    key = key_path.read_bytes()
    require(len(key) == 32, "HMAC key length changed")
    require(stat.S_IMODE(key_path.stat().st_mode) == 0o600, "HMAC key mode changed")
    require(sha256_bytes(key) == HMAC_KEY_COMMITMENT, "HMAC key commitment mismatch")
    ignored = subprocess.run(
        ["git", "check-ignore", "-q", str(key_path.relative_to(REPO))], cwd=REPO
    )
    require(ignored.returncode == 0, "HMAC key is not ignored")

    restricted_metadata = load_json(I1 / "c4_real_restricted_mapping_metadata_v3.json")
    require(
        restricted_metadata.get("hmac_key_sha256_commitment") == HMAC_KEY_COMMITMENT,
        "tracked key commitment mismatch",
    )
    for name, expected in restricted_metadata["mapping_files"].items():
        path = RESTRICTED / name
        require(path.is_file(), f"restricted V3 mapping absent: {name}")
        require(sha256_file(path) == expected["sha256"], f"restricted V3 hash mismatch: {name}")
        require(stat.S_IMODE(path.stat().st_mode) == 0o600, f"restricted V3 mode mismatch: {name}")
        require(
            subprocess.run(
                ["git", "check-ignore", "-q", str(path.relative_to(REPO))], cwd=REPO
            ).returncode
            == 0,
            f"restricted V3 file is not ignored: {name}",
        )

    protected_dirs = [*R3_SOURCE_DIRS.values(), R3D0]
    diff = subprocess.run(
        ["git", "diff", "--quiet", START_HEAD, "--", *[str(p.relative_to(REPO)) for p in protected_dirs]],
        cwd=REPO,
    )
    require(diff.returncode == 0, "an immutable R3/R3D0 source differs from starting HEAD")
    return {
        "branch": branch,
        "head": head,
        "key": key,
        "restricted_metadata": restricted_metadata,
        "policy_sha256": sha256_file(HERE / "c4_real_identical_answer_text_policy_v1.json"),
    }


def source_preservation_manifest() -> dict[str, Any]:
    prefixes = [str(path.relative_to(REPO)) for path in [*R3_SOURCE_DIRS.values(), R3D0]]
    names = str(git("ls-tree", "-r", "--name-only", START_HEAD, "--", *prefixes)).splitlines()
    files: list[dict[str, Any]] = []
    for name in names:
        path = REPO / name
        require(path.is_file(), f"immutable source missing: {name}")
        current = path.read_bytes()
        frozen = git("show", f"{START_HEAD}:{name}", text=False)
        require(isinstance(frozen, bytes) and current == frozen, f"immutable source bytes changed: {name}")
        files.append({"path": name, "bytes": len(current), "sha256": sha256_bytes(current)})
    return {
        "schema_version": "c4-real-r3d1-r1-source-preservation-manifest-v1",
        "status": "PASS_ALL_R3_R3D0_R3C1_SOURCE_BYTES_UNCHANGED",
        "starting_head": START_HEAD,
        "continuation_commit_present_exactly_once": True,
        "file_count": len(files),
        "files": files,
    }


def _extract_outer_answer(raw_response_content: str) -> str:
    try:
        value = json.loads(raw_response_content)
    except json.JSONDecodeError as exc:
        raise FreezeError("selected response outer JSON is invalid") from exc
    require(isinstance(value, dict) and set(value) == {"answer_text"}, "outer schema mismatch")
    answer = value["answer_text"]
    require(isinstance(answer, str) and answer.strip(), "empty selected answer")
    return answer


def build_canonical_responses() -> tuple[list[dict[str, Any]], list[dict[str, Any]], dict[str, Any]]:
    validator = load_module(
        "c4_real_r3d1_validator_v2",
        R3D0 / "c4_real_student_facing_response_validator_v2.py",
    )
    selection_rows = load_jsonl(R3D0 / "c4_real_r3_existing_canonical_response_selection_v1.jsonl")
    selected = {
        (row["shard"], row["logical_generation_request_id"]): row
        for row in selection_rows
    }
    require(len(selected) == 104, "R3D0 canonical selection population changed")

    attempt_rows: dict[str, list[dict[str, Any]]] = {}
    attempts_by_key: dict[tuple[str, str, int], dict[str, Any]] = {}
    for shard, directory in R3_SOURCE_DIRS.items():
        path = directory / "execution_output_v1/GENERATION_ATTEMPT_JOURNAL.jsonl"
        rows = load_jsonl(path)
        attempt_rows[shard] = rows
        require(len(rows) == EXPECTED_SOURCE_IDENTITIES[shard]["physical_attempts"], f"Shard {shard} attempt count changed")
        for row in rows:
            key = (shard, row["logical_generation_request_id"], row["attempt_number"])
            require(key not in attempts_by_key, "duplicate physical attempt identity")
            attempts_by_key[key] = row

    continuation_rows = attempt_rows["C_CONTINUATION"]
    for row in continuation_rows:
        require(row["attempt_number"] == 1, "continuation contains a retry")
        answer = _extract_outer_answer(row["raw_response_content"])
        status = validator.validate_answer_text(answer)
        require(status == validator.VALID_STUDENT_FACING_RESPONSE, "continuation fails Validator V2")
        selected[("C_CONTINUATION", row["logical_generation_request_id"])] = {
            "shard": "C_CONTINUATION",
            "logical_order": row["logical_order"],
            "logical_generation_request_id": row["logical_generation_request_id"],
            "response_blind_id": row["response_blind_id"],
            "selected_attempt_number": 1,
            "raw_response_source_sha256": sha256_bytes(row["raw_response_content"].encode("utf-8")),
            "answer_text": answer,
            "answer_text_sha256": sha256_bytes(answer.encode("utf-8")),
            "v2_format_status": status,
            "original_terminal_selection_relationship": "CONTINUATION_SINGLE_VALID_ATTEMPT",
        }
    require(len(selected) == 147, "combined canonical selection count differs")

    manifest = load_jsonl(I1 / "c4_real_unique_generation_request_manifest_frozen_v3.jsonl")
    require(len(manifest) == 147, "frozen V3 request manifest count changed")
    manifest_ids = {row["logical_generation_request_id"] for row in manifest}
    selected_by_id = {key[1]: value for key, value in selected.items()}
    require(len(selected_by_id) == 147 and set(selected_by_id) == manifest_ids, "canonical/V3 request identity mismatch")

    canonical: list[dict[str, Any]] = []
    source_registry: list[dict[str, Any]] = []
    for manifest_order, manifest_row in enumerate(manifest, 1):
        request_id = manifest_row["logical_generation_request_id"]
        choice = selected_by_id[request_id]
        shard = choice["shard"]
        attempt = attempts_by_key[(shard, request_id, choice["selected_attempt_number"])]
        answer = _extract_outer_answer(attempt["raw_response_content"])
        answer_hash = sha256_bytes(answer.encode("utf-8"))
        raw_hash = sha256_bytes(attempt["raw_response_content"].encode("utf-8"))
        require(answer == choice["answer_text"], "selected answer bytes differ from R3D0/continuation selection")
        require(answer_hash == choice["answer_text_sha256"], "selected answer hash differs")
        require(raw_hash == choice["raw_response_source_sha256"], "selected raw source hash differs")
        require(attempt["logical_generation_request_id"] == request_id, "attempt request ID mismatch")
        require(attempt["response_blind_id"] == manifest_row["response_blind_id"], "response blind ID mismatch")
        require(attempt["provider_payload_sha256"] == manifest_row["provider_payload_sha256"], "Provider payload hash mismatch")
        status = validator.validate_answer_text(answer)
        require(status == validator.VALID_STUDENT_FACING_RESPONSE, "canonical response fails Validator V2")
        source_path = (
            R3_SOURCE_DIRS[shard] / "execution_output_v1/GENERATION_ATTEMPT_JOURNAL.jsonl"
        ).relative_to(REPO).as_posix()
        record = {
            "schema_version": "c4-real-r3-canonical-unique-response-frozen-v1",
            "frozen_manifest_order": manifest_order,
            "logical_generation_request_id": request_id,
            "response_blind_id": manifest_row["response_blind_id"],
            "answer_text": answer,
            "answer_text_sha256": answer_hash,
            "provider_payload_sha256": manifest_row["provider_payload_sha256"],
            "selected_execution_source": source_path,
            "selected_attempt_number": choice["selected_attempt_number"],
            "raw_response_source_sha256": raw_hash,
            "requested_model": attempt["requested_model"],
            "returned_model": attempt["returned_model"],
            "provider_response_id": attempt.get("provider_response_id"),
            "system_fingerprint": attempt.get("system_fingerprint"),
            "finish_reason": attempt.get("finish_reason"),
            "prompt_tokens": attempt["prompt_tokens"],
            "cached_input_tokens": attempt.get("cached_input_tokens"),
            "completion_tokens": attempt["completion_tokens"],
            "total_tokens": attempt["total_tokens"],
            "generation_status": status,
        }
        canonical.append(record)
        source_registry.append(
            {
                "schema_version": "c4-real-r3-response-source-registry-v1",
                "logical_generation_request_id": request_id,
                "response_blind_id": manifest_row["response_blind_id"],
                "provider_payload_sha256": manifest_row["provider_payload_sha256"],
                "selected_execution_source": source_path,
                "selected_attempt_number": choice["selected_attempt_number"],
                "raw_response_source_sha256": raw_hash,
                "selection_rule_id": "C4_REAL_R3_CANONICAL_ATTEMPT_SELECTION_RULE_V1",
                "selection_relationship": choice.get(
                    "original_terminal_selection_relationship",
                    "CONTINUATION_SINGLE_VALID_ATTEMPT",
                ),
            }
        )

    request_ids = [row["logical_generation_request_id"] for row in canonical]
    response_ids = [row["response_blind_id"] for row in canonical]
    payload_hashes = [row["provider_payload_sha256"] for row in canonical]
    require(len(set(request_ids)) == len(set(response_ids)) == len(set(payload_hashes)) == 147, "canonical identity collision")
    by_text: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in canonical:
        by_text[row["answer_text_sha256"]].append(row)
    duplicate_groups = [rows for rows in by_text.values() if len(rows) > 1]
    require(len(by_text) == 146, "distinct answer-text hash count differs")
    require(len(duplicate_groups) == 1 and len(duplicate_groups[0]) == 2, "duplicate-text structure differs")
    group = duplicate_groups[0]
    require(group[0]["answer_text_sha256"] == KNOWN_DUPLICATE_TEXT_SHA256, "known duplicate text hash differs")
    require(
        {row["logical_generation_request_id"] for row in group}
        == set(KNOWN_DUPLICATE_REQUEST_IDS),
        "known duplicate request pair differs",
    )
    require(len({row["response_blind_id"] for row in group}) == 2, "duplicate response-ID collision")
    require(len({row["provider_payload_sha256"] for row in group}) == 2, "duplicate Provider-payload collision")
    require(
        next(row for row in selection_rows if row["shard"] == "A" and row["logical_order"] == 40)["selected_attempt_number"] == 1,
        "Shard A order 40 selection differs",
    )
    require(
        next(row for row in selection_rows if row["shard"] == "C" and row["logical_order"] == 4)["selected_attempt_number"] == 1,
        "original Shard C order 4 selection differs",
    )

    usage_by_shard: dict[str, dict[str, int]] = {}
    for shard, attempts in attempt_rows.items():
        usage = {
            "logical_requests": EXPECTED_USAGE[shard]["logical_requests"],
            "physical_attempts": len(attempts),
            "prompt_tokens": sum(int(row["prompt_tokens"]) for row in attempts),
            "cached_input_tokens": sum(int(row.get("cached_input_tokens") or 0) for row in attempts),
            "completion_tokens": sum(int(row["completion_tokens"]) for row in attempts),
            "total_tokens": sum(int(row["total_tokens"]) for row in attempts),
        }
        require(usage == EXPECTED_USAGE[shard], f"Shard {shard} aggregate usage differs")
        usage_by_shard[shard] = usage
        terminal = R3_SOURCE_DIRS[shard] / "execution_output_v1/GENERATION_TERMINAL_JOURNAL.jsonl"
        require(sha256_file(terminal) == EXPECTED_SOURCE_IDENTITIES[shard]["terminal_journal_sha256"], f"Shard {shard} terminal hash differs")
        audit_name = (
            "continuation_execution_audit_v1.json"
            if shard == "C_CONTINUATION"
            else "generation_execution_audit_v1.json"
        )
        audit = load_json(R3_SOURCE_DIRS[shard] / audit_name)
        observed_answer_set = (
            audit.get("hashes", {}).get("answer_set_sha256")
            if isinstance(audit.get("hashes"), dict)
            else audit.get("answer_set_sha256")
        )
        require(
            observed_answer_set == EXPECTED_SOURCE_IDENTITIES[shard]["answer_set_sha256"],
            f"Shard {shard} original answer-set identity differs",
        )
    aggregate = {
        "frozen_logical_request_universe": 147,
        "physical_attempts": sum(row["physical_attempts"] for row in usage_by_shard.values()),
        "historical_redundant_retries": 2,
        "prompt_tokens": sum(row["prompt_tokens"] for row in usage_by_shard.values()),
        "cached_input_tokens": sum(row["cached_input_tokens"] for row in usage_by_shard.values()),
        "completion_tokens": sum(row["completion_tokens"] for row in usage_by_shard.values()),
        "total_tokens": sum(row["total_tokens"] for row in usage_by_shard.values()),
    }
    require(
        aggregate
        == {
            "frozen_logical_request_universe": 147,
            "physical_attempts": 149,
            "historical_redundant_retries": 2,
            "prompt_tokens": 127762,
            "cached_input_tokens": 14720,
            "completion_tokens": 23568,
            "total_tokens": 151330,
        },
        "aggregate generation usage differs",
    )
    usage_artifact = {
        "schema_version": "c4-real-r3-generation-usage-frozen-v1",
        "status": "PASS_AGGREGATE_USAGE_RECONCILED",
        "shards": usage_by_shard,
        "aggregate": aggregate,
        "redundant_retry_interpretation": "EXECUTION_ATTEMPTS_NOT_ADDITIONAL_EXPERIMENTAL_OBSERVATIONS",
        "cost_status": "NOT_COMPUTED_NO_FROZEN_PRICING_AUTHORITY",
    }
    return canonical, source_registry, usage_artifact


def build_duplicate_text_audit(canonical: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    groups: dict[str, list[Mapping[str, Any]]] = defaultdict(list)
    for row in canonical:
        groups[str(row["answer_text_sha256"])].append(row)
    duplicates = [rows for rows in groups.values() if len(rows) > 1]
    require(len(duplicates) == 1 and len(duplicates[0]) == 2, "duplicate-text audit population differs")
    rows = duplicates[0]
    return {
        "schema_version": "c4-real-r3-duplicate-text-identity-audit-v1",
        "status": "PASS_DISTINCT_RESPONSE_IDENTITIES_SHARED_TEXT_PERMITTED",
        "duplicate_groups": [
            {
                "answer_text_sha256": rows[0]["answer_text_sha256"],
                "group_size": len(rows),
                "identity_collision_status": "NO_REQUEST_RESPONSE_OR_PROVIDER_PAYLOAD_IDENTITY_COLLISION",
                "records": [
                    {
                        "logical_generation_request_id": row["logical_generation_request_id"],
                        "response_blind_id": row["response_blind_id"],
                        "provider_payload_sha256": row["provider_payload_sha256"],
                        "answer_text_sha256": row["answer_text_sha256"],
                        "group_size": len(rows),
                        "identity_collision_status": "DISTINCT_IDENTITY",
                    }
                    for row in sorted(rows, key=lambda item: item["logical_generation_request_id"])
                ],
            }
        ],
    }


def _parses_as_container(text: str, parser: str) -> bool:
    try:
        value = json.loads(text) if parser == "json" else ast.literal_eval(text)
    except (ValueError, SyntaxError, json.JSONDecodeError):
        return False
    return isinstance(value, (dict, list))


def build_format_audit(canonical: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    validator = load_module(
        "c4_real_r3d1_format_validator_v2",
        R3D0 / "c4_real_student_facing_response_validator_v2.py",
    )
    counts: Counter[str] = Counter()
    literal_occurrences: Counter[str] = Counter()
    affected_ids: set[str] = set()
    local_path_patterns = {
        "local_database_paths": re.compile(
            r"(?:/Users/|/home/|[A-Za-z]:\\\\|(?:^|[\\s'\"])(?:[^\\s'\"]+/)*[^\\s'\"]+\\.(?:db|sqlite|sqlite3)(?:$|[\\s'\"]))",
            re.IGNORECASE,
        ),
        "local_source_paths": re.compile(
            r"(?:/Users/|/home/|(?:^|[\\s'\"])(?:evaluation|src|app|tests)/[^\\s'\"]+)",
            re.IGNORECASE,
        ),
    }
    for row in canonical:
        text = str(row["answer_text"])
        stripped = text.strip()
        request_id = str(row["logical_generation_request_id"])
        counts["response_records"] += 1
        if stripped:
            counts["non_empty"] += 1
        if validator.validate_answer_text(text) == validator.VALID_STUDENT_FACING_RESPONSE:
            counts["validator_v2_valid"] += 1
        if not _parses_as_container(stripped, "json"):
            counts["not_json_container"] += 1
        if not _parses_as_container(stripped, "python"):
            counts["not_python_container"] += 1
        if not re.fullmatch(r"[^\\w\\s]+", stripped, flags=re.UNICODE):
            counts["not_punctuation_only"] += 1
        if not re.search(r"```|<\\?xml\\b|^\\s*</?[A-Za-z][^>]*>", text, re.IGNORECASE | re.MULTILINE):
            counts["no_raw_code_or_xml_block"] += 1
        for literal in LEAKAGE_LITERALS:
            hits = len(re.findall(re.escape(literal), text, flags=re.IGNORECASE))
            if hits:
                literal_occurrences[literal] += hits
                affected_ids.add(request_id)
        for label, pattern in local_path_patterns.items():
            hits = len(pattern.findall(text))
            if hits:
                literal_occurrences[label] += hits
                affected_ids.add(request_id)
    required_full = {
        "response_records",
        "non_empty",
        "validator_v2_valid",
        "not_json_container",
        "not_python_container",
        "not_punctuation_only",
        "no_raw_code_or_xml_block",
    }
    require(all(counts[name] == 147 for name in required_full), "final response format audit failed")
    require(not literal_occurrences and not affected_ids, "final response leakage scan failed")
    return {
        "schema_version": "c4-real-r3-final-response-format-audit-v1",
        "status": "PASS_MECHANICAL_FORMAT_AND_LITERAL_LEAKAGE_AUDIT",
        "audit_scope": "MECHANICAL_ONLY_NOT_RESPONSE_QUALITY_EVALUATION",
        "response_counts": {
            "canonical": 147,
            "outer_schema_valid": 147,
            "non_empty": counts["non_empty"],
            "validator_v2_valid_student_facing_response": counts["validator_v2_valid"],
            "json_object_or_array_answers": 147 - counts["not_json_container"],
            "python_dict_or_list_answers": 147 - counts["not_python_container"],
            "raw_internal_structures": 0,
            "punctuation_only_responses": 147 - counts["not_punctuation_only"],
            "raw_code_or_xml_blocks": 147 - counts["no_raw_code_or_xml_block"],
        },
        "literal_leakage_scan": {
            "literals": list(LEAKAGE_LITERALS),
            "local_database_path_patterns": True,
            "local_source_path_patterns": True,
            "total_occurrences": sum(literal_occurrences.values()),
            "affected_response_records": len(affected_ids),
            "occurrences_by_literal": dict(sorted(literal_occurrences.items())),
        },
        "response_quality_assessment_performed": False,
    }


def build_condition_response_mapping(
    canonical: Sequence[Mapping[str, Any]],
) -> tuple[
    list[dict[str, Any]],
    list[dict[str, Any]],
    dict[str, Any],
    dict[str, Any],
    dict[tuple[str, str], dict[str, Any]],
]:
    mapping_path = RESTRICTED / "c4_real_condition_to_unique_request_mapping_frozen_v3.csv"
    registry_path = RESTRICTED / "c4_real_condition_generation_payload_registry_frozen_v3.jsonl"
    mapping_rows = load_csv(mapping_path)
    registry_rows = load_jsonl(registry_path)
    applicability_rows = load_jsonl(I1 / "c4_real_condition_applicability_maps_frozen_v1.jsonl")
    mechanism_rows = load_jsonl(I1 / "c4_real_condition_mechanism_records_frozen_v1.jsonl")
    require(len(mapping_rows) == len(registry_rows) == len(applicability_rows) == len(mechanism_rows) == 558, "condition population differs")

    registry = {(row["scenario_id"], row["mode_id"]): row for row in registry_rows}
    applicability = {(row["scenario_id"], row["mode"]): row for row in applicability_rows}
    mechanisms = {(row["scenario_id"], row["mode"]): row for row in mechanism_rows}
    require(len(registry) == len(applicability) == len(mechanisms) == 558, "condition key collision")
    responses = {row["logical_generation_request_id"]: row for row in canonical}
    require(len(responses) == 147, "canonical response index collision")

    condition_records: list[dict[str, Any]] = []
    response_mapping: list[dict[str, Any]] = []
    applicability_recomputed = load_module(
        "rq3_r3d1_applicability",
        PROTOCOL / "rq3_judge_request_builder.py",
    )
    by_response_payloads: dict[str, set[str]] = defaultdict(set)
    by_scenario: dict[str, list[dict[str, Any]]] = defaultdict(list)
    seen_conditions: set[str] = set()
    for mapping in sorted(mapping_rows, key=lambda row: int(row["logical_order"])):
        key = (mapping["scenario_id"], mapping["mode_id"])
        require(key in registry and key in applicability and key in mechanisms, "condition join key missing")
        source = registry[key]
        app = applicability[key]
        mechanism = mechanisms[key]
        request_id = mapping["logical_generation_request_id"]
        require(request_id in responses, "condition lacks a canonical response")
        response = responses[request_id]
        payload_hash = mapping["provider_payload_sha256_v3"]
        require(source["provider_payload_sha256_v3"] == payload_hash, "condition registry payload mismatch")
        require(response["provider_payload_sha256"] == payload_hash, "condition/response payload mismatch")
        require(mapping["response_blind_id"] == response["response_blind_id"], "expected response blind ID mismatch")
        require(mapping["replay_record_id"] == source["replay_record_id"] == mechanism["replay_record_id"], "condition record ID mismatch")
        require(mapping["replay_record_id"] not in seen_conditions, "duplicate condition ID")
        seen_conditions.add(mapping["replay_record_id"])
        frozen_map = app["frozen_applicability_map"]
        recomputed = applicability_recomputed.freeze_applicability(app["source_metadata"])
        require(recomputed == frozen_map, "applicability map differs from frozen pre-response metadata")
        record = {
            "schema_version": "c4-real-r3-condition-response-record-frozen-v1",
            "logical_order": int(mapping["logical_order"]),
            "replay_record_id": mapping["replay_record_id"],
            "scenario_id": mapping["scenario_id"],
            "mode_id": mapping["mode_id"],
            "current_page": mapping["current_page"],
            "route_signature": mapping["route_signature"],
            "activation_mask": source["activation_mask"],
            "mechanism_metadata": mechanism,
            "logical_generation_request_id": request_id,
            "response_blind_id": response["response_blind_id"],
            "provider_payload_sha256": payload_hash,
            "answer_text": response["answer_text"],
            "answer_text_sha256": response["answer_text_sha256"],
            "selected_execution_source": response["selected_execution_source"],
            "selected_attempt_number": response["selected_attempt_number"],
            "raw_response_source_sha256": response["raw_response_source_sha256"],
            "generation_status": response["generation_status"],
            "frozen_applicability_map": frozen_map,
            "applicability_source_metadata": app["source_metadata"],
            "provider_generation_payload_v3": source["provider_payload"],
        }
        condition_records.append(record)
        by_scenario[mapping["scenario_id"]].append(record)
        by_response_payloads[response["response_blind_id"]].add(payload_hash)
        response_mapping.append(
            {
                "response_blind_id": response["response_blind_id"],
                "logical_generation_request_id": request_id,
                "provider_payload_sha256": payload_hash,
                "replay_record_id": mapping["replay_record_id"],
            }
        )

    require(len(condition_records) == len(response_mapping) == len(seen_conditions) == 558, "condition-response mapping count differs")
    require(len({row["response_blind_id"] for row in response_mapping}) == 147, "mapped response identity count differs")
    require(558 - 147 == 411, "exact-payload duplicate mapping arithmetic differs")
    require(all(len(values) == 1 for values in by_response_payloads.values()), "response identity shared across unequal payloads")

    primary = ("CLARITY", "CONTEXT_AWARENESS", "RELIABILITY")
    for record in condition_records:
        criteria = record["frozen_applicability_map"]["criteria"]
        require(all(criteria[name] is True for name in primary), "always-applicable criterion changed")
        require(sum(criteria.values()) >= 3, "fewer than three applicable criteria")
    memory_scenarios = {
        scenario
        for scenario, rows in by_scenario.items()
        if any(row["applicability_source_metadata"]["long_term_memory_relevant"] for row in rows)
    }
    planning_scenarios = {
        scenario
        for scenario, rows in by_scenario.items()
        if any(row["applicability_source_metadata"]["request_requires_advice"] for row in rows)
    }
    for scenario in memory_scenarios:
        require(all(row["frozen_applicability_map"]["criteria"]["PERSONALISATION"] for row in by_scenario[scenario]), "Memory-on/off PERSONALISATION applicability changed")
    for scenario in planning_scenarios:
        require(all(row["frozen_applicability_map"]["criteria"]["ACTIONABILITY"] for row in by_scenario[scenario]), "Planning-on/off ACTIONABILITY applicability changed")

    mapping_metadata = {
        "schema_version": "c4-real-r3-response-mapping-metadata-v1",
        "status": "PASS_RESTRICTED_558_CONDITION_RESPONSE_JOIN",
        "key_commitment": HMAC_KEY_COMMITMENT,
        "mapping_files": {},
        "condition_response_records": 558,
        "unique_response_identities": 147,
        "exact_payload_duplicate_mappings": 411,
        "missing_condition_ids": 0,
        "duplicate_condition_ids": 0,
        "response_identities_shared_across_unequal_payloads": 0,
        "raw_mapping_content_in_metadata": False,
    }
    applicability_audit = {
        "schema_version": "c4-real-r3-applicability-integrity-audit-v1",
        "status": "PASS_ALL_PRE_RESPONSE_APPLICABILITY_MAPS_UNCHANGED",
        "record_count": 558,
        "source_sha256": sha256_file(I1 / "c4_real_condition_applicability_maps_frozen_v1.jsonl"),
        "clarity_applicable": 558,
        "context_awareness_applicable": 558,
        "reliability_applicable": 558,
        "minimum_applicable_primary_criteria": min(
            row["frozen_applicability_map"]["applicable_primary_count"] for row in condition_records
        ),
        "memory_relevant_family_count": len(memory_scenarios),
        "memory_relevant_records_preserving_personalisation": sum(len(by_scenario[s]) for s in memory_scenarios),
        "planning_relevant_family_count": len(planning_scenarios),
        "planning_relevant_records_preserving_actionability": sum(len(by_scenario[s]) for s in planning_scenarios),
        "applicability_inferred_from_answer_text": False,
        "applicability_modifications": 0,
    }
    return condition_records, response_mapping, mapping_metadata, applicability_audit, registry


RENDERED_HEADERS = (
    "CURRENT LAD PAGE",
    "STUDENT REQUEST",
    "VISIBLE CONVERSATION HISTORY",
    "DASHBOARD EVIDENCE",
    "COURSE EVIDENCE",
    "LEARNER MEMORY",
    "PLANNING SUPPORT",
    "LIMITATIONS",
)


def parse_rendered_generation_context(text: str, expected_page: str) -> dict[str, Any]:
    require(isinstance(text, str) and text.endswith("\n"), "V3 rendered context is malformed")
    pattern = re.compile(
        r"^(" + "|".join(re.escape(header) for header in RENDERED_HEADERS) + r")\n",
        re.MULTILINE,
    )
    matches = list(pattern.finditer(text))
    require(matches, "V3 rendered context contains no sections")
    observed_headers = [match.group(1) for match in matches]
    require(len(observed_headers) == len(set(observed_headers)), "duplicate V3 rendered section")
    positions = [RENDERED_HEADERS.index(header) for header in observed_headers]
    require(positions == sorted(positions), "V3 rendered section order differs")
    sections: dict[str, str] = {}
    for index, match in enumerate(matches):
        end = matches[index + 1].start() if index + 1 < len(matches) else len(text)
        sections[match.group(1)] = text[match.end() : end].strip()
    require(sections.get("CURRENT LAD PAGE") == expected_page, "rendered current page mismatch")
    require(bool(sections.get("STUDENT REQUEST", "").strip()), "rendered student query absent")
    limitations = sections.get("LIMITATIONS") or None
    dashboard = {
        "evidence_text": sections.get("DASHBOARD EVIDENCE") or None,
        "cross_source_availability_notes": limitations,
    }
    return {
        "student_query": sections["STUDENT REQUEST"],
        "current_lad_page": sections["CURRENT LAD PAGE"],
        "visible_conversation_history": (
            [sections["VISIBLE CONVERSATION HISTORY"]]
            if sections.get("VISIBLE CONVERSATION HISTORY")
            else []
        ),
        "frozen_dashboard_evidence": dashboard,
        "course_evidence_available_in_condition": sections.get("COURSE EVIDENCE") or None,
        "long_term_memory_available_in_condition": sections.get("LEARNER MEMORY") or None,
        "planning_support_available_in_condition": sections.get("PLANNING SUPPORT") or None,
    }


def _judge_configuration(prompt_hash: str, schema_hash: str, rubric_hash: str, applicability_hash: str) -> dict[str, Any]:
    return {
        "schema_version": "c4-real-judge-configuration-r3d1-r1-v1",
        "status": "FROZEN_NO_JUDGE_CALL_AUTHORIZED_IN_R3D1_R1",
        "model": JUDGE_MODEL,
        "endpoint": "OpenAI Chat Completions",
        "endpoint_path": "/v1/chat/completions",
        "temperature": JUDGE_TEMPERATURE,
        "max_output_tokens": JUDGE_MAX_OUTPUT_TOKENS,
        "automatic_sdk_retries": 0,
        "manual_retry": {
            "maximum_retries": 1,
            "permitted_only_after": [
                "INVALID_JSON",
                "STRICT_SCHEMA_VALIDATION_FAILED",
                "APPLICABILITY_CONTRACT_VIOLATION",
            ],
            "request_bytes": "IDENTICAL",
            "correction_message_added": False,
        },
        "streaming": False,
        "tools": "NONE",
        "serial_execution": True,
        "minimum_seconds_between_initial_request_starts": 2,
        "judge_prompt_sha256": prompt_hash,
        "provider_schema_sha256": schema_hash,
        "primary_rubric_sha256": rubric_hash,
        "applicability_contract_sha256": applicability_hash,
        "semantic_contract": "AUTHORITATIVE_RQ3_0B4_V1_UNCHANGED",
        "primary_outcome": "OVERALL_APPLICABLE_MEAN",
        "secondary_audits_excluded_from_primary_mean": True,
        "judge_calls": 0,
    }


def _judge_execution_contract(configuration_sha256: str) -> dict[str, Any]:
    return {
        "schema_version": "c4-real-judge-execution-contract-v1",
        "status": "FROZEN_FOR_FUTURE_SEPARATELY_AUTHORIZED_EXECUTION",
        "python_executable": "/opt/anaconda3/bin/python3",
        "python_version": "3.13.5",
        "openai_sdk_version": "1.109.1",
        "automatic_sdk_retries": 0,
        "serial_execution": True,
        "minimum_seconds_between_initial_request_starts": 2,
        "preflight_receipt_before_calls": True,
        "attempt_and_terminal_append_flush_fsync": True,
        "existing_output_directory_permitted": False,
        "automatic_resume": False,
        "raw_invalid_output_preserved": True,
        "returned_model_identity_verified": JUDGE_MODEL,
        "non_retryable_error_policy": "STOP_ENTIRE_SHARD",
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
        "condition_comparisons_inside_worker": False,
        "configuration_sha256": configuration_sha256,
        "execution_authorized": False,
    }


def _build_provider_judge_payload(
    blind_request: Mapping[str, Any], prompt: str, schema: Mapping[str, Any]
) -> dict[str, Any]:
    require(prompt.count("{{BLIND_JUDGE_REQUEST_JSON}}") == 1, "Judge Prompt placeholder count differs")
    request_json = canonical_json_bytes(dict(blind_request)).decode("utf-8")
    rendered_prompt = prompt.replace("{{BLIND_JUDGE_REQUEST_JSON}}", request_json)
    return {
        "model": JUDGE_MODEL,
        "messages": [{"role": "system", "content": rendered_prompt}],
        "temperature": JUDGE_TEMPERATURE,
        "max_tokens": JUDGE_MAX_OUTPUT_TOKENS,
        "stream": False,
        "response_format": {
            "type": "json_schema",
            "json_schema": {
                "name": "c4_real_judge_response_v2_provider_compatible",
                "strict": True,
                "schema": dict(schema),
            },
        },
    }


def _estimated_input_tokens(provider_payload: Mapping[str, Any]) -> int:
    messages = provider_payload["messages"]
    message_bytes = sum(len(canonical_json_bytes(message)) for message in messages)
    response_format_bytes = len(canonical_json_bytes(provider_payload["response_format"]))
    # Predeclared deterministic approximation used only for Shard balancing.
    return math.ceil((message_bytes + response_format_bytes + 16) / 4)


def _forbid_evaluation_identity(value: Any, path: str = "$") -> None:
    forbidden_keys = {
        "scenario_id",
        "scenario_family_id",
        "family_id",
        "mode",
        "mode_id",
        "condition",
        "condition_id",
        "condition_name",
        "route",
        "route_id",
        "route_signature",
        "p3",
        "gold",
        "expected_winner",
        "dataset_group",
        "generation_shard",
        "generation_attempt_number",
    }
    forbidden_values = LEAKAGE_LITERALS[:9] + (
        "BASE_NEVER_ON",
        "ALWAYS_ON",
        "ORACLE_ROUTE",
        "PREDICTED_ROUTE",
    )
    if isinstance(value, Mapping):
        for key, child in value.items():
            require(isinstance(key, str), f"non-string Judge request key at {path}")
            require(key.casefold() not in forbidden_keys, f"forbidden Judge request key at {path}.{key}")
            _forbid_evaluation_identity(child, f"{path}.{key}")
    elif isinstance(value, list):
        for index, child in enumerate(value):
            _forbid_evaluation_identity(child, f"{path}[{index}]")
    elif isinstance(value, str):
        require(not any(token.casefold() in value.casefold() for token in forbidden_values), f"forbidden Judge request token at {path}")
        require(not re.search(r"(?<![A-Za-z0-9])P3(?![A-Za-z0-9])", value, re.IGNORECASE), f"P3 token in Judge request at {path}")


class DisjointSet:
    def __init__(self, values: Iterable[str]) -> None:
        self.parent = {value: value for value in values}

    def find(self, value: str) -> str:
        parent = self.parent[value]
        if parent != value:
            self.parent[value] = self.find(parent)
        return self.parent[value]

    def union(self, left: str, right: str) -> None:
        a, b = self.find(left), self.find(right)
        if a != b:
            if b < a:
                a, b = b, a
            self.parent[b] = a


def build_judge_universe(
    condition_records: Sequence[Mapping[str, Any]], key: bytes
) -> tuple[
    list[dict[str, Any]],
    list[dict[str, Any]],
    dict[str, Any],
    dict[str, Any],
    dict[str, Any],
    bytes,
    bytes,
]:
    prompt_path = I1 / "c4_real_judge_prompt_v2_provider_compatible.txt"
    schema_path = I1 / "c4_real_judge_schema_v2_provider_compatible.json"
    rubric_path = PROTOCOL / "rq3_primary_eight_criterion_rubric_v1.json"
    applicability_contract_path = PROTOCOL / "rq3_dimension_applicability_v1.json"
    prompt_bytes = prompt_path.read_bytes()
    schema_bytes = schema_path.read_bytes()
    rubric_bytes = rubric_path.read_bytes()
    applicability_bytes = applicability_contract_path.read_bytes()
    prompt_hash = sha256_bytes(prompt_bytes)
    schema_hash = sha256_bytes(schema_bytes)
    rubric_hash = sha256_bytes(rubric_bytes)
    applicability_hash = sha256_bytes(applicability_bytes)
    require(prompt_hash == "5b99b52bef760daa4e2fc8ae6ab13cead7e031b9d41b52d41e88617d906c35f3", "Judge Prompt hash changed")
    require(schema_hash == "caf69ff4e8c27b71805414b29caf3b87fa5da92bf0df0dec23c6945b2019be30", "Judge schema hash changed")
    require(rubric_hash == "be955850ab2669b8d7380b96a1ab335dc344d89d54dd85d649118a4d86385350", "Judge rubric hash changed")
    require(applicability_hash == "bee7bf9d681004f4ab5be549053b7dbeb2f7726361217251495a167257460b0e", "applicability contract hash changed")
    prompt = prompt_bytes.decode("utf-8")
    schema = json.loads(schema_bytes)
    config = _judge_configuration(prompt_hash, schema_hash, rubric_hash, applicability_hash)
    config_bytes = pretty_json_bytes(config)
    config_hash = sha256_bytes(config_bytes)
    execution_contract = _judge_execution_contract(config_hash)
    execution_contract_bytes = pretty_json_bytes(execution_contract)
    request_validator = load_module(
        "rq3_r3d1_judge_request_contract",
        PROTOCOL / "rq3_judge_request_builder.py",
    )

    unique_by_payload: dict[str, dict[str, Any]] = {}
    condition_mapping: list[dict[str, Any]] = []
    assignments_by_payload: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for condition in condition_records:
        generation_payload = condition["provider_generation_payload_v3"]
        messages = generation_payload.get("messages")
        require(isinstance(messages, list) and len(messages) == 2, "generation payload message shape differs")
        rendered_context = messages[1].get("content")
        parsed = parse_rendered_generation_context(rendered_context, condition["current_page"])
        blind_without_id = {
            "schema_version": "rq3-blind-judge-request-v1",
            **parsed,
            "candidate_response": condition["answer_text"],
            "frozen_applicability_map": condition["frozen_applicability_map"],
        }
        identity_basis = {
            "blind_request_without_result_id": blind_without_id,
            "judge_prompt_sha256": prompt_hash,
            "judge_schema_sha256": schema_hash,
            "judge_configuration_sha256": config_hash,
            "judge_rubric_sha256": rubric_hash,
        }
        basis_hash = sha256_bytes(canonical_json_bytes(identity_basis))
        logical_id = opaque_id(key, JUDGE_DOMAIN, "logical-request-id", basis_hash, "C4J1-", 24)
        result_id = opaque_id(key, JUDGE_DOMAIN, "result-blind-id", basis_hash, "R3B-", 20)
        blind_request = {**blind_without_id, "response_blind_id": result_id}
        blind_request = request_validator.validate_blind_judge_request(blind_request)
        _forbid_evaluation_identity(blind_request)
        provider_payload = _build_provider_judge_payload(blind_request, prompt, schema)
        payload_bytes = canonical_json_bytes(provider_payload)
        payload_hash = sha256_bytes(payload_bytes)
        record = {
            "schema_version": "c4-real-unique-judge-request-frozen-v1",
            "logical_judge_request_id": logical_id,
            "judge_result_blind_id": result_id,
            "provider_payload_sha256": payload_hash,
            "estimated_input_tokens": _estimated_input_tokens(provider_payload),
            "shard_id": None,
            "provider_payload": provider_payload,
        }
        prior = unique_by_payload.setdefault(
            payload_hash,
            {
                "bytes": payload_bytes,
                "record": record,
                "basis_hash": basis_hash,
                "blind_request": blind_request,
            },
        )
        require(prior["bytes"] == payload_bytes, "Judge Provider-payload hash collision")
        require(prior["record"]["logical_judge_request_id"] == logical_id, "Judge ID instability")
        mapping = {
            "logical_order": condition["logical_order"],
            "replay_record_id": condition["replay_record_id"],
            "scenario_id": condition["scenario_id"],
            "mode_id": condition["mode_id"],
            "generation_logical_request_id": condition["logical_generation_request_id"],
            "generation_response_blind_id": condition["response_blind_id"],
            "judge_logical_request_id": logical_id,
            "judge_result_blind_id": result_id,
            "judge_provider_payload_sha256": payload_hash,
            "shard_id": None,
        }
        condition_mapping.append(mapping)
        assignments_by_payload[payload_hash].append(mapping)

    require(len(condition_mapping) == 558, "condition-to-Judge mapping count differs")
    require(len(unique_by_payload) <= 558, "Judge deduplication count invalid")
    require(len({row["replay_record_id"] for row in condition_mapping}) == 558, "Judge condition mapping collision")
    require(len({item["record"]["logical_judge_request_id"] for item in unique_by_payload.values()}) == len(unique_by_payload), "Judge logical ID collision")
    require(len({item["record"]["judge_result_blind_id"] for item in unique_by_payload.values()}) == len(unique_by_payload), "Judge result ID collision")

    # Build connected family components so a request shared by more than one
    # family cannot split those families across Shards.
    scenarios = sorted({row["scenario_id"] for row in condition_mapping})
    dsu = DisjointSet(scenarios)
    for mappings in assignments_by_payload.values():
        linked = sorted({row["scenario_id"] for row in mappings})
        for scenario in linked[1:]:
            dsu.union(linked[0], scenario)
    component_scenarios: dict[str, set[str]] = defaultdict(set)
    for scenario in scenarios:
        component_scenarios[dsu.find(scenario)].add(scenario)
    scenario_to_component = {
        scenario: root for root, members in component_scenarios.items() for scenario in members
    }
    component_payloads: dict[str, set[str]] = defaultdict(set)
    component_pages: dict[str, set[str]] = defaultdict(set)
    component_modes: dict[str, set[str]] = defaultdict(set)
    for payload_hash, mappings in assignments_by_payload.items():
        roots = {scenario_to_component[row["scenario_id"]] for row in mappings}
        require(len(roots) == 1, "shared Judge request spans Shard components")
        root = next(iter(roots))
        component_payloads[root].add(payload_hash)
        component_modes[root].update(row["mode_id"] for row in mappings)
    page_by_scenario = {
        row["scenario_id"]: row["current_page"] for row in condition_records
    }
    for root, members in component_scenarios.items():
        component_pages[root].update(page_by_scenario[scenario] for scenario in members)

    components: list[dict[str, Any]] = []
    for root, members in component_scenarios.items():
        payloads = component_payloads[root]
        components.append(
            {
                "root": root,
                "scenarios": members,
                "payloads": payloads,
                "tokens": sum(unique_by_payload[value]["record"]["estimated_input_tokens"] for value in payloads),
                "count": len(payloads),
                "pages": component_pages[root],
                "modes": component_modes[root],
                "tie": hashlib.sha256(
                    canonical_json_bytes(
                        ["c4-real-judge-sharding-v1", SEED, sorted(members), sorted(payloads)]
                    )
                ).hexdigest(),
            }
        )
    components.sort(key=lambda item: (-item["tokens"], -item["count"], item["tie"]))
    all_pages = {row["current_page"] for row in condition_records}
    all_modes = {row["mode_id"] for row in condition_records}
    shard_state = {
        shard: {"tokens": 0, "count": 0, "pages": set(), "modes": set(), "scenarios": set(), "payloads": set()}
        for shard in ("A", "B", "C")
    }
    for component in components:
        candidates: list[tuple[tuple[Any, ...], str]] = []
        for shard in ("A", "B", "C"):
            projected_tokens = {name: state["tokens"] for name, state in shard_state.items()}
            projected_counts = {name: state["count"] for name, state in shard_state.items()}
            projected_pages = {name: set(state["pages"]) for name, state in shard_state.items()}
            projected_modes = {name: set(state["modes"]) for name, state in shard_state.items()}
            projected_tokens[shard] += component["tokens"]
            projected_counts[shard] += component["count"]
            projected_pages[shard].update(component["pages"])
            projected_modes[shard].update(component["modes"])
            score = (
                max(projected_tokens.values()) - min(projected_tokens.values()),
                max(projected_counts.values()) - min(projected_counts.values()),
                sum(len(all_pages - pages) for pages in projected_pages.values()),
                sum(len(all_modes - modes) for modes in projected_modes.values()),
                hashlib.sha256(
                    canonical_json_bytes(["c4-real-judge-sharding-tie-v1", SEED, component["tie"], shard])
                ).hexdigest(),
            )
            candidates.append((score, shard))
        _score, chosen = min(candidates)
        state = shard_state[chosen]
        state["tokens"] += component["tokens"]
        state["count"] += component["count"]
        state["pages"].update(component["pages"])
        state["modes"].update(component["modes"])
        state["scenarios"].update(component["scenarios"])
        state["payloads"].update(component["payloads"])

    payload_to_shard: dict[str, str] = {}
    scenario_to_shard: dict[str, str] = {}
    for shard, state in shard_state.items():
        for payload_hash in state["payloads"]:
            require(payload_hash not in payload_to_shard, "Judge request assigned to multiple Shards")
            payload_to_shard[payload_hash] = shard
        for scenario in state["scenarios"]:
            require(scenario not in scenario_to_shard, "scenario family assigned to multiple Shards")
            scenario_to_shard[scenario] = shard
    require(len(payload_to_shard) == len(unique_by_payload), "unassigned Judge request")
    require(len(scenario_to_shard) == len(scenarios), "unassigned scenario family")
    for payload_hash, mappings in assignments_by_payload.items():
        shard = payload_to_shard[payload_hash]
        require(all(scenario_to_shard[row["scenario_id"]] == shard for row in mappings), "family-atomic Shard invariant failed")
        unique_by_payload[payload_hash]["record"]["shard_id"] = shard
        for row in mappings:
            row["shard_id"] = shard

    unique_records: list[dict[str, Any]] = []
    for shard in ("A", "B", "C"):
        rows = [
            value["record"]
            for payload_hash, value in unique_by_payload.items()
            if payload_to_shard[payload_hash] == shard
        ]
        rows.sort(
            key=lambda row: hmac_hex(
                key,
                JUDGE_DOMAIN,
                "shard-request-order",
                shard,
                row["logical_judge_request_id"],
            )
        )
        unique_records.extend(rows)

    known_sets: list[set[str]] = []
    for generation_id in KNOWN_DUPLICATE_REQUEST_IDS:
        known_sets.append(
            {
                row["judge_logical_request_id"]
                for row in condition_mapping
                if row["generation_logical_request_id"] == generation_id
            }
        )
    require(all(known_sets), "known duplicate response lacks Judge mapping")
    require(known_sets[0].isdisjoint(known_sets[1]), "equal answer text collapsed distinct Judge payloads")

    shard_summary = {
        shard: {
            "unique_judge_requests": shard_state[shard]["count"],
            "estimated_input_tokens": shard_state[shard]["tokens"],
            "scenario_family_count": len(shard_state[shard]["scenarios"]),
            "page_coverage_count": len(shard_state[shard]["pages"]),
            "response_condition_coverage_count": len(shard_state[shard]["modes"]),
            "maximum_physical_attempts": shard_state[shard]["count"] * 2,
        }
        for shard in ("A", "B", "C")
    }
    require(sum(item["unique_judge_requests"] for item in shard_summary.values()) == len(unique_records), "Judge Shard request arithmetic differs")
    judge_audit = {
        "schema_version": "c4-real-judge-request-deduplication-audit-v1",
        "status": "PASS_COMPLETE_PROVIDER_PAYLOAD_BYTE_IDENTITY_ONLY",
        "condition_to_judge_mappings": 558,
        "unique_judge_requests": len(unique_records),
        "deduplicated_condition_mappings": 558 - len(unique_records),
        "deduplication_key": "COMPLETE_CANONICAL_PROVIDER_PAYLOAD_BYTES",
        "answer_text_sha256_used_as_deduplication_key": False,
        "known_equal_text_generation_responses": 2,
        "known_equal_text_judge_request_sets_disjoint": True,
        "known_equal_text_collapsed_due_to_text_only": False,
        "opaque_id_domain": JUDGE_DOMAIN,
        "generation_ids_reused_as_judge_ids": False,
        "scenario_family_atomic_shards": True,
        "estimated_token_method": "CEIL_UTF8_BYTES_OF_MESSAGES_AND_RESPONSE_FORMAT_PLUS_16_DIVIDED_BY_4",
        "shards": shard_summary,
    }
    judge_mapping_metadata = {
        "schema_version": "c4-real-judge-restricted-mapping-metadata-v1",
        "status": "PASS_RESTRICTED_MAPPING_FROZEN",
        "key_commitment": HMAC_KEY_COMMITMENT,
        "condition_mapping_filename": "c4_real_condition_to_unique_judge_request_mapping_v1.csv",
        "condition_mapping_rows": 558,
        "unique_judge_request_count": len(unique_records),
        "raw_mapping_content_in_metadata": False,
    }
    judge_protocol = {
        "configuration": config,
        "configuration_bytes": config_bytes,
        "configuration_sha256": config_hash,
        "execution_contract": execution_contract,
        "execution_contract_bytes": execution_contract_bytes,
        "prompt_bytes": prompt_bytes,
        "prompt_sha256": prompt_hash,
        "schema_bytes": schema_bytes,
        "schema_sha256": schema_hash,
        "rubric_bytes": rubric_bytes,
        "rubric_sha256": rubric_hash,
        "applicability_bytes": applicability_bytes,
        "applicability_sha256": applicability_hash,
    }
    return (
        unique_records,
        condition_mapping,
        judge_audit,
        judge_mapping_metadata,
        judge_protocol,
        config_bytes,
        execution_contract_bytes,
    )


def _extract_blind_request(provider_payload: Mapping[str, Any]) -> dict[str, Any]:
    content = provider_payload["messages"][0]["content"]
    begin = "BEGIN_BLIND_JUDGE_REQUEST_JSON\n"
    end = "\nEND_BLIND_JUDGE_REQUEST_JSON"
    require(content.count(begin) == 1 and content.count(end) == 1, "blind Judge request boundary differs")
    value = json.loads(content.split(begin, 1)[1].rsplit(end, 1)[0])
    require(isinstance(value, dict), "blind Judge request is not an object")
    return value


def select_human_families(
    condition_records: Sequence[Mapping[str, Any]],
    canonical_response_manifest_sha256: str,
    key: bytes,
) -> tuple[list[str], dict[str, Any]]:
    cohort_path = REAL / "track_d_dataset/final_62_scenario_identity_v1.json"
    cohort = load_json(cohort_path)
    rows = cohort["rows"]
    require(len(rows) == 62, "human-sampling family population differs")
    by_scenario = {row["scenario_id"]: row for row in rows}
    require(len(by_scenario) == 62, "human-sampling scenario family collision")
    condition_scenarios = {row["scenario_id"] for row in condition_records}
    require(set(by_scenario) == condition_scenarios, "human-sampling family/cohort mismatch")
    modes_by_scenario: dict[str, set[str]] = defaultdict(set)
    for condition in condition_records:
        modes_by_scenario[condition["scenario_id"]].add(condition["mode_id"])
    require(all(len(modes) == 9 for modes in modes_by_scenario.values()), "eligible condition coverage differs")

    tokens_by_family: dict[str, set[str]] = {}
    capability_tokens = {
        "RAG-required",
        "Memory-required",
        "Planning-required",
        "neither-required",
        "RAG+Memory",
    }
    for scenario, row in by_scenario.items():
        required = set(row["required_capabilities"])
        rag = "course_material_retrieval" in required
        memory = "short_term_memory" in required
        planning = "recommendation_planning" in required
        tokens: set[str] = set()
        if rag:
            tokens.add("RAG-required")
        if memory:
            tokens.add("Memory-required")
        if planning:
            tokens.add("Planning-required")
        if not (rag or memory or planning):
            tokens.add("neither-required")
        if rag and memory:
            tokens.add("RAG+Memory")
        tokens.add("PAGE:" + row["primary_input"]["current_page"])
        tokens.update("CONDITION:" + mode for mode in modes_by_scenario[scenario])
        tokens_by_family[scenario] = tokens

    prevalence: Counter[str] = Counter()
    for tokens in tokens_by_family.values():
        prevalence.update(tokens)
    pages = {token for token in prevalence if token.startswith("PAGE:")}
    conditions = {token for token in prevalence if token.startswith("CONDITION:")}
    required_tokens = capability_tokens | pages | conditions
    require(all(prevalence[token] > 0 for token in required_tokens), "a required human-sampling stratum is absent")
    cohort_manifest_sha256 = sha256_file(cohort_path)
    schema_version = "c4-real-human-validation-family-sampling-v1"
    selected: list[str] = []
    selected_counts: Counter[str] = Counter()
    target = 12
    while len(selected) < target:
        scored: list[tuple[Fraction, Fraction, str, str]] = []
        covered = set(selected_counts)
        for scenario, tokens in tokens_by_family.items():
            if scenario in selected:
                continue
            uncovered_gain = sum(
                (Fraction(1, prevalence[token]) for token in tokens if token not in covered),
                Fraction(0, 1),
            )
            balance_gain = sum(
                (
                    Fraction(1, prevalence[token] * (1 + selected_counts[token]))
                    for token in tokens
                ),
                Fraction(0, 1),
            )
            tie = hashlib.sha256(
                canonical_json_bytes(
                    [
                        schema_version,
                        SEED,
                        cohort_manifest_sha256,
                        canonical_response_manifest_sha256,
                        scenario,
                    ]
                )
            ).hexdigest()
            scored.append((uncovered_gain, balance_gain, tie, scenario))
        require(scored, "human-sampling candidate set exhausted")
        best_gain = max((item[0], item[1]) for item in scored)
        chosen = min(item for item in scored if (item[0], item[1]) == best_gain)[3]
        selected.append(chosen)
        selected_counts.update(tokens_by_family[chosen])
    missing = sorted(required_tokens - set(selected_counts))
    require(not missing, f"human sample lacks required strata: {missing}")
    family_blind_ids = [
        opaque_id(key, HUMAN_DOMAIN, "family-blind-id", scenario, "HFS1-", 20)
        for scenario in selected
    ]
    metadata = {
        "schema_version": schema_version,
        "status": "PASS_DETERMINISTIC_PREDECLARED_FAMILY_SELECTION",
        "selection_unit": "scenario_family_id",
        "eligible_family_count": 62,
        "target_family_count": 12,
        "selected_family_count": len(selected),
        "selected_family_blind_ids": family_blind_ids,
        "deterministic_seed": SEED,
        "cohort_manifest_sha256": cohort_manifest_sha256,
        "canonical_response_manifest_sha256": canonical_response_manifest_sha256,
        "selection_algorithm": [
            "Compute frozen family tokens and token prevalence.",
            "Maximise uncovered gain as the sum of inverse token prevalence.",
            "Then maximise balance gain using selected token counts.",
            "Break exact ties by ascending manifest-bound SHA-256.",
            "Stop at 12 families and require complete stratum coverage.",
        ],
        "coverage": {
            "capability_strata": len(capability_tokens),
            "lad_pages": len(pages),
            "predeclared_response_conditions": len(conditions),
            "missing_required_tokens": 0,
        },
        "answer_quality_used_for_selection": False,
        "answer_length_used_for_selection": False,
        "duplicate_text_status_used_for_selection": False,
        "judge_result_used_for_selection": False,
        "condition_performance_used_for_selection": False,
        "raw_family_identity_in_metadata": False,
    }
    return selected, metadata


def _human_guide_bytes() -> bytes:
    text = """# C4 REAL independent human-rater guide

Status: `FROZEN_UNRATED_PACKET_R3D1_R1`

Rate only the candidate response shown in each row against the evidence visible in that same row. Do not infer an experimental condition, capability route, expected winner, or hidden information. Do not compare against the other rater or an LLM Judge. The order is deliberately blinded and differs between Reviewer A and Reviewer B.

Use integer scores 1–5 for applicable criteria and write `NA` exactly for a criterion whose applicability flag is false. Applicability was frozen before responses were scored. Never use `NA` merely because the response performs poorly. Keep each rationale short and criterion-specific. All rating and rationale cells begin blank.

The eight criteria are:

- CLARITY: understandable, well organised, and free of unnecessary jargon.
- PERSONALISATION: appropriate use of available student-specific context without invention.
- ACTIONABILITY: specific and feasible strategies or next steps where appropriate.
- CONTEXT_AWARENESS: correct integration of the visible Dashboard, conversation, course, learner, and planning context.
- MOTIVATION_AND_ENGAGEMENT: supportive and autonomy-respecting engagement without manipulation or empty praise.
- RELIABILITY: accurate scoping to the supplied evidence without fabricated or misleading claims.
- MULTI_PAGE_COHESIVENESS: coherent integration when evidence spans multiple LAD pages.
- ERROR_HANDLING: safe treatment of missing, incomplete, conflicting, ambiguous, or unavailable information.

Score meaning: 1 poor, 2 major weaknesses, 3 adequate with a material weakness, 4 strong with a minor weakness, and 5 excellent under the criterion. Do not reward length, confidence, or fluent wording by itself.

Work independently. Do not inspect the other packet, Judge material, restricted mappings, condition identities, or expected outcomes. Do not alter item IDs, evidence, applicability flags, or candidate responses. Complete the separate attestation only after finishing all assigned ratings.
"""
    return text.encode("utf-8")


def _human_attestation_bytes(role: str) -> bytes:
    text = f"""# C4 REAL human-rater {role} attestation

Packet status: `UNRATED_TEMPLATE`

Reviewer role: `{role}`

- Independent rating completed: 
- Experimental condition identities remained unseen: 
- Other reviewer's ratings remained unseen: 
- LLM Judge outputs remained unseen: 
- All applicability rules were followed: 
- No response text, evidence, or item identifier was changed: 

Reviewer signature: 

Completion date/time: 

Notes: 
"""
    return text.encode("utf-8")


def _human_item_fieldnames() -> list[str]:
    fields = [
        "rating_item_id",
        "student_query",
        "current_lad_page",
        "visible_conversation_history",
        "condition_visible_dashboard_evidence",
        "condition_visible_course_evidence",
        "condition_visible_learner_memory",
        "condition_visible_planning_support",
        "candidate_response",
        "applicability_flags",
    ]
    score_names = (
        "clarity",
        "personalisation",
        "actionability",
        "context_awareness",
        "motivation_and_engagement",
        "reliability",
        "multi_page_cohesiveness",
        "error_handling",
    )
    for name in score_names:
        fields.extend((f"{name}_rating", f"{name}_rationale"))
    return fields


def _human_order(
    rows: Sequence[Mapping[str, Any]], key: bytes, role: str
) -> list[dict[str, Any]]:
    grouped: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in rows:
        grouped[str(row["_scenario_id"])].append(dict(row))
    for scenario, family_rows in grouped.items():
        family_rows.sort(
            key=lambda row: hmac_hex(
                key, HUMAN_DOMAIN, f"reviewer-{role}-item-order", scenario, row["rating_item_id"]
            )
        )
    ordered: list[dict[str, Any]] = []
    previous: str | None = None
    round_index = 0
    while any(grouped.values()):
        active = [scenario for scenario, family_rows in grouped.items() if family_rows]
        active.sort(
            key=lambda scenario: hmac_hex(
                key, HUMAN_DOMAIN, f"reviewer-{role}-family-round", str(round_index), scenario
            )
        )
        if len(active) > 1 and active[0] == previous:
            active = active[1:] + active[:1]
        for scenario in active:
            ordered.append(grouped[scenario].pop(0))
            previous = scenario
        round_index += 1
    return ordered


def build_human_packets(
    selected_scenarios: Sequence[str],
    condition_records: Sequence[Mapping[str, Any]],
    unique_judge_records: Sequence[Mapping[str, Any]],
    condition_judge_mapping: Sequence[Mapping[str, Any]],
    key: bytes,
) -> tuple[dict[str, bytes], bytes, bytes, list[dict[str, Any]], dict[str, Any]]:
    judge_by_id = {row["logical_judge_request_id"]: row for row in unique_judge_records}
    judge_map_by_condition = {row["replay_record_id"]: row for row in condition_judge_mapping}
    condition_by_id = {row["replay_record_id"]: row for row in condition_records}
    selected_set = set(selected_scenarios)
    raw_items: list[dict[str, Any]] = []
    restricted_mapping: list[dict[str, Any]] = []
    score_names = (
        "clarity",
        "personalisation",
        "actionability",
        "context_awareness",
        "motivation_and_engagement",
        "reliability",
        "multi_page_cohesiveness",
        "error_handling",
    )
    for condition in condition_records:
        if condition["scenario_id"] not in selected_set:
            continue
        mapping = judge_map_by_condition[condition["replay_record_id"]]
        judge_record = judge_by_id[mapping["judge_logical_request_id"]]
        blind_request = _extract_blind_request(judge_record["provider_payload"])
        material = sha256_bytes(
            canonical_json_bytes(
                [condition["replay_record_id"], mapping["judge_provider_payload_sha256"]]
            )
        )
        rating_id = opaque_id(key, HUMAN_DOMAIN, "rating-item-id", material, "HR1-", 24)
        item: dict[str, Any] = {
            "_scenario_id": condition["scenario_id"],
            "rating_item_id": rating_id,
            "student_query": blind_request["student_query"],
            "current_lad_page": blind_request["current_lad_page"],
            "visible_conversation_history": blind_request["visible_conversation_history"],
            "condition_visible_dashboard_evidence": blind_request["frozen_dashboard_evidence"],
            "condition_visible_course_evidence": blind_request["course_evidence_available_in_condition"],
            "condition_visible_learner_memory": blind_request["long_term_memory_available_in_condition"],
            "condition_visible_planning_support": blind_request["planning_support_available_in_condition"],
            "candidate_response": blind_request["candidate_response"],
            "applicability_flags": blind_request["frozen_applicability_map"]["criteria"],
        }
        for name in score_names:
            item[f"{name}_rating"] = ""
            item[f"{name}_rationale"] = ""
        raw_items.append(item)
        restricted_mapping.append(
            {
                "rating_item_id": rating_id,
                "replay_record_id": condition["replay_record_id"],
                "scenario_id": condition["scenario_id"],
                "mode_id": condition["mode_id"],
                "generation_logical_request_id": condition["logical_generation_request_id"],
                "generation_response_blind_id": condition["response_blind_id"],
                "judge_logical_request_id": mapping["judge_logical_request_id"],
                "judge_result_blind_id": mapping["judge_result_blind_id"],
            }
        )
    require(len(raw_items) == len(selected_scenarios) * 9 == 108, "human item population differs")
    require(len({row["rating_item_id"] for row in raw_items}) == len(raw_items), "human rating-item ID collision")
    ordered_a = _human_order(raw_items, key, "A")
    ordered_b = _human_order(raw_items, key, "B")
    ids_a = [row["rating_item_id"] for row in ordered_a]
    ids_b = [row["rating_item_id"] for row in ordered_b]
    require(set(ids_a) == set(ids_b) and ids_a != ids_b, "Human A/B item-set or order invariant failed")

    fieldnames = _human_item_fieldnames()
    def public_csv_rows(rows: Sequence[Mapping[str, Any]]) -> list[dict[str, str]]:
        output: list[dict[str, str]] = []
        complex_fields = {
            "visible_conversation_history",
            "condition_visible_dashboard_evidence",
            "condition_visible_course_evidence",
            "condition_visible_learner_memory",
            "condition_visible_planning_support",
            "applicability_flags",
        }
        for row in rows:
            public: dict[str, str] = {}
            for field in fieldnames:
                value = row[field]
                public[field] = (
                    canonical_json_bytes(value).decode("utf-8") if field in complex_fields else str(value)
                )
            output.append(public)
        return output

    csv_a = csv_bytes(fieldnames, public_csv_rows(ordered_a))
    csv_b = csv_bytes(fieldnames, public_csv_rows(ordered_b))
    guide = _human_guide_bytes()
    attestation_a = _human_attestation_bytes("A")
    attestation_b = _human_attestation_bytes("B")
    item_set_hash = sha256_bytes(canonical_json_bytes(sorted(ids_a)))
    order_hash_a = sha256_bytes(canonical_json_bytes(ids_a))
    order_hash_b = sha256_bytes(canonical_json_bytes(ids_b))
    tracked_manifest = {
        "schema_version": "c4-real-human-review-packet-manifest-v1",
        "status": "PASS_TWO_INDEPENDENT_BLINDED_UNRATED_PACKETS",
        "selected_family_count": len(selected_scenarios),
        "rating_item_count": len(raw_items),
        "same_item_set": True,
        "different_deterministic_orders": True,
        "item_set_sha256": item_set_hash,
        "order_sha256": {"A": order_hash_a, "B": order_hash_b},
        "packet_csv_sha256": {"A": sha256_bytes(csv_a), "B": sha256_bytes(csv_b)},
        "guide_sha256": sha256_bytes(guide),
        "attestation_sha256": {
            "A": sha256_bytes(attestation_a),
            "B": sha256_bytes(attestation_b),
        },
        "condition_level_items_retained": True,
        "ratings_completed": 0,
        "rating_fields_blank": True,
        "rationale_fields_blank": True,
        "judge_ids_exposed_in_packets": False,
        "condition_or_scenario_ids_exposed_in_packets": False,
    }
    packet_files = {
        "HUMAN_RATER_GUIDE.md": guide,
        "human_rating_packet_A.csv": csv_a,
        "human_rating_packet_B.csv": csv_b,
        "human_rater_attestation_A.md": attestation_a,
        "human_rater_attestation_B.md": attestation_b,
    }
    return packet_files, csv_a, csv_b, restricted_mapping, tracked_manifest


def build_judge_packages(
    unique_records: Sequence[Mapping[str, Any]], judge_protocol: Mapping[str, Any]
) -> tuple[dict[str, bytes], dict[str, Any], dict[str, int]]:
    runner_bytes = (HERE / "judge_execution_runner_v1.py").read_bytes()
    parser_bytes = (HERE / "judge_result_parser_v1.py").read_bytes()
    validator_bytes = (HERE / "judge_package_validator_v1.py").read_bytes()
    test_bytes = (HERE / "judge_package_offline_tests_v1.py").read_bytes()
    external: dict[str, bytes] = {}
    packages: dict[str, Any] = {}
    package_test_counts: dict[str, int] = {}
    for shard in ("A", "B", "C"):
        records = [row for row in unique_records if row["shard_id"] == shard]
        require(records, f"Judge Shard {shard} is empty")
        members: dict[str, bytes] = {
            "README.md": (
                f"# C4 REAL Judge Shard {shard} execution Package R1\n\n"
                "This is a blinded, frozen future-execution Package. R3D1-R1 authorizes no Judge call. "
                "Use only after separate execution authority and run with `/opt/anaconda3/bin/python3`. "
                "The runner is serial, has zero SDK retries, permits one byte-identical retry only for the "
                "three frozen invalid-output classes, and refuses existing output directories.\n\n"
                f"Frozen unique requests: `{len(records)}`.\n"
            ).encode("utf-8"),
            "BLINDED_JUDGE_REQUESTS.jsonl": jsonl_bytes(records),
            "JUDGE_PROMPT.txt": judge_protocol["prompt_bytes"],
            "JUDGE_SCHEMA.json": judge_protocol["schema_bytes"],
            "JUDGE_CONFIGURATION.json": judge_protocol["configuration_bytes"],
            "PRIMARY_RUBRIC.json": judge_protocol["rubric_bytes"],
            "APPLICABILITY_CONTRACT.json": judge_protocol["applicability_bytes"],
            "EXECUTION_CONTRACT.json": judge_protocol["execution_contract_bytes"],
            "judge_execution_runner_v1.py": runner_bytes,
            "judge_result_parser_v1.py": parser_bytes,
            "validate_package.py": validator_bytes,
            "test_package.py": test_bytes,
        }
        source_hashes = {
            "schema_version": "c4-real-judge-package-source-hashes-v1",
            "shard_id": shard,
            "member_sha256": {name: sha256_bytes(data) for name, data in sorted(members.items())},
        }
        members["PACKAGE_SOURCE_HASHES.json"] = pretty_json_bytes(source_hashes)
        with tempfile.TemporaryDirectory(prefix=f"c4-r3d1-judge-{shard.lower()}-") as tmp:
            package_dir = Path(tmp)
            for name, data in members.items():
                (package_dir / name).write_bytes(data)
            result = validate_package_dir(package_dir)
            require(result["status"] == "PASS", f"Judge Shard {shard} Package validation failed")
            env = dict(os.environ)
            env["PYTHONDONTWRITEBYTECODE"] = "1"
            tests = subprocess.run(
                ["/opt/anaconda3/bin/python3", "test_package.py"],
                cwd=package_dir,
                env=env,
                capture_output=True,
                text=True,
            )
            require(tests.returncode == 0, f"Judge Shard {shard} Package tests failed: {tests.stdout}{tests.stderr}")
            package_test_counts[shard] = 5
        archive = zip_bytes(members)
        filename = f"C4_REAL_JUDGE_SHARD_{shard}_EXECUTION_PACKAGE_R1_2026-09-02.zip"
        external[filename] = archive
        packages[shard] = {
            "file_name": filename,
            "sha256": sha256_bytes(archive),
            "regular_file_count": len(members),
            "unique_judge_request_count": len(records),
            "estimated_input_tokens": sum(row["estimated_input_tokens"] for row in records),
            "maximum_physical_attempts": len(records) * 2,
            "package_validation": "PASS",
            "package_tests_passed": 5,
            "package_tests_failed": 0,
            "member_sha256": {name: sha256_bytes(data) for name, data in sorted(members.items())},
        }
    manifest = {
        "schema_version": "c4-real-judge-package-manifest-r1-v1",
        "status": "PASS_THREE_BLINDED_PACKAGES_FROZEN_NO_CALLS",
        "packages": packages,
        "judge_calls": 0,
        "credentials_included": False,
        "restricted_mapping_or_hmac_key_included": False,
        "existing_judge_outputs_included": False,
    }
    return external, manifest, package_test_counts


def build_human_archives(
    packet_files: Mapping[str, bytes], tracked_manifest: Mapping[str, Any]
) -> tuple[dict[str, bytes], dict[str, Any]]:
    external: dict[str, bytes] = {}
    archive_metadata: dict[str, Any] = {}
    for role in ("A", "B"):
        csv_name = f"human_rating_packet_{role}.csv"
        attestation_name = f"human_rater_attestation_{role}.md"
        role_manifest = {
            "schema_version": "c4-real-human-rater-packet-archive-manifest-v1",
            "status": "FROZEN_UNRATED_TEMPLATE",
            "reviewer_role": role,
            "rating_item_count": tracked_manifest["rating_item_count"],
            "item_set_sha256": tracked_manifest["item_set_sha256"],
            "order_sha256": tracked_manifest["order_sha256"][role],
            "member_sha256": {
                "HUMAN_RATER_GUIDE.md": sha256_bytes(packet_files["HUMAN_RATER_GUIDE.md"]),
                csv_name: sha256_bytes(packet_files[csv_name]),
                attestation_name: sha256_bytes(packet_files[attestation_name]),
            },
            "ratings_completed": 0,
        }
        members = {
            "HUMAN_RATER_GUIDE.md": packet_files["HUMAN_RATER_GUIDE.md"],
            csv_name: packet_files[csv_name],
            attestation_name: packet_files[attestation_name],
            "PACKET_MANIFEST.json": pretty_json_bytes(role_manifest),
        }
        archive = zip_bytes(members)
        filename = f"C4_REAL_HUMAN_RATER_{role}_PACKET_2026-09-02.zip"
        external[filename] = archive
        archive_metadata[role] = {
            "file_name": filename,
            "sha256": sha256_bytes(archive),
            "regular_file_count": len(members),
            "rating_item_count": tracked_manifest["rating_item_count"],
            "ratings_completed": 0,
            "member_sha256": {name: sha256_bytes(data) for name, data in sorted(members.items())},
        }
    return external, archive_metadata


def _condition_csv_data(rows: Sequence[Mapping[str, Any]]) -> tuple[list[str], list[dict[str, Any]]]:
    fields = [
        "schema_version",
        "logical_order",
        "replay_record_id",
        "scenario_id",
        "mode_id",
        "current_page",
        "route_signature",
        "activation_mask",
        "mechanism_metadata",
        "logical_generation_request_id",
        "response_blind_id",
        "provider_payload_sha256",
        "answer_text",
        "answer_text_sha256",
        "selected_execution_source",
        "selected_attempt_number",
        "raw_response_source_sha256",
        "generation_status",
        "frozen_applicability_map",
        "applicability_source_metadata",
        "provider_generation_payload_v3",
    ]
    complex_fields = {
        "activation_mask",
        "mechanism_metadata",
        "frozen_applicability_map",
        "applicability_source_metadata",
        "provider_generation_payload_v3",
    }
    output: list[dict[str, Any]] = []
    for row in rows:
        output.append(
            {
                field: (
                    canonical_json_bytes(row[field]).decode("utf-8")
                    if field in complex_fields
                    else row[field]
                )
                for field in fields
            }
        )
    return fields, output


def _canonical_response_csv_bytes(canonical: Sequence[Mapping[str, Any]]) -> bytes:
    fields = [
        "schema_version",
        "frozen_manifest_order",
        "logical_generation_request_id",
        "response_blind_id",
        "answer_text",
        "answer_text_sha256",
        "provider_payload_sha256",
        "selected_execution_source",
        "selected_attempt_number",
        "raw_response_source_sha256",
        "requested_model",
        "returned_model",
        "provider_response_id",
        "system_fingerprint",
        "finish_reason",
        "prompt_tokens",
        "cached_input_tokens",
        "completion_tokens",
        "total_tokens",
        "generation_status",
    ]
    return csv_bytes(fields, canonical)


def _source_registry_csv_not_required() -> None:
    """Marker that the authorized source registry is JSONL-only."""


def _response_freeze_report(
    policy_sha256: str,
    canonical_jsonl_sha256: str,
    canonical_csv_sha256: str,
    source_registry_sha256: str,
    duplicate_audit_sha256: str,
    format_audit_sha256: str,
    usage: Mapping[str, Any],
) -> bytes:
    aggregate = usage["aggregate"]
    text = f"""# C4 REAL R3 final response freeze report

Status: `PASS_FINAL_R3_RESPONSE_IDENTITY_FREEZE`

This R3D1-R1 freeze applies the amended distinct-response-identity policy. Response uniqueness is defined by the frozen logical request, response blind ID, and Provider-payload identity—not by natural-language text. No response was generated, regenerated, rewritten, removed, merged, scored, or rated in this stage.

## Frozen response universe

- Canonical response records: `147`
- Unique logical-generation request IDs: `147`
- Unique response blind IDs: `147`
- Unique Provider-payload SHA-256 values: `147`
- Distinct answer-text SHA-256 values: `146`
- Exact duplicate-text groups: `1`
- Records in the duplicate-text group: `2`
- Missing response records or identity collisions: `0`
- Canonical rule: `EARLIEST_VALID_ATTEMPT_UNDER_VALIDATOR_V2`
- Shard A logical order 40 selected attempt: `1`
- Original Shard C logical order 4 selected attempt: `1`

## Mechanical format and leakage audit

- Outer-schema valid: `147/147`
- Non-empty: `147/147`
- Validator V2 student-facing valid: `147/147`
- JSON/Python container, raw internal structure, punctuation-only, raw code/XML: `0`
- Literal or local-path leakage occurrences: `0`
- Response-quality assessment: `not performed`

## Historical generation usage

- Physical attempts: `{aggregate['physical_attempts']}`
- Historical redundant retries: `{aggregate['historical_redundant_retries']}`
- Prompt tokens: `{aggregate['prompt_tokens']}`
- Cached-input tokens: `{aggregate['cached_input_tokens']}`
- Completion tokens: `{aggregate['completion_tokens']}`
- Total tokens: `{aggregate['total_tokens']}`
- Cost: `NOT_COMPUTED_NO_FROZEN_PRICING_AUTHORITY`

## Artifact identities

- Identical-answer policy SHA-256: `{policy_sha256}`
- Canonical JSONL SHA-256: `{canonical_jsonl_sha256}`
- Canonical CSV SHA-256: `{canonical_csv_sha256}`
- Response source registry SHA-256: `{source_registry_sha256}`
- Duplicate-text audit SHA-256: `{duplicate_audit_sha256}`
- Final format audit SHA-256: `{format_audit_sha256}`
"""
    return text.encode("utf-8")


def _judge_report(judge_audit: Mapping[str, Any], protocol: Mapping[str, Any]) -> bytes:
    shard_lines = "\n".join(
        f"- Shard {shard}: `{item['unique_judge_requests']}` unique requests, "
        f"estimated input tokens `{item['estimated_input_tokens']}`, "
        f"maximum physical attempts `{item['maximum_physical_attempts']}`"
        for shard, item in judge_audit["shards"].items()
    )
    text = f"""# C4 REAL Judge-request deduplication report

Status: `PASS_BLIND_JUDGE_REQUEST_UNIVERSE_FROZEN`

Exactly 558 restricted condition-to-Judge mappings were built first. Deduplication then used only complete canonical Provider-facing Judge-payload byte identity. Answer text, answer-text SHA-256, and generation response identity were not deduplication keys.

- Unique Judge requests: `{judge_audit['unique_judge_requests']}`
- Deduplicated condition mappings: `{judge_audit['deduplicated_condition_mappings']}`
- Known equal-text response identities kept as disjoint Judge-request sets: `yes`
- Opaque ID domain: `{JUDGE_DOMAIN}`
- Scenario-family atomic Shards: `yes`
- Judge calls: `0`

## Frozen Judge identity

- Model: `{JUDGE_MODEL}`
- Temperature: `{JUDGE_TEMPERATURE}`
- Maximum output tokens: `{JUDGE_MAX_OUTPUT_TOKENS}`
- Prompt SHA-256: `{protocol['prompt_sha256']}`
- Schema SHA-256: `{protocol['schema_sha256']}`
- Configuration SHA-256: `{protocol['configuration_sha256']}`
- Rubric SHA-256: `{protocol['rubric_sha256']}`
- Applicability contract SHA-256: `{protocol['applicability_sha256']}`

## Shards

{shard_lines}
"""
    return text.encode("utf-8")


def _status_bytes(
    judge_count: int,
    shard_summary: Mapping[str, Any],
    human_family_count: int,
    human_item_count: int,
) -> bytes:
    text = f"""# RQ3 REAL C4 R3D1-R1 status

`RQ3_REAL_R3D1_STATUS = READY_FOR_PARALLEL_C4_REAL_JUDGE_EXECUTION_AND_INDEPENDENT_HUMAN_REVIEW`

- Starting HEAD: `{START_HEAD}`
- Canonical response identities: `147`
- Distinct answer-text hashes: `146`
- Permitted duplicate-text groups / records: `1 / 2`
- Condition-response mappings: `558`
- Unique blind Judge requests: `{judge_count}`
- Judge Shard counts: `A={shard_summary['A']['unique_judge_requests']}`, `B={shard_summary['B']['unique_judge_requests']}`, `C={shard_summary['C']['unique_judge_requests']}`
- Human-validation families / rating items: `{human_family_count} / {human_item_count}`
- Provider, generation, Judge, scoring, and human-rating calls in R3D1-R1: `0`
- Existing generation histories, mappings, applicability maps, Prompt, schema, routes, mechanisms, and HMAC key: `unchanged`

This status authorizes no Judge call or human rating. Those actions require their own later authority.
"""
    return text.encode("utf-8")


def _materialize_once(path: Path, data: bytes, mode: int = 0o644) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("xb") as handle:
        handle.write(data)
        handle.flush()
        os.fsync(handle.fileno())
    path.chmod(mode)


def main() -> int:
    state = assert_initial_and_immutable_state()
    canonical, source_registry, usage = build_canonical_responses()
    duplicate_audit = build_duplicate_text_audit(canonical)
    format_audit = build_format_audit(canonical)
    source_manifest = source_preservation_manifest()
    (
        condition_records,
        response_mapping,
        mapping_metadata,
        applicability_audit,
        _registry,
    ) = build_condition_response_mapping(canonical)
    (
        unique_judge_records,
        condition_judge_mapping,
        judge_audit,
        judge_mapping_metadata,
        judge_protocol,
        judge_configuration_bytes,
        judge_execution_contract_bytes,
    ) = build_judge_universe(condition_records, state["key"])

    canonical_jsonl = jsonl_bytes(canonical)
    canonical_csv = _canonical_response_csv_bytes(canonical)
    source_registry_jsonl = jsonl_bytes(source_registry)
    duplicate_audit_bytes = pretty_json_bytes(duplicate_audit)
    format_audit_bytes = pretty_json_bytes(format_audit)
    usage_bytes = pretty_json_bytes(usage)
    source_manifest_bytes = pretty_json_bytes(source_manifest)

    condition_jsonl = jsonl_bytes(condition_records)
    condition_fields, condition_csv_rows = _condition_csv_data(condition_records)
    condition_csv = csv_bytes(condition_fields, condition_csv_rows)
    response_mapping_fields = [
        "response_blind_id",
        "logical_generation_request_id",
        "provider_payload_sha256",
        "replay_record_id",
    ]
    response_mapping_csv = csv_bytes(response_mapping_fields, response_mapping)
    restricted_response_files = {
        "c4_real_r3_condition_response_records_frozen_v1.csv": condition_csv,
        "c4_real_r3_condition_response_records_frozen_v1.jsonl": condition_jsonl,
        "c4_real_r3_response_to_condition_mapping_frozen_v1.csv": response_mapping_csv,
    }
    for name, data in restricted_response_files.items():
        mapping_metadata["mapping_files"][name] = {
            "row_count": 558,
            "sha256": sha256_bytes(data),
        }

    judge_mapping_fields = [
        "logical_order",
        "replay_record_id",
        "scenario_id",
        "mode_id",
        "generation_logical_request_id",
        "generation_response_blind_id",
        "judge_logical_request_id",
        "judge_result_blind_id",
        "judge_provider_payload_sha256",
        "shard_id",
    ]
    judge_mapping_csv = csv_bytes(judge_mapping_fields, condition_judge_mapping)
    judge_mapping_metadata["condition_mapping_sha256"] = sha256_bytes(judge_mapping_csv)
    unique_judge_jsonl = jsonl_bytes(unique_judge_records)
    unique_judge_sha256 = sha256_bytes(unique_judge_jsonl)

    selected_scenarios, human_sample_metadata = select_human_families(
        condition_records,
        sha256_bytes(canonical_jsonl),
        state["key"],
    )
    (
        human_packet_files,
        human_csv_a,
        human_csv_b,
        human_restricted_mapping,
        human_packet_manifest,
    ) = build_human_packets(
        selected_scenarios,
        condition_records,
        unique_judge_records,
        condition_judge_mapping,
        state["key"],
    )
    human_mapping_fields = [
        "rating_item_id",
        "replay_record_id",
        "scenario_id",
        "mode_id",
        "generation_logical_request_id",
        "generation_response_blind_id",
        "judge_logical_request_id",
        "judge_result_blind_id",
    ]
    human_mapping_csv = csv_bytes(human_mapping_fields, human_restricted_mapping)
    human_mapping_metadata = {
        "schema_version": "c4-real-human-restricted-mapping-metadata-v1",
        "status": "PASS_RESTRICTED_MAPPING_FROZEN",
        "key_commitment": HMAC_KEY_COMMITMENT,
        "mapping_filename": "c4_real_human_rating_item_to_condition_mapping_frozen_v1.csv",
        "mapping_rows": len(human_restricted_mapping),
        "mapping_sha256": sha256_bytes(human_mapping_csv),
        "raw_mapping_content_in_metadata": False,
    }

    judge_external, judge_package_manifest, package_test_counts = build_judge_packages(
        unique_judge_records, judge_protocol
    )
    human_external, human_archive_metadata = build_human_archives(
        human_packet_files, human_packet_manifest
    )
    human_packet_manifest = {
        **human_packet_manifest,
        "archives": human_archive_metadata,
    }

    response_receipt = {
        "schema_version": "c4-real-r3-final-response-set-freeze-v1",
        "status": "FROZEN_DISTINCT_RESPONSE_IDENTITIES",
        "canonical_response_identities": 147,
        "unique_logical_generation_request_ids": 147,
        "unique_response_blind_ids": 147,
        "unique_provider_payload_sha256_values": 147,
        "distinct_answer_text_sha256_values": 146,
        "duplicate_text_groups": 1,
        "duplicate_text_records": 2,
        "duplicate_text_policy_id": POLICY_ID,
        "duplicate_text_policy_sha256": state["policy_sha256"],
        "condition_response_mappings": 558,
        "validator_v2_sha256": sha256_file(R3D0 / "c4_real_student_facing_response_validator_v2.py"),
        "canonical_attempt_selection_rule_sha256": sha256_file(R3D0 / "C4_REAL_R3_CANONICAL_ATTEMPT_SELECTION_RULE_V1.json"),
        "canonical_response_jsonl_sha256": sha256_bytes(canonical_jsonl),
        "canonical_response_csv_sha256": sha256_bytes(canonical_csv),
        "response_source_registry_sha256": sha256_bytes(source_registry_jsonl),
        "duplicate_text_audit_sha256": sha256_bytes(duplicate_audit_bytes),
        "final_response_format_audit_sha256": sha256_bytes(format_audit_bytes),
        "zero_g2_answer_inclusion": True,
        "write_count": 1,
        "overwrite_permitted": False,
    }
    judge_receipt = {
        "schema_version": "c4-real-judge-protocol-freeze-receipt-v1",
        "status": "FROZEN_READY_FOR_SEPARATELY_AUTHORIZED_PARALLEL_EXECUTION",
        "judge_model": JUDGE_MODEL,
        "temperature": JUDGE_TEMPERATURE,
        "maximum_output_tokens": JUDGE_MAX_OUTPUT_TOKENS,
        "prompt_sha256": judge_protocol["prompt_sha256"],
        "schema_sha256": judge_protocol["schema_sha256"],
        "configuration_sha256": judge_protocol["configuration_sha256"],
        "rubric_sha256": judge_protocol["rubric_sha256"],
        "applicability_sha256": judge_protocol["applicability_sha256"],
        "unique_judge_request_count": len(unique_judge_records),
        "unique_judge_manifest_sha256": unique_judge_sha256,
        "shards": judge_audit["shards"],
        "maximum_physical_attempts": len(unique_judge_records) * 2,
        "package_sha256": {
            shard: judge_package_manifest["packages"][shard]["sha256"]
            for shard in ("A", "B", "C")
        },
        "judge_calls": 0,
    }
    human_receipt = {
        "schema_version": "c4-real-human-validation-freeze-receipt-v1",
        "status": "FROZEN_READY_FOR_INDEPENDENT_HUMAN_REVIEW",
        "selected_family_count": len(selected_scenarios),
        "rating_item_count": human_packet_manifest["rating_item_count"],
        "packet_sha256": {
            role: human_archive_metadata[role]["sha256"] for role in ("A", "B")
        },
        "order_sha256": human_packet_manifest["order_sha256"],
        "item_set_sha256": human_packet_manifest["item_set_sha256"],
        "same_item_set": True,
        "different_deterministic_orders": True,
        "completed_ratings": 0,
    }

    response_report = _response_freeze_report(
        state["policy_sha256"],
        sha256_bytes(canonical_jsonl),
        sha256_bytes(canonical_csv),
        sha256_bytes(source_registry_jsonl),
        sha256_bytes(duplicate_audit_bytes),
        sha256_bytes(format_audit_bytes),
        usage,
    )
    judge_report = _judge_report(judge_audit, judge_protocol)
    status = _status_bytes(
        len(unique_judge_records),
        judge_audit["shards"],
        len(selected_scenarios),
        human_packet_manifest["rating_item_count"],
    )

    tracked: dict[str, bytes] = {
        "c4_real_r3_canonical_unique_responses_frozen_v1.jsonl": canonical_jsonl,
        "c4_real_r3_canonical_unique_responses_frozen_v1.csv": canonical_csv,
        "c4_real_r3_response_source_registry_v1.jsonl": source_registry_jsonl,
        "c4_real_r3_duplicate_text_identity_audit_v1.json": duplicate_audit_bytes,
        "c4_real_r3_final_response_format_audit_v1.json": format_audit_bytes,
        "C4_REAL_R3_FINAL_RESPONSE_FREEZE_REPORT.md": response_report,
        "c4_real_r3_generation_usage_frozen_v1.json": usage_bytes,
        "c4_real_r3_source_preservation_manifest_v1.json": source_manifest_bytes,
        "c4_real_r3_response_mapping_metadata_v1.json": pretty_json_bytes(mapping_metadata),
        "c4_real_r3_applicability_integrity_audit_v1.json": pretty_json_bytes(applicability_audit),
        "c4_real_unique_judge_request_manifest_frozen_v1.jsonl": unique_judge_jsonl,
        "C4_REAL_JUDGE_REQUEST_DEDUPLICATION_REPORT.md": judge_report,
        "c4_real_judge_request_deduplication_audit_v1.json": pretty_json_bytes(judge_audit),
        "c4_real_judge_restricted_mapping_metadata_v1.json": pretty_json_bytes(judge_mapping_metadata),
        "c4_real_judge_configuration_frozen_r1.json": judge_configuration_bytes,
        "c4_real_judge_execution_contract_v1.json": judge_execution_contract_bytes,
        "c4_real_judge_package_manifest_r1_v1.json": pretty_json_bytes(judge_package_manifest),
        "c4_real_human_validation_sample_metadata_v1.json": pretty_json_bytes(human_sample_metadata),
        "HUMAN_RATER_GUIDE.md": human_packet_files["HUMAN_RATER_GUIDE.md"],
        "human_rating_packet_A.csv": human_csv_a,
        "human_rating_packet_B.csv": human_csv_b,
        "human_rater_attestation_A.md": human_packet_files["human_rater_attestation_A.md"],
        "human_rater_attestation_B.md": human_packet_files["human_rater_attestation_B.md"],
        "c4_real_human_packet_manifest_v1.json": pretty_json_bytes(human_packet_manifest),
        "c4_real_human_restricted_mapping_metadata_v1.json": pretty_json_bytes(human_mapping_metadata),
        "C4_REAL_R3_FINAL_RESPONSE_SET_FREEZE.json": pretty_json_bytes(response_receipt),
        "C4_REAL_JUDGE_PROTOCOL_FREEZE_RECEIPT.json": pretty_json_bytes(judge_receipt),
        "C4_REAL_HUMAN_VALIDATION_FREEZE_RECEIPT.json": pretty_json_bytes(human_receipt),
        "STATUS.md": status,
    }
    restricted: dict[str, bytes] = {
        **restricted_response_files,
        "c4_real_condition_to_unique_judge_request_mapping_v1.csv": judge_mapping_csv,
        "c4_real_human_rating_item_to_condition_mapping_frozen_v1.csv": human_mapping_csv,
    }
    external = {**judge_external, **human_external}

    for name in tracked:
        require(not (HERE / name).exists(), f"tracked freeze target already exists: {name}")
    for name in restricted:
        require(not (RESTRICTED / name).exists(), f"restricted freeze target already exists: {name}")
    for name in external:
        require(not (DOWNLOADS / name).exists(), f"external freeze target already exists: {name}")

    # Every staged artifact has been mechanically constructed and every Package
    # validated and tested before this first target write.
    for name, data in tracked.items():
        _materialize_once(HERE / name, data)
    for name, data in restricted.items():
        _materialize_once(RESTRICTED / name, data, 0o600)
    for name, data in external.items():
        _materialize_once(DOWNLOADS / name, data)

    for name in restricted:
        path = RESTRICTED / name
        require(stat.S_IMODE(path.stat().st_mode) == 0o600, f"restricted output mode differs: {name}")
        require(
            subprocess.run(
                ["git", "check-ignore", "-q", str(path.relative_to(REPO))], cwd=REPO
            ).returncode
            == 0,
            f"restricted output is not ignored: {name}",
        )
    untracked_visible = str(git("ls-files", "--others", "--exclude-standard")).splitlines()
    require(all(path.startswith(str(HERE.relative_to(REPO)) + "/") for path in untracked_visible), "new visible file escaped R3D1 tracked scope")

    summary = {
        "status": "PASS_R3D1_R1_ARTIFACTS_MATERIALIZED_ONCE",
        "canonical_responses": len(canonical),
        "distinct_answer_text_sha256": 146,
        "condition_response_records": len(condition_records),
        "unique_judge_requests": len(unique_judge_records),
        "judge_shards": {
            shard: judge_audit["shards"][shard]["unique_judge_requests"]
            for shard in ("A", "B", "C")
        },
        "human_families": len(selected_scenarios),
        "human_rating_items": human_packet_manifest["rating_item_count"],
        "package_tests_passed": package_test_counts,
        "provider_calls": 0,
        "generation_calls": 0,
        "judge_calls": 0,
        "scoring_calls": 0,
        "human_rating_actions": 0,
    }
    print(json.dumps(summary, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
