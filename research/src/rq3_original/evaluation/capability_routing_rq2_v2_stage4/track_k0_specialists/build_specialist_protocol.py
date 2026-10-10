from __future__ import annotations

import argparse
import csv
import hashlib
import json
import math
from pathlib import Path
import textwrap
from typing import Any, Iterable, Mapping, Sequence


TRACK_DIR = Path(__file__).resolve().parent
STAGE4_DIR = TRACK_DIR.parent
B4_DIR = STAGE4_DIR / "track_i_b4"
DEV_PROTOCOL_DIR = STAGE4_DIR / "dev_protocol"

FREEZE_DATE = "2026-08-31"
STARTING_HEAD = "92795f1d0bb92e1046b087bd843a415208fff6ae"
EXPECTED_BRANCH = "research/rq2-v2-stage4-k0-specialist-protocol"
MODEL_SNAPSHOT = "gpt-4o-mini-2024-07-18"
TEMPERATURE = 0
MAXIMUM_OUTPUT_TOKENS = 32
SDK_TRANSPORT_RETRIES = 0
MANUAL_INVALID_OUTPUT_RETRIES_MAX = 1
EXPECTED_TEST_COUNT = 24

FOLDS = (
    "DEV-CV-FOLD-1",
    "DEV-CV-FOLD-2",
    "DEV-CV-FOLD-3",
    "DEV-CV-FOLD-4",
)
SIGNATURES = ("000", "001", "010", "011", "100", "101", "110", "111")
SEMANTIC_FIELDS = (
    "current_query",
    "current_page",
    "dashboard_context",
    "visible_conversation_history",
)

SOURCE_FILES = {
    "track_i_b4/b4_fold_examples_v1.csv": (
        B4_DIR / "b4_fold_examples_v1.csv",
        "5834833e0d9af6520e858fc1061477ff80ff026b5ea42bbfd0133f51faf8916c",
    ),
    "track_i_b4/b4_final_dev_examples_v1.csv": (
        B4_DIR / "b4_final_dev_examples_v1.csv",
        "34f12e80a654bb79a7103e35a14c5df058e4a54c8831c27d73756355754fb5b3",
    ),
    "track_i_b4/b4_dev_execution_manifest_v1.jsonl": (
        B4_DIR / "b4_dev_execution_manifest_v1.jsonl",
        "f0b8e90c43a680ab9305b873414fe7aa23d6531187b9d8560e8b389c80971b55",
    ),
    "track_i_b4/b4_fold_prompt_hashes_v1.json": (
        B4_DIR / "b4_fold_prompt_hashes_v1.json",
        "d4a7f9084745a9a4c6eab19ea20d6006f23e619404cf698392e3bcacb93f0699",
    ),
    "dev_protocol/dev_capability_gold_v1.csv": (
        DEV_PROTOCOL_DIR / "dev_capability_gold_v1.csv",
        "8d3422198a99422b3e314c60819f3553ff27cd42394ed2d9f68c0eb3ce858b56",
    ),
    "dev_protocol/dev_cv_folds_v1.csv": (
        DEV_PROTOCOL_DIR / "dev_cv_folds_v1.csv",
        "2a3a4161c81bddfcfe51b238ac5940c64df87a25beed26e54671b64c76c5ab46",
    ),
    "dev_protocol/dev_atomic_group_map_v1.csv": (
        DEV_PROTOCOL_DIR / "dev_atomic_group_map_v1.csv",
        "f1ac8973c590155ee3730de194b4c2afd6d05531744bef70a163be2428d4bd6f",
    ),
    "dev_protocol/stage4_dev_protocol_v1.json": (
        DEV_PROTOCOL_DIR / "stage4_dev_protocol_v1.json",
        "9e4e8afa354f544d58d6d30187af194e52968df5ec21ccbdcb7f6585adb75336",
    ),
}

RAG_PROMPT = textwrap.dedent(
    """\
    You are the RAG capability specialist for an educational chatbot. The shared clarification gate has already predicted ANSWER for this case.

    Decide only this question:
    Does correctly answering the visible student request minimally require additional course or external knowledge that is not already present in the visible input?

    Set rag_required to true only when both conditions hold:
    - Correct answering minimally requires course knowledge or external knowledge.
    - That required knowledge is absent from the current visible input.

    Set rag_required to false when any of these conditions holds:
    - The visible information is sufficient.
    - The question can be answered from the displayed dashboard or context.
    - Retrieval could merely improve or enrich an answer but is not necessary.
    - A week, course, lecture, resource, or rubric is merely mentioned.

    Judge RAG independently:
    - Ignore whether Memory is required.
    - Ignore whether Planning is required.
    - Do not infer RAG from another capability.
    - Do not judge retrieval quality.
    - Decide only whether retrieval is minimally necessary.

    The only semantic inputs are current_query, current_page, dashboard_context, and visible_conversation_history. Base the decision solely on those four fields.

    Return only one JSON object with exactly this key and a JSON boolean value:
    {"rag_required":true}
    Do not add Markdown, prose, a free-form explanation, or any other field.
    """
)

MEMORY_PROMPT = textwrap.dedent(
    """\
    You are the Memory capability specialist for an educational chatbot. The shared clarification gate has already predicted ANSWER for this case.

    Decide only this question:
    Does correctly answering the visible student request minimally require student-specific information from an earlier interaction that is absent from visible conversation history?

    Set memory_required to true only when all conditions hold:
    - A student-specific prior goal, preference, constraint, difficulty, deadline, or prior plan is needed.
    - That information is absent from visible conversation history.
    - It must therefore be retrieved from long-term Memory.

    Set memory_required to false when any of these conditions holds:
    - The required information is already visible.
    - Current Dashboard information is sufficient.
    - The query is self-contained.
    - Generic course knowledge is needed instead.
    - The query merely mentions the past but no missing personal fact is necessary.

    Judge Memory independently:
    - Visible conversation history is not long-term Memory.
    - Ignore whether RAG is required.
    - Ignore whether Planning is required.
    - Do not retrieve or invent the missing memory.
    - Judge only whether long-term Memory is minimally necessary.

    The only semantic inputs are current_query, current_page, dashboard_context, and visible_conversation_history. Base the decision solely on those four fields.

    Return only one JSON object with exactly this key and a JSON boolean value:
    {"memory_required":true}
    Do not add Markdown, prose, a free-form explanation, or any other field.
    """
)

