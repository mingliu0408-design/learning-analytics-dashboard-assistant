"""Build the Stage 4N registry and unexecuted TEST manifests.

This module performs source/input verification and serialization only.  It
does not import a router runtime, contact a provider, create predictions, or
open TEST Gold.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
from pathlib import Path
import subprocess
from typing import Any, Iterable, Mapping, Sequence

from .constants import (
    B4_EXAMPLE_SET_SHA256,
    B4_MODEL,
    B4_PROMPT_SHA256,
    B4_SCHEMA_SHA256,
    C0_ROOT,
    C0_SOURCE_HEAD,
    DETERMINISTIC_METHOD_IDS,
    EXPECTED_SOURCE_HASHES,
    EXPECTED_TEST_INPUT_HASHES,
    EXTERNAL_SOURCE_HASHES,
    FORBIDDEN_TEST_FIELD_NAMES,
    INTEGRATION_DIR,
    MEMORY_EXAMPLE_SET_SHA256,
    MEMORY_PROMPT_SHA256,
    MEMORY_SCHEMA_SHA256,
    METHOD_IDS,
    MPNET_REVISION,
    PRIMARY_FEATURE_PROFILE,
    PRIMARY_FIELDS,
    PROVIDER_STREAMS,
    RAG_EXAMPLE_SET_SHA256,
    RAG_PROMPT_SHA256,
    RAG_SCHEMA_SHA256,
    READY_STATUS,
    REPORTING_TIERS,
    REPOSITORY_ROOT,
    SOURCE_STAGE_HEAD,
    TEST_ESCROW_ZIP,
    TEST_ESCROW_ZIP_SHA256,
    TEST_INPUT_DIR,
    TEST_INPUT_FIELDS,
    TEST_INPUT_STATUS,
    TEST_STATUS,
)


class Stage4NBuildError(RuntimeError):
    """Raised on any frozen-source, input, or serialization drift."""


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def sha256_text(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def canonical_sha256(value: Any) -> str:
    encoded = json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def read_json(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise Stage4NBuildError(f"cannot read JSON object: {path}") from exc
    if not isinstance(value, dict):
        raise Stage4NBuildError(f"JSON root is not an object: {path}")
    return value


def write_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(value, ensure_ascii=False, sort_keys=True, indent=2) + "\n",
        encoding="utf-8",
    )


def write_jsonl(path: Path, rows: Iterable[Mapping[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    lines = [
        json.dumps(row, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
        for row in rows
    ]
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def _git(*args: str, cwd: Path = REPOSITORY_ROOT) -> str:
    try:
        result = subprocess.run(
            ["git", *args],
            cwd=cwd,
            check=True,
            capture_output=True,
            text=True,
        )
    except subprocess.CalledProcessError as exc:
        raise Stage4NBuildError(f"git verification failed: {' '.join(args)}") from exc
    return result.stdout.strip()


def verify_frozen_sources() -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    _git("cat-file", "-e", f"{SOURCE_STAGE_HEAD}^{{commit}}")
    source_rows: list[dict[str, Any]] = []
    for relative, expected in sorted(EXPECTED_SOURCE_HASHES.items()):
        path = REPOSITORY_ROOT / relative
        if not path.is_file():
            raise Stage4NBuildError(f"frozen Stage-4 source is missing: {relative}")
        observed = sha256_file(path)
        if observed != expected:
            raise Stage4NBuildError(
                f"frozen Stage-4 source hash mismatch: {relative}: {observed}"
            )
        source_rows.append(
            {
                "path": relative,
                "sha256": observed,
                "size_bytes": path.stat().st_size,
                "source_commit": SOURCE_STAGE_HEAD,
                "verification_status": "PASS_EXACT_RAW_BYTES",
            }
        )

    if _git("rev-parse", "HEAD", cwd=C0_ROOT) != C0_SOURCE_HEAD:
        raise Stage4NBuildError("frozen C0 checkout HEAD differs")
    if _git("status", "--short", cwd=C0_ROOT):
        raise Stage4NBuildError("frozen C0 checkout is not clean")
    external_rows: list[dict[str, Any]] = []
    for name, expected in sorted(EXTERNAL_SOURCE_HASHES.items()):
        path = Path(name)
        if not path.is_file():
            raise Stage4NBuildError(f"external frozen source is missing: {path}")
        observed = sha256_file(path)
        if observed != expected:
            raise Stage4NBuildError(f"external frozen source hash mismatch: {path}")
        external_rows.append(
            {
                "path": str(path),
                "sha256": observed,
                "size_bytes": path.stat().st_size,
                "verification_status": "PASS_EXACT_RAW_BYTES",
            }
        )
    return source_rows, external_rows


def verify_test_inputs() -> list[dict[str, Any]]:
    if not TEST_ESCROW_ZIP.is_file():
        raise Stage4NBuildError("authorized TEST escrow ZIP is missing")
    if sha256_file(TEST_ESCROW_ZIP) != TEST_ESCROW_ZIP_SHA256:
        raise Stage4NBuildError("authorized TEST escrow ZIP hash differs")
    for name, expected in EXPECTED_TEST_INPUT_HASHES.items():
        path = TEST_INPUT_DIR / name
        if not path.is_file() or sha256_file(path) != expected:
            raise Stage4NBuildError(f"allowed extracted TEST member differs: {name}")

    csv_path = TEST_INPUT_DIR / "test_inputs_frozen_v1.csv"
    with csv_path.open(newline="", encoding="utf-8-sig") as handle:
        reader = csv.DictReader(handle)
        if tuple(reader.fieldnames or ()) != TEST_INPUT_FIELDS:
            raise Stage4NBuildError("TEST CSV fields are not the exact allowed fields")
        csv_rows = [dict(row) for row in reader]

    jsonl_path = TEST_INPUT_DIR / "test_inputs_frozen_v1.jsonl"
    jsonl_rows: list[dict[str, Any]] = []
    for line_number, line in enumerate(
        jsonl_path.read_text(encoding="utf-8").splitlines(), start=1
    ):
        if not line:
            continue
        try:
            row = json.loads(line)
        except json.JSONDecodeError as exc:
            raise Stage4NBuildError(f"invalid TEST JSONL at line {line_number}") from exc
        if not isinstance(row, dict) or tuple(row.keys()) != TEST_INPUT_FIELDS:
            raise Stage4NBuildError("TEST JSONL fields are not the exact allowed fields")
        jsonl_rows.append(row)

    if len(csv_rows) != 36 or len(jsonl_rows) != 36:
        raise Stage4NBuildError("TEST input population is not exactly 36")

    def normalize(row: Mapping[str, Any]) -> dict[str, Any]:
        if set(row) != set(TEST_INPUT_FIELDS):
            raise Stage4NBuildError("TEST input contains an extra or missing field")
        history = row["visible_conversation_history"]
        if isinstance(history, str):
            try:
                history = json.loads(history)
            except json.JSONDecodeError as exc:
                raise Stage4NBuildError("visible history is invalid JSON") from exc
        if not isinstance(history, list):
            raise Stage4NBuildError("visible history must decode to a list")
        normalized: dict[str, Any] = {
            "annotation_case_id": str(row["annotation_case_id"]),
            "current_query": row["current_query"],
            "current_page": row["current_page"],
            "dashboard_context": row["dashboard_context"],
            "visible_conversation_history": history,
        }
        if not normalized["annotation_case_id"]:
            raise Stage4NBuildError("TEST annotation ID is empty")
        for field in ("current_query", "current_page", "dashboard_context"):
            if not isinstance(normalized[field], str):
                raise Stage4NBuildError(f"TEST field is not text: {field}")
        return normalized

    normalized_csv = [normalize(row) for row in csv_rows]
    normalized_jsonl = [normalize(row) for row in jsonl_rows]
    if normalized_csv != normalized_jsonl:
        raise Stage4NBuildError("TEST CSV/JSONL semantic rows differ")
    ids = [row["annotation_case_id"] for row in normalized_csv]
    if len(set(ids)) != 36:
        raise Stage4NBuildError("TEST annotation IDs are not unique")
    serialized = [
        json.dumps(row, ensure_ascii=False, sort_keys=True) for row in normalized_csv
    ]
    if len(set(serialized)) != 36:
        raise Stage4NBuildError("TEST input rows are not unique")
    forbidden = set(TEST_INPUT_FIELDS).intersection(FORBIDDEN_TEST_FIELD_NAMES)
    if forbidden:
        raise Stage4NBuildError(f"TEST input schema contains forbidden fields: {forbidden}")
    return normalized_csv


def _assert_equal(value: Any, expected: Any, label: str) -> None:
    if value != expected:
        raise Stage4NBuildError(f"frozen identity mismatch for {label}")


def verify_embedded_identities() -> dict[str, Any]:
    stage4 = REPOSITORY_ROOT / "evaluation/capability_routing_rq2_v2_stage4"
    stage1 = REPOSITORY_ROOT / "evaluation/capability_routing_rq2_v2_stage1"
    cg = read_json(stage4 / "track_g_b0_b1/clarification_gate_frozen_v1.json")
    _assert_equal(cg.get("selected_config_id"), "R2V2-CG1-C01_REFERENCE_MULTI_TARGET_UNSELECTED", "CG1 config ID")
    _assert_equal(cg.get("selected_config_sha256"), "e988d54231e392a655b3c542b14e55a6f899ca0f6bb555473f9b2cbec3ea40e3", "CG1 config hash")
    _assert_equal(cg.get("clarification_code_sha256"), "ef532e656da3de775a6f33f8cee5defab8e63e2571066b517a115de1234615eb", "CG1 code hash")

    b0 = read_json(stage4 / "track_g_b0_b1/b0_frozen_config_v1.json")
    _assert_equal(b0.get("b0_ruleset_sha256"), "84fdd1413958199106c10c4105df248e9ace7075ca6988e50c6bcdc253146f53", "B0 ruleset hash")
    _assert_equal(b0.get("b0_code_sha256"), "834a457cf996039a4edae4422240f25047af203a07f35d3d8036aab5f9d28c27", "B0 code hash")
    _assert_equal(b0.get("primary_feature_profile"), PRIMARY_FEATURE_PROFILE, "B0 feature profile")

    c0 = read_json(stage4 / "track_g_b0_b1/c0_identity_frozen_v1.json")
    b1 = read_json(stage4 / "track_g_b0_b1/b1_mapping_frozen_v1.json")
    _assert_equal(c0.get("router_id"), "C0_COSINE", "B1 C0 router")
    _assert_equal(c0.get("source_repository_head"), C0_SOURCE_HEAD, "B1 C0 source HEAD")
    _assert_equal(c0.get("intent_label_count"), 16, "B1 intent count")
    _assert_equal(len(c0.get("intent_label_universe") or []), 16, "B1 label universe")
    _assert_equal(b1.get("intent_universe_count"), 16, "B1 mapping universe")
    _assert_equal(b1.get("mapping_id"), "R2V2-B1-C0-TO-CAPABILITY-DEV-V1", "B1 mapping ID")
    _assert_equal(b1.get("mapping_status"), "FROZEN_DEV_DERIVED_B1_MAPPING", "B1 mapping status")
    _assert_equal(len(b1.get("mappings") or []), 16, "B1 mapping rows")

    b2_path = stage4 / "track_h_b2_b3/b2_frozen_model_v1.json"
    b3_path = stage4 / "track_h_b2_b3/b3_frozen_model_v1.json"
    b2 = read_json(b2_path)
    b3 = read_json(b3_path)
    _assert_equal(b2.get("model_id"), "R2V2-B2_PROTOTYPE", "B2 model ID")
    _assert_equal(b3.get("model_id"), "R2V2-B3_OVR", "B3 model ID")
    _assert_equal(b2.get("encoder_identity", {}).get("revision"), MPNET_REVISION, "B2 MPNet revision")
    _assert_equal(b3.get("encoder_identity", {}).get("revision"), MPNET_REVISION, "B3 MPNet revision")
    _assert_equal(set(b2.get("prototypes") or {}), {"RAG", "Memory", "Planning"}, "B2 prototypes")
    _assert_equal(set(b3.get("coefficients") or {}), {"RAG", "Memory", "Planning"}, "B3 coefficients")
    _assert_equal(b3.get("configuration", {}).get("config_id"), "B3_C_10p0_CW_NONE", "B3 configuration")

    b4 = read_json(stage4 / "track_i_b4/b4_final_frozen_configuration_v2.json")
    _assert_equal(b4.get("model_snapshot"), B4_MODEL, "B4 model snapshot")
    _assert_equal(b4.get("prompt_sha256"), B4_PROMPT_SHA256, "B4 prompt hash")
    _assert_equal(b4.get("response_schema_v2_sha256"), B4_SCHEMA_SHA256, "B4 schema hash")
    _assert_equal(b4.get("full_dev_examples", {}).get("example_set_sha256"), B4_EXAMPLE_SET_SHA256, "B4 example-set hash")
    _assert_equal(len(b4.get("full_dev_examples", {}).get("example_ids") or []), 8, "B4 example count")

    p1 = read_json(stage4 / "track_j_p1_protocol/p1_final_policy_frozen_v1.json")
    _assert_equal(p1.get("final_policy_id"), "P1-C08-NONUNANIMOUS", "P1 policy ID")
    _assert_equal(p1.get("P1_MODEL_STATUS"), "FROZEN_AFTER_DEV_SELECTION", "P1 status")
    _assert_equal(p1.get("frozen_input_hashes", {}).get("p1_candidate_grid_sha256"), EXPECTED_SOURCE_HASHES["evaluation/capability_routing_rq2_v2_stage4/track_j_p1_protocol/p1_candidate_policies_frozen_v1.json"], "P1 grid hash")
    _assert_equal(p1.get("frozen_input_hashes", {}).get("p1_selection_protocol_sha256"), EXPECTED_SOURCE_HASHES["evaluation/capability_routing_rq2_v2_stage4/track_j_p1_protocol/p1_nested_selection_protocol_v1.json"], "P1 selection hash")

    rag = read_json(stage4 / "track_k_rag_specialist_execution/rag_specialist_frozen_configuration_v1.json")
    memory = read_json(stage4 / "track_l_memory_specialist_execution/memory_specialist_frozen_configuration_v1.json")
    _assert_equal(rag.get("model_snapshot"), B4_MODEL, "RAG model snapshot")
    _assert_equal(rag.get("prompt_sha256"), RAG_PROMPT_SHA256, "RAG prompt hash")
    _assert_equal(rag.get("schema_sha256"), RAG_SCHEMA_SHA256, "RAG schema hash")
    _assert_equal(rag.get("final_full_dev_examples_and_order", {}).get("specialist_example_set_sha256"), RAG_EXAMPLE_SET_SHA256, "RAG example-set hash")
    _assert_equal(memory.get("model_snapshot"), B4_MODEL, "Memory model snapshot")
    _assert_equal(memory.get("prompt_sha256"), MEMORY_PROMPT_SHA256, "Memory prompt hash")
    _assert_equal(memory.get("schema_sha256"), MEMORY_SCHEMA_SHA256, "Memory schema hash")
    _assert_equal(memory.get("final_full_dev_examples_and_order", {}).get("specialist_example_set_sha256"), MEMORY_EXAMPLE_SET_SHA256, "Memory example-set hash")

    p2 = read_json(stage4 / "track_m_specialist_composition/p2_rag_specialist_composition_frozen_v1.json")
    p3 = read_json(stage4 / "track_m_specialist_composition/p3_rag_memory_specialists_frozen_v1.json")
    p4 = read_json(stage4 / "track_m_specialist_composition/p4_memory_specialist_composition_frozen_v1.json")
    _assert_equal(p2.get("composition_id"), "R2V2-P2_RAG_SPECIALIST_COMPOSITION", "P2 ID")
    _assert_equal(p3.get("composition_id"), "R2V2-P3_RAG_MEMORY_SPECIALISTS", "P3 ID")
    _assert_equal(p4.get("composition_id"), "R2V2-P4_MEMORY_SPECIALIST_COMPOSITION", "P4 ID")
    _assert_equal(p2.get("missing_or_invalid_component_behavior", {}).get("fallback_or_router_substitution_allowed"), False, "P2 missing-component behavior")
    _assert_equal(p3.get("missing_or_invalid_component_behavior", {}).get("imputation_allowed"), False, "P3 missing-component behavior")
    _assert_equal(p4.get("P4_STATUS"), "FROZEN_POST_DEV_EXPLORATORY_ABLATION_BEFORE_TEST", "P4 exploratory status")

    return {
        "clarification_gate": {
            "selected_configuration_id": cg["selected_config_id"],
            "selected_configuration_sha256": cg["selected_config_sha256"],
            "code_sha256": cg["clarification_code_sha256"],
        },
        "B0": {
            "ruleset_id": b0["ruleset_id"],
            "ruleset_sha256": b0["b0_ruleset_sha256"],
            "code_sha256": b0["b0_code_sha256"],
        },
        "B1": {
            "c0_router_id": c0["router_id"],
            "c0_source_head": c0["source_repository_head"],
            "intent_label_count": c0["intent_label_count"],
            "intent_label_universe": c0["intent_label_universe"],
            "final_mapping_id": b1["mapping_id"],
            "final_mapping_raw_file_sha256": EXPECTED_SOURCE_HASHES["evaluation/capability_routing_rq2_v2_stage4/track_g_b0_b1/b1_mapping_frozen_v1.json"],
        },
        "B2": {
            "model_id": b2["model_id"],
            "encoder_revision": MPNET_REVISION,
            "frozen_model_raw_file_sha256": sha256_file(b2_path),
            "thresholds": b2["thresholds"],
            "prototype_dimensions": {key: len(value["positive"]) for key, value in b2["prototypes"].items()},
        },
        "B3": {
            "model_id": b3["model_id"],
            "configuration": b3["configuration"],
            "frozen_model_raw_file_sha256": sha256_file(b3_path),
            "thresholds": b3["thresholds"],
            "coefficient_dimensions": {key: len(value) for key, value in b3["coefficients"].items()},
            "intercepts": b3["intercepts"],
        },
        "B4": {
            "model_snapshot": b4["model_snapshot"],
            "prompt_sha256": b4["prompt_sha256"],
            "schema_sha256": b4["response_schema_v2_sha256"],
            "example_ids_in_order": b4["full_dev_examples"]["example_ids"],
            "example_set_sha256": b4["full_dev_examples"]["example_set_sha256"],
        },
        "P1": {
            "policy_id": p1["final_policy_id"],
            "status": p1["P1_MODEL_STATUS"],
            "policy_grid_sha256": p1["frozen_input_hashes"]["p1_candidate_grid_sha256"],
            "selection_protocol_sha256": p1["frozen_input_hashes"]["p1_selection_protocol_sha256"],
        },
        "RAG_SPECIALIST": {
            "model_snapshot": rag["model_snapshot"],
            "prompt_sha256": rag["prompt_sha256"],
            "schema_sha256": rag["schema_sha256"],
            "example_ids_in_order": rag["final_full_dev_examples_and_order"]["example_ids_in_order"],
            "example_set_sha256": rag["final_full_dev_examples_and_order"]["specialist_example_set_sha256"],
        },
        "MEMORY_SPECIALIST": {
            "model_snapshot": memory["model_snapshot"],
            "prompt_sha256": memory["prompt_sha256"],
            "schema_sha256": memory["schema_sha256"],
            "example_ids_in_order": memory["final_full_dev_examples_and_order"]["example_ids"],
            "example_set_sha256": memory["final_full_dev_examples_and_order"]["specialist_example_set_sha256"],
        },
        "P2": {"composition_rule": p2["composition_rule"], "components": p2["components"], "missing_component_behavior": p2["missing_or_invalid_component_behavior"]},
        "P3": {"composition_rule": p3["composition_rule"], "components": p3["components"], "missing_component_behavior": p3["missing_or_invalid_component_behavior"]},
        "P4": {"composition_rule": p4["composition_rule"], "components": p4["components"], "missing_component_behavior": p4["missing_or_invalid_component_behavior"], "development_status": p4["method_development_status"]},
    }


METHOD_SOURCES: dict[str, tuple[str, ...]] = {
    "R2V2-D0_ALWAYS_ON": (
        "evaluation/capability_routing_rq2_v2_stage4/track_h_b2_b3/sanity_baseline_definitions_v1.json",
        "evaluation/capability_routing_rq2_v2_stage4/track_h_b2_b3/diagnostic_audit.py",
    ),
    "R2V2-D1_NEVER_ON": (
        "evaluation/capability_routing_rq2_v2_stage4/track_h_b2_b3/sanity_baseline_definitions_v1.json",
        "evaluation/capability_routing_rq2_v2_stage4/track_h_b2_b3/diagnostic_audit.py",
    ),
    "R2V2-CG1_CLARIFICATION_RULE": (
        "evaluation/capability_routing_rq2_v2_stage4/track_g_b0_b1/clarification_candidate_configs_v1.json",
        "evaluation/capability_routing_rq2_v2_stage4/track_g_b0_b1/clarification_gate.py",
        "evaluation/capability_routing_rq2_v2_stage4/track_g_b0_b1/clarification_gate_frozen_v1.json",
    ),
    "R2V2-B0_RULE": (
        "evaluation/capability_routing_rq2_v2_stage1/track_b_b0_b1/b0_rule_router.py",
        "evaluation/capability_routing_rq2_v2_stage1/track_b_b0_b1/config/b0_rules_v1.json",
        "evaluation/capability_routing_rq2_v2_stage4/track_g_b0_b1/b0_frozen_config_v1.json",
    ),
    "R2V2-B1_LEGACY_INTENT": (
        "evaluation/capability_routing_rq2_v2_stage1/track_b_b0_b1/b1_legacy_intent_adapter.py",
        "evaluation/capability_routing_rq2_v2_stage4/track_g_b0_b1/c0_identity_frozen_v1.json",
        "evaluation/capability_routing_rq2_v2_stage4/track_g_b0_b1/b1_mapping_frozen_v1.json",
    ),
    "R2V2-B2_PROTOTYPE": (
        "evaluation/capability_routing_rq2_v2_stage1/track_c_b2_b3/canonical_text.py",
        "evaluation/capability_routing_rq2_v2_stage1/track_c_b2_b3/embeddings.py",
        "evaluation/capability_routing_rq2_v2_stage1/track_c_b2_b3/prototype_router.py",
        "evaluation/capability_routing_rq2_v2_stage4/track_h_b2_b3/dev_embedding_identity_v1.json",
        "evaluation/capability_routing_rq2_v2_stage4/track_h_b2_b3/b2_frozen_model_v1.json",
        "evaluation/capability_routing_rq2_v2_stage4/track_h_b2_b3/track_h.py",
    ),
    "R2V2-B3_OVR": (
        "evaluation/capability_routing_rq2_v2_stage1/track_c_b2_b3/canonical_text.py",
        "evaluation/capability_routing_rq2_v2_stage1/track_c_b2_b3/embeddings.py",
        "evaluation/capability_routing_rq2_v2_stage1/track_c_b2_b3/ovr_router.py",
        "evaluation/capability_routing_rq2_v2_stage1/track_c_b2_b3/router_common.py",
        "evaluation/capability_routing_rq2_v2_stage4/track_h_b2_b3/dev_embedding_identity_v1.json",
        "evaluation/capability_routing_rq2_v2_stage4/track_h_b2_b3/b3_frozen_model_v1.json",
        "evaluation/capability_routing_rq2_v2_stage4/track_h_b2_b3/track_h.py",
    ),
    "R2V2-B4_JOINT_LLM": (
        "evaluation/capability_routing_rq2_v2_stage4/track_i_b4/b4_prompt_template_frozen_v1.txt",
        "evaluation/capability_routing_rq2_v2_stage4/track_i_b4/b4_response_schema_v2.json",
        "evaluation/capability_routing_rq2_v2_stage4/track_i_b4/b4_final_full_dev_prompt_package_v1.json",
        "evaluation/capability_routing_rq2_v2_stage4/track_i_b4/b4_final_frozen_configuration_v2.json",
        "evaluation/capability_routing_rq2_v2_stage4/track_i_b4/b4_execution_runtime_v1.json",
        "evaluation/capability_routing_rq2_v2_stage4/track_i_b4/execute_b4_dev_r1.py",
    ),
    "R2V2-P1_HYBRID": (
        "evaluation/capability_routing_rq2_v2_stage4/track_j_p1_protocol/p1_candidate_policies_frozen_v1.json",
        "evaluation/capability_routing_rq2_v2_stage4/track_j_p1_protocol/p1_nested_selection_protocol_v1.json",
        "evaluation/capability_routing_rq2_v2_stage4/track_j_p1_protocol/p1_final_policy_frozen_v1.json",
        "evaluation/capability_routing_rq2_v2_stage4/track_j_p1_protocol/p1_protocol.py",
    ),
    "R2V2-RAG_SPECIALIST": (
        "evaluation/capability_routing_rq2_v2_stage4/track_k0_specialists/rag_specialist_prompt_frozen_v1.txt",
        "evaluation/capability_routing_rq2_v2_stage4/track_k0_specialists/rag_specialist_schema_v1.json",
        "evaluation/capability_routing_rq2_v2_stage4/track_k0_specialists/rag_specialist_final_full_dev_prompt_package_v1.json",
        "evaluation/capability_routing_rq2_v2_stage4/track_k_rag_specialist_execution/rag_specialist_frozen_configuration_v1.json",
        "evaluation/capability_routing_rq2_v2_stage4/track_k_rag_specialist_execution/rag_specialist_protocol.py",
        "evaluation/capability_routing_rq2_v2_stage4/track_k_rag_specialist_execution/execute_rag_specialist_dev.py",
    ),
    "R2V2-MEMORY_SPECIALIST": (
        "evaluation/capability_routing_rq2_v2_stage4/track_k0_specialists/memory_specialist_prompt_frozen_v1.txt",
        "evaluation/capability_routing_rq2_v2_stage4/track_k0_specialists/memory_specialist_schema_v1.json",
        "evaluation/capability_routing_rq2_v2_stage4/track_k0_specialists/memory_specialist_final_full_dev_prompt_package_v1.json",
        "evaluation/capability_routing_rq2_v2_stage4/track_l_memory_specialist_execution/memory_specialist_frozen_configuration_v1.json",
        "evaluation/capability_routing_rq2_v2_stage4/track_l_memory_specialist_execution/memory_specialist_common.py",
        "evaluation/capability_routing_rq2_v2_stage4/track_l_memory_specialist_execution/execute_memory_specialist_dev.py",
    ),
    "R2V2-P2_RAG_SPECIALIST_COMPOSITION": (
        "evaluation/capability_routing_rq2_v2_stage4/track_k0_specialists/p2_rag_specialist_composition_contract_v1.json",
        "evaluation/capability_routing_rq2_v2_stage4/track_m_specialist_composition/p2_rag_specialist_composition_frozen_v1.json",
        "evaluation/capability_routing_rq2_v2_stage4/track_m_specialist_composition/run_stage4m.py",
    ),
    "R2V2-P3_RAG_MEMORY_SPECIALISTS": (
        "evaluation/capability_routing_rq2_v2_stage4/track_k0_specialists/p3_capability_specialists_composition_contract_v1.json",
        "evaluation/capability_routing_rq2_v2_stage4/track_m_specialist_composition/p3_rag_memory_specialists_frozen_v1.json",
        "evaluation/capability_routing_rq2_v2_stage4/track_m_specialist_composition/run_stage4m.py",
    ),
    "R2V2-P4_MEMORY_SPECIALIST_COMPOSITION": (
        "evaluation/capability_routing_rq2_v2_stage4/track_m_specialist_composition/p4_memory_specialist_composition_frozen_v1.json",
        "evaluation/capability_routing_rq2_v2_stage4/track_m_specialist_composition/P4_POST_DEV_EXTENSION_DISCLOSURE.md",
        "evaluation/capability_routing_rq2_v2_stage4/track_m_specialist_composition/run_stage4m.py",
    ),
}


def build_method_registry() -> dict[str, Any]:
    attributes = {
        "R2V2-D0_ALWAYS_ON": ("DIAGNOSTIC_BASELINE_FROZEN_PRE_TEST", "DIAGNOSTIC_NOT_CONFIRMATORY", "CONSTANT_NO_INPUT", []),
        "R2V2-D1_NEVER_ON": ("DIAGNOSTIC_BASELINE_FROZEN_PRE_TEST", "DIAGNOSTIC_NOT_CONFIRMATORY", "CONSTANT_NO_INPUT", []),
        "R2V2-CG1_CLARIFICATION_RULE": ("FROZEN_AFTER_DEV_SELECTION", "SHARED_UPSTREAM_NOT_A_CORE_COMPARATOR", PRIMARY_FEATURE_PROFILE, []),
        "R2V2-B0_RULE": ("ORIGINAL_PRE_SPECIFIED_UNCHANGED_BASELINE", "CONFIRMATORY_ORIGINAL_MODEL", PRIMARY_FEATURE_PROFILE, []),
        "R2V2-B1_LEGACY_INTENT": ("FROZEN_DEV_DERIVED_MAPPING", "CONFIRMATORY_ORIGINAL_MODEL", "C0_CURRENT_QUERY_CURRENT_PAGE_SUBSET_OF_R2V2_PRIMARY_SEMANTIC_INPUT_V1", []),
        "R2V2-B2_PROTOTYPE": ("FROZEN_AFTER_DEV_CALIBRATION", "CONFIRMATORY_ORIGINAL_MODEL", PRIMARY_FEATURE_PROFILE, []),
        "R2V2-B3_OVR": ("FROZEN_AFTER_DEV_CALIBRATION", "CONFIRMATORY_ORIGINAL_MODEL", PRIMARY_FEATURE_PROFILE, []),
        "R2V2-B4_JOINT_LLM": ("FROZEN_AFTER_DEV_EXECUTION", "CONFIRMATORY_ORIGINAL_MODEL", PRIMARY_FEATURE_PROFILE, []),
        "R2V2-P1_HYBRID": ("FROZEN_AFTER_DEV_SELECTION", "CONFIRMATORY_ORIGINAL_MODEL", "COMPONENT_PREDICTIONS_ONLY_NO_ADDITIONAL_SEMANTIC_FEATURES", ["R2V2-B0_RULE", "R2V2-B2_PROTOTYPE", "R2V2-B3_OVR", "R2V2-B4_JOINT_LLM"]),
        "R2V2-P2_RAG_SPECIALIST_COMPOSITION": ("DEV_INFORMED_PREDECLARED_PRIMARY_SPECIALIST_FROZEN_BEFORE_TEST", "CONFIRMATORY_SPECIALIST_PRIMARY", "COMPONENT_PREDICTIONS_ONLY_NO_ADDITIONAL_SEMANTIC_FEATURES", ["R2V2-B4_JOINT_LLM", "R2V2-RAG_SPECIALIST"]),
        "R2V2-P3_RAG_MEMORY_SPECIALISTS": ("DEV_INFORMED_PREDECLARED_SECONDARY_SPECIALIST_FROZEN_BEFORE_TEST", "CONFIRMATORY_SPECIALIST_SECONDARY", "COMPONENT_PREDICTIONS_ONLY_NO_ADDITIONAL_SEMANTIC_FEATURES", ["R2V2-B4_JOINT_LLM", "R2V2-RAG_SPECIALIST", "R2V2-MEMORY_SPECIALIST"]),
        "R2V2-P4_MEMORY_SPECIALIST_COMPOSITION": ("POST_DEV_EXPLORATORY_ABLATION_FROZEN_BEFORE_TEST", "EXPLORATORY_FACTORIAL_ABLATION", "COMPONENT_PREDICTIONS_ONLY_NO_ADDITIONAL_SEMANTIC_FEATURES", ["R2V2-B4_JOINT_LLM", "R2V2-MEMORY_SPECIALIST"]),
        "R2V2-RAG_SPECIALIST": ("FROZEN_AFTER_DEV_EXECUTION", "COMPONENT_ANALYSIS_NOT_STANDALONE_REPORTING_TIER", PRIMARY_FEATURE_PROFILE, []),
        "R2V2-MEMORY_SPECIALIST": ("FROZEN_AFTER_DEV_EXECUTION", "COMPONENT_ANALYSIS_NOT_STANDALONE_REPORTING_TIER", PRIMARY_FEATURE_PROFILE, []),
    }
    tier_by_method = {
        method_id: tier for tier, method_ids in REPORTING_TIERS.items() for method_id in method_ids
    }
    methods: list[dict[str, Any]] = []
    for method_id in METHOD_IDS:
        status, role, feature_profile, components = attributes[method_id]
        reporting_tier = tier_by_method.get(method_id)
        if method_id == "R2V2-CG1_CLARIFICATION_RULE":
            method_tier = "SHARED_UPSTREAM_METHOD"
        elif method_id in {"R2V2-RAG_SPECIALIST", "R2V2-MEMORY_SPECIALIST"}:
            method_tier = "COMPONENT_METHOD"
        else:
            method_tier = reporting_tier
        source_files = [
            {"path": path, "sha256": EXPECTED_SOURCE_HASHES[path]}
            for path in METHOD_SOURCES[method_id]
        ]
        methods.append(
            {
                "method_id": method_id,
                "method_tier": method_tier,
                "reporting_tier": reporting_tier,
                "development_status": status,
                "confirmatory_exploratory_role": role,
                "exact_source_files": source_files,
                "feature_profile": feature_profile,
                "required_component_methods": components,
                "TEST_status": TEST_STATUS,
            }
        )
    return {
        "schema_version": "rq2-v2-stage4n-final-method-registry-v1",
        "registry_status": "FROZEN_BEFORE_TEST_EXECUTION",
        "source_stage_head": SOURCE_STAGE_HEAD,
        "method_count": len(methods),
        "method_ids_in_frozen_order": list(METHOD_IDS),
        "reporting_tiers": REPORTING_TIERS,
        "non_reporting_method_classes": {
            "SHARED_UPSTREAM_METHOD": ["R2V2-CG1_CLARIFICATION_RULE"],
            "COMPONENT_METHOD": ["R2V2-RAG_SPECIALIST", "R2V2-MEMORY_SPECIALIST"],
        },
        "winner_designated": False,
        "methods": methods,
    }


def _semantic(row: Mapping[str, Any]) -> dict[str, Any]:
    return {field: row[field] for field in PRIMARY_FIELDS}


def build_deterministic_manifest(rows: Sequence[Mapping[str, Any]]) -> list[dict[str, Any]]:
    records = []
    for index, row in enumerate(rows, start=1):
        records.append(
            {
                "logical_case_id": f"R2V2-TEST-{index:04d}",
                "annotation_case_id": row["annotation_case_id"],
                **_semantic(row),
                "execution_status": TEST_STATUS,
            }
        )
    return records


def _example_ids(stream: str, configuration: Mapping[str, Any]) -> list[str]:
    if stream == "B4":
        ids = configuration.get("full_dev_examples", {}).get("example_ids")
    elif stream == "RAG_SPECIALIST":
        ids = configuration.get("final_full_dev_examples_and_order", {}).get(
            "example_ids_in_order"
        )
    else:
        ids = configuration.get("final_full_dev_examples_and_order", {}).get(
            "example_ids"
        )
    if not isinstance(ids, list) or len(ids) != 8 or not all(isinstance(x, str) for x in ids):
        raise Stage4NBuildError(f"{stream} final example order is not exactly eight IDs")
    return ids


def _ordered_example_output(stream: str, output: Mapping[str, Any]) -> dict[str, bool]:
    if stream == "B4":
        keys = ("rag_required", "memory_required", "planning_required")
    elif stream == "RAG_SPECIALIST":
        keys = ("rag_required",)
    else:
        keys = ("memory_required",)
    if set(output) != set(keys) or any(not isinstance(output[key], bool) for key in keys):
        raise Stage4NBuildError(f"{stream} frozen DEV example output differs")
    return {key: output[key] for key in keys}


def build_provider_manifest(
    stream: str, rows: Sequence[Mapping[str, Any]]
) -> list[dict[str, Any]]:
    spec = PROVIDER_STREAMS[stream]
    prompt_package = read_json(REPOSITORY_ROOT / spec["prompt_package"])
    configuration = read_json(REPOSITORY_ROOT / spec["configuration"])
    schema = read_json(REPOSITORY_ROOT / spec["schema"])
    prompt = prompt_package.get("prompt_template")
    examples = prompt_package.get("few_shot_examples")
    if not isinstance(prompt, str) or sha256_text(prompt) != spec["prompt_sha256"]:
        raise Stage4NBuildError(f"{stream} prompt bytes differ")
    if not isinstance(examples, list) or len(examples) != 8:
        raise Stage4NBuildError(f"{stream} frozen prompt package lacks eight examples")
    example_ids = _example_ids(stream, configuration)
    if stream == "B4":
        embedded_hash = configuration["full_dev_examples"]["example_set_sha256"]
    else:
        embedded_hash = configuration["final_full_dev_examples_and_order"]["specialist_example_set_sha256"]
    _assert_equal(embedded_hash, spec["example_set_sha256"], f"{stream} example hash")
    if sha256_file(REPOSITORY_ROOT / spec["schema"]) != spec["schema_sha256"]:
        raise Stage4NBuildError(f"{stream} response schema raw bytes differ")

    base_messages: list[dict[str, str]] = [{"role": "system", "content": prompt}]
    for example in examples:
        if not isinstance(example, dict) or set(example) != {"input", "output"}:
            raise Stage4NBuildError(f"{stream} example structure differs")
        example_input = example["input"]
        if not isinstance(example_input, dict) or set(example_input) != set(PRIMARY_FIELDS):
            raise Stage4NBuildError(f"{stream} example input fields differ")
        ordered_input = {field: example_input[field] for field in PRIMARY_FIELDS}
        ordered_output = _ordered_example_output(stream, example["output"])
        base_messages.extend(
            [
                {"role": "user", "content": json.dumps(ordered_input, ensure_ascii=False, separators=(",", ":"))},
                {"role": "assistant", "content": json.dumps(ordered_output, ensure_ascii=False, separators=(",", ":"))},
            ]
        )

    records: list[dict[str, Any]] = []
    for index, row in enumerate(rows, start=1):
        semantic = _semantic(row)
        messages = [*base_messages, {"role": "user", "content": json.dumps(semantic, ensure_ascii=False, separators=(",", ":"))}]
        payload = {
            "model": B4_MODEL,
            "messages": messages,
            "temperature": 0,
            "max_tokens": spec["max_output_tokens"],
            "response_format": {
                "type": "json_schema",
                "json_schema": {
                    "name": spec["schema_name"],
                    "strict": True,
                    "schema": schema,
                },
            },
        }
        records.append(
            {
                "schema_version": "rq2-v2-stage4n-provider-test-execution-record-v1",
                "logical_case_id": f"R2V2-TEST-{index:04d}",
                "logical_call_id": f"{spec['logical_prefix']}-{index:04d}",
                "annotation_case_id": row["annotation_case_id"],
                **semantic,
                "method_id": spec["method_id"],
                "model_snapshot": B4_MODEL,
                "final_full_dev_prompt_package_path": spec["prompt_package"],
                "final_full_dev_example_ids_in_order": example_ids,
                "final_full_dev_example_set_sha256": spec["example_set_sha256"],
                "prompt_template_sha256": spec["prompt_sha256"],
                "response_schema_sha256": spec["schema_sha256"],
                "execution_controls": {
                    "temperature": 0,
                    "max_output_tokens": spec["max_output_tokens"],
                    "sdk_transport_retries": 0,
                    "manual_retry_max": 1,
                    "manual_retry_only_after": ["INVALID_JSON", "STRICT_SCHEMA_VALIDATION_FAILED"],
                    "prompt_change_on_retry": False,
                },
                "provider_request_payload": payload,
                "provider_request_payload_sha256": canonical_sha256(payload),
                "execution_status": TEST_STATUS,
            }
        )
    return records


def scoring_protocol() -> dict[str, Any]:
    core_metrics = [
        "Macro-F1", "Micro-F1", "per-label Precision/Recall/F1",
        "Exact Capability Set Match", "example-based F1", "Jaccard",
        "Hamming Loss", "under-routing", "over-routing",
        "mean capability count", "signature distribution", "family-both-correct",
        "family prediction consistency", "contrast consistency",
        "Gold-pattern contrast match", "page metrics", "Writer A/B metrics",
    ]
    end_to_end_metrics = [
        "dialogue-action Accuracy/F1", "full route-signature Exact Match",
        "family-both-correct", "family prediction consistency",
        "complete contrast consistency", "complete Gold-pattern match",
    ]
    return {
        "schema_version": "rq2-v2-stage4n-final-test-scoring-protocol-v1",
        "protocol_status": "FROZEN_BEFORE_TEST_PREDICTION_EXECUTION",
        "current_scoring_status": TEST_STATUS,
        "gold_access_gate": {
            "open_TEST_Gold_only_after_all_prediction_files_are_frozen": True,
            "execution_tasks_must_remain_blind_to_TEST_Gold": True,
            "gold_used_to_select_execution_population": False,
        },
        "core_capability_scoring": {
            "population": "GOLD_ANSWER_CASES_ONLY_DERIVED_AT_SCORING_TIME",
            "capabilities": ["RAG", "Memory", "Planning"],
            "metrics": core_metrics,
            "writer_metrics_rule": "USE_WRITER_IDENTITY_FROM_AUTHORIZED_GOLD_ONLY; IF_OMITTED_REPORT_UNAVAILABLE_AND_DO_NOT_INFER",
        },
        "end_to_end_scoring": {
            "population": "ALL_36_TEST_INPUTS",
            "dialogue_action_source": "FROZEN_CLARIFICATION_GATE",
            "predicted_CLARIFY": "CAPABILITY_OUTPUTS_NOT_APPLICABLE",
            "predicted_ANSWER": "USE_CORRESPONDING_FROZEN_CORE_PREDICTION",
            "metrics": end_to_end_metrics,
        },
        "call_and_cost_reporting": {
            "actual_experimental_provider_calls_reported": True,
            "counterfactual_deployment_calls_and_costs_reported_separately": True,
            "core_calls_on_cases_later_found_Gold_CLARIFY": "RESEARCH_AUDIT_CALLS_NOT_COUNTERFACTUAL_DEPLOYMENT_CALLS",
        },
        "method_status_immutability": "TEST_RESULTS_MUST_NOT_RECLASSIFY_DEVELOPMENT_STATUS",
        "winner_designation_at_stage4n": False,
    }


def comparison_hierarchy() -> dict[str, Any]:
    return {
        "schema_version": "rq2-v2-stage4n-comparison-hierarchy-v1",
        "status": "FROZEN_BEFORE_TEST",
        "original_rq2_model_comparison": ["R2V2-B0_RULE", "R2V2-B1_LEGACY_INTENT", "R2V2-B2_PROTOTYPE", "R2V2-B3_OVR", "R2V2-B4_JOINT_LLM", "R2V2-P1_HYBRID", "R2V2-D0_ALWAYS_ON", "R2V2-D1_NEVER_ON"],
        "specialist_primary_comparison": ["R2V2-P2_RAG_SPECIALIST_COMPOSITION", "R2V2-B4_JOINT_LLM"],
        "specialist_secondary_comparison": ["R2V2-P3_RAG_MEMORY_SPECIALISTS", "R2V2-B4_JOINT_LLM"],
        "exploratory_factorial_comparisons": [
            ["R2V2-P4_MEMORY_SPECIALIST_COMPOSITION", "R2V2-B4_JOINT_LLM"],
            ["R2V2-P4_MEMORY_SPECIALIST_COMPOSITION", "R2V2-P3_RAG_MEMORY_SPECIALISTS"],
        ],
        "component_analysis": [
            ["R2V2-RAG_SPECIALIST", "R2V2-B4_JOINT_LLM.RAG_BIT"],
            ["R2V2-MEMORY_SPECIALIST", "R2V2-B4_JOINT_LLM.MEMORY_BIT"],
        ],
        "P4_role": "EXPLORATORY_POST_DEV_ABLATION",
        "winner_designated": False,
    }


def uncertainty_plan() -> dict[str, Any]:
    return {
        "schema_version": "rq2-v2-stage4n-uncertainty-reporting-plan-v1",
        "status": "FROZEN_BEFORE_TEST",
        "interpretation": "DESCRIPTIVE_UNCERTAINTY_NOT_SIGNIFICANCE_TESTING",
        "resampling_unit": "scenario_family_id",
        "seed": 20260831,
        "bootstrap_replicates": 10000,
        "interval": {"method": "PERCENTILE", "level": 0.95},
        "metrics": ["Macro-F1", "Exact Capability Set Match", "Jaccard", "under-routing", "over-routing"],
        "paired_differences": ["B4 minus B3", "P1 minus B4", "P2 minus B4", "P3 minus B4", "P4 minus B4", "P4 minus P3"],
        "may_change_methods_thresholds_prompts_or_tiers": False,
        "statistical_significance_promised": False,
    }


def _scoring_markdown() -> str:
    return """# RQ2-V2 Final TEST Scoring Protocol

