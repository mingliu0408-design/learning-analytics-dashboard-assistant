"""One-time, offline, fail-closed Stage 5E final TEST scoring implementation."""

from __future__ import annotations

from collections import Counter, defaultdict
import csv
from datetime import datetime, timezone
import hashlib
import io
import json
import os
from pathlib import Path
import tempfile
from typing import Any, Iterable, Mapping, Sequence
import uuid
import zipfile

from evaluation.capability_routing_rq2_v2_stage4.final_router_selection.selection_rule import (
    COVERAGE_FIELDS,
    METHOD_TIER_NUMBERS,
    select_final_router,
)

from . import compositions
from .constants import (
    ACCESS_RECEIPT_PATH,
    ALL_METHOD_IDS,
    B4_PATH,
    BINDING_PATH,
    BOOTSTRAP_REPLICATES,
    BOOTSTRAP_SEED,
    CACHED_INPUT_USD_PER_MILLION,
    COMPLETE_METHOD_IDS,
    DETERMINISTIC_METHOD_IDS,
    DETERMINISTIC_PATH,
    ELIGIBILITY_PATH,
    ELIGIBILITY_SHA256,
    ELIGIBLE_METHOD_IDS,
    ESCROW_MEMBER_ALLOWLIST,
    ESCROW_MEMBER_HASHES,
    ESCROW_ZIP,
    ESCROW_ZIP_SHA256,
    EXPECTED_BRANCH,
    EXPECTED_WORKTREE,
    FINAL_SCORING_DIR,
    INPUT_USD_PER_MILLION,
    INTEGRATED_COMMITS,
    MEMORY_SPECIALIST_PATH,
    METHOD_REGISTRY_PATH,
    METHOD_REGISTRY_SHA256,
    MODEL_ID,
    OUTPUT_USD_PER_MILLION,
    PREDICTION_HASHES,
    PRE_SCORING_RECEIPT_PATH,
    PROJECT_ROOT,
    RAG_SPECIALIST_PATH,
    SCORING_PROTOCOL_PATH,
    SCORING_PROTOCOL_SHA256,
    SELECTION_RULE_PATH,
    SELECTION_RULE_SHA256,
    STAGE4_TEST_INPUT_DIR,
    STAGE4_TEST_INPUT_HASHES,
    STARTING_HEAD,
    TEST_GOLD_FIELDS,
)
from .metrics import (
    Signature,
    bootstrap_analysis,
    capability_contrast_metrics,
    clarification_metrics,
    compare_component_to_b4,
    component_metrics,
    core_metrics,
    end_to_end_metrics,
    gold_signature,
    signature_text,
)


class Stage5EError(RuntimeError):
    """A fail-closed Stage 5E contract violation."""


def canonical_json_bytes(value: Any) -> bytes:
    return (
        json.dumps(value, ensure_ascii=False, sort_keys=True, indent=2) + "\n"
    ).encode("utf-8")


def compact_json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def read_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def read_jsonl(path: Path) -> list[dict[str, Any]]:
    return [
        json.loads(line)
        for line in path.read_text(encoding="utf-8").splitlines()
        if line
    ]


def write_json(path: Path, value: Any) -> None:
    path.write_bytes(canonical_json_bytes(value))


def write_jsonl(path: Path, rows: Sequence[Mapping[str, Any]]) -> None:
    data = "".join(
        json.dumps(dict(row), ensure_ascii=False, sort_keys=True, separators=(",", ":"))
        + "\n"
        for row in rows
    ).encode("utf-8")
    path.write_bytes(data)


def _csv_value(value: Any) -> Any:
    if isinstance(value, (dict, list, tuple)):
        return compact_json(value)
    if value is None:
        return "NOT_APPLICABLE"
    if type(value) is bool:
        return "true" if value else "false"
    return value


def write_csv(path: Path, rows: Sequence[Mapping[str, Any]], fieldnames: Sequence[str]) -> None:
    buffer = io.StringIO(newline="")
    writer = csv.DictWriter(
        buffer,
        fieldnames=list(fieldnames),
        extrasaction="raise",
        lineterminator="\n",
    )
    writer.writeheader()
    for row in rows:
        writer.writerow({key: _csv_value(row.get(key)) for key in fieldnames})
    path.write_text(buffer.getvalue(), encoding="utf-8", newline="")


def write_once_json(path: Path, value: Any) -> None:
    """Publish complete bytes atomically, refusing an existing destination."""

    if path.exists():
        raise Stage5EError(f"write-once destination already exists: {path}")
    data = canonical_json_bytes(value)
    temporary = path.with_name(f".{path.name}.{os.getpid()}.{uuid.uuid4().hex}.tmp")
    try:
        with temporary.open("xb") as handle:
            handle.write(data)
            handle.flush()
            os.fsync(handle.fileno())
        try:
            os.link(temporary, path)
        except FileExistsError as exc:
            raise Stage5EError(f"write-once destination already exists: {path}") from exc
        directory_fd = os.open(path.parent, os.O_RDONLY)
        try:
            os.fsync(directory_fd)
        finally:
            os.close(directory_fd)
    finally:
        if temporary.exists():
            temporary.unlink()


def _unique_by_id(rows: Iterable[Mapping[str, Any]], label: str) -> dict[str, dict[str, Any]]:
    result: dict[str, dict[str, Any]] = {}
    for source in rows:
        row = dict(source)
        case_id = row.get("annotation_case_id")
        if not isinstance(case_id, str) or not case_id or case_id in result:
            raise Stage5EError(f"{label} annotation IDs must be nonempty and unique")
        result[case_id] = row
    return result


def _verify_hash(path: Path, expected: str, label: str) -> str:
    actual = sha256_file(path)
    if actual != expected:
        raise Stage5EError(f"{label} SHA-256 mismatch: {actual} != {expected}")
    return actual


def verify_frozen_sources() -> dict[str, str]:
    actual: dict[str, str] = {}
    for relative, expected in PREDICTION_HASHES.items():
        path = PROJECT_ROOT / relative
        actual[relative] = _verify_hash(path, expected, relative)
    for path, expected in (
        (ELIGIBILITY_PATH, ELIGIBILITY_SHA256),
        (SELECTION_RULE_PATH, SELECTION_RULE_SHA256),
        (METHOD_REGISTRY_PATH, METHOD_REGISTRY_SHA256),
        (SCORING_PROTOCOL_PATH, SCORING_PROTOCOL_SHA256),
        (ESCROW_ZIP, ESCROW_ZIP_SHA256),
    ):
        actual[str(path)] = _verify_hash(path, expected, str(path))
    for name, expected in STAGE4_TEST_INPUT_HASHES.items():
        path = STAGE4_TEST_INPUT_DIR / name
        actual[str(path.relative_to(PROJECT_ROOT))] = _verify_hash(path, expected, name)
    if BINDING_PATH.exists():
        raise Stage5EError("write-once RQ3 binding already exists")
    return actual


def _provider_rows(
    path: Path,
    *,
    label: str,
    method_id: str,
    prediction_keys: set[str],
) -> dict[str, dict[str, Any]]:
    rows = _unique_by_id(read_jsonl(path), label)
    if len(rows) != 36:
        raise Stage5EError(f"{label} must contain exactly 36 records")
    for case_id, row in rows.items():
        if row.get("method_id") != method_id:
            raise Stage5EError(f"{label} method identity mismatch: {case_id}")
        if row.get("execution_status") != "VALID_PREDICTION":
            raise Stage5EError(f"{label} invalid execution status: {case_id}")
        if row.get("scoring_performed") is not False:
            raise Stage5EError(f"{label} was already scored: {case_id}")
        if row.get("physical_attempts") != 1:
            raise Stage5EError(f"{label} retry/attempt count differs: {case_id}")
        prediction = row.get("prediction")
        if not isinstance(prediction, dict) or set(prediction) != prediction_keys:
            raise Stage5EError(f"{label} strict prediction schema failed: {case_id}")
        if any(type(prediction[key]) is not bool for key in prediction_keys):
            raise Stage5EError(f"{label} prediction bit is not boolean: {case_id}")
        attempts = row.get("attempt_records")
        if not isinstance(attempts, list) or len(attempts) != 1:
            raise Stage5EError(f"{label} attempt record count differs: {case_id}")
        attempt = attempts[0]
        if (
            attempt.get("outcome") != "VALID"
            or attempt.get("provider_error") is not None
            or attempt.get("validation_error") is not None
            or attempt.get("returned_model") != MODEL_ID
            or attempt.get("prediction") != prediction
        ):
            raise Stage5EError(f"{label} terminal attempt integrity failed: {case_id}")
        usage = attempt.get("usage")
        if not isinstance(usage, dict) or set(usage) != {
            "input_tokens",
            "output_tokens",
            "total_tokens",
        }:
            raise Stage5EError(f"{label} usage schema failed: {case_id}")
        if any(type(usage[key]) is not int or usage[key] < 0 for key in usage):
            raise Stage5EError(f"{label} usage value failed: {case_id}")
        if usage["input_tokens"] + usage["output_tokens"] != usage["total_tokens"]:
            raise Stage5EError(f"{label} usage arithmetic failed: {case_id}")
    return rows


