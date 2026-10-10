#!/usr/bin/env python3
"""Build the offline RQ3-REAL-C4 I1 mechanism and request artifacts."""

from __future__ import annotations

from collections import Counter, defaultdict
from dataclasses import asdict
import hashlib
import hmac
import json
import math
import os
from pathlib import Path
import re
import socket
import stat
import tempfile
from typing import Any, Iterable, Mapping, Sequence
from unittest.mock import patch

from evaluation.rq3_real_c4.i1_route_integration.i1_common import (
    BRANCH,
    COMMIT_MAPPING,
    COURSE_ROOT,
    EXPECTED_HASHES,
    HERE,
    I0,
    METHOD_ID,
    MPNET_PATH,
    ROOT,
    SOURCE_PATHS,
    STARTING_HEAD,
    TRACK_D,
    assemble_p3,
    canonical_bytes,
    canonical_sha256,
    load_jsonl,
    sha256_file,
    verify_sources,
    write_csv,
    write_json,
    write_jsonl,
)
from evaluation.rq3_v2.rq3_0b4_evaluation_protocol.rq3_judge_request_builder import (
    freeze_applicability,
)
from utils.c4_memory.c4_memory_retriever import FrozenLocalMPNetBackend
from utils.c4_real_adapters import (
    C4PersistentLearnerMemoryAdapter,
    C4ProviderCompatibleGenerator,
    C4RealEvidenceCompilerV1,
    C4RealEvidenceSynthesisAdapter,
    C4RecommendationPlannerAdapter,
    C4SelectedR0CourseRAGAdapter,
    FrozenClarificationGateAdapter,
    PrecomputedP3RouteCache,
    project_provider_evidence,
    project_provider_planning_support,
)
from utils.c4_real_contracts import (
    C4Mode,
    C4RealDependencies,
    C4RealRequest,
    ExecutionContext,
)
from utils.c4_real_service import C4RealService


QUERY_TIME = "2026-09-01T12:00:00+00:00"
SHARD_SEED = 20260901
PERSISTENT_SCENARIOS = (
    "U026",
    "U027",
    "U029",
    "U031",
    "U033",
    "U034",
    "U035",
    "U036",
    "U037",
)
EXPECTED_SIGNATURES = {
    "000": 25,
    "001": 8,
    "010": 7,
    "011": 1,
    "100": 7,
    "101": 3,
    "110": 8,
    "111": 3,
}
EXPECTED_ACTIVATION_COUNTS = {
    "route_lookup": 434,
    "evidence_synthesis": 496,
    "evidence_compiler": 558,
    "generation_payload_construction": 558,
    "rag": 84,
    "memory": 76,
    "planning": 60,
}
PROVIDER_PROHIBITED_KEYS = frozenset(
    {
        "path",
        "file_path",
        "file",
        "filename",
        "files",
        "source_file",
        "source_files",
        "source_notes",
        "source_path",
        "source_sha256",
        "sha256",
        "evidence_id",
        "chunk_id",
        "document_id",
        "memory_id",
        "database_path",
        "source_session_id",
        "source_turn_id",
        "student_id",
        "scenario_id",
        "mode",
        "mode_id",
        "condition",
        "condition_id",
        "condition_name",
        "route",
        "route_id",
        "method_id",
        "decision_id",
        "lexical_score",
        "dense_score",
        "semantic_score",
        "fusion_score",
        "embedding",
        "embeddings",
        "cache_key",
        "internal_cache_key",
        "gold",
        "gold_label",
        "expected_label",
        "expected_labels",
        "expected_capabilities",
        "reference_answer",
        "historical_judge_score",
        "compiled_evidence_sha256",
    }
)
_LOCAL_VALUE = re.compile(
    r"(?:/Users/|/private/|/var/folders/|file://|"
    r"(?:^|\s)(?:evaluation|utils|input|course_materials_v2|System Data)/|\.sqlite(?:3)?\b)",
    re.IGNORECASE,
)
_SCENARIO_VALUE = re.compile(r"\bU\d{3}\b")
_MODE_VALUE = re.compile(
    r"\bC(?:0_ORIGINAL|1_EVIDENCE|2_EVIDENCE_RAG|3_EVIDENCE_MEMORY|"
    r"4_EVIDENCE_PLANNING|5_FULL_C4|5_MINUS_RAG|5_MINUS_MEMORY|5_MINUS_PLANNING)\b"
)
_INTERNAL_ROUTE_VALUE = re.compile(r"\b(?:R2V2|C4-P3-|P3)\b")
_VISIBLE_EXCLUSION = re.compile(r"VISIBLE_HISTORY_DUPLICATES_EXCLUDED:(\d+)")


def _request_for(scenario_id: str, value: Mapping[str, Any], mode: C4Mode) -> C4RealRequest:
    return C4RealRequest(
        request_id=f"C4-I1-REQUEST::{scenario_id}::{mode.value}",
        scenario_id=scenario_id,
        mode=mode,
        current_query=str(value["current_query"]),
        current_page=str(value["current_page"]),
        dashboard_context=value["dashboard_context"],
        visible_conversation_history=tuple(value["visible_conversation_history"]),
        student_id=f"C4-I1-STUDENT::{scenario_id}",
        session_id=f"C4-I1-TARGET-SESSION::{scenario_id}",
        state_reset_id=f"C4-I1-RESET::{scenario_id}::{mode.value}",
        execution_context=ExecutionContext.EVALUATION,
    )


def _result_dict(value: Any) -> Any:
    return asdict(value) if value is not None else None


def _route_signature(route: Mapping[str, Any]) -> str:
    return "".join(
        str(int(route[name]))
        for name in ("rag_required", "memory_required", "planning_required")
    )


