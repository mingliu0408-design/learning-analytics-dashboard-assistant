#!/usr/bin/env python3
"""Rebuild all 558 frozen conditions into the uniform, dormant R3 interface."""

from __future__ import annotations

import argparse
from collections import Counter, defaultdict
import copy
import csv
import hashlib
import hmac
import io
import json
import math
import os
from pathlib import Path
import re
import stat
import subprocess
from typing import Any, Iterable, Mapping, Sequence

try:
    from .c4_real_generation_request_renderer_v3 import (
        render_generation_request_v3_with_audit,
        source_substantive_facts,
    )
except ImportError:
    from c4_real_generation_request_renderer_v3 import (
        render_generation_request_v3_with_audit,
        source_substantive_facts,
    )


REPO_ROOT = Path(__file__).resolve().parents[3]
REPAIR_DIR = Path(__file__).resolve().parent
I1_DIR = REPO_ROOT / "evaluation/rq3_real_c4/i1_route_integration"
RESTRICTED_DIR = I1_DIR / "restricted_internal"
INTEGRATED_G2_HEAD = "2c1094d6486d5db8d01d8a4ef02e11f15d1813e9"
BRANCH = "research/rq3-real-c4-i1-route-integration"
SEED = 20260901
MODEL = "gpt-4o-mini-2024-07-18"
HMAC_KEY_COMMITMENT = "199db23c86b0dd824edaff2d5b40da12761c9aa76bf2fb9d902952ab376481b5"
OUTER_SCHEMA_SHA256 = "485dbdc6af48577808d3e6a51fc9811e54f7a8f670f50f92c5bbb64ee382f873"

PROMPT_PATH = REPAIR_DIR / "c4_real_generation_prompt_frozen_v3.txt"
RENDERER_PATH = REPAIR_DIR / "c4_real_generation_request_renderer_v3.py"
FORMAT_CONTRACT_PATH = REPAIR_DIR / "c4_real_student_facing_response_format_contract_v1.json"
VALIDATOR_PATH = REPAIR_DIR / "c4_real_student_facing_response_validator_v1.py"
OUTER_SCHEMA_PATH = I1_DIR / "c4_real_generation_schema_v2_provider_compatible.json"
V2_REGISTRY_PATH = RESTRICTED_DIR / "c4_real_condition_generation_payload_registry_frozen_v2.jsonl"
V2_MAPPING_PATH = RESTRICTED_DIR / "c4_real_condition_to_unique_request_mapping_frozen_v2.csv"
V2_UNIQUE_MANIFEST_PATH = I1_DIR / "c4_real_unique_generation_request_manifest_frozen_v2.jsonl"
V2_METADATA_PATH = I1_DIR / "c4_real_restricted_mapping_metadata_v2.json"
MECHANISM_PATH = I1_DIR / "c4_real_condition_mechanism_records_frozen_v1.jsonl"
APPLICABILITY_PATH = I1_DIR / "c4_real_condition_applicability_maps_frozen_v1.jsonl"
HMAC_KEY_PATH = RESTRICTED_DIR / "c4_real_i1_blinding_hmac_key.bin"

SCIENTIFIC_HASHES = {
    MECHANISM_PATH: "053217a461985280746b981c4184633e7b4fe21c6b980a1e86fab249ef21e7c0",
    APPLICABILITY_PATH: "1f5b159b3d80506c32265624a8f4e5866af4dba996dd0f62abf53dff93f31084",
}

V3_RESTRICTED_PATHS = {
    "registry": RESTRICTED_DIR / "c4_real_condition_generation_payload_registry_frozen_v3.jsonl",
    "condition_mapping": RESTRICTED_DIR / "c4_real_condition_to_unique_request_mapping_frozen_v3.csv",
    "response_condition": RESTRICTED_DIR / "c4_real_response_to_condition_mapping_frozen_v3.csv",
    "response_scenario": RESTRICTED_DIR / "c4_real_response_to_scenario_mapping_frozen_v3.csv",
    "response_mode": RESTRICTED_DIR / "c4_real_response_to_mode_mapping_frozen_v3.csv",
}

V3_TRACKED_PATHS = {
    "unique_manifest": I1_DIR / "c4_real_unique_generation_request_manifest_frozen_v3.jsonl",
    "dedup_summary": I1_DIR / "c4_real_generation_request_deduplication_summary_v3.json",
    "dedup_report": I1_DIR / "C4_REAL_GENERATION_REQUEST_DEDUPLICATION_REPORT_V3.md",
    "shard_summary": I1_DIR / "c4_real_generation_shard_summary_v3.json",
    "restricted_metadata": I1_DIR / "c4_real_restricted_mapping_metadata_v3.json",
    "rebuild_summary": I1_DIR / "c4_real_condition_payload_rebuild_summary_v3.json",
    "configuration": I1_DIR / "c4_real_generation_configuration_frozen_v3.json",
    "diff_audit": REPAIR_DIR / "c4_real_generation_renderer_v2_v3_diff_audit.json",
}

