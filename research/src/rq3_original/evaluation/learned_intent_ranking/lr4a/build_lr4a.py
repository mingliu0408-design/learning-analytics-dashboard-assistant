"""Build the LR-4A governed training-evidence expansion readiness package."""

from __future__ import annotations

import csv
import hashlib
import io
import json
import re
import statistics
import unicodedata
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any


HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]
LR_ROOT = HERE.parent
LR1 = LR_ROOT / "lr1"
LR1R = LR_ROOT / "lr1r"
LR2R = LR_ROOT / "lr2r"
LR3R = LR_ROOT / "lr3r"
LR3S = LR_ROOT / "lr3s"


def sha(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def read_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def read_jsonl(path: Path) -> list[dict[str, Any]]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def write_json(name: str, value: Any) -> None:
    (HERE / name).write_text(json.dumps(value, indent=2, sort_keys=True, ensure_ascii=False) + "\n", encoding="utf-8")


def verify_checksum_manifest(path: Path) -> dict[str, Any]:
    rows = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        expected, relative = line.split(None, 1)
        relative = relative.strip().lstrip("*")
        target = path.parent / relative
        actual = sha(target)
        rows.append({"path": relative, "expected_sha256": expected, "actual_sha256": actual, "match": actual == expected})
    if not rows or not all(row["match"] for row in rows):
        raise ValueError(f"checksum verification failed: {path}")
    return {"manifest_path": str(path.relative_to(ROOT)), "manifest_sha256": sha(path), "entry_count": len(rows), "all_match": True, "entries": rows}


def casefolded_whitespace(text: str) -> str:
    return re.sub(r"\s+", " ", unicodedata.normalize("NFKC", str(text)).strip()).casefold()


def normalised(text: str) -> str:
    value = casefolded_whitespace(text)
    value = "".join(" " if unicodedata.category(char).startswith("P") else char for char in value)
    return re.sub(r"\s+", " ", value).strip()


def query_identities(text: str) -> dict[str, str]:
    raw = str(text)
    return {
        "exact": hashlib.sha256(raw.encode("utf-8")).hexdigest(),
        "casefolded_whitespace": hashlib.sha256(casefolded_whitespace(raw).encode("utf-8")).hexdigest(),
        "normalised": hashlib.sha256(normalised(raw).encode("utf-8")).hexdigest(),
    }


def protected_inventory() -> dict[str, dict[str, str]]:
    groups: dict[str, list[Path]] = {
        "production": list((ROOT / "utils").rglob("*")) + list((ROOT / "pages").rglob("*")),
        "semantic_runtime": list((ROOT / "semantic_runtime").rglob("*")),
        "prior_lr_stages": [ROOT / "LR0_LEARNED_INTENT_RANKING_READINESS_AUDIT.md"] + [
            path for name in ["lr1", "lr1r", "lr2", "lr2r", "lr3", "lr3r", "lr3s"]
            for path in (LR_ROOT / name).rglob("*")
        ],
        "original_datasets": [ROOT / path for path in [
            "evaluation/deterministic_query_classification_characterisation_v1.jsonl",
            "evaluation/functional_qa/functional_qa_cases_v1.jsonl",
            "evaluation/scenarios.jsonl", "evaluation/multiturn_scenarios.jsonl", "evaluation/rag_scenarios.jsonl",
            "evaluation/unified_benchmark_scenarios.jsonl", "evaluation/unified_benchmark_gold_labels.jsonl",
            "evaluation/unified_reference_evidence_v1.jsonl",
        ]],
    }
    return {name: {str(path.relative_to(ROOT)): sha(path) for path in sorted(paths) if path.is_file()} for name, paths in groups.items()}


def labels(rows: list[dict[str, Any]], field: str) -> dict[str, int]:
    return dict(sorted(Counter(str(row[field]) for row in rows if row.get(field) is not None).items()))


def role(training: str, development: str, final_gold: str, recommended: str) -> dict[str, str]:
    return {
        "training_eligibility": training,
        "development_eligibility": development,
        "final_gold_eligibility": final_gold,
        "recommended_role": recommended,
    }


def asset(
    *, dataset_id: str, path: Path | None, record_count: int | None, query_field: str | None,
    label_field: str | None, schema_version: str | None, label_counts: dict[str, int] | None,
    provenance: str, authorship_source: str | None, external_source: str | None,
    annotation_method: str, annotators: str, human_review_status: str,
    previous_use: dict[str, bool], eligibility: dict[str, str], notes: str,
) -> dict[str, Any]:
    return {
        "dataset_id": dataset_id,
        "path": str(path.relative_to(ROOT)) if path else None,
        "sha256": sha(path) if path and path.exists() else None,
        "availability": "PRESENT" if path and path.exists() else "EXPLICITLY_EXCLUDED" if dataset_id == "primary_v3_formal_heldout" else "REFERENCED_BUT_ABSENT",
        "record_count": record_count,
        "query_field": query_field,
        "label_field": label_field,
        "schema_version": schema_version,
        "label_universe": sorted(label_counts) if label_counts is not None else None,
        "per_label_counts": label_counts,
        "source_provenance": provenance,
        "authorship_source": authorship_source,
        "external_dataset_source_if_known": external_source,
        "annotation_method": annotation_method,
        "number_of_annotators": annotators,
        "human_review_status": human_review_status,
        "previously_used_for": previous_use,
        **eligibility,
        "notes": notes,
    }


def previous(**overrides: bool) -> dict[str, bool]:
    result = {
        "taxonomy_design": False, "embedding_model_selection": False, "example_index_selection": False,
        "calibration": False, "threshold_selection": False, "functional_qa_repair": False,
        "learned_ranker_train": False, "learned_ranker_dev": False, "final_evaluation": False,
    }
    result.update(overrides)
    return result


def records_with_query(dataset_id: str, rows: list[dict[str, Any]], id_field: str, query_field: str) -> list[dict[str, Any]]:
    result = []
    for row in rows:
        query = str(row[query_field])
        result.append({"dataset_id": dataset_id, "record_id": str(row[id_field]), "query": query, **query_identities(query)})
    return result


def overlap(left: list[dict[str, Any]], right: list[dict[str, Any]]) -> dict[str, Any]:
    output = {}
    for identity in ["exact", "casefolded_whitespace", "normalised"]:
        left_groups: dict[str, list[str]] = defaultdict(list)
        right_groups: dict[str, list[str]] = defaultdict(list)
        for row in left:
            left_groups[row[identity]].append(row["record_id"])
        for row in right:
            right_groups[row[identity]].append(row["record_id"])
        shared = sorted(set(left_groups) & set(right_groups))
        output[identity] = {
            "shared_identity_count": len(shared),
            "left_record_count_in_overlap": sum(len(left_groups[value]) for value in shared),
            "right_record_count_in_overlap": sum(len(right_groups[value]) for value in shared),
            "groups": [
                {"identity_sha256": value, "left_record_ids": sorted(left_groups[value]), "right_record_ids": sorted(right_groups[value])}
                for value in shared
            ],
        }
    return output


def main() -> None:
    HERE.mkdir(parents=True, exist_ok=True)
    before = protected_inventory()

    approved_path = ROOT / "semantic_runtime/artifacts/intent_examples_approved_index_v1.jsonl"
    train_path = LR1 / "ranker_train_manifest_candidate_v1.jsonl"
    dev_path = LR1R / "ranker_dev_manifest_candidate_v2.jsonl"
    fqa_path = ROOT / "evaluation/functional_qa/functional_qa_cases_v1.jsonl"
    unified_path = ROOT / "evaluation/unified_benchmark_scenarios.jsonl"
    unified_gold_path = ROOT / "evaluation/unified_benchmark_gold_labels.jsonl"
    dqc_path = ROOT / "evaluation/deterministic_query_classification_characterisation_v1.jsonl"
    main_path = ROOT / "evaluation/scenarios.jsonl"
    memory_path = ROOT / "evaluation/multiturn_scenarios.jsonl"
    rag_path = ROOT / "evaluation/rag_scenarios.jsonl"
    reference_path = ROOT / "evaluation/unified_reference_evidence_v1.jsonl"

    approved = read_jsonl(approved_path)
    train = read_jsonl(train_path)
    dev = read_jsonl(dev_path)
    fqa_cases = read_jsonl(fqa_path)
    unified = read_jsonl(unified_path)
    unified_gold = read_jsonl(unified_gold_path)
    dqc = read_jsonl(dqc_path)
    main_rows = read_jsonl(main_path)
    memory_rows = read_jsonl(memory_path)
    rag_rows = read_jsonl(rag_path)
    reference_rows = read_jsonl(reference_path)
    singleton_ids = {
        row["record_id"]
        for row in read_json(LR2R / "lr2r_singleton_exclusion_manifest_v1.json")["records"]
    }
    pairwise = [row for row in train if row["record_id"] not in singleton_ids]

    fqa_turns = []
    fqa_case_by_id = {row["case_id"]: row for row in fqa_cases}
    for case in fqa_cases:
        for turn_index, turn in enumerate(case["turns"], start=1):
            fqa_turns.append({
                "record_id": f"{case['case_id']}:T{turn_index}", "query": turn["query"],
                "intent_label": turn.get("expected_intent_family") or case.get("expected_intent_family"),
                "case_id": case["case_id"], "family": case.get("family"),
            })

    inventory = []
    inventory.append(asset(
        dataset_id="approved_semantic_index_v1", path=approved_path, record_count=len(approved), query_field="query",
        label_field="final_semantic_label", schema_version="intent-approved-index-v1",
        label_counts=labels(approved, "final_semantic_label"),
        provenance="Frozen production retrieval examples assembled in Stage 3A and researcher-confirmed assisted review in Stage 3B.",
        authorship_source="Unified benchmark sources, existing production tests, and researcher-authored future-outcome examples.",
        external_source=None, annotation_method="researcher-confirmed assisted review", annotators="1 documented researcher",
        human_review_status="57 approved; 5 revised in the final 62-record index",
        previous_use=previous(example_index_selection=True, learned_ranker_train=True),
        eligibility=role("CURRENT_TRAIN_SOURCE_NOT_ADDITIONAL_EXPANSION", "NOT_ELIGIBLE_RETRIEVAL_EXPOSED", "NOT_ELIGIBLE_DEVELOPMENT_EXPOSED", "CURRENT_TRAIN_AND_PRODUCTION_RETRIEVAL_SUPPORT"),
        notes="62 retrieval records; four singleton labels remain retrieval-only for pairwise training.",
    ))
    inventory.append(asset(
        dataset_id="lr1_train_manifest_v1", path=train_path, record_count=len(train), query_field="HASH_REFERENCE_TO_APPROVED_INDEX",
        label_field="intent_label", schema_version="ranker-train-manifest-candidate-v1", label_counts=labels(train, "intent_label"),
        provenance="Governed LR-1 manifest referencing the approved semantic index.", authorship_source="Derived governance manifest",
        external_source=None, annotation_method="inherits approved-index review", annotators="inherits source",
        human_review_status="governed and frozen", previous_use=previous(learned_ranker_train=True),
        eligibility=role("CURRENT_TRAIN_MANIFEST", "NOT_ELIGIBLE", "NOT_ELIGIBLE", "CURRENT_TRAIN_GOVERNANCE"),
        notes="Contains 62 records; LR-2R authorises only the 58 non-singleton records for pairwise training.",
    ))
    inventory.append(asset(
        dataset_id="lr2r_pairwise_train_universe_v1", path=LR2R / "lr2r_label_universe_v1.json", record_count=len(pairwise),
        query_field="REFERENCES_LR1_TRAIN", label_field="intent_label", schema_version="lr2r-label-universe-v1",
        label_counts=labels(pairwise, "intent_label"), provenance="LR-2R repaired pairwise exposure universe.",
        authorship_source="Deterministic subset of LR-1 TRAIN", external_source=None,
        annotation_method="inherits approved-index review", annotators="inherits source", human_review_status="governed and frozen",
        previous_use=previous(learned_ranker_train=True),
        eligibility=role("CURRENT_PAIRWISE_TRAIN", "NOT_ELIGIBLE", "NOT_ELIGIBLE", "CURRENT_PAIRWISE_TRAIN"),
        notes="58 records, 12 positive-capable labels; excludes four singleton records from every pair endpoint.",
    ))
    inventory.append(asset(
        dataset_id="functional_qa_authorised_dev_v2", path=dev_path, record_count=len(dev), query_field="HASH_AND_SOURCE_TURN_REFERENCE",
        label_field="intent_label", schema_version="ranker-dev-manifest-candidate-v2", label_counts=labels(dev, "intent_label"),
        provenance="84 governed turns resolved from Functional-QA cases; fixed LR learned-ranker DEV.",
        authorship_source="Project Functional-QA authorship", external_source=None,
        annotation_method="expected intent fields in development/repair cases; independent intent annotation not documented",
        annotators="not documented", human_review_status="DEVELOPMENT_ONLY; governance adjudicated",
        previous_use=previous(functional_qa_repair=True, learned_ranker_dev=True),
        eligibility=role("PROHIBITED_DEVELOPMENT_ONLY", "FIXED_CURRENT_DEV", "NOT_ELIGIBLE_DEVELOPMENT_EXPOSED", "DEVELOPMENT_ONLY"),
        notes="Must never be used as anchors, candidates, or augmentation seeds.",
    ))
    inventory.append(asset(
        dataset_id="functional_qa_source_pool_v1", path=fqa_path, record_count=len(fqa_turns), query_field="turns[].query",
        label_field="turns[].expected_intent_family or case.expected_intent_family", schema_version=None,
        label_counts=dict(sorted(Counter(row["intent_label"] for row in fqa_turns if row["intent_label"]).items())),
        provenance="100 Functional-QA cases / 108 turns repeatedly used for repair and regression.",
        authorship_source="Project-authored Functional-QA", external_source=None,
        annotation_method="task expectations embedded in test cases", annotators="not documented",
        human_review_status="development and bug-repair exposed", previous_use=previous(functional_qa_repair=True, learned_ranker_dev=True),
        eligibility=role("PROHIBITED_DEVELOPMENT_ONLY", "CURRENT_DEV_SOURCE_POOL_ONLY", "NOT_ELIGIBLE", "DEVELOPMENT_AND_REGRESSION_ONLY"),
        notes="84 turns are authorised DEV; remaining turns are not a new independent training pool.",
    ))
    inventory.append(asset(
        dataset_id="unified_capability_benchmark_scenarios_v1", path=unified_path, record_count=len(unified), query_field="student_query",
        label_field="gold_query_type", schema_version="unified-gold-v1.0", label_counts=labels(unified, "gold_query_type"),
        provenance="25 main + 12 memory + 10 RAG + 15 handwritten Unified scenarios.",
        authorship_source="Project benchmark authorship; Ming Liu human review", external_source="Includes original offline example-conversation benchmark ancestry",
        annotation_method="human-reviewed query/route/capability gold", annotators="1 documented researcher",
        human_review_status="53 approved; 9 revised", previous_use=previous(example_index_selection=True, final_evaluation=True),
        eligibility=role("NOT_NEW_TRAIN_EXPANSION_FAIL_CLOSED", "REGRESSION_HISTORICAL_DEVELOPMENT_ONLY", "CONTAMINATED_FOR_RANKER_FINAL", "REGRESSION_AND_HISTORICAL_DEVELOPMENT"),
        notes="48 exact queries source approved production retrieval examples.",
    ))
    inventory.append(asset(
        dataset_id="unified_capability_benchmark_gold_v1", path=unified_gold_path, record_count=len(unified_gold), query_field="JOIN scenario_id TO unified scenarios",
        label_field="gold_query_type", schema_version="unified-gold-v1.0", label_counts=labels(unified_gold, "gold_query_type"),
        provenance="Separated gold labels for Unified scenarios.", authorship_source="Ming Liu", external_source=None,
        annotation_method="human review", annotators="1 documented researcher", human_review_status="53 approved; 9 revised",
        previous_use=previous(example_index_selection=True, final_evaluation=True),
        eligibility=role("NOT_NEW_TRAIN_EXPANSION_FAIL_CLOSED", "REGRESSION_ONLY", "CONTAMINATED_FOR_RANKER_FINAL", "REGRESSION_ONLY"),
        notes="Contains labels but no independent query records; inherits Unified contamination.",
    ))
    inventory.append(asset(
        dataset_id="deterministic_query_characterisation_v1", path=dqc_path, record_count=len(dqc), query_field="query",
        label_field="legacy_query_type_before_stage2", schema_version=None, label_counts=labels(dqc, "legacy_query_type_before_stage2"),
        provenance="60 characterisation rows derived from Unified scenarios.", authorship_source="Deterministic project derivation",
        external_source=None, annotation_method="legacy deterministic classifier output, not independent semantic annotation",
        annotators="0", human_review_status="characterisation_only", previous_use=previous(functional_qa_repair=True),
        eligibility=role("NOT_ELIGIBLE_DERIVED_AND_NOT_INDEPENDENT_LABELS", "REGRESSION_ONLY", "NOT_ELIGIBLE", "REGRESSION_ONLY"),
        notes="60/60 query identities occur in Unified; 48 overlap current TRAIN.",
    ))
    inventory.append(asset(
        dataset_id="main_benchmark_scenarios", path=main_path, record_count=len(main_rows), query_field="student_query",
        label_field="query_type", schema_version=None, label_counts=labels(main_rows, "query_type"),
        provenance="Original 25-scenario offline benchmark; ancestor of Unified.",
        authorship_source="Example Conversation Data and project benchmark authorship", external_source="System Data/Example Conversation Data.csv",
        annotation_method="historical scenario labels", annotators="not documented", human_review_status="historical development-visible",
        previous_use=previous(example_index_selection=True, final_evaluation=True),
        eligibility=role("NOT_ELIGIBLE_ANCESTOR_DATA", "REGRESSION_ONLY", "NOT_ELIGIBLE", "REGRESSION_ONLY"),
        notes="24 rows exactly overlap current TRAIN; source/derivation ancestry is explicit.",
    ))
    inventory.append(asset(
        dataset_id="memory_diagnostic_scenarios", path=memory_path, record_count=len(memory_rows), query_field="student_query",
        label_field=None, schema_version=None, label_counts=None,
        provenance="12 authored conversation-memory diagnostic scenarios; Unified ancestor.",
        authorship_source="Project-authored diagnostics", external_source=None, annotation_method="no direct frozen semantic intent labels",
        annotators="not applicable", human_review_status="historical development-visible", previous_use=previous(final_evaluation=True),
        eligibility=role("NOT_ELIGIBLE_NO_DIRECT_LABEL_AND_ANCESTOR_DATA", "REGRESSION_ONLY", "NOT_ELIGIBLE", "REGRESSION_ONLY"),
        notes="Contextual memory cases are not independent labelled ranker rows.",
    ))
    inventory.append(asset(
        dataset_id="rag_diagnostic_scenarios", path=rag_path, record_count=len(rag_rows), query_field="student_query",
        label_field=None, schema_version=None, label_counts=None,
        provenance="10 authored RAG diagnostic scenarios; Unified ancestor.", authorship_source="Project-authored diagnostics",
        external_source=None, annotation_method="no direct frozen semantic intent labels", annotators="not applicable",
        human_review_status="historical development-visible", previous_use=previous(example_index_selection=True, final_evaluation=True),
        eligibility=role("NOT_ELIGIBLE_NO_DIRECT_LABEL_AND_ANCESTOR_DATA", "REGRESSION_ONLY", "NOT_ELIGIBLE", "REGRESSION_ONLY"),
        notes="All ten queries exactly overlap current TRAIN.",
    ))
    inventory.append(asset(
        dataset_id="unified_reference_evidence_v1", path=reference_path, record_count=len(reference_rows), query_field="reference_student_query",
        label_field=None, schema_version="reference-evidence-v1", label_counts=None,
        provenance="Reviewed evidence packs repeating Unified query/context.", authorship_source="Project evidence review",
        external_source=None, annotation_method="evidence review, not intent annotation", annotators="reviewer fields present",
        human_review_status="reviewed evidence only", previous_use=previous(final_evaluation=True),
        eligibility=role("NOT_ELIGIBLE_NOT_INDEPENDENT_INTENT_DATA", "NOT_ELIGIBLE", "NOT_ELIGIBLE", "EXCLUDED_FOR_RANKER"),
        notes="Repeats Unified queries; not a labelled expansion dataset.",
    ))
    inventory.append(asset(
        dataset_id="intent_candidate_and_review_trail_v1", path=ROOT / "evaluation/intent_examples_candidate_v1.jsonl", record_count=79,
        query_field="UNKNOWN", label_field="UNKNOWN", schema_version=None, label_counts=None,
        provenance="Referenced by approved-index metadata as Stage-3A candidate/review trail; rows absent.",
        authorship_source="human-reviewed Unified, existing tests, researcher future-outcome examples", external_source=None,
        annotation_method="researcher-confirmed assisted review according to frozen metadata", annotators="1 documented researcher",
        human_review_status="candidate/pending/completed files absent", previous_use=previous(example_index_selection=True),
        eligibility=role("NOT_ELIGIBLE_ABSENT_AND_MUST_NOT_RECONSTRUCT", "NOT_ELIGIBLE", "NOT_ELIGIBLE", "UNAVAILABLE"),
        notes="Do not reconstruct the missing 79 candidates from code or summaries.",
    ))
    inventory.append(asset(
        dataset_id="semantic_calibration_dataset_v1", path=None, record_count=None, query_field=None, label_field=None,
        schema_version=None, label_counts=None, provenance="Only hash retained in Stage-4B selection manifest.",
        authorship_source=None, external_source=None, annotation_method="unknown", annotators="unknown",
        human_review_status="rows absent", previous_use=previous(embedding_model_selection=True, calibration=True, threshold_selection=True),
        eligibility=role("NOT_ELIGIBLE_ABSENT_AND_SELECTION_EXPOSED", "NOT_ELIGIBLE", "NOT_ELIGIBLE", "UNAVAILABLE"),
        notes="Must not be regenerated from summary statistics.",
    ))
    inventory.append(asset(
        dataset_id="semantic_internal_validation_dataset_v1", path=None, record_count=None, query_field=None, label_field=None,
        schema_version=None, label_counts=None, provenance="Only hash retained in Stage-4B selection manifest.",
        authorship_source=None, external_source=None, annotation_method="unknown", annotators="unknown",
        human_review_status="rows absent; results historically inspected", previous_use=previous(embedding_model_selection=True),
        eligibility=role("NOT_ELIGIBLE_ABSENT_AND_DEVELOPMENT_EXPOSED", "NOT_ELIGIBLE", "NOT_ELIGIBLE", "UNAVAILABLE"),
        notes="Must not be regenerated from summary statistics.",
    ))
    inventory.append(asset(
        dataset_id="primary_v3_formal_heldout", path=None, record_count=None, query_field=None, label_field=None,
        schema_version=None, label_counts=None, provenance="Explicitly excluded by project manifest and prior governance.",
        authorship_source=None, external_source=None, annotation_method="sealed/unknown", annotators="unknown",
        human_review_status="not inspected", previous_use=previous(),
        eligibility=role("NOT_TRAINING_DATA", "NOT_DEVELOPMENT_DATA", "POTENTIAL_FINAL_GOLD", "POTENTIAL_FINAL_GOLD_NOT_ACCESSED"),
        notes="Query text was not searched or opened.",
    ))

    write_json("lr4a_candidate_dataset_inventory_v1.json", {
        "schema_version": "lr4a-candidate-dataset-inventory-v1",
        "search_boundary": "CURRENT_PROJECT_ROOT_ONLY",
        "search_terms": ["intent", "semantic", "candidate", "labelled", "labeled", "review", "training", "dataset", "student query", "expanded", "augmentation", "secondary", "Stage 3", "Stage 4"],
        "outside_project_search_performed": False,
        "primary_v3_query_text_inspected": False,
        "candidate_dataset_count": len(inventory),
        "additional_independent_labelled_datasets_found": 0,
        "additional_candidate_records": 0,
        "suitable_larger_secondary_training_dataset_present": False,
        "datasets": inventory,
    })

    approved_query = {row["example_id"]: row["query"] for row in approved}
    train_records = [{"dataset_id": "lr1_train", "record_id": row["record_id"], "query": approved_query[row["record_id"]], **query_identities(approved_query[row["record_id"]])} for row in train]
    pair_records = [row for row in train_records if row["record_id"] not in singleton_ids]
    dev_records = []
    for row in dev:
        case = fqa_case_by_id[row["provenance"]["case_id"]]
        turn = case["turns"][int(row["provenance"]["turn_index"]) - 1]
        dev_records.append({"dataset_id": "dev84", "record_id": row["record_id"], "query": turn["query"], **query_identities(turn["query"])})
        if query_identities(turn["query"])["exact"] != row["query_sha256"]:
            raise ValueError("DEV source resolution hash mismatch")

    candidate_query_sets = {
        "unified_capability_benchmark_scenarios_v1": records_with_query("unified", unified, "scenario_id", "student_query"),
        "deterministic_query_characterisation_v1": records_with_query("dqc", dqc, "case_id", "query"),
        "main_benchmark_scenarios": records_with_query("main", main_rows, "scenario_id", "student_query"),
        "memory_diagnostic_scenarios": records_with_query("memory", memory_rows, "scenario_id", "student_query"),
        "rag_diagnostic_scenarios": records_with_query("rag", rag_rows, "scenario_id", "student_query"),
        "unified_reference_evidence_v1": records_with_query("reference", reference_rows, "scenario_id", "reference_student_query"),
        "functional_qa_source_pool_v1": [
            {"dataset_id": "fqa", "record_id": row["record_id"], "query": row["query"], **query_identities(row["query"])} for row in fqa_turns
        ],
    }
    overlap_results = {}
    for dataset_id, rows in candidate_query_sets.items():
        overlap_results[dataset_id] = {
            "record_count": len(rows), "unique_exact_query_count": len({row["exact"] for row in rows}),
            "against_current_train_62": overlap(rows, train_records),
            "against_current_pairwise_train_58": overlap(rows, pair_records),
            "against_authorised_dev_84": overlap(rows, dev_records),
        }
    train_dev_overlap = overlap(pair_records, dev_records)
    if any(train_dev_overlap[key]["shared_identity_count"] for key in train_dev_overlap):
        raise ValueError("deterministic TRAIN/DEV leakage detected")

    write_json("lr4a_contamination_audit_v1.json", {
        "schema_version": "lr4a-contamination-audit-v1",
        "normalisation": {
            "exact": "SHA256 UTF-8 query bytes",
            "casefolded_whitespace": "NFKC + trim + whitespace collapse + Unicode casefold",
            "normalised": "casefolded-whitespace plus Unicode punctuation replacement/removal and whitespace collapse",
        },
        "reference_corpora": {
            "approved_retrieval_records": 62, "pairwise_train_records": 58, "authorised_dev_records": 84,
            "unified_benchmark_records": 62, "functional_qa_source_turns": 108,
            "production_regression_fixtures": "historical roles taken from LR-1 inventory; no absent expansion rows to compare",
            "future_final_gold_identifiers_or_hashes_supplied": False,
        },
        "current_pairwise_train_vs_authorised_dev": train_dev_overlap,
        "deterministic_train_dev_leakage_count": 0,
        "candidate_and_historical_dataset_overlaps": overlap_results,
        "identifier_checks": {
            "source_record_id": "audited where present through provenance graph",
            "scenario_id": "audited where present through provenance graph",
            "seed_id": "no additional candidate values supplied",
            "family_id": "current TRAIN families governed; no additional candidate values supplied",
            "contrast_set_id": "current DEV governed; no additional candidate values supplied",
            "parent_record_id": "no additional candidate values supplied",
        },
        "semantic_near_diagnostic": {
            "run": False, "new_review_flag_count": 0,
            "reason": "No new candidate expansion rows exist. High-similarity review is not meaningful without an intake dataset.",
            "prior_lr1r_semantic_near_adjudications_preserved": 6,
            "automatic_deletion_performed": False,
        },
        "primary_v3_accessed": False,
    })

    train_families: dict[str, list[str]] = defaultdict(list)
    for row in train:
        train_families[row["paraphrase_family_id"]].append(row["record_id"])
    fqa_groups: dict[str, list[str]] = defaultdict(list)
    for row in dev:
        fqa_groups[row["provenance"]["case_id"]].append(row["record_id"])
    source_edges = []
    for row in approved:
        source_edges.append({
            "from_dataset": "approved_semantic_index_v1", "from_record_id": row["example_id"],
            "to_dataset_path": row["source_path"], "to_source_record_id": row["source_record_id"],
            "edge_type": "SOURCE_DERIVATION",
        })
    write_json("lr4a_provenance_graph_v1.json", {
        "schema_version": "lr4a-provenance-graph-v1",
        "split_rule": "Rows sharing source, seed, scenario, paraphrase family, augmentation parent, or contrast set must remain one governance group.",
        "nodes": [
            {"dataset_id": item["dataset_id"], "path": item["path"], "availability": item["availability"], "recommended_role": item["recommended_role"]}
            for item in inventory
        ],
        "dataset_edges": [
            {"from": "lr1_train_manifest_v1", "to": "approved_semantic_index_v1", "relation": "ONE_TO_ONE_REFERENCE", "record_count": 62},
            {"from": "lr2r_pairwise_train_universe_v1", "to": "lr1_train_manifest_v1", "relation": "NON_SINGLETON_SUBSET", "record_count": 58},
            {"from": "approved_semantic_index_v1", "to": "unified_capability_benchmark_scenarios_v1", "relation": "EXACT_SOURCE_QUERY", "record_count": 48},
            {"from": "unified_capability_benchmark_scenarios_v1", "to": "main_benchmark_scenarios", "relation": "SOURCE_SCENARIO_LINEAGE", "record_count": 25},
            {"from": "unified_capability_benchmark_scenarios_v1", "to": "memory_diagnostic_scenarios", "relation": "SOURCE_SCENARIO_LINEAGE", "record_count": 12},
            {"from": "unified_capability_benchmark_scenarios_v1", "to": "rag_diagnostic_scenarios", "relation": "SOURCE_SCENARIO_LINEAGE", "record_count": 10},
            {"from": "deterministic_query_characterisation_v1", "to": "unified_capability_benchmark_scenarios_v1", "relation": "EXACT_QUERY_DERIVATION", "record_count": 60},
            {"from": "unified_reference_evidence_v1", "to": "unified_capability_benchmark_scenarios_v1", "relation": "QUERY_AND_CONTEXT_REPEAT", "record_count": 62},
            {"from": "functional_qa_authorised_dev_v2", "to": "functional_qa_source_pool_v1", "relation": "GOVERNED_TURN_SUBSET", "record_count": 84},
        ],
        "record_source_edges": source_edges,
        "governance_groups": {
            "train_paraphrase_family_groups": [{"group_id": family, "record_ids": sorted(ids)} for family, ids in sorted(train_families.items())],
            "dev_case_groups": [{"group_id": case_id, "record_ids": sorted(ids)} for case_id, ids in sorted(fqa_groups.items())],
            "additional_expansion_groups": [],
        },
        "derivation_siblings_split_across_train_and_dev": 0,
    })

    reliability_entries = []
    for item in inventory:
        if item["dataset_id"] in {"approved_semantic_index_v1", "lr1_train_manifest_v1", "lr2r_pairwise_train_universe_v1"}:
            tier, reason = "TIER_B", "Researcher-confirmed assisted review; single documented researcher; current governed TRAIN only."
        elif item["dataset_id"] in {"unified_capability_benchmark_scenarios_v1", "unified_capability_benchmark_gold_v1"}:
            tier, reason = "TIER_B_LABEL_RELIABILITY_BUT_EXCLUDED_ROLE", "Single documented researcher review, but historical/index contamination prohibits new expansion use."
        elif item["dataset_id"] == "primary_v3_formal_heldout":
            tier, reason = "NOT_ASSESSED_SEALED", "Potential final gold; not opened."
        elif item["availability"] != "PRESENT":
            tier, reason = "EXCLUDED", "Rows/provenance unavailable or explicitly sealed."
        else:
            tier, reason = "EXCLUDED", "Regression/DEV/derived/no-direct-label role prevents training intake."
        reliability_entries.append({"dataset_id": item["dataset_id"], "annotation_reliability_tier": tier, "reason": reason, "numeric_truth_interpretation": False})
    write_json("lr4a_annotation_reliability_v1.json", {
        "schema_version": "lr4a-annotation-reliability-v1",
        "tier_definitions": {
            "TIER_A": "multi-annotator or independently verified high-confidence labels",
            "TIER_B": "researcher-reviewed single-annotator labels",
            "TIER_C": "single-annotator or automatically assisted labels without sufficient independent verification",
            "EXCLUDED": "unreliable, ambiguous, unresolved provenance, or prohibited data role",
        },
        "tiers_are_governance_metadata_not_numeric_truth": True,
        "additional_candidate_record_tier_counts": {},
        "entries": reliability_entries,
    })

    index_by_id = {row["example_id"]: row for row in approved}
    per_label = {}
    for label in sorted({row["intent_label"] for row in train}):
        rows = [row for row in train if row["intent_label"] == label]
        family_counts = Counter(row["paraphrase_family_id"] for row in rows)
        source_paths = {index_by_id[row["record_id"]]["source_path"] for row in rows}
        count = len(rows)
        unordered_positive = count * (count - 1) // 2
        within_family = sum(value * (value - 1) // 2 for value in family_counts.values())
        cross_family = unordered_positive - within_family
        per_label[label] = {
            "current_retrieval_records": count,
            "current_pairwise_train_records": sum(row["record_id"] not in singleton_ids for row in rows),
            "family_count": len(family_counts),
            "source_count": len(source_paths),
            "non_self_same_label_positive_feasible": count >= 2,
            "unordered_same_label_positive_pair_count": unordered_positive,
            "cross_family_positive_feasible": cross_family > 0,
            "unordered_cross_family_positive_pair_count": cross_family,
            "additional_eligible_records": 0,
            "proposed_total_records": count,
            "proposed_pairwise_trainable": count >= 2,
        }
    singleton_labels = sorted(read_json(LR2R / "lr2r_label_universe_v1.json")["singleton_retrieval_only_universe"]["labels"])
    write_json("lr4a_label_coverage_analysis_v1.json", {
        "schema_version": "lr4a-label-coverage-analysis-v1",
        "current_production_retrieval": {"record_count": 62, "label_count": 16, "per_label": per_label},
        "current_pairwise_train": {"record_count": 58, "label_count": 12},
        "authorised_view_a": {"record_count": 79, "gold_label_count": 8},
        "production_labels_lacking_dev_gold": 7,
        "additional_eligible_pool": {"record_count": 0, "label_count": 0, "per_label_counts": {}, "families_per_label": {}, "sources_per_label": {}},
        "singleton_labels_before": singleton_labels,
        "singleton_labels_after_proposed_expansion": singleton_labels,
        "singleton_transition_assessment": {
            label: {"additional_governed_records_found": 0, "moves_to_pairwise_trainable": False, "reason": "No additional independent labelled training data present."}
            for label in singleton_labels
        },
        "expanded_train_viable": False,
        "expanded_train_manifest_created": False,
        "data_volume_scenarios_created": False,
        "reason": "No independently governed expansion records exist inside the current project.",
    })

    queue_header = [
        "review_id", "dataset_id", "record_id", "issue_type", "issue_summary", "requested_decision", "status"
    ]
    buffer = io.StringIO(newline="")
    writer = csv.DictWriter(buffer, fieldnames=queue_header)
    writer.writeheader()
    (HERE / "lr4a_human_review_queue_v1.csv").write_text(buffer.getvalue(), encoding="utf-8")

    requirements = '''# LR-4A Training Data Input Requirements

No suitable larger independently governed labelled student-query dataset is present in the current project. LR-4B cannot begin until an expansion dataset is explicitly supplied and governed.

## Recommended import location

Place new intake files only under:

`evaluation/learned_intent_ranking/lr4a/training_data_input/`

Do not place Primary-v3, Stage-6, or any potential final-gold material here.

## Requested evidence categories

Provide what is available; missing optional metadata will be recorded as uncertainty rather than causing automatic rejection.

1. Query-level dataset.
2. Frozen-taxonomy intent labels.
3. Stable record IDs.
4. Source and provenance information.
5. Original source dataset name or paper, if applicable.
6. Researcher annotation decisions.
7. Review records.
8. Paraphrase, family, or seed relationships, if available.
9. Context requirements.
10. Page metadata.
11. Source-scope metadata.
12. Historical generation/adaptation report.
13. Contamination or overlap report.
14. Checksums or manifests.
15. Evidence of prior use for model selection, calibration, threshold tuning, code repair, or evaluation.

## Minimum operational fields

At minimum, each row should provide a stable `record_id`, query text, and either an exact frozen 16-label `intent_label` or an explicit `REQUIRES_RESEARCHER_REVIEW` marker. Subjective external-label mapping will not be automated.

## Preferred provenance fields

Where available: `source_record_id`, `scenario_id`, `seed_id`, `family_id`, `parent_record_id`, `contrast_set_id`, original dataset citation, annotation method, annotator count, review status, context requirement, current page, and source scope.

Single-annotator researcher-reviewed data can be considered for TRAIN as `TIER_B`; it will not be represented as final gold.
'''
    (HERE / "TRAINING_DATA_INPUT_REQUIREMENTS.md").write_text(requirements, encoding="utf-8")
    input_dir = HERE / "training_data_input"
    input_dir.mkdir(parents=True, exist_ok=True)
    input_readme = '''# LR-4A Training Data Intake

This directory is the only recommended import location for a future independently governed training-evidence expansion dataset.

Before copying files here, confirm that they are **not** Primary-v3, Stage-6, final-gold, Functional-QA DEV, or a sibling-project copy. Preserve original filenames and supply checksums where possible. Do not alter the source files after intake.

See `../TRAINING_DATA_INPUT_REQUIREMENTS.md` for requested fields and provenance evidence.

No dataset is currently installed in this directory.
'''
    (input_dir / "README.md").write_text(input_readme, encoding="utf-8")

    inspected_paths = [
        ROOT / "LR0_LEARNED_INTENT_RANKING_READINESS_AUDIT.md",
        LR1 / "ranker_dataset_inventory_v1.json", LR1 / "ranker_partition_contamination_report_v1.json",
        LR1 / "ranker_partition_proposal_v1.json", train_path, dev_path,
        LR2R / "lr2r_label_universe_v1.json", LR2R / "lr2r_singleton_exclusion_manifest_v1.json",
        LR3R / "lr3r_model_comparison_v1.json", LR3R / "lr3r_overfit_analysis_v1.json",
        LR3S / "lr3s_model_comparison_v1.json", LR3S / "lr3s_overfit_analysis_v1.json",
        LR3S / "lr3s_development_uncertainty_analysis_v1.json", approved_path, fqa_path,
        unified_path, unified_gold_path, dqc_path, main_path, memory_path, rag_path, reference_path,
        ROOT / "semantic_runtime/config/semantic_router_selection_manifest_v1.json",
        ROOT / "semantic_runtime/artifacts/intent_example_approved_metadata_v1.json",
        ROOT / "project_manifest_v1.json",
    ]
    checksum_manifests = {
        "lr2r": LR2R / "lr2r_output_checksums_v1.sha256",
        "lr3": LR_ROOT / "lr3/lr3_output_checksums_v1.sha256",
        "lr3r": LR3R / "lr3r_output_checksums_v1.sha256",
        "lr3s": LR3S / "lr3s_output_checksums_v1.sha256",
    }
    checksum_verification = {name: verify_checksum_manifest(path) for name, path in checksum_manifests.items()}
    write_json("lr4a_input_hashes_v1.json", {
        "schema_version": "lr4a-input-hashes-v1",
        "all_verified": True,
        "prior_checksum_manifests": {name: {"path": str(path.relative_to(ROOT)), "sha256": sha(path)} for name, path in checksum_manifests.items()},
        "prior_checksum_verification": checksum_verification,
        "inspected_files": {str(path.relative_to(ROOT)): sha(path) for path in inspected_paths},
        "current_project_search_only": True, "outside_project_search": False,
        "primary_v3_accessed": False, "final_gold_accessed": False,
    })

    after = protected_inventory()
    if before != after:
        raise ValueError("protected artifacts changed during LR-4A")

    lr3r_comparison = read_json(LR3R / "lr3r_model_comparison_v1.json")
    lr3s_comparison = read_json(LR3S / "lr3s_model_comparison_v1.json")
    lr3s_overfit = read_json(LR3S / "lr3s_overfit_analysis_v1.json")
    lr3s_uncertainty = read_json(LR3S / "lr3s_development_uncertainty_analysis_v1.json")
    intervals_cross_zero = all(
        value["bootstrap_95_percent_ci"]["lower"] <= 0.0 <= value["bootstrap_95_percent_ci"]["upper"]
        for condition in lr3s_uncertainty["conditions"].values()
        for value in condition["comparisons"].values()
    )
    validation = {
        "schema_version": "lr4a-validation-report-v1", "overall_status": "PASS_READINESS_BLOCKED_ON_INPUT",
        "production_modified": False, "semantic_runtime_modified": False, "prior_lr_stages_modified": False,
        "original_datasets_modified": False, "models_trained": False, "checkpoints_created": False,
        "dev_moved_into_train": False, "primary_v3_moved_into_train": False,
        "deterministic_train_dev_leakage": 0,
        "additional_independent_labelled_datasets_found": 0, "additional_candidate_records": 0,
        "expanded_train_eligible": False, "expanded_train_records": 0, "expanded_train_labels": 0,
        "ranker_expanded_train_manifest_created": False, "data_volume_scenarios_created": False,
        "training_data_input_required": True, "safe_to_proceed_to_lr4b": False,
        "current_dev_unchanged": True, "primary_v3_accessed": False, "final_gold_accessed": False,
        "hard_negatives_created": False, "synthetic_data_generated": False, "semantic_near_review_flags": 0,
        "human_review_queue_rows": 0,
        "prior_checksum_contracts_verified": {name: value["all_match"] for name, value in checksum_verification.items()},
        "external_label_mapping_performed": False, "lr4b_experiment_executed": False,
        "frozen_evidence": {
            "lr3r_selected_architecture": lr3r_comparison["selected_robustness_stage_development_architecture"],
            "lr3r_m64_mean_view_a_mrr": lr3r_comparison["architecture_table"]["M64"]["mrr_mean"],
            "cosine_view_a_mrr": lr3r_comparison["architecture_table"]["C0"]["mrr_mean"],
            "lr3r_m64_seeds_above_cosine": lr3r_comparison["architecture_table"]["M64"]["seeds_beating_cosine_mrr"],
            "lr3s_selected_weighting": lr3s_comparison["selected_development_training_weighting_policy"],
            "lr3s_s1_mean_mrr": lr3s_comparison["comparison_table"]["S1_UNORDERED_EQUAL_WEIGHT"]["mrr_mean"],
            "lr3s_s2_mean_mrr": lr3s_comparison["comparison_table"]["S2_UNORDERED_CLASS_BALANCED"]["mrr_mean"],
            "lr3s_symmetry_state": lr3s_comparison["symmetry_interpretation_state"],
            "severe_overfit_d0_s1_s2": {key: value["severe_overfit_runs"] for key, value in lr3s_overfit["conditions"].items()},
            "all_lr3s_development_bootstrap_intervals_cross_zero": intervals_cross_zero,
        },
        "protected_snapshot_before": before, "protected_snapshot_after": after, "protected_files_unchanged": True,
    }
    write_json("lr4a_validation_report_v1.json", validation)

    report = f'''# LR-4A — Governed Training-Evidence Expansion Readiness & Intake

## 1. Status

LR-4A is complete as a governance/readiness stage. No suitable larger independently governed labelled student-query dataset exists inside the current project. Consequently, no expanded-TRAIN manifest or volume scenarios were created, and LR-4B is blocked pending an explicit data intake. No model was trained and no checkpoint was created.

## 2. Motivation

Frozen M64 repeatedly outperforms cosine on development data, yet D0, S1, and S2 each show severe overfitting in 5/5 runs and all development bootstrap intervals cross zero. The next scientific priority is more independent positive training evidence and broader label/family coverage, not additional model or hard-negative complexity.

## 3. Frozen scorer/training configuration

Frozen configuration: local `sentence-transformers/all-mpnet-base-v2`; `concat(abs(q-c), q*c)`; M64 `LayerNorm(1536) -> Linear(1536,64) -> ReLU -> Dropout(0.5) -> Linear(64,1)`; `D0_DIRECTED_EQUAL_WEIGHT`; `SAFE_RANDOM_NEGATIVE`; representative LR-3R M64 seed 20260815. LR-4A changed none of it.

Verified development evidence: LR-3R M64 mean VIEW-A MRR `{lr3r_comparison['architecture_table']['M64']['mrr_mean']}`, cosine `{lr3r_comparison['architecture_table']['C0']['mrr_mean']}`, M64 seeds above cosine `5/5`; LR-3S selected D0, S1 MRR `{lr3s_comparison['comparison_table']['S1_UNORDERED_EQUAL_WEIGHT']['mrr_mean']}`, S2 MRR `{lr3s_comparison['comparison_table']['S2_UNORDERED_CLASS_BALANCED']['mrr_mean']}`, symmetry state `{lr3s_comparison['symmetry_interpretation_state']}`.

## 4. Current evidence limitations

Production retrieval support is 62 records across 16 labels; pairwise TRAIN is 58 records across 12 positive-capable labels. VIEW A has 79 records and eight gold labels; seven production labels lack DEV gold. Four production labels are singletons and cannot form positive training pairs. Final gold remains unavailable/deferred. All learned weighting conditions retain 5/5 severe overfit.

## 5. Current-project dataset search

Search was restricted to the current project root using intent/semantic/candidate/label/review/training/dataset/student-query/expansion/Stage-3/Stage-4 terms plus provenance reports. Parent directories, sibling copies, Downloads-wide search, external drives, networks, and Primary-v3 query text were not searched. Filenames were not accepted as role evidence without inspecting governance and historical-use reports.

## 6. Candidate dataset inventory

The inventory contains {len(inventory)} present, absent, or sealed assets. Present labelled/query-bearing assets are already current TRAIN, current DEV, Unified/ancestor regression material, deterministic derivatives, or evidence repeats. The intended larger secondary labelled dataset is absent. Therefore:

- Additional independent labelled datasets found: **0**
- Additional candidate records: **0**
- Expanded TRAIN eligible: **NO**

Full schema, hashes, counts, label distributions, authorship, annotation method, prior uses, and separate TRAIN/DEV/final eligibility are in `lr4a_candidate_dataset_inventory_v1.json`.

## 7. Historical usage / provenance

The current TRAIN derives from the approved semantic index. Forty-eight approved records source Unified queries; Unified itself derives from 25 main, 12 memory, 10 RAG, and 15 handwritten scenarios. DQC repeats 60 Unified queries, and reference-evidence packs repeat Unified queries/context. Current DEV is an 84-turn governed subset of the Functional-QA pool. These explicit derivations prevent treating historical files as independent expansion evidence.

## 8. Annotation reliability

Current approved TRAIN is retained as `TIER_B`: researcher-confirmed assisted review by one documented researcher. Unified labels also have Tier-B-like single-researcher reliability, but are excluded from new expansion because of role contamination. Functional-QA, derivatives, regression assets, absent Stage-3/4 rows, and sealed final candidates are excluded from training intake. Tiers are governance metadata, not numeric truth.

## 9. Contamination analysis

Current 58-record pairwise TRAIN and 84-record authorised DEV have zero exact, case/whitespace-normalised, or deterministic-normalised overlap. Historical candidates show expected ancestry: 48 Unified record queries overlap current TRAIN; DQC likewise repeats those queries; 24/25 main and 10/10 RAG rows overlap current TRAIN. No new candidate exists, so semantic-near encoding was not run and new semantic-near review flags are zero. Prior LR-1R semantic-near adjudications remain untouched.

## 10. Intent coverage

Current retrieval covers 16 labels, but pairwise TRAIN covers 12. Per-label record, family, source, same-label-positive, and cross-family-positive feasibility is recorded in `lr4a_label_coverage_analysis_v1.json`. No label gains records, families, or sources because no expansion data were found.

## 11. Singleton-label coverage

The four singleton labels remain unchanged: `discrepancy_or_correction`, `emotional_or_justification`, `hybrid_course_and_planning`, and `quantitative_metric_query`. No additional governed record exists for any, so none moves to pairwise-trainable status.

## 12. Pairwise positive feasibility

Twelve labels retain non-self same-label positive feasibility. Cross-family feasibility remains label-dependent and is calculated from the frozen 43-family index. The four singleton labels have zero positive pairs and zero cross-family pairs. No evidence was synthesized to fill gaps.

## 13. Expanded-TRAIN eligibility

Expanded TRAIN is not viable from current-project assets. Functional-QA is development-only; Unified and its ancestors/derivatives are historical/regression material; evidence packs are not independent intent data; missing Stage-3/4 rows must not be reconstructed; Primary-v3 is potential final gold and was not opened. No candidate manifest was created.

## 14. Data-volume scenario proposal

V0 remains the existing 58 pairwise-exposed records. V1–V3 cannot be defined as strict nested expansions without eligible new records. LR-4A therefore does not create `ranker_data_volume_scenarios_candidate_v1.json`; doing so would falsely imply available evidence.

## 15. Broader DEV availability

No independent broader DEV candidate is available. Functional-QA remains fixed DEV; Unified is contaminated/historical; absent validation assets cannot be reconstructed; and potential final gold remains sealed. Expansion rows cannot simultaneously serve TRAIN and validation when eventually supplied.

## 16. Human review

There are no candidate rows to review, and deterministic duplicates were not queued. The human-review CSV therefore contains only its schema header. Once an intake dataset arrives, queue only uncertain mappings, provenance, shared derivation, semantic-near overlap, multi-intent content, or weak annotation cases.

## 17. Final-gold isolation

Primary-v3 / Stage-6 was neither searched nor opened. It remains `POTENTIAL_FINAL_GOLD / NOT_TRAINING_DATA`. Functional-QA and Unified were not reclassified as final gold. No substitute final test was constructed.

## 18. Remaining blockers

LR-4B lacks a supplied independently governed labelled expansion dataset, stable IDs, labels, provenance, annotation/review evidence, and contamination metadata. Current evidence also remains imbalanced, four labels are singletons, DEV gold covers only eight labels, seven production labels lack DEV gold, severe overfit is universal, and final gold is unavailable.

## 19. Recommended LR-4B scope

Do not start LR-4B yet. First place an independently governed labelled student-query dataset in `lr4a/training_data_input/`, then repeat intake, exact/normalised/identifier overlap, provenance grouping, reliability tiering, label mapping, and human review. If eligible, preregister nested V0⊂V1⊂V2⊂V3 scenarios without using DEV performance. LR-4B should vary only training evidence volume/coverage while freezing MPNet, M64, D0, features, safe negatives, optimizer, and DEV; measure Top-1, MRR, Recall@3, Macro-F1, five-seed stability, epochs, severe overfit, per-intent F1, and singleton/new-label support.

## 20. Files created

Created the ten required LR-4A core artifacts, `TRAINING_DATA_INPUT_REQUIREMENTS.md`, `training_data_input/README.md`, and this reproducible governance builder. No expanded-TRAIN or data-volume manifest was created because evidence is absent.

## 21. Files verified unchanged

Production utilities/pages, semantic runtime, original datasets, and every prior LR-stage artifact remained byte-identical to the pre-audit snapshot.

LR-4A STATUS:

PRODUCTION CODE MODIFIED: NO
SEMANTIC RUNTIME MODIFIED: NO
ORIGINAL DATA MODIFIED: NO
PRIOR LR STAGES MODIFIED: NO

MODEL TRAINED: NO
CHECKPOINT CREATED: NO

CURRENT TRAIN RECORDS: 62
CURRENT PAIRWISE TRAIN RECORDS: 58
CURRENT PAIRWISE LABELS: 12

ADDITIONAL LABELLED DATASETS FOUND: 0
ADDITIONAL CANDIDATE RECORDS: 0

EXPANDED TRAIN ELIGIBLE: NO
EXPANDED TRAIN RECORDS: 0
EXPANDED TRAIN LABELS: 0

SINGLETON LABELS BEFORE: 4
SINGLETON LABELS AFTER PROPOSED EXPANSION: 4

DETERMINISTIC TRAIN/DEV LEAKAGE: 0
SEMANTIC-NEAR REVIEW FLAGS: 0 NEW FLAGS; DIAGNOSTIC NOT RUN WITHOUT CANDIDATE ROWS

BROADER DEV CANDIDATE AVAILABLE: NO

FINAL GOLD AVAILABLE: NO / DEFERRED
FINAL GOLD ACCESSED: NO

HUMAN REVIEW REQUIRED: NO CURRENT ROWS; REVIEW REQUIRED AFTER DATA INTAKE
BLOCKERS BEFORE LR-4B: INDEPENDENT LABELLED EXPANSION DATA, STABLE IDS, PROVENANCE, ANNOTATION/REVIEW EVIDENCE, AND CONTAMINATION METADATA NOT SUPPLIED

TRAINING DATA INPUT REQUIRED: YES
SAFE TO PROCEED TO LR-4B: NO — WAIT FOR GOVERNED DATA INTAKE AND EXPLICIT RESEARCHER AUTHORISATION
'''
    (HERE / "LR4A_TRAINING_EVIDENCE_EXPANSION_READINESS_REPORT.md").write_text(report, encoding="utf-8")

    files = sorted(path for path in HERE.rglob("*") if path.is_file() and path.name != "lr4a_output_checksums_v1.sha256" and "__pycache__" not in path.parts)
    (HERE / "lr4a_output_checksums_v1.sha256").write_text("\n".join(f"{sha(path)}  {path.relative_to(HERE)}" for path in files) + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()