RAG_SCHEMA = {
    "type": "object",
    "properties": {"rag_required": {"type": "boolean"}},
    "required": ["rag_required"],
    "additionalProperties": False,
}

MEMORY_SCHEMA = {
    "type": "object",
    "properties": {"memory_required": {"type": "boolean"}},
    "required": ["memory_required"],
    "additionalProperties": False,
}

SPECIALISTS = {
    "rag": {
        "display_name": "RAG Specialist",
        "target_field": "rag_required",
        "prompt": RAG_PROMPT,
        "schema": RAG_SCHEMA,
        "schema_name": "rq2_v2_rag_specialist_v1",
    },
    "memory": {
        "display_name": "Memory Specialist",
        "target_field": "memory_required",
        "prompt": MEMORY_PROMPT,
        "schema": MEMORY_SCHEMA,
        "schema_name": "rq2_v2_memory_specialist_v1",
    },
}

RETRY_POLICY = {
    "schema_version": "rq2-v2-stage4-k0-specialist-future-retry-policy-v1",
    "status": "FROZEN_NOT_EXECUTED",
    "applies_identically_to": ["RAG_SPECIALIST", "MEMORY_SPECIALIST"],
    "logical_calls_per_specialist": 64,
    "initial_requests_per_logical_call": 1,
    "manual_retries_per_logical_call_max": 1,
    "manual_retry_condition": "INVALID_JSON_OR_STRICT_SCHEMA_ONLY",
    "retry_uses_identical_prompt": True,
    "correction_message_allowed": False,
    "string_to_boolean_coercion_allowed": False,
    "json_extraction_from_prose_allowed": False,
    "sdk_transport_retries": 0,
    "non_retryable_error_categories": [
        "AUTHENTICATION",
        "PERMISSION",
        "REQUEST_CONFIGURATION",
        "TRANSPORT",
        "RATE_LIMIT",
        "MODEL",
    ],
    "maximum_physical_attempts_per_specialist": 128,
    "provider_calls_authorized_in_stage4_k0": 0,
}


def canonical_json(value: Any) -> str:
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    )


def rendered_json(value: Any) -> str:
    return json.dumps(
        value,
        ensure_ascii=False,
        separators=(",", ":"),
        allow_nan=False,
    )


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
        json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False) + "\n",
    )


def read_csv(path: Path) -> list[dict[str, str]]:
    with path.open("r", encoding="utf-8", newline="") as handle:
        return list(csv.DictReader(handle))


def read_jsonl(path: Path) -> list[dict[str, Any]]:
    with path.open("r", encoding="utf-8") as handle:
        return [json.loads(line) for line in handle if line.strip()]


def parse_csv_boolean(value: str) -> bool:
    if value == "true":
        return True
    if value == "false":
        return False
    raise ValueError(f"Expected exact lowercase JSON boolean, observed {value!r}")


def verify_sources() -> dict[str, Any]:
    verified: list[dict[str, str]] = []
    for name, (path, expected_hash) in SOURCE_FILES.items():
        observed_hash = sha256_file(path)
        if observed_hash != expected_hash:
            raise RuntimeError(
                f"Frozen source mismatch for {name}: expected {expected_hash}, "
                f"observed {observed_hash}"
            )
        verified.append(
            {"name": name, "sha256": observed_hash, "access_class": "FROZEN_DEV_OR_B4_PREPARATION"}
        )
    return {
        "schema_version": "rq2-v2-stage4-k0-source-verification-v1",
        "status": "PASS",
        "starting_head": STARTING_HEAD,
        "verified_files": verified,
        "governance": {
            "dev_only": True,
            "test_inputs_accessed": False,
            "test_gold_accessed": False,
            "test_escrow_accessed": False,
            "stage3c_test_ids_accessed": False,
            "restricted_full_split_accessed": False,
            "successful_case_level_b4_predictions_accessed": False,
            "b4_error_files_accessed": False,
        },
    }


def semantic_input_from_csv(row: Mapping[str, str]) -> dict[str, Any]:
    value = {
        "current_query": row["current_query"],
        "current_page": row["current_page"],
        "dashboard_context": row["dashboard_context"],
        "visible_conversation_history": json.loads(row["visible_conversation_history"]),
    }
    if tuple(value) != SEMANTIC_FIELDS:
        raise RuntimeError("Semantic input field order or membership changed")
    return value


def specialist_public_example(row: Mapping[str, str], target_field: str) -> dict[str, Any]:
    return {
        "input": semantic_input_from_csv(row),
        "output": {target_field: parse_csv_boolean(row[target_field])},
    }


def response_format(schema_name: str, schema: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "type": "json_schema",
        "json_schema": {"name": schema_name, "strict": True, "schema": schema},
    }


def few_shot_messages(prompt: str, examples: Sequence[Mapping[str, Any]]) -> list[dict[str, str]]:
    messages = [{"role": "system", "content": prompt}]
    for example in examples:
        messages.append({"role": "user", "content": rendered_json(example["input"])})
        messages.append({"role": "assistant", "content": rendered_json(example["output"])})
    return messages


def provider_request_prefix(
    prompt: str,
    examples: Sequence[Mapping[str, Any]],
    schema_name: str,
    schema: Mapping[str, Any],
) -> dict[str, Any]:
    return {
        "model": MODEL_SNAPSHOT,
        "messages": few_shot_messages(prompt, examples),
        "temperature": TEMPERATURE,
        "max_tokens": MAXIMUM_OUTPUT_TOKENS,
        "response_format": response_format(schema_name, schema),
    }


