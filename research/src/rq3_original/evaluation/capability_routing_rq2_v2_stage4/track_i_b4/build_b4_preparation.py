"""Build the offline-only RQ2-V2 Stage 4I B4 preparation artifacts.

This module reads only the frozen Stage 4-0 DEV protocol plus the explicitly
authorized, local MPNet snapshot.  It does not import a provider SDK, open a
network connection, or execute a B4 prediction.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import importlib.metadata
import json
import math
import os
from pathlib import Path
import textwrap
from typing import Any, Iterable, Mapping, Sequence


SCRIPT_DIR = Path(__file__).resolve().parent
DEV_PROTOCOL_DIR = SCRIPT_DIR.parent / "dev_protocol"

FOLDS = tuple(f"DEV-CV-FOLD-{index}" for index in range(1, 5))
SIGNATURES = tuple(f"{value:03b}" for value in range(8))
SEMANTIC_FIELDS = (
    "current_query",
    "current_page",
    "dashboard_context",
    "visible_conversation_history",
)
LABEL_FIELDS = (
    "rag_required",
    "memory_required",
    "planning_required",
)

ENCODER_REPO_ID = "sentence-transformers/all-mpnet-base-v2"
ENCODER_REVISION = "e8c3b32edf5434bc2275fc9bab85f82640a19130"
ENCODER_ROOT = Path(
    "/Users/liuming/Downloads/duteaiapp_cfull_semantic_integrated_v1_副本3"
)
ENCODER_LOCAL_PATH = (
    ENCODER_ROOT
    / "semantic_runtime/models/all-mpnet-base-v2"
    / ENCODER_REVISION
)
ENCODER_CONFIG_PATH = (
    ENCODER_ROOT / "semantic_runtime/config/semantic_routing_config.json"
)
ENCODER_FILE_HASHES = {
    "config.json": "d46a3e04ded82bba22528424480697d394eeda6a27484e08c5bb2bdf5906cfa0",
    "model.safetensors": "78c0197b6159d92658e319bc1d72e4c73a9a03dd03815e70e555c5ef05615658",
    "tokenizer.json": "b8be2c30ba5dd723a6d5ee26d013da103d5408d92ddcb23747622f9e48f1d842",
}

EXPECTED_DEV_INPUT_HASHES = {
    "dev_capability_gold_v1.csv": "8d3422198a99422b3e314c60819f3553ff27cd42394ed2d9f68c0eb3ce858b56",
    "dev_atomic_group_map_v1.csv": "f1ac8973c590155ee3730de194b4c2afd6d05531744bef70a163be2428d4bd6f",
    "dev_cv_folds_v1.csv": "2a3a4161c81bddfcfe51b238ac5940c64df87a25beed26e54671b64c76c5ab46",
    "DEV_SOURCE_MANIFEST.json": "34a46785139435c757db6368540d264522834b57624ed2e6dd7ec0d07cd40e61",
    "STAGE4_DEV_PROTOCOL.md": "f4573b956dcfb39509fba7b1a93bf2fd89bbdf63235b0b2341bb1d3ce083fa66",
}
DEV_SOURCE_PACKAGE_SHA256 = (
    "accc086f91a8c8a7e1e94ce1ab45f5de5266d38265b1c2a59ff3571ee0218066"
)

EXISTING_PROVIDER = "OpenAI Chat Completions"
EXISTING_MODEL_IDENTIFIER = "gpt-4o-mini"
MODEL_AUTHORIZATION_STATUS = "REQUIRES_DIRECT_USER_AUTHORIZATION_FOR_B4_EXECUTION"

PROMPT_TEMPLATE = """You are the B4 conditional capability router for an educational chatbot. The shared clarification gate has already predicted ANSWER for this case.

Apply the minimum-necessary principle: mark a capability true only when correct handling of the request minimally requires that capability. More than one capability may be true at the same time.

RAG (rag_required): true only when correct answering minimally requires course knowledge or external knowledge that is not already present in the visible input. Information already stated in the current query, page, dashboard context, or visible conversation history does not require RAG merely because it concerns the course.

Memory (memory_required): true only when student-specific prior information that is absent from the visible conversation history must be retrieved. Visible conversation history is short-term visible input and is not long-term Memory.

Planning (planning_required): true only when the request requires an actionable order, schedule, prioritisation, or concrete next-step sequence. Explanation, interpretation, comparison, or advice without an ordered or prioritised action sequence does not by itself require Planning.

The only semantic inputs are current_query, current_page, dashboard_context, and visible_conversation_history. Base the decision solely on the content of those four fields; no other metadata is an input.