def load_frozen_predictions() -> dict[str, Any]:
    deterministic = _unique_by_id(read_jsonl(DETERMINISTIC_PATH), "deterministic")
    if len(deterministic) != 36:
        raise Stage5EError("deterministic predictions must contain exactly 36 records")
    required = set(DETERMINISTIC_METHOD_IDS)
    for case_id, row in deterministic.items():
        if (
            row.get("execution_status") != "VALID_PREDICTIONS"
            or row.get("provider_calls") != 0
            or row.get("scoring_performed") is not False
        ):
            raise Stage5EError(f"deterministic terminal integrity failed: {case_id}")
        methods = row.get("method_predictions")
        if not isinstance(methods, dict) or set(methods) != required:
            raise Stage5EError(f"deterministic seven-method universe differs: {case_id}")
        for method_id, prediction in methods.items():
            if method_id == "R2V2-CG1_CLARIFICATION_RULE":
                if prediction.get("dialogue_action") not in {"ANSWER", "CLARIFY"}:
                    raise Stage5EError(f"invalid clarification prediction: {case_id}")
            else:
                compositions.signature(prediction)
    b4 = _provider_rows(
        B4_PATH,
        label="B4",
        method_id="R2V2-B4_JOINT_LLM",
        prediction_keys={"rag_required", "memory_required", "planning_required"},
    )
    rag = _provider_rows(
        RAG_SPECIALIST_PATH,
        label="RAG Specialist",
        method_id="R2V2-RAG_SPECIALIST",
        prediction_keys={"rag_required"},
    )
    memory = _provider_rows(
        MEMORY_SPECIALIST_PATH,
        label="Memory Specialist",
        method_id="R2V2-MEMORY_SPECIALIST",
        prediction_keys={"memory_required"},
    )
    id_sets = {frozenset(value) for value in (deterministic, b4, rag, memory)}
    if len(id_sets) != 1:
        raise Stage5EError("prediction annotation ID sets differ")
    if sum(len(row["method_predictions"]) for row in deterministic.values()) != 252:
        raise Stage5EError("deterministic method output count differs from 252")
    return {"deterministic": deterministic, "b4": b4, "rag": rag, "memory": memory}


def _extract_escrow_once(access_timestamp: str) -> tuple[Path, dict[str, str]]:
    extraction_dir = Path(tempfile.mkdtemp(prefix="rq2_v2_stage5e_gold_", dir="/tmp"))
    member_hashes: dict[str, str] = {}
    try:
        with zipfile.ZipFile(ESCROW_ZIP, "r") as archive:
            infos = archive.infolist()
            names = [item.filename for item in infos]
            if len(names) != len(set(names)) or tuple(sorted(names)) != ESCROW_MEMBER_ALLOWLIST:
                raise Stage5EError("escrow ZIP exact member allowlist differs")
            if any(
                item.is_dir()
                or Path(item.filename).name != item.filename
                or item.filename.startswith(("/", "\\"))
                for item in infos
            ):
                raise Stage5EError("escrow ZIP contains an unsafe member path")
            bad = archive.testzip()
            if bad is not None:
                raise Stage5EError(f"escrow ZIP CRC failure: {bad}")
            for name in names:
                data = archive.read(name)
                digest = sha256_bytes(data)
                expected = ESCROW_MEMBER_HASHES[name]
                if digest != expected:
                    raise Stage5EError(f"escrow member hash mismatch: {name}")
                member_hashes[name] = digest
                (extraction_dir / name).write_bytes(data)
    except Exception:
        # Preserve any partial extraction directory as failure evidence.
        raise
    if not access_timestamp:
        raise Stage5EError("Gold access timestamp was not captured")
    return extraction_dir, member_hashes


def _parse_gold(extraction_dir: Path) -> tuple[list[dict[str, str]], dict[str, Any]]:
    csv_path = extraction_dir / "test_gold_escrow_v1.csv"
    jsonl_path = extraction_dir / "test_gold_escrow_v1.jsonl"
    with csv_path.open("r", encoding="utf-8-sig", newline="") as handle:
        reader = csv.DictReader(handle)
        if tuple(reader.fieldnames or ()) != TEST_GOLD_FIELDS:
            raise Stage5EError("TEST Gold CSV schema differs from the frozen field order")
        csv_rows = list(reader)
    jsonl_rows = read_jsonl(jsonl_path)
    if any(tuple(row) != TEST_GOLD_FIELDS for row in jsonl_rows):
        raise Stage5EError("TEST Gold JSONL schema differs from the frozen field order")
    if csv_rows != jsonl_rows:
        raise Stage5EError("TEST Gold CSV and JSONL values differ")
    by_id = _unique_by_id(csv_rows, "TEST Gold")
    if len(by_id) != 36:
        raise Stage5EError("TEST Gold must contain exactly 36 unique cases")
    families: dict[str, list[dict[str, str]]] = defaultdict(list)
    for row in csv_rows:
        case_id = row["annotation_case_id"]
        family_id = row["canonical_scenario_family_id"]
        if not family_id:
            raise Stage5EError(f"TEST Gold family identity is empty: {case_id}")
        families[family_id].append(row)
        if row["final_case_validity"] != "INCLUDE_VALID_CASE":
            raise Stage5EError(f"TEST Gold contains an excluded/invalid case: {case_id}")
        if row["final_dialogue_action"] not in {"ANSWER", "CLARIFY"}:
            raise Stage5EError(f"invalid TEST Gold dialogue action: {case_id}")
        capability_values = (
            row["final_rag_required"],
            row["final_memory_required"],
            row["final_planning_required"],
        )
        if row["final_dialogue_action"] == "ANSWER":
            if any(value not in {"YES", "NO"} for value in capability_values):
                raise Stage5EError(f"invalid TEST Gold capability label: {case_id}")
            expected_signature = "".join("1" if value == "YES" else "0" for value in capability_values)
        else:
            if capability_values != ("NOT_APPLICABLE",) * 3:
                raise Stage5EError(f"CLARIFY capabilities must be NOT_APPLICABLE: {case_id}")
            expected_signature = "CLARIFY"
        if row["final_family_routing_signature"] != expected_signature:
            raise Stage5EError(f"family routing signature mismatch: {case_id}")
        if (
            row["partition"] != "TEST"
            or row["split_seed"] != "20260830"
            or row["split_version"] != "RQ2_V2_CONTRAST_SAFE_SPLIT_V1"
            or row["split_status"] != "FROZEN_PRE_MODEL_DEVELOPMENT_SPLIT"
            or row["escrow_status"] != "FROZEN_NOT_FOR_MODEL_DEVELOPMENT"
        ):
            raise Stage5EError(f"TEST Gold freeze metadata mismatch: {case_id}")
    if len(families) != 18 or any(len(items) != 2 for items in families.values()):
        raise Stage5EError("TEST Gold must contain exactly 18 two-utterance families")
    for family_id, items in families.items():
        if len({row["utterance_id"] for row in items}) != 2:
            raise Stage5EError(f"family does not contain two unique utterances: {family_id}")
        if len({row["final_family_routing_signature"] for row in items}) != 1:
            raise Stage5EError(f"family Gold signature is inconsistent: {family_id}")
    summary = {
        "case_count": len(csv_rows),
        "unique_annotation_id_count": len(by_id),
        "family_count": len(families),
        "utterances_per_family": 2,
        "gold_answer_case_count": sum(row["final_dialogue_action"] == "ANSWER" for row in csv_rows),
        "gold_clarify_case_count": sum(row["final_dialogue_action"] == "CLARIFY" for row in csv_rows),
        "family_signature_distribution": dict(
            sorted(Counter(items[0]["final_family_routing_signature"] for items in families.values()).items())
        ),
        "capability_distributions_on_answer_cases": {
            key: dict(
                sorted(
                    Counter(
                        row[field]
                        for row in csv_rows
                        if row["final_dialogue_action"] == "ANSWER"
                    ).items()
                )
            )
            for key, field in (
                ("RAG", "final_rag_required"),
                ("Memory", "final_memory_required"),
                ("Planning", "final_planning_required"),
            )
        },
        "page_distribution": dict(sorted(Counter(row["current_page"] for row in csv_rows).items())),
        "writer_distribution": dict(sorted(Counter(row["writer_id"] for row in csv_rows).items())),
        "contrast_axis_distribution": dict(
            sorted(Counter(row["contrast_axis"] or "NONE" for row in csv_rows).items())
        ),
        "contrast_group_case_distribution": dict(
            sorted(Counter(row["contrast_group_id"] or "NONE" for row in csv_rows).items())
        ),
        "excluded_case_count": 0,
    }
    return csv_rows, summary