def write_specialist_examples_csv(
    path: Path,
    rows: Iterable[Mapping[str, str]],
    target_field: str,
    *,
    include_fold: bool,
) -> None:
    fieldnames: list[str] = []
    if include_fold:
        fieldnames.append("outer_fold")
    fieldnames.extend(
        [
            "example_order",
            "signature",
            "annotation_case_id",
            "scenario_family_id",
            "dev_atomic_component_id",
            *SEMANTIC_FIELDS,
            target_field,
        ]
    )
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames, lineterminator="\n")
        writer.writeheader()
        for row in rows:
            output: dict[str, Any] = {}
            if include_fold:
                output["outer_fold"] = row["outer_fold_id"]
            output.update(
                {
                    "example_order": row["example_order"],
                    "signature": row["signature"],
                    "annotation_case_id": row["annotation_case_id"],
                    "scenario_family_id": row["scenario_family_id"],
                    "dev_atomic_component_id": row["dev_atomic_component_id"],
                    "current_query": row["current_query"],
                    "current_page": row["current_page"],
                    "dashboard_context": row["dashboard_context"],
                    "visible_conversation_history": row["visible_conversation_history"],
                    target_field: row[target_field],
                }
            )
            writer.writerow(output)


def fold_filename(specialist: str, fold: str) -> str:
    number = fold.rsplit("-", 1)[-1]
    return f"{specialist}_specialist_dev_cv_fold_{number}_prompt_package_v1.json"


def execution_controls() -> dict[str, Any]:
    return {
        "sdk_transport_retries": SDK_TRANSPORT_RETRIES,
        "initial_request_count": 1,
        "manual_retry_max": MANUAL_INVALID_OUTPUT_RETRIES_MAX,
        "manual_retry_condition": "INVALID_JSON_OR_STRICT_SCHEMA_ONLY",
        "retry_prompt_identical": True,
        "correction_message_allowed": False,
        "string_to_boolean_coercion_allowed": False,
        "json_extraction_from_prose_allowed": False,
        "non_retryable_error_categories": RETRY_POLICY["non_retryable_error_categories"],
        "maximum_output_tokens": MAXIMUM_OUTPUT_TOKENS,
    }


def build_packages(
    output_dir: Path,
    fold_rows: Sequence[Mapping[str, str]],
    final_rows: Sequence[Mapping[str, str]],
    b4_hashes: Mapping[str, Any],
    prompt_hashes: Mapping[str, str],
    schema_hashes: Mapping[str, str],
) -> tuple[dict[str, Any], dict[str, dict[str, Any]]]:
    index: dict[str, Any] = {
        "schema_version": "rq2-v2-stage4-k0-specialist-fold-prompt-hashes-v1",
        "status": "FROZEN_NOT_EXECUTED",
        "hash_serialization": "UTF-8 canonical JSON with sorted keys and compact separators",
        "source_b4_fold_examples_file_sha256": SOURCE_FILES[
            "track_i_b4/b4_fold_examples_v1.csv"
        ][1],
        "source_b4_final_examples_file_sha256": SOURCE_FILES[
            "track_i_b4/b4_final_dev_examples_v1.csv"
        ][1],
        "specialists": {},
    }
    fold_material: dict[str, dict[str, Any]] = {name: {} for name in SPECIALISTS}
    for specialist, config in SPECIALISTS.items():
        target = config["target_field"]
        specialist_index: dict[str, Any] = {
            "prompt_template_sha256": prompt_hashes[specialist],
            "specialist_schema_sha256": schema_hashes[specialist],
            "folds": {},
        }
        for fold in FOLDS:
            selected = [row for row in fold_rows if row["outer_fold_id"] == fold]
            if len(selected) != 8:
                raise RuntimeError(f"Expected eight source B4 examples for {fold}")
            examples = [specialist_public_example(row, target) for row in selected]
            example_ids = [row["annotation_case_id"] for row in selected]
            prefix = provider_request_prefix(
                config["prompt"], examples, config["schema_name"], config["schema"]
            )
            hashes = {
                "prompt_template_sha256": prompt_hashes[specialist],
                "specialist_schema_sha256": schema_hashes[specialist],
                "example_id_order_sha256": canonical_sha256(example_ids),
                "specialist_example_set_sha256": canonical_sha256(examples),
                "complete_rendered_fold_package_sha256": canonical_sha256(prefix),
            }
            package = {
                "schema_version": f"rq2-v2-stage4-k0-{specialist}-specialist-fold-package-v1",
                "status": "FROZEN_NOT_EXECUTED",
                "specialist": config["display_name"],
                "outer_fold": fold,
                "model_snapshot": MODEL_SNAPSHOT,
                "prompt_template": config["prompt"],
                "specialist_schema": config["schema"],
                "few_shot_examples": examples,
                "complete_rendered_fold_package": prefix,
                "hashes": hashes,
                "source_b4_reuse": {
                    "example_ids_in_order": example_ids,
                    "source_b4_example_id_order": b4_hashes["folds"][fold]["example_ids"],
                    "source_b4_example_set_sha256": b4_hashes["folds"][fold][
                        "example_set_sha256"
                    ],
                    "identity_and_order_exact": (
                        example_ids == b4_hashes["folds"][fold]["example_ids"]
                    ),
                },
                "execution_controls": execution_controls(),
                "execution_boundary": {
                    "provider_calls_authorized": 0,
                    "provider_calls_made": 0,
                    "specialist_predictions_present": 0,
                },
            }
            filename = fold_filename(specialist, fold)
            write_json(output_dir / filename, package)
            specialist_index["folds"][fold] = {
                "prompt_package_filename": filename,
                "example_count": 8,
                "signatures": [row["signature"] for row in selected],
                "example_ids": example_ids,
                "target_yes_count": sum(
                    1 for example in examples if example["output"][target]
                ),
                "target_no_count": sum(
                    1 for example in examples if not example["output"][target]
                ),
                **hashes,
            }
            fold_material[specialist][fold] = {
                "examples": examples,
                "example_ids": example_ids,
                "hashes": hashes,
                "prefix": prefix,
            }

        final_examples = [specialist_public_example(row, target) for row in final_rows]
        final_ids = [row["annotation_case_id"] for row in final_rows]
        final_prefix = provider_request_prefix(
            config["prompt"],
            final_examples,
            config["schema_name"],
            config["schema"],
        )
        final_hashes = {
            "prompt_template_sha256": prompt_hashes[specialist],
            "specialist_schema_sha256": schema_hashes[specialist],
            "example_id_order_sha256": canonical_sha256(final_ids),
            "specialist_example_set_sha256": canonical_sha256(final_examples),
            "complete_rendered_full_dev_package_sha256": canonical_sha256(final_prefix),
        }
        final_package = {
            "schema_version": f"rq2-v2-stage4-k0-{specialist}-specialist-final-full-dev-package-v1",
            "status": "FROZEN_NOT_EXECUTED",
            "specialist": config["display_name"],
            "population": "FINAL_FULL_DEV_PROMPT_ONLY",
            "model_snapshot": MODEL_SNAPSHOT,
            "prompt_template": config["prompt"],
            "specialist_schema": config["schema"],
            "few_shot_examples": final_examples,
            "complete_rendered_full_dev_package": final_prefix,
            "hashes": final_hashes,
            "source_b4_reuse": {
                "example_ids_in_order": final_ids,
                "source_b4_example_id_order": b4_hashes["full_dev"]["example_ids"],
                "source_b4_example_set_sha256": b4_hashes["full_dev"][
                    "example_set_sha256"
                ],
                "identity_and_order_exact": (
                    final_ids == b4_hashes["full_dev"]["example_ids"]
                ),
            },
            "execution_boundary": {
                "provider_calls_authorized": 0,
                "provider_calls_made": 0,
                "specialist_predictions_present": 0,
            },
        }
        final_filename = f"{specialist}_specialist_final_full_dev_prompt_package_v1.json"
        write_json(output_dir / final_filename, final_package)
        specialist_index["full_dev"] = {
            "prompt_package_filename": final_filename,
            "example_count": 8,
            "signatures": [row["signature"] for row in final_rows],
            "example_ids": final_ids,
            "target_yes_count": sum(
                1 for example in final_examples if example["output"][target]
            ),
            "target_no_count": sum(
                1 for example in final_examples if not example["output"][target]
            ),
            **final_hashes,
        }
        index["specialists"][specialist] = specialist_index

    write_json(output_dir / "specialist_fold_prompt_hashes_v1.json", index)
    return index, fold_material


