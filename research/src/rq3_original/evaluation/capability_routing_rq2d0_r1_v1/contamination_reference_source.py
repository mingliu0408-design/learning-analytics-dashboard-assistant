"""Resolve the eight governed contamination partitions without path guessing."""

from __future__ import annotations

import csv
from dataclasses import dataclass
import hashlib
import json
from pathlib import Path
from typing import Any, Callable, Iterable

from evaluation.learned_intent_ranking.rq1c.final_input_schema import parse_final_csv_bytes

from . import (
    FIXTURE28_SHA256,
    REFERENCE_PARTITION_COUNTS,
    ROOT,
    sha256_bytes,
    sha256_file,
)


class ReferenceSourceError(RuntimeError):
    """A frozen source is absent, ambiguous, or does not match its authority."""


@dataclass(frozen=True)
class SourceSpec:
    partition_id: str
    source_alias: str
    relative_path: str
    expected_sha256: str
    expected_count: int
    source_contract_id: str
    source_role: str


@dataclass(frozen=True)
class ReferenceRecord:
    source_record_identity: str
    query: str
    history: Any
    family_or_group: str | None = None


SPECS = {
    "RQ1_TRAIN": SourceSpec(
        "RQ1_TRAIN",
        "RQ1_EXPANDED_TRAIN_MANIFEST_V2",
        "evaluation/learned_intent_ranking/lr4a/lr4a_r1/"
        "ranker_expanded_train_manifest_candidate_v2.jsonl",
        "623bcdeaad62ae20559c616dc57aedfb22bd2d006f0beb6888da88d549c40805",
        318,
        "LR4B_GOVERNED_EXPANDED_TRAIN_V2",
        "RQ1_TRAIN_CONTAMINATION_REFERENCE",
    ),
    "RQ1_DEV": SourceSpec(
        "RQ1_DEV",
        "RQ1_FUNCTIONAL_QA_DEV_MANIFEST_V2",
        "evaluation/learned_intent_ranking/lr1r/ranker_dev_manifest_candidate_v2.jsonl",
        "7765ffbbe48fcde543b60561f22a03cef596235af07eed58540aacb64334f09f",
        84,
        "LR1R_FUNCTIONAL_QA_DEV_V2",
        "RQ1_DEV_CONTAMINATION_REFERENCE",
    ),
    "C0_FROZEN_62_CANDIDATES": SourceSpec(
        "C0_FROZEN_62_CANDIDATES",
        "C0_APPROVED_INTENT_INDEX_V1",
        "semantic_runtime/artifacts/intent_examples_approved_index_v1.jsonl",
        "b4cac34df91c074a4a2fa85e4ccc52623563f3358fe44938771f8303f00b6be9",
        62,
        "RQ1_C0_FROZEN_62_MAX_AGGREGATION",
        "FROZEN_CANDIDATE_CONTAMINATION_REFERENCE",
    ),
    "TRACK_A_SAFE_IDENTITIES": SourceSpec(
        "TRACK_A_SAFE_IDENTITIES",
        "PRIMARY_V3_TRACK_A_RQ1_FINAL_GOLD_V1",
        "evaluation/learned_intent_ranking/rq1c/local_final_gold/"
        "primary_v3_semantic_heldout_human_review_researcher_final_v1.csv",
        "5d40f0a4a6b460e77271ee9815fce1b0954c1d7e05c7a4cd2f5d8e28ff09eb8f",
        128,
        "RQ1C_FINAL_GOLD_AUTHORITY_CONTRACT_V1",
        "HASH_ONLY_FINAL_INDEPENDENCE_REFERENCE",
    ),
    "AUTHENTIC22": SourceSpec(
        "AUTHENTIC22",
        "AUTHENTIC_CODEBOOK_CALIBRATION_GOLD_V1",
        "evaluation/capability_routing_v1_r2b/local_gold/"
        "authentic_codebook_calibration_gold_v1.jsonl",
        "96e23f1131c14e5fb627d711a19295594a56bd3daaaef4cdf0ebce71a7af0346",
        22,
        "SOURCE_SEPARATED_CAPABILITY_GOLD_MANIFEST_V1",
        "SENSITIVITY_REFERENCE",
    ),
    "SYNTHETIC35": SourceSpec(
        "SYNTHETIC35",
        "SYNTHETIC_COVERAGE_STRESS_GOLD_V1",
        "evaluation/capability_routing_v1_r2b/local_gold/"
        "synthetic_coverage_stress_gold_v1.jsonl",
        "9e01b400a6daf9fed13e6cca2bdfe2d714785741b34f2266bbf6c36e8ca08399",
        35,
        "SOURCE_SEPARATED_CAPABILITY_GOLD_MANIFEST_V1",
        "HARD_FINAL_INDEPENDENCE_REFERENCE",
    ),
    "CONTEXT_MISSING3": SourceSpec(
        "CONTEXT_MISSING3",
        "AUTHENTIC_CONTEXT_MISSING_QUALITATIVE_REGISTRY_V1",
        "evaluation/capability_routing_v1_r2b/local_gold/"
        "authentic_context_missing_qualitative_registry_v1.jsonl",
        "2f89ccaec37b890ec97a415b76169996d2ae0a6d8f20ebb910410f1c5801c412",
        3,
        "SOURCE_SEPARATED_CAPABILITY_GOLD_MANIFEST_V1",
        "SENSITIVITY_REFERENCE",
    ),
    "CONTROLLED_MECHANISM_FIXTURE28": SourceSpec(
        "CONTROLLED_MECHANISM_FIXTURE28",
        "RQ2_P2_CONTROLLED_MECHANISM_FIXTURE_BANK_V1",
        "evaluation/capability_routing_rq2c0_r1_v1/local_fixture_bank/"
        "rq2_p2_controlled_mechanism_fixture_bank_v1.jsonl",
        FIXTURE28_SHA256,
        28,
        "CONTROLLED_MECHANISM_FIXTURE_MANIFEST_V1",
        "SENSITIVITY_REFERENCE",
    ),
}


