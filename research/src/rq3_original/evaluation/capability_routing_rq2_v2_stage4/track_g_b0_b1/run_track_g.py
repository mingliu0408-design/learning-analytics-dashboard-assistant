"""Run the authorized RQ2-V2 Stage 4G DEV-only evaluation.

The runner is local, deterministic, fail-closed, and network-blocked. It reads
only the frozen Stage 4-0 DEV protocol plus the explicitly authorized read-only
historical C0 repository. It never locates or accepts a held-out input path.
"""

from __future__ import annotations

from collections import Counter, defaultdict
from contextlib import contextmanager
import csv
import hashlib
import json
import os
from pathlib import Path
import re
import socket
import subprocess
import sys
from typing import Any, Iterable, Iterator, Mapping, Sequence
from unittest.mock import patch

from . import (
    B0_MODEL_ID,
    B1_MODEL_ID,
    CAPABILITIES,
    CLARIFICATION_GATE_ID,
    PACKAGE_ROOT,
    PROJECT_ROOT,
    STAGE4_ROOT,
)
from .clarification_gate import ALLOWED_FIELDS, ClarificationGate
from .metrics import clarification_metrics, core_metrics, end_to_end_metrics


DEV_ROOT = STAGE4_ROOT / "dev_protocol"
CANDIDATE_PATH = PACKAGE_ROOT / "clarification_candidate_configs_v1.json"
STAGE1_B0_ROOT = (
    PROJECT_ROOT / "evaluation" / "capability_routing_rq2_v2_stage1" / "track_b_b0_b1"
)
B0_CONFIG_PATH = STAGE1_B0_ROOT / "config" / "b0_rules_v1.json"
B0_CODE_PATH = STAGE1_B0_ROOT / "b0_rule_router.py"
C0_ROOT = Path("/Users/liuming/Downloads/duteaiapp_cfull_semantic_integrated_v1_副本3")
C0_CONFIG_PATH = C0_ROOT / "semantic_runtime" / "config" / "semantic_routing_config.json"
C0_INDEX_PATH = (
    C0_ROOT / "semantic_runtime" / "artifacts" / "intent_examples_approved_index_v1.jsonl"
)
C0_EMBEDDING_PATH = (
    C0_ROOT
    / "semantic_runtime"
    / "artifacts"
    / "intent_index_embeddings_mpnet_base_v2_v1.npz"
)
C0_LOADER_PATH = C0_ROOT / "utils" / "production_intent_router.py"
C0_ROUTER_PATH = C0_ROOT / "utils" / "semantic_intent_router.py"

FOLDS = tuple(f"DEV-CV-FOLD-{index}" for index in range(1, 5))
LABEL_KEYS = ("rag", "memory", "planning")
LABEL_NAMES = dict(zip(LABEL_KEYS, CAPABILITIES))

EXPECTED_DEV_HASHES = {
    "dev_capability_gold_v1.csv": "8d3422198a99422b3e314c60819f3553ff27cd42394ed2d9f68c0eb3ce858b56",
    "dev_capability_gold_v1.jsonl": "0ed28dec7dc3cb87e289747d0658541f8fdd66f2c50f5483dd1e2da577e82598",
    "dev_atomic_group_map_v1.csv": "f1ac8973c590155ee3730de194b4c2afd6d05531744bef70a163be2428d4bd6f",
    "dev_atomic_group_map_v1.jsonl": "58fa4748fee8430e3f9918a65982ab09427b967896f5461eeb3b7237052670a2",
    "dev_cv_folds_v1.csv": "2a3a4161c81bddfcfe51b238ac5940c64df87a25beed26e54671b64c76c5ab46",
    "dev_cv_folds_v1.jsonl": "d69b67e51268b7d5c46041aacf2767be4ab2ac2780572f8a8a9cced57bce0b1c",
    "stage4_dev_protocol_v1.json": "9e4e8afa354f544d58d6d30187af194e52968df5ec21ccbdcb7f6585adb75336",
    "STAGE4_DEV_PROTOCOL.md": "f4573b956dcfb39509fba7b1a93bf2fd89bbdf63235b0b2341bb1d3ce083fa66",
}

EXPECTED_C0_HASHES = {
    "loader_code": "e3b7517a6520c35b6b4727249ed536d617b880a25cb23abe5eab020e5912c6b1",
    "router_code": "10f64166401ac0ecbf1c4d7051420f5406754190f58ce95d3f890d6cc8d0dbe9",
    "runtime_config": "5d1f59587e16f03cd7640e2392fdad757731854ca9e1276de779a0050dac2220",
    "intent_index": "b4cac34df91c074a4a2fa85e4ccc52623563f3358fe44938771f8303f00b6be9",
    "embedding_matrix": "8b6fb268970c119ec58ce304e1c9ad0380e161fe086713dbf77d432b547bf9d8",
}

EXPECTED_B0_HASHES = {
    "ruleset": "84fdd1413958199106c10c4105df248e9ace7075ca6988e50c6bcdc253146f53",
    "code": "834a457cf996039a4edae4422240f25047af203a07f35d3d8036aab5f9d28c27",
}

OFFLINE_ENVIRONMENT = {
    "PYTHONDONTWRITEBYTECODE": "1",
    "HF_HUB_OFFLINE": "1",
    "TRANSFORMERS_OFFLINE": "1",
    "TOKENIZERS_PARALLELISM": "false",
    "OPENAI_API_KEY": "",
    "CUDA_VISIBLE_DEVICES": "",
}


class TrackGEvaluationError(RuntimeError):
    """Raised before a result is accepted when a frozen boundary fails."""


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def canonical_json_bytes(value: Any) -> bytes:
    return json.dumps(
        value, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    ).encode("utf-8")


def canonical_sha256(value: Any) -> str:
    return hashlib.sha256(canonical_json_bytes(value)).hexdigest()


def _read_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def _read_jsonl(path: Path) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for line_number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        if not line.strip():
            continue
        value = json.loads(line)
        if not isinstance(value, dict):
            raise TrackGEvaluationError(f"non-object JSONL row at {path}:{line_number}")
        rows.append(value)
    return rows


def _read_csv(path: Path) -> list[dict[str, str]]:
    with path.open(encoding="utf-8", newline="") as handle:
        return [dict(row) for row in csv.DictReader(handle)]


def _write_json(path: Path, value: Any) -> None:
    path.write_text(
        json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
        newline="\n",
    )


def _write_csv(path: Path, fieldnames: Sequence[str], rows: Iterable[Mapping[str, Any]]) -> None:
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames, lineterminator="\n")
        writer.writeheader()
        for row in rows:
            writer.writerow({name: row.get(name, "") for name in fieldnames})


def _yes_no(value: bool) -> str:
    return "YES" if value else "NO"


def _parse_yes_no(value: str, *, allow_not_applicable: bool = False) -> bool | None:
    if value == "YES":
        return True
    if value == "NO":
        return False
    if allow_not_applicable and value in {"", "NOT_APPLICABLE"}:
        return None
    raise TrackGEvaluationError(f"invalid frozen capability value: {value!r}")


def _case_sort(row: Mapping[str, Any]) -> str:
    return str(row["annotation_case_id"])