def write_transport_contracts() -> dict[str, Any]:
    schema_v2_path = HERE / "c4_real_generation_schema_v2_provider_compatible.json"
    expected_schema_v2 = {
        "type": "object",
        "properties": {"answer_text": {"type": "string"}},
        "required": ["answer_text"],
        "additionalProperties": False,
    }
    if json.loads(schema_v2_path.read_text(encoding="utf-8")) != expected_schema_v2:
        raise ValueError("generation schema V2 is not the exact authorised object")
    if sha256_file(SOURCE_PATHS["generation_schema_v1"]) != EXPECTED_HASHES["generation_schema_v1"]:
        raise ValueError("generation schema V1 changed")
    if sha256_file(SOURCE_PATHS["generation_prompt"]) != EXPECTED_HASHES["generation_prompt"]:
        raise ValueError("generation prompt changed")

    config_v2 = {
        "schema_version": "c4-real-generation-configuration-v2",
        "status": "FROZEN_REQUESTS_PREPARED_NO_EXECUTION_AUTHORITY",
        "model": "gpt-4o-mini-2024-07-18",
        "endpoint": "OpenAI Chat Completions",
        "temperature": 0,
        "max_output_tokens": 512,
        "automatic_sdk_retries": 0,
        "manual_retry": "ONE_IDENTICAL_RETRY_ONLY_INVALID_JSON_OR_SCHEMA",
        "streaming": False,
        "tools": "NONE",
        "output_language": "English",
        "prompt_sha256": EXPECTED_HASHES["generation_prompt"],
        "local_semantic_schema_v1_sha256": EXPECTED_HASHES["generation_schema_v1"],
        "provider_transport_schema_v2_sha256": sha256_file(schema_v2_path),
        "provider_transport_schema_v2_path": str(schema_v2_path.relative_to(ROOT)),
        "provider_safe_projection": "c4-real-provider-evidence-projection-v1",
        "generation_execution_authorised": False,
        "response_existed_before_v2": False,
    }
    write_json(HERE / "c4_real_generation_configuration_frozen_v2.json", config_v2)
    (HERE / "C4_REAL_GENERATION_SCHEMA_COMPATIBILITY_NOTE.md").write_text(
        "# C4 REAL generation schema V1/V2 compatibility\n\n"
        "- Response semantics remain exactly one `answer_text` string.\n"
        "- V1 remains the local semantic contract and continues to enforce a non-empty value locally.\n"
        "- V2 changes only the provider transport representation by removing local-validation metadata.\n"
        "- No C4 response existed before this transport change.\n"
        "- No prompt, task, evidence, model, mode, retry policy, or output language changed.\n"
        f"- V1 SHA-256: `{EXPECTED_HASHES['generation_schema_v1']}`.\n"
        f"- V2 SHA-256: `{sha256_file(schema_v2_path)}`.\n"
        f"- Prompt SHA-256 (unchanged): `{EXPECTED_HASHES['generation_prompt']}`.\n",
        encoding="utf-8",
    )
    projection_contract = {
        "schema_version": "c4-real-provider-evidence-projection-v1",
        "status": "FROZEN_ALLOWLIST",
        "provider_visible_top_level_fields": [
            "schema_version",
            "evidence",
            "typed_absence",
            "limitations",
        ],
        "source_kind_allowlists": {
            "DASHBOARD": ["source_kind", "evidence_type", "evidence_strength", "content"],
            "COURSE_RAG": [
                "source_kind",
                "source_type",
                "document_title",
                "week",
                "section",
                "evidence_strength",
                "content",
            ],
            "LEARNER_MEMORY": ["source_kind", "memory_type", "content"],
        },
        "typed_absence_fields": ["source_kind", "status"],
        "prohibited_fields": sorted(PROVIDER_PROHIBITED_KEYS),
        "internal_compiled_evidence_changed": False,
        "projection_implementation": "utils.c4_real_adapters::project_provider_evidence",
    }
    write_json(HERE / "c4_real_provider_evidence_projection_v1.json", projection_contract)

    judge_prompt_v1 = ROOT / "evaluation/rq3_v2/rq3_0b4_evaluation_protocol/rq3_judge_prompt_frozen_v1.txt"
    prompt = judge_prompt_v1.read_text(encoding="utf-8")
    prompt_v2 = prompt.replace(
        "RQ3-0B4 BLIND RESPONSE-QUALITY JUDGE PROMPT v1",
        "RQ3-0B4 BLIND RESPONSE-QUALITY JUDGE PROMPT v2 — provider-compatible transport",
        1,
    )
    prompt_v2 = prompt_v2.replace(
        "5. Return exactly one JSON object matching rq3_judge_response_schema_v1.json. Return no Markdown, prose wrapper, code fence, extra field, or missing field.",
        "5. Return exactly one JSON object matching c4_real_judge_schema_v2_provider_compatible.json. Encode every primary score and EVIDENCE_FAITHFULNESS as a JSON string; use one of \"1\", \"2\", \"3\", \"4\", \"5\", or \"NA\" where NA is permitted. Encode UNSUPPORTED_CLAIM_COUNT and OVERALL_APPLICABLE_MEAN as decimal JSON strings. The local parser restores the unchanged V1 numeric/NA semantics. Return no Markdown, prose wrapper, code fence, extra field, or missing field.",
        1,
    )
    if prompt_v2 == prompt:
        raise ValueError("Judge V2 prompt transport edit was not applied")
    judge_prompt_v2 = HERE / "c4_real_judge_prompt_v2_provider_compatible.txt"
    judge_prompt_v2.write_text(prompt_v2, encoding="utf-8")
    judge_schema_v1 = I0 / "c4_real_judge_schema_v1.json"
    judge_schema_v2 = HERE / "c4_real_judge_schema_v2_provider_compatible.json"
    judge_config_v1 = json.loads((I0 / "c4_real_judge_configuration_frozen_v1.json").read_text(encoding="utf-8"))
    judge_config_v2 = {
        "schema_version": "c4-real-judge-configuration-v2-provider-compatible",
        "status": "TRANSPORT_READY_NO_RESPONSE_NO_JUDGE_REQUEST_NO_CALL",
        "model": "gpt-4.1-2025-04-14",
        "temperature": 0,
        "semantic_contract": "AUTHORITATIVE_V1_UNCHANGED",
        "semantic_schema_v1_sha256": sha256_file(judge_schema_v1),
        "provider_schema_v2_sha256": sha256_file(judge_schema_v2),
        "judge_prompt_v1_sha256": sha256_file(judge_prompt_v1),
        "judge_prompt_v2_sha256": sha256_file(judge_prompt_v2),
        "primary_criteria": judge_config_v1["primary_criteria"],
        "primary_outcome": judge_config_v1["primary_outcome"],
        "secondary_audits": judge_config_v1["secondary_audits"],
        "scale": "1-5_OR_NA_BY_FROZEN_APPLICABILITY",
        "transport_score_encoding": "DECIMAL_STRINGS_NORMALISED_LOCALLY_TO_V1",
        "bootstrap_replicates": judge_config_v1["bootstrap_replicates"],
        "multiplicity": judge_config_v1["multiplicity"],
        "judge_manifest_created": False,
        "judge_calls": 0,
    }
    write_json(HERE / "c4_real_judge_configuration_frozen_v2.json", judge_config_v2)
    (HERE / "C4_REAL_JUDGE_SCHEMA_COMPATIBILITY_NOTE.md").write_text(
        "# C4 REAL Judge transport compatibility\n\n"
        "The authoritative eight-criterion V1 semantic contract and rubric remain unchanged. "
        "V1 uses `$ref`, `$defs`, `oneOf`, numeric bounds, string bounds, a pattern, and local extension metadata. "
        "The provider-facing V2 expands referenced fields and transports scores/counts/mean as strings. "
        "The local V2 adapter converts those strings back to the V1 integer/`NA` representation and invokes the unchanged V1 parser, including applicability and mean recomputation.\n\n"
        "No criterion, applicability rule, 1–5/NA meaning, OVERALL_APPLICABLE_MEAN, EVIDENCE_FAITHFULNESS, "
        "UNSUPPORTED_CLAIM_COUNT, paired comparison, bootstrap rule, or Holm rule changed. No answer-bearing Judge request exists and no Judge call was made.\n",
        encoding="utf-8",
    )
    return {
        "generation_schema_v1_sha256": EXPECTED_HASHES["generation_schema_v1"],
        "generation_schema_v2_sha256": sha256_file(schema_v2_path),
        "generation_prompt_sha256": EXPECTED_HASHES["generation_prompt"],
        "judge_schema_v1_sha256": sha256_file(judge_schema_v1),
        "judge_schema_v2_sha256": sha256_file(judge_schema_v2),
        "judge_prompt_v1_sha256": sha256_file(judge_prompt_v1),
        "judge_prompt_v2_sha256": sha256_file(judge_prompt_v2),
    }


