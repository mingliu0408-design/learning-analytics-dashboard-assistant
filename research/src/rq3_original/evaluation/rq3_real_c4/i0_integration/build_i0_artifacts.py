#!/usr/bin/env python3
"""Build frozen I0 manifests and three unexecuted P3 route packages.

The builder is local and deterministic. It verifies all governed input bytes,
runs only the deterministic Clarification Gate, and writes no model output. It
does not import an OpenAI SDK, execute P3, generate a response, call a Judge,
or launch Streamlit.
"""

from __future__ import annotations

from collections import Counter, defaultdict
import csv
import hashlib
import io
import json
from pathlib import Path
import shutil
import stat
import tempfile
from typing import Any, Iterable, Mapping
from zipfile import ZIP_DEFLATED, ZipFile, ZipInfo


if __package__ in {None, ""}:
    import sys

    root = Path(__file__).resolve().parents[3]
    if str(root) not in sys.path:
        sys.path.insert(0, str(root))

from utils.c4_real_adapters import (
    FrozenClarificationGateAdapter,
    canonical_json_bytes,
    semantic_input_sha256,
)
from utils.c4_real_contracts import PrimarySemanticInput


HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]
DOWNLOADS = Path("/Users/liuming/Downloads")
CANONICAL = DOWNLOADS / "duteaiapp_cfull_semantic_integrated_v1_副本3"
TRACK_D = HERE.parent / "track_d_dataset"
RQ2 = ROOT / "evaluation/capability_routing_rq2_v2_stage4"
RQ3_PROTOCOL = ROOT / "evaluation/rq3_v2/rq3_0b4_evaluation_protocol"

UNIFIED = CANONICAL / "evaluation/unified_benchmark_scenarios.jsonl"
ORIGINAL_25 = CANONICAL / "evaluation/scenarios.jsonl"
REFERENCE = CANONICAL / "evaluation/unified_reference_evidence_v1.jsonl"
ORIGINAL_DIALOGUE = CANONICAL / "System Data/Example Conversation Data.csv"
REPLAY = TRACK_D / "c4_real_replay_manifest_unexecuted_v1.jsonl"
IDENTITY = TRACK_D / "final_62_scenario_identity_v1.json"
MEMORY_REGISTRY = TRACK_D / "memory_scenario_registry_v1.csv"
MODE_REGISTRY = TRACK_D / "c4_real_ablation_mode_registry_v1.json"

EXPECTED = {
    str(UNIFIED): "2df88a153101b39872154ed1ef339d6639e3ea28fac7df0eb42dd8bc9d998ce4",
    str(ORIGINAL_25): "e74f1b583c5225da4bb8b999b11c1cf72b8a8f2b89b8633da40982eb675a4d1e",
    str(ORIGINAL_DIALOGUE): "6d91aa61b9a1011318dc1756747752d04c20c45cb4202dc4f06daa23580d3bc8",
    str(RQ2 / "final_router_selection/RQ2_FINAL_ROUTER_FOR_RQ3.json"): "893a0726570ae654d2815a96ab1987555f89fbfc00d6714ab609a979a13d20dd",
}

PERSISTENT_CASES = {
    "U026": "M001",
    "U027": "M002",
    "U029": "M004",
    "U031": "M006",
    "U033": "M008",
    "U034": "M009",
    "U035": "M010",
    "U036": "M011",
    "U037": "M012",
}
RAG_COHORT = (
    "U023", "U024", "U038", "U039", "U040", "U041", "U042", "U043",
    "U044", "U045", "U046", "U047", "U058", "U059", "U060",
)
PRIMARY_MODES = (
    "C0_ORIGINAL",
    "C1_EVIDENCE",
    "C2_EVIDENCE_RAG",
    "C3_EVIDENCE_MEMORY",
    "C4_EVIDENCE_PLANNING",
    "C5_FULL_C4",
)
REMOVE_ONE_MODES = (
    "C5_MINUS_RAG",
    "C5_MINUS_MEMORY",
    "C5_MINUS_PLANNING",
)
ALL_MODES = PRIMARY_MODES + REMOVE_ONE_MODES