def _verify_hashes(root: Path, expected: Mapping[str, str]) -> dict[str, str]:
    observed: dict[str, str] = {}
    for name, expected_hash in expected.items():
        path = root / name
        if not path.is_file():
            raise TrackGEvaluationError(f"required frozen file is missing: {path}")
        digest = sha256_file(path)
        if digest != expected_hash:
            raise TrackGEvaluationError(f"frozen file hash mismatch: {path}")
        observed[name] = digest
    return observed


def load_dev_rows() -> tuple[list[dict[str, Any]], dict[str, str]]:
    """Verify and join only the eight authorized Stage 4-0 DEV files."""

    observed_hashes = _verify_hashes(DEV_ROOT, EXPECTED_DEV_HASHES)
    gold_csv = _read_csv(DEV_ROOT / "dev_capability_gold_v1.csv")
    gold_jsonl = _read_jsonl(DEV_ROOT / "dev_capability_gold_v1.jsonl")
    if len(gold_csv) != 72 or len(gold_jsonl) != 72:
        raise TrackGEvaluationError("DEV Gold must contain exactly 72 rows in both formats")
    json_by_id = {str(row.get("annotation_case_id")): row for row in gold_jsonl}
    if len(json_by_id) != 72:
        raise TrackGEvaluationError("DEV JSONL annotation IDs are not unique")
    for row in gold_csv:
        other = json_by_id.get(row["annotation_case_id"])
        if other is None or any(str(other.get(key, "")) != value for key, value in row.items()):
            raise TrackGEvaluationError("DEV CSV and JSONL Gold bytes are semantically inconsistent")

    atomic_csv = _read_csv(DEV_ROOT / "dev_atomic_group_map_v1.csv")
    atomic_jsonl = _read_jsonl(DEV_ROOT / "dev_atomic_group_map_v1.jsonl")
    if len(atomic_csv) != 72 or len(atomic_jsonl) != 72:
        raise TrackGEvaluationError("atomic grouping maps must each contain 72 rows")
    atomic_by_id = {row["annotation_case_id"]: row for row in atomic_csv}
    atomic_json_by_id = {str(row.get("annotation_case_id")): row for row in atomic_jsonl}
    if len(atomic_by_id) != 72 or len(atomic_json_by_id) != 72:
        raise TrackGEvaluationError("atomic grouping IDs are not unique")
    for annotation_id, row in atomic_by_id.items():
        other = atomic_json_by_id.get(annotation_id)
        if other is None or any(str(other.get(key, "")) != value for key, value in row.items()):
            raise TrackGEvaluationError("atomic CSV and JSONL are inconsistent")

    fold_csv = _read_csv(DEV_ROOT / "dev_cv_folds_v1.csv")
    fold_jsonl = _read_jsonl(DEV_ROOT / "dev_cv_folds_v1.jsonl")
    if len(fold_csv) != 288 or len(fold_jsonl) != 288:
        raise TrackGEvaluationError("expanded four-fold files must each contain 288 rows")
    fold_key = lambda row: (str(row["annotation_case_id"]), str(row["fold_id"]))
    fold_csv_by_key = {fold_key(row): row for row in fold_csv}
    fold_json_by_key = {fold_key(row): row for row in fold_jsonl}
    if len(fold_csv_by_key) != 288 or set(fold_csv_by_key) != set(fold_json_by_key):
        raise TrackGEvaluationError("fold rows are not uniquely aligned")
    for key, row in fold_csv_by_key.items():
        other = fold_json_by_key[key]
        if any(str(other.get(name, "")) != value for name, value in row.items()):
            raise TrackGEvaluationError("fold CSV and JSONL are inconsistent")

    validation_fold: dict[str, str] = {}
    for annotation_id in sorted(atomic_by_id):
        assignments = [
            fold_csv_by_key[(annotation_id, fold)]
            for fold in FOLDS
            if (annotation_id, fold) in fold_csv_by_key
        ]
        if len(assignments) != 4:
            raise TrackGEvaluationError("each DEV case must occur in every outer fold")
        roles = Counter(row["fold_role"] for row in assignments)
        if roles != Counter({"TRAINING": 3, "VALIDATION": 1}):
            raise TrackGEvaluationError("each DEV case must have exactly one validation fold")
        validation_fold[annotation_id] = next(
            row["fold_id"] for row in assignments if row["fold_role"] == "VALIDATION"
        )

    component_folds: dict[str, set[str]] = defaultdict(set)
    rows: list[dict[str, Any]] = []
    for raw in gold_csv:
        annotation_id = raw["annotation_case_id"]
        atomic = atomic_by_id.get(annotation_id)
        if atomic is None:
            raise TrackGEvaluationError("Gold case is absent from the atomic map")
        try:
            history = json.loads(raw["visible_conversation_history"])
        except json.JSONDecodeError as exc:
            raise TrackGEvaluationError("visible history is not valid JSON") from exc
        if not isinstance(history, list):
            raise TrackGEvaluationError("visible history must decode to a list")
        action = raw["final_dialogue_action"]
        if action not in {"ANSWER", "CLARIFY"} or raw["partition"] != "DEV":
            raise TrackGEvaluationError("Gold action or partition is outside the DEV contract")
        row = {
            "annotation_case_id": annotation_id,
            "scenario_family_id": raw["scenario_family_id"],
            "current_query": raw["current_query"],
            "current_page": raw["current_page"],
            "dashboard_context": raw["dashboard_context"],
            "visible_conversation_history": history,
            "gold_dialogue_action": action,
            "gold_rag": _parse_yes_no(raw["final_rag_required"], allow_not_applicable=True),
            "gold_memory": _parse_yes_no(raw["final_memory_required"], allow_not_applicable=True),
            "gold_planning": _parse_yes_no(raw["final_planning_required"], allow_not_applicable=True),
            "dev_atomic_component_id": atomic["dev_atomic_component_id"],
            "dev_contrast_group_id": atomic.get("dev_contrast_group_id", ""),
            "dev_contrast_axis": atomic.get("dev_contrast_axis", ""),
            "outer_fold": validation_fold[annotation_id],
        }
        if action == "ANSWER" and any(row[f"gold_{key}"] is None for key in LABEL_KEYS):
            raise TrackGEvaluationError("ANSWER case has a non-binary capability Gold value")
        component_folds[row["dev_atomic_component_id"]].add(row["outer_fold"])
        rows.append(row)
    rows.sort(key=_case_sort)
    families = Counter(row["scenario_family_id"] for row in rows)
    if len(families) != 36 or set(families.values()) != {2}:
        raise TrackGEvaluationError("DEV must contain exactly two utterances in each of 36 families")
    actions = Counter(row["gold_dialogue_action"] for row in rows)
    if actions != Counter({"ANSWER": 64, "CLARIFY": 8}):
        raise TrackGEvaluationError("DEV action distribution has drifted")
    if len(component_folds) != 24 or any(len(folds) != 1 for folds in component_folds.values()):
        raise TrackGEvaluationError("an atomic component crosses validation folds")
    fold_counts = Counter(row["outer_fold"] for row in rows)
    if fold_counts != Counter({fold: 18 for fold in FOLDS}):
        raise TrackGEvaluationError("validation folds must each contain 18 utterances")
    return rows, observed_hashes


def semantic_input(row: Mapping[str, Any]) -> dict[str, Any]:
    return {field: row[field] for field in ALLOWED_FIELDS}