Status: `FROZEN_BEFORE_TEST_PREDICTION_EXECUTION`. Current scoring status:
`NOT_EXECUTED`.

## Gold access gate

TEST Gold may be opened only by a separately authorized scoring task after all
prediction files have been frozen. Prediction execution remains blind to Gold,
and Gold must never determine which of the 36 inputs receives a prediction.

## Core Capability scoring

Score RAG, Memory, and Planning only on cases whose authorized Gold dialogue
action is ANSWER. Derive that population at scoring time. Report Macro-F1,
Micro-F1, per-label Precision/Recall/F1, Exact Capability Set Match,
example-based F1, Jaccard, Hamming Loss, under-routing, over-routing, mean
capability count, signature distribution, family-both-correct, family
prediction consistency, contrast consistency, Gold-pattern contrast match,
page metrics, and Writer A/B metrics. Writer identity may come only from the
authorized Gold; if it is absent, report the writer metrics unavailable and do
not infer identity from IDs.

## End-to-end scoring

Evaluate all 36 inputs. The frozen Clarification Gate supplies the runtime
dialogue action. For predicted CLARIFY, capability outputs are NOT_APPLICABLE.
For predicted ANSWER, use the corresponding frozen core prediction. Report
dialogue-action Accuracy/F1, full route-signature Exact Match,
family-both-correct, family prediction consistency, complete contrast
consistency, and complete Gold-pattern match.