def _yes_no(value: str) -> bool:
    if value not in {"YES", "NO"}:
        raise Stage5EError(f"expected YES/NO, received {value!r}")
    return value == "YES"


def build_normalized_records(
    gold_rows: Sequence[Mapping[str, str]], frozen: Mapping[str, Any]
) -> tuple[list[dict[str, Any]], dict[str, dict[str, Signature]], dict[str, Any]]:
    prediction_ids = set(frozen["deterministic"])
    gold_ids = {row["annotation_case_id"] for row in gold_rows}
    if gold_ids != prediction_ids:
        raise Stage5EError("every TEST prediction must join Gold exactly once")
    normalized: list[dict[str, Any]] = []
    predictions_by_method = {method_id: {} for method_id in COMPLETE_METHOD_IDS}
    p1_metadata: dict[str, Any] = {}
    for gold in sorted(gold_rows, key=lambda row: row["annotation_case_id"].encode("utf-8")):
        case_id = gold["annotation_case_id"]
        deterministic = frozen["deterministic"][case_id]["method_predictions"]
        b4_row = frozen["b4"][case_id]
        rag_row = frozen["rag"][case_id]
        memory_row = frozen["memory"][case_id]
        methods, metadata = compositions.compose_case(
            deterministic,
            b4_row["prediction"],
            rag_row["prediction"],
            memory_row["prediction"],
        )
        if set(methods) != set(COMPLETE_METHOD_IDS):
            raise Stage5EError(f"complete method universe differs: {case_id}")
        for method_id, prediction in methods.items():
            predictions_by_method[method_id][case_id] = prediction
        p1_metadata[case_id] = metadata
        answer = gold["final_dialogue_action"] == "ANSWER"
        normalized.append(
            {
                "annotation_case_id": case_id,
                "canonical_scenario_family_id": gold["canonical_scenario_family_id"],
                "utterance_id": gold["utterance_id"],
                "writer_id": gold["writer_id"],
                "current_page": gold["current_page"],
                "contrast_group_id": gold["contrast_group_id"],
                "contrast_axis": gold["contrast_axis"],
                "gold_dialogue_action": gold["final_dialogue_action"],
                "gold_rag_required": _yes_no(gold["final_rag_required"]) if answer else None,
                "gold_memory_required": _yes_no(gold["final_memory_required"]) if answer else None,
                "gold_planning_required": _yes_no(gold["final_planning_required"]) if answer else None,
                "frozen_clarification_prediction": deterministic[
                    "R2V2-CG1_CLARIFICATION_RULE"
                ]["dialogue_action"],
                "d0_prediction": compositions.signature_dict(methods["R2V2-D0_ALWAYS_ON"]),
                "d1_prediction": compositions.signature_dict(methods["R2V2-D1_NEVER_ON"]),
                "b0_prediction": compositions.signature_dict(methods["R2V2-B0_RULE"]),
                "b1_prediction": compositions.signature_dict(methods["R2V2-B1_LEGACY_INTENT"]),
                "b2_prediction": compositions.signature_dict(methods["R2V2-B2_PROTOTYPE"]),
                "b3_prediction": compositions.signature_dict(methods["R2V2-B3_OVR"]),
                "b4_prediction": compositions.signature_dict(methods["R2V2-B4_JOINT_LLM"]),
                "rag_specialist_prediction": rag_row["prediction"],
                "memory_specialist_prediction": memory_row["prediction"],
                "b4_per_case_usage": b4_row["attempt_records"][0]["usage"],
                "rag_specialist_per_case_usage": rag_row["attempt_records"][0]["usage"],
                "memory_specialist_per_case_usage": memory_row["attempt_records"][0]["usage"],
                "p1_policy": metadata,
            }
        )
    return normalized, predictions_by_method, p1_metadata


NORMALIZED_FIELDS = (
    "annotation_case_id",
    "canonical_scenario_family_id",
    "utterance_id",
    "writer_id",
    "current_page",
    "contrast_group_id",
    "contrast_axis",
    "gold_dialogue_action",
    "gold_rag_required",
    "gold_memory_required",
    "gold_planning_required",
    "frozen_clarification_prediction",
    "d0_prediction",
    "d1_prediction",
    "b0_prediction",
    "b1_prediction",
    "b2_prediction",
    "b3_prediction",
    "b4_prediction",
    "rag_specialist_prediction",
    "memory_specialist_prediction",
    "b4_per_case_usage",
    "rag_specialist_per_case_usage",
    "memory_specialist_per_case_usage",
    "p1_policy",
)


def complete_prediction_rows(
    normalized: Sequence[Mapping[str, Any]],
    predictions: Mapping[str, Mapping[str, Signature]],
    p1_metadata: Mapping[str, Any],
) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    ids = [row["annotation_case_id"] for row in normalized]
    for method_id in COMPLETE_METHOD_IDS:
        if set(predictions[method_id]) != set(ids):
            raise Stage5EError(f"complete prediction coverage failed: {method_id}")
        for case_id in ids:
            value = predictions[method_id][case_id]
            rows.append(
                {
                    "method_id": method_id,
                    "annotation_case_id": case_id,
                    "rag_required": value[0],
                    "memory_required": value[1],
                    "planning_required": value[2],
                    "complete_signature": signature_text(value),
                    "prediction_status": "FROZEN_COMPLETE_NO_IMPUTATION",
                    "frozen_method_status": (
                        "POST_DEV_EXPLORATORY_ABLATION"
                        if method_id == "R2V2-P4_MEMORY_SPECIALIST_COMPOSITION"
                        else "FROZEN_PRE_TEST_COMPLETE_METHOD"
                    ),
                    "p1_triggered": (
                        p1_metadata[case_id]["p1_triggered"]
                        if method_id == "R2V2-P1_HYBRID"
                        else None
                    ),
                    "p1_selected_complete_signature_source": (
                        p1_metadata[case_id]["p1_selected_complete_signature_source"]
                        if method_id == "R2V2-P1_HYBRID"
                        else None
                    ),
                    "selection_eligibility": (
                        "INELIGIBLE_POST_DEV_EXPLORATORY"
                        if method_id == "R2V2-P4_MEMORY_SPECIALIST_COMPOSITION"
                        else (
                            "ELIGIBLE_SUBJECT_TO_COVERAGE_GATE"
                            if method_id in ELIGIBLE_METHOD_IDS
                            else "INELIGIBLE_DIAGNOSTIC"
                        )
                    ),
                }
            )
    return rows


COMPLETE_PREDICTION_FIELDS = (
    "method_id",
    "annotation_case_id",
    "rag_required",
    "memory_required",
    "planning_required",
    "complete_signature",
    "prediction_status",
    "frozen_method_status",
    "p1_triggered",
    "p1_selected_complete_signature_source",
    "selection_eligibility",
)


def _usage_totals(
    ids: Iterable[str], normalized_by_id: Mapping[str, Mapping[str, Any]], components: Sequence[str]
) -> dict[str, Any]:
    fields = {
        "B4": "b4_per_case_usage",
        "RAG_SPECIALIST": "rag_specialist_per_case_usage",
        "MEMORY_SPECIALIST": "memory_specialist_per_case_usage",
    }
    ids_list = list(ids)
    input_tokens = output_tokens = total_tokens = 0
    for case_id in ids_list:
        for component in components:
            usage = normalized_by_id[case_id][fields[component]]
            input_tokens += usage["input_tokens"]
            output_tokens += usage["output_tokens"]
            total_tokens += usage["total_tokens"]
    standard_cost = (
        input_tokens * INPUT_USD_PER_MILLION
        + output_tokens * OUTPUT_USD_PER_MILLION
    ) / 1_000_000
    cached_lower = (
        input_tokens * CACHED_INPUT_USD_PER_MILLION
        + output_tokens * OUTPUT_USD_PER_MILLION
    ) / 1_000_000
    return {
        "provider_component_call_count": len(ids_list) * len(components),
        "component_methods": list(components),
        "input_tokens": input_tokens,
        "output_tokens": output_tokens,
        "total_tokens": total_tokens,
        "counterfactual_token_cost": standard_cost,
        "standard_uncached_input_approximate_cost_usd": standard_cost,
        "all_cached_input_theoretical_lower_bound_usd": cached_lower,
        "exact_billed_cost_available": False,
    }