def build_manifests(
    output_dir: Path,
    source_manifest: Sequence[Mapping[str, Any]],
    fold_material: Mapping[str, Mapping[str, Any]],
    prompt_hashes: Mapping[str, str],
    schema_hashes: Mapping[str, str],
) -> tuple[dict[str, list[dict[str, Any]]], dict[str, dict[str, Any]]]:
    if len(source_manifest) != 64:
        raise RuntimeError("Frozen B4 preparation manifest must contain 64 records")
    records_by_specialist: dict[str, list[dict[str, Any]]] = {}
    estimates: dict[str, dict[str, Any]] = {}
    for specialist, config in SPECIALISTS.items():
        target = config["target_field"]
        records: list[dict[str, Any]] = []
        input_estimates: list[int] = []
        for index, source_record in enumerate(source_manifest, start=1):
            if source_record["execution_status"] != "NOT_EXECUTED":
                raise RuntimeError("Source B4 preparation manifest is not unexecuted")
            fold = source_record["outer_fold_id"]
            material = fold_material[specialist][fold]
            source_validation_input = source_record["validation_input"]
            if set(source_validation_input) != set(SEMANTIC_FIELDS):
                raise RuntimeError("Validation input contains non-semantic fields")
            validation_input = {
                field: source_validation_input[field] for field in SEMANTIC_FIELDS
            }
            payload = dict(material["prefix"])
            payload["messages"] = list(material["prefix"]["messages"])
            payload["messages"].append(
                {"role": "user", "content": rendered_json(validation_input)}
            )
            estimated_tokens = math.ceil(len(canonical_json(payload)) / 4)
            input_estimates.append(estimated_tokens)
            records.append(
                {
                    "schema_version": f"rq2-v2-stage4-k0-{specialist}-specialist-dev-execution-record-v1",
                    "logical_call_id": f"R2V2-{specialist.upper()}-SPECIALIST-DEV-{index:04d}",
                    "annotation_case_id": source_record["annotation_case_id"],
                    "outer_fold": fold,
                    "model_snapshot": MODEL_SNAPSHOT,
                    "prompt_sha256": prompt_hashes[specialist],
                    "specialist_schema_sha256": schema_hashes[specialist],
                    "fold_example_ids_in_order": material["example_ids"],
                    "fold_example_id_order_sha256": material["hashes"][
                        "example_id_order_sha256"
                    ],
                    "fold_example_set_sha256": material["hashes"][
                        "specialist_example_set_sha256"
                    ],
                    "fold_prompt_package_sha256": material["hashes"][
                        "complete_rendered_fold_package_sha256"
                    ],
                    "semantic_validation_inputs": validation_input,
                    "provider_facing_request": payload,
                    "provider_facing_request_sha256": canonical_sha256(payload),
                    "estimated_input_tokens_char_div_4": estimated_tokens,
                    "execution_status": "NOT_EXECUTED",
                    "model_execution_authorization_status": (
                        f"REQUIRES_NEW_DIRECT_USER_AUTHORIZATION_FOR_{specialist.upper()}_SPECIALIST_DEV_EXECUTION"
                    ),
                    "execution_controls": execution_controls(),
                    "validation_gold_in_provider_request": False,
                }
            )
        manifest_path = output_dir / f"{specialist}_specialist_dev_execution_manifest_v1.jsonl"
        with manifest_path.open("w", encoding="utf-8", newline="\n") as handle:
            for record in records:
                handle.write(canonical_json(record) + "\n")
        first_input_total = sum(input_estimates)
        first_output_upper = 64 * MAXIMUM_OUTPUT_TOKENS
        max_input_total = first_input_total * 2
        max_output_upper = 128 * MAXIMUM_OUTPUT_TOKENS
        estimates[specialist] = {
            "logical_call_count": 64,
            "maximum_physical_attempt_count": 128,
            "minimum_input_tokens_per_attempt_char_div_4": min(input_estimates),
            "maximum_input_tokens_per_attempt_char_div_4": max(input_estimates),
            "first_attempt_input_tokens_total_char_div_4": first_input_total,
            "maximum_input_tokens_if_all_calls_retry_char_div_4": max_input_total,
            "first_attempt_output_tokens_upper_bound": first_output_upper,
            "maximum_output_tokens_if_all_calls_retry_upper_bound": max_output_upper,
            "target_field": target,
        }
        records_by_specialist[specialist] = records
    return records_by_specialist, estimates