def precondition_memory(
    memory: C4PersistentLearnerMemoryAdapter,
    input_by_id: Mapping[str, Mapping[str, Any]],
) -> dict[str, Any]:
    records = load_jsonl(SOURCE_PATHS["memory_preconditioning_manifest"])
    if tuple(row["scenario_id"] for row in records) != PERSISTENT_SCENARIOS:
        raise ValueError("frozen nine-scenario preconditioning order mismatch")
    receipts: list[dict[str, Any]] = []
    by_id = {row["scenario_id"]: row for row in records}
    for record in records:
        scenario_id = record["scenario_id"]
        value = input_by_id[scenario_id]
        if record["target_query"] != value["current_query"] or not record["target_query_preserved_byte_for_byte"]:
            raise ValueError(f"target query changed: {scenario_id}")
        if record["assistant_recommendation_as_learner_fact"]:
            raise ValueError("assistant recommendation entered learner facts")
        for write in record["writes"]:
            if write["source_role"] == "ASSISTANT":
                raise ValueError("assistant write entered preconditioning")
            if write["source_role"] == "SYSTEM" and (
                write["claim_basis"] != "VERIFIED_SYSTEM_EVENT"
                or write["candidate"]["memory_type"] != "ACTIVE_PLAN"
            ):
                raise ValueError("unverified system plan item entered preconditioning")
        for mode in C4Mode:
            request = _request_for(scenario_id, value, mode)
            proof = dict(memory.precondition(request.memory_scope, record))
            results = proof["write_results"]
            if len(results) != record["setup_write_count"] or any(not item["accepted"] for item in results):
                raise ValueError(f"preconditioning write mismatch: {scenario_id}/{mode.value}")
            if len(proof["active_memory_ids_after_reopen"]) != record["setup_write_count"]:
                raise ValueError(f"preconditioning reopen mismatch: {scenario_id}/{mode.value}")
            receipts.append(
                {
                    "schema_version": "c4-real-i1-memory-preconditioning-receipt-v1",
                    "scenario_id": scenario_id,
                    "source_scenario_id": record["source_scenario_id"],
                    "mode": mode.value,
                    "namespace_sha256": proof["namespace_sha256"],
                    "setup_write_count": len(results),
                    "accepted_write_count": sum(bool(item["accepted"]) for item in results),
                    "active_after_reopen_count": len(proof["active_memory_ids_after_reopen"]),
                    "write_results_sha256": canonical_sha256(results),
                    "integrity_before_close": proof["integrity_before_close"],
                    "integrity_after_reopen": proof["integrity_after_reopen"],
                    "store_reopened": proof["store_reopened"],
                    "raw_database_path_exposed": False,
                }
            )
    if len(receipts) != 81 or len({row["namespace_sha256"] for row in receipts}) != 81:
        raise ValueError("preconditioning namespace population mismatch")
    if sum(row["accepted_write_count"] for row in receipts) != 180:
        raise ValueError("preconditioning accepted-write count mismatch")
    if any(row["scenario_id"] == "U031" and row["setup_write_count"] != 0 for row in receipts):
        raise ValueError("U031 zero-write control changed")

    selected_envelopes: list[dict[str, Any]] = []
    for scenario_id in ("U031", "U036", "U037"):
        request = _request_for(scenario_id, input_by_id[scenario_id], C4Mode.C3_EVIDENCE_MEMORY)
        envelope = memory.read(scope=request.memory_scope, request=request)
        selected_envelopes.append(
            {
                "schema_version": "c4-real-i1-selected-memory-envelope-v1",
                "scenario_id": scenario_id,
                "mode": C4Mode.C3_EVIDENCE_MEMORY.value,
                "purpose": "PRECONDITIONING_DIAGNOSTIC_READ_NOT_A_C4_CONDITION_ACTIVATION",
                "status": envelope.status,
                "selected_item_count": len(envelope.items),
                "selected_items": [
                    {
                        "memory_type": item.item_type,
                        "content": item.value,
                        "version": item.version,
                        "status": item.timestamp_version.get("status"),
                    }
                    for item in envelope.items
                ],
                "limitations": list(envelope.limitations),
                "raw_database_path_exposed": False,
            }
        )
    if next(row for row in selected_envelopes if row["scenario_id"] == "U036")["status"] != "NO_MATCH":
        raise ValueError("U036 frozen NO_MATCH control changed")
    write_jsonl(HERE / "c4_real_memory_preconditioning_receipts_v1.jsonl", receipts)
    write_jsonl(
        HERE / "c4_real_memory_preconditioning_selected_envelopes_v1.jsonl",
        selected_envelopes,
    )
    summary = {
        "schema_version": "c4-real-i1-memory-preconditioning-summary-v1",
        "status": "PASS",
        "scenario_count": len(records),
        "mode_count": len(C4Mode),
        "isolated_namespace_count": len(receipts),
        "unique_namespace_count": len({row["namespace_sha256"] for row in receipts}),
        "setup_write_attempt_count": sum(row["setup_write_count"] for row in receipts),
        "accepted_setup_write_count": sum(row["accepted_write_count"] for row in receipts),
        "rejected_setup_write_count": 0,
        "all_stores_reopened": all(row["store_reopened"] for row in receipts),
        "u031_setup_write_count": sum(
            row["setup_write_count"] for row in receipts if row["scenario_id"] == "U031"
        ),
        "u036_diagnostic_status": next(
            row["status"] for row in selected_envelopes if row["scenario_id"] == "U036"
        ),
        "diagnostic_read_count_separate_from_c4_target_reads": len(selected_envelopes),
        "assistant_recommendation_stored_as_learner_fact": False,
        "target_session_write_proposals": 0,
        "target_session_writes": 0,
        "raw_database_paths_committed": False,
        "manifest_sha256": EXPECTED_HASHES["memory_preconditioning_manifest"],
    }
    write_json(HERE / "c4_real_memory_preconditioning_summary_v1.json", summary)
    return {"records": by_id, "receipts": receipts, "summary": summary, "selected": selected_envelopes}


class NoNetworkSocket(socket.socket):
    attempt_count = 0

    def connect(self, *args: Any, **kwargs: Any) -> Any:
        type(self).attempt_count += 1
        raise AssertionError("I1 replay attempted an outbound socket connection")

    def connect_ex(self, *args: Any, **kwargs: Any) -> Any:
        type(self).attempt_count += 1
        raise AssertionError("I1 replay attempted an outbound socket connection")

    def sendto(self, *args: Any, **kwargs: Any) -> Any:
        type(self).attempt_count += 1
        raise AssertionError("I1 replay attempted an outbound socket send")


def _stable_trace(preparation: Any, scenario_id: str, mode: str) -> dict[str, Any]:
    raw = preparation.trace.to_dict()
    for key in ("trace_id", "latency_ms", "stage_latency_ms", "committed_at_utc"):
        raw.pop(key, None)
    raw["trace_id"] = "C4I1T-" + canonical_sha256(
        {"scenario_id": scenario_id, "mode": mode, "mechanism": preparation.deterministic_hashes}
    )[:24]
    raw["timing_fields_frozen"] = False
    raw["generation_sent"] = False
    return raw


def _provider_leakage_errors(value: Any, path: tuple[str, ...] = ()) -> list[str]:
    errors: list[str] = []
    if isinstance(value, Mapping):
        for key, nested in value.items():
            clean = str(key).casefold()
            if clean in PROVIDER_PROHIBITED_KEYS:
                errors.append("forbidden_key:" + ".".join((*path, str(key))))
            errors.extend(_provider_leakage_errors(nested, (*path, str(key))))
    elif isinstance(value, (list, tuple)):
        for index, nested in enumerate(value):
            errors.extend(_provider_leakage_errors(nested, (*path, str(index))))
    elif isinstance(value, str):
        if _LOCAL_VALUE.search(value):
            errors.append("local_path_value:" + ".".join(path))
        if _SCENARIO_VALUE.search(value):
            errors.append("scenario_value:" + ".".join(path))
        if _MODE_VALUE.search(value):
            errors.append("mode_value:" + ".".join(path))
        if _INTERNAL_ROUTE_VALUE.search(value):
            errors.append("route_value:" + ".".join(path))
    return errors


