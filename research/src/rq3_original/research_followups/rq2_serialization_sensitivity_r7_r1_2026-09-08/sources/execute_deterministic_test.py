"""Future-only executor for the seven frozen deterministic TEST methods.

Stage 4N never runs this module.  A later task must supply the exact execution
authorization token.  The executor predicts every frozen method for all 36
inputs and writes no metric or Gold-derived value.
"""

from __future__ import annotations

import argparse
from contextlib import contextmanager
import hashlib
import json
import os
from pathlib import Path
import socket
import sys
from typing import Any, Iterator, Mapping
from unittest.mock import patch


AUTHORIZATION_TOKEN = "RQ2_V2_FINAL_TEST_PREDICTION_EXECUTION_AUTHORIZED"
PRIMARY_FIELDS = (
    "current_query", "current_page", "dashboard_context",
    "visible_conversation_history",
)
METHOD_IDS = (
    "R2V2-CG1_CLARIFICATION_RULE", "R2V2-D0_ALWAYS_ON",
    "R2V2-D1_NEVER_ON", "R2V2-B0_RULE", "R2V2-B1_LEGACY_INTENT",
    "R2V2-B2_PROTOTYPE", "R2V2-B3_OVR",
)


class ExecutionBoundaryError(RuntimeError):
    """Raised when a frozen future-execution boundary differs."""


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def read_json(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ExecutionBoundaryError(f"JSON root must be an object: {path}")
    return value


def read_manifest(path: Path) -> list[dict[str, Any]]:
    rows = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line]
    if len(rows) != 36 or any(not isinstance(row, dict) for row in rows):
        raise ExecutionBoundaryError("deterministic manifest must have 36 object records")
    ids = [str(row.get("annotation_case_id") or "") for row in rows]
    if len(set(ids)) != 36 or "" in ids:
        raise ExecutionBoundaryError("deterministic manifest annotation IDs differ")
    allowed = {"logical_case_id", "annotation_case_id", *PRIMARY_FIELDS, "execution_status"}
    for row in rows:
        if set(row) != allowed or row.get("execution_status") != "NOT_EXECUTED":
            raise ExecutionBoundaryError("deterministic manifest fields/status differ")
    return rows


def verify_registry(registry: Mapping[str, Any], repository_root: Path) -> None:
    if registry.get("registry_status") != "PASS_ALL_FROZEN_SOURCE_BINDINGS":
        raise ExecutionBoundaryError("source registry is not frozen")
    for item in registry.get("source_files") or []:
        path = repository_root / str(item["path"])
        if not path.is_file() or sha256_file(path) != item.get("sha256"):
            raise ExecutionBoundaryError(f"frozen repository source differs: {path}")
    for item in registry.get("external_files") or []:
        path = Path(str(item["path"]))
        if not path.is_file() or sha256_file(path) != item.get("sha256"):
            raise ExecutionBoundaryError(f"frozen external source differs: {path}")


def _blocked(*_args: Any, **_kwargs: Any) -> Any:
    raise ExecutionBoundaryError("deterministic execution attempted network access")


@contextmanager
def offline_guard() -> Iterator[None]:
    environment = {
        "HF_HUB_OFFLINE": "1",
        "TRANSFORMERS_OFFLINE": "1",
        "HF_DATASETS_OFFLINE": "1",
        "TOKENIZERS_PARALLELISM": "false",
    }
    with patch.dict(os.environ, environment, clear=False):
        with patch("socket.create_connection", _blocked):
            with patch.object(socket.socket, "connect", _blocked):
                with patch.object(socket.socket, "connect_ex", _blocked):
                    yield


def load_c0(c0_root: Path) -> Any:
    config = c0_root / "semantic_runtime/config/semantic_routing_config.json"
    if str(c0_root) not in sys.path:
        sys.path.insert(0, str(c0_root))
    from utils.production_intent_router import load_production_semantic_router

    module_path = Path(sys.modules[load_production_semantic_router.__module__].__file__).resolve()
    expected = (c0_root / "utils/production_intent_router.py").resolve()
    if module_path != expected:
        raise ExecutionBoundaryError("C0 loader resolved outside frozen checkout")
    runtime = load_production_semantic_router(str(config))
    if runtime.aggregation_method != "max" or len(tuple(runtime.frozen_index.records)) != 62:
        raise ExecutionBoundaryError("C0 runtime identity differs")
    return runtime