def _regular(path: Path) -> None:
    if not path.is_file() or path.is_symlink():
        raise ReferenceSourceError("BLOCKED_RQ2_D0_R1_CONTAMINATION_REFERENCE_INCOMPLETE")


def _jsonl(path: Path) -> list[dict[str, Any]]:
    return [
        json.loads(line)
        for line in path.read_text(encoding="utf-8-sig").splitlines()
        if line.strip()
    ]


def _history(value: Any) -> Any:
    if value in (None, "", [], ()):  # one canonical empty-history marker
        return []
    if isinstance(value, str):
        stripped = value.strip()
        if not stripped:
            return []
        try:
            return json.loads(stripped)
        except json.JSONDecodeError:
            return stripped
    return value


def _verify_query_hash(query: str, expected: str) -> None:
    if sha256_bytes(query.encode("utf-8")) != expected:
        raise ReferenceSourceError("BLOCKED_RQ2_D0_R1_REFERENCE_IDENTITY")


def _resolve_train(_: Path) -> list[ReferenceRecord]:
    manifest = _jsonl(ROOT / SPECS["RQ1_TRAIN"].relative_path)
    approved = {
        str(row["example_id"]): row
        for row in _jsonl(ROOT / SPECS["C0_FROZEN_62_CANDIDATES"].relative_path)
    }
    retained_path = ROOT / (
        "evaluation/learned_intent_ranking/lr4a/training_data_input/"
        "eedi_stage_e4_confirmed_candidate_subset_256.csv"
    )
    _regular(retained_path)
    if sha256_file(retained_path) != (
        "5959b2bd343fd10ae180c641ddc72d5af0396956875ad69a2162ffeaeb25d9d3"
    ):
        raise ReferenceSourceError("BLOCKED_RQ2_D0_R1_REFERENCE_IDENTITY")
    with retained_path.open("r", encoding="utf-8-sig", newline="") as handle:
        retained = {str(row["record_id"]): row for row in csv.DictReader(handle)}
    result: list[ReferenceRecord] = []
    for row in manifest:
        record_id = str(row["record_id"])
        if record_id in approved:
            source = approved[record_id]
            query = str(source["query"])
            history: Any = []
        elif record_id in retained:
            source = retained[record_id]
            query = str(source["utterance_for_review"])
            history = _history(source.get("previous_turns_for_review"))
        else:
            raise ReferenceSourceError("BLOCKED_RQ2_D0_R1_REFERENCE_SOURCE_AMBIGUOUS")
        _verify_query_hash(query, str(row["query_sha256"]))
        result.append(
            ReferenceRecord(
                source_record_identity=(
                    f"{row['source_dataset_id']}\x00{row['source_record_id']}"
                ),
                query=query,
                history=history,
                family_or_group=str(
                    row.get("paraphrase_family_id") or row.get("contrast_set_id") or ""
                )
                or None,
            )
        )
    return result