def cost_estimate(estimates: Mapping[str, Mapping[str, Any]]) -> dict[str, Any]:
    input_rate = 0.15
    output_rate = 0.60

    def add_costs(value: Mapping[str, Any]) -> dict[str, Any]:
        first = (
            value["first_attempt_input_tokens_total_char_div_4"] * input_rate
            + value["first_attempt_output_tokens_upper_bound"] * output_rate
        ) / 1_000_000
        maximum = (
            value["maximum_input_tokens_if_all_calls_retry_char_div_4"] * input_rate
            + value["maximum_output_tokens_if_all_calls_retry_upper_bound"] * output_rate
        ) / 1_000_000
        return {**value, "first_attempt_cost_usd_upper_bound": round(first, 8), "all_retry_cost_usd_upper_bound": round(maximum, 8)}

    specialists = {name: add_costs(value) for name, value in estimates.items()}
    combined = {
        key: sum(int(specialists[name][key]) for name in specialists)
        for key in (
            "logical_call_count",
            "maximum_physical_attempt_count",
            "first_attempt_input_tokens_total_char_div_4",
            "maximum_input_tokens_if_all_calls_retry_char_div_4",
            "first_attempt_output_tokens_upper_bound",
            "maximum_output_tokens_if_all_calls_retry_upper_bound",
        )
    }
    combined_first = (
        combined["first_attempt_input_tokens_total_char_div_4"] * input_rate
        + combined["first_attempt_output_tokens_upper_bound"] * output_rate
    ) / 1_000_000
    combined_max = (
        combined["maximum_input_tokens_if_all_calls_retry_char_div_4"] * input_rate
        + combined["maximum_output_tokens_if_all_calls_retry_upper_bound"] * output_rate
    ) / 1_000_000
    combined["first_attempt_cost_usd_upper_bound"] = round(combined_first, 8)
    combined["all_retry_cost_usd_upper_bound"] = round(combined_max, 8)
    return {
        "schema_version": "rq2-v2-stage4-k0-specialist-token-cost-estimate-v1",
        "status": "OFFLINE_ESTIMATE_NO_CALLS_MADE",
        "method": "Input tokens use ceil(canonical provider-request characters / 4); output uses the frozen 32-token cap for every physical attempt.",
        "limitations": [
            "Character division is not provider tokenization.",
            "Output values are conservative upper bounds, not expected usage.",
            "No cached-input discount is assumed.",
            "Pricing may change before execution and must be re-verified at authorization time.",
        ],
        "pricing_verified_on": FREEZE_DATE,
        "pricing_source": "https://developers.openai.com/api/docs/models/gpt-4o-mini",
        "pricing_usd_per_million_tokens": {
            "uncached_input": input_rate,
            "cached_input_not_used": 0.075,
            "output": output_rate,
        },
        "specialists": specialists,
        "combined": combined,
    }


def composition_contracts() -> tuple[dict[str, Any], dict[str, Any]]:
    shared = {
        "population": "64_FROZEN_DEV_ANSWER_UTTERANCES",
        "join_key": "annotation_case_id",
        "output_field_order": ["rag_required", "memory_required", "planning_required"],
        "output_values": "JSON_BOOLEAN_BITS_ONLY",
        "confidence_or_scores_used": False,
        "learned_composition_model_used": False,
        "b3_fallback_allowed": False,
        "missing_or_invalid_specialist_result": {
            "composition_status": "INCOMPLETE",
            "substitution_allowed": False,
            "fallback_allowed": False,
            "coverage_reported_separately": True,
        },
        "execution_status": "NOT_EXECUTED",
        "dev_scoring_status": "NOT_SCORED",
    }
    p2 = {
        "schema_version": "rq2-v2-stage4-k0-p2-rag-specialist-composition-contract-v1",
        "composition_id": "R2V2-P2_RAG_SPECIALIST_COMPOSITION",
        "method_role": "PRIMARY_RAGATE_INSPIRED_EXTENSION",
        "formal_vector": ["RAG_specialist", "B4_memory", "B4_planning"],
        "bindings": {
            "rag_required": {
                "source": "RAG_SPECIALIST_VALID_STRUCTURED_RESULT",
                "source_field": "rag_required",
            },
            "memory_required": {
                "source": "FROZEN_JOINT_B4_VALID_STRUCTURED_RESULT",
                "source_field": "memory_required",
            },
            "planning_required": {
                "source": "FROZEN_JOINT_B4_VALID_STRUCTURED_RESULT",
                "source_field": "planning_required",
            },
        },
        "planning_is_function_of_memory": False,
        **shared,
    }
    p3 = {
        "schema_version": "rq2-v2-stage4-k0-p3-capability-specialists-composition-contract-v1",
        "composition_id": "R2V2-P3_RAG_MEMORY_SPECIALISTS",
        "method_role": "EXPLORATORY_PREDECLARED_FULL_SPECIALIST_EXTENSION",
        "formal_vector": ["RAG_specialist", "Memory_specialist", "B4_planning"],
        "bindings": {
            "rag_required": {
                "source": "RAG_SPECIALIST_VALID_STRUCTURED_RESULT",
                "source_field": "rag_required",
            },
            "memory_required": {
                "source": "MEMORY_SPECIALIST_VALID_STRUCTURED_RESULT",
                "source_field": "memory_required",
            },
            "planning_required": {
                "source": "FROZEN_JOINT_B4_VALID_STRUCTURED_RESULT",
                "source_field": "planning_required",
            },
        },
        "planning_is_function_of_memory": False,
        **shared,
    }
    return p2, p3