_SCENARIO = re.compile(r"\bU\d{3}\b")
_MODE = re.compile(
    r"\bC(?:0_ORIGINAL|1_EVIDENCE|2_EVIDENCE_RAG|3_EVIDENCE_MEMORY|"
    r"4_EVIDENCE_PLANNING|5_FULL_C4|5_MINUS_RAG|5_MINUS_MEMORY|5_MINUS_PLANNING)\b"
)
_ROUTE_OR_P3 = re.compile(r"\b(?:R2V2|C4-P3-|P3_GATE|P3)\b", re.IGNORECASE)
_LOCAL_PATH = re.compile(r"(?:/Users/|/private/|/var/folders/|file://|\.sqlite(?:3)?\b)", re.IGNORECASE)
_HASH = re.compile(r"\b[0-9a-fA-F]{64}\b")
_RAW_INTERNAL_KEY = re.compile(
    r"(?m)(?:\"|')?(?:action_steps|recommended_action|student_state|main_issue|"
    r"next_steps|next_step|evidence|availability_notes|supporting_evidence|"
    r"reflection_summary|activity_summary|data_summary|gaps_identified|planning_support)"
    r"(?:\"|')?\s*:"
)


def canonical_bytes(value: Any) -> bytes:
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    ).encode("utf-8")


def pretty_json_bytes(value: Any) -> bytes:
    return (json.dumps(value, ensure_ascii=False, sort_keys=True, indent=2) + "\n").encode("utf-8")


def jsonl_bytes(rows: Iterable[Mapping[str, Any]]) -> bytes:
    return b"".join(
        json.dumps(dict(row), ensure_ascii=False, sort_keys=True).encode("utf-8") + b"\n"
        for row in rows
    )


def csv_bytes(rows: Sequence[Mapping[str, Any]], fieldnames: Sequence[str]) -> bytes:
    output = io.StringIO(newline="")
    writer = csv.DictWriter(output, fieldnames=fieldnames, lineterminator="\n")
    writer.writeheader()
    writer.writerows({field: row.get(field, "") for field in fieldnames} for row in rows)
    return output.getvalue().encode("utf-8")


def sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def sha256_file(path: Path) -> str:
    return sha256_bytes(path.read_bytes())


def read_jsonl(path: Path) -> list[dict[str, Any]]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line]


def read_csv(path: Path) -> list[dict[str, str]]:
    with path.open(encoding="utf-8", newline="") as handle:
        return list(csv.DictReader(handle))


def git(*args: str, check: bool = True) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["git", *args], cwd=REPO_ROOT, check=check, capture_output=True, text=True
    )


def verify_inputs() -> tuple[bytes, dict[str, Any]]:
    if Path.cwd().resolve() != REPO_ROOT:
        raise RuntimeError("V3 builder must run from the repository root")
    if git("branch", "--show-current").stdout.strip() != BRANCH:
        raise RuntimeError("branch mismatch")
    head = git("rev-parse", "HEAD").stdout.strip()
    if head != INTEGRATED_G2_HEAD:
        parent = git("rev-parse", "HEAD^").stdout.strip()
        subject = git("show", "-s", "--format=%s", "HEAD").stdout.strip()
        if (
            parent != INTEGRATED_G2_HEAD
            or subject
            != "RQ3-REAL-G2D0: audit generated responses and freeze uniform regeneration"
        ):
            raise RuntimeError("integrated G2 or single G2D0 repair HEAD mismatch")
    for path, expected_hash in SCIENTIFIC_HASHES.items():
        if sha256_file(path) != expected_hash:
            raise RuntimeError(f"frozen scientific input changed: {path.name}")
    if sha256_file(OUTER_SCHEMA_PATH) != OUTER_SCHEMA_SHA256:
        raise RuntimeError("outer schema bytes changed")

    metadata = json.loads(V2_METADATA_PATH.read_text(encoding="utf-8"))
    for name, entry in metadata["v1_mapping_files_preserved"].items():
        if sha256_file(RESTRICTED_DIR / name) != entry["sha256"]:
            raise RuntimeError(f"restricted V1 mapping changed: {name}")
    for name, entry in metadata["v2_mapping_files"].items():
        if sha256_file(RESTRICTED_DIR / name) != entry["sha256"]:
            raise RuntimeError(f"restricted V2 mapping changed: {name}")

    key = HMAC_KEY_PATH.read_bytes()
    if len(key) != 32 or sha256_bytes(key) != HMAC_KEY_COMMITMENT:
        raise RuntimeError("restricted HMAC key identity changed")
    if stat.S_IMODE(HMAC_KEY_PATH.stat().st_mode) != 0o600:
        raise RuntimeError("restricted HMAC key mode is not 0600")
    ignored = git("check-ignore", "-q", str(HMAC_KEY_PATH.relative_to(REPO_ROOT)), check=False)
    if ignored.returncode != 0:
        raise RuntimeError("restricted HMAC key is not ignored")
    tracked = git("ls-files", "--error-unmatch", str(HMAC_KEY_PATH.relative_to(REPO_ROOT)), check=False)
    if tracked.returncode == 0:
        raise RuntimeError("restricted HMAC key is tracked")
    return key, metadata