def run_replay(
    source: Mapping[str, Any],
    p3: Mapping[str, Any],
    memory: C4PersistentLearnerMemoryAdapter,
) -> dict[str, Any]:
    route_inputs = source["route_inputs"]
    input_by_id = {row["scenario_id"]: row["semantic_input"] for row in route_inputs}
    route_by_id = {row["scenario_id"]: row for row in p3["routes"]}
    route_provider = PrecomputedP3RouteCache(
        p3["cache"]["route_cache"],
        evaluation_mode=True,
    )
    evidence = C4RealEvidenceSynthesisAdapter(dashboard_data=None)
    rag = C4SelectedR0CourseRAGAdapter()
    planner = C4RecommendationPlannerAdapter()
    generator = C4ProviderCompatibleGenerator(execution_authorised=False)
    service = C4RealService(
        C4RealDependencies(
            clarification_gate=FrozenClarificationGateAdapter(),
            p3_router=route_provider,
            evidence_synthesiser=evidence,
            course_rag=rag,
            learner_memory=memory,
            evidence_compiler=C4RealEvidenceCompilerV1(),
            planner=planner,
            generator=generator,
            output_guard=object(),
            trace_sink=None,
        )
    )

    mechanism_records: list[dict[str, Any]] = []
    traces: list[dict[str, Any]] = []
    dashboard_records: list[dict[str, Any]] = []
    rag_records: list[dict[str, Any]] = []
    memory_records: list[dict[str, Any]] = []
    planner_records: list[dict[str, Any]] = []
    compiled_records: list[dict[str, Any]] = []
    payload_registry: list[dict[str, Any]] = []
    module_counts: Counter[str] = Counter()
    NoNetworkSocket.attempt_count = 0
    with patch.object(socket, "socket", NoNetworkSocket):
        for logical_order, replay_row in enumerate(source["replay"], 1):
            scenario_id = replay_row["scenario_id"]
            mode = C4Mode(replay_row["mode_id"])
            value = input_by_id[scenario_id]
            provider_input = replay_row["provider_input"]
            observed = {
                "current_query": provider_input["current_query"],
                "current_page": provider_input["current_page"],
                "dashboard_context": provider_input["dashboard_context"],
                "visible_conversation_history": provider_input["visible_conversation_history"],
            }
            if canonical_bytes(observed) != canonical_bytes(value):
                raise ValueError(f"replay semantic input changed: {scenario_id}/{mode.value}")
            request = _request_for(scenario_id, value, mode)
            preparation = service.prepare_generation_request(
                request,
                payload_builder=generator,
            )
            if not preparation.success or not preparation.generation_ready:
                raise RuntimeError(
                    f"irrecoverable pre-generation failure: {scenario_id}/{mode.value}: {preparation.error}"
                )
            if preparation.generation_sent:
                raise RuntimeError("I1 preparation sent a generation request")
            called = tuple(preparation.trace.modules_actually_called)
            module_counts.update(called)
            for prohibited in ("common_generator", "output_guard", "memory_write_proposal"):
                if prohibited in called:
                    raise RuntimeError(f"I1 preparation executed prohibited module: {prohibited}")
            if mode in {C4Mode.C0_ORIGINAL, C4Mode.C1_EVIDENCE} and "frozen_scenario_route_provider" in called:
                raise RuntimeError("C0/C1 performed a P3 lookup")

            route = route_by_id[scenario_id]
            signature = _route_signature(route)
            activation = preparation.activation.to_trace_dict()
            payload = dict(preparation.provider_generation_payload)
            leakage = _provider_leakage_errors(payload)
            if leakage:
                raise ValueError(f"provider-payload leakage: {scenario_id}/{mode.value}:{leakage[:3]}")
            trace = _stable_trace(preparation, scenario_id, mode.value)
            traces.append(trace)
            dashboard_value = _result_dict(preparation.dashboard_evidence)
            rag_value = _result_dict(preparation.course_rag)
            memory_value = _result_dict(preparation.learner_memory)
            planner_value = _result_dict(preparation.planner_result)
            compiled_value = _result_dict(preparation.compiled_evidence)
            dashboard_records.append(
                {
                    "schema_version": "c4-real-condition-dashboard-evidence-frozen-v1",
                    "scenario_id": scenario_id,
                    "mode": mode.value,
                    "activation": activation["evidence_synthesis"],
                    "status": (
                        preparation.dashboard_evidence.status
                        if preparation.dashboard_evidence is not None
                        else "NOT_ACTIVATED"
                    ),
                    "result": dashboard_value,
                    "result_sha256": canonical_sha256(dashboard_value),
                }
            )
            rag_records.append(
                {
                    "schema_version": "c4-real-condition-rag-result-frozen-v1",
                    "scenario_id": scenario_id,
                    "mode": mode.value,
                    "activation": activation["rag"],
                    "status": (
                        preparation.course_rag.result_status
                        if preparation.course_rag is not None
                        else "NOT_ACTIVATED"
                    ),
                    "result": rag_value,
                    "result_sha256": canonical_sha256(rag_value),
                }
            )
            memory_records.append(
                {
                    "schema_version": "c4-real-condition-memory-result-frozen-v1",
                    "scenario_id": scenario_id,
                    "mode": mode.value,
                    "activation": activation["memory"],
                    "status": (
                        preparation.learner_memory.status
                        if preparation.learner_memory is not None
                        else "NOT_ACTIVATED"
                    ),
                    "result": memory_value,
                    "result_sha256": canonical_sha256(memory_value),
                }
            )
            planner_records.append(
                {
                    "schema_version": "c4-real-condition-planner-result-frozen-v1",
                    "scenario_id": scenario_id,
                    "mode": mode.value,
                    "activation": activation["planning"],
                    "status": (
                        preparation.planner_result.status
                        if preparation.planner_result is not None
                        else "NOT_ACTIVATED"
                    ),
                    "result": planner_value,
                    "result_sha256": canonical_sha256(planner_value),
                }
            )
            compiled_records.append(
                {
                    "schema_version": "c4-real-condition-compiled-evidence-frozen-v1",
                    "scenario_id": scenario_id,
                    "mode": mode.value,
                    "compiled_evidence": compiled_value,
                    "compiled_evidence_sha256": preparation.compiled_evidence.compiled_evidence_sha256,
                    "provider_projection": project_provider_evidence(preparation.compiled_evidence),
                    "provider_planning_projection": project_provider_planning_support(
                        preparation.planner_result
                    ),
                }
            )
            mechanism_records.append(
                {
                    "schema_version": "c4-real-condition-mechanism-record-frozen-v1",
                    "logical_order": logical_order,
                    "replay_record_id": replay_row["replay_record_id"],
                    "scenario_id": scenario_id,
                    "mode": mode.value,
                    "analysis_tier": replay_row["analysis_tier"],
                    "semantic_input_sha256": route["semantic_input_sha256"],
                    "route_signature": signature,
                    "frozen_route_identity": (
                        {
                            "method_id": route["method_id"],
                            "decision_id": route["decision_id"],
                        }
                        if mode not in {C4Mode.C0_ORIGINAL, C4Mode.C1_EVIDENCE}
                        else None
                    ),
                    "activation_mask": activation,
                    "modules_actually_called": list(called),
                    "provider_call_count": 0,
                    "generator_transport_call_count": 0,
                    "judge_call_count": 0,
                    "memory_write_proposal_count": 0,
                    "target_memory_write_count": 0,
                    "dashboard_result_sha256": canonical_sha256(dashboard_value),
                    "rag_result_sha256": canonical_sha256(rag_value),
                    "memory_result_sha256": canonical_sha256(memory_value),
                    "compiled_evidence_sha256": preparation.compiled_evidence.compiled_evidence_sha256,
                    "planner_result_sha256": canonical_sha256(planner_value),
                    "generation_payload_sha256": preparation.deterministic_hashes[
                        "provider_generation_payload_sha256"
                    ],
                    "generation_ready": True,
                    "generation_sent": False,
                    "typed_statuses": {
                        "dashboard": dashboard_records[-1]["status"],
                        "rag": rag_records[-1]["status"],
                        "memory": memory_records[-1]["status"],
                        "planning": planner_records[-1]["status"],
                    },
                }
            )
            payload_registry.append(
                {
                    "schema_version": "c4-real-restricted-condition-payload-registry-v1",
                    "logical_order": logical_order,
                    "replay_record_id": replay_row["replay_record_id"],
                    "scenario_id": scenario_id,
                    "mode_id": mode.value,
                    "current_page": value["current_page"],
                    "route_signature": signature,
                    "provider_payload_sha256": preparation.deterministic_hashes[
                        "provider_generation_payload_sha256"
                    ],
                    "provider_payload": payload,
                }
            )

    if NoNetworkSocket.attempt_count != 0:
        raise RuntimeError("outbound network attempt occurred during I1 replay")
    observed = {
        "route_lookup": module_counts["frozen_scenario_route_provider"],
        "evidence_synthesis": module_counts["dashboard_evidence_synthesis"],
        "evidence_compiler": module_counts["evidence_compiler"],
        "generation_payload_construction": module_counts["generation_payload_construction"],
        "rag": module_counts["course_rag"],
        "memory": module_counts["learner_memory"],
        "planning": module_counts["recommendation_planner"],
    }
    if observed != EXPECTED_ACTIVATION_COUNTS:
        raise ValueError(f"mechanism activation mismatch: {observed}")
    if route_provider.request_count != 434 or route_provider.cache_hit_count != 434:
        raise ValueError("route-cache lookup count mismatch")
    if rag.retrieval_call_count != 21:
        raise ValueError("RAG retrieval-cache miss count mismatch")

    active_rag = [row for row in rag_records if row["activation"]]
    active_memory = [row for row in memory_records if row["activation"]]
    active_planning = [row for row in planner_records if row["activation"]]
    rag_status = Counter(row["status"] for row in active_rag)
    evidence_strengths: Counter[str] = Counter()
    selected_sources = 0
    title_metadata_source_count = 0
    title_metadata_condition_count = 0
    for row in active_rag:
        sources = row["result"]["sources"]
        selected_sources += len(sources)
        has_boundary = False
        for item in sources:
            evidence_strengths[item["evidence_strength"]] += 1
            if item["evidence_strength"] in {"TITLE_AND_METADATA_ONLY", "LINK_ONLY"}:
                title_metadata_source_count += 1
                has_boundary = True
        title_metadata_condition_count += int(has_boundary)
    memory_status = Counter(row["status"] for row in active_memory)
    memory_types: Counter[str] = Counter()
    selected_memory_items = 0
    visible_exclusions = 0
    stale_selection_count = 0
    for row in active_memory:
        result = row["result"]
        selected_memory_items += len(result["items"])
        for item in result["items"]:
            memory_types[item["item_type"]] += 1
            if item["timestamp_version"].get("status") != "ACTIVE":
                stale_selection_count += 1
        for limitation in result["limitations"]:
            match = _VISIBLE_EXCLUSION.search(str(limitation))
            if match:
                visible_exclusions += int(match.group(1))
    planner_status = Counter(row["status"] for row in active_planning)
    zero_step_plans = sum(
        not (row["result"] or {}).get("plan")
        or not (row["result"]["plan"] or {}).get("action_steps")
        for row in active_planning
    )
    if planner_status.get("UNSUPPORTED_OR_INCONSISTENT", 0):
        raise ValueError("Planner produced an inconsistent result")

    write_jsonl(HERE / "c4_real_condition_mechanism_records_frozen_v1.jsonl", mechanism_records)
    write_jsonl(HERE / "c4_real_condition_execution_traces_frozen_v1.jsonl", traces)
    write_jsonl(HERE / "c4_real_condition_dashboard_evidence_frozen_v1.jsonl", dashboard_records)
    write_jsonl(HERE / "c4_real_condition_rag_results_frozen_v1.jsonl", rag_records)
    write_jsonl(HERE / "c4_real_condition_memory_results_frozen_v1.jsonl", memory_records)
    write_jsonl(HERE / "c4_real_condition_planner_results_frozen_v1.jsonl", planner_records)
    write_jsonl(HERE / "c4_real_condition_compiled_evidence_frozen_v1.jsonl", compiled_records)
    summary = {
        "schema_version": "c4-real-mechanism-replay-summary-v1",
        "status": "PASS_LOCAL_PRE_GENERATION_REPLAY",
        "condition_count": len(mechanism_records),
        "scenario_count": len({row["scenario_id"] for row in mechanism_records}),
        "mode_count": len({row["mode"] for row in mechanism_records}),
        "analysis_tier_counts": dict(Counter(row["analysis_tier"] for row in mechanism_records)),
        "c0_c1_zero_route_lookup_count": sum(
            row["mode"] in {"C0_ORIGINAL", "C1_EVIDENCE"}
            and row["frozen_route_identity"] is None
            for row in mechanism_records
        ),
        "observed_module_counts": observed,
        "independently_expected_module_counts": EXPECTED_ACTIVATION_COUNTS,
        "route_cache": {
            "lookup_count": route_provider.request_count,
            "hit_count": route_provider.cache_hit_count,
            "live_decision_count": route_provider.live_decision_count,
        },
        "rag": {
            "activation_count": len(active_rag),
            "unique_route_positive_semantic_input_count": 21,
            "lexical_retrieval_computation_count": rag.retrieval_call_count,
            "retrieval_cache_hit_count": len(active_rag) - rag.retrieval_call_count,
            "result_status_counts": dict(sorted(rag_status.items())),
            "evidence_strength_counts": dict(sorted(evidence_strengths.items())),
            "selected_source_count": selected_sources,
            "no_result_count": rag_status.get("NO_RESULT", 0),
            "title_or_metadata_only_source_count": title_metadata_source_count,
            "title_or_metadata_only_condition_count": title_metadata_condition_count,
            "selected_implementation": "C4_RAG_R0_LEXICAL",
        },
        "memory": {
            "target_condition_read_count": len(active_memory),
            "status_counts": dict(sorted(memory_status.items())),
            "selected_item_count": selected_memory_items,
            "selected_memory_type_counts": dict(sorted(memory_types.items())),
            "visible_history_exclusion_count": visible_exclusions,
            "stale_or_superseded_selection_count": stale_selection_count,
            "target_write_proposal_count": 0,
            "target_write_count": 0,
        },
        "planner": {
            "activation_count": len(active_planning),
            "status_counts": dict(sorted(planner_status.items())),
            "zero_step_plan_count": zero_step_plans,
            "evidence_provenance_inconsistency_count": planner_status.get(
                "UNSUPPORTED_OR_INCONSISTENT", 0
            ),
            "learner_constraint_inconsistency_count": 0,
        },
        "prepared_generation_payload_count": len(payload_registry),
        "generation_sent_count": 0,
        "provider_call_count": 0,
        "response_generation_count": 0,
        "judge_call_count": 0,
        "route_accuracy_score_count": 0,
        "response_quality_score_count": 0,
        "streamlit_launch_count": 0,
        "outbound_network_attempt_count": NoNetworkSocket.attempt_count,
    }
    write_json(HERE / "c4_real_mechanism_replay_summary_v1.json", summary)
    return {
        "mechanism_records": mechanism_records,
        "traces": traces,
        "dashboard_records": dashboard_records,
        "rag_records": rag_records,
        "memory_records": memory_records,
        "planner_records": planner_records,
        "compiled_records": compiled_records,
        "payload_registry": payload_registry,
        "summary": summary,
        "memory_backend_identity": dict(memory.semantic_backend.identity),
    }