## Calls and costs

Report actual experimental provider calls. Separately report counterfactual
deployment calls and costs. Calls on cases later found to be Gold CLARIFY are
research-audit calls and are not counterfactual deployment calls.

## Frozen interpretation and uncertainty

Use `comparison_hierarchy_v1.json` and
`uncertainty_reporting_plan_v1.json`. P4 remains exploratory. TEST results and
bootstrap intervals must not alter any method, threshold, prompt, development
status, or reporting tier. No statistical-significance claim is predeclared.
"""


def _status_markdown() -> str:
    return f"""# RQ2-V2 Stage 4N Status

`{READY_STATUS}`

- Source Stage-4 HEAD: `{SOURCE_STAGE_HEAD}`
- Frozen method count: 14
- TEST input status: `{TEST_INPUT_STATUS}`
- TEST input rows: 36
- Deterministic logical cases: 36; frozen method outputs per case: 7; total future deterministic method outputs: 252
- B4 logical calls: 36; physical-attempt ceiling: 72
- RAG Specialist logical calls: 36; physical-attempt ceiling: 72
- Memory Specialist logical calls: 36; physical-attempt ceiling: 72
- Total future provider logical calls: 108; total provider physical-attempt ceiling: 216
- TEST predictions created in Stage 4N: 0
- Provider calls made in Stage 4N: 0
- TEST scores calculated in Stage 4N: 0
- TEST Gold opened or extracted in Stage 4N: no
- Frozen method bytes changed: no
- RQ3 access or work: none