def cost_analysis(
    normalized: Sequence[Mapping[str, Any]], p1_metadata: Mapping[str, Any]
) -> dict[str, Any]:
    by_id = {row["annotation_case_id"]: row for row in normalized}
    all_ids = list(by_id)
    answer_ids = [
        case_id for case_id, row in by_id.items() if row["gold_dialogue_action"] == "ANSWER"
    ]
    gate_answer_ids = [
        case_id
        for case_id, row in by_id.items()
        if row["frozen_clarification_prediction"] == "ANSWER"
    ]
    actual_streams = {
        "B4": _usage_totals(all_ids, by_id, ("B4",)),
        "RAG_SPECIALIST": _usage_totals(all_ids, by_id, ("RAG_SPECIALIST",)),
        "MEMORY_SPECIALIST": _usage_totals(all_ids, by_id, ("MEMORY_SPECIALIST",)),
    }
    for value in actual_streams.values():
        value["logical_calls"] = value.pop("provider_component_call_count")
        value["physical_attempts"] = value["logical_calls"]
        value["retries"] = 0
    zero = {
        "provider_component_call_count": 0,
        "component_methods": [],
        "input_tokens": 0,
        "output_tokens": 0,
        "total_tokens": 0,
        "counterfactual_token_cost": 0.0,
        "standard_uncached_input_approximate_cost_usd": 0.0,
        "all_cached_input_theoretical_lower_bound_usd": 0.0,
        "exact_billed_cost_available": False,
    }

    def deployment(ids: list[str]) -> dict[str, Any]:
        p1_ids = [case_id for case_id in ids if p1_metadata[case_id]["p1_triggered"]]
        return {
            **{method_id: dict(zero) for method_id in COMPLETE_METHOD_IDS[:6]},
            "R2V2-B4_JOINT_LLM": _usage_totals(ids, by_id, ("B4",)),
            "R2V2-P1_HYBRID": _usage_totals(p1_ids, by_id, ("B4",)),
            "R2V2-P2_RAG_SPECIALIST_COMPOSITION": _usage_totals(
                ids, by_id, ("B4", "RAG_SPECIALIST")
            ),
            "R2V2-P3_RAG_MEMORY_SPECIALISTS": _usage_totals(
                ids, by_id, ("B4", "RAG_SPECIALIST", "MEMORY_SPECIALIST")
            ),
            "R2V2-P4_MEMORY_SPECIALIST_COMPOSITION": _usage_totals(
                ids, by_id, ("B4", "MEMORY_SPECIALIST")
            ),
        }

    total_actual = {
        "logical_calls": sum(value["logical_calls"] for value in actual_streams.values()),
        "physical_attempts": sum(value["physical_attempts"] for value in actual_streams.values()),
        "input_tokens": sum(value["input_tokens"] for value in actual_streams.values()),
        "output_tokens": sum(value["output_tokens"] for value in actual_streams.values()),
        "total_tokens": sum(value["total_tokens"] for value in actual_streams.values()),
        "standard_uncached_input_approximate_cost_usd": sum(
            value["standard_uncached_input_approximate_cost_usd"]
            for value in actual_streams.values()
        ),
        "exact_billed_cost_available": False,
    }
    return {
        "schema_version": "rq2-v2-stage5e-final-cost-and-calls-v1",
        "pricing_reference_date": "2026-08-31",
        "pricing_usd_per_million_tokens": {
            "standard_input": INPUT_USD_PER_MILLION,
            "cached_input": CACHED_INPUT_USD_PER_MILLION,
            "output": OUTPUT_USD_PER_MILLION,
        },
        "stage5e_new_provider_calls": 0,
        "actual_historical_test_execution": {
            "streams": actual_streams,
            "total": total_actual,
            "interpretation": "Historical frozen TEST execution; not deployment-conditioned usage.",
        },
        "counterfactual_gold_answer_core_population": {
            "population_count": len(answer_ids),
            "methods": deployment(answer_ids),
        },
        "counterfactual_gate_conditioned_end_to_end_deployment": {
            "gate_predicted_answer_count": len(gate_answer_ids),
            "methods": deployment(gate_answer_ids),
        },
        "actual_and_counterfactual_calls_mixed": False,
        "exact_billed_cost_claimed": False,
    }


def _runtime_composition(method_id: str) -> dict[str, Any]:
    values = {
        "R2V2-B0_RULE": {"core": "R2V2-B0_RULE"},
        "R2V2-B1_LEGACY_INTENT": {"core": "R2V2-B1_LEGACY_INTENT"},
        "R2V2-B2_PROTOTYPE": {"core": "R2V2-B2_PROTOTYPE"},
        "R2V2-B3_OVR": {"core": "R2V2-B3_OVR"},
        "R2V2-B4_JOINT_LLM": {"core": "R2V2-B4_JOINT_LLM"},
        "R2V2-P1_HYBRID": {
            "policy": "P1-C08-NONUNANIMOUS",
            "trigger": "not(B0_complete_signature == B2_complete_signature == B3_complete_signature)",
            "triggered_source": "R2V2-B4_JOINT_LLM complete signature",
            "nontriggered_source": "R2V2-B3_OVR complete signature",
            "label_level_mixing": False,
        },
        "R2V2-P2_RAG_SPECIALIST_COMPOSITION": {
            "RAG": "R2V2-RAG_SPECIALIST",
            "Memory": "R2V2-B4_JOINT_LLM",
            "Planning": "R2V2-B4_JOINT_LLM",
        },
        "R2V2-P3_RAG_MEMORY_SPECIALISTS": {
            "RAG": "R2V2-RAG_SPECIALIST",
            "Memory": "R2V2-MEMORY_SPECIALIST",
            "Planning": "R2V2-B4_JOINT_LLM",
        },
    }
    if method_id not in values:
        raise Stage5EError(f"selected method has no frozen RQ3 composition: {method_id}")
    return values[method_id]


def _method_table(
    registry: Mapping[str, Any],
    core: Mapping[str, Any],
    clarification: Mapping[str, Any],
    components: Mapping[str, Any],
    end_to_end: Mapping[str, Any],
    costs: Mapping[str, Any],
) -> list[dict[str, Any]]:
    registry_by_id = {row["method_id"]: row for row in registry["methods"]}
    rows: list[dict[str, Any]] = []
    for method_id in ALL_METHOD_IDS:
        source = registry_by_id[method_id]
        base = {
            "method_id": method_id,
            "method_tier": source["method_tier"],
            "reporting_tier": source["reporting_tier"],
            "development_status": source["development_status"],
            "confirmatory_exploratory_role": source["confirmatory_exploratory_role"],
            "test_reporting_status": "SCORED_FROZEN",
            "selectable": method_id in ELIGIBLE_METHOD_IDS,
            "frozen_method_status": (
                "POST_DEV_EXPLORATORY_ABLATION"
                if method_id == "R2V2-P4_MEMORY_SPECIALIST_COMPOSITION"
                else "PRESERVED_FROM_FROZEN_REGISTRY"
            ),
        }
        if method_id in COMPLETE_METHOD_IDS:
            metric = core["methods"][method_id]
            end = end_to_end["methods"][method_id]
            cost = costs["counterfactual_gold_answer_core_population"]["methods"][method_id]
            base.update(
                {
                    "row_role": "COMPLETE_ROUTER",
                    "core_population_count": metric["population_count"],
                    "core_macro_f1_gold_answer_cases": metric["macro_f1"],
                    "core_micro_f1_gold_answer_cases": metric["micro_f1"],
                    "exact_capability_set_match": metric["exact_capability_set_match"],
                    "jaccard": metric["jaccard"],
                    "under_routing_rate": metric["under_routing_rate"],
                    "over_routing_rate": metric["over_routing_rate"],
                    "family_both_utterances_correct_rate": metric["family_metrics"][
                        "both_utterances_exact_correct_rate"
                    ],
                    "complete_gold_pattern_contrast_match_rate": metric[
                        "capability_contrast"
                    ]["complete_gold_pattern_match_rate"],
                    "end_to_end_full_route_exact_match": end[
                        "full_route_signature_exact_match"
                    ],
                    "counterfactual_provider_component_call_count": cost[
                        "provider_component_call_count"
                    ],
                    "counterfactual_token_cost": cost["counterfactual_token_cost"],
                }
            )
        elif method_id == "R2V2-CG1_CLARIFICATION_RULE":
            base.update(
                {
                    "row_role": "SHARED_CLARIFICATION_CONTROL",
                    "dialogue_action_accuracy": clarification["accuracy"],
                    "clarify_precision": clarification["per_class"]["CLARIFY"]["precision"],
                    "clarify_recall": clarification["per_class"]["CLARIFY"]["recall"],
                    "clarify_f1": clarification["per_class"]["CLARIFY"]["f1"],
                }
            )
        else:
            component_key = "rag_specialist" if method_id == "R2V2-RAG_SPECIALIST" else "memory_specialist"
            metric = components[component_key]["metrics"]
            base.update(
                {
                    "row_role": "COMPONENT_SPECIALIST",
                    "component_accuracy": metric["accuracy"],
                    "component_precision": metric["precision"],
                    "component_recall": metric["recall"],
                    "component_f1": metric["f1"],
                    "component_specificity": metric["specificity"],
                }
            )
        rows.append(base)
    return rows