def freeze_applicability_maps(
    replay: Mapping[str, Any],
    p3: Mapping[str, Any],
) -> list[dict[str, Any]]:
    route_by_id = {row["scenario_id"]: row for row in p3["routes"]}
    rag_by_key = {(row["scenario_id"], row["mode"]): row for row in replay["rag_records"]}
    memory_by_key = {(row["scenario_id"], row["mode"]): row for row in replay["memory_records"]}
    planner_by_key = {(row["scenario_id"], row["mode"]): row for row in replay["planner_records"]}
    dashboard_by_key = {(row["scenario_id"], row["mode"]): row for row in replay["dashboard_records"]}
    input_by_id = {
        row["scenario_id"]: row["semantic_input"]
        for row in load_jsonl(SOURCE_PATHS["p3_route_input_manifest"])
    }
    output: list[dict[str, Any]] = []
    for condition in replay["mechanism_records"]:
        scenario_id = condition["scenario_id"]
        mode = condition["mode"]
        route = route_by_id[scenario_id]
        value = input_by_id[scenario_id]
        pages = [str(value["current_page"])]
        dashboard_context = value["dashboard_context"]
        if isinstance(dashboard_context, Mapping):
            for key in dashboard_context:
                if str(key).casefold() in {"overview", "lecture", "resources", "debate", "reflection"}:
                    candidate = str(key).title()
                    if candidate not in pages:
                        pages.append(candidate)
        rag_row = rag_by_key[(scenario_id, mode)]
        memory_row = memory_by_key[(scenario_id, mode)]
        planner_row = planner_by_key[(scenario_id, mode)]
        dashboard_row = dashboard_by_key[(scenario_id, mode)]
        missing = (
            dashboard_row["status"] == "FROZEN_TYPED_EMPTY_OUTPUT_LEVEL_PACK"
            or (rag_row["activation"] and rag_row["status"] == "NO_RESULT")
            or (memory_row["activation"] and memory_row["status"] == "NO_MATCH")
        )
        metadata_only = bool(
            rag_row["activation"]
            and rag_row["result"]
            and any(
                source["evidence_strength"] in {"TITLE_AND_METADATA_ONLY", "LINK_ONLY"}
                for source in rag_row["result"]["sources"]
            )
        )
        metadata = {
            "applicability_metadata_version": "rq3-applicability-source-metadata-v1",
            "student_specific_data_relevant": bool(dashboard_context) or route["memory_required"],
            "long_term_memory_relevant": route["memory_required"],
            "request_requires_advice": route["planning_required"],
            "gold_planning_required": False,
            "student_facing_support_appropriate": True,
            "material_lad_pages": pages,
            "ambiguity_relevant": False,
            "missing_evidence_relevant": bool(missing),
            "insufficiency_relevant": planner_row["status"] == "INSUFFICIENT_EVIDENCE",
            "conflict_relevant": planner_row["status"] == "UNSUPPORTED_OR_INCONSISTENT",
            "boundary_handling_relevant": metadata_only,
        }
        frozen = freeze_applicability(metadata)
        output.append(
            {
                "schema_version": "c4-real-condition-applicability-map-frozen-v1",
                "scenario_id": scenario_id,
                "mode": mode,
                "freeze_timing": "BEFORE_ANY_CANDIDATE_RESPONSE_EXISTS",
                "source_metadata": metadata,
                "frozen_applicability_map": frozen,
                "candidate_response_accessed": False,
                "gold_accessed": False,
            }
        )
    if len(output) != 558 or any(
        row["frozen_applicability_map"]["applicable_primary_count"] < 3 for row in output
    ):
        raise ValueError("applicability population or minimum count mismatch")
    for criterion in ("CLARITY", "CONTEXT_AWARENESS", "RELIABILITY"):
        if any(not row["frozen_applicability_map"]["criteria"][criterion] for row in output):
            raise ValueError(f"always-applicable criterion changed: {criterion}")
    for scenario_id in {row["scenario_id"] for row in output}:
        rows = [row for row in output if row["scenario_id"] == scenario_id]
        personal = {row["frozen_applicability_map"]["criteria"]["PERSONALISATION"] for row in rows}
        action = {row["frozen_applicability_map"]["criteria"]["ACTIONABILITY"] for row in rows}
        if len(personal) != 1 or len(action) != 1:
            raise ValueError("module OFF changed scenario-level need applicability")
    write_jsonl(HERE / "c4_real_condition_applicability_maps_frozen_v1.jsonl", output)
    return output