def _resolve_dev(_: Path) -> list[ReferenceRecord]:
    manifest = _jsonl(ROOT / SPECS["RQ1_DEV"].relative_path)
    source_paths = {str(row["provenance"]["source_path"]) for row in manifest}
    if source_paths != {"evaluation/functional_qa/functional_qa_cases_v1.jsonl"}:
        raise ReferenceSourceError("BLOCKED_RQ2_D0_R1_REFERENCE_SOURCE_AMBIGUOUS")
    source_path = ROOT / next(iter(source_paths))
    _regular(source_path)
    cases = {str(row["case_id"]): row for row in _jsonl(source_path)}
    result: list[ReferenceRecord] = []
    for row in manifest:
        provenance = row["provenance"]
        case_id = str(provenance["case_id"])
        turn_index = int(provenance["turn_index"])
        case = cases.get(case_id)
        if case is None or not 1 <= turn_index <= len(case["turns"]):
            raise ReferenceSourceError("BLOCKED_RQ2_D0_R1_REFERENCE_SOURCE_AMBIGUOUS")
        query = str(case["turns"][turn_index - 1]["query"])
        _verify_query_hash(query, str(row["query_sha256"]))
        result.append(
            ReferenceRecord(
                source_record_identity=f"functional_qa_v1\x00{case_id}:T{turn_index}",
                query=query,
                history=[],
                family_or_group=str(row.get("contrast_set_id") or "") or None,
            )
        )
    return result


def _resolve_candidates(path: Path) -> list[ReferenceRecord]:
    return [
        ReferenceRecord(
            source_record_identity=(
                f"{row.get('source_path', '')}\x00{row.get('source_record_id') or row['example_id']}"
            ),
            query=str(row["query"]),
            history=[],
            family_or_group=str(row.get("final_paraphrase_family_id") or "") or None,
        )
        for row in _jsonl(path)
    ]


def _resolve_track_a(path: Path) -> list[ReferenceRecord]:
    raw = path.read_bytes()
    spec = SPECS["TRACK_A_SAFE_IDENTITIES"]
    if sha256_bytes(raw) != spec.expected_sha256 or len(raw) != 129_236:
        raise ReferenceSourceError("BLOCKED_RQ2_D0_R1_REFERENCE_IDENTITY")
    contract = json.loads(
        (ROOT / "evaluation/learned_intent_ranking/rq1c/"
         "rq1c_final_gold_authority_contract_v1.json").read_text(encoding="utf-8")
    )
    records, _ = parse_final_csv_bytes(raw, contract)
    return [
        ReferenceRecord(
            source_record_identity=f"PRIMARY_V3_TRACK_A\x00{row['record_id']}",
            query=str(row["query"]),
            history=[],
            family_or_group=str(row["family_id"]),
        )
        for row in records
    ]