METHOD_TABLE_FIELDS = (
    "method_id",
    "method_tier",
    "reporting_tier",
    "development_status",
    "confirmatory_exploratory_role",
    "test_reporting_status",
    "selectable",
    "frozen_method_status",
    "row_role",
    "core_population_count",
    "core_macro_f1_gold_answer_cases",
    "core_micro_f1_gold_answer_cases",
    "exact_capability_set_match",
    "jaccard",
    "under_routing_rate",
    "over_routing_rate",
    "family_both_utterances_correct_rate",
    "complete_gold_pattern_contrast_match_rate",
    "end_to_end_full_route_exact_match",
    "counterfactual_provider_component_call_count",
    "counterfactual_token_cost",
    "dialogue_action_accuracy",
    "clarify_precision",
    "clarify_recall",
    "clarify_f1",
    "component_accuracy",
    "component_precision",
    "component_recall",
    "component_f1",
    "component_specificity",
)


def _candidate_rows(method_rows: Sequence[Mapping[str, Any]]) -> list[dict[str, Any]]:
    by_id = {row["method_id"]: row for row in method_rows}
    rows: list[dict[str, Any]] = []
    for method_id in ELIGIBLE_METHOD_IDS:
        source = by_id[method_id]
        row = {
            "method_id": method_id,
            **{field: True for field in COVERAGE_FIELDS},
            "core_macro_f1_gold_answer_cases": source[
                "core_macro_f1_gold_answer_cases"
            ],
            "exact_capability_set_match": source["exact_capability_set_match"],
            "jaccard": source["jaccard"],
            "under_routing_rate": source["under_routing_rate"],
            "over_routing_rate": source["over_routing_rate"],
            "family_both_utterances_correct_rate": source[
                "family_both_utterances_correct_rate"
            ],
            "complete_gold_pattern_contrast_match_rate": source[
                "complete_gold_pattern_contrast_match_rate"
            ],
            "counterfactual_provider_component_call_count": source[
                "counterfactual_provider_component_call_count"
            ],
            "counterfactual_token_cost": source["counterfactual_token_cost"],
            "method_tier_number": METHOD_TIER_NUMBERS[method_id],
            "method_id_utf8": method_id,
        }
        rows.append(row)
    if len(rows) != 8 or {row["method_id"] for row in rows} != set(ELIGIBLE_METHOD_IDS):
        raise Stage5EError("candidate table differs from the frozen eight-method set")
    return rows


CANDIDATE_FIELDS = (
    "method_id",
    *COVERAGE_FIELDS,
    "core_macro_f1_gold_answer_cases",
    "exact_capability_set_match",
    "jaccard",
    "under_routing_rate",
    "over_routing_rate",
    "family_both_utterances_correct_rate",
    "complete_gold_pattern_contrast_match_rate",
    "counterfactual_provider_component_call_count",
    "counterfactual_token_cost",
    "method_tier_number",
    "method_id_utf8",
)


def _core_markdown_table(core: Mapping[str, Any]) -> str:
    lines = [
        "| Method | Macro-F1 | Micro-F1 | Exact | Jaccard | Under | Over |",
        "| --- | ---: | ---: | ---: | ---: | ---: | ---: |",
    ]
    for method_id in COMPLETE_METHOD_IDS:
        value = core["methods"][method_id]
        lines.append(
            f"| `{method_id}` | {value['macro_f1']:.6f} | {value['micro_f1']:.6f} | "
            f"{value['exact_capability_set_match']:.6f} | {value['jaccard']:.6f} | "
            f"{value['under_routing_rate']:.6f} | {value['over_routing_rate']:.6f} |"
        )
    return "\n".join(lines)


def _end_markdown_table(end_to_end: Mapping[str, Any]) -> str:
    lines = [
        "| Method | Action accuracy | Action Macro-F1 | Full-route exact | Family both correct |",
        "| --- | ---: | ---: | ---: | ---: |",
    ]
    for method_id in COMPLETE_METHOD_IDS:
        value = end_to_end["methods"][method_id]
        lines.append(
            f"| `{method_id}` | {value['dialogue_action_accuracy']:.6f} | "
            f"{value['dialogue_action_macro_f1']:.6f} | "
            f"{value['full_route_signature_exact_match']:.6f} | "
            f"{value['family_both_utterances_correct']['rate']:.6f} |"
        )
    return "\n".join(lines)