This is a research-only freeze. It grants no prediction-execution authority.
"""


def _readme_markdown() -> str:
    return """# RQ2-V2 Stage 4N Final Integration

This directory freezes the 14-method universe, frozen source identities,
Gold-free TEST execution population, four unexecuted manifests, future scoring
protocol, and execution-only package builders.

The builder and validators are serialization/static-audit tools. They do not
execute a Router, import a provider SDK, score TEST, or open TEST Gold. The two
provider and deterministic runner files are future-only and require a separate
literal execution authorization token.
"""


def _schemas() -> tuple[dict[str, Any], dict[str, Any]]:
    deterministic = {
        "$schema": "https://json-schema.org/draft/2020-12/schema",
        "title": "RQ2-V2 deterministic TEST terminal result",
        "type": "object",
        "additionalProperties": False,
        "required": ["schema_version", "logical_case_id", "annotation_case_id", "execution_status", "method_predictions", "provider_calls", "scoring_performed"],
        "properties": {
            "schema_version": {"const": "rq2-v2-stage4n-deterministic-test-terminal-result-v1"},
            "logical_case_id": {"type": "string"},
            "annotation_case_id": {"type": "string"},
            "execution_status": {"const": "VALID_PREDICTIONS"},
            "method_predictions": {
                "type": "object",
                "required": list(DETERMINISTIC_METHOD_IDS),
                "additionalProperties": False,
                "properties": {method: {"type": "object"} for method in DETERMINISTIC_METHOD_IDS},
            },
            "provider_calls": {"const": 0},
            "scoring_performed": {"const": False},
        },
    }
    provider = {
        "$schema": "https://json-schema.org/draft/2020-12/schema",
        "title": "RQ2-V2 provider TEST terminal result",
        "type": "object",
        "additionalProperties": False,
        "required": ["schema_version", "logical_case_id", "logical_call_id", "annotation_case_id", "method_id", "execution_status", "physical_attempts", "attempt_records", "prediction", "scoring_performed"],
        "properties": {
            "schema_version": {"const": "rq2-v2-stage4n-provider-test-terminal-result-v1"},
            "logical_case_id": {"type": "string"},
            "logical_call_id": {"type": "string"},
            "annotation_case_id": {"type": "string"},
            "method_id": {"enum": [spec["method_id"] for spec in PROVIDER_STREAMS.values()]},
            "execution_status": {"enum": ["VALID_PREDICTION", "INVALID_TERMINAL_RESULT", "PROVIDER_ERROR"]},
            "physical_attempts": {"type": "integer", "minimum": 1, "maximum": 2},
            "attempt_records": {"type": "array", "minItems": 1, "maxItems": 2},
            "prediction": {"type": ["object", "null"]},
            "scoring_performed": {"const": False},
        },
    }
    return deterministic, provider


def build_all(output_dir: Path = INTEGRATION_DIR) -> list[str]:
    source_rows, external_rows = verify_frozen_sources()
    rows = verify_test_inputs()
    identities = verify_embedded_identities()
    method_registry = build_method_registry()
    deterministic = build_deterministic_manifest(rows)
    provider_manifests = {
        stream: build_provider_manifest(stream, rows) for stream in PROVIDER_STREAMS
    }

    source_registry = {
        "schema_version": "rq2-v2-stage4n-frozen-source-hash-registry-v1",
        "registry_status": "PASS_ALL_FROZEN_SOURCE_BINDINGS",
        "source_stage_head": SOURCE_STAGE_HEAD,
        "source_file_count": len(source_rows),
        "source_files": source_rows,
        "external_source_checkout": {"path": str(C0_ROOT), "head": C0_SOURCE_HEAD, "clean": True},
        "external_file_count": len(external_rows),
        "external_files": external_rows,
        "embedded_identities": identities,
        "primary_feature_profile": {"id": PRIMARY_FEATURE_PROFILE, "semantic_fields": list(PRIMARY_FIELDS)},
        "opaque_test_escrow_zip": {"path": str(TEST_ESCROW_ZIP), "sha256": TEST_ESCROW_ZIP_SHA256, "content_inspection": "ALLOWLISTED_EXTRACTION_ONLY"},
    }
    deterministic_source_paths = sorted(
        {
            path
            for method_id in DETERMINISTIC_METHOD_IDS
            for path in METHOD_SOURCES[method_id]
        }
    )
    deterministic_source_registry = {
        "schema_version": "rq2-v2-stage4n-deterministic-source-hash-registry-v1",
        "registry_status": "PASS_ALL_FROZEN_SOURCE_BINDINGS",
        "source_stage_head": SOURCE_STAGE_HEAD,
        "method_ids": list(DETERMINISTIC_METHOD_IDS),
        "source_files": [
            row for row in source_rows if row["path"] in deterministic_source_paths
        ],
        "external_files": external_rows,
        "primary_feature_profile": {
            "id": PRIMARY_FEATURE_PROFILE,
            "semantic_fields": list(PRIMARY_FIELDS),
        },
    }
    test_verification = {
        "schema_version": "rq2-v2-stage4n-test-input-verification-v1",
        "TEST_INPUT_STATUS": TEST_INPUT_STATUS,
        "opaque_escrow_zip_sha256": TEST_ESCROW_ZIP_SHA256,
        "allowed_extracted_members": [
            {"name": name, "sha256": digest, "size_bytes": (TEST_INPUT_DIR / name).stat().st_size}
            for name, digest in EXPECTED_TEST_INPUT_HASHES.items()
        ],
        "row_count": 36,
        "unique_row_count": 36,
        "unique_annotation_case_id_count": 36,
        "exact_fields": list(TEST_INPUT_FIELDS),
        "semantic_fields": list(PRIMARY_FIELDS),
        "visible_history_valid_json_array_count": 36,
        "csv_jsonl_semantically_identical_in_order": True,
        "capability_labels_present": False,
        "dialogue_action_labels_present": False,
        "scenario_family_ids_present": False,
        "writer_ids_present": False,
        "contrast_ids_present": False,
        "Gold_fields_present": False,
        "partition_derived_model_features_present": False,
        "individual_query_manual_review_or_classification_performed": False,
        "TEST_Gold_opened": False,
        "TEST_Gold_extracted": False,
    }
    deterministic_config = {
        "schema_version": "rq2-v2-stage4n-deterministic-test-execution-config-v1",
        "status": TEST_STATUS,
        "population": "ALL_36_FROZEN_TEST_INPUTS_WITHOUT_GOLD_FILTERING",
        "logical_case_count": 36,
        "methods_per_case": list(DETERMINISTIC_METHOD_IDS),
        "method_prediction_count": 252,
        "provider_call_count": 0,
        "method_execution_attempt_ceiling": 252,
        "P1_future_composition": {"components": ["R2V2-B0_RULE", "R2V2-B2_PROTOTYPE", "R2V2-B3_OVR", "R2V2-B4_JOINT_LLM"], "executed_in_stage4n": False},
        "scoring_performed": False,
    }
    population = {
        "schema_version": "rq2-v2-stage4n-test-execution-population-v1",
        "status": TEST_STATUS,
        "population_rule": "ALL_CORE_EXECUTORS_RECEIVE_ALL_36_TEST_INPUTS_WITHOUT_GOLD_FILTERING",
        "deterministic": {"logical_cases": 36, "method_outputs": 252, "physical_attempt_ceiling": 252, "provider_calls": 0},
        "B4": {"logical_calls": 36, "physical_attempt_ceiling": 72},
        "RAG_SPECIALIST": {"logical_calls": 36, "physical_attempt_ceiling": 72},
        "MEMORY_SPECIALIST": {"logical_calls": 36, "physical_attempt_ceiling": 72},
        "provider_totals": {"logical_calls": 108, "physical_attempt_ceiling": 216},
        "actual_stage4n": {"predictions": 0, "provider_calls": 0, "scores": 0},
    }

    deterministic_schema, provider_schema = _schemas()
    artifacts: dict[str, Any] = {
        "final_method_registry_v1.json": method_registry,
        "frozen_source_hash_registry_v1.json": source_registry,
        "deterministic_source_hash_registry_v1.json": deterministic_source_registry,
        "test_input_verification_v1.json": test_verification,
        "deterministic_test_execution_config_v1.json": deterministic_config,
        "test_execution_population_v1.json": population,
        "final_test_scoring_protocol_v1.json": scoring_protocol(),
        "comparison_hierarchy_v1.json": comparison_hierarchy(),
        "uncertainty_reporting_plan_v1.json": uncertainty_plan(),
        "deterministic_prediction_output_schema_v1.json": deterministic_schema,
        "provider_prediction_output_schema_v1.json": provider_schema,
    }
    for name, value in artifacts.items():
        write_json(output_dir / name, value)
    write_jsonl(output_dir / "deterministic_test_execution_manifest_v1.jsonl", deterministic)
    for stream, records in provider_manifests.items():
        write_jsonl(output_dir / PROVIDER_STREAMS[stream]["manifest"], records)
    (output_dir / "FINAL_TEST_SCORING_PROTOCOL.md").write_text(_scoring_markdown(), encoding="utf-8")
    (output_dir / "STATUS.md").write_text(_status_markdown(), encoding="utf-8")
    (output_dir / "README.md").write_text(_readme_markdown(), encoding="utf-8")

    generated_names = sorted(
        [*artifacts,
         "deterministic_test_execution_manifest_v1.jsonl",
         *[spec["manifest"] for spec in PROVIDER_STREAMS.values()],
         "FINAL_TEST_SCORING_PROTOCOL.md", "STATUS.md", "README.md"]
    )
    generated_manifest = {
        "schema_version": "rq2-v2-stage4n-generated-artifact-manifest-v1",
        "status": "FROZEN_UNEXECUTED",
        "files": [
            {"path": name, "sha256": sha256_file(output_dir / name), "size_bytes": (output_dir / name).stat().st_size}
            for name in generated_names
        ],
    }
    write_json(output_dir / "STAGE4N_GENERATED_SHA256_MANIFEST.json", generated_manifest)
    return [*generated_names, "STAGE4N_GENERATED_SHA256_MANIFEST.json"]


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-dir", type=Path, default=INTEGRATION_DIR)
    args = parser.parse_args()
    names = build_all(args.output_dir.resolve())
    print(f"PASS built {len(names)} deterministic Stage 4N artifacts")
    print("PASS zero Router predictions, provider calls, TEST scores, or Gold access")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
