"""Load and validate the frozen Stage 0 contracts without model execution."""

from __future__ import annotations

from collections import Counter
import hashlib
import json
from pathlib import Path
from typing import Any, Iterable, Mapping

from jsonschema import Draft202012Validator

from . import (
    CAPABILITY_FIELDS,
    CASE_SCHEMA_VERSION,
    CONTRACT_SCHEMA_VERSION,
    DATASET_REGISTRY_SCHEMA_VERSION,
    MODEL_IDS,
    PACKAGE_ROOT,
    PREDICTION_SCHEMA_VERSION,
    PROJECT_ROOT,
    SCENARIO_MATRIX_SCHEMA_VERSION,
)


class Stage0ContractError(ValueError):
    """Raised when a Stage 0 artifact violates the frozen contract."""


def load_json(path: Path) -> Any:
    return json.loads(Path(path).read_text(encoding="utf-8"))


def load_jsonl(path: Path) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for line_number, line in enumerate(
        Path(path).read_text(encoding="utf-8").splitlines(), start=1
    ):
        if not line.strip():
            continue
        value = json.loads(line)
        if not isinstance(value, dict):
            raise Stage0ContractError(
                f"{path}:{line_number} must contain a JSON object"
            )
        rows.append(value)
    return rows


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with Path(path).open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _schema(name: str) -> dict[str, Any]:
    value = load_json(PACKAGE_ROOT / "schemas" / name)
    if not isinstance(value, dict):
        raise Stage0ContractError(f"Schema {name} is not a JSON object")
    Draft202012Validator.check_schema(value)
    return value


def _validate(instance: Any, schema_name: str) -> None:
    validator = Draft202012Validator(_schema(schema_name))
    errors = sorted(validator.iter_errors(instance), key=lambda item: list(item.path))
    if errors:
        first = errors[0]
        location = ".".join(str(item) for item in first.path) or "<root>"
        raise Stage0ContractError(f"{schema_name}:{location}: {first.message}")


def validate_case(case: Mapping[str, Any]) -> None:
    _validate(dict(case), "case_v1.schema.json")
    if case.get("schema_version") != CASE_SCHEMA_VERSION:
        raise Stage0ContractError("case schema version drift")


def validate_prediction(prediction: Mapping[str, Any]) -> None:
    _validate(dict(prediction), "prediction_v1.schema.json")
    if prediction.get("schema_version") != PREDICTION_SCHEMA_VERSION:
        raise Stage0ContractError("prediction schema version drift")


def validate_contrast_pair(pair: Mapping[str, Any]) -> None:
    _validate(dict(pair), "contrast_pair_v1.schema.json")


def validate_clarification_contract(contract: Mapping[str, Any]) -> None:
    expected = {
        "schema_version": "rq2-v2-clarification-scenario-contract-v1",
        "dialogue_action": "CLARIFY",
        "core_capability_route_execution": False,
        "target_scenario_family_count": 6,
        "target_human_utterances_per_family": 2,
        "target_case_count": 12,
        "development_family_target": 4,
        "development_case_target": 8,
        "test_family_target": 2,
        "test_case_target": 4,
        "scenario_family_definitions_created": 0,
        "utterances_created": 0,
    }
    for name, value in expected.items():
        if contract.get(name) != value:
            raise Stage0ContractError(f"clarification scenario contract drift: {name}")
    if contract.get("split_unit") != "scenario_family_id":
        raise Stage0ContractError("clarification cases must split by scenario family")


def validate_dataset_registry(registry: Mapping[str, Any]) -> None:
    _validate(dict(registry), "dataset_registry_v1.schema.json")
    if registry.get("schema_version") != DATASET_REGISTRY_SCHEMA_VERSION:
        raise Stage0ContractError("dataset registry schema version drift")

    asset_ids: set[str] = set()
    for entry in registry["assets"]:
        asset_id = entry["asset_id"]
        if asset_id in asset_ids:
            raise Stage0ContractError(f"duplicate dataset asset_id: {asset_id}")
        asset_ids.add(asset_id)

        relative = Path(entry["path"])
        if relative.is_absolute() or ".." in relative.parts:
            raise Stage0ContractError(f"unsafe dataset path: {entry['path']}")
        exists = (PROJECT_ROOT / relative).exists()
        if exists is not bool(entry["exists_at_inventory"]):
            raise Stage0ContractError(
                f"dataset existence drift for {asset_id}: expected "
                f"{entry['exists_at_inventory']}, observed {exists}"
            )
        if entry["include_in_review_zip"]:
            raise Stage0ContractError(
                f"existing governed asset must not enter review ZIP: {asset_id}"
            )