PACKAGE_SPECS = {
    "RAG": {
        "filename": "C4_REAL_P3_RAG_ROUTE_EXECUTION_PACKAGE_2026-09-01.zip",
        "package_id": "C4_REAL_P3_RAG_ROUTE_EXECUTION_V1",
        "prompt": RQ2 / "track_k0_specialists/rag_specialist_prompt_frozen_v1.txt",
        "schema": RQ2 / "track_k0_specialists/rag_specialist_schema_v1.json",
        "package": RQ2 / "track_k0_specialists/rag_specialist_final_full_dev_prompt_package_v1.json",
        "prompt_sha256": "e0e34a097ec0449e2cedfa305d43c7aad7b096ca5fb0a64dc54ad39e9c035d5c",
        "schema_sha256": "3a304b91bc642e8d04f59077b4f1240bf5f242105f888cfdb634ffa858901866",
        "example_sha256": "a932596e126ab66c054173bd1b9c454cbba9988e9d0b418da2d80c3e1df1e6eb",
        "response_schema_name": "c4_real_p3_rag_specialist_v1",
        "p3_consumption": "RAG_BIT",
    },
    "MEMORY": {
        "filename": "C4_REAL_P3_MEMORY_ROUTE_EXECUTION_PACKAGE_2026-09-01.zip",
        "package_id": "C4_REAL_P3_MEMORY_ROUTE_EXECUTION_V1",
        "prompt": RQ2 / "track_k0_specialists/memory_specialist_prompt_frozen_v1.txt",
        "schema": RQ2 / "track_k0_specialists/memory_specialist_schema_v1.json",
        "package": RQ2 / "track_k0_specialists/memory_specialist_final_full_dev_prompt_package_v1.json",
        "prompt_sha256": "c8a53b27f16b84ef0373ddfdd20eab997cc986eab10a93a138ede06571ebab04",
        "schema_sha256": "41a0f015b3fd7589bd1a08bd1d3e2a7c8bd5491b22c2531ef43ead634642a3d7",
        "example_sha256": "57a7aecd53710a1587388711177d7564f4560f1a8729939d445268d2514d3eb4",
        "response_schema_name": "c4_real_p3_memory_specialist_v1",
        "p3_consumption": "MEMORY_BIT",
    },
    "B4_PLANNING": {
        "filename": "C4_REAL_P3_B4_PLANNING_ROUTE_EXECUTION_PACKAGE_2026-09-01.zip",
        "package_id": "C4_REAL_P3_B4_PLANNING_ROUTE_EXECUTION_V1",
        "prompt": RQ2 / "track_i_b4/b4_prompt_template_frozen_v1.txt",
        "schema": RQ2 / "track_i_b4/b4_response_schema_v2.json",
        "package": RQ2 / "track_i_b4/b4_final_full_dev_prompt_package_v1.json",
        "prompt_sha256": "62dd0072b40f812bea9d2400bf5053c1d727187c47cab3c8777a341e0a185541",
        "schema_sha256": "8017f1677e3ddc0bdd5042cff1c87e1e8ef4053da10b5c86da2cf45c35319876",
        "example_sha256": "020ec80b8b592a62c9975b47bf5bc63c9dd86c029da05a6a4afd43440291aff2",
        "response_schema_name": "c4_real_p3_b4_route_v1",
        "p3_consumption": "PLANNING_BIT_ONLY_ALL_THREE_BITS_RETAINED",
    },
}


def require(condition: bool, message: str) -> None:
    if not condition:
        raise RuntimeError(message)


def sha_file(path: Path) -> str:
    require(path.is_file(), f"Missing required file: {path}")
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def canonical_sha(value: Any) -> str:
    return hashlib.sha256(canonical_json_bytes(value)).hexdigest()


def load_json(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    require(isinstance(value, dict), f"Expected JSON object: {path}")
    return value


def load_jsonl(path: Path) -> list[dict[str, Any]]:
    rows = []
    for number, line in enumerate(path.read_text(encoding="utf-8-sig").splitlines(), 1):
        if not line.strip():
            continue
        value = json.loads(line)
        require(isinstance(value, dict), f"{path}:{number} is not an object")
        rows.append(value)
    return rows


def write_json(path: Path, value: Any) -> None:
    path.write_text(
        json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True, allow_nan=False) + "\n",
        encoding="utf-8",
    )


def write_jsonl(path: Path, rows: Iterable[Mapping[str, Any]]) -> None:
    path.write_bytes(b"".join(canonical_json_bytes(dict(row)) + b"\n" for row in rows))


def write_csv(path: Path, fields: list[str], rows: list[dict[str, Any]]) -> None:
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields, lineterminator="\n")
        writer.writeheader()
        writer.writerows(rows)