def opaque_id(key: bytes, purpose: str, payload_hash: str) -> str:
    digest = hmac.new(
        key,
        f"C4_REAL_GENERATION_R3|{SEED}|{purpose}|{payload_hash}".encode("utf-8"),
        hashlib.sha256,
    ).hexdigest().upper()
    if purpose == "logical-request-v3":
        return "C4G3-" + digest[:24]
    if purpose == "response-blind-v3":
        return "R3B3-" + digest[:20]
    raise ValueError("unknown V3 HMAC purpose")


def validate_plain_text_message(text: str) -> None:
    if not isinstance(text, str) or not text.strip():
        raise RuntimeError("V3 provider user message is empty")
    try:
        parsed = json.loads(text)
    except json.JSONDecodeError:
        parsed = None
    if isinstance(parsed, (dict, list)):
        raise RuntimeError("V3 provider user message is still a raw JSON object or array")
    if _RAW_INTERNAL_KEY.search(text):
        raise RuntimeError("V3 provider user message contains a raw internal serialized key")
    for pattern, label in (
        (_SCENARIO, "scenario identity"),
        (_MODE, "mode identity"),
        (_ROUTE_OR_P3, "route or P3 identity"),
        (_LOCAL_PATH, "local path or database"),
        (_HASH, "hash"),
    ):
        if pattern.search(text):
            raise RuntimeError(f"V3 provider user message exposes {label}")


def assign_shards(
    unique: dict[str, dict[str, Any]], conditions: Sequence[Mapping[str, Any]]
) -> None:
    scenarios = sorted({str(row["scenario_id"]) for row in conditions})
    parent = {scenario: scenario for scenario in scenarios}

    def find(value: str) -> str:
        while parent[value] != value:
            parent[value] = parent[parent[value]]
            value = parent[value]
        return value

    def union(left: str, right: str) -> None:
        a, b = find(left), find(right)
        if a != b:
            parent[max(a, b)] = min(a, b)

    scenarios_by_hash: dict[str, set[str]] = defaultdict(set)
    for row in conditions:
        scenarios_by_hash[str(row["provider_payload_sha256_v3"])].add(str(row["scenario_id"]))
    for values in scenarios_by_hash.values():
        ordered = sorted(values)
        for value in ordered[1:]:
            union(ordered[0], value)

    components: dict[str, set[str]] = defaultdict(set)
    for scenario in scenarios:
        components[find(scenario)].add(scenario)
    requests_by_component: dict[str, set[str]] = defaultdict(set)
    pages_by_component: dict[str, set[str]] = defaultdict(set)
    modes_by_component: dict[str, set[str]] = defaultdict(set)
    for row in conditions:
        component = find(str(row["scenario_id"]))
        requests_by_component[component].add(str(row["provider_payload_sha256_v3"]))
        pages_by_component[component].add(str(row["current_page"]))
        modes_by_component[component].add(str(row["mode_id"]))
    order = sorted(
        components,
        key=lambda component: (
            -sum(unique[value]["estimated_input_tokens"] for value in requests_by_component[component]),
            -len(requests_by_component[component]),
            hashlib.sha256(
                f"{SEED}|{'|'.join(sorted(components[component]))}".encode("utf-8")
            ).hexdigest(),
        ),
    )
    state = {
        shard: {"tokens": 0, "requests": set(), "pages": set(), "modes": set()}
        for shard in "ABC"
    }
    for component in order:
        request_hashes = requests_by_component[component]
        token_total = sum(unique[value]["estimated_input_tokens"] for value in request_hashes)
        candidates = []
        for shard in "ABC":
            tie = hashlib.sha256(f"{SEED}|{component}|{shard}".encode("utf-8")).hexdigest()
            candidates.append(
                (
                    state[shard]["tokens"] + token_total,
                    len(state[shard]["requests"] | request_hashes),
                    -len(pages_by_component[component] - state[shard]["pages"]),
                    -len(modes_by_component[component] - state[shard]["modes"]),
                    tie,
                    shard,
                )
            )
        shard = min(candidates)[-1]
        state[shard]["tokens"] += token_total
        state[shard]["requests"].update(request_hashes)
        state[shard]["pages"].update(pages_by_component[component])
        state[shard]["modes"].update(modes_by_component[component])
        for request_hash in request_hashes:
            prior = unique[request_hash].get("shard_id")
            if prior is not None and prior != shard:
                raise RuntimeError("V3 request assigned to multiple shards")
            unique[request_hash]["shard_id"] = shard
    for scenario in scenarios:
        shards = {
            unique[str(row["provider_payload_sha256_v3"])]["shard_id"]
            for row in conditions
            if row["scenario_id"] == scenario
        }
        if len(shards) != 1:
            raise RuntimeError("scenario-atomic shard assignment failed")