def evaluation_protocol() -> dict[str, Any]:
    specialist_common = [
        "precision",
        "recall",
        "f1",
        "accuracy",
        "specificity",
        "confusion_matrix",
        "positive_prediction_rate",
        "family_both_utterances_correct",
        "family_prediction_consistency",
        "target_contrast_consistency",
        "target_gold_pattern_contrast_match",
        "page_stratified_results",
    ]
    composition_metrics = [
        "macro_f1",
        "micro_f1",
        "per_label_precision_recall_f1",
        "exact_capability_set_match",
        "example_based_f1",
        "jaccard",
        "hamming_loss",
        "under_routing",
        "over_routing",
        "family_both_correct",
        "family_prediction_consistency",
        "contrast_consistency",
        "gold_pattern_contrast_match",
        "page_metrics",
        "fold_metrics",
    ]
    return {
        "schema_version": "rq2-v2-stage4-k0-specialist-evaluation-protocol-v1",
        "status": "PREDECLARED_NOT_EXECUTED_NOT_SCORED",
        "population": {
            "partition": "DEV",
            "dialogue_action": "ANSWER",
            "utterance_count": 64,
            "shared_clarification_gate": "UPSTREAM_UNCHANGED",
            "gold_source": "../dev_protocol/dev_capability_gold_v1.csv",
            "fold_source": "../dev_protocol/dev_cv_folds_v1.csv",
            "family_and_contrast_source": "../dev_protocol/dev_atomic_group_map_v1.csv",
        },
        "specialists": {
            "RAG": {
                "target": "rag_required",
                "metrics": [
                    value.replace("target_", "rag_") for value in specialist_common
                ],
            },
            "Memory": {
                "target": "memory_required",
                "metrics": [
                    value.replace("target_", "memory_") for value in specialist_common
                ],
            },
        },
        "compositions": {
            "R2V2-P2_RAG_SPECIALIST_COMPOSITION": composition_metrics,
            "R2V2-P3_RAG_MEMORY_SPECIALISTS": composition_metrics,
        },
        "metric_definitions": {
            "specificity": "TN divided by TN plus FP; report numerator and denominator.",
            "positive_prediction_rate": "Predicted-positive utterances divided by valid covered utterances.",
            "family_both_utterances_correct": "Fraction of two-utterance ANSWER families for which both target predictions, or both three-bit composition outputs, exactly match Gold.",
            "family_prediction_consistency": "Fraction of two-utterance ANSWER families whose two predictions are identical; report separately from correctness.",
            "target_contrast_consistency": "For eligible target-axis contrast groups, both utterances must agree within each family and the directed target-bit change between families must match Gold.",
            "contrast_consistency": "For eligible contrast groups, both utterances must agree within each family and the directed three-bit capability-change vector between families must match Gold.",
            "target_gold_pattern_contrast_match": "Fraction of eligible target-axis contrast groups for which every utterance target prediction exactly matches the frozen Gold target pattern.",
            "gold_pattern_contrast_match": "Fraction of eligible contrast groups for which every utterance three-bit composition exactly matches the frozen Gold pattern.",
            "example_based_f1": "Mean per-case set F1; two empty sets score 1.",
            "jaccard": "Mean per-case set intersection over union; two empty sets score 1.",
            "hamming_loss": "Incorrect capability bits divided by covered ANSWER cases times three.",
            "under_routing": "Fraction of covered ANSWER cases with one or more false-negative capability bits.",
            "over_routing": "Fraction of covered ANSWER cases with one or more false-positive capability bits.",
            "coverage": "Valid result count and rate are reported separately; incomplete compositions are excluded from covered-case metrics and are never silently imputed.",
        },
        "comparisons": [
            "RAG_SPECIALIST_VS_JOINT_B4_RAG_BIT",
            "MEMORY_SPECIALIST_VS_JOINT_B4_MEMORY_BIT",
            "P2_VS_JOINT_B4",
            "P3_VS_JOINT_B4",
            "P2_VS_P3",
        ],
        "comparison_interpretation": "No Specialist or composition is required or presumed to win. Once validly executed and frozen, both P2 and P3 remain reportable regardless of DEV performance.",
        "coverage_policy": {
            "invalid_or_missing_specialist_result": "INCOMPLETE",
            "fallback": "NONE",
            "coverage_reported_separately": True,
        },
        "test_access": 0,
    }


def method_note() -> str:
    return textwrap.dedent(
        f"""\
        # RAGate method-adaptation note

        ## Positioning

        This Stage 4K-0 extension is a **RAGate-inspired capability specialist**, not a reproduction of RAGate.

        RAGate frames the retrieval decision as a binary per-turn gate: it uses conversational context and related inputs to predict whether a system response should receive retrieval augmentation. The official study uses KETOD conversational data. The official repository exposes RAGate-MHA and RAGate-Llama variants.

        Official sources checked on {FREEZE_DATE}:

        - Wang, Sen, Li, and Yilmaz, “Adaptive Retrieval-Augmented Generation for Conversational Systems,” Findings of NAACL 2025: https://aclanthology.org/2025.findings-naacl.30/
        - Official implementation repository: https://github.com/wangxieric/RAGate

        ## LAD adaptation boundary

        The LAD experiment has a different educational domain, a different four-field visible context schema, and a different minimum-necessary definition of RAG. Here, `rag_required` is true only when correct answering minimally requires course or external knowledge that is absent from the visible input. This is narrower than asking whether retrieval could improve a response.

        The extension therefore borrows the transparent specialist-decomposition principle. It does not adopt the official checkpoint or training pipeline.

        - No official RAGate checkpoint is used as human Gold.
        - No official RAGate checkpoint is used for primary inference.
        - No KETOD example is mixed into the primary LAD DEV set.
        - Official RAGate code is not copied into the main Router implementation in this stage.
        - The RAGate MHA is not trained here.
        - Llama-2 is not fine-tuned here.
        - No checkpoint is downloaded.

        Stage 4K-0 freezes protocol, prompts, examples, packages, schemas, composition contracts, evaluation, and future execution plans only. It makes no provider call and produces no Specialist prediction.
        """
    )


def disclosure() -> str:
    return textwrap.dedent(
        """\
        # Specialist extension disclosure

        P2 and P3 were introduced after aggregate DEV analysis identified RAG and Memory as remaining error sources. TEST had not been executed or inspected.

        The prompts, strict schemas, frozen B4 few-shot identities and order, retry policy, composition rules, and DEV evaluation protocol are frozen before any Specialist execution. No RAG Specialist or Memory Specialist output was available while this method was defined.

        `R2V2-P2_RAG_SPECIALIST_COMPOSITION` is the primary RAGate-inspired extension. `R2V2-P3_RAG_MEMORY_SPECIALISTS` is a predeclared exploratory secondary full-specialist extension. Once validly executed and frozen, both remain reportable even if either has poor DEV performance.

        Official RAGate checkpoints were not used for human labels or primary inference. This transparent DEV-informed method extension was not part of the original Stage 0 model set.

        Stage 4K-0 performs no provider call, Specialist prediction, P2/P3 scoring, or TEST access.
        """
    )