def source_verification() -> None:
    for raw, expected in EXPECTED.items():
        observed = sha_file(Path(raw))
        require(observed == expected, f"Governed source hash mismatch: {raw}: {observed}")
    unified = load_jsonl(UNIFIED)
    require(len(unified) == 62, "Unified dataset is not 62 scenarios")
    require(
        [row["scenario_id"] for row in unified] == [f"U{index:03d}" for index in range(1, 63)],
        "Unified IDs are not exact U001-U062 order",
    )
    require(len(load_jsonl(ORIGINAL_25)) == 25, "Authentic source is not 25 scenarios")
    replay = load_jsonl(REPLAY)
    require(len(replay) == 558, "Replay registry is not 558 records")
    tiers = Counter(row["analysis_tier"] for row in replay)
    require(tiers == {"PRIMARY": 372, "TARGETED_SECONDARY": 186}, f"Replay tiers drifted: {tiers}")
    modes = load_json(MODE_REGISTRY)
    mode_values = [row["mode_id"] for row in modes["modes"]]
    require(tuple(mode_values) == ALL_MODES, f"Nine-mode registry drifted: {mode_values}")


def semantic_inputs() -> list[dict[str, Any]]:
    rows = load_jsonl(REPLAY)
    grouped: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in rows:
        grouped[str(row["scenario_id"])].append(row)
    require(set(grouped) == {f"U{index:03d}" for index in range(1, 63)}, "Replay IDs drifted")
    output = []
    for scenario_id in sorted(grouped):
        observed: dict[str, dict[str, Any]] = {}
        for row in grouped[scenario_id]:
            source = row["provider_input"]
            four = {
                "current_query": source["current_query"],
                "current_page": source["current_page"],
                "dashboard_context": source["dashboard_context"],
                "visible_conversation_history": source["visible_conversation_history"],
            }
            observed[canonical_sha(four)] = four
        require(len(observed) == 1, f"Semantic input differs across modes: {scenario_id}")
        output.append({"scenario_id": scenario_id, "semantic_input": next(iter(observed.values()))})
    return output


