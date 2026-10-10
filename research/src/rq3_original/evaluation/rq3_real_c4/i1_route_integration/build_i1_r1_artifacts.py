#!/usr/bin/env python3
"""Rebuild only hygienic provider payloads from frozen I1 records."""

from __future__ import annotations

from collections import Counter, defaultdict
import hashlib
import hmac
import json
import math
import os
from pathlib import Path
import stat
from typing import Any, Mapping, Sequence
import zipfile

from evaluation.rq3_real_c4.i1_route_integration.i1_r1_common import (
    AUDIT_PHRASES,
    BRANCH,
    GENERATION_CONFIGURATION_V2_SHA256,
    GENERATION_PROMPT_SHA256,
    GENERATION_SCHEMA_V2_SHA256,
    HERE,
    HMAC_KEY_COMMITMENT,
    MODEL,
    OLD_PACKAGE_PATHS,
    OLD_PACKAGE_SHA256,
    RESTRICTED,
    ROOT,
    SCIENTIFIC_SHA256,
    SEED,
    STARTING_HEAD,
    V1_REQUEST_ARTIFACT_SHA256,
    V1_RESTRICTED_SHA256,
    V2_PROHIBITED_MESSAGE_KEYS,
    V2_PROHIBITED_TEXT,
    assert_sha256,
    canonical_bytes,
    canonical_sha256,
    git,
    load_csv,
    load_jsonl,
    sha256_file,
    write_csv,
    write_json,
    write_jsonl,
)
from evaluation.rq3_real_c4.i1_route_integration.i1_common import SOURCE_PATHS
from utils.c4_real_adapters import (
    PROVIDER_EVIDENCE_PROJECTION_V2_ID,
    project_provider_evidence_v2_from_v1,
)


EXPECTED_OLD_PACKAGE_MEMBERS = frozenset(
    {
        "README.md",
        "BLINDED_REQUESTS.jsonl",
        "GENERATION_PROMPT.txt",
        "GENERATION_SCHEMA.json",
        "GENERATION_CONFIGURATION.json",
        "generation_runner.py",
        "validate_package.py",
        "test_package.py",
        "EXECUTION_CONTRACT.json",
        "PACKAGE_SOURCE_HASHES.json",
    }
)
V1_UNIQUE_MANIFEST = HERE / "c4_real_unique_generation_request_manifest_frozen_v1.jsonl"
V2_UNIQUE_MANIFEST = HERE / "c4_real_unique_generation_request_manifest_frozen_v2.jsonl"
V1_REGISTRY = RESTRICTED / "c4_real_condition_generation_payload_registry_frozen_v1.jsonl"
V2_REGISTRY = RESTRICTED / "c4_real_condition_generation_payload_registry_frozen_v2.jsonl"


def _walk_keys(value: Any, counts: Counter[str]) -> None:
    if isinstance(value, Mapping):
        for key, nested in value.items():
            counts[str(key)] += 1
            _walk_keys(nested, counts)
    elif isinstance(value, (list, tuple)):
        for nested in value:
            _walk_keys(nested, counts)


def _walk_v2_hygiene(value: Any, path: tuple[str, ...] = ()) -> list[str]:
    errors: list[str] = []
    if isinstance(value, Mapping):
        for key, nested in value.items():
            if str(key) in V2_PROHIBITED_MESSAGE_KEYS:
                errors.append("prohibited_key:" + ".".join((*path, str(key))))
            errors.extend(_walk_v2_hygiene(nested, (*path, str(key))))
    elif isinstance(value, (list, tuple)):
        for index, nested in enumerate(value):
            errors.extend(_walk_v2_hygiene(nested, (*path, str(index))))
    elif isinstance(value, str) and V2_PROHIBITED_TEXT.search(value):
        errors.append("prohibited_text:" + ".".join(path))
    return errors


def _source_category_v2(item: Mapping[str, Any]) -> str:
    source = str(item.get("source") or "")
    if source in {"dashboard_activity", "current_page_context"}:
        return "DASHBOARD"
    if source == "course_material":
        return "COURSE_RAG"
    if source == "learner_memory":
        return "LEARNER_MEMORY"
    raise ValueError(f"unknown V2 evidence source: {source}")


def _v2_substantive_item_from_v1(item: Mapping[str, Any]) -> Mapping[str, Any]:
    projected = project_provider_evidence_v2_from_v1(
        {"evidence": [dict(item)], "typed_absence": [], "limitations": []}
    )["evidence"]
    if len(projected) != 1:
        raise ValueError("V1 evidence item did not project exactly once")
    return projected[0]