def _ensure_blinding_key() -> tuple[bytes, Path]:
    restricted = HERE / "restricted_internal"
    restricted.mkdir(exist_ok=True)
    key_path = restricted / "c4_real_i1_blinding_hmac_key.bin"
    if key_path.exists():
        key = key_path.read_bytes()
    else:
        descriptor = os.open(key_path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        key = os.urandom(32)
        with os.fdopen(descriptor, "wb") as handle:
            handle.write(key)
            handle.flush()
            os.fsync(handle.fileno())
    os.chmod(key_path, 0o600)
    if len(key) != 32 or stat.S_IMODE(key_path.stat().st_mode) != 0o600:
        raise ValueError("restricted HMAC key length or mode mismatch")
    return key, key_path


def _opaque_id(key: bytes, purpose: str, payload_hash: str) -> str:
    digest = hmac.new(
        key,
        f"C4_REAL_I1|{SHARD_SEED}|{purpose}|{payload_hash}".encode("utf-8"),
        hashlib.sha256,
    ).hexdigest().upper()
    return ("C4G-" + digest[:24]) if purpose == "logical-request" else ("R3B-" + digest[:20])


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

    by_hash_scenarios: dict[str, set[str]] = defaultdict(set)
    for row in conditions:
        by_hash_scenarios[str(row["provider_payload_sha256"])].add(str(row["scenario_id"]))
    for scenario_set in by_hash_scenarios.values():
        values = sorted(scenario_set)
        for value in values[1:]:
            union(values[0], value)
    components: dict[str, set[str]] = defaultdict(set)
    for scenario in scenarios:
        components[find(scenario)].add(scenario)
    requests_by_component: dict[str, set[str]] = defaultdict(set)
    pages_by_component: dict[str, set[str]] = defaultdict(set)
    modes_by_component: dict[str, set[str]] = defaultdict(set)
    for row in conditions:
        component = find(str(row["scenario_id"]))
        requests_by_component[component].add(str(row["provider_payload_sha256"]))
        pages_by_component[component].add(str(row["current_page"]))
        modes_by_component[component].add(str(row["mode_id"]))
    component_order = sorted(
        components,
        key=lambda component: (
            -sum(unique[value]["estimated_input_tokens"] for value in requests_by_component[component]),
            -len(requests_by_component[component]),
            hashlib.sha256(
                f"{SHARD_SEED}|{'|'.join(sorted(components[component]))}".encode("utf-8")
            ).hexdigest(),
        ),
    )
    state = {
        shard: {"tokens": 0, "requests": set(), "pages": set(), "modes": set()}
        for shard in "ABC"
    }
    for component in component_order:
        request_hashes = requests_by_component[component]
        token_total = sum(unique[value]["estimated_input_tokens"] for value in request_hashes)
        candidates = []
        for shard in "ABC":
            new_pages = len(pages_by_component[component] - state[shard]["pages"])
            new_modes = len(modes_by_component[component] - state[shard]["modes"])
            tie = hashlib.sha256(
                f"{SHARD_SEED}|{component}|{shard}".encode("utf-8")
            ).hexdigest()
            candidates.append(
                (
                    state[shard]["tokens"] + token_total,
                    len(state[shard]["requests"] | request_hashes),
                    -new_pages,
                    -new_modes,
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
                raise ValueError("unique request assigned across shards")
            unique[request_hash]["shard_id"] = shard
    if any("shard_id" not in value for value in unique.values()):
        raise ValueError("unassigned unique request")
    for scenario in scenarios:
        assigned = {
            unique[str(row["provider_payload_sha256"])]["shard_id"]
            for row in conditions
            if row["scenario_id"] == scenario
        }
        if len(assigned) != 1:
            raise ValueError("scenario requests span generation shards")


def deduplicate_and_blind(replay: Mapping[str, Any]) -> dict[str, Any]:
    key, key_path = _ensure_blinding_key()
    conditions = replay["payload_registry"]
    unique: dict[str, dict[str, Any]] = {}
    for row in conditions:
        payload_bytes = canonical_bytes(row["provider_payload"])
        payload_hash = hashlib.sha256(payload_bytes).hexdigest()
        if payload_hash != row["provider_payload_sha256"]:
            raise ValueError("condition payload hash changed before deduplication")
        prior = unique.setdefault(
            payload_hash,
            {
                "provider_payload": row["provider_payload"],
                "provider_payload_bytes": payload_bytes,
                "estimated_input_tokens": math.ceil(len(payload_bytes) / 4),
            },
        )
        if prior["provider_payload_bytes"] != payload_bytes:
            raise ValueError("SHA collision or non-byte-identical deduplication")
    _assign_shards(unique, conditions)
    for payload_hash, value in unique.items():
        value["logical_generation_request_id"] = _opaque_id(
            key, "logical-request", payload_hash
        )
        value["response_blind_id"] = _opaque_id(key, "response-blind", payload_hash)
    if len({value["logical_generation_request_id"] for value in unique.values()}) != len(unique):
        raise ValueError("logical request ID collision")
    if len({value["response_blind_id"] for value in unique.values()}) != len(unique):
        raise ValueError("response blind ID collision")

    condition_rows: list[dict[str, Any]] = []
    for row in conditions:
        item = unique[row["provider_payload_sha256"]]
        condition_rows.append(
            {
                "logical_order": row["logical_order"],
                "replay_record_id": row["replay_record_id"],
                "scenario_id": row["scenario_id"],
                "mode_id": row["mode_id"],
                "current_page": row["current_page"],
                "route_signature": row["route_signature"],
                "provider_payload_sha256": row["provider_payload_sha256"],
                "logical_generation_request_id": item["logical_generation_request_id"],
                "response_blind_id": item["response_blind_id"],
                "shard_id": item["shard_id"],
            }
        )
    restricted = HERE / "restricted_internal"
    write_jsonl(
        restricted / "c4_real_condition_generation_payload_registry_frozen_v1.jsonl",
        conditions,
    )
    write_csv(
        restricted / "c4_real_condition_to_unique_request_mapping_frozen_v1.csv",
        list(condition_rows[0]),
        condition_rows,
    )
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
        restricted / "c4_real_response_to_condition_mapping_frozen_v1.csv",
        ["response_blind_id", "replay_record_id"],
        response_condition,
    )
    write_csv(
        restricted / "c4_real_response_to_scenario_mapping_frozen_v1.csv",
        ["response_blind_id", "scenario_id"],
        response_scenario,
    )
    write_csv(
        restricted / "c4_real_response_to_mode_mapping_frozen_v1.csv",
        ["response_blind_id", "mode_id"],
        response_mode,
    )

    unique_rows = []
    for payload_hash, value in sorted(
        unique.items(), key=lambda item: item[1]["logical_generation_request_id"]
    ):
        unique_rows.append(
            {
                "schema_version": "c4-real-unique-generation-request-frozen-v1",
                "logical_generation_request_id": value["logical_generation_request_id"],
                "response_blind_id": value["response_blind_id"],
                "provider_payload_sha256": payload_hash,
                "estimated_input_tokens": value["estimated_input_tokens"],
                "shard_id": value["shard_id"],
                "provider_payload": value["provider_payload"],
            }
        )
    write_jsonl(
        HERE / "c4_real_unique_generation_request_manifest_frozen_v1.jsonl",
        unique_rows,
    )
    mapping_files = {
        path.name: {
            "sha256": sha256_file(path),
            "row_count": sum(1 for line in path.read_text(encoding="utf-8").splitlines()) - 1
            if path.suffix == ".csv"
            else len(load_jsonl(path)),
        }
        for path in (
            restricted / "c4_real_condition_generation_payload_registry_frozen_v1.jsonl",
            restricted / "c4_real_condition_to_unique_request_mapping_frozen_v1.csv",
            restricted / "c4_real_response_to_condition_mapping_frozen_v1.csv",
            restricted / "c4_real_response_to_scenario_mapping_frozen_v1.csv",
            restricted / "c4_real_response_to_mode_mapping_frozen_v1.csv",
        )
    }
    metadata = {
        "schema_version": "c4-real-restricted-mapping-metadata-v1",
        "status": "PASS_RESTRICTED_UNTRACKED",
        "hmac_key_filename": key_path.name,
        "hmac_key_byte_count": len(key),
        "hmac_key_file_mode": "0600",
        "hmac_key_sha256_commitment": hashlib.sha256(key).hexdigest(),
        "raw_key_committed": False,
        "raw_key_in_generation_packages": False,
        "mapping_files": mapping_files,
    }
    write_json(HERE / "c4_real_restricted_mapping_metadata_v1.json", metadata)

    mode_counts = Counter(row["mode_id"] for row in condition_rows)
    signature_counts = Counter(row["route_signature"] for row in condition_rows)
    shard_summaries = []
    for shard in "ABC":
        rows = [row for row in unique_rows if row["shard_id"] == shard]
        shard_summaries.append(
            {
                "shard_id": shard,
                "unique_request_count": len(rows),
                "estimated_input_tokens": sum(row["estimated_input_tokens"] for row in rows),
                "maximum_physical_attempts": len(rows) * 2,
                "page_coverage_count": len(
                    {
                        row["current_page"]
                        for row in condition_rows
                        if row["shard_id"] == shard
                    }
                ),
                "mode_coverage_count": len(
                    {row["mode_id"] for row in condition_rows if row["shard_id"] == shard}
                ),
                "scenario_identity_exposed": False,
                "mode_identity_exposed_in_package": False,
            }
        )
    shard_summary = {
        "schema_version": "c4-real-generation-shard-summary-v1",
        "seed": SHARD_SEED,
        "scenario_atomic": True,
        "unique_request_count": len(unique_rows),
        "logical_call_count": len(unique_rows),
        "maximum_physical_attempt_count": len(unique_rows) * 2,
        "shards": shard_summaries,
    }
    write_json(HERE / "c4_real_generation_shard_summary_v1.json", shard_summary)
    dedup = {
        "schema_version": "c4-real-generation-request-deduplication-summary-v1",
        "condition_mapping_count": len(condition_rows),
        "unique_request_count": len(unique_rows),
        "duplicate_mapping_count": len(condition_rows) - len(unique_rows),
        "deduplication_rule": "EXACT_CANONICAL_PROVIDER_PAYLOAD_BYTES_ONLY",
        "counts_by_mode": dict(sorted(mode_counts.items())),
        "counts_by_route_signature": dict(sorted(signature_counts.items())),
        "estimated_input_tokens": sum(row["estimated_input_tokens"] for row in unique_rows),
        "future_logical_call_count": len(unique_rows),
        "maximum_future_physical_attempt_count": len(unique_rows) * 2,
        "unique_count_hard_coded": False,
        "provider_calls": 0,
    }
    write_json(HERE / "c4_real_generation_request_deduplication_summary_v1.json", dedup)
    (HERE / "C4_REAL_GENERATION_REQUEST_DEDUPLICATION_REPORT.md").write_text(
        "# C4 REAL generation-request deduplication\n\n"
        f"- Condition mappings: `{dedup['condition_mapping_count']}`.\n"
        f"- Exact unique canonical provider requests: `{dedup['unique_request_count']}`.\n"
        f"- Duplicate condition mappings: `{dedup['duplicate_mapping_count']}`.\n"
        f"- Estimated unique input tokens (UTF-8 canonical bytes / 4, rounded up): `{dedup['estimated_input_tokens']}`.\n"
        f"- Future logical calls: `{dedup['future_logical_call_count']}`.\n"
        f"- Maximum future physical attempts: `{dedup['maximum_future_physical_attempt_count']}`.\n\n"
        "Deduplication used exact canonical provider-payload bytes only. Different evidence, typed absence, "
        "Planning support, model, prompt, page, history, schema, temperature, or token limit cannot share a request. "
        "No generation call was made.\n",
        encoding="utf-8",
    )
    return {
        "unique_rows": unique_rows,
        "condition_rows": condition_rows,
        "metadata": metadata,
        "shard_summary": shard_summary,
        "dedup": dedup,
    }


def write_reports(
    source: Mapping[str, Any],
    p3: Mapping[str, Any],
    precondition: Mapping[str, Any],
    replay: Mapping[str, Any],
    applicability: Sequence[Mapping[str, Any]],
    dedup: Mapping[str, Any],
    transport: Mapping[str, Any],
) -> dict[str, Any]:
    summary = replay["summary"]
    leakage = {
        "schema_version": "c4-real-provider-payload-privacy-and-leakage-audit-v1",
        "status": "PASS_ZERO_LEAKS",
        "provider_payload_count": len(replay["payload_registry"]),
        "unique_provider_payload_count": dedup["dedup"]["unique_request_count"],
        "prohibited_key_occurrence_count": 0,
        "local_path_occurrence_count": 0,
        "scenario_identity_occurrence_count": 0,
        "mode_or_condition_identity_occurrence_count": 0,
        "route_or_method_identity_occurrence_count": 0,
        "gold_expected_reference_answer_occurrence_count": 0,
        "internal_compiled_provenance_preserved": True,
        "provider_projection_contract_sha256": sha256_file(
            HERE / "c4_real_provider_evidence_projection_v1.json"
        ),
    }
    write_json(HERE / "c4_real_provider_payload_privacy_and_leakage_audit_v1.json", leakage)
    (HERE / "C4_REAL_PROVIDER_PAYLOAD_PRIVACY_AND_LEAKAGE_AUDIT.md").write_text(
        "# C4 REAL provider-payload privacy and leakage audit\n\n"
        f"All `{leakage['provider_payload_count']}` condition payloads and "
        f"`{leakage['unique_provider_payload_count']}` unique payloads passed the recursive key/value scan. "
        "No local path, source/hash/evidence/chunk/Memory/database identity, student/scenario/mode/condition/route/method identity, "
        "score, Gold, expected label, reference answer, or historical Judge value was present.\n\n"
        "Full provenance remains in the internal compiled-evidence and mechanism records. Only the separate allowlisted projection enters a provider payload.\n",
        encoding="utf-8",
    )
    (HERE / "C4_REAL_MECHANISM_REPLAY_REPORT.md").write_text(
        "# RQ3-REAL-C4 I1 mechanism replay\n\n"
        f"Status: `{summary['status']}`. The replay prepared `{summary['condition_count']}` provider-safe requests across "
        f"`{summary['scenario_count']}` scenarios and `{summary['mode_count']}` modes without sending any request.\n\n"
        f"- PRIMARY / TARGETED_SECONDARY: `{summary['analysis_tier_counts']['PRIMARY']}` / `{summary['analysis_tier_counts']['TARGETED_SECONDARY']}`.\n"
        f"- C0/C1 zero-P3 conditions: `{summary['c0_c1_zero_route_lookup_count']}`; route-cache lookups: `{summary['route_cache']['lookup_count']}`.\n"
        f"- Evidence Synthesis / Compiler / payload preparation: `{summary['observed_module_counts']['evidence_synthesis']}` / "
        f"`{summary['observed_module_counts']['evidence_compiler']}` / `{summary['prepared_generation_payload_count']}`.\n"
        f"- RAG activations / computations / cache hits: `{summary['rag']['activation_count']}` / "
        f"`{summary['rag']['lexical_retrieval_computation_count']}` / `{summary['rag']['retrieval_cache_hit_count']}`.\n"
        f"- Memory target reads: `{summary['memory']['target_condition_read_count']}`; target writes: `0`.\n"
        f"- Planner activations: `{summary['planner']['activation_count']}`; inconsistent results: "
        f"`{summary['planner']['evidence_provenance_inconsistency_count']}`.\n"
        "- Provider, generation transport, Judge, scoring, and Streamlit calls: `0`.\n",
        encoding="utf-8",
    )
    source_manifest = {
        "schema_version": "c4-real-i1-source-and-output-manifest-v1",
        "status": "PASS",
        "working_directory": str(ROOT),
        "branch": BRANCH,
        "starting_head": STARTING_HEAD,
        "integrated_commit_mapping": [
            {"order": index, "original_commit": original, "cherry_picked_commit": cherry}
            for index, (original, cherry) in enumerate(COMMIT_MAPPING, 1)
        ],
        "frozen_source_hashes": {
            **source["observed_hashes"],
            "course_corpus": EXPECTED_HASHES["course_corpus"],
        },
        "dataset": {
            "dataset_id": "C4_REAL_PRIMARY_UNIFIED_DATASET_V1",
            "scenario_count": 62,
            "sha256": EXPECTED_HASHES["dataset"],
        },
        "replay": {
            "total": 558,
            "primary": 372,
            "targeted_secondary": 186,
        },
        "p3_route_manifest_sha256": sha256_file(
            HERE / "c4_real_p3_route_source_manifest_v1.json"
        ),
        "mechanism_summary_sha256": sha256_file(
            HERE / "c4_real_mechanism_replay_summary_v1.json"
        ),
        "preconditioning_summary_sha256": sha256_file(
            HERE / "c4_real_memory_preconditioning_summary_v1.json"
        ),
        "applicability_map_count": len(applicability),
        "generation_transport": transport,
        "privacy_audit_sha256": sha256_file(
            HERE / "c4_real_provider_payload_privacy_and_leakage_audit_v1.json"
        ),
        "restricted_mapping_metadata_sha256": sha256_file(
            HERE / "c4_real_restricted_mapping_metadata_v1.json"
        ),
        "execution_counters": {
            "external_provider_calls": 0,
            "generation_calls": 0,
            "judge_calls": 0,
            "route_accuracy_scoring_calls": 0,
            "response_quality_scoring_calls": 0,
            "streamlit_launches": 0,
        },
    }
    write_json(HERE / "c4_real_i1_source_manifest_v1.json", source_manifest)
    status = {
        "schema_version": "c4-real-i1-status-v1",
        "RQ3_REAL_I1_STATUS": "READY_FOR_PARALLEL_C4_REAL_RESPONSE_GENERATION_AUTHORIZATION",
        "routes_frozen": True,
        "mechanism_replay_complete": True,
        "provider_safe_requests_frozen": True,
        "generation_packages_preparation_complete": False,
        "response_generation_authorised": False,
        "response_generation_executed": False,
        "judge_executed": False,
        "scoring_executed": False,
        "streamlit_launched": False,
        "external_provider_calls": 0,
    }
    write_json(HERE / "c4_real_i1_status_v1.json", status)
    (HERE / "STATUS.md").write_text(
        "# RQ3-REAL-C4 I1 status\n\n"
        "`RQ3_REAL_I1_STATUS = READY_FOR_PARALLEL_C4_REAL_RESPONSE_GENERATION_AUTHORIZATION`\n\n"
        "Frozen P3 route integration, isolated local mechanism replay, provider-safe request preparation, exact-byte deduplication, "
        "blinding, and deterministic three-shard assignment passed. Generation package construction is the remaining local packaging step.\n\n"
        "No provider request was sent; no student response was generated; no Judge or scoring call was made; Streamlit was not launched. "
        "READY status is not response-generation authority.\n",
        encoding="utf-8",
    )
    return {"source_manifest": source_manifest, "status": status, "leakage": leakage}


def main() -> int:
    os.environ["HF_HUB_OFFLINE"] = "1"
    os.environ["TRANSFORMERS_OFFLINE"] = "1"
    os.environ["HF_DATASETS_OFFLINE"] = "1"
    source = verify_sources()
    p3 = assemble_p3(source)
    transport = write_transport_contracts()
    input_by_id = {
        row["scenario_id"]: row["semantic_input"] for row in source["route_inputs"]
    }
    backend = FrozenLocalMPNetBackend(MPNET_PATH, verify_hashes=True)
    with tempfile.TemporaryDirectory(prefix="c4-real-i1-memory-") as temporary:
        memory = C4PersistentLearnerMemoryAdapter(
            Path(temporary) / "isolated_namespaces",
            evaluation_mode=True,
            semantic_backend=backend,
            clock=lambda: QUERY_TIME,
        )
        precondition = precondition_memory(memory, input_by_id)
        replay = run_replay(source, p3, memory)
        if memory.store_open_count != memory.store_close_count:
            raise RuntimeError("I1 replay left a SQLite store open")
    if replay["memory_backend_identity"].get("backend") != "FROZEN_LOCAL_MPNET":
        raise ValueError("frozen local MPNet Memory backend was not used")
    applicability = freeze_applicability_maps(replay, p3)
    dedup = deduplicate_and_blind(replay)
    reports = write_reports(
        source,
        p3,
        precondition,
        replay,
        applicability,
        dedup,
        transport,
    )
    print(
        json.dumps(
            {
                "status": reports["status"]["RQ3_REAL_I1_STATUS"],
                "routes": len(p3["routes"]),
                "conditions": replay["summary"]["condition_count"],
                "unique_requests": dedup["dedup"]["unique_request_count"],
                "provider_calls": 0,
                "generation_calls": 0,
                "judge_calls": 0,
            },
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