def _render_reports(
    gold_summary: Mapping[str, Any],
    clarification: Mapping[str, Any],
    core: Mapping[str, Any],
    components: Mapping[str, Any],
    end_to_end: Mapping[str, Any],
    costs: Mapping[str, Any],
    bootstrap: Mapping[str, Any],
    candidates: Sequence[Mapping[str, Any]],
    selected: str,
    binding_hash: str,
    registry_by_id: Mapping[str, Any],
) -> None:
    clarification_class = clarification["per_class"]["CLARIFY"]
    results = f"""# RQ2-V2 Final TEST Results

Status: `FROZEN_AFTER_ONE_TIME_SCORING`

All Router and Specialist predictions were frozen before TEST Gold access. Stage 5E made zero provider calls and performed no prediction rerun.

## Gold population

- Cases: {gold_summary['case_count']}
- Families: {gold_summary['family_count']}
- Gold ANSWER / CLARIFY: {gold_summary['gold_answer_case_count']} / {gold_summary['gold_clarify_case_count']}
- Excluded cases: {gold_summary['excluded_case_count']}

## Shared Clarification Gate

- Dialogue-action accuracy: {clarification['accuracy']:.6f}
- CLARIFY precision / recall / F1: {clarification_class['precision']:.6f} / {clarification_class['recall']:.6f} / {clarification_class['f1']:.6f}
- Family both utterances correct: {clarification['family_both_utterances_correct']['rate']:.6f}
- Clarification contrast consistency / Gold-pattern match: {clarification['clarification_contrast']['clarification_contrast_consistency_rate']:.6f} / {clarification['clarification_contrast']['clarification_gold_pattern_match_rate']:.6f}

## Core capability results on Gold ANSWER cases

{_core_markdown_table(core)}

## Specialists

- RAG Specialist Accuracy / F1: {components['rag_specialist']['metrics']['accuracy']:.6f} / {components['rag_specialist']['metrics']['f1']:.6f}
- Memory Specialist Accuracy / F1: {components['memory_specialist']['metrics']['accuracy']:.6f} / {components['memory_specialist']['metrics']['f1']:.6f}

## End-to-end results

{_end_markdown_table(end_to_end)}

## Cost and uncertainty boundary

- Historical TEST provider calls / tokens: {costs['actual_historical_test_execution']['total']['logical_calls']} / {costs['actual_historical_test_execution']['total']['total_tokens']}
- Historical standard-rate approximate cost: USD {costs['actual_historical_test_execution']['total']['standard_uncached_input_approximate_cost_usd']:.7f}; exact billed cost is unavailable.
- Bootstrap: {bootstrap['replicates']} family-clustered replicates, seed {bootstrap['seed']}; descriptive only.

The selected method is `{selected}`. Its TEST result is selection-conditional because the pre-frozen rule selected among eight eligible methods on this same final TEST evaluation.
"""
    (FINAL_SCORING_DIR / "RQ2_FINAL_TEST_RESULTS.md").write_text(
        results, encoding="utf-8", newline="\n"
    )

    candidate_lines = [
        "| Method | Macro-F1 | Exact | Jaccard | Under | Over | Calls | Token cost | Coverage |",
        "| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | --- |",
    ]
    for row in candidates:
        coverage = all(row[field] for field in COVERAGE_FIELDS)
        candidate_lines.append(
            f"| `{row['method_id']}` | {row['core_macro_f1_gold_answer_cases']:.12f} | "
            f"{row['exact_capability_set_match']:.12f} | {row['jaccard']:.12f} | "
            f"{row['under_routing_rate']:.12f} | {row['over_routing_rate']:.12f} | "
            f"{row['counterfactual_provider_component_call_count']} | "
            f"{row['counterfactual_token_cost']:.12f} | {'PASS' if coverage else 'FAIL'} |"
        )
    selection_md = f"""# RQ2 Final Router Selection

Status: `FROZEN_FOR_RQ3`

The unchanged pre-TEST frozen selection implementation selected `{selected}` from the exact eight eligible complete methods using full-precision values.

{chr(10).join(candidate_lines)}

- P4 entered candidate table: no
- Coverage-complete candidates: {sum(all(row[field] for field in COVERAGE_FIELDS) for row in candidates)}/8
- Frozen eligibility hash: `{ELIGIBILITY_SHA256}`
- Frozen selection-rule hash: `{SELECTION_RULE_SHA256}`
- Write-once binding hash: `{binding_hash}`
"""
    (FINAL_SCORING_DIR / "RQ2_FINAL_ROUTER_SELECTION.md").write_text(
        selection_md, encoding="utf-8", newline="\n"
    )

    boundary = """# RQ2 Final TEST Interpretation Boundary

- All predictions were frozen before TEST Gold access.
- The Router-selection rule and eligible eight-method set were frozen before TEST Gold access.
- All fourteen frozen registry methods are reported in their appropriate complete, control, or component roles.
- R2V2-P4_MEMORY_SPECIALIST_COMPOSITION remains post-DEV exploratory and was ineligible for selection.
- The selected method's TEST result is selection-conditional, not an unbiased single-model generalization estimate.
- TEST will not be reused for further Router, threshold, prompt, few-shot, composition, or model development.
- RQ3 is a separate downstream response-quality evaluation and was not executed in Stage 5E.
- Human Gold is the Oracle Route source and was not selected as a Router.
"""
    (FINAL_SCORING_DIR / "RQ2_FINAL_TEST_INTERPRETATION_BOUNDARY.md").write_text(
        boundary, encoding="utf-8", newline="\n"
    )

    selected_registry = registry_by_id[selected]
    handoff_md = f"""# RQ2 Final Router for RQ3 Handoff

- Selected core Router: `{selected}`
- Shared Clarification Gate: `R2V2-CG1_CLARIFICATION_RULE`
- Binding status: `FROZEN_AFTER_ONE_TIME_RQ2_FINAL_SCORING`
- Binding SHA-256: `{binding_hash}`
- Runtime composition: `{compact_json(_runtime_composition(selected))}`
- Method tier: `{selected_registry['method_tier']}`
- Development status: `{selected_registry['development_status']}`
- Missing component behavior: fail closed; no imputation, fallback, or Router substitution.
- Input contract: `current_query`, `current_page`, `dashboard_context`, `visible_conversation_history` under `R2V2_PRIMARY_SEMANTIC_INPUT_V1`.
- Output contract: dialogue action plus RAG, Memory, and Planning booleans on ANSWER; capabilities are NOT_APPLICABLE on CLARIFY.
- RQ3 cannot revise, overwrite, or reselect this binding.

This safe handoff contains no TEST query, Gold, annotation ID, case prediction, error registry, or restricted family mapping.
"""
    (FINAL_SCORING_DIR / "RQ2_FINAL_ROUTER_RQ3_HANDOFF.md").write_text(
        handoff_md, encoding="utf-8", newline="\n"
    )

    status = f"""# RQ2-V2 Stage 5E Status

`RQ2_FINAL_TEST_STATUS = FROZEN_AFTER_ONE_TIME_SCORING`

`RQ2_FINAL_ROUTER_STATUS = FROZEN_FOR_RQ3`

- Selected Router: `{selected}`
- Shared gate: `R2V2-CG1_CLARIFICATION_RULE`
- Gold cases / families: {gold_summary['case_count']} / {gold_summary['family_count']}
- Coverage-complete eligible methods: 8/8
- New provider calls: 0
- Prediction reruns: 0
- Method, prompt, threshold, and composition changes after Gold access: 0
- RQ3 executions: 0
- Binding write count: 1; overwrite permitted: false
- Stop boundary: Stage 5E complete; do not execute RQ3 without separate authority.
"""
    (FINAL_SCORING_DIR / "STATUS.md").write_text(status, encoding="utf-8", newline="\n")


def _error_registry(
    rows: Sequence[Mapping[str, Any]],
    predictions: Mapping[str, Mapping[str, Signature]],
    gate: Mapping[str, str],
) -> list[dict[str, Any]]:
    errors: list[dict[str, Any]] = []
    for row in rows:
        case_id = row["annotation_case_id"]
        gold_route = (
            "CLARIFY"
            if row["gold_dialogue_action"] == "CLARIFY"
            else signature_text(gold_signature(row))
        )
        for method_id in COMPLETE_METHOD_IDS:
            predicted_core = signature_text(predictions[method_id][case_id])
            if row["gold_dialogue_action"] == "ANSWER" and predicted_core != gold_route:
                errors.append(
                    {
                        "annotation_case_id": case_id,
                        "method_id": method_id,
                        "evaluation_scope": "CORE_GOLD_ANSWER",
                        "error_type": "CAPABILITY_SET_MISMATCH",
                        "gold_signature": gold_route,
                        "predicted_signature": predicted_core,
                    }
                )
            predicted_route = "CLARIFY" if gate[case_id] == "CLARIFY" else predicted_core
            if predicted_route != gold_route:
                errors.append(
                    {
                        "annotation_case_id": case_id,
                        "method_id": method_id,
                        "evaluation_scope": "END_TO_END_ALL_TEST",
                        "error_type": "FULL_ROUTE_MISMATCH",
                        "gold_signature": gold_route,
                        "predicted_signature": predicted_route,
                    }
                )
    return errors


ERROR_FIELDS = (
    "annotation_case_id",
    "method_id",
    "evaluation_scope",
    "error_type",
    "gold_signature",
    "predicted_signature",
)