def build_gate_and_route_manifests(
    inputs: list[dict[str, Any]],
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    gate = FrozenClarificationGateAdapter()
    decisions: list[dict[str, Any]] = []
    route_rows: list[dict[str, Any]] = []
    for record in inputs:
        value = record["semantic_input"]
        primary = PrimarySemanticInput(
            current_query=value["current_query"],
            current_page=value["current_page"],
            dashboard_context=value["dashboard_context"],
            visible_conversation_history=tuple(value["visible_conversation_history"]),
        )
        digest = semantic_input_sha256(primary)
        decision = gate.evaluate(primary)
        action = "CLARIFY" if decision.needs_clarification else "ANSWER"
        status = (
            "SKIPPED_BY_CLARIFICATION_GATE"
            if decision.needs_clarification
            else "READY_FOR_P3_ROUTE_EXECUTION"
        )
        decisions.append(
            {
                "scenario_id": record["scenario_id"],
                "semantic_input_sha256": digest,
                "dialogue_action": action,
                "matched_clause": decision.reason_code,
                "gate_id": decision.gate_id,
                "execution_kind": "LOCAL_DETERMINISTIC_ZERO_PROVIDER_CALL",
            }
        )
        route_rows.append(
            {
                "schema_version": "c4-real-p3-route-input-v1",
                "scenario_id": record["scenario_id"],
                "semantic_input_sha256": digest,
                "status": status,
                "semantic_input": value if action == "ANSWER" else None,
            }
        )
    write_csv(
        HERE / "c4_real_clarification_decisions_frozen_v1.csv",
        list(decisions[0]),
        decisions,
    )
    write_jsonl(HERE / "c4_real_p3_route_input_manifest_v1.jsonl", route_rows)
    return decisions, route_rows


def add_write(
    writes: list[dict[str, Any]], *, alias: str, source_text: str,
    evidence_span: str, memory_type: str, source_role: str,
    claim_basis: str, event_at: str
) -> None:
    require(evidence_span in source_text, f"Evidence span is not verbatim for {alias}")
    writes.append(
        {
            "alias": alias,
            "source_session_id": "FROZEN_EARLIER_SESSION",
            "source_turn_id": f"FROZEN_SETUP::{alias}",
            "source_text": source_text,
            "source_role": source_role,
            "claim_basis": claim_basis,
            "event_at": event_at,
            "candidate": {
                "operation": "ADD",
                "memory_type": memory_type,
                "content": evidence_span,
                "target_memory_id": None,
                "confidence": 1.0,
                "evidence_span": evidence_span,
            },
        }
    )


def memory_writes(scenario_id: str, history: list[dict[str, Any]]) -> list[dict[str, Any]]:
    require(len(history) == 2, f"Persistent setup is not exactly two turns: {scenario_id}")
    user = str(history[0]["content"])
    assistant = str(history[1]["content"])
    writes: list[dict[str, Any]] = []
    base = int(scenario_id[1:])
    time = lambda offset: f"2026-08-{10 + base % 10:02d}T09:{offset:02d}:00+00:00"
    if scenario_id == "U026":
        for index, text in enumerate(
            (
                "Revisit one missed lecture video and write two notes.",
                "Reply to one debate post by summarising a peer's point and adding your view.",
                "Write one short reflection paragraph connecting a lecture idea to your own learning.",
            ), 1
        ):
            add_write(writes, alias=f"plan_{index}", source_text=assistant, evidence_span=text,
                      memory_type="ACTIVE_PLAN", source_role="SYSTEM",
                      claim_basis="VERIFIED_SYSTEM_EVENT", event_at=time(index))
    elif scenario_id == "U027":
        spans = (
            "Check the week with the lowest resource activity.",
            "Choose one resource from that week and write a short note.",
            "Use the note in a debate or reflection task.",
        )
        for index, text in enumerate(spans, 1):
            add_write(writes, alias=f"plan_{index}", source_text=assistant, evidence_span=text,
                      memory_type="ACTIVE_PLAN", source_role="SYSTEM",
                      claim_basis="VERIFIED_SYSTEM_EVENT", event_at=time(index))
    elif scenario_id == "U029":
        for index, text in enumerate(
            ("Revisit W4 lecture and write two notes.", "Connect one note to a course concept."), 1
        ):
            add_write(writes, alias=f"plan_{index}", source_text=assistant, evidence_span=text,
                      memory_type="ACTIVE_PLAN", source_role="SYSTEM",
                      claim_basis="VERIFIED_SYSTEM_EVENT", event_at=time(index))
    elif scenario_id == "U031":
        return []
    else:
        user_spans: dict[str, list[tuple[str, str]]] = {
            "U033": [("I want to improve my debate participation", "GOAL"),
                     ("I only have 20 minutes each day", "CONSTRAINT")],
            "U034": [("My goal is to catch up on the missed lecture.", "GOAL")],
            "U035": [("I want to connect lecture ideas to my reflection.", "GOAL")],
            "U036": [("I want to improve my debate participation.", "GOAL")],
            "U037": [("I need to catch up", "GOAL"),
                     ("I only have 15 minutes today", "CONSTRAINT")],
        }
        system_spans = {
            "U033": "Start by watching the W4 lecture and writing two notes for a debate reply.",
            "U034": "You should review the W4 lecture first.",
            "U035": "You could choose one W4 concept and write a two-sentence reflection about it.",
            "U036": "You could reply to one debate post.",
            "U037": "Start with one short lecture segment, then write one note.",
        }
        for index, (text, memory_type) in enumerate(user_spans[scenario_id], 1):
            add_write(writes, alias=f"user_{index}", source_text=user, evidence_span=text,
                      memory_type=memory_type, source_role="USER",
                      claim_basis="EXPLICIT_USER_STATEMENT", event_at=time(index))
        text = system_spans[scenario_id]
        add_write(writes, alias="selected_plan", source_text=assistant, evidence_span=text,
                  memory_type="ACTIVE_PLAN", source_role="SYSTEM",
                  claim_basis="VERIFIED_SYSTEM_EVENT", event_at=time(8))
    return writes


def build_memory_manifest(inputs: list[dict[str, Any]]) -> list[dict[str, Any]]:
    by_id = {row["scenario_id"]: row["semantic_input"] for row in inputs}
    registry = {row["unified_scenario_id"]: row for row in csv.DictReader(MEMORY_REGISTRY.open())}
    rows: list[dict[str, Any]] = []
    for scenario_id, source_id in PERSISTENT_CASES.items():
        reg = registry[scenario_id]
        require(reg["persistent_replay_eligible"] == "YES", f"Eligibility drift: {scenario_id}")
        original_history = [dict(item) for item in load_jsonl(UNIFIED)[int(scenario_id[1:]) - 1]["conversation_history"]]
        writes = memory_writes(scenario_id, original_history)
        value = by_id[scenario_id]
        require(value["visible_conversation_history"] == [], f"Target history not reset: {scenario_id}")
        rows.append(
            {
                "schema_version": "c4-real-memory-preconditioning-v1",
                "scenario_id": scenario_id,
                "source_scenario_id": source_id,
                "persistent_replay_eligible": True,
                "memory_architecture": "C4_LEARNER_MEMORY_V1",
                "earlier_session_setup": original_history,
                "earlier_session_setup_sha256": canonical_sha(original_history),
                "writes": writes,
                "setup_write_count": len(writes),
                "target_session_visible_history": [],
                "target_query": value["current_query"],
                "target_query_sha256": hashlib.sha256(value["current_query"].encode()).hexdigest(),
                "target_query_preserved_byte_for_byte": True,
                "expected_target_retrieval": reg["expected_target_retrieval_operation"],
                "expected_target_update": reg["expected_target_update_operation"],
                "negative_control": reg["control_status"] == "NEGATIVE_MEMORY_CONTROL",
                "close_after_setup": True,
                "reopen_for_target_session": True,
                "initial_state_copy_per_mode": list(ALL_MODES),
                "cross_scenario_state": False,
                "cross_mode_state": False,
                "assistant_recommendation_as_learner_fact": False,
                "system_plan_items_basis": "VERIFIED_SYSTEM_EVENT",
            }
        )
    write_jsonl(HERE / "c4_real_memory_preconditioning_manifest_v1.jsonl", rows)
    return rows


def build_cohorts() -> dict[str, Any]:
    identity = load_json(IDENTITY)
    planning = [
        row["scenario_id"]
        for row in identity["rows"]
        if "recommendation_planning" in row["required_capabilities"]
    ]
    references = {row["scenario_id"]: row for row in load_jsonl(REFERENCE)}
    require(all(references[sid]["review_status"] in {"approved", "revised"} for sid in RAG_COHORT),
            "RAG cohort has unreviewed reference status")
    cohort = {
        "schema_version": "c4-real-final-analysis-cohorts-v1",
        "status": "FROZEN_BEFORE_P3_ROUTES_RESPONSES_AND_SCORES",
        "registry_record_count": 558,
        "primary_six_mode_dataset": {"scenario_count": 62, "scenario_ids": [f"U{i:03d}" for i in range(1, 63)], "modes": list(PRIMARY_MODES)},
        "authentic_subset": {"identity": "C4_REAL_ORIGINAL_25_AUTHENTIC_SUBSET_V1", "scenario_count": 25, "scenario_ids": [f"U{i:03d}" for i in range(1, 26)]},
        "long_term_memory_primary_effect_subset": {"scenario_count": 9, "scenario_ids": list(PERSISTENT_CASES), "source_case_ids": list(PERSISTENT_CASES.values())},
        "rag_effect_subset": {"scenario_count": len(RAG_COHORT), "scenario_ids": list(RAG_COHORT), "includes_typed_no_result_controls": ["U045", "U046"], "selection_rule": "approved_or_revised_course_reference_population_with_valid_selected_R0_support_or_R0_NO_RESULT_control"},
        "planning_effect_subset": {"scenario_count": len(planning), "scenario_ids": planning, "selection_rule": "frozen_required_capabilities_contains_recommendation_planning"},
        "remove_one_comparisons": {
            "C5_MINUS_RAG_vs_C5_FULL_C4": "rag_effect_subset",
            "C5_MINUS_MEMORY_vs_C5_FULL_C4": "long_term_memory_primary_effect_subset",
            "C5_MINUS_PLANNING_vs_C5_FULL_C4": "planning_effect_subset",
        },
        "post_response_denominator_changes_permitted": False,
    }
    write_json(HERE / "c4_real_final_analysis_cohorts_v1.json", cohort)
    return cohort


def build_generation_and_judge() -> None:
    generation_schema = {
        "$schema": "https://json-schema.org/draft/2020-12/schema",
        "type": "object",
        "additionalProperties": False,
        "required": ["answer_text"],
        "properties": {"answer_text": {"type": "string", "minLength": 1}},
    }
    write_json(HERE / "c4_real_generation_schema_v1.json", generation_schema)
    generation_prompt = (
        "You are a student-facing educational assistant. Answer the current request in English.\n"
        "Use only the supplied request context, selected evidence, and optional planning support.\n"
        "Preserve source boundaries: activity traces do not prove learning quality, metadata does not prove document content, and absent evidence must not be invented.\n"
        "Treat learner information as factual only when it is explicitly present in the supplied context.\n"
        "When evidence is missing, ambiguous, or insufficient, state the bounded limitation and ask only the focused clarification needed.\n"
        "Return strict JSON matching the supplied schema and no text outside it.\n"
    )
    (HERE / "c4_real_generation_prompt_frozen_v1.txt").write_text(generation_prompt, encoding="utf-8")
    write_json(
        HERE / "c4_real_generation_configuration_frozen_v1.json",
        {
            "schema_version": "c4-real-generation-configuration-v1",
            "status": "FROZEN_UNEXECUTED_NO_CALL_AUTHORIZED_IN_I0",
            "model": "gpt-4o-mini-2024-07-18",
            "endpoint": "OpenAI Chat Completions",
            "temperature": 0,
            "max_output_tokens": 512,
            "automatic_sdk_retries": 0,
            "manual_retry": "ONE_IDENTICAL_RETRY_ONLY_INVALID_STRICT_STRUCTURED_OUTPUT",
            "streaming": False,
            "tools": "NONE",
            "output_language": "English",
            "prompt_sha256": sha_file(HERE / "c4_real_generation_prompt_frozen_v1.txt"),
            "schema_sha256": sha_file(HERE / "c4_real_generation_schema_v1.json"),
            "route_content_in_generation_input": False,
        },
    )
    shutil.copyfile(
        RQ3_PROTOCOL / "rq3_judge_response_schema_v1.json",
        HERE / "c4_real_judge_schema_v1.json",
    )
    write_json(
        HERE / "c4_real_judge_configuration_frozen_v1.json",
        {
            "schema_version": "c4-real-judge-configuration-v1",
            "status": "FROZEN_UNEXECUTED_NO_JUDGE_CALL_AUTHORIZED_IN_I0",
            "model": "gpt-4.1-2025-04-14",
            "endpoint": "OpenAI Chat Completions",
            "temperature": 0,
            "automatic_sdk_retries": 0,
            "judge_prompt_path": "evaluation/rq3_v2/rq3_0b4_evaluation_protocol/rq3_judge_prompt_frozen_v1.txt",
            "judge_prompt_sha256": sha_file(RQ3_PROTOCOL / "rq3_judge_prompt_frozen_v1.txt"),
            "provider_schema_path": "evaluation/rq3_real_c4/i0_integration/c4_real_judge_schema_v1.json",
            "provider_schema_sha256": sha_file(HERE / "c4_real_judge_schema_v1.json"),
            "rubric_sha256": sha_file(RQ3_PROTOCOL / "rq3_primary_eight_criterion_rubric_v1.json"),
            "statistical_contract_sha256": sha_file(RQ3_PROTOCOL / "rq3_statistical_analysis_contract_v1.json"),
            "primary_criteria": ["CLARITY", "PERSONALISATION", "ACTIONABILITY", "CONTEXT_AWARENESS", "MOTIVATION_AND_ENGAGEMENT", "RELIABILITY", "MULTI_PAGE_COHESIVENESS", "ERROR_HANDLING"],
            "scale": "1-5_OR_NA_BY_FROZEN_APPLICABILITY",
            "primary_outcome": "OVERALL_APPLICABLE_MEAN",
            "secondary_audits": ["EVIDENCE_FAITHFULNESS", "UNSUPPORTED_CLAIM_COUNT"],
            "paired_scenario_analysis": True,
            "bootstrap_replicates": 10000,
            "multiplicity": "HOLM_STEP_DOWN",
            "human_validation_protocol_preserved": True,
        },
    )


def zip_bytes(files: Mapping[str, bytes]) -> bytes:
    buffer = io.BytesIO()
    with ZipFile(buffer, "w", compression=ZIP_DEFLATED, compresslevel=9) as archive:
        for name in sorted(files):
            info = ZipInfo(name, date_time=(2026, 9, 1, 0, 0, 0))
            info.compress_type = ZIP_DEFLATED
            info.external_attr = ((stat.S_IFREG | 0o644) & 0xFFFF) << 16
            archive.writestr(info, files[name])
    return buffer.getvalue()


def build_route_packages(route_rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    ready = [row for row in route_rows if row["status"] == "READY_FOR_P3_ROUTE_EXECUTION"]
    request_bytes = b"".join(canonical_json_bytes(row) + b"\n" for row in ready)
    runner_bytes = (HERE / "route_execution_runner.py").read_bytes()
    summaries = []
    for label, spec in PACKAGE_SPECS.items():
        require(sha_file(spec["prompt"]) == spec["prompt_sha256"], f"{label} prompt mismatch")
        require(sha_file(spec["schema"]) == spec["schema_sha256"], f"{label} schema mismatch")
        package = load_json(spec["package"])
        examples = package["few_shot_examples"]
        if label == "B4_PLANNING":
            observed_example_hash = package["hashes"]["example_set_sha256"]
        else:
            observed_example_hash = package["hashes"]["specialist_example_set_sha256"]
        require(observed_example_hash == spec["example_sha256"], f"{label} example-set mismatch")
        require(canonical_sha(examples) == spec["example_sha256"], f"{label} example bytes mismatch")
        plan = {
            "schema_version": "c4-real-p3-route-execution-plan-v1",
            "status": "UNEXECUTED_REQUIRES_NEW_DIRECT_AUTHORIZATION",
            "package_id": spec["package_id"],
            "route_component": label,
            "p3_consumption": spec["p3_consumption"],
            "model": "gpt-4o-mini-2024-07-18",
            "endpoint": "OpenAI Chat Completions",
            "temperature": 0,
            "max_output_tokens": 64,
            "automatic_sdk_retries": 0,
            "manual_retry": "ONE_IDENTICAL_RETRY_ONLY_INVALID_STRICT_STRUCTURED_OUTPUT",
            "streaming": False,
            "tools": "NONE",
            "logical_call_count": len(ready),
            "maximum_physical_attempt_count": len(ready) * 2,
            "response_schema_name": spec["response_schema_name"],
            "semantic_input_fields": ["current_query", "current_page", "dashboard_context", "visible_conversation_history"],
            "prompt_sha256": spec["prompt_sha256"],
            "schema_sha256": spec["schema_sha256"],
            "final_example_set_sha256": spec["example_sha256"],
            "requests_sha256": hashlib.sha256(request_bytes).hexdigest(),
            "attempt_journal": "DURABLE_APPEND_FSYNC_BEFORE_EACH_PROVIDER_CALL",
            "terminal_journal": "DURABLE_APPEND_FSYNC_AFTER_TERMINAL_RESULT",
            "resume_safe": True,
        }
        files = {
            "ATTEMPT_JOURNAL.jsonl": b"",
            "EXECUTION_PLAN.json": json.dumps(plan, ensure_ascii=False, indent=2, sort_keys=True).encode() + b"\n",
            "README.md": (
                f"# {spec['package_id']}\n\nUNEXECUTED. I0 authorizes zero provider calls. "
                "A later package-specific authorization record, --execute, RQ3_REAL_P3_EXECUTION_AUTHORIZED=YES, "
                "and OPENAI_API_KEY are all required. Scenario requests contain only the frozen four-field semantic input; "
                "demonstration outputs are frozen DEV few-shot examples, not evaluation expectations.\n"
            ).encode(),
            "TERMINAL_JOURNAL.jsonl": b"",
            "execute_route_package.py": runner_bytes,
            "few_shot_examples.json": json.dumps({"few_shot_examples": examples}, ensure_ascii=False, indent=2, sort_keys=True).encode() + b"\n",
            "prompt.txt": spec["prompt"].read_bytes(),
            "requests.jsonl": request_bytes,
            "schema.json": spec["schema"].read_bytes(),
        }
        manifest = {
            "schema_version": "c4-real-route-package-manifest-v1",
            "package_id": spec["package_id"],
            "strict_allowlist": sorted([*files, "PACKAGE_MANIFEST.json"]),
            "member_sha256_excluding_self": {name: hashlib.sha256(data).hexdigest() for name, data in sorted(files.items())},
            "contains_gold": False,
            "contains_evaluation_expected_capabilities": False,
            "contains_reference_evidence": False,
            "contains_mode_labels": False,
            "contains_credentials": False,
            "provider_calls_in_i0": 0,
        }
        files["PACKAGE_MANIFEST.json"] = json.dumps(manifest, ensure_ascii=False, indent=2, sort_keys=True).encode() + b"\n"
        target = DOWNLOADS / spec["filename"]
        target.write_bytes(zip_bytes(files))
        summaries.append({
            "route_component": label,
            "package_id": spec["package_id"],
            "path": str(target),
            "sha256": sha_file(target),
            "logical_call_count": len(ready),
            "maximum_physical_attempt_count": len(ready) * 2,
        })
    return summaries


def source_manifest(package_summaries: list[dict[str, Any]]) -> None:
    sources = [
        UNIFIED, ORIGINAL_25, ORIGINAL_DIALOGUE, REFERENCE, REPLAY, IDENTITY,
        MODE_REGISTRY, MEMORY_REGISTRY,
        ROOT / "utils/evidence_synthesiser.py",
        ROOT / "evaluation/assistant_modes.py",
        ROOT / "utils/c4_real_contracts.py",
        ROOT / "utils/c4_real_service.py",
        ROOT / "utils/c4_real_adapters.py",
        ROOT / "utils/c4_real_factory.py",
        HERE / "build_i0_artifacts.py",
        HERE / "route_execution_runner.py",
        HERE / "assemble_frozen_routes.py",
        HERE / "run_real_system_dry_run.py",
        HERE / "validate_memory_preconditioning.py",
        HERE / "build_review_zip.py",
        ROOT / "utils/c4_rag/provider.py",
        HERE.parent / "track_r_rag/selected_c4_rag_frozen_v1.json",
        ROOT / "utils/c4_memory/c4_memory_provider.py",
        ROOT / "utils/c4_memory/c4_memory_writer.py",
        RQ2 / "final_router_selection/RQ2_FINAL_ROUTER_FOR_RQ3.json",
        RQ3_PROTOCOL / "rq3_primary_eight_criterion_rubric_v1.json",
        RQ3_PROTOCOL / "rq3_statistical_analysis_contract_v1.json",
    ]
    write_json(
        HERE / "c4_real_integration_source_manifest_v1.json",
        {
            "schema_version": "c4-real-integration-source-manifest-v1",
            "status": "FROZEN_I0_ZERO_PROVIDER_EXECUTION",
            "source_files": [
                {"path": str(path), "sha256": sha_file(path), "byte_count": path.stat().st_size}
                for path in sources
            ],
            "track_identities": {
                "dataset": "C4_REAL_PRIMARY_UNIFIED_DATASET_V1",
                "authentic_subset": "C4_REAL_ORIGINAL_25_AUTHENTIC_SUBSET_V1",
                "course_rag": "C4_RAG_R0_LEXICAL",
                "course_corpus_chunk_count": 624,
                "course_corpus_sha256": "daaba43aebeda730db2bd7aef4583729610242a1af44060615c3f4c235e67ede",
                "memory": "C4_LEARNER_MEMORY_V1",
                "router": "R2V2-P3_RAG_MEMORY_SPECIALISTS",
            },
            "route_packages": package_summaries,
            "actual_execution_counters": {"provider_calls": 0, "p3_calls": 0, "generation_calls": 0, "judge_calls": 0, "streamlit_launches": 0},
        },
    )


def build() -> dict[str, Any]:
    source_verification()
    inputs = semantic_inputs()
    decisions, route_rows = build_gate_and_route_manifests(inputs)
    memory = build_memory_manifest(inputs)
    cohorts = build_cohorts()
    build_generation_and_judge()
    packages = build_route_packages(route_rows)
    answer_count = sum(row["dialogue_action"] == "ANSWER" for row in decisions)
    clarify_count = len(decisions) - answer_count
    write_json(
        HERE / "c4_real_route_execution_plan_v1.json",
        {
            "schema_version": "c4-real-route-execution-plan-v1",
            "status": "READY_BUT_UNEXECUTED_REQUIRES_NEW_DIRECT_AUTHORIZATION",
            "clarification_counts": {"ANSWER": answer_count, "CLARIFY": clarify_count},
            "logical_call_population": answer_count,
            "per_package_physical_attempt_ceiling": answer_count * 2,
            "identical_population_across_packages": True,
            "post_execution_local_merger": "assemble_frozen_routes.py",
            "post_execution_merger_provider_calls": 0,
            "packages": packages,
            "p3_execution_calls_in_i0": 0,
        },
    )
    source_manifest(packages)
    result = {
        "scenario_count": len(inputs),
        "answer_count": answer_count,
        "clarify_count": clarify_count,
        "memory_case_count": len(memory),
        "rag_cohort_count": cohorts["rag_effect_subset"]["scenario_count"],
        "planning_cohort_count": cohorts["planning_effect_subset"]["scenario_count"],
        "packages": packages,
        "provider_calls": 0,
    }
    write_json(HERE / "c4_real_i0_build_report_v1.json", result)
    return result


def main() -> int:
    print(json.dumps(build(), ensure_ascii=False, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