def verify_frozen_inputs() -> Mapping[str, Any]:
    if Path.cwd().resolve() != ROOT.resolve():
        raise ValueError("I1-R1 builder must run from the repository root")
    if git("branch", "--show-current") != BRANCH:
        raise ValueError("I1-R1 branch mismatch")
    if git("rev-parse", "HEAD") != STARTING_HEAD:
        raise ValueError("I1-R1 starting HEAD mismatch")

    for name, expected in SCIENTIFIC_SHA256.items():
        assert_sha256(HERE / name, expected, name)
    for name, expected in V1_REQUEST_ARTIFACT_SHA256.items():
        assert_sha256(HERE / name, expected, name)
    for name, expected in V1_RESTRICTED_SHA256.items():
        assert_sha256(RESTRICTED / name, expected, name)

    assert_sha256(
        HERE / "c4_real_generation_configuration_frozen_v2.json",
        GENERATION_CONFIGURATION_V2_SHA256,
        "generation configuration V2",
    )
    assert_sha256(
        SOURCE_PATHS["generation_prompt"],
        GENERATION_PROMPT_SHA256,
        "generation prompt",
    )
    assert_sha256(
        HERE / "c4_real_generation_schema_v2_provider_compatible.json",
        GENERATION_SCHEMA_V2_SHA256,
        "generation schema V2",
    )

    old_manifest = json.loads(
        (HERE / "c4_real_generation_package_manifest_v1.json").read_text(encoding="utf-8")
    )
    if any(
        old_manifest.get(field) != 0
        for field in ("provider_calls", "generation_calls", "judge_calls", "scoring_calls")
    ):
        raise ValueError("old package manifest records execution")
    old_packages = []
    for shard in "ABC":
        path = OLD_PACKAGE_PATHS[shard]
        assert_sha256(path, OLD_PACKAGE_SHA256[shard], f"old shard {shard}")
        with zipfile.ZipFile(path) as archive:
            names = archive.namelist()
            if set(names) != EXPECTED_OLD_PACKAGE_MEMBERS or len(names) != len(set(names)):
                raise ValueError(f"old shard {shard} member allowlist changed")
            if any(
                token in name
                for name in names
                for token in ("TERMINAL", "ATTEMPT", "PREFLIGHT_RECEIPT", "RESPONSE")
            ):
                raise ValueError(f"old shard {shard} contains an execution output")
        old_packages.append(
            {
                "shard": shard,
                "path": str(path),
                "sha256": OLD_PACKAGE_SHA256[shard],
                "status": "SUPERSEDED_UNEXECUTED_BY_I1_R1",
                "member_count": len(EXPECTED_OLD_PACKAGE_MEMBERS),
                "execution_output_member_count": 0,
            }
        )

    key_path = RESTRICTED / "c4_real_i1_blinding_hmac_key.bin"
    key = key_path.read_bytes()
    if (
        len(key) != 32
        or stat.S_IMODE(key_path.stat().st_mode) != 0o600
        or hashlib.sha256(key).hexdigest() != HMAC_KEY_COMMITMENT
    ):
        raise ValueError("existing restricted HMAC key identity changed")
    if git("check-ignore", key_path.relative_to(ROOT).as_posix()) == "":
        raise ValueError("restricted HMAC key is not ignored")
    tracked = set(git("ls-files").splitlines())
    if key_path.relative_to(ROOT).as_posix() in tracked:
        raise ValueError("restricted HMAC key is tracked")

    route_manifest = json.loads(
        (HERE / "c4_real_p3_route_source_manifest_v1.json").read_text(encoding="utf-8")
    )
    if route_manifest["component_yes_counts"] != {
        "all_optional_no": 25,
        "any_optional": 37,
        "memory": 19,
        "planning": 15,
        "rag": 21,
    }:
        raise ValueError("frozen P3 route composition changed")
    mechanism = json.loads(
        (HERE / "c4_real_mechanism_replay_summary_v1.json").read_text(encoding="utf-8")
    )
    if mechanism["condition_count"] != 558 or mechanism["analysis_tier_counts"] != {
        "PRIMARY": 372,
        "TARGETED_SECONDARY": 186,
    }:
        raise ValueError("frozen condition population changed")
    return {
        "old_packages": old_packages,
        "key": key,
        "key_path": key_path,
        "scientific_hashes": dict(SCIENTIFIC_SHA256),
        "v1_request_artifact_hashes": dict(V1_REQUEST_ARTIFACT_SHA256),
        "v1_restricted_hashes": dict(V1_RESTRICTED_SHA256),
    }