Return only one JSON object with exactly these three keys: rag_required, memory_required, planning_required. Every value must be a JSON boolean. Do not add Markdown, prose, an explanation, or any other field.
"""

RESPONSE_SCHEMA: dict[str, Any] = {
    "$schema": "https://json-schema.org/draft/2020-12/schema",
    "title": "RQ2-V2 B4 Capability Routing Response V1",
    "type": "object",
    "additionalProperties": False,
    "minProperties": 3,
    "maxProperties": 3,
    "required": list(LABEL_FIELDS),
    "properties": {
        "rag_required": {"type": "boolean"},
        "memory_required": {"type": "boolean"},
        "planning_required": {"type": "boolean"},
    },
}

PROHIBITED_PROMPT_FIELD_NAMES = (
    "annotation_case_id",
    "scenario_family_id",
    "dev_atomic_component_id",
    "dev_contrast_group_id",
    "dev_contrast_axis",
    "fold_id",
    "fold_role",
    "writer_id",
    "writer",
    "design_label",
    "design_target",
    "expected_output",
    "validation_gold",
    "model_prediction",
    "contrast_metadata",
    "partition",
)


def canonical_json(value: Any) -> str:
    """Return the canonical UTF-8 JSON representation used for hashing."""

    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )


def rendered_json(value: Any) -> str:
    """Render compact JSON while preserving the frozen semantic/key order."""

    return json.dumps(value, ensure_ascii=False, separators=(",", ":"))


def parse_strict_response(raw_text: str) -> dict[str, bool]:
    """Parse one B4 response without extraction, coercion, or repair."""

    def reject_duplicate_keys(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
        result: dict[str, Any] = {}
        for key, value in pairs:
            if key in result:
                raise ValueError(f"Duplicate response field: {key}")
            result[key] = value
        return result

    try:
        parsed = json.loads(raw_text, object_pairs_hook=reject_duplicate_keys)
    except (json.JSONDecodeError, ValueError) as error:
        raise ValueError("Response is not one valid duplicate-free JSON value") from error
    if not isinstance(parsed, dict):
        raise ValueError("Response must be a JSON object")
    if set(parsed) != set(LABEL_FIELDS) or len(parsed) != len(LABEL_FIELDS):
        raise ValueError("Response must contain exactly the three capability fields")
    if any(type(parsed[field]) is not bool for field in LABEL_FIELDS):
        raise ValueError("Every capability value must be a JSON boolean")
    return {field: parsed[field] for field in LABEL_FIELDS}


def sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def canonical_sha256(value: Any) -> str:
    return sha256_bytes(canonical_json(value).encode("utf-8"))


def write_text(path: Path, content: str) -> None:
    path.write_text(content, encoding="utf-8", newline="\n")


def write_json(path: Path, value: Any) -> None:
    write_text(
        path,
        json.dumps(value, ensure_ascii=False, sort_keys=True, indent=2) + "\n",
    )


def read_csv(path: Path) -> list[dict[str, str]]:
    with path.open("r", encoding="utf-8", newline="") as handle:
        return list(csv.DictReader(handle))


def verify_dev_sources() -> dict[str, Any]:
    verified_files: list[dict[str, Any]] = []
    for name, expected_hash in EXPECTED_DEV_INPUT_HASHES.items():
        path = DEV_PROTOCOL_DIR / name
        if not path.is_file():
            raise FileNotFoundError(f"Required frozen DEV input is missing: {path}")
        observed_hash = sha256_file(path)
        if observed_hash != expected_hash:
            raise RuntimeError(
                f"Frozen DEV input hash mismatch for {name}: "
                f"expected {expected_hash}, observed {observed_hash}"
            )
        verified_files.append(
            {
                "name": name,
                "sha256": observed_hash,
                "size_bytes": path.stat().st_size,
            }
        )

    source_manifest = json.loads(
        (DEV_PROTOCOL_DIR / "DEV_SOURCE_MANIFEST.json").read_text(encoding="utf-8")
    )
    source_package_hash = source_manifest["dev_source_package"]["sha256"]
    if source_package_hash != DEV_SOURCE_PACKAGE_SHA256:
        raise RuntimeError("Frozen DEV source-package identity does not match")
    governance = source_manifest["governance"]
    required_governance = {
        "test_identifier_retained": False,
        "test_query_or_gold_accessed": False,
        "test_record_retained": False,
    }
    for field, expected in required_governance.items():
        if governance.get(field) is not expected:
            raise RuntimeError(f"Frozen DEV governance check failed: {field}")

    return {
        "schema_version": "rq2-v2-stage4-i-b4-source-verification-v1",
        "status": "PASS",
        "authorized_input_directory": str(DEV_PROTOCOL_DIR),
        "dev_source_package_sha256": source_package_hash,
        "verified_files": verified_files,
        "governance": required_governance,
        "input_scope": "FROZEN_STAGE4_0_DEV_PROTOCOL_ONLY",
    }


def verify_encoder_snapshot() -> dict[str, Any]:
    if not ENCODER_LOCAL_PATH.is_dir():
        raise FileNotFoundError(f"Local MPNet snapshot is missing: {ENCODER_LOCAL_PATH}")
    verified_files: list[dict[str, Any]] = []
    for name, expected_hash in ENCODER_FILE_HASHES.items():
        path = ENCODER_LOCAL_PATH / name
        observed_hash = sha256_file(path)
        if observed_hash != expected_hash:
            raise RuntimeError(
                f"Frozen MPNet file hash mismatch for {name}: "
                f"expected {expected_hash}, observed {observed_hash}"
            )
        verified_files.append(
            {
                "name": name,
                "sha256": observed_hash,
                "size_bytes": path.stat().st_size,
            }
        )

    runtime_config = json.loads(ENCODER_CONFIG_PATH.read_text(encoding="utf-8"))
    model_config = runtime_config.get("model") or {}
    expected_model_config = {
        "repo_id": ENCODER_REPO_ID,
        "revision": ENCODER_REVISION,
        "local_path": (
            "semantic_runtime/models/all-mpnet-base-v2/" + ENCODER_REVISION
        ),
        "local_files_only": True,
        "device": "cpu",
    }
    for field, expected in expected_model_config.items():
        if model_config.get(field) != expected:
            raise RuntimeError(f"Local MPNet runtime identity mismatch: {field}")
    if runtime_config.get("allow_network_downloads") is not False:
        raise RuntimeError("Local MPNet config does not prohibit downloads")

    return {
        "schema_version": "rq2-v2-stage4-i-b4-encoder-identity-v1",
        "repo_id": ENCODER_REPO_ID,
        "revision": ENCODER_REVISION,
        "local_path": str(ENCODER_LOCAL_PATH),
        "local_files_only": True,
        "network_downloads_allowed": False,
        "device": "cpu",
        "purpose": "DETERMINISTIC_FEW_SHOT_EXAMPLE_SELECTION_ONLY",
        "prohibited_purpose": "B4_PREDICTION",
        "verified_files": verified_files,
        "runtime_config_path": str(ENCODER_CONFIG_PATH),
        "runtime_config_sha256": sha256_file(ENCODER_CONFIG_PATH),
    }


def load_dev_inputs() -> tuple[
    list[dict[str, Any]],
    dict[str, dict[str, str]],
    dict[str, dict[str, str]],
]:
    raw_gold = read_csv(DEV_PROTOCOL_DIR / "dev_capability_gold_v1.csv")
    atomic_rows = read_csv(DEV_PROTOCOL_DIR / "dev_atomic_group_map_v1.csv")
    fold_rows = read_csv(DEV_PROTOCOL_DIR / "dev_cv_folds_v1.csv")

    if len(raw_gold) != 72:
        raise RuntimeError(f"Expected 72 DEV utterances, observed {len(raw_gold)}")
    if {row["partition"] for row in raw_gold} != {"DEV"}:
        raise RuntimeError("Non-DEV partition value found in authorized source")

    atomic_by_id = {row["annotation_case_id"]: row for row in atomic_rows}
    if len(atomic_by_id) != 72:
        raise RuntimeError("Atomic map must contain exactly 72 unique DEV cases")

    fold_by_case_and_fold: dict[tuple[str, str], dict[str, str]] = {}
    for row in fold_rows:
        key = (row["annotation_case_id"], row["fold_id"])
        if key in fold_by_case_and_fold:
            raise RuntimeError(f"Duplicate fold record: {key}")
        fold_by_case_and_fold[key] = row
    if len(fold_by_case_and_fold) != 72 * 4:
        raise RuntimeError("Fold map must contain 72 cases across four folds")

    rows: list[dict[str, Any]] = []
    for row in raw_gold:
        annotation_id = row["annotation_case_id"]
        if annotation_id not in atomic_by_id:
            raise RuntimeError(f"Missing atomic metadata for {annotation_id}")
        try:
            visible_history = json.loads(row["visible_conversation_history"])
        except json.JSONDecodeError as error:
            raise RuntimeError(f"Invalid visible history for {annotation_id}") from error
        if not isinstance(visible_history, list):
            raise RuntimeError(f"Visible history must be a JSON list for {annotation_id}")

        action = row["final_dialogue_action"]
        if action not in {"ANSWER", "CLARIFY"}:
            raise RuntimeError(f"Unexpected dialogue action for {annotation_id}: {action}")
        if action == "ANSWER":
            label_output: dict[str, bool] | None = {
                "rag_required": _parse_yes_no(row["final_rag_required"]),
                "memory_required": _parse_yes_no(row["final_memory_required"]),
                "planning_required": _parse_yes_no(row["final_planning_required"]),
            }
            signature = "".join(
                "1" if label_output[field] else "0" for field in LABEL_FIELDS
            )
            if atomic_by_id[annotation_id]["final_family_routing_signature"] != signature:
                raise RuntimeError(f"Routing signature mismatch for {annotation_id}")
        else:
            if {
                row["final_rag_required"],
                row["final_memory_required"],
                row["final_planning_required"],
            } != {"NOT_APPLICABLE"}:
                raise RuntimeError(
                    f"CLARIFY case must have NOT_APPLICABLE capabilities: {annotation_id}"
                )
            label_output = None
            signature = "CLARIFY"

        semantic_input = {
            "current_query": row["current_query"],
            "current_page": row["current_page"],
            "dashboard_context": row["dashboard_context"],
            "visible_conversation_history": visible_history,
        }
        rows.append(
            {
                "annotation_case_id": annotation_id,
                "scenario_family_id": row["scenario_family_id"],
                "dev_atomic_component_id": atomic_by_id[annotation_id][
                    "dev_atomic_component_id"
                ],
                "dialogue_action": action,
                "signature": signature,
                "semantic_input": semantic_input,
                "label_output": label_output,
                "semantic_text": canonical_json(semantic_input),
            }
        )

    answer_rows = [row for row in rows if row["dialogue_action"] == "ANSWER"]
    if len(answer_rows) != 64:
        raise RuntimeError(f"Expected 64 ANSWER utterances, observed {len(answer_rows)}")
    signature_counts = {
        signature: sum(row["signature"] == signature for row in answer_rows)
        for signature in SIGNATURES
    }
    if set(signature_counts.values()) != {8}:
        raise RuntimeError(f"Unexpected ANSWER signature counts: {signature_counts}")

    validation_fold_by_id: dict[str, str] = {}
    for row in rows:
        annotation_id = row["annotation_case_id"]
        validation_folds = [
            fold
            for fold in FOLDS
            if fold_by_case_and_fold[(annotation_id, fold)]["fold_role"] == "VALIDATION"
        ]
        if len(validation_folds) != 1:
            raise RuntimeError(f"Case must validate in exactly one fold: {annotation_id}")
        validation_fold_by_id[annotation_id] = validation_folds[0]

    return rows, atomic_by_id, {
        f"{annotation_id}|{fold}": fold_by_case_and_fold[(annotation_id, fold)]
        for annotation_id in sorted(validation_fold_by_id)
        for fold in FOLDS
    }


def _parse_yes_no(value: str) -> bool:
    if value == "YES":
        return True
    if value == "NO":
        return False
    raise RuntimeError(f"Expected YES or NO, observed {value!r}")


def load_embeddings(
    answer_rows: Sequence[Mapping[str, Any]],
    encoder_identity: dict[str, Any],
) -> dict[str, Any]:
    """Encode authorized semantic fields from the local snapshot only."""

    os.environ["HF_HUB_OFFLINE"] = "1"
    os.environ["TRANSFORMERS_OFFLINE"] = "1"
    os.environ["HF_DATASETS_OFFLINE"] = "1"
    os.environ["TOKENIZERS_PARALLELISM"] = "false"
    os.environ["JOBLIB_MULTIPROCESSING"] = "0"
    os.environ["LOKY_MAX_CPU_COUNT"] = "1"

    import numpy as np
    import torch
    from sentence_transformers import SentenceTransformer

    torch.manual_seed(0)
    torch.set_num_threads(1)
    torch.use_deterministic_algorithms(True)

    ordered_rows = sorted(answer_rows, key=lambda row: row["annotation_case_id"])
    model = SentenceTransformer(
        str(ENCODER_LOCAL_PATH),
        device="cpu",
        local_files_only=True,
        trust_remote_code=False,
    )
    vectors = model.encode(
        [row["semantic_text"] for row in ordered_rows],
        batch_size=8,
        show_progress_bar=False,
        convert_to_numpy=True,
        normalize_embeddings=True,
    )
    vectors = np.asarray(vectors, dtype=np.float64)
    if vectors.shape[0] != 64:
        raise RuntimeError(f"Expected 64 MPNet embeddings, observed {vectors.shape}")
    if not np.isfinite(vectors).all():
        raise RuntimeError("MPNet produced a non-finite embedding")

    encoder_identity["embedding_dimension"] = int(vectors.shape[1])
    encoder_identity["sentence_transformers_version"] = importlib.metadata.version(
        "sentence-transformers"
    )
    encoder_identity["torch_version"] = torch.__version__
    encoder_identity["embedding_serialization"] = (
        "canonical JSON of exactly current_query, current_page, dashboard_context, "
        "and parsed visible_conversation_history"
    )
    encoder_identity["utterance_embedding_normalization"] = "L2"
    encoder_identity["family_representation"] = (
        "L2-normalized mean of the family's two L2-normalized utterance embeddings"
    )
    encoder_identity["family_selection_distance"] = "cosine distance to signature-family centroid"

    return {
        row["annotation_case_id"]: vectors[index]
        for index, row in enumerate(ordered_rows)
    }


def _normalize(vector: Any) -> Any:
    import numpy as np

    norm = float(np.linalg.norm(vector))
    if norm == 0.0:
        raise RuntimeError("Cannot normalize zero vector")
    return vector / norm


def select_signature_examples(
    eligible_rows: Sequence[Mapping[str, Any]],
    embeddings: Mapping[str, Any],
    selection_scope: str,
) -> list[dict[str, Any]]:
    """Select one family medoid and one lower-median-length utterance per signature."""

    import numpy as np

    selected: list[dict[str, Any]] = []
    for order, signature in enumerate(SIGNATURES, start=1):
        signature_rows = [row for row in eligible_rows if row["signature"] == signature]
        families: dict[str, list[Mapping[str, Any]]] = {}
        for row in signature_rows:
            families.setdefault(row["scenario_family_id"], []).append(row)
        if not families:
            raise RuntimeError(f"No eligible family for {selection_scope} signature {signature}")
        if any(len(rows) != 2 for rows in families.values()):
            raise RuntimeError(
                f"Every eligible family must retain two utterances: {selection_scope} {signature}"
            )

        family_vectors: dict[str, Any] = {}
        for family_id, family_rows in families.items():
            vector = np.mean(
                [embeddings[row["annotation_case_id"]] for row in family_rows],
                axis=0,
            )
            family_vectors[family_id] = _normalize(vector)
        signature_centroid = _normalize(np.mean(list(family_vectors.values()), axis=0))
        distances = {
            family_id: float(1.0 - np.dot(vector, signature_centroid))
            for family_id, vector in family_vectors.items()
        }
        selected_family_id = min(
            family_vectors,
            key=lambda family_id: (distances[family_id], family_id),
        )

        ordered_utterances = sorted(
            families[selected_family_id],
            key=lambda row: (len(row["semantic_text"]), row["annotation_case_id"]),
        )
        selected_row = ordered_utterances[(len(ordered_utterances) - 1) // 2]
        selected.append(
            {
                "selection_scope": selection_scope,
                "example_order": order,
                "signature": signature,
                "annotation_case_id": selected_row["annotation_case_id"],
                "scenario_family_id": selected_row["scenario_family_id"],
                "dev_atomic_component_id": selected_row["dev_atomic_component_id"],
                "semantic_input": selected_row["semantic_input"],
                "label_output": selected_row["label_output"],
                "semantic_input_character_count": len(selected_row["semantic_text"]),
                "eligible_signature_family_count": len(families),
                "eligible_signature_utterance_count": len(signature_rows),
                "family_centroid_cosine_distance": format(
                    distances[selected_family_id], ".15f"
                ),
                "utterance_selection_rule": (
                    "lower median after semantic-input character-length ordering; "
                    "annotation_case_id is the final tie-break"
                ),
            }
        )
    return selected


def select_all_examples(
    rows: Sequence[Mapping[str, Any]],
    fold_map: Mapping[str, Mapping[str, str]],
    embeddings: Mapping[str, Any],
) -> tuple[dict[str, list[dict[str, Any]]], list[dict[str, Any]]]:
    answer_rows = [row for row in rows if row["dialogue_action"] == "ANSWER"]
    fold_examples: dict[str, list[dict[str, Any]]] = {}
    for fold in FOLDS:
        validation_rows = [
            row
            for row in rows
            if fold_map[f"{row['annotation_case_id']}|{fold}"]["fold_role"]
            == "VALIDATION"
        ]
        validation_ids = {row["annotation_case_id"] for row in validation_rows}
        validation_families = {row["scenario_family_id"] for row in validation_rows}
        validation_components = {
            row["dev_atomic_component_id"] for row in validation_rows
        }
        eligible_rows = [
            row
            for row in answer_rows
            if row["annotation_case_id"] not in validation_ids
            and row["scenario_family_id"] not in validation_families
            and row["dev_atomic_component_id"] not in validation_components
        ]
        if len(eligible_rows) != 48:
            raise RuntimeError(
                f"Expected 48 fold-safe ANSWER pool utterances for {fold}, "
                f"observed {len(eligible_rows)}"
            )
        fold_examples[fold] = select_signature_examples(
            eligible_rows,
            embeddings,
            selection_scope=fold,
        )

    full_dev_examples = select_signature_examples(
        answer_rows,
        embeddings,
        selection_scope="FULL_DEV",
    )
    return fold_examples, full_dev_examples


def public_example(audit_row: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "input": audit_row["semantic_input"],
        "output": audit_row["label_output"],
    }


def response_format_payload() -> dict[str, Any]:
    return {
        "type": "json_schema",
        "json_schema": {
            "name": "rq2_v2_b4_capability_route_v1",
            "strict": True,
            "schema": RESPONSE_SCHEMA,
        },
    }


def few_shot_messages(examples: Sequence[Mapping[str, Any]]) -> list[dict[str, str]]:
    messages: list[dict[str, str]] = [{"role": "system", "content": PROMPT_TEMPLATE}]
    for example in examples:
        messages.append(
            {"role": "user", "content": rendered_json(example["input"])}
        )
        messages.append(
            {"role": "assistant", "content": rendered_json(example["output"])}
        )
    return messages


def prompt_package_hash(examples: Sequence[Mapping[str, Any]]) -> str:
    return canonical_sha256(
        {
            "messages": few_shot_messages(examples),
            "response_format": response_format_payload(),
        }
    )


def _write_examples_csv(
    path: Path,
    rows: Iterable[Mapping[str, Any]],
    include_fold: bool,
) -> None:
    fieldnames = []
    if include_fold:
        fieldnames.append("outer_fold_id")
    fieldnames.extend(
        [
            "example_order",
            "signature",
            "annotation_case_id",
            "scenario_family_id",
            "dev_atomic_component_id",
            *SEMANTIC_FIELDS,
            *LABEL_FIELDS,
            "semantic_input_character_count",
            "eligible_signature_family_count",
            "eligible_signature_utterance_count",
            "family_centroid_cosine_distance",
            "utterance_selection_rule",
            "encoder_repo_id",
            "encoder_revision",
        ]
    )
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames, lineterminator="\n")
        writer.writeheader()
        for row in rows:
            output: dict[str, Any] = {}
            if include_fold:
                output["outer_fold_id"] = row["selection_scope"]
            output.update(
                {
                    "example_order": row["example_order"],
                    "signature": row["signature"],
                    "annotation_case_id": row["annotation_case_id"],
                    "scenario_family_id": row["scenario_family_id"],
                    "dev_atomic_component_id": row["dev_atomic_component_id"],
                    "current_query": row["semantic_input"]["current_query"],
                    "current_page": row["semantic_input"]["current_page"],
                    "dashboard_context": row["semantic_input"]["dashboard_context"],
                    "visible_conversation_history": canonical_json(
                        row["semantic_input"]["visible_conversation_history"]
                    ),
                    "rag_required": canonical_json(row["label_output"]["rag_required"]),
                    "memory_required": canonical_json(
                        row["label_output"]["memory_required"]
                    ),
                    "planning_required": canonical_json(
                        row["label_output"]["planning_required"]
                    ),
                    "semantic_input_character_count": row[
                        "semantic_input_character_count"
                    ],
                    "eligible_signature_family_count": row[
                        "eligible_signature_family_count"
                    ],
                    "eligible_signature_utterance_count": row[
                        "eligible_signature_utterance_count"
                    ],
                    "family_centroid_cosine_distance": row[
                        "family_centroid_cosine_distance"
                    ],
                    "utterance_selection_rule": row["utterance_selection_rule"],
                    "encoder_repo_id": ENCODER_REPO_ID,
                    "encoder_revision": ENCODER_REVISION,
                }
            )
            writer.writerow(output)


def build_manifest(
    rows: Sequence[Mapping[str, Any]],
    fold_map: Mapping[str, Mapping[str, str]],
    fold_examples: Mapping[str, Sequence[Mapping[str, Any]]],
    prompt_hash: str,
    schema_hash: str,
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    records: list[dict[str, Any]] = []
    counter = 0
    request_character_counts: list[int] = []
    for fold in FOLDS:
        audits = list(fold_examples[fold])
        public_examples = [public_example(row) for row in audits]
        example_ids = [row["annotation_case_id"] for row in audits]
        example_set_hash = canonical_sha256(public_examples)
        fold_prompt_hash = prompt_package_hash(public_examples)
        validation_answer_rows = sorted(
            (
                row
                for row in rows
                if row["dialogue_action"] == "ANSWER"
                and fold_map[f"{row['annotation_case_id']}|{fold}"]["fold_role"]
                == "VALIDATION"
            ),
            key=lambda row: row["annotation_case_id"],
        )
        if len(validation_answer_rows) != 16:
            raise RuntimeError(f"Expected 16 B4 validation cases for {fold}")
        for row in validation_answer_rows:
            counter += 1
            messages = few_shot_messages(public_examples)
            messages.append(
                {"role": "user", "content": rendered_json(row["semantic_input"])}
            )
            provider_payload = {
                "model": EXISTING_MODEL_IDENTIFIER,
                "messages": messages,
                "temperature": 0,
                "response_format": response_format_payload(),
            }
            request_characters = len(canonical_json(provider_payload))
            request_character_counts.append(request_characters)
            records.append(
                {
                    "schema_version": "rq2-v2-stage4-i-b4-dev-execution-record-v1",
                    "logical_call_id": f"R2V2-B4-DEV-{counter:04d}",
                    "annotation_case_id": row["annotation_case_id"],
                    "outer_fold_id": fold,
                    "prompt_template_sha256": prompt_hash,
                    "fold_specific_example_ids": example_ids,
                    "fold_specific_example_set_sha256": example_set_hash,
                    "fold_prompt_package_sha256": fold_prompt_hash,
                    "validation_input": row["semantic_input"],
                    "strict_response_schema_sha256": schema_hash,
                    "execution_status": "NOT_EXECUTED",
                    "model_execution_authorization_status": MODEL_AUTHORIZATION_STATUS,
                    "execution_controls": {
                        "sdk_transport_retries": 0,
                        "invalid_structured_output_retries_max": 1,
                        "silent_repair_allowed": False,
                    },
                    "estimated_input_tokens_char_div_4": math.ceil(
                        request_characters / 4
                    ),
                    "provider_request_payload": provider_payload,
                }
            )
    if counter != 64:
        raise RuntimeError(f"Expected 64 logical DEV requests, observed {counter}")

    max_output_characters = max(
        len(
            canonical_json(
                {
                    "rag_required": bool(value & 4),
                    "memory_required": bool(value & 2),
                    "planning_required": bool(value & 1),
                }
            )
        )
        for value in range(8)
    )
    max_output_tokens = math.ceil(max_output_characters / 4)
    first_attempt_input_tokens = sum(
        record["estimated_input_tokens_char_div_4"] for record in records
    )
    token_estimate = {
        "method": "offline heuristic ceil(canonical request characters / 4); not a provider tokenizer",
        "logical_call_count": 64,
        "maximum_physical_attempt_count": 128,
        "minimum_input_tokens_per_attempt": math.ceil(
            min(request_character_counts) / 4
        ),
        "maximum_input_tokens_per_attempt": math.ceil(
            max(request_character_counts) / 4
        ),
        "first_attempt_input_tokens_total": first_attempt_input_tokens,
        "maximum_input_tokens_if_every_case_uses_one_retry": (
            first_attempt_input_tokens * 2
        ),
        "maximum_output_tokens_per_attempt": max_output_tokens,
        "first_attempt_output_tokens_total_upper_bound": max_output_tokens * 64,
        "maximum_output_tokens_for_128_attempts_upper_bound": max_output_tokens
        * 128,
    }
    return records, token_estimate


def _authorization_request(
    prompt_hash: str,
    schema_hash: str,
    token_estimate: Mapping[str, Any],
) -> str:
    return textwrap.dedent(
        f"""\
        # B4 DEV Execution Authorization Request

        Status: `AWAITING_DIRECT_USER_AUTHORIZATION__NOT_EXECUTED`

        This document requests a future, separate authorization. It is not execution authority and this preparation task made no provider call.

        ## Proposed frozen execution configuration

        - Provider/client surface: `{EXISTING_PROVIDER}` through the repository's existing OpenAI client path.
        - Proposed model identifier: `{EXISTING_MODEL_IDENTIFIER}`. This identifier is already configured in the repository, but it is not authorized for B4 execution by this document.
        - Model authorization status: `{MODEL_AUTHORIZATION_STATUS}`.
        - Logical call count: `64`.
        - Maximum physical attempt count: `128` if every logical case consumes the one permitted invalid-output retry.
        - Temperature: `0` where supported.
        - One terminal logical result record per DEV case.
        - SDK transport retries: `0`; the existing SDK default must be overridden for any future B4 run.
        - Manual retries: maximum `1`, and only after syntactically invalid JSON or strict-schema validation failure.
        - Prompt template SHA-256: `{prompt_hash}`.
        - Strict response-schema SHA-256: `{schema_hash}`.

        ## Strict output contract

        The response must be one JSON object with exactly three boolean fields: `rag_required`, `memory_required`, and `planning_required`. Missing fields, unknown fields, string booleans, invalid JSON, and prose-wrapped JSON are invalid. No prediction may be inferred, coerced, extracted, or repaired.

        On the first invalid structured output, retain an attempt-level invalid record and retry once with the identical model, prompt, examples, schema, and temperature. If the second output is invalid, emit the single terminal logical outcome `INVALID_STRUCTURED_OUTPUT` with no capability prediction. Transport, authentication, quota, timeout, and provider errors receive no retry under this plan and produce a terminal provider-error outcome with no capability prediction.

        ## Offline token estimate

        - Method: `{token_estimate['method']}`.
        - Estimated input tokens per physical attempt: `{token_estimate['minimum_input_tokens_per_attempt']}` to `{token_estimate['maximum_input_tokens_per_attempt']}`.
        - Estimated first-attempt input tokens across 64 calls: `{token_estimate['first_attempt_input_tokens_total']}`.
        - Estimated maximum input tokens across 128 attempts: `{token_estimate['maximum_input_tokens_if_every_case_uses_one_retry']}`.
        - Estimated maximum output tokens per attempt: `{token_estimate['maximum_output_tokens_per_attempt']}`.
        - Estimated maximum output tokens across 128 attempts: `{token_estimate['maximum_output_tokens_for_128_attempts_upper_bound']}`.

        These are character-based planning estimates, not provider-tokenizer counts or billing quotes.

        ## Explicit exclusions

        - No TEST calls or TEST access.
        - No P1 calls or implementation.
        - No RQ3 calls or execution.
        - No execution until a direct user authorization names the model and permits the bounded DEV calls.
        """
    )


def _provider_inventory() -> str:
    return textwrap.dedent(
        f"""\
        # B4 Provider and Client Inventory

        Status: `INVENTORIED_NOT_CALLED`

        - Client construction path: `pages/1 - 👨🏼‍💻 Individual Feedback.py` constructs `openai.Client(api_key=st.secrets["openai_api_key"])`.
        - Reusable call path: `utils/c_full_service.py::generate_c_full_response()` calls `openai_client.chat.completions.create(...)`.
        - Existing model configuration: `{EXISTING_MODEL_IDENTIFIER}` is both the reusable function default and the page-level explicit value.
        - Existing request settings: `temperature=0`; messages are plain system/user content.
        - Structured output in the current wrapper: none. The inspected installed OpenAI 1.x client exposes the Chat Completions `response_format` parameter; the proposed B4 request uses strict `json_schema` with `strict=true`. Provider/model compatibility still requires a separately authorized pre-call verification.
        - Credential names: the existing app uses the Streamlit secret key `openai_api_key` (not an environment variable). The installed SDK also recognizes `OPENAI_API_KEY` when an explicit key is not passed. No value was read or recorded.
        - Retry behaviour: the repository wrapper has no explicit retry loop and does not override client retries. The inspected installed client default is `max_retries=2`. A future bounded B4 executor must set SDK transport retries to `0` and implement at most one manual retry solely for invalid structured output.
        - Logging behaviour: the wrapper does not explicitly log provider request bodies, responses, usage, or tokens. `generate_c_full_chat_turn()` logs a transaction exception with `logger.exception`; the Streamlit page separately retains visible chat content in application state/history.
        - SDK constraint in repository: `openai>=1.0.0,<2`.

        No SDK was installed and no provider client was instantiated or called during this inventory.
        """
    )


def _preparation_report(
    prompt_hash: str,
    schema_hash: str,
    fold_hashes: Mapping[str, Any],
    full_examples: Sequence[Mapping[str, Any]],
    token_estimate: Mapping[str, Any],
) -> str:
    fold_count_lines = textwrap.indent(
        "\n".join(
            f"- `{fold}`: {entry['example_count']} examples; signatures "
            f"{', '.join(entry['signatures'])}"
            for fold, entry in fold_hashes["folds"].items()
        ),
        "        ",
    )
    return textwrap.dedent(
        f"""\
        # RQ2-V2 Stage 4I B4 Preparation Report

        Status: `READY_FOR_DIRECT_B4_DEV_EXECUTION_AUTHORIZATION`

        This status means the offline prompt, strict schema, fold-safe examples, full-DEV package, and unexecuted DEV manifest are technically prepared. It is not authorization, execution, validation performance, TEST readiness, or a model result.

        ## Frozen inputs and boundaries

        - Authorized source: frozen Stage 4-0 DEV protocol only.
        - DEV source-package SHA-256: `{DEV_SOURCE_PACKAGE_SHA256}`.
        - B4 population: 64 ANSWER utterances; the shared clarification gate is outside this conditional core manifest.
        - Prompt SHA-256: `{prompt_hash}`.
        - Response-schema SHA-256: `{schema_hash}`.
        - Encoder: `{ENCODER_REPO_ID}@{ENCODER_REVISION}`, local CPU snapshot, offline-only, selection-only.
        - Encoder is not the B4 prediction model.

        ## Deterministic selection

        Each signature groups eligible utterances by scenario family. Each family is the L2-normalized mean of its two normalized MPNet embeddings. The selected family representation has minimum cosine distance to the signature-family centroid. The selected utterance is the lower median after ordering by canonical semantic-input character length, with annotation ID used only as the final tie-break. Fold pools exclude every validation utterance, validation family, and validation-linked atomic component.