def evaluate_clarification(
    rows: Sequence[Mapping[str, Any]], candidate_payload: Mapping[str, Any]
) -> tuple[dict[str, Any], list[dict[str, Any]], list[dict[str, Any]]]:
    gate = ClarificationGate(candidate_payload)
    evaluated: dict[str, list[dict[str, Any]]] = {}
    candidate_metrics: dict[str, Any] = {}
    raw_candidates = candidate_payload["candidates"]
    for config in raw_candidates:
        config_id = str(config["config_id"])
        predictions: list[dict[str, Any]] = []
        for row in rows:
            predicted = gate.predict(semantic_input(row), config_id)
            predictions.append(
                {
                    **row,
                    "predicted_dialogue_action": predicted.dialogue_action,
                    "matched_clause": predicted.matched_clause,
                    "unresolved_reference": predicted.unresolved_reference,
                    "plausible_visible_targets": predicted.plausible_visible_targets,
                    "explicit_selection": predicted.explicit_selection,
                    "explicitly_unselected": predicted.explicitly_unselected,
                    "history_resolved": predicted.history_resolved,
                    "activity_unidentified": predicted.activity_unidentified,
                    "deadline_unidentified": predicted.deadline_unidentified,
                }
            )
        evaluated[config_id] = predictions
        candidate_metrics[config_id] = clarification_metrics(predictions)
    ranked = sorted(
        raw_candidates,
        key=lambda config: (
            -candidate_metrics[config["config_id"]]["clarify"]["f1"],
            -candidate_metrics[config["config_id"]]["dialogue_action_accuracy"],
            candidate_metrics[config["config_id"]]["false_clarify_rate_on_gold_answer"],
            -candidate_metrics[config["config_id"]]["clarify"]["recall"],
            int(config["simplicity_rank"]),
            str(config["config_id"]),
        ),
    )
    selected_config = dict(ranked[0])
    selected_id = str(selected_config["config_id"])
    selected_rows = evaluated[selected_id]
    errors = [
        row
        for row in selected_rows
        if row["gold_dialogue_action"] != row["predicted_dialogue_action"]
    ]
    frozen = {
        "schema_version": "rq2-v2-stage4g-clarification-frozen-v1",
        "gate_id": CLARIFICATION_GATE_ID,
        "selection_status": "FROZEN_DEV_SELECTED_NOT_INDEPENDENT_TEST",
        "selected_config_id": selected_id,
        "selected_config": selected_config,
        "selected_config_sha256": canonical_sha256(selected_config),
        "candidate_file_sha256": sha256_file(CANDIDATE_PATH),
        "clarification_code_sha256": sha256_file(PACKAGE_ROOT / "clarification_gate.py"),
        "candidate_metrics": candidate_metrics,
        "selected_oof_metrics": candidate_metrics[selected_id],
        "oof_prediction_count": len(selected_rows),
        "oof_error_count": len(errors),
        "outer_folds": list(FOLDS),
        "selection_order": list(candidate_payload["selection_order"]),
        "candidate_mutation_after_scoring": False,
        "test_accessed": False,
    }
    return frozen, selected_rows, errors


def _canonical_b0_case(row: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "schema_version": "rq2-v2-case-v1",
        "case_id": str(row["annotation_case_id"]),
        "scenario_family_id": str(row["scenario_family_id"]),
        "utterance_id": str(row["annotation_case_id"]),
        "provenance": {
            "type": "HUMAN_ELICITED",
            "source_asset_id": "RQ2_V2_STAGE4_0_FROZEN_DEV",
            "prior_exposure_to_model_selection": True,
            "human_verified": True,
        },
        "partition": "DEV",
        "model_input": {
            **semantic_input(row),
            "rag_context_state": "UNKNOWN",
            "memory_context_state": "UNKNOWN",
        },
        "gold": {
            "dialogue_action": str(row["gold_dialogue_action"]),
            "rag_required": bool(row["gold_rag"]),
            "memory_required": bool(row["gold_memory"]),
            "planning_required": bool(row["gold_planning"]),
        },
        "governance": {
            "final_test_eligible": False,
            "fixture_only": False,
            "authentic_student_data_claim": False,
            "contains_restricted_data": False,
        },
    }


def evaluate_b0(
    rows: Sequence[Mapping[str, Any]], gate_rows: Sequence[Mapping[str, Any]]
) -> tuple[dict[str, Any], list[dict[str, Any]], list[dict[str, Any]], list[dict[str, Any]]]:
    observed = {
        "ruleset": sha256_file(B0_CONFIG_PATH),
        "code": sha256_file(B0_CODE_PATH),
    }
    if observed != EXPECTED_B0_HASHES:
        raise TrackGEvaluationError("frozen Stage 1 B0 hash identity has drifted")
    from evaluation.capability_routing_rq2_v2_stage1.track_b_b0_b1.b0_rule_router import (
        B0RuleRouter,
    )

    router = B0RuleRouter(B0_CONFIG_PATH)
    gate_by_id = {row["annotation_case_id"]: row for row in gate_rows}
    execution_ids = {
        row["annotation_case_id"]
        for row in rows
        if row["gold_dialogue_action"] == "ANSWER"
        or gate_by_id[row["annotation_case_id"]]["predicted_dialogue_action"] == "ANSWER"
    }
    predictions: dict[str, Any] = {}
    for row in rows:
        if row["annotation_case_id"] in execution_ids:
            predictions[row["annotation_case_id"]] = router.predict(_canonical_b0_case(row))
    core_rows: list[dict[str, Any]] = []
    for row in rows:
        if row["gold_dialogue_action"] != "ANSWER":
            continue
        prediction = predictions[row["annotation_case_id"]]
        core_rows.append(
            {
                **row,
                "predicted_dialogue_action": "ANSWER",
                "predicted_rag": bool(prediction.rag_required),
                "predicted_memory": bool(prediction.memory_required),
                "predicted_planning": bool(prediction.planning_required),
                "matched_rule_ids": tuple(prediction.metadata["matched_rule_ids"]),
                "suppressed_rule_ids": tuple(prediction.metadata["suppressed_rule_ids"]),
            }
        )
    end_rows: list[dict[str, Any]] = []
    for row in rows:
        gate_action = gate_by_id[row["annotation_case_id"]]["predicted_dialogue_action"]
        if gate_action == "CLARIFY":
            predicted = {key: False for key in LABEL_KEYS}
            core_executed = False
            matched: tuple[str, ...] = ()
            suppressed: tuple[str, ...] = ()
        else:
            result = predictions[row["annotation_case_id"]]
            predicted = {
                "rag": bool(result.rag_required),
                "memory": bool(result.memory_required),
                "planning": bool(result.planning_required),
            }
            core_executed = True
            matched = tuple(result.metadata["matched_rule_ids"])
            suppressed = tuple(result.metadata["suppressed_rule_ids"])
        end_rows.append(
            {
                **row,
                "predicted_dialogue_action": gate_action,
                **{f"predicted_{key}": value for key, value in predicted.items()},
                "core_executed": core_executed,
                "matched_rule_ids": matched,
                "suppressed_rule_ids": suppressed,
            }
        )
    errors = [row for row in core_rows if any(row[f"gold_{key}"] != row[f"predicted_{key}"] for key in LABEL_KEYS)]
    frozen = {
        "schema_version": "rq2-v2-stage4g-b0-frozen-config-v1",
        "model_id": B0_MODEL_ID,
        "ruleset_id": router.ruleset_id,
        "ruleset_status": router.ruleset_status,
        "source_config_path": B0_CONFIG_PATH.relative_to(PROJECT_ROOT).as_posix(),
        "source_code_path": B0_CODE_PATH.relative_to(PROJECT_ROOT).as_posix(),
        "b0_ruleset_sha256": observed["ruleset"],
        "b0_code_sha256": observed["code"],
        "primary_feature_profile": "R2V2_PRIMARY_SEMANTIC_INPUT_V1",
        "model_visible_fields": list(ALLOWED_FIELDS),
        "privileged_fields_excluded": True,
        "rules_modified_for_stage4g": False,
        "dev_error_specific_tuning": False,
    }
    return frozen, core_rows, end_rows, errors