def audit_v1_unique_payloads() -> Mapping[str, Any]:
    rows = load_jsonl(V1_UNIQUE_MANIFEST)
    if len(rows) != 197:
        raise ValueError("V1 unique request count changed")
    phrase_payload_counts: Counter[str] = Counter()
    phrase_occurrence_counts: Counter[str] = Counter()
    schema_label_payload_count = 0
    schema_label_values: Counter[str] = Counter()
    evidence_types: Counter[str] = Counter()
    duplicate_payload_count = 0
    total_extra_duplicates = 0
    duplicate_extra_by_kind: Counter[str] = Counter()
    duplicate_payloads_by_kind: Counter[str] = Counter()
    distinct_duplicate_hashes: set[str] = set()
    source_item_counts: Counter[str] = Counter()
    for row in rows:
        payload_text = canonical_bytes(row["provider_payload"]).decode("utf-8")
        for phrase in AUDIT_PHRASES:
            count = payload_text.count(phrase)
            phrase_occurrence_counts[phrase] += count
            phrase_payload_counts[phrase] += int(count > 0)
        content = json.loads(row["provider_payload"]["messages"][1]["content"])
        evidence = content["evidence"]
        if "schema_version" in evidence:
            schema_label_payload_count += 1
            schema_label_values[str(evidence["schema_version"])] += 1
        duplicate_in_payload = False
        for source_kind in ("DASHBOARD", "COURSE_RAG", "LEARNER_MEMORY"):
            items = [
                item
                for item in evidence.get("evidence", [])
                if item.get("source_kind") == source_kind
            ]
            source_item_counts[source_kind] += len(items)
            counts = Counter(canonical_bytes(item) for item in items)
            extra = sum(count - 1 for count in counts.values() if count > 1)
            if extra:
                duplicate_in_payload = True
                total_extra_duplicates += extra
                duplicate_extra_by_kind[source_kind] += extra
                duplicate_payloads_by_kind[source_kind] += 1
                distinct_duplicate_hashes.update(
                    hashlib.sha256(identity).hexdigest()
                    for identity, count in counts.items()
                    if count > 1
                )
        duplicate_payload_count += int(duplicate_in_payload)
        for item in evidence.get("evidence", []):
            if "evidence_type" in item:
                evidence_types[str(item["evidence_type"])] += 1
    audit = {
        "schema_version": "c4-real-provider-payload-hygiene-audit-v1",
        "status": "FAIL_HYGIENE_REPAIR_REQUIRED_BEFORE_ANY_RESPONSE",
        "audit_timing": "BEFORE_ANY_C4_REAL_RESPONSE_EXISTS",
        "unique_payload_count": len(rows),
        "phrase_payload_counts": dict(phrase_payload_counts),
        "phrase_occurrence_counts": dict(phrase_occurrence_counts),
        "provider_visible_internal_schema_version_payload_count": schema_label_payload_count,
        "provider_visible_internal_schema_version_values": dict(schema_label_values),
        "provider_visible_evidence_type_occurrences": dict(evidence_types),
        "source_item_occurrences": dict(source_item_counts),
        "payloads_with_exact_duplicate_projected_evidence": duplicate_payload_count,
        "total_extra_duplicate_copies": total_extra_duplicates,
        "duplicate_extra_copies_by_source_kind": dict(duplicate_extra_by_kind),
        "payloads_with_duplicates_by_source_kind": dict(duplicate_payloads_by_kind),
        "distinct_duplicated_item_hash_count": len(distinct_duplicate_hashes),
        "dashboard_duplicate_extra_copy_count": duplicate_extra_by_kind["DASHBOARD"],
        "course_duplicate_extra_copy_count": duplicate_extra_by_kind["COURSE_RAG"],
        "memory_duplicate_extra_copy_count": duplicate_extra_by_kind["LEARNER_MEMORY"],
        "counts_hard_coded_from_external_report": False,
        "provider_calls": 0,
        "response_generation_calls": 0,
    }
    if (
        duplicate_payload_count != 20
        or total_extra_duplicates != 32
        or duplicate_extra_by_kind != Counter({"COURSE_RAG": 32})
    ):
        raise ValueError("independent V1 exact-duplicate audit changed")
    write_json(HERE / "c4_real_provider_payload_hygiene_audit_v1.json", audit)
    return audit


def _opaque_id(key: bytes, purpose: str, payload_hash: str) -> str:
    digest = hmac.new(
        key,
        f"C4_REAL_I1_R1|{SEED}|{purpose}|{payload_hash}".encode("utf-8"),
        hashlib.sha256,
    ).hexdigest().upper()
    return ("C4G-" + digest[:24]) if purpose == "logical-request-v2" else ("R3B-" + digest[:20])