def c0_predictions(runtime: Any, rows: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    results: dict[str, dict[str, Any]] = {}
    for row in rows:
        page = None if row["current_page"] == "Other" else row["current_page"]
        prediction = runtime.predict(
            row["current_query"], current_page=page, top_k=62,
            candidate_limit=16, aggregate_all_examples=True,
        )
        value = prediction.result
        if value.status != "available" or not value.winning_label:
            raise ExecutionBoundaryError("C0 inference returned unavailable")
        results[row["annotation_case_id"]] = {
            "intent_id": str(value.winning_label),
            "score": float(value.winning_score),
            "margin": None if value.margin is None else float(value.margin),
        }
    return results


def load_embeddings(c0_root: Path, texts: list[str]) -> Any:
    model_path = c0_root / (
        "semantic_runtime/models/all-mpnet-base-v2/"
        "e8c3b32edf5434bc2275fc9bab85f82640a19130"
    )
    from sentence_transformers import SentenceTransformer

    model = SentenceTransformer(str(model_path), device="cpu", local_files_only=True)
    return model.encode(
        texts, batch_size=16, show_progress_bar=False,
        convert_to_numpy=True, normalize_embeddings=True,
    )


def execute(
    rows: list[dict[str, Any]], repository_root: Path, c0_root: Path,
) -> list[dict[str, Any]]:
    with offline_guard():
        runtime = load_c0(c0_root)
        c0 = c0_predictions(runtime, rows)
        if str(repository_root) in sys.path:
            sys.path.remove(str(repository_root))
        sys.path.insert(0, str(repository_root))
        from evaluation.capability_routing_rq2_v2_stage4.track_g_b0_b1.clarification_gate import ClarificationGate
        from evaluation.capability_routing_rq2_v2_stage1.track_b_b0_b1 import b0_rule_router as b0_module
        from evaluation.capability_routing_rq2_v2_stage1.track_c_b2_b3.canonical_text import serialize_canonical_text
        from evaluation.capability_routing_rq2_v2_stage4.track_h_b2_b3.track_h import predict_from_b2_payload, predict_from_b3_payload

        stage4 = repository_root / "evaluation/capability_routing_rq2_v2_stage4"
        candidate = read_json(stage4 / "track_g_b0_b1/clarification_candidate_configs_v1.json")
        cg_freeze = read_json(stage4 / "track_g_b0_b1/clarification_gate_frozen_v1.json")
        gate = ClarificationGate(candidate)
        b0 = b0_module.B0RuleRouter(
            repository_root / "evaluation/capability_routing_rq2_v2_stage1/track_b_b0_b1/config/b0_rules_v1.json"
        )
        # Adapt the sanitized five-field TEST row to the old Stage-0 container
        # without introducing placeholder Gold.  The frozen B0 prediction body
        # remains unchanged and reads only case_id/model_input.
        b0_module.validate_case = lambda _case: None
        mapping_payload = read_json(stage4 / "track_g_b0_b1/b1_mapping_frozen_v1.json")
        mapping = {item["intent_id"]: item["capabilities"] for item in mapping_payload["mappings"]}

        cases = [
            {"model_input": {field: row[field] for field in PRIMARY_FIELDS}}
            for row in rows
        ]
        texts = [serialize_canonical_text(case) for case in cases]
        embeddings = load_embeddings(c0_root, texts)
        b2_payload = read_json(stage4 / "track_h_b2_b3/b2_frozen_model_v1.json")
        b3_payload = read_json(stage4 / "track_h_b2_b3/b3_frozen_model_v1.json")
        b2_scores, b2_predictions = predict_from_b2_payload(embeddings, b2_payload)
        b3_probabilities, b3_predictions = predict_from_b3_payload(embeddings, b3_payload)

        capabilities = ("RAG", "Memory", "Planning")
        output: list[dict[str, Any]] = []
        for index, row in enumerate(rows):
            semantic = {field: row[field] for field in PRIMARY_FIELDS}
            cg = gate.predict(semantic, cg_freeze["selected_config_id"])
            b0_prediction = b0.predict({"case_id": row["annotation_case_id"], "model_input": semantic})
            intent = c0[row["annotation_case_id"]]
            mapped = mapping.get(intent["intent_id"])
            if mapped is None:
                raise ExecutionBoundaryError("C0 intent is outside frozen B1 mapping")
            b1_bits = {
                "rag_required": bool(mapped["RAG"]["mapping_boolean"]),
                "memory_required": bool(mapped["Memory"]["mapping_boolean"]),
                "planning_required": bool(mapped["Planning"]["mapping_boolean"]),
            }
            b2_bits = {f"{name.casefold()}_required": bool(b2_predictions[index, column]) for column, name in enumerate(capabilities)}
            b3_bits = {f"{name.casefold()}_required": bool(b3_predictions[index, column]) for column, name in enumerate(capabilities)}
            method_predictions = {
                "R2V2-CG1_CLARIFICATION_RULE": {"dialogue_action": cg.dialogue_action, "matched_clause": cg.matched_clause},
                "R2V2-D0_ALWAYS_ON": {"rag_required": True, "memory_required": True, "planning_required": True},
                "R2V2-D1_NEVER_ON": {"rag_required": False, "memory_required": False, "planning_required": False},
                "R2V2-B0_RULE": {"rag_required": bool(b0_prediction.rag_required), "memory_required": bool(b0_prediction.memory_required), "planning_required": bool(b0_prediction.planning_required)},
                "R2V2-B1_LEGACY_INTENT": {**b1_bits, "legacy_intent": intent["intent_id"], "legacy_top1_score": intent["score"], "legacy_top1_margin": intent["margin"]},
                "R2V2-B2_PROTOTYPE": {**b2_bits, "scores": {name: float(b2_scores[index, column]) for column, name in enumerate(capabilities)}},
                "R2V2-B3_OVR": {**b3_bits, "probabilities": {name: float(b3_probabilities[index, column]) for column, name in enumerate(capabilities)}},
            }
            if tuple(method_predictions) != METHOD_IDS:
                raise ExecutionBoundaryError("deterministic method universe differs")
            output.append({
                "schema_version": "rq2-v2-stage4n-deterministic-test-terminal-result-v1",
                "logical_case_id": row["logical_case_id"],
                "annotation_case_id": row["annotation_case_id"],
                "execution_status": "VALID_PREDICTIONS",
                "method_predictions": method_predictions,
                "provider_calls": 0,
                "scoring_performed": False,
            })
    return output


def write_output(path: Path, rows: list[dict[str, Any]]) -> None:
    if path.exists():
        raise ExecutionBoundaryError("deterministic output already exists")
    temporary = path.with_suffix(path.suffix + ".partial")
    if temporary.exists():
        raise ExecutionBoundaryError("deterministic partial output already exists")
    with temporary.open("x", encoding="utf-8") as handle:
        for row in rows:
            handle.write(json.dumps(row, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n")
        handle.flush()
        os.fsync(handle.fileno())
    os.replace(temporary, path)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--source-registry", type=Path, required=True)
    parser.add_argument("--repository-root", type=Path, required=True)
    parser.add_argument("--c0-root", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--authorization-token", required=True)
    args = parser.parse_args()
    if args.authorization_token != AUTHORIZATION_TOKEN:
        raise ExecutionBoundaryError("separate final-TEST prediction authority is absent")
    rows = read_manifest(args.manifest.resolve())
    repository_root = args.repository_root.resolve()
    c0_root = args.c0_root.resolve()
    registry = read_json(args.source_registry.resolve())
    verify_registry(registry, repository_root)
    results = execute(rows, repository_root, c0_root)
    if len(results) != 36:
        raise ExecutionBoundaryError("deterministic terminal result count differs")
    write_output(args.output.resolve(), results)
    print("PASS executed 36 future cases x 7 deterministic methods; no scoring performed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