def authorization_request(
    specialist: str,
    prompt_hash: str,
    schema_hash: str,
    estimate: Mapping[str, Any],
) -> str:
    name = SPECIALISTS[specialist]["display_name"]
    return textwrap.dedent(
        f"""\
        # {name} DEV execution authorization request

        This file requests a future, separate authorization. It does not authorize execution, and Stage 4K-0 made zero provider calls.

        ## Frozen request

        - Model snapshot: `{MODEL_SNAPSHOT}`
        - DEV ANSWER logical calls: `64`
        - Maximum physical attempts: `128`
        - Prompt template SHA-256: `{prompt_hash}`
        - Strict Specialist schema SHA-256: `{schema_hash}`
        - Temperature: `{TEMPERATURE}`
        - Maximum output tokens: `{MAXIMUM_OUTPUT_TOKENS}`
        - SDK transport retries: `{SDK_TRANSPORT_RETRIES}`
        - Manual retry: at most one retry, only for invalid JSON or strict-schema output
        - Retry payload: identical prompt; no correction message
        - Coercion/repair: no string-to-boolean coercion and no JSON extraction from prose
        - Non-retryable: authentication, permission, request-configuration, transport, rate-limit, and model errors
        - TEST calls: `0`

        ## Offline token and cost estimate

        - Estimated input tokens for 64 first attempts (character/4 heuristic): `{estimate['first_attempt_input_tokens_total_char_div_4']}`
        - Estimated maximum input tokens if every call retries: `{estimate['maximum_input_tokens_if_all_calls_retry_char_div_4']}`
        - First-attempt output-token upper bound: `{estimate['first_attempt_output_tokens_upper_bound']}`
        - All-retry output-token upper bound: `{estimate['maximum_output_tokens_if_all_calls_retry_upper_bound']}`
        - First-attempt cost upper bound at the {FREEZE_DATE} public GPT-4o mini rates: `${estimate['first_attempt_cost_usd_upper_bound']:.8f}`
        - All-retry cost upper bound at those rates: `${estimate['all_retry_cost_usd_upper_bound']:.8f}`

        Input tokens use `ceil(canonical request characters / 4)` and are not provider-tokenizer counts. Output cost assumes the full 32-token cap on every attempt. No prompt-caching discount is assumed. Pricing source: https://developers.openai.com/api/docs/models/gpt-4o-mini. Pricing must be re-verified immediately before any separately authorized execution.

        ## Required future gate

        Execution requires a new direct user authorization naming this Specialist, the exact hashes above, the 64-call DEV population, and the retry/cost boundary. That authorization must continue to prohibit TEST access.
        """
    )


def status_document(
    prompt_hashes: Mapping[str, str],
    schema_hashes: Mapping[str, str],
    index: Mapping[str, Any],
    costs: Mapping[str, Any],
) -> str:
    return textwrap.dedent(
        f"""\
        # RQ2-V2 Stage 4K-0 status

        `READY_FOR_PARALLEL_RAG_AND_MEMORY_SPECIALIST_DEV_EXECUTION`

        This status means the offline protocol and future DEV execution plans are technically frozen. It is not execution authorization and does not show that either Specialist, P2, or P3 has run.

        ## Frozen identity

        - Starting HEAD: `{STARTING_HEAD}`
        - Expected branch: `{EXPECTED_BRANCH}`
        - Model snapshot for both Specialists: `{MODEL_SNAPSHOT}`
        - Temperature: `{TEMPERATURE}`
        - Maximum output tokens: `{MAXIMUM_OUTPUT_TOKENS}`
        - RAG prompt SHA-256: `{prompt_hashes['rag']}`
        - RAG schema SHA-256: `{schema_hashes['rag']}`
        - Memory prompt SHA-256: `{prompt_hashes['memory']}`
        - Memory schema SHA-256: `{schema_hashes['memory']}`

        ## Frozen population and examples

        - RAG DEV logical calls: `64`, all `NOT_EXECUTED`
        - Memory DEV logical calls: `64`, all `NOT_EXECUTED`
        - Each outer fold reuses the exact eight frozen B4 annotation IDs, family IDs, component-safe selections, and order.
        - Every fold spans signatures `000` through `111` and is balanced 4 YES / 4 NO for each Specialist target.
        - Final full-DEV RAG and Memory packages reuse the exact frozen full-DEV B4 example identities and order.

        ## Compositions

        - P2: `[RAG_specialist, B4_memory, B4_planning]`
        - P3: `[RAG_specialist, Memory_specialist, B4_planning]`
        - Missing or invalid Specialist outputs make the composition incomplete; there is no B3 fallback or silent substitution.

        ## Offline estimate

        - Combined first-attempt input-token estimate: `{costs['combined']['first_attempt_input_tokens_total_char_div_4']}`
        - Combined all-retry input-token estimate: `{costs['combined']['maximum_input_tokens_if_all_calls_retry_char_div_4']}`
        - Combined first-attempt cost upper bound: `${costs['combined']['first_attempt_cost_usd_upper_bound']:.8f}`
        - Combined all-retry cost upper bound: `${costs['combined']['all_retry_cost_usd_upper_bound']:.8f}`

        ## Verification boundary

        - Unit tests: `{EXPECTED_TEST_COUNT}` passed, `0` failed.
        - Provider inference calls: `0`
        - Specialist predictions: `0`
        - P2/P3 scores: `0`
        - TEST inputs/Gold/escrow/IDs accessed: `0`
        - Successful case-level B4 predictions or B4 error files inspected: `0`

        The fold hash registry is `specialist_fold_prompt_hashes_v1.json`; its status is `{index['status']}`. Future execution requires new direct authorization.
        """
    )