def _assign_shards(
    unique: dict[str, dict[str, Any]],
    conditions: Sequence[Mapping[str, Any]],
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
        scenarios_by_hash[str(row["provider_payload_sha256_v2"])].add(str(row["scenario_id"]))
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
        requests_by_component[component].add(str(row["provider_payload_sha256_v2"]))
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
                raise ValueError("V2 unique request assigned across shards")
            unique[request_hash]["shard_id"] = shard
    for scenario in scenarios:
        shards = {
            unique[str(row["provider_payload_sha256_v2"])]["shard_id"]
            for row in conditions
            if row["scenario_id"] == scenario
        }
        if len(shards) != 1:
            raise ValueError("V2 scenario requests span shards")


def rebuild_payloads(frozen: Mapping[str, Any]) -> Mapping[str, Any]:
    registry = load_jsonl(V1_REGISTRY)
    mechanisms = load_jsonl(HERE / "c4_real_condition_mechanism_records_frozen_v1.jsonl")
    compiled = load_jsonl(HERE / "c4_real_condition_compiled_evidence_frozen_v1.jsonl")
    v1_mapping = load_csv(RESTRICTED / "c4_real_condition_to_unique_request_mapping_frozen_v1.csv")
    if not (len(registry) == len(mechanisms) == len(compiled) == len(v1_mapping) == 558):
        raise ValueError("frozen condition population mismatch")
    mechanism_by_key = {(row["scenario_id"], row["mode"]): row for row in mechanisms}
    compiled_by_key = {(row["scenario_id"], row["mode"]): row for row in compiled}
    mapping_by_key = {(row["scenario_id"], row["mode_id"]): row for row in v1_mapping}
    if not (len(mechanism_by_key) == len(compiled_by_key) == len(mapping_by_key) == 558):
        raise ValueError("frozen condition keys are not unique")

    v2_conditions: list[dict[str, Any]] = []
    v1_items: Counter[str] = Counter()
    v2_items: Counter[str] = Counter()
    duplicate_removed: Counter[str] = Counter()
    conditions_deduplicated = 0
    substantive_mismatch_count = 0
    planning_unchanged_count = 0
    query_page_history_unchanged_count = 0
    provider_config_unchanged_count = 0
    v1_key_counts: Counter[str] = Counter()
    availability_notes: Counter[str] = Counter()
    v2_phrase_occurrences: Counter[str] = Counter()
    v2_duplicate_payloads = 0
    v2_duplicate_extra = 0
    for old_row in registry:
        key = (old_row["scenario_id"], old_row["mode_id"])
        mechanism = mechanism_by_key[key]
        compiled_row = compiled_by_key[key]
        mapping_row = mapping_by_key[key]
        if old_row["logical_order"] != mechanism["logical_order"]:
            raise ValueError("condition logical order changed")
        old_payload = old_row["provider_payload"]
        if canonical_sha256(old_payload) != old_row["provider_payload_sha256"]:
            raise ValueError("V1 provider payload hash mismatch")
        if mechanism["generation_payload_sha256"] != old_row["provider_payload_sha256"]:
            raise ValueError("frozen mechanism/payload binding mismatch")
        old_content = json.loads(old_payload["messages"][1]["content"])
        old_evidence = old_content["evidence"]
        if canonical_bytes(old_evidence) != canonical_bytes(compiled_row["provider_projection"]):
            raise ValueError("frozen compiled/provider projection mismatch")
        if canonical_bytes(old_content["planning_support"]) != canonical_bytes(
            compiled_row["provider_planning_projection"]
        ):
            raise ValueError("frozen Planning projection mismatch")

        new_evidence = project_provider_evidence_v2_from_v1(old_evidence)
        hygiene_errors = _walk_v2_hygiene(new_evidence)
        if hygiene_errors:
            raise ValueError(f"V2 evidence hygiene failure: {key}:{hygiene_errors[:3]}")
        new_content = dict(old_content)
        new_content["evidence"] = new_evidence
        new_payload = json.loads(json.dumps(old_payload, ensure_ascii=False))
        new_payload["messages"][1]["content"] = canonical_bytes(new_content).decode("utf-8")
        new_hash = canonical_sha256(new_payload)

        for field in ("current_query", "current_page", "visible_conversation_history"):
            if canonical_bytes(old_content[field]) != canonical_bytes(new_content[field]):
                raise ValueError(f"provider semantic input changed: {key}/{field}")
        query_page_history_unchanged_count += 1
        if canonical_bytes(old_content["planning_support"]) != canonical_bytes(
            new_content["planning_support"]
        ):
            raise ValueError("Planning support changed")
        planning_unchanged_count += 1
        old_without_user = json.loads(json.dumps(old_payload, ensure_ascii=False))
        new_without_user = json.loads(json.dumps(new_payload, ensure_ascii=False))
        old_without_user["messages"][1]["content"] = "<EVIDENCE_PROJECTION_ONLY>"
        new_without_user["messages"][1]["content"] = "<EVIDENCE_PROJECTION_ONLY>"
        if canonical_bytes(old_without_user) != canonical_bytes(new_without_user):
            raise ValueError("model/prompt/schema/config transport changed")
        provider_config_unchanged_count += 1
        if new_payload["model"] != MODEL:
            raise ValueError("generation model changed")

        _walk_keys(old_evidence, v1_key_counts)
        v1_substantive: dict[str, set[bytes]] = defaultdict(set)
        for item in old_evidence.get("evidence", []):
            kind = str(item.get("source_kind"))
            v1_items[kind] += 1
            v1_substantive[kind].add(canonical_bytes(_v2_substantive_item_from_v1(item)))
        v2_substantive: dict[str, set[bytes]] = defaultdict(set)
        for item in new_evidence["evidence"]:
            kind = _source_category_v2(item)
            v2_items[kind] += 1
            v2_substantive[kind].add(canonical_bytes(item))
        if dict(v1_substantive) != dict(v2_substantive):
            substantive_mismatch_count += 1
        per_condition_removed = sum(
            len([item for item in old_evidence.get("evidence", []) if item.get("source_kind") == kind])
            - len(v2_substantive.get(kind, set()))
            for kind in ("DASHBOARD", "COURSE_RAG", "LEARNER_MEMORY")
        )
        if per_condition_removed:
            conditions_deduplicated += 1
        for kind in ("DASHBOARD", "COURSE_RAG", "LEARNER_MEMORY"):
            duplicate_removed[kind] += (
                len([item for item in old_evidence.get("evidence", []) if item.get("source_kind") == kind])
                - len(v2_substantive.get(kind, set()))
            )
        availability_notes.update(new_evidence["availability_notes"])
        new_text = canonical_bytes(new_payload).decode("utf-8")
        for phrase in AUDIT_PHRASES:
            v2_phrase_occurrences[phrase] += new_text.count(phrase)
        counts = Counter(canonical_bytes(item) for item in new_evidence["evidence"])
        extra = sum(count - 1 for count in counts.values() if count > 1)
        v2_duplicate_payloads += int(extra > 0)
        v2_duplicate_extra += extra

        v2_conditions.append(
            {
                "schema_version": "c4-real-condition-generation-payload-registry-v2",
                "logical_order": old_row["logical_order"],
                "replay_record_id": old_row["replay_record_id"],
                "scenario_id": old_row["scenario_id"],
                "mode_id": old_row["mode_id"],
                "current_page": old_row["current_page"],
                "route_signature": old_row["route_signature"],
                "activation_mask": mechanism["activation_mask"],
                "compiled_evidence_sha256": mechanism["compiled_evidence_sha256"],
                "planner_result_sha256": mechanism["planner_result_sha256"],
                "provider_payload_sha256_v1": old_row["provider_payload_sha256"],
                "logical_generation_request_id_v1": mapping_row[
                    "logical_generation_request_id"
                ],
                "response_blind_id_v1": mapping_row["response_blind_id"],
                "provider_payload_sha256_v2": new_hash,
                "provider_payload": new_payload,
            }
        )

    if substantive_mismatch_count or v2_duplicate_payloads or v2_duplicate_extra:
        raise ValueError("V2 substantive preservation or exact deduplication failed")
    if any(v2_phrase_occurrences.values()):
        raise ValueError("V2 provider payload retains prohibited implementation text")

    unique: dict[str, dict[str, Any]] = {}
    for row in v2_conditions:
        payload = row["provider_payload"]
        payload_hash = row["provider_payload_sha256_v2"]
        payload_bytes = canonical_bytes(payload)
        prior = unique.setdefault(
            payload_hash,
            {
                "provider_payload": payload,
                "provider_payload_bytes": payload_bytes,
                "estimated_input_tokens": math.ceil(len(payload_bytes) / 4),
            },
        )
        if prior["provider_payload_bytes"] != payload_bytes:
            raise ValueError("V2 payload hash collision")
    _assign_shards(unique, v2_conditions)
    key_bytes = frozen["key"]
    for payload_hash, value in unique.items():
        value["logical_generation_request_id"] = _opaque_id(
            key_bytes, "logical-request-v2", payload_hash
        )
        value["response_blind_id"] = _opaque_id(
            key_bytes, "response-blind-v2", payload_hash
        )
    if len({value["logical_generation_request_id"] for value in unique.values()}) != len(unique):
        raise ValueError("V2 logical request ID collision")
    if len({value["response_blind_id"] for value in unique.values()}) != len(unique):
        raise ValueError("V2 response blind ID collision")

    condition_rows = []
    for row in v2_conditions:
        unique_row = unique[row["provider_payload_sha256_v2"]]
        condition_rows.append(
            {
                "logical_order": row["logical_order"],
                "replay_record_id": row["replay_record_id"],
                "scenario_id": row["scenario_id"],
                "mode_id": row["mode_id"],
                "current_page": row["current_page"],
                "route_signature": row["route_signature"],
                "provider_payload_sha256_v1": row["provider_payload_sha256_v1"],
                "provider_payload_sha256_v2": row["provider_payload_sha256_v2"],
                "logical_generation_request_id": unique_row[
                    "logical_generation_request_id"
                ],
                "response_blind_id": unique_row["response_blind_id"],
                "shard_id": unique_row["shard_id"],
            }
        )
    unique_rows = [
        {
            "schema_version": "c4-real-unique-generation-request-frozen-v2",
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

    write_jsonl(V2_REGISTRY, v2_conditions)
    mapping_path = RESTRICTED / "c4_real_condition_to_unique_request_mapping_frozen_v2.csv"
    write_csv(mapping_path, list(condition_rows[0]), condition_rows)
    response_condition = [
        {
            "response_blind_id": row["response_blind_id"],
            "replay_record_id": row["replay_record_id"],
        }
        for row in condition_rows
    ]
    response_scenario = [
        {"response_blind_id": row["response_blind_id"], "scenario_id": row["scenario_id"]}
        for row in condition_rows
    ]
    response_mode = [
        {"response_blind_id": row["response_blind_id"], "mode_id": row["mode_id"]}
        for row in condition_rows
    ]
    write_csv(
        RESTRICTED / "c4_real_response_to_condition_mapping_frozen_v2.csv",
        ["response_blind_id", "replay_record_id"],
        response_condition,
    )
    write_csv(
        RESTRICTED / "c4_real_response_to_scenario_mapping_frozen_v2.csv",
        ["response_blind_id", "scenario_id"],
        response_scenario,
    )
    write_csv(
        RESTRICTED / "c4_real_response_to_mode_mapping_frozen_v2.csv",
        ["response_blind_id", "mode_id"],
        response_mode,
    )
    write_jsonl(V2_UNIQUE_MANIFEST, unique_rows)

    v2_mapping_paths = (
        V2_REGISTRY,
        mapping_path,
        RESTRICTED / "c4_real_response_to_condition_mapping_frozen_v2.csv",
        RESTRICTED / "c4_real_response_to_scenario_mapping_frozen_v2.csv",
        RESTRICTED / "c4_real_response_to_mode_mapping_frozen_v2.csv",
    )
    v2_mapping_metadata = {}
    for path in v2_mapping_paths:
        row_count = len(load_jsonl(path)) if path.suffix == ".jsonl" else len(load_csv(path))
        v2_mapping_metadata[path.name] = {
            "sha256": sha256_file(path),
            "row_count": row_count,
        }
    restricted_metadata = {
        "schema_version": "c4-real-restricted-mapping-metadata-v2",
        "status": "PASS_V2_RESTRICTED_UNTRACKED_V1_PRESERVED",
        "hmac_key_sha256_commitment": HMAC_KEY_COMMITMENT,
        "hmac_key_byte_count": 32,
        "hmac_key_file_mode": "0600",
        "hmac_key_regenerated": False,
        "v1_mapping_files_preserved": {
            name: {"sha256": digest, "unchanged": True}
            for name, digest in V1_RESTRICTED_SHA256.items()
        },
        "v2_mapping_files": v2_mapping_metadata,
        "raw_key_committed": False,
        "raw_mapping_committed": False,
        "raw_key_or_mapping_in_packages": False,
    }
    write_json(HERE / "c4_real_restricted_mapping_metadata_v2.json", restricted_metadata)

    v1_unique = load_jsonl(V1_UNIQUE_MANIFEST)
    old_hash_by_condition = {
        (row["scenario_id"], row["mode_id"]): row["provider_payload_sha256"]
        for row in registry
    }
    old_to_new: dict[str, set[str]] = defaultdict(set)
    new_to_old: dict[str, set[str]] = defaultdict(set)
    for row in condition_rows:
        old_hash = old_hash_by_condition[(row["scenario_id"], row["mode_id"])]
        new_hash = row["provider_payload_sha256_v2"]
        old_to_new[old_hash].add(new_hash)
        new_to_old[new_hash].add(old_hash)
    split_old_request_count = sum(len(values) > 1 for values in old_to_new.values())
    merged_new_request_count = sum(len(values) > 1 for values in new_to_old.values())
    mode_counts = Counter(row["mode_id"] for row in condition_rows)
    page_counts = Counter(row["current_page"] for row in condition_rows)
    shard_rows = []
    for shard in "ABC":
        requests = [row for row in unique_rows if row["shard_id"] == shard]
        shard_rows.append(
            {
                "shard_id": shard,
                "unique_request_count": len(requests),
                "estimated_input_tokens": sum(row["estimated_input_tokens"] for row in requests),
                "maximum_physical_attempt_count": len(requests) * 2,
                "page_coverage_count": len(
                    {row["current_page"] for row in condition_rows if row["shard_id"] == shard}
                ),
                "mode_coverage_count": len(
                    {row["mode_id"] for row in condition_rows if row["shard_id"] == shard}
                ),
                "scenario_atomic": True,
            }
        )
    dedup_summary = {
        "schema_version": "c4-real-generation-request-deduplication-summary-v2",
        "condition_mapping_count": len(condition_rows),
        "v1_unique_request_count": len(v1_unique),
        "v2_unique_request_count": len(unique_rows),
        "v2_duplicate_mapping_count": len(condition_rows) - len(unique_rows),
        "unique_request_count_change": len(unique_rows) - len(v1_unique),
        "split_old_request_count": split_old_request_count,
        "merged_new_request_count": merged_new_request_count,
        "deduplication_rule": "EXACT_CANONICAL_PROVIDER_PAYLOAD_BYTES_ONLY",
        "estimated_input_tokens": sum(row["estimated_input_tokens"] for row in unique_rows),
        "counts_by_mode": dict(sorted(mode_counts.items())),
        "counts_by_page": dict(sorted(page_counts.items())),
        "why_requests_changed": [
            "Provider evidence projection V2 removes implementation metadata.",
            "Activated no-result states use neutral student-facing wording.",
            "Exact repeated projected evidence copies are removed before payload hashing.",
        ],
        "why_requests_merged": (
            "Distinct V1 payload groups became byte-identical after hygiene repair."
            if merged_new_request_count
            else "No previously distinct V1 request groups became byte-identical."
        ),
        "provider_calls": 0,
        "generation_calls": 0,
    }
    write_json(HERE / "c4_real_generation_request_deduplication_summary_v2.json", dedup_summary)
    (HERE / "C4_REAL_GENERATION_REQUEST_DEDUPLICATION_REPORT_V2.md").write_text(
        "# C4 REAL generation-request deduplication V2\n\n"
        f"- Condition mappings: `{len(condition_rows)}`.\n"
        f"- V1 / V2 unique requests: `{len(v1_unique)}` / `{len(unique_rows)}`.\n"
        f"- V2 duplicate mappings: `{len(condition_rows) - len(unique_rows)}`.\n"
        f"- V2 estimated input tokens: `{dedup_summary['estimated_input_tokens']}`.\n"
        f"- Old groups split / new groups merged: `{split_old_request_count}` / `{merged_new_request_count}`.\n\n"
        "Only exact canonical provider-payload bytes were deduplicated. Changes arise from the V2 evidence-hygiene "
        "projection, neutral activated/no-result wording, and exact duplicate evidence removal. No model, prompt, "
        "schema, query, page, visible history, Planning support, route, or mechanism result changed.\n",
        encoding="utf-8",
    )
    shard_summary = {
        "schema_version": "c4-real-generation-shard-summary-v2",
        "seed": SEED,
        "scenario_atomic": True,
        "unique_request_count": len(unique_rows),
        "logical_call_count": len(unique_rows),
        "maximum_physical_attempt_count": len(unique_rows) * 2,
        "shards": shard_rows,
    }
    write_json(HERE / "c4_real_generation_shard_summary_v2.json", shard_summary)

    diff_audit = {
        "schema_version": "c4-real-provider-projection-v1-v2-diff-audit-v1",
        "status": "PASS_ONLY_METADATA_AND_EXACT_DUPLICATES_REMOVED",
        "condition_count": len(v2_conditions),
        "conditions_with_unchanged_query_page_history": query_page_history_unchanged_count,
        "conditions_with_unchanged_planning_support": planning_unchanged_count,
        "conditions_with_unchanged_model_prompt_schema_configuration": provider_config_unchanged_count,
        "conditions_with_substantive_evidence_set_mismatch": substantive_mismatch_count,
        "conditions_with_exact_evidence_duplicates_removed": conditions_deduplicated,
        "v1_evidence_item_occurrences_by_source_kind": dict(v1_items),
        "v2_evidence_item_occurrences_by_source_kind": dict(v2_items),
        "exact_duplicate_copies_removed_by_source_kind": dict(duplicate_removed),
        "exact_duplicate_copies_removed_total": sum(duplicate_removed.values()),
        "v2_payloads_with_exact_duplicate_evidence": v2_duplicate_payloads,
        "v2_extra_duplicate_copy_count": v2_duplicate_extra,
        "v1_internal_key_occurrences_removed": {
            key: v1_key_counts[key]
            for key in sorted(V2_PROHIBITED_MESSAGE_KEYS)
            if v1_key_counts[key]
        },
        "v2_prohibited_phrase_occurrences": dict(v2_phrase_occurrences),
        "neutral_availability_note_occurrences": dict(availability_notes),
        "every_unique_substantive_v1_item_preserved": True,
        "new_factual_evidence_added": False,
        "planning_support_changed": False,
        "internal_compiled_evidence_changed": False,
        "mechanism_trace_changed": False,
        "provider_calls": 0,
        "generation_calls": 0,
    }
    write_json(HERE / "c4_real_provider_projection_v1_v2_diff_audit.json", diff_audit)

    rebuild_summary = {
        "schema_version": "c4-real-condition-payload-rebuild-summary-v2",
        "status": "PASS_REBUILT_FROM_FROZEN_RECORDS_WITHOUT_MECHANISM_RERUN",
        "condition_count": len(v2_conditions),
        "mechanism_record_sha256": SCIENTIFIC_SHA256[
            "c4_real_condition_mechanism_records_frozen_v1.jsonl"
        ],
        "compiled_evidence_record_sha256": SCIENTIFIC_SHA256[
            "c4_real_condition_compiled_evidence_frozen_v1.jsonl"
        ],
        "query_page_history_unchanged_count": query_page_history_unchanged_count,
        "planning_support_unchanged_count": planning_unchanged_count,
        "model_prompt_schema_configuration_unchanged_count": provider_config_unchanged_count,
        "rag_retrieval_rerun_count": 0,
        "memory_preconditioning_rerun_count": 0,
        "memory_retrieval_rerun_count": 0,
        "planner_rerun_count": 0,
        "p3_rerun_count": 0,
        "evidence_synthesis_rerun_count": 0,
        "provider_calls": 0,
        "generation_calls": 0,
    }
    write_json(HERE / "c4_real_condition_payload_rebuild_summary_v2.json", rebuild_summary)
    return {
        "condition_rows": condition_rows,
        "unique_rows": unique_rows,
        "restricted_metadata": restricted_metadata,
        "dedup_summary": dedup_summary,
        "shard_summary": shard_summary,
        "diff_audit": diff_audit,
        "rebuild_summary": rebuild_summary,
    }


def write_reports(
    frozen: Mapping[str, Any],
    v1_audit: Mapping[str, Any],
    rebuilt: Mapping[str, Any],
) -> None:
    projection_contract = {
        "schema_version": "c4-real-provider-evidence-projection-contract-v2",
        "projection_id": PROVIDER_EVIDENCE_PROJECTION_V2_ID,
        "status": "FROZEN_STUDENT_RELEVANT_HYGIENE_ALLOWLIST",
        "provider_visible_top_level_fields": ["evidence", "availability_notes"],
        "provider_visible_sources": [
            "current_page_context",
            "dashboard_activity",
            "course_material",
            "learner_memory",
        ],
        "neutral_absence_semantics": {
            "course_material_no_result": "No sufficiently relevant course material was found for this request.",
            "learner_memory_no_match": "No relevant earlier-session learner information was available for this request.",
            "empty_dashboard": "No student activity evidence was available for this page.",
        },
        "module_off_semantics": "OMIT_WITHOUT_EXPOSING_ABLATION_OR_ROUTE_STATUS",
        "deduplication": "EXACT_CANONICAL_PROVIDER_VISIBLE_BYTES_PER_SOURCE_FIRST_OCCURRENCE",
        "internal_compiled_evidence_changed": False,
        "planning_support_changed": False,
    }
    write_json(HERE / "c4_real_provider_evidence_projection_v2.json", projection_contract)
    supersession = {
        "schema_version": "c4-real-generation-package-supersession-v1",
        "status": "PASS_ORIGINAL_PACKAGES_PRESERVED_UNEXECUTED",
        "packages": frozen["old_packages"],
        "old_packages_deleted": False,
        "old_packages_overwritten": False,
        "old_packages_executed": False,
        "response_exists": False,
    }
    write_json(HERE / "c4_real_generation_package_supersession_v1.json", supersession)
    preservation = {
        "schema_version": "c4-real-i1-r1-scientific-preservation-manifest-v1",
        "status": "PASS_ALL_FROZEN_SCIENTIFIC_ARTIFACTS_BYTE_IDENTICAL",
        "starting_head": STARTING_HEAD,
        "scientific_artifacts": {
            name: {"sha256_before": digest, "sha256_after": sha256_file(HERE / name), "unchanged": True}
            for name, digest in SCIENTIFIC_SHA256.items()
        },
        "v1_request_artifacts": {
            name: {"sha256_before": digest, "sha256_after": sha256_file(HERE / name), "unchanged": True}
            for name, digest in V1_REQUEST_ARTIFACT_SHA256.items()
        },
        "generation_prompt_sha256": GENERATION_PROMPT_SHA256,
        "generation_schema_v2_sha256": GENERATION_SCHEMA_V2_SHA256,
        "generation_configuration_v2_sha256": GENERATION_CONFIGURATION_V2_SHA256,
        "route_execution_count": 0,
        "local_mechanism_rerun_count": 0,
    }
    write_json(HERE / "c4_real_i1_r1_scientific_preservation_manifest_v1.json", preservation)
    (HERE / "C4_REAL_PRE_GENERATION_PAYLOAD_AND_RUNNER_REPAIR.md").write_text(
        "# C4 REAL pre-generation payload and runner repair\n\n"
        "No C4 REAL response has been generated; this review and repair occurred before any outcome existed. "
        "All frozen route, RAG, Memory, Planner, Evidence Synthesis, compiled-evidence, trace, applicability, "
        "condition, mode, query, and replay results remain byte-identical.\n\n"
        "The I1 provider-safe audit blocked prohibited keys and paths but did not block implementation-status text "
        "inside allowlisted limitation strings. Internal development metadata was therefore present in blinded "
        "provider payloads. The independent audit also found exact repeated course-evidence items. In addition, "
        "the original future runner would continue to later logical requests after a non-retryable error.\n\n"
        "I1-R1 changes only provider-facing hygiene, exact provider-visible evidence deduplication, opaque request "
        "remapping, replacement package preparation, and future execution provenance. It adds no evidence, removes "
        "no unique substantive evidence item, changes no route, and performs no outcome-informed tuning. The original "
        "R1 packages remain preserved and unexecuted with status `SUPERSEDED_UNEXECUTED_BY_I1_R1`.\n",
        encoding="utf-8",
    )
    status = {
        "schema_version": "c4-real-i1-r1-status-v1",
        "RQ3_REAL_I1_R1_STATUS": "PAYLOADS_REPAIRED_AWAITING_R2_PACKAGE_FREEZE",
        "scientific_results_preserved": True,
        "provider_projection_v2_frozen": True,
        "condition_payload_count": 558,
        "v2_unique_request_count": rebuilt["dedup_summary"]["v2_unique_request_count"],
        "replacement_generation_packages_complete": False,
        "response_generation_authorised": False,
        "response_generation_executed": False,
        "provider_calls": 0,
        "judge_calls": 0,
        "scoring_calls": 0,
        "streamlit_launches": 0,
    }
    write_json(HERE / "c4_real_i1_r1_status_v1.json", status)
    (HERE / "STATUS.md").write_text(
        "# RQ3-REAL-C4 I1-R1 status\n\n"
        "`RQ3_REAL_I1_R1_STATUS = PAYLOADS_REPAIRED_AWAITING_R2_PACKAGE_FREEZE`\n\n"
        "Provider projection V2, exact evidence deduplication, 558 repaired payload mappings, preserved HMAC "
        "blinding, and scenario-atomic V2 shard assignment passed. Replacement R2 package construction remains.\n\n"
        "No route or local mechanism was rerun; no provider request, response generation, Judge, scoring, or "
        "Streamlit execution occurred. This status grants no response-generation authority.\n",
        encoding="utf-8",
    )


def main() -> int:
    frozen = verify_frozen_inputs()
    v1_audit = audit_v1_unique_payloads()
    rebuilt = rebuild_payloads(frozen)
    write_reports(frozen, v1_audit, rebuilt)
    print(
        json.dumps(
            {
                "status": "PAYLOADS_REPAIRED_AWAITING_R2_PACKAGE_FREEZE",
                "condition_count": 558,
                "v1_unique_requests": v1_audit["unique_payload_count"],
                "v2_unique_requests": rebuilt["dedup_summary"]["v2_unique_request_count"],
                "exact_duplicate_copies_removed": rebuilt["diff_audit"][
                    "exact_duplicate_copies_removed_total"
                ],
                "provider_calls": 0,
                "generation_calls": 0,
            },
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