{fold_count_lines}

        - Final full-DEV examples: `{len(full_examples)}` covering signatures `{', '.join(row['signature'] for row in full_examples)}`.
        - DEV execution manifest: `64` unique logical calls, all `NOT_EXECUTED`.
        - Maximum future physical attempts under the proposed retry policy: `{token_estimate['maximum_physical_attempt_count']}`.

        ## Provider inventory outcome

        The repository contains an OpenAI Chat Completions client and an existing `{EXISTING_MODEL_IDENTIFIER}` configuration. Current application code does not request structured output and inherits SDK retries; any future B4 execution therefore requires direct authorization plus an execution adapter/configuration that uses strict JSON Schema, `max_retries=0`, and at most one manual invalid-output retry.

        ## Verification boundary

        The included unit tests verify source hashes, DEV-only IDs, fold and atomic-component exclusion, schema strictness, deterministic selection and prompt hashing, provider-payload leakage boundaries, and zero network/provider calls during an offline rebuild. Observed pass/fail counts are recorded in `B4_VERIFICATION_REPORT.md` only after the tests are actually run.

        No provider call, network download, B4 prediction, TEST access, P1 work, or RQ3 work is performed by this package.
        """
    )


def _status_document(prompt_hash: str, schema_hash: str) -> str:
    return textwrap.dedent(
        f"""\
        # RQ2-V2 Stage 4I B4 Status

        Status: `READY_FOR_DIRECT_B4_DEV_EXECUTION_AUTHORIZATION`

        Preparation-only result. The prompt, strict response schema, four fold-safe eight-example sets, one eight-example full-DEV package, and 64-record `NOT_EXECUTED` manifest are frozen.

        - Prompt SHA-256: `{prompt_hash}`
        - Response-schema SHA-256: `{schema_hash}`
        - Proposed existing model identifier: `{EXISTING_MODEL_IDENTIFIER}`
        - Model execution authorization: `{MODEL_AUTHORIZATION_STATUS}`
        - Network calls: `0`
        - Provider calls: `0`

        Do not execute B4 without a new direct user authorization. No TEST, P1, or RQ3 action is authorized by this status.
        """
    )


def build(output_dir: Path = SCRIPT_DIR) -> dict[str, Any]:
    output_dir = output_dir.resolve()
    output_dir.mkdir(parents=True, exist_ok=True)

    source_verification = verify_dev_sources()
    encoder_identity = verify_encoder_snapshot()
    rows, _atomic_by_id, fold_map = load_dev_inputs()
    answer_rows = [row for row in rows if row["dialogue_action"] == "ANSWER"]
    embeddings = load_embeddings(answer_rows, encoder_identity)
    fold_examples, full_examples = select_all_examples(rows, fold_map, embeddings)

    prompt_path = output_dir / "b4_prompt_template_frozen_v1.txt"
    schema_path = output_dir / "b4_response_schema_v1.json"
    write_text(prompt_path, PROMPT_TEMPLATE)
    write_json(schema_path, RESPONSE_SCHEMA)
    prompt_hash = sha256_file(prompt_path)
    schema_hash = sha256_file(schema_path)

    fold_csv_rows = [
        row for fold in FOLDS for row in fold_examples[fold]
    ]
    _write_examples_csv(
        output_dir / "b4_fold_examples_v1.csv",
        fold_csv_rows,
        include_fold=True,
    )
    _write_examples_csv(
        output_dir / "b4_final_dev_examples_v1.csv",
        full_examples,
        include_fold=False,
    )

    fold_hash_entries: dict[str, Any] = {}
    for fold in FOLDS:
        public_examples = [public_example(row) for row in fold_examples[fold]]
        fold_hash_entries[fold] = {
            "example_count": len(public_examples),
            "signatures": [row["signature"] for row in fold_examples[fold]],
            "example_ids": [
                row["annotation_case_id"] for row in fold_examples[fold]
            ],
            "example_set_sha256": canonical_sha256(public_examples),
            "fold_prompt_package_sha256": prompt_package_hash(public_examples),
        }
    final_public_examples = [public_example(row) for row in full_examples]
    fold_hashes = {
        "schema_version": "rq2-v2-stage4-i-b4-fold-prompt-hashes-v1",
        "prompt_template_sha256": prompt_hash,
        "strict_response_schema_sha256": schema_hash,
        "hash_serialization": "UTF-8 canonical JSON with sorted keys and compact separators",
        "folds": fold_hash_entries,
        "full_dev": {
            "example_count": len(final_public_examples),
            "signatures": [row["signature"] for row in full_examples],
            "example_ids": [row["annotation_case_id"] for row in full_examples],
            "example_set_sha256": canonical_sha256(final_public_examples),
            "prompt_package_sha256": prompt_package_hash(final_public_examples),
        },
    }
    write_json(output_dir / "b4_fold_prompt_hashes_v1.json", fold_hashes)

    manifest_records, token_estimate = build_manifest(
        rows,
        fold_map,
        fold_examples,
        prompt_hash,
        schema_hash,
    )
    with (output_dir / "b4_dev_execution_manifest_v1.jsonl").open(
        "w", encoding="utf-8", newline="\n"
    ) as handle:
        for record in manifest_records:
            handle.write(canonical_json(record) + "\n")

    package_content = {
        "prompt_template": PROMPT_TEMPLATE,
        "few_shot_examples": final_public_examples,
        "response_schema": RESPONSE_SCHEMA,
        "structured_output": response_format_payload(),
        "encoder_identity": encoder_identity,
    }
    final_package = {
        "schema_version": "rq2-v2-stage4-i-b4-final-full-dev-prompt-package-v1",
        "status": "FROZEN_NOT_EXECUTED",
        **package_content,
        "hashes": {
            "prompt_template_sha256": prompt_hash,
            "strict_response_schema_sha256": schema_hash,
            "example_set_sha256": canonical_sha256(final_public_examples),
            "prompt_package_content_sha256": canonical_sha256(package_content),
        },
        "execution_boundary": {
            "provider_calls_made": 0,
            "network_calls_made": 0,
            "model_execution_authorization_status": MODEL_AUTHORIZATION_STATUS,
            "intended_future_use": "ONE_TIME_B4_TEST_EXECUTION_ONLY_AFTER_MODEL_DEVELOPMENT_FREEZE_AND_NEW_AUTHORIZATION",
        },
    }
    write_json(
        output_dir / "b4_final_full_dev_prompt_package_v1.json",
        final_package,
    )
    write_json(output_dir / "b4_encoder_identity_v1.json", encoder_identity)
    write_json(
        output_dir / "b4_dev_source_verification_v1.json", source_verification
    )
    write_json(output_dir / "b4_token_estimate_v1.json", token_estimate)

    write_text(
        output_dir / "B4_DEV_EXECUTION_AUTHORIZATION_REQUEST.md",
        _authorization_request(prompt_hash, schema_hash, token_estimate),
    )
    write_text(
        output_dir / "B4_PROVIDER_CLIENT_INVENTORY.md",
        _provider_inventory(),
    )
    write_text(
        output_dir / "TRACK_I_PREPARATION_REPORT.md",
        _preparation_report(
            prompt_hash,
            schema_hash,
            fold_hashes,
            full_examples,
            token_estimate,
        ),
    )
    write_text(
        output_dir / "STATUS.md",
        _status_document(prompt_hash, schema_hash),
    )

    return {
        "status": "READY_FOR_DIRECT_B4_DEV_EXECUTION_AUTHORIZATION",
        "output_directory": str(output_dir),
        "prompt_sha256": prompt_hash,
        "response_schema_sha256": schema_hash,
        "fold_example_counts": {
            fold: len(fold_examples[fold]) for fold in FOLDS
        },
        "final_full_dev_example_count": len(full_examples),
        "logical_call_count": len(manifest_records),
        "maximum_physical_attempt_count": token_estimate[
            "maximum_physical_attempt_count"
        ],
        "network_calls": 0,
        "provider_calls": 0,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=SCRIPT_DIR,
        help="Artifact output directory (defaults to this track directory).",
    )
    args = parser.parse_args()
    print(json.dumps(build(args.output_dir), ensure_ascii=False, sort_keys=True, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