def build_outputs(key: bytes, v2_metadata: Mapping[str, Any]) -> dict[Path, bytes]:
    registry = read_jsonl(V2_REGISTRY_PATH)
    v2_mapping = read_csv(V2_MAPPING_PATH)
    v2_unique = read_jsonl(V2_UNIQUE_MANIFEST_PATH)
    mechanisms = read_jsonl(MECHANISM_PATH)
    applicability = read_jsonl(APPLICABILITY_PATH)
    if not (
        len(registry)
        == len(v2_mapping)
        == len(mechanisms)
        == len(applicability)
        == 558
    ):
        raise RuntimeError("frozen 558-condition input population mismatch")
    mapping_by_key = {(row["scenario_id"], row["mode_id"]): row for row in v2_mapping}
    mechanism_by_key = {(row["scenario_id"], row["mode"]): row for row in mechanisms}
    applicability_by_key = {(row["scenario_id"], row["mode"]): row for row in applicability}
    if not (len(mapping_by_key) == len(mechanism_by_key) == len(applicability_by_key) == 558):
        raise RuntimeError("frozen condition keys are not unique")

    prompt = PROMPT_PATH.read_text(encoding="utf-8")
    prompt_sha256 = sha256_file(PROMPT_PATH)
    v3_conditions: list[dict[str, Any]] = []
    audit_counts: Counter[str] = Counter()
    source_fact_count = 0
    rendered_fact_count = 0
    evidence_item_occurrences: Counter[str] = Counter()
    neutral_note_occurrences: Counter[str] = Counter()
    prohibited_occurrences = 0

    for old_row in registry:
        key_tuple = (old_row["scenario_id"], old_row["mode_id"])
        mapping_row = mapping_by_key[key_tuple]
        mechanism = mechanism_by_key[key_tuple]
        applicability_row = applicability_by_key[key_tuple]
        if old_row["logical_order"] != mechanism["logical_order"]:
            raise RuntimeError("condition logical order changed")
        if old_row["replay_record_id"] != mapping_row["replay_record_id"]:
            raise RuntimeError("V2 registry/mapping binding changed")
        if old_row["compiled_evidence_sha256"] != mechanism["compiled_evidence_sha256"]:
            raise RuntimeError("compiled evidence binding changed")
        if old_row["planner_result_sha256"] != mechanism["planner_result_sha256"]:
            raise RuntimeError("Planning result binding changed")
        if applicability_row["gold_accessed"] is not False or applicability_row[
            "candidate_response_accessed"
        ] is not False:
            raise RuntimeError("frozen applicability provenance changed")

        old_payload = old_row["provider_payload"]
        if sha256_bytes(canonical_bytes(old_payload)) != old_row["provider_payload_sha256_v2"]:
            raise RuntimeError("V2 provider payload hash mismatch")
        old_context = json.loads(old_payload["messages"][1]["content"])
        expected_facts = source_substantive_facts(old_context)
        rendered = render_generation_request_v3_with_audit(old_context)
        rendered_text = rendered.text
        validate_plain_text_message(rendered_text)
        if Counter(expected_facts) != Counter(rendered.rendered_substantive_facts):
            raise RuntimeError("V2/V3 substantive fact mismatch")
        source_fact_count += len(expected_facts)
        rendered_fact_count += len(rendered.rendered_substantive_facts)
        if old_context["current_query"].encode("utf-8") not in rendered_text.encode("utf-8"):
            raise RuntimeError("query bytes not preserved")
        if old_context["current_page"] not in rendered_text:
            raise RuntimeError("page value not preserved")
        for fact_path, fact_text in expected_facts:
            if fact_text not in rendered_text:
                raise RuntimeError(f"substantive text absent from V3 rendering: {fact_path}")

        for item in old_context["evidence"]["evidence"]:
            evidence_item_occurrences[str(item["source"])] += 1
        neutral_note_occurrences.update(old_context["evidence"]["availability_notes"])
        prohibited_occurrences += len(_RAW_INTERNAL_KEY.findall(rendered_text))

        new_payload = copy.deepcopy(old_payload)
        new_payload["messages"][0]["content"] = prompt
        new_payload["messages"][1]["content"] = rendered_text
        for field in ("model", "temperature", "max_tokens", "stream", "response_format"):
            if canonical_bytes(new_payload[field]) != canonical_bytes(old_payload[field]):
                raise RuntimeError(f"provider transport field changed: {field}")
        if new_payload["model"] != MODEL or "tools" in new_payload:
            raise RuntimeError("model or tools boundary changed")
        new_hash = sha256_bytes(canonical_bytes(new_payload))
        audit_counts["query_byte_preserved"] += 1
        audit_counts["page_preserved"] += 1
        audit_counts["history_preserved"] += 1
        audit_counts["evidence_preserved"] += 1
        audit_counts["planning_preserved"] += 1
        audit_counts["plain_text_user_message"] += 1
        audit_counts["provider_configuration_preserved"] += 1

        v3_conditions.append(
            {
                "schema_version": "c4-real-condition-generation-payload-registry-v3",
                "logical_order": old_row["logical_order"],
                "replay_record_id": old_row["replay_record_id"],
                "scenario_id": old_row["scenario_id"],
                "mode_id": old_row["mode_id"],
                "current_page": old_row["current_page"],
                "route_signature": old_row["route_signature"],
                "activation_mask": old_row["activation_mask"],
                "compiled_evidence_sha256": old_row["compiled_evidence_sha256"],
                "planner_result_sha256": old_row["planner_result_sha256"],
                "provider_payload_sha256_v2": old_row["provider_payload_sha256_v2"],
                "provider_payload_sha256_v3": new_hash,
                "provider_payload": new_payload,
            }
        )

    if any(value != 558 for value in audit_counts.values()) or prohibited_occurrences:
        raise RuntimeError("V3 global preservation audit failed")

    unique: dict[str, dict[str, Any]] = {}
    for row in v3_conditions:
        payload_hash = row["provider_payload_sha256_v3"]
        payload_bytes = canonical_bytes(row["provider_payload"])
        prior = unique.setdefault(
            payload_hash,
            {
                "provider_payload": row["provider_payload"],
                "provider_payload_bytes": payload_bytes,
                "estimated_input_tokens": math.ceil(len(payload_bytes) / 4),
            },
        )
        if prior["provider_payload_bytes"] != payload_bytes:
            raise RuntimeError("V3 payload hash collision")
    assign_shards(unique, v3_conditions)
    for payload_hash, value in unique.items():
        value["logical_generation_request_id"] = opaque_id(key, "logical-request-v3", payload_hash)
        value["response_blind_id"] = opaque_id(key, "response-blind-v3", payload_hash)
    if len({value["logical_generation_request_id"] for value in unique.values()}) != len(unique):
        raise RuntimeError("V3 logical request ID collision")
    if len({value["response_blind_id"] for value in unique.values()}) != len(unique):
        raise RuntimeError("V3 response blind ID collision")

    old_g2_ids = {
        record["opaque_response_blind_id"]
        for record in json.loads(
            (REPAIR_DIR / "c4_real_g2_prejudge_format_audit_v1.json").read_text(encoding="utf-8")
        )["records"]
    }
    new_response_ids = {value["response_blind_id"] for value in unique.values()}
    if old_g2_ids & new_response_ids:
        raise RuntimeError("V3 response blind ID collides with G2")

    condition_rows: list[dict[str, Any]] = []
    for row in v3_conditions:
        unique_row = unique[row["provider_payload_sha256_v3"]]
        condition_rows.append(
            {
                "logical_order": row["logical_order"],
                "replay_record_id": row["replay_record_id"],
                "scenario_id": row["scenario_id"],
                "mode_id": row["mode_id"],
                "current_page": row["current_page"],
                "route_signature": row["route_signature"],
                "provider_payload_sha256_v2": row["provider_payload_sha256_v2"],
                "provider_payload_sha256_v3": row["provider_payload_sha256_v3"],
                "logical_generation_request_id": unique_row["logical_generation_request_id"],
                "response_blind_id": unique_row["response_blind_id"],
                "shard_id": unique_row["shard_id"],
            }
        )

    unique_rows = [
        {
            "schema_version": "c4-real-unique-generation-request-frozen-v3",
            "logical_generation_request_id": value["logical_generation_request_id"],
            "response_blind_id": value["response_blind_id"],
            "provider_payload_sha256": payload_hash,
            "estimated_input_tokens": value["estimated_input_tokens"],
            "shard_id": value["shard_id"],
            "provider_payload": value["provider_payload"],
        }
        for payload_hash, value in sorted(
            unique.items(), key=lambda item: item[1]["logical_generation_request_id"]
        )
    ]
    if len(condition_rows) != 558 or len(unique_rows) != len(unique):
        raise RuntimeError("V3 mapping or unique population mismatch")

    restricted_bytes = {
        V3_RESTRICTED_PATHS["registry"]: jsonl_bytes(v3_conditions),
        V3_RESTRICTED_PATHS["condition_mapping"]: csv_bytes(condition_rows, list(condition_rows[0])),
        V3_RESTRICTED_PATHS["response_condition"]: csv_bytes(
            [
                {
                    "response_blind_id": row["response_blind_id"],
                    "replay_record_id": row["replay_record_id"],
                }
                for row in condition_rows
            ],
            ["response_blind_id", "replay_record_id"],
        ),
        V3_RESTRICTED_PATHS["response_scenario"]: csv_bytes(
            [
                {
                    "response_blind_id": row["response_blind_id"],
                    "scenario_id": row["scenario_id"],
                }
                for row in condition_rows
            ],
            ["response_blind_id", "scenario_id"],
        ),
        V3_RESTRICTED_PATHS["response_mode"]: csv_bytes(
            [
                {"response_blind_id": row["response_blind_id"], "mode_id": row["mode_id"]}
                for row in condition_rows
            ],
            ["response_blind_id", "mode_id"],
        ),
    }

    v2_hash_to_v3: dict[str, set[str]] = defaultdict(set)
    v3_hash_to_v2: dict[str, set[str]] = defaultdict(set)
    for row in condition_rows:
        v2_hash_to_v3[row["provider_payload_sha256_v2"]].add(row["provider_payload_sha256_v3"])
        v3_hash_to_v2[row["provider_payload_sha256_v3"]].add(row["provider_payload_sha256_v2"])
    split_v2_count = sum(len(values) > 1 for values in v2_hash_to_v3.values())
    merged_v3_count = sum(len(values) > 1 for values in v3_hash_to_v2.values())
    mode_counts = Counter(row["mode_id"] for row in condition_rows)
    page_counts = Counter(row["current_page"] for row in condition_rows)

    shard_rows = []
    for shard in "ABC":
        requests = [row for row in unique_rows if row["shard_id"] == shard]
        conditions_in_shard = [row for row in condition_rows if row["shard_id"] == shard]
        shard_rows.append(
            {
                "shard_id": shard,
                "unique_request_count": len(requests),
                "estimated_input_tokens": sum(row["estimated_input_tokens"] for row in requests),
                "maximum_physical_attempt_count": len(requests) * 2,
                "page_coverage_count": len({row["current_page"] for row in conditions_in_shard}),
                "mode_coverage_count": len({row["mode_id"] for row in conditions_in_shard}),
                "scenario_atomic": True,
            }
        )
    if {row["shard_id"] for row in shard_rows if row["unique_request_count"]} != {"A", "B", "C"}:
        raise RuntimeError("exactly three non-empty V3 shards were not produced")

    dedup_summary = {
        "schema_version": "c4-real-generation-request-deduplication-summary-v3",
        "condition_mapping_count": len(condition_rows),
        "g2_v2_unique_request_count": len(v2_unique),
        "v3_unique_request_count": len(unique_rows),
        "v3_duplicate_mapping_count": len(condition_rows) - len(unique_rows),
        "unique_request_count_change_from_g2_v2": len(unique_rows) - len(v2_unique),
        "split_v2_request_count": split_v2_count,
        "merged_v3_request_count": merged_v3_count,
        "deduplication_rule": "EXACT_CANONICAL_V3_PROVIDER_PAYLOAD_BYTES_ONLY",
        "estimated_input_tokens": sum(row["estimated_input_tokens"] for row in unique_rows),
        "counts_by_mode": dict(sorted(mode_counts.items())),
        "counts_by_page": dict(sorted(page_counts.items())),
        "changes_relative_to_g2_v2": [
            "The single frozen V3 system prompt adds an explicit student-facing answer_text contract.",
            "The complete provider-visible request context is rendered as deterministic plain text instead of one JSON object.",
            "No G2 answer is used as input and no mechanism, evidence, route, or applicability result changes.",
        ],
        "unique_request_count_forced_to_197": False,
        "provider_calls": 0,
        "generation_calls": 0,
    }
    shard_summary = {
        "schema_version": "c4-real-generation-shard-summary-v3",
        "seed": SEED,
        "optimization_priority": [
            "estimated input-token totals",
            "unique-request counts",
            "page coverage",
            "mode coverage",
            "deterministic hash tie-break",
        ],
        "scenario_atomic": True,
        "unique_request_count": len(unique_rows),
        "logical_call_count": len(unique_rows),
        "maximum_physical_attempt_count": len(unique_rows) * 2,
        "shards": shard_rows,
    }
    diff_audit = {
        "schema_version": "c4-real-generation-renderer-v2-v3-diff-audit-v1",
        "status": "PASS_ZERO_SUBSTANTIVE_EVIDENCE_MISMATCHES",
        "condition_count": len(v3_conditions),
        "conditions_with_query_bytes_preserved": audit_counts["query_byte_preserved"],
        "conditions_with_page_value_preserved": audit_counts["page_preserved"],
        "conditions_with_visible_history_preserved": audit_counts["history_preserved"],
        "conditions_with_all_unique_substantive_evidence_preserved": audit_counts[
            "evidence_preserved"
        ],
        "conditions_with_all_planning_content_preserved": audit_counts["planning_preserved"],
        "conditions_with_plain_text_user_message": audit_counts["plain_text_user_message"],
        "conditions_with_provider_configuration_preserved": audit_counts[
            "provider_configuration_preserved"
        ],
        "v2_raw_json_object_user_message_count": 558,
        "v3_raw_json_object_or_array_user_message_count": 0,
        "source_substantive_fact_occurrence_count": source_fact_count,
        "rendered_substantive_fact_occurrence_count": rendered_fact_count,
        "substantive_fact_mismatch_count": 0,
        "substantive_evidence_mismatch_count": 0,
        "planning_content_mismatch_count": 0,
        "provider_visible_evidence_item_occurrences_by_source": dict(
            sorted(evidence_item_occurrences.items())
        ),
        "neutral_availability_note_occurrences": dict(sorted(neutral_note_occurrences.items())),
        "raw_internal_serialization_key_occurrences": prohibited_occurrences,
        "mode_route_p3_gold_ids_hashes_paths_or_database_exposed": False,
        "new_factual_content_added": False,
        "unique_factual_content_removed": False,
        "evidence_strength_boundaries_preserved": True,
        "neutral_no_result_and_no_match_statements_preserved": True,
        "mechanism_records_changed": False,
        "provider_calls": 0,
        "generation_calls": 0,
    }
    rebuild_summary = {
        "schema_version": "c4-real-condition-payload-rebuild-summary-v3",
        "status": "PASS_ALL_CONDITIONS_UNIFORMLY_REBUILT_WITHOUT_MECHANISM_RERUN",
        "condition_count": len(v3_conditions),
        "mechanism_record_sha256": SCIENTIFIC_HASHES[MECHANISM_PATH],
        "applicability_record_sha256": SCIENTIFIC_HASHES[APPLICABILITY_PATH],
        "rebuilt_fields": [
            "provider-facing plain-text user message",
            "V3 provider payload",
            "canonical V3 request hash",
            "V3 unique-request mapping",
            "V3 blind identities",
            "R3 execution packages",
        ],
        "unchanged_fields": [
            "dataset",
            "scenario and condition populations",
            "routes",
            "capability masks",
            "Dashboard evidence",
            "course evidence",
            "learner Memory",
            "Planner output",
            "model",
            "temperature",
            "maximum output tokens",
            "outer response schema",
            "evaluation applicability",
        ],
        "g2_answer_used_as_input_count": 0,
        "rag_rerun_count": 0,
        "memory_rerun_count": 0,
        "planner_rerun_count": 0,
        "p3_rerun_count": 0,
        "evidence_synthesis_rerun_count": 0,
        "provider_calls": 0,
        "generation_calls": 0,
    }
    configuration = {
        "schema_version": "c4-real-generation-configuration-v3",
        "status": "FROZEN_R3_REQUESTS_PREPARED_NO_EXECUTION_AUTHORITY",
        "model": MODEL,
        "temperature": 0,
        "max_output_tokens": 512,
        "streaming": False,
        "tools": "NONE",
        "automatic_sdk_retries": 0,
        "manual_retry": "ONE_BYTE_IDENTICAL_RETRY_ONLY_INVALID_JSON_STRICT_SCHEMA_OR_NON_STUDENT_FACING_FORMAT",
        "output_language": "English",
        "prompt_sha256": prompt_sha256,
        "request_renderer_sha256": sha256_file(RENDERER_PATH),
        "student_facing_format_contract_sha256": sha256_file(FORMAT_CONTRACT_PATH),
        "student_facing_validator_sha256": sha256_file(VALIDATOR_PATH),
        "provider_safe_projection": "c4-real-provider-evidence-projection-v2",
        "provider_transport_schema_path": str(OUTER_SCHEMA_PATH.relative_to(REPO_ROOT)),
        "provider_transport_schema_sha256": OUTER_SCHEMA_SHA256,
        "semantic_validation_after_strict_outer_schema": True,
        "generation_execution_authorised": False,
        "response_generation_executed": False,
        "provider_calls": 0,
        "judge_calls": 0,
        "scoring_calls": 0,
    }

    restricted_metadata = {
        "schema_version": "c4-real-restricted-mapping-metadata-v3",
        "hmac_key_sha256_commitment": HMAC_KEY_COMMITMENT,
        "mapping_files": {
            path.name: {
                "sha256": sha256_bytes(data),
                "row_count": (
                    len(v3_conditions)
                    if path.suffix == ".jsonl"
                    else len(condition_rows)
                ),
            }
            for path, data in sorted(restricted_bytes.items(), key=lambda item: item[0].name)
        },
        "raw_mapping_content_in_metadata": False,
        "raw_key_in_metadata": False,
    }

    dedup_report = (
        "# C4 REAL generation-request deduplication V3\n\n"
        f"- Condition mappings: `{len(condition_rows)}`.\n"
        f"- G2/V2 unique requests: `{len(v2_unique)}`.\n"
        f"- V3 unique requests: `{len(unique_rows)}`.\n"
        f"- V3 duplicate mappings: `{len(condition_rows) - len(unique_rows)}`.\n"
        f"- Unique-request change from G2/V2: `{len(unique_rows) - len(v2_unique)}`.\n"
        f"- V3 estimated input tokens: `{dedup_summary['estimated_input_tokens']}`.\n"
        f"- V2 groups split / V3 groups merged: `{split_v2_count}` / `{merged_v3_count}`.\n\n"
        "Deduplication used exact canonical V3 provider-payload bytes only; the unique-request count was recomputed, not forced. All 558 conditions were rebuilt uniformly. Only the frozen V3 prompt and provider-facing plain-text request rendering changed; no G2 answer, route, mechanism result, evidence, or applicability decision was used or altered.\n"
    ).encode("utf-8")

    outputs: dict[Path, bytes] = {
        **restricted_bytes,
        V3_TRACKED_PATHS["unique_manifest"]: jsonl_bytes(unique_rows),
        V3_TRACKED_PATHS["dedup_summary"]: pretty_json_bytes(dedup_summary),
        V3_TRACKED_PATHS["dedup_report"]: dedup_report,
        V3_TRACKED_PATHS["shard_summary"]: pretty_json_bytes(shard_summary),
        V3_TRACKED_PATHS["restricted_metadata"]: pretty_json_bytes(restricted_metadata),
        V3_TRACKED_PATHS["rebuild_summary"]: pretty_json_bytes(rebuild_summary),
        V3_TRACKED_PATHS["configuration"]: pretty_json_bytes(configuration),
        V3_TRACKED_PATHS["diff_audit"]: pretty_json_bytes(diff_audit),
    }
    return outputs