def _blocked_network(*_args: Any, **_kwargs: Any) -> Any:
    raise TrackGEvaluationError("network access is blocked for Stage 4G")


@contextmanager
def offline_network_guard() -> Iterator[None]:
    with patch.dict(os.environ, OFFLINE_ENVIRONMENT, clear=False), patch(
        "socket.create_connection", _blocked_network
    ), patch.object(socket.socket, "connect", _blocked_network), patch.object(
        socket.socket, "connect_ex", _blocked_network
    ):
        yield


def verify_c0_identity() -> tuple[dict[str, Any], tuple[str, ...]]:
    paths = {
        "loader_code": C0_LOADER_PATH,
        "router_code": C0_ROUTER_PATH,
        "runtime_config": C0_CONFIG_PATH,
        "intent_index": C0_INDEX_PATH,
        "embedding_matrix": C0_EMBEDDING_PATH,
    }
    observed = {name: sha256_file(path) for name, path in paths.items()}
    if observed != EXPECTED_C0_HASHES:
        raise TrackGEvaluationError("frozen C0 source or artifact identity has drifted")
    config = _read_json(C0_CONFIG_PATH)
    model = config.get("model") or {}
    if (
        config.get("aggregation") != "max"
        or config.get("aggregate_all_examples") is not True
        or config.get("allow_network_downloads") is not False
        or model.get("repo_id") != "sentence-transformers/all-mpnet-base-v2"
        or model.get("revision") != "e8c3b32edf5434bc2275fc9bab85f82640a19130"
        or model.get("local_files_only") is not True
    ):
        raise TrackGEvaluationError("frozen C0 runtime configuration has drifted")
    model_path = C0_ROOT / str(model["local_path"])
    if not model_path.is_dir():
        raise TrackGEvaluationError("frozen local MPNet snapshot is unavailable")
    index_rows = _read_jsonl(C0_INDEX_PATH)
    label_counts = Counter(str(row.get("final_semantic_label") or "") for row in index_rows)
    if len(index_rows) != 62 or len(label_counts) != 16 or "" in label_counts:
        raise TrackGEvaluationError("C0 approved index is not the exact 62-example/16-label index")
    import numpy as np

    with np.load(C0_EMBEDDING_PATH, allow_pickle=False) as payload:
        embeddings = payload["embeddings"]
        if embeddings.shape != (62, 768) or str(embeddings.dtype) != "float32":
            raise TrackGEvaluationError("C0 embedding matrix shape or dtype has drifted")
        artifact_revision = str(payload["model_revision"].item())
        artifact_repo = str(payload["repo_id"].item())
    if artifact_revision != model["revision"] or artifact_repo != model["repo_id"]:
        raise TrackGEvaluationError("C0 embedding metadata does not match the encoder identity")
    git_head = subprocess.run(
        ["git", "-C", str(C0_ROOT), "rev-parse", "HEAD"],
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()
    git_status = subprocess.run(
        ["git", "-C", str(C0_ROOT), "status", "--short"],
        check=True,
        capture_output=True,
        text=True,
    ).stdout
    identity = {
        "schema_version": "rq2-v2-stage4g-c0-identity-v1",
        "router_id": "C0_COSINE",
        "source_repository_root": str(C0_ROOT),
        "source_repository_head": git_head,
        "source_repository_clean_at_verification": git_status == "",
        "actual_source_paths": {name: str(path) for name, path in paths.items()},
        "code_hashes": {
            "production_loader_sha256": observed["loader_code"],
            "semantic_router_sha256": observed["router_code"],
        },
        "runtime_config_sha256": observed["runtime_config"],
        "intent_index_sha256": observed["intent_index"],
        "embedding_matrix_sha256": observed["embedding_matrix"],
        "approved_example_count": 62,
        "intent_label_count": 16,
        "intent_label_universe": sorted(label_counts),
        "intent_label_example_counts": dict(sorted(label_counts.items())),
        "embedding_shape": [62, 768],
        "embedding_dtype": "float32",
        "aggregation": "MAX",
        "encoder": {
            "repo_id": model["repo_id"],
            "revision": model["revision"],
            "local_path": str(model_path),
            "local_files_only": True,
        },
        "download_performed": False,
        "c0_modified": False,
    }
    return identity, tuple(sorted(label_counts))


def run_c0(
    rows: Sequence[Mapping[str, Any]], identity: Mapping[str, Any]
) -> dict[str, dict[str, Any]]:
    if str(C0_ROOT) not in sys.path:
        sys.path.insert(0, str(C0_ROOT))
    with offline_network_guard():
        from utils.production_intent_router import load_production_semantic_router

        module_path = Path(sys.modules[load_production_semantic_router.__module__].__file__).resolve()
        if module_path != C0_LOADER_PATH.resolve():
            raise TrackGEvaluationError("C0 loader resolved outside the authorized repository")
        runtime = load_production_semantic_router(str(C0_CONFIG_PATH))
        records = tuple(runtime.frozen_index.records)
        runtime_labels = {str(record.final_semantic_label) for record in records}
        if (
            runtime.aggregation_method != "max"
            or len(records) != 62
            or runtime_labels != set(identity["intent_label_universe"])
        ):
            raise TrackGEvaluationError("loaded C0 runtime identity differs from the verified assets")
        predictions: dict[str, dict[str, Any]] = {}
        for row in sorted(rows, key=_case_sort):
            current_page = None if row["current_page"] == "Other" else row["current_page"]
            prediction = runtime.predict(
                row["current_query"],
                current_page=current_page,
                top_k=62,
                candidate_limit=16,
                aggregate_all_examples=True,
            )
            result = prediction.result
            if result.status != "available" or not result.winning_label:
                raise TrackGEvaluationError(
                    f"frozen C0 inference unavailable for {row['annotation_case_id']}"
                )
            if result.winning_label not in runtime_labels:
                raise TrackGEvaluationError("C0 returned an intent outside its frozen universe")
            predictions[row["annotation_case_id"]] = {
                "predicted_intent": str(result.winning_label),
                "similarity_score": float(result.winning_score),
                "margin": float(result.margin) if result.margin is not None else None,
                "c0_current_page": current_page,
            }
    return predictions


def build_b1_mapping(
    rows: Sequence[Mapping[str, Any]],
    c0_predictions: Mapping[str, Mapping[str, Any]],
    label_universe: Sequence[str],
) -> list[dict[str, Any]]:
    mappings: list[dict[str, Any]] = []
    for intent in label_universe:
        intent_rows = [
            row
            for row in rows
            if c0_predictions[row["annotation_case_id"]]["predicted_intent"] == intent
        ]
        observed_weight = 0.5 * len(intent_rows)
        capabilities: dict[str, Any] = {}
        for key in LABEL_KEYS:
            positive = 0.5 * sum(bool(row[f"gold_{key}"]) for row in intent_rows)
            negative = observed_weight - positive
            prevalence = positive / observed_weight if observed_weight else None
            mapped = bool(prevalence is not None and prevalence > 0.5)
            if not observed_weight:
                reason = "UNOBSERVED_INTENT_CONSERVATIVE_NO"
            elif prevalence == 0.5:
                reason = "EXACT_TIE_MINIMUM_NECESSARY_NO"
            else:
                reason = "STRICTLY_GREATER_THAN_HALF" if mapped else "NOT_GREATER_THAN_HALF"
            capabilities[LABEL_NAMES[key]] = {
                "weighted_positive_count": positive,
                "weighted_negative_count": negative,
                "positive_prevalence": prevalence,
                "mapping": _yes_no(mapped),
                "mapping_boolean": mapped,
                "decision_reason": reason,
            }
        mappings.append(
            {
                "intent_id": intent,
                "observation_status": "OBSERVED" if observed_weight else "UNOBSERVED",
                "weighted_observed_family_count": observed_weight,
                "utterance_count": len(intent_rows),
                "capabilities": capabilities,
            }
        )
    return mappings


def _mapping_lookup(mappings: Sequence[Mapping[str, Any]]) -> dict[str, dict[str, bool]]:
    return {
        str(row["intent_id"]): {
            key: bool(row["capabilities"][LABEL_NAMES[key]]["mapping_boolean"])
            for key in LABEL_KEYS
        }
        for row in mappings
    }


def evaluate_b1(
    rows: Sequence[Mapping[str, Any]],
    gate_rows: Sequence[Mapping[str, Any]],
    identity: Mapping[str, Any],
    label_universe: Sequence[str],
) -> tuple[
    dict[str, Any],
    dict[str, Any],
    list[dict[str, Any]],
    list[dict[str, Any]],
    list[dict[str, Any]],
    list[dict[str, Any]],
]:
    answer_rows = [row for row in rows if row["gold_dialogue_action"] == "ANSWER"]
    gate_by_id = {row["annotation_case_id"]: row for row in gate_rows}
    extra_rows = [
        row
        for row in rows
        if row["gold_dialogue_action"] == "CLARIFY"
        and gate_by_id[row["annotation_case_id"]]["predicted_dialogue_action"] == "ANSWER"
    ]
    c0_predictions = run_c0([*answer_rows, *extra_rows], identity)
    fold_payloads: list[dict[str, Any]] = []
    core_rows: list[dict[str, Any]] = []
    fold_lookups: dict[str, dict[str, dict[str, bool]]] = {}
    for fold in FOLDS:
        training = [row for row in answer_rows if row["outer_fold"] != fold]
        validation = [row for row in answer_rows if row["outer_fold"] == fold]
        if len(training) != 48 or len(validation) != 16:
            raise TrackGEvaluationError("B1 outer-fold training/validation sizes have drifted")
        mappings = build_b1_mapping(training, c0_predictions, label_universe)
        lookup = _mapping_lookup(mappings)
        fold_lookups[fold] = lookup
        training_ids = sorted(row["annotation_case_id"] for row in training)
        fold_payloads.append(
            {
                "mapping_id": f"R2V2-B1-{fold}-TRAINING-COMPLEMENT",
                "validation_fold": fold,
                "training_folds": [value for value in FOLDS if value != fold],
                "training_case_count": len(training),
                "validation_case_count": len(validation),
                "training_annotation_id_set_sha256": canonical_sha256(training_ids),
                "mapping_method": "FAMILY_BALANCED_UTTERANCE_WEIGHT_0_5_STRICT_GT_HALF",
                "mappings": mappings,
            }
        )
        for row in validation:
            intent = c0_predictions[row["annotation_case_id"]]["predicted_intent"]
            mapped = lookup[intent]
            core_rows.append(
                {
                    **row,
                    "predicted_dialogue_action": "ANSWER",
                    **{f"predicted_{key}": mapped[key] for key in LABEL_KEYS},
                    "predicted_intent": intent,
                    "similarity_score": c0_predictions[row["annotation_case_id"]]["similarity_score"],
                    "margin": c0_predictions[row["annotation_case_id"]]["margin"],
                    "mapping_id": f"R2V2-B1-{fold}-TRAINING-COMPLEMENT",
                }
            )
    core_rows.sort(key=_case_sort)
    if len(core_rows) != 64 or len({row["annotation_case_id"] for row in core_rows}) != 64:
        raise TrackGEvaluationError("B1 OOF predictions are not exactly one per ANSWER case")
    core_by_id = {row["annotation_case_id"]: row for row in core_rows}
    end_rows: list[dict[str, Any]] = []
    for row in rows:
        gate_action = gate_by_id[row["annotation_case_id"]]["predicted_dialogue_action"]
        if gate_action == "CLARIFY":
            predicted = {key: False for key in LABEL_KEYS}
            core_executed = False
            intent = "NOT_APPLICABLE"
            score = margin = None
            mapping_id = "NOT_APPLICABLE"
        else:
            c0 = c0_predictions[row["annotation_case_id"]]
            intent = str(c0["predicted_intent"])
            mapped = fold_lookups[row["outer_fold"]][intent]
            predicted = mapped
            core_executed = True
            score = c0["similarity_score"]
            margin = c0["margin"]
            mapping_id = f"R2V2-B1-{row['outer_fold']}-TRAINING-COMPLEMENT"
        end_rows.append(
            {
                **row,
                "predicted_dialogue_action": gate_action,
                **{f"predicted_{key}": predicted[key] for key in LABEL_KEYS},
                "core_executed": core_executed,
                "predicted_intent": intent,
                "similarity_score": score,
                "margin": margin,
                "mapping_id": mapping_id,
            }
        )
    final_mappings = build_b1_mapping(answer_rows, c0_predictions, label_universe)
    final_lookup = _mapping_lookup(final_mappings)
    signature_counts = Counter(
        "".join("1" if final_lookup[intent][key] else "0" for key in LABEL_KEYS)
        for intent in label_universe
    )
    capability_yes_counts = {
        LABEL_NAMES[key]: sum(final_lookup[intent][key] for intent in label_universe)
        for key in LABEL_KEYS
    }
    unobserved = sum(row["observation_status"] == "UNOBSERVED" for row in final_mappings)
    fold_file = {
        "schema_version": "rq2-v2-stage4g-b1-fold-mappings-v1",
        "model_id": B1_MODEL_ID,
        "mapping_status": "OOF_TRAINING_COMPLEMENT_DERIVED",
        "outer_fold_count": 4,
        "utterance_weight": 0.5,
        "strict_positive_threshold": 0.5,
        "tie_behavior": "NO_MINIMUM_NECESSARY",
        "unseen_intent_behavior": "NO_CONSERVATIVE_DEFAULT",
        "folds": fold_payloads,
        "test_accessed": False,
    }
    final_file = {
        "schema_version": "rq2-v2-stage4g-b1-mapping-frozen-v1",
        "model_id": B1_MODEL_ID,
        "mapping_id": "R2V2-B1-C0-TO-CAPABILITY-DEV-V1",
        "mapping_status": "FROZEN_DEV_DERIVED_B1_MAPPING",
        "mapping_scope": "DEV_ONLY_NOT_FINAL_GENERALIZATION",
        "final_inference_authorized": False,
        "method": "FAMILY_BALANCED_UTTERANCE_WEIGHT_0_5_STRICT_GT_HALF",
        "utterance_weight": 0.5,
        "positive_threshold": "STRICTLY_GREATER_THAN_0.5",
        "tie_behavior": "NO_MINIMUM_NECESSARY",
        "unseen_intent_behavior": "NO_CONSERVATIVE_DEFAULT",
        "source_answer_utterance_count": 64,
        "source_family_count": 32,
        "intent_universe_count": 16,
        "unobserved_intent_count": unobserved,
        "capability_yes_counts": capability_yes_counts,
        "capability_signature_distribution": dict(sorted(signature_counts.items())),
        "c0_identity": {
            "router_id": "C0_COSINE",
            "intent_index_sha256": identity["intent_index_sha256"],
            "embedding_matrix_sha256": identity["embedding_matrix_sha256"],
            "encoder_revision": identity["encoder"]["revision"],
        },
        "mappings": final_mappings,
        "test_accessed": False,
    }
    intent_rows = [
        {
            **row,
            **c0_predictions[row["annotation_case_id"]],
        }
        for row in answer_rows
    ]
    errors = [row for row in core_rows if any(row[f"gold_{key}"] != row[f"predicted_{key}"] for key in LABEL_KEYS)]
    return fold_file, final_file, intent_rows, core_rows, end_rows, errors


def _capability_csv_value(row: Mapping[str, Any], prefix: str, key: str) -> str:
    if prefix == "gold" and row["gold_dialogue_action"] == "CLARIFY":
        return "NOT_APPLICABLE"
    if prefix == "predicted" and row["predicted_dialogue_action"] == "CLARIFY":
        return "NOT_APPLICABLE"
    return _yes_no(bool(row[f"{prefix}_{key}"]))


def _base_prediction_csv(row: Mapping[str, Any], model_id: str, scope: str) -> dict[str, Any]:
    return {
        "schema_version": "rq2-v2-stage4g-canonical-prediction-v1",
        "model_id": model_id,
        "evaluation_scope": scope,
        "annotation_case_id": row["annotation_case_id"],
        "scenario_family_id": row["scenario_family_id"],
        "dev_atomic_component_id": row["dev_atomic_component_id"],
        "outer_fold": row["outer_fold"],
        "current_page": row["current_page"],
        "gold_dialogue_action": row["gold_dialogue_action"],
        "predicted_dialogue_action": row["predicted_dialogue_action"],
        "gold_rag_required": _capability_csv_value(row, "gold", "rag"),
        "predicted_rag_required": _capability_csv_value(row, "predicted", "rag"),
        "gold_memory_required": _capability_csv_value(row, "gold", "memory"),
        "predicted_memory_required": _capability_csv_value(row, "predicted", "memory"),
        "gold_planning_required": _capability_csv_value(row, "gold", "planning"),
        "predicted_planning_required": _capability_csv_value(row, "predicted", "planning"),
    }


PREDICTION_FIELDS = (
    "schema_version",
    "model_id",
    "evaluation_scope",
    "annotation_case_id",
    "scenario_family_id",
    "dev_atomic_component_id",
    "outer_fold",
    "current_page",
    "gold_dialogue_action",
    "predicted_dialogue_action",
    "gold_rag_required",
    "predicted_rag_required",
    "gold_memory_required",
    "predicted_memory_required",
    "gold_planning_required",
    "predicted_planning_required",
)


def _write_prediction_files(
    clarification_rows: Sequence[Mapping[str, Any]],
    clarification_errors: Sequence[Mapping[str, Any]],
    b0_core: Sequence[Mapping[str, Any]],
    b0_end: Sequence[Mapping[str, Any]],
    b0_errors: Sequence[Mapping[str, Any]],
    b1_intents: Sequence[Mapping[str, Any]],
    b1_core: Sequence[Mapping[str, Any]],
    b1_end: Sequence[Mapping[str, Any]],
    b1_errors: Sequence[Mapping[str, Any]],
) -> None:
    clarification_fields = (
        "schema_version",
        "gate_id",
        "annotation_case_id",
        "scenario_family_id",
        "dev_atomic_component_id",
        "outer_fold",
        "current_page",
        "gold_dialogue_action",
        "predicted_dialogue_action",
        "matched_clause",
        "unresolved_reference",
        "plausible_visible_targets",
        "explicit_selection",
        "explicitly_unselected",
        "history_resolved",
        "activity_unidentified",
        "deadline_unidentified",
    )
    clarification_csv = [
        {
            **{name: row.get(name, "") for name in clarification_fields},
            "schema_version": "rq2-v2-stage4g-clarification-oof-v1",
            "gate_id": CLARIFICATION_GATE_ID,
        }
        for row in clarification_rows
    ]
    _write_csv(PACKAGE_ROOT / "clarification_oof_predictions_v1.csv", clarification_fields, clarification_csv)
    clarification_error_fields = (
        "annotation_case_id",
        "scenario_family_id",
        "outer_fold",
        "current_page",
        "gold_dialogue_action",
        "predicted_dialogue_action",
        "matched_clause",
    )
    _write_csv(
        PACKAGE_ROOT / "clarification_error_registry_v1.csv",
        clarification_error_fields,
        clarification_errors,
    )

    b0_extra = ("core_executed", "matched_rule_ids", "suppressed_rule_ids")
    b0_core_csv = []
    for row in b0_core:
        value = _base_prediction_csv(row, B0_MODEL_ID, "CONDITIONAL_CORE_OOF_DEV_ANSWER")
        value.update(
            {
                "core_executed": True,
                "matched_rule_ids": ";".join(row["matched_rule_ids"]),
                "suppressed_rule_ids": ";".join(row["suppressed_rule_ids"]),
            }
        )
        b0_core_csv.append(value)
    b0_end_csv = []
    for row in b0_end:
        value = _base_prediction_csv(row, B0_MODEL_ID, "END_TO_END_OOF_DEV_ALL")
        value.update(
            {
                "core_executed": str(bool(row["core_executed"])).lower(),
                "matched_rule_ids": ";".join(row["matched_rule_ids"]),
                "suppressed_rule_ids": ";".join(row["suppressed_rule_ids"]),
            }
        )
        b0_end_csv.append(value)
    _write_csv(PACKAGE_ROOT / "b0_core_oof_predictions_v1.csv", (*PREDICTION_FIELDS, *b0_extra), b0_core_csv)
    _write_csv(PACKAGE_ROOT / "b0_end_to_end_oof_predictions_v1.csv", (*PREDICTION_FIELDS, *b0_extra), b0_end_csv)

    error_fields = (
        "model_id",
        "evaluation_scope",
        "annotation_case_id",
        "scenario_family_id",
        "outer_fold",
        "current_page",
        "false_negative_capabilities",
        "false_positive_capabilities",
    )
    def error_rows(model_id: str, source: Sequence[Mapping[str, Any]]) -> list[dict[str, Any]]:
        values = []
        for row in source:
            values.append(
                {
                    "model_id": model_id,
                    "evaluation_scope": "CONDITIONAL_CORE_OOF_DEV_ANSWER",
                    "annotation_case_id": row["annotation_case_id"],
                    "scenario_family_id": row["scenario_family_id"],
                    "outer_fold": row["outer_fold"],
                    "current_page": row["current_page"],
                    "false_negative_capabilities": ";".join(
                        LABEL_NAMES[key]
                        for key in LABEL_KEYS
                        if row[f"gold_{key}"] and not row[f"predicted_{key}"]
                    ),
                    "false_positive_capabilities": ";".join(
                        LABEL_NAMES[key]
                        for key in LABEL_KEYS
                        if not row[f"gold_{key}"] and row[f"predicted_{key}"]
                    ),
                }
            )
        return values
    _write_csv(PACKAGE_ROOT / "b0_error_registry_v1.csv", error_fields, error_rows(B0_MODEL_ID, b0_errors))

    intent_fields = (
        "schema_version",
        "annotation_case_id",
        "scenario_family_id",
        "outer_fold",
        "current_page",
        "c0_current_page",
        "predicted_intent",
        "similarity_score",
        "margin",
        "c0_router_id",
        "c0_identity_version",
    )
    intent_csv = []
    for row in b1_intents:
        intent_csv.append(
            {
                "schema_version": "rq2-v2-stage4g-b1-intent-prediction-v1",
                "annotation_case_id": row["annotation_case_id"],
                "scenario_family_id": row["scenario_family_id"],
                "outer_fold": row["outer_fold"],
                "current_page": row["current_page"],
                "c0_current_page": row["c0_current_page"] or "",
                "predicted_intent": row["predicted_intent"],
                "similarity_score": f"{row['similarity_score']:.12f}",
                "margin": "" if row["margin"] is None else f"{row['margin']:.12f}",
                "c0_router_id": "C0_COSINE",
                "c0_identity_version": "62x768_MPNet_MAX_e8c3b32e",
            }
        )
    _write_csv(PACKAGE_ROOT / "b1_intent_predictions_dev_v1.csv", intent_fields, intent_csv)

    b1_extra = ("core_executed", "predicted_intent", "similarity_score", "margin", "mapping_id")
    def b1_csv(source: Sequence[Mapping[str, Any]], scope: str) -> list[dict[str, Any]]:
        values = []
        for row in source:
            value = _base_prediction_csv(row, B1_MODEL_ID, scope)
            value.update(
                {
                    "core_executed": str(bool(row.get("core_executed", True))).lower(),
                    "predicted_intent": row["predicted_intent"],
                    "similarity_score": "" if row["similarity_score"] is None else f"{row['similarity_score']:.12f}",
                    "margin": "" if row["margin"] is None else f"{row['margin']:.12f}",
                    "mapping_id": row["mapping_id"],
                }
            )
            values.append(value)
        return values
    _write_csv(
        PACKAGE_ROOT / "b1_core_oof_predictions_v1.csv",
        (*PREDICTION_FIELDS, *b1_extra),
        b1_csv(b1_core, "CONDITIONAL_CORE_OOF_DEV_ANSWER"),
    )
    _write_csv(
        PACKAGE_ROOT / "b1_end_to_end_oof_predictions_v1.csv",
        (*PREDICTION_FIELDS, *b1_extra),
        b1_csv(b1_end, "END_TO_END_OOF_DEV_ALL"),
    )
    _write_csv(PACKAGE_ROOT / "b1_error_registry_v1.csv", error_fields, error_rows(B1_MODEL_ID, b1_errors))


def _verification_summary() -> dict[str, Any]:
    path = PACKAGE_ROOT / "verification_report_v1.json"
    if not path.is_file():
        return {"status": "PENDING", "tests_run": 0, "passed": 0, "failed": 0}
    value = _read_json(path)
    required = {"status", "tests_run", "passed", "failed", "command"}
    if not isinstance(value, dict) or not required.issubset(value):
        raise TrackGEvaluationError("verification report is malformed")
    return value


def _render_markdown(metrics: Mapping[str, Any], final_mapping: Mapping[str, Any]) -> str:
    clarification = metrics["clarification"]["selected_oof"]
    b0 = metrics["b0"]
    b1 = metrics["b1"]
    c0 = metrics["c0_identity"]
    verification = metrics["verification"]
    return f"""# RQ2-V2 Stage 4G DEV Results

Status: `{metrics['status']}`

These are DEV selection and calibration estimates. They are not independent TEST results and do not establish final generalization performance.

## Shared clarification gate

- Gate: `{CLARIFICATION_GATE_ID}`
- Selected configuration: `{metrics['clarification']['selected_config_id']}`
- CLARIFY precision / recall / F1: `{clarification['clarify']['precision']:.6f}` / `{clarification['clarify']['recall']:.6f}` / `{clarification['clarify']['f1']:.6f}`
- Dialogue-action accuracy: `{clarification['dialogue_action_accuracy']:.6f}`
- False-CLARIFY rate on Gold ANSWER: `{clarification['false_clarify_rate_on_gold_answer']:.6f}`
- Family-both-utterances-correct: `{clarification['family_both_utterances_correct']['rate']:.6f}`

## B0 rule baseline

- Ruleset: `{metrics['b0']['identity']['ruleset_id']}`
- Conditional core Macro-F1 / Micro-F1: `{b0['conditional_core']['macro_f1']:.6f}` / `{b0['conditional_core']['micro_f1']:.6f}`
- Conditional exact capability-set match: `{b0['conditional_core']['exact_capability_set_match']:.6f}`
- End-to-end full-route exact match: `{b0['end_to_end']['full_route_signature_exact_match']:.6f}`
- The Stage 1 B0 rules and configuration were not tuned or modified.

## Frozen historical C0 identity

- Router: `C0_COSINE`; approved examples: `{c0['approved_example_count']}`; labels: `{c0['intent_label_count']}`
- Embeddings: `{c0['embedding_shape'][0]} x {c0['embedding_shape'][1]} {c0['embedding_dtype']}`; aggregation: `{c0['aggregation']}`
- Encoder: `{c0['encoder']['repo_id']}` at `{c0['encoder']['revision']}`
- Intent index SHA-256: `{c0['intent_index_sha256']}`
- Embedding matrix SHA-256: `{c0['embedding_matrix_sha256']}`

## B1 legacy-intent calibration

- Conditional core Macro-F1 / Micro-F1: `{b1['conditional_core']['macro_f1']:.6f}` / `{b1['conditional_core']['micro_f1']:.6f}`
- Conditional exact capability-set match: `{b1['conditional_core']['exact_capability_set_match']:.6f}`
- End-to-end full-route exact match: `{b1['end_to_end']['full_route_signature_exact_match']:.6f}`
- Final mapping status: `{final_mapping['mapping_status']}`
- Capability YES counts across 16 intents: `{json.dumps(final_mapping['capability_yes_counts'], sort_keys=True)}`
- Capability-signature distribution: `{json.dumps(final_mapping['capability_signature_distribution'], sort_keys=True)}`
- Unobserved intents: `{final_mapping['unobserved_intent_count']}`

## Stratification and governance

- Page-stratified metrics are recorded in `track_g_metrics_v1.json`.
- Writer A/B metrics: `NOT_AVAILABLE_AUTHORIZED_WRITER_JOIN_ABSENT`. The frozen DEV inputs intentionally omit writer identity, so no writer label was inferred from IDs.
- Provider calls: `0`; network access: `false`; downloads: `0`; C0 modifications: `0`.
- Held-out data access: `0`; RQ3 work: `0`; B2/B3/P1 work: `0`.

## Verification

- Status: `{verification['status']}`
- Tests: `{verification['passed']}/{verification['tests_run']} PASS`; failures: `{verification['failed']}`
"""


def _render_status(metrics: Mapping[str, Any]) -> str:
    verification = metrics["verification"]
    return f"""# RQ2-V2 Stage 4G Status

`{metrics['status']}`

- Scope completed: shared clarification gate, unchanged B0 DEV evaluation, frozen historical C0 DEV inference, and cross-validated B1 DEV calibration.
- Scientific interpretation: DEV selection/calibration estimate only; not independent generalization evidence.
- Starting HEAD: `1838a5d85db2dcaeba481c7404c36cbfbc94215e`
- Tests: `{verification['passed']}/{verification['tests_run']} PASS`; failures: `{verification['failed']}`; status: `{verification['status']}`.
- Provider calls: `0`; network access: `false`; downloads: `0`.
- Held-out access: `0`; C0 modifications: `0`; B0 modifications: `0`.
- Writer A/B metrics were not computed because the required separately authorized audit-only join is absent from the allowed DEV inputs.
- Stop boundary: do not proceed to held-out evaluation or another Track.
"""


def generate_outputs() -> dict[str, Any]:
    if Path.cwd().resolve() != PROJECT_ROOT.resolve():
        raise TrackGEvaluationError(f"runner must execute from the authorized worktree root: {PROJECT_ROOT}")
    rows, source_hashes = load_dev_rows()
    candidate_payload = _read_json(CANDIDATE_PATH)
    clarification_frozen, clarification_rows, clarification_errors = evaluate_clarification(
        rows, candidate_payload
    )
    b0_frozen, b0_core, b0_end, b0_errors = evaluate_b0(rows, clarification_rows)
    c0_identity, label_universe = verify_c0_identity()
    (
        b1_fold_mappings,
        b1_final_mapping,
        b1_intents,
        b1_core,
        b1_end,
        b1_errors,
    ) = evaluate_b1(rows, clarification_rows, c0_identity, label_universe)

    verification = _verification_summary()
    status = (
        "READY_FOR_STAGE_4G_DEV_REVIEW"
        if verification.get("status") == "PASS" and verification.get("failed") == 0
        else "IMPLEMENTED_AWAITING_FINAL_VERIFICATION"
    )
    metrics = {
        "schema_version": "rq2-v2-stage4g-track-metrics-v1",
        "status": status,
        "scientific_interpretation": "DEV_SELECTION_AND_CALIBRATION_ESTIMATE_NOT_INDEPENDENT_TEST",
        "source_hashes": source_hashes,
        "clarification": {
            "selected_config_id": clarification_frozen["selected_config_id"],
            "selected_config_sha256": clarification_frozen["selected_config_sha256"],
            "candidate_metrics": clarification_frozen["candidate_metrics"],
            "selected_oof": clarification_frozen["selected_oof_metrics"],
        },
        "b0": {
            "identity": b0_frozen,
            "conditional_core": core_metrics(b0_core),
            "end_to_end": end_to_end_metrics(b0_end),
            "conditional_error_count": len(b0_errors),
        },
        "c0_identity": c0_identity,
        "b1": {
            "conditional_core": core_metrics(b1_core),
            "end_to_end": end_to_end_metrics(b1_end),
            "conditional_error_count": len(b1_errors),
            "final_mapping_status": b1_final_mapping["mapping_status"],
            "final_mapping_distribution": b1_final_mapping["capability_signature_distribution"],
            "unobserved_intent_count": b1_final_mapping["unobserved_intent_count"],
        },
        "writer_metrics": {
            "status": "NOT_AVAILABLE_AUTHORIZED_WRITER_JOIN_ABSENT",
            "inferred_from_identifiers": False,
        },
        "verification": verification,
        "governance": {
            "authorized_dev_input_files": sorted(EXPECTED_DEV_HASHES),
            "test_identifiers_accessed": 0,
            "test_files_accessed": 0,
            "test_escrow_accessed": False,
            "downloads_directory_test_search_performed": False,
            "provider_call_count": 0,
            "network_access": False,
            "download_count": 0,
            "c0_modified": False,
            "b0_modified": False,
            "b2_or_b3_trained": False,
            "llm_called": False,
            "p1_implemented": False,
            "rq3_executed": False,
        },
        "pipeline_code_sha256": sha256_file(Path(__file__)),
    }

    _write_json(PACKAGE_ROOT / "clarification_gate_frozen_v1.json", clarification_frozen)
    _write_json(PACKAGE_ROOT / "b0_frozen_config_v1.json", b0_frozen)
    _write_json(PACKAGE_ROOT / "c0_identity_frozen_v1.json", c0_identity)
    _write_json(PACKAGE_ROOT / "b1_fold_mappings_v1.json", b1_fold_mappings)
    _write_json(PACKAGE_ROOT / "b1_mapping_frozen_v1.json", b1_final_mapping)
    _write_prediction_files(
        clarification_rows,
        clarification_errors,
        b0_core,
        b0_end,
        b0_errors,
        b1_intents,
        b1_core,
        b1_end,
        b1_errors,
    )
    _write_json(PACKAGE_ROOT / "track_g_metrics_v1.json", metrics)
    (PACKAGE_ROOT / "TRACK_G_DEV_RESULTS.md").write_text(
        _render_markdown(metrics, b1_final_mapping), encoding="utf-8", newline="\n"
    )
    (PACKAGE_ROOT / "STATUS.md").write_text(
        _render_status(metrics), encoding="utf-8", newline="\n"
    )
    manifest_names = sorted(
        path.name
        for path in PACKAGE_ROOT.iterdir()
        if path.is_file()
        and path.name not in {"OUTPUT_SHA256_MANIFEST.json"}
        and path.suffix not in {".pyc"}
    )
    output_manifest = {
        "schema_version": "rq2-v2-stage4g-output-sha256-manifest-v1",
        "files": [
            {
                "name": name,
                "sha256": sha256_file(PACKAGE_ROOT / name),
                "size_bytes": (PACKAGE_ROOT / name).stat().st_size,
            }
            for name in manifest_names
        ],
        "restricted_assets_included": False,
        "model_or_embedding_assets_included": False,
    }
    _write_json(PACKAGE_ROOT / "OUTPUT_SHA256_MANIFEST.json", output_manifest)
    return {
        "status": status,
        "clarification_selected_config": clarification_frozen["selected_config_id"],
        "clarification_f1": clarification_frozen["selected_oof_metrics"]["clarify"]["f1"],
        "b0_macro_f1": metrics["b0"]["conditional_core"]["macro_f1"],
        "b1_macro_f1": metrics["b1"]["conditional_core"]["macro_f1"],
        "unobserved_intents": b1_final_mapping["unobserved_intent_count"],
        "output_directory": str(PACKAGE_ROOT),
    }


def main() -> int:
    result = generate_outputs()
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())


__all__ = [
    "EXPECTED_B0_HASHES",
    "EXPECTED_C0_HASHES",
    "EXPECTED_DEV_HASHES",
    "FOLDS",
    "PREDICTION_FIELDS",
    "TrackGEvaluationError",
    "build_b1_mapping",
    "canonical_sha256",
    "generate_outputs",
    "load_dev_rows",
    "offline_network_guard",
    "sha256_file",
    "verify_c0_identity",
]