def validate_contract(contract: Mapping[str, Any]) -> None:
    if contract.get("schema_version") != CONTRACT_SCHEMA_VERSION:
        raise Stage0ContractError("capability contract schema version drift")
    if tuple(contract.get("model_ids") or ()) != MODEL_IDS:
        raise Stage0ContractError("frozen R2V2 model ID drift")
    if tuple(contract.get("core_capability_fields") or ()) != CAPABILITY_FIELDS:
        raise Stage0ContractError("core capability field drift")
    if contract.get("dashboard_role") != "INPUT_CONTEXT_NOT_CAPABILITY_LABEL":
        raise Stage0ContractError("dashboard role drift")
    if contract.get("dialogue_control", {}).get("actions") != ["ANSWER", "CLARIFY"]:
        raise Stage0ContractError("dialogue-control action drift")
    benchmark = contract.get("planned_benchmark") or {}
    expected = {
        "answerable_case_target": 96,
        "clarification_case_target": 12,
        "total_case_target": 108,
        "stage0_cases_created": 0,
    }
    for name, value in expected.items():
        if benchmark.get(name) != value:
            raise Stage0ContractError(f"planned benchmark contract drift: {name}")


def validate_scenario_matrix(rows: Iterable[Mapping[str, Any]]) -> None:
    materialised = [dict(row) for row in rows]
    for row in materialised:
        _validate(row, "scenario_matrix_row_v1.schema.json")
        if row.get("schema_version") != SCENARIO_MATRIX_SCHEMA_VERSION:
            raise Stage0ContractError("scenario matrix schema version drift")

    expected_ids = {f"{value:03b}" for value in range(8)}
    observed_ids = [str(row["combination_id"]) for row in materialised]
    if len(observed_ids) != 8 or set(observed_ids) != expected_ids:
        raise Stage0ContractError("scenario matrix must contain exactly 000 through 111")
    if len(observed_ids) != len(set(observed_ids)):
        raise Stage0ContractError("scenario matrix combination IDs must be unique")

    for row in materialised:
        labels = row["capability_combination"]
        signature = "".join(
            "1" if labels[field] else "0" for field in CAPABILITY_FIELDS
        )
        if signature != row["combination_id"]:
            raise Stage0ContractError(
                f"scenario signature mismatch for {row['combination_id']}"
            )
        if row["target_scenario_family_count"] != 6:
            raise Stage0ContractError("each answerable combination requires six families")
        if row["target_human_utterances_per_family"] != 2:
            raise Stage0ContractError("each family requires two human utterances")
        if row["target_human_utterances"] != 12:
            raise Stage0ContractError("each combination requires twelve utterances")
        if row["development_family_target"] != 4 or row["test_family_target"] != 2:
            raise Stage0ContractError("each combination must split 4 DEV / 2 TEST families")


def validate_b1_legacy_contract(contract: Mapping[str, Any]) -> None:
    if contract.get("schema_version") != "rq2-v2-b1-legacy-interface-v1":
        raise Stage0ContractError("B1 legacy interface schema version drift")
    if contract.get("selected_rq1_router") != "C0_COSINE":
        raise Stage0ContractError("B1 must bind to frozen RQ1 C0_COSINE")
    if contract.get("mapping_status") != "PENDING_DEVELOPMENT_ONLY_FREEZE":
        raise Stage0ContractError("B1 mapping must remain unfrozen in Stage 0")
    if "intent_to_capability_mapping" in contract:
        raise Stage0ContractError("Stage 0 must not guess a B1 intent mapping")

    approved = contract["artifacts"]["approved_index"]
    embeddings = contract["artifacts"]["embedding_npz"]
    for artifact in (approved, embeddings):
        path = PROJECT_ROOT / artifact["path"]
        if not path.is_file():
            raise Stage0ContractError(f"missing frozen RQ1 artifact: {artifact['path']}")
        if sha256_file(path) != artifact["sha256"]:
            raise Stage0ContractError(f"frozen RQ1 artifact hash mismatch: {artifact['path']}")

    index_rows = load_jsonl(PROJECT_ROOT / approved["path"])
    counts = Counter(str(row.get("final_semantic_label")) for row in index_rows)
    configured = {
        item["label"]: int(item["approved_example_count"])
        for item in contract["frozen_label_universe"]
    }
    if counts != Counter(configured) or sum(counts.values()) != 62 or len(counts) != 16:
        raise Stage0ContractError("B1 frozen label universe does not match RQ1 index")

    selection_path = PROJECT_ROOT / contract["selection_manifest_path"]
    selection = load_json(selection_path)
    if selection.get("selected_router") != "C0_COSINE":
        raise Stage0ContractError("RQ1 selection manifest no longer selects C0_COSINE")
    model_path = PROJECT_ROOT / contract["encoder"]["local_path"]
    if not model_path.is_dir():
        raise Stage0ContractError("frozen local RQ1 encoder path is unavailable")


def load_stage0_contracts() -> dict[str, Any]:
    return {
        "capability_contract": load_json(
            PACKAGE_ROOT / "config" / "rq2_v2_contract_v1.json"
        ),
        "b1_legacy_contract": load_json(
            PACKAGE_ROOT / "config" / "b1_legacy_interface_v1.json"
        ),
        "dataset_registry": load_json(
            PACKAGE_ROOT / "data" / "dataset_registry_v1.json"
        ),
        "scenario_matrix": load_jsonl(
            PACKAGE_ROOT / "data" / "scenario_matrix_v1.jsonl"
        ),
        "clarification_contract": load_json(
            PACKAGE_ROOT / "data" / "clarification_scenario_contract_v1.json"
        ),
    }