def _resolve_gold(path: Path) -> list[ReferenceRecord]:
    result: list[ReferenceRecord] = []
    for row in _jsonl(path):
        identity = str(row.get("canonical_case_id") or row.get("review_case_id") or "")
        if not identity:
            raise ReferenceSourceError("BLOCKED_RQ2_D0_R1_REFERENCE_IDENTITY")
        result.append(
            ReferenceRecord(
                source_record_identity=f"{row.get('source_bank_alias', '')}\x00{identity}",
                query=str(row["current_query"]),
                history=_history(row.get("necessary_conversation_history")),
                family_or_group=None,
            )
        )
    return result


def _fixture_query(value: Any) -> tuple[str, Any]:
    if isinstance(value, str):
        return value, []
    if isinstance(value, dict):
        query = next(
            (
                str(value[key])
                for key in ("query", "current_query", "event_query", "utterance")
                if value.get(key) not in (None, "")
            ),
            json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")),
        )
        history = _history(value.get("history") or value.get("conversation_history"))
        return query, history
    return json.dumps(value, ensure_ascii=False, sort_keys=True), []


def _resolve_fixtures(path: Path) -> list[ReferenceRecord]:
    result: list[ReferenceRecord] = []
    for row in _jsonl(path):
        query, history = _fixture_query(row["input_event_or_query"])
        result.append(
            ReferenceRecord(
                source_record_identity=f"RQ2_P2_FIXTURE\x00{row['fixture_id']}",
                query=query,
                history=history,
                family_or_group=str(row.get("mechanism_group") or "") or None,
            )
        )
    return result


RESOLVERS: dict[str, Callable[[Path], list[ReferenceRecord]]] = {
    "RQ1_TRAIN": _resolve_train,
    "RQ1_DEV": _resolve_dev,
    "C0_FROZEN_62_CANDIDATES": _resolve_candidates,
    "TRACK_A_SAFE_IDENTITIES": _resolve_track_a,
    "AUTHENTIC22": _resolve_gold,
    "SYNTHETIC35": _resolve_gold,
    "CONTEXT_MISSING3": _resolve_gold,
    "CONTROLLED_MECHANISM_FIXTURE28": _resolve_fixtures,
}


def resolve_all_reference_sources() -> tuple[dict[str, list[ReferenceRecord]], dict[str, Any]]:
    records: dict[str, list[ReferenceRecord]] = {}
    safe_rows: list[dict[str, Any]] = []
    for partition_id in REFERENCE_PARTITION_COUNTS:
        spec = SPECS[partition_id]
        path = ROOT / spec.relative_path
        _regular(path)
        actual_sha = sha256_file(path)
        if actual_sha != spec.expected_sha256:
            raise ReferenceSourceError("BLOCKED_RQ2_D0_R1_REFERENCE_IDENTITY")
        rows = RESOLVERS[partition_id](path)
        if len(rows) != spec.expected_count:
            raise ReferenceSourceError(
                "BLOCKED_RQ2_D0_R1_CONTAMINATION_REFERENCE_INCOMPLETE"
            )
        records[partition_id] = rows
        safe_rows.append(
            {
                "partition_id": partition_id,
                "source_alias": spec.source_alias,
                "expected_count": spec.expected_count,
                "observed_count": len(rows),
                "source_sha256": actual_sha,
                "source_size_bytes": path.stat().st_size,
                "source_contract_id": spec.source_contract_id,
                "source_role": spec.source_role,
                "resolution_status": "PASS",
            }
        )
    return records, {
        "schema_version": "contamination-reference-source-resolution-v1",
        "reference_contract_id": "RQ2_TRACK_B_CONTAMINATION_REFERENCE_AUTHORITY_V1",
        "status": "PASS",
        "partition_count": len(safe_rows),
        "total_record_count": sum(row["observed_count"] for row in safe_rows),
        "sources": safe_rows,
        "absolute_paths_emitted": False,
        "reference_text_emitted": False,
        "track_b_accessed": False,
    }