def publish_once(outputs: Mapping[Path, bytes]) -> None:
    existing = [path for path in outputs if path.exists()]
    if existing:
        raise FileExistsError("refusing to overwrite V3 freeze: " + ", ".join(map(str, existing)))
    created: list[Path] = []
    try:
        for path in sorted(outputs, key=str):
            path.parent.mkdir(parents=True, exist_ok=True)
            descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600 if path.parent == RESTRICTED_DIR else 0o644)
            with os.fdopen(descriptor, "wb") as handle:
                handle.write(outputs[path])
                handle.flush()
                os.fsync(handle.fileno())
            created.append(path)
    except Exception:
        for path in created:
            path.unlink(missing_ok=True)
        raise


def verify_outputs(outputs: Mapping[Path, bytes]) -> None:
    for path, expected in outputs.items():
        if not path.exists() or path.read_bytes() != expected:
            raise RuntimeError(f"V3 frozen output differs from deterministic rebuild: {path}")
    for path in V3_RESTRICTED_PATHS.values():
        if git("check-ignore", "-q", str(path.relative_to(REPO_ROOT)), check=False).returncode != 0:
            raise RuntimeError(f"V3 restricted mapping is not ignored: {path.name}")
        if git("ls-files", "--error-unmatch", str(path.relative_to(REPO_ROOT)), check=False).returncode == 0:
            raise RuntimeError(f"V3 restricted mapping is tracked: {path.name}")
    if sha256_file(HMAC_KEY_PATH) != HMAC_KEY_COMMITMENT:
        raise RuntimeError("HMAC key changed during V3 build")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--verify-only", action="store_true")
    args = parser.parse_args()
    key, metadata = verify_inputs()
    outputs = build_outputs(key, metadata)
    if args.verify_only:
        verify_outputs(outputs)
        print("V3_REGENERATION_ARTIFACTS_VERIFIED")
        return 0
    publish_once(outputs)
    verify_outputs(outputs)
    summary = json.loads(outputs[V3_TRACKED_PATHS["dedup_summary"]])
    print(
        json.dumps(
            {
                "status": "V3_REGENERATION_ARTIFACTS_FROZEN",
                "condition_count": summary["condition_mapping_count"],
                "unique_request_count": summary["v3_unique_request_count"],
                "duplicate_mapping_count": summary["v3_duplicate_mapping_count"],
                "provider_calls": 0,
                "generation_calls": 0,
            },
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