def run_one_time_final_scoring() -> dict[str, Any]:
    if Path.cwd().resolve() != EXPECTED_WORKTREE.resolve():
        raise Stage5EError("runner is outside the authorized worktree")
    if ACCESS_RECEIPT_PATH.exists():
        raise Stage5EError("the one-time TEST Gold scoring invocation already began")
    if BINDING_PATH.exists():
        raise Stage5EError("write-once RQ3 binding already exists")
    if not PRE_SCORING_RECEIPT_PATH.is_file():
        raise Stage5EError("pre-scoring harness receipt is absent")
    pre_receipt = read_json(PRE_SCORING_RECEIPT_PATH)
    if (
        pre_receipt.get("zero_gold_access_status", {}).get("test_gold_values_accessed")
        is not False
        or pre_receipt.get("zero_provider_call_status", {}).get("provider_calls") != 0
        or pre_receipt.get("bootstrap", {}).get("seed") != BOOTSTRAP_SEED
        or pre_receipt.get("bootstrap", {}).get("replicates") != BOOTSTRAP_REPLICATES
    ):
        raise Stage5EError("pre-scoring harness receipt contract differs")
    for relative, expected in pre_receipt["scoring_source_file_hashes"].items():
        if sha256_file(PROJECT_ROOT / relative) != expected:
            raise Stage5EError(f"pre-scoring source hash changed before Gold access: {relative}")
    source_hashes = verify_frozen_sources()
    frozen = load_frozen_predictions()

    access_timestamp = datetime.now(timezone.utc).isoformat()
    invocation_id = f"RQ2-V2-STAGE5E-{uuid.uuid4()}"
    extraction_dir, escrow_member_hashes = _extract_escrow_once(access_timestamp)
    access_receipt = {
        "schema_version": "rq2-v2-stage5e-test-gold-access-receipt-v1",
        "escrow_zip_path": str(ESCROW_ZIP),
        "escrow_zip_sha256": ESCROW_ZIP_SHA256,
        "gold_csv_sha256": escrow_member_hashes["test_gold_escrow_v1.csv"],
        "gold_jsonl_sha256": escrow_member_hashes["test_gold_escrow_v1.jsonl"],
        "access_timestamp_utc": access_timestamp,
        "scoring_invocation_id": invocation_id,
        "fresh_temporary_extraction_directory": str(extraction_dir),
        "scoring_code_receipt_sha256": sha256_file(PRE_SCORING_RECEIPT_PATH),
        "prediction_source_hashes": dict(sorted(PREDICTION_HASHES.items())),
        "declaration": "FIRST_AUTHORIZED_FINAL_SCORING_INVOCATION",
        "provider_calls_during_stage5e": 0,
        "network_calls_during_stage5e": 0,
    }
    write_once_json(ACCESS_RECEIPT_PATH, access_receipt)

    gold_rows, gold_summary = _parse_gold(extraction_dir)
    normalized, predictions, p1_metadata = build_normalized_records(gold_rows, frozen)
    answer_rows = [row for row in normalized if row["gold_dialogue_action"] == "ANSWER"]
    answer_families = Counter(row["canonical_scenario_family_id"] for row in answer_rows)
    if any(count != 2 for count in answer_families.values()):
        raise Stage5EError("core population must contain complete Gold ANSWER families only")
    gate = {row["annotation_case_id"]: row["frozen_clarification_prediction"] for row in normalized}

    clarification = clarification_metrics(normalized, gate)
    clarification.update(
        {
            "schema_version": "rq2-v2-stage5e-final-clarification-metrics-v1",
            "method_id": "R2V2-CG1_CLARIFICATION_RULE",
            "gate_modified": False,
        }
    )
    core = {
        "schema_version": "rq2-v2-stage5e-final-core-method-metrics-v1",
        "population": "GOLD_DIALOGUE_ACTION_ANSWER",
        "population_count": len(answer_rows),
        "family_count": len(answer_families),
        "metric_definition_source": "Stage_0_and_Stage_4_frozen_set_metrics",
        "selection_values_rounded": False,
        "methods": {
            method_id: core_metrics(answer_rows, predictions[method_id])
            for method_id in COMPLETE_METHOD_IDS
        },
    }
    rag_predictions = {
        case_id: row["prediction"]["rag_required"] for case_id, row in frozen["rag"].items()
    }
    memory_predictions = {
        case_id: row["prediction"]["memory_required"]
        for case_id, row in frozen["memory"].items()
    }
    b4_rag = {case_id: value[0] for case_id, value in predictions["R2V2-B4_JOINT_LLM"].items()}
    b4_memory = {case_id: value[1] for case_id, value in predictions["R2V2-B4_JOINT_LLM"].items()}
    components = {
        "schema_version": "rq2-v2-stage5e-final-component-metrics-v1",
        "population": "GOLD_DIALOGUE_ACTION_ANSWER",
        "rag_specialist": {
            "method_id": "R2V2-RAG_SPECIALIST",
            "metrics": component_metrics(answer_rows, rag_predictions, capability="rag"),
            "comparison_with_b4_rag_bit": compare_component_to_b4(
                answer_rows,
                rag_predictions,
                b4_rag,
                gold_key="gold_rag_required",
            ),
        },
        "memory_specialist": {
            "method_id": "R2V2-MEMORY_SPECIALIST",
            "metrics": component_metrics(answer_rows, memory_predictions, capability="memory"),
            "comparison_with_b4_memory_bit": compare_component_to_b4(
                answer_rows,
                memory_predictions,
                b4_memory,
                gold_key="gold_memory_required",
            ),
        },
    }
    end_methods: dict[str, Any] = {}
    route_predictions: dict[str, dict[str, str]] = {}
    for method_id in COMPLETE_METHOD_IDS:
        routes = {
            case_id: (
                "CLARIFY" if gate[case_id] == "CLARIFY" else signature_text(value)
            )
            for case_id, value in predictions[method_id].items()
        }
        route_predictions[method_id] = routes
        end_methods[method_id] = end_to_end_metrics(normalized, gate, routes)
    end_to_end = {
        "schema_version": "rq2-v2-stage5e-final-end-to-end-metrics-v1",
        "population": "ALL_36_TEST_CASES",
        "shared_clarification_gate_id": "R2V2-CG1_CLARIFICATION_RULE",
        "methods": end_methods,
    }
    family_contrast = {
        "schema_version": "rq2-v2-stage5e-final-family-contrast-results-v1",
        "clarification": {
            "family_both_utterances_correct": clarification[
                "family_both_utterances_correct"
            ],
            "family_prediction_consistency": clarification[
                "family_prediction_consistency"
            ],
            "contrast": clarification["clarification_contrast"],
        },
        "core_methods": {
            method_id: {
                "family_metrics": core["methods"][method_id]["family_metrics"],
                "capability_contrast": core["methods"][method_id][
                    "capability_contrast"
                ],
            }
            for method_id in COMPLETE_METHOD_IDS
        },
        "end_to_end_methods": {
            method_id: {
                "family_both_utterances_correct": end_methods[method_id][
                    "family_both_utterances_correct"
                ],
                "family_prediction_consistency": end_methods[method_id][
                    "family_prediction_consistency"
                ],
                "complete_contrast": end_methods[method_id]["complete_contrast"],
            }
            for method_id in COMPLETE_METHOD_IDS
        },
    }
    costs = cost_analysis(normalized, p1_metadata)
    bootstrap = bootstrap_analysis(answer_rows, predictions)

    write_csv(
        FINAL_SCORING_DIR / "final_test_normalized_records_v1.csv",
        normalized,
        NORMALIZED_FIELDS,
    )
    write_jsonl(
        FINAL_SCORING_DIR / "final_test_normalized_records_v1.jsonl", normalized
    )
    complete_rows = complete_prediction_rows(normalized, predictions, p1_metadata)
    write_csv(
        FINAL_SCORING_DIR / "final_test_complete_method_predictions_v1.csv",
        complete_rows,
        COMPLETE_PREDICTION_FIELDS,
    )
    write_jsonl(
        FINAL_SCORING_DIR / "final_test_complete_method_predictions_v1.jsonl",
        complete_rows,
    )
    write_json(FINAL_SCORING_DIR / "final_test_clarification_metrics_v1.json", clarification)
    write_json(FINAL_SCORING_DIR / "final_test_component_metrics_v1.json", components)
    write_json(FINAL_SCORING_DIR / "final_test_core_method_metrics_v1.json", core)
    write_json(FINAL_SCORING_DIR / "final_test_end_to_end_metrics_v1.json", end_to_end)
    write_json(FINAL_SCORING_DIR / "final_test_cost_and_calls_v1.json", costs)
    write_json(
        FINAL_SCORING_DIR / "final_test_family_contrast_results_v1.json", family_contrast
    )
    write_json(FINAL_SCORING_DIR / "final_test_bootstrap_v1.json", bootstrap)

    registry = read_json(METHOD_REGISTRY_PATH)
    registry_by_id = {row["method_id"]: row for row in registry["methods"]}
    method_rows = _method_table(
        registry, core, clarification, components, end_to_end, costs
    )
    if len(method_rows) != 14 or tuple(row["method_id"] for row in method_rows) != ALL_METHOD_IDS:
        raise Stage5EError("final method table does not contain all 14 registry methods")
    write_csv(
        FINAL_SCORING_DIR / "final_test_method_results_v1.csv",
        method_rows,
        METHOD_TABLE_FIELDS,
    )
    method_result = {
        "schema_version": "rq2-v2-stage5e-final-method-results-v1",
        "method_count": 14,
        "core_population_count": len(answer_rows),
        "selection_numeric_values_unrounded": True,
        "methods": method_rows,
    }
    write_json(FINAL_SCORING_DIR / "final_test_method_results_v1.json", method_result)

    candidates = _candidate_rows(method_rows)
    write_csv(
        FINAL_SCORING_DIR / "final_router_selection_candidate_table_v1.csv",
        candidates,
        CANDIDATE_FIELDS,
    )
    eligibility = read_json(ELIGIBILITY_PATH)
    selection_rule = read_json(SELECTION_RULE_PATH)
    selected = select_final_router(candidates, eligibility, selection_rule)
    if selected not in ELIGIBLE_METHOD_IDS or selected == "R2V2-P4_MEMORY_SPECIALIST_COMPOSITION":
        raise Stage5EError("frozen selection returned an ineligible method")
    candidate_hash = sha256_file(
        FINAL_SCORING_DIR / "final_router_selection_candidate_table_v1.csv"
    )
    scoring_result_hash = sha256_file(
        FINAL_SCORING_DIR / "final_test_method_results_v1.json"
    )
    selection_result = {
        "schema_version": "rq2-v2-stage5e-final-router-selection-result-v1",
        "selection_status": "FROZEN_FOR_RQ3",
        "selected_method_id": selected,
        "eligible_candidate_count": 8,
        "coverage_complete_candidate_count": sum(
            all(row[field] is True for field in COVERAGE_FIELDS) for row in candidates
        ),
        "selection_implementation": str(
            (PROJECT_ROOT / "evaluation/capability_routing_rq2_v2_stage4/final_router_selection/selection_rule.py").relative_to(PROJECT_ROOT)
        ),
        "eligibility_registry_sha256": ELIGIBILITY_SHA256,
        "selection_rule_sha256": SELECTION_RULE_SHA256,
        "candidate_table_sha256": candidate_hash,
        "final_scoring_result_sha256": scoring_result_hash,
        "numeric_values_rounded_for_selection": False,
        "p4_entered_candidate_table": False,
        "p4_status": "POST_DEV_EXPLORATORY_ABLATION",
        "selection_rule_changed": False,
    }
    write_json(
        FINAL_SCORING_DIR / "final_router_selection_result_v1.json", selection_result
    )

    selected_registry = registry_by_id[selected]
    binding = {
        "schema_version": "rq2-v2-final-router-for-rq3-binding-v1",
        "binding_name": "RQ2_FINAL_ROUTER_FOR_RQ3",
        "selected_method_id": selected,
        "shared_clarification_gate_id": "R2V2-CG1_CLARIFICATION_RULE",
        "binding_status": "FROZEN_AFTER_ONE_TIME_RQ2_FINAL_SCORING",
        "selected_method_tier": selected_registry["method_tier"],
        "selected_method_development_status": selected_registry["development_status"],
        "selected_method_frozen_source_configuration_hashes": selected_registry[
            "exact_source_files"
        ],
        "selected_method_runtime_composition": _runtime_composition(selected),
        "eligibility_registry_sha256": ELIGIBILITY_SHA256,
        "selection_rule_sha256": SELECTION_RULE_SHA256,
        "final_candidate_table_sha256": candidate_hash,
        "final_scoring_result_sha256": scoring_result_hash,
        "test_prediction_source_hashes": dict(sorted(PREDICTION_HASHES.items())),
        "test_gold_escrow_sha256": ESCROW_ZIP_SHA256,
        "write_count": 1,
        "overwrite_permitted": False,
        "p4_selection_permitted": False,
        "oracle_route_source": "HUMAN_GOLD_NOT_SELECTED_ROUTER",
        "rq3_may_change_binding": False,
    }
    write_once_json(BINDING_PATH, binding)
    binding_hash = sha256_file(BINDING_PATH)

    handoff = {
        "schema_version": "rq2-v2-final-router-rq3-handoff-v1",
        "selected_core_router_method_id": selected,
        "shared_clarification_gate_id": "R2V2-CG1_CLARIFICATION_RULE",
        "runtime_composition": _runtime_composition(selected),
        "method_tier": selected_registry["method_tier"],
        "development_status": selected_registry["development_status"],
        "method_configuration_sources": selected_registry["exact_source_files"],
        "required_source_paths": [
            item["path"] for item in selected_registry["exact_source_files"]
        ],
        "expected_input_schema": {
            "feature_profile": "R2V2_PRIMARY_SEMANTIC_INPUT_V1",
            "fields": [
                "current_query",
                "current_page",
                "dashboard_context",
                "visible_conversation_history",
            ],
        },
        "expected_output_schema": {
            "dialogue_action": ["ANSWER", "CLARIFY"],
            "answer_capability_fields": [
                "rag_required",
                "memory_required",
                "planning_required",
            ],
            "clarify_capability_value": "NOT_APPLICABLE",
        },
        "missing_component_behavior": "FAIL_CLOSED_NO_IMPUTATION_NO_SUBSTITUTION",
        "binding_path": str(BINDING_PATH.relative_to(PROJECT_ROOT)),
        "binding_sha256": binding_hash,
        "rq3_can_revise_selection": False,
        "contains_test_query_gold_case_prediction_or_annotation_id": False,
        "contains_error_registry_or_restricted_family_mapping": False,
    }
    write_json(
        FINAL_SCORING_DIR / "rq2_final_router_rq3_handoff_v1.json", handoff
    )

    error_rows = _error_registry(normalized, predictions, gate)
    write_csv(
        FINAL_SCORING_DIR / "final_test_error_registry_v1.csv", error_rows, ERROR_FIELDS
    )

    source_manifest = {
        "schema_version": "rq2-v2-stage5e-final-test-source-manifest-v1",
        "working_directory": str(EXPECTED_WORKTREE),
        "branch": EXPECTED_BRANCH,
        "starting_head": STARTING_HEAD,
        "integrated_commits": [
            {
                "original_commit": original,
                "cherry_picked_commit": integrated,
                "subject": subject,
            }
            for original, integrated, subject in INTEGRATED_COMMITS
        ],
        "escrow_zip": {"path": str(ESCROW_ZIP), "sha256": ESCROW_ZIP_SHA256},
        "escrow_member_hashes": escrow_member_hashes,
        "prediction_source_hashes": dict(sorted(PREDICTION_HASHES.items())),
        "selection_sources": {
            "eligibility_sha256": ELIGIBILITY_SHA256,
            "selection_rule_sha256": SELECTION_RULE_SHA256,
            "method_registry_sha256": METHOD_REGISTRY_SHA256,
            "scoring_protocol_sha256": SCORING_PROTOCOL_SHA256,
        },
        "pre_scoring_harness_receipt_sha256": sha256_file(PRE_SCORING_RECEIPT_PATH),
        "test_gold_access_receipt_sha256": sha256_file(ACCESS_RECEIPT_PATH),
        "gold_summary": gold_summary,
        "source_hash_verification": source_hashes,
        "provider_calls_during_stage5e": 0,
        "network_calls_during_stage5e": 0,
        "prediction_reruns": 0,
        "rq3_executions": 0,
    }
    write_json(FINAL_SCORING_DIR / "FINAL_TEST_SOURCE_MANIFEST.json", source_manifest)

    _render_reports(
        gold_summary,
        clarification,
        core,
        components,
        end_to_end,
        costs,
        bootstrap,
        candidates,
        selected,
        binding_hash,
        registry_by_id,
    )

    post_gold_hashes = {
        relative: sha256_file(PROJECT_ROOT / relative)
        for relative in pre_receipt["scoring_source_file_hashes"]
    }
    if post_gold_hashes != pre_receipt["scoring_source_file_hashes"]:
        raise Stage5EError("scoring source hashes changed after Gold access")

    output_names = sorted(
        path.name
        for path in FINAL_SCORING_DIR.iterdir()
        if path.is_file()
        and path.name
        not in {
            "FINAL_STAGE5E_SHA256_MANIFEST.json",
        }
        and path.suffix != ".pyc"
    )
    output_manifest = {
        "schema_version": "rq2-v2-stage5e-output-sha256-manifest-v1",
        "files": [
            {
                "name": name,
                "sha256": sha256_file(FINAL_SCORING_DIR / name),
                "size_bytes": (FINAL_SCORING_DIR / name).stat().st_size,
            }
            for name in output_names
        ],
        "external_binding": {
            "path": str(BINDING_PATH.relative_to(PROJECT_ROOT)),
            "sha256": binding_hash,
        },
        "post_gold_scoring_source_hashes_unchanged": True,
        "provider_calls": 0,
        "network_calls": 0,
        "rq3_executions": 0,
    }
    write_json(
        FINAL_SCORING_DIR / "FINAL_STAGE5E_SHA256_MANIFEST.json", output_manifest
    )

    return {
        "status": "FROZEN_AFTER_ONE_TIME_SCORING",
        "selected_method_id": selected,
        "binding_sha256": binding_hash,
        "gold_summary": gold_summary,
        "temporary_extraction_directory": str(extraction_dir),
        "new_provider_calls": 0,
        "prediction_reruns": 0,
        "rq3_executions": 0,
    }