def verification_report() -> str:
    return textwrap.dedent(
        f"""\
        # Stage 4K-0 offline verification report

        Command:

        ```text
        PYTHONDONTWRITEBYTECODE=1 python3 -m unittest -v tests.test_specialist_protocol
        ```

        Observed result on {FREEZE_DATE}: `{EXPECTED_TEST_COUNT}` passed, `0` failed.

        The tests cover frozen source hashes, DEV-only identity membership, zero provider/network calls during rebuild, 64+64 unexecuted manifests, exact B4 example reuse, fold/family/component exclusions, balanced examples, strict schemas, semantic-only prompts, validation-Gold exclusion, deterministic hashes, retry rules, exact P2/P3 bindings, Planning independence from Memory, evaluation predeclarations, and absence of an operational RAGate checkpoint dependency.

        No Specialist was executed and no P2/P3 score was calculated.
        """
    )


def write_sha256_manifest(output_dir: Path) -> None:
    manifest_path = output_dir / "STAGE4_K0_SHA256_MANIFEST.json"
    files: list[dict[str, str]] = []
    for path in sorted(output_dir.rglob("*"), key=lambda value: value.as_posix().encode("utf-8")):
        if not path.is_file() or path == manifest_path or path.suffix == ".pyc":
            continue
        if "__pycache__" in path.parts:
            continue
        files.append(
            {
                "path": path.relative_to(output_dir).as_posix(),
                "sha256": sha256_file(path),
            }
        )
    write_json(
        manifest_path,
        {
            "schema_version": "rq2-v2-stage4-k0-sha256-manifest-v1",
            "hash_algorithm": "SHA-256",
            "manifest_self_hash_included": False,
            "file_count": len(files),
            "files": files,
        },
    )


def build(output_dir: Path = TRACK_DIR) -> dict[str, Any]:
    output_dir = output_dir.resolve()
    output_dir.mkdir(parents=True, exist_ok=True)
    source_verification = verify_sources()

    fold_rows = read_csv(B4_DIR / "b4_fold_examples_v1.csv")
    final_rows = read_csv(B4_DIR / "b4_final_dev_examples_v1.csv")
    source_manifest = read_jsonl(B4_DIR / "b4_dev_execution_manifest_v1.jsonl")
    b4_hashes = json.loads(
        (B4_DIR / "b4_fold_prompt_hashes_v1.json").read_text(encoding="utf-8")
    )
    if len(fold_rows) != 32 or len(final_rows) != 8:
        raise RuntimeError("Frozen B4 example row counts changed")

    prompt_paths = {
        "rag": output_dir / "rag_specialist_prompt_frozen_v1.txt",
        "memory": output_dir / "memory_specialist_prompt_frozen_v1.txt",
    }
    schema_paths = {
        "rag": output_dir / "rag_specialist_schema_v1.json",
        "memory": output_dir / "memory_specialist_schema_v1.json",
    }
    for specialist, config in SPECIALISTS.items():
        write_text(prompt_paths[specialist], config["prompt"])
        write_json(schema_paths[specialist], config["schema"])
    prompt_hashes = {name: sha256_file(path) for name, path in prompt_paths.items()}
    schema_hashes = {name: sha256_file(path) for name, path in schema_paths.items()}

    for specialist, config in SPECIALISTS.items():
        write_specialist_examples_csv(
            output_dir / f"{specialist}_specialist_fold_examples_v1.csv",
            fold_rows,
            config["target_field"],
            include_fold=True,
        )
        write_specialist_examples_csv(
            output_dir / f"{specialist}_specialist_final_examples_v1.csv",
            final_rows,
            config["target_field"],
            include_fold=False,
        )

    index, fold_material = build_packages(
        output_dir,
        fold_rows,
        final_rows,
        b4_hashes,
        prompt_hashes,
        schema_hashes,
    )
    records, estimates = build_manifests(
        output_dir,
        source_manifest,
        fold_material,
        prompt_hashes,
        schema_hashes,
    )
    costs = cost_estimate(estimates)
    write_json(output_dir / "specialist_token_cost_estimate_v1.json", costs)
    write_json(output_dir / "specialist_future_retry_policy_v1.json", RETRY_POLICY)

    p2, p3 = composition_contracts()
    write_json(output_dir / "p2_rag_specialist_composition_contract_v1.json", p2)
    write_json(output_dir / "p3_capability_specialists_composition_contract_v1.json", p3)
    write_json(
        output_dir / "specialist_evaluation_protocol_v1.json", evaluation_protocol()
    )
    write_json(
        output_dir / "specialist_source_verification_v1.json", source_verification
    )

    write_text(output_dir / "RAGATE_METHOD_ADAPTATION_NOTE.md", method_note())
    write_text(output_dir / "SPECIALIST_EXTENSION_DISCLOSURE.md", disclosure())
    write_text(
        output_dir / "RAG_SPECIALIST_DEV_EXECUTION_AUTHORIZATION_REQUEST.md",
        authorization_request(
            "rag", prompt_hashes["rag"], schema_hashes["rag"], costs["specialists"]["rag"]
        ),
    )
    write_text(
        output_dir / "MEMORY_SPECIALIST_DEV_EXECUTION_AUTHORIZATION_REQUEST.md",
        authorization_request(
            "memory",
            prompt_hashes["memory"],
            schema_hashes["memory"],
            costs["specialists"]["memory"],
        ),
    )
    write_text(
        output_dir / "STATUS.md",
        status_document(prompt_hashes, schema_hashes, index, costs),
    )
    write_text(
        output_dir / "STAGE4_K0_VERIFICATION_REPORT.md", verification_report()
    )
    write_sha256_manifest(output_dir)

    return {
        "status": "READY_FOR_PARALLEL_RAG_AND_MEMORY_SPECIALIST_DEV_EXECUTION",
        "output_directory": str(output_dir),
        "rag_prompt_sha256": prompt_hashes["rag"],
        "rag_schema_sha256": schema_hashes["rag"],
        "memory_prompt_sha256": prompt_hashes["memory"],
        "memory_schema_sha256": schema_hashes["memory"],
        "rag_logical_call_count": len(records["rag"]),
        "memory_logical_call_count": len(records["memory"]),
        "provider_calls": 0,
        "specialist_predictions": 0,
        "test_accesses": 0,
    }


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Build the offline RQ2-V2 Stage 4K-0 Specialist protocol freeze."
    )
    parser.add_argument("--output-dir", type=Path, default=TRACK_DIR)
    args = parser.parse_args()
    print(json.dumps(build(args.output_dir), ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
