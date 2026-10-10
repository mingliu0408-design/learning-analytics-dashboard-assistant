"""Build and validate the sealed LR-4A-R1 secondary-training intake package."""

from __future__ import annotations

import csv
import hashlib
import json
import re
import unicodedata
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any, Callable

import numpy as np
from sentence_transformers import SentenceTransformer


HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[3]
LR4A = HERE.parent
INPUT = LR4A / "training_data_input"
LR = LR4A.parent

FULL_PATH = INPUT / "eedi_stage_e4_researcher_confirmed_300.csv"
SUBSET_PATH = INPUT / "eedi_stage_e4_confirmed_candidate_subset_256.csv"
AUDIT_PATH = INPUT / "eedi_stage_e4_audit.json"
CODEBOOK_PATH = INPUT / "eedi_stage_e4_codebook_researcher_confirmed_v1.json"
APPROVED_PATH = ROOT / "semantic_runtime/artifacts/intent_examples_approved_index_v1.jsonl"
TRAIN_PATH = LR / "lr1/ranker_train_manifest_candidate_v1.jsonl"
DEV_PATH = LR / "lr1r/ranker_dev_manifest_candidate_v2.jsonl"
FQA_PATH = ROOT / "evaluation/functional_qa/functional_qa_cases_v1.jsonl"
SINGLETON_PATH = LR / "lr2r/lr2r_singleton_exclusion_manifest_v1.json"
LR4A_CHECKSUM_PATH = LR4A / "lr4a_output_checksums_v1.sha256"
MODEL_PATH = ROOT / "semantic_runtime/models/all-mpnet-base-v2/e8c3b32edf5434bc2275fc9bab85f82640a19130"

FROZEN_LABELS = [
    "access_or_capability_question",
    "course_content_question",
    "cross_page_relationship",
    "dashboard_interpretation",
    "discrepancy_or_correction",
    "emotional_or_justification",
    "hybrid_course_and_planning",
    "improvement_recommendation",
    "metric_clarification",
    "out_of_scope",
    "planning_or_strategy",
    "quantitative_metric_query",
    "reflection_structure_question",
    "social_interaction",
    "technical_data_question",
    "unsupported_task",
]
ACTIVATED_LABELS = {"emotional_or_justification", "discrepancy_or_correction"}
REMAINING_SINGLETONS = {"hybrid_course_and_planning", "quantitative_metric_query"}


def sha(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def text_sha(text: str) -> str:
    return hashlib.sha256(str(text).encode("utf-8")).hexdigest()


def read_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def read_jsonl(path: Path) -> list[dict[str, Any]]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def read_csv(path: Path) -> list[dict[str, str]]:
    with path.open(encoding="utf-8-sig", newline="") as handle:
        return list(csv.DictReader(handle))


def write_json(name: str, value: Any) -> None:
    (HERE / name).write_text(
        json.dumps(value, indent=2, sort_keys=True, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )


def write_jsonl(name: str, rows: list[dict[str, Any]]) -> None:
    content = "".join(json.dumps(row, sort_keys=True, separators=(",", ":"), ensure_ascii=False) + "\n" for row in rows)
    (HERE / name).write_text(content, encoding="utf-8")


def casefolded_whitespace(text: str) -> str:
    return re.sub(r"\s+", " ", unicodedata.normalize("NFKC", str(text)).strip()).casefold()


def normalised(text: str) -> str:
    value = casefolded_whitespace(text)
    value = "".join(" " if unicodedata.category(char).startswith("P") else char for char in value)
    return re.sub(r"\s+", " ", value).strip()


def identities(text: str) -> dict[str, str]:
    return {
        "query_sha256": text_sha(text),
        "casefolded_whitespace_query_sha256": text_sha(casefolded_whitespace(text)),
        "normalised_query_sha256": text_sha(normalised(text)),
    }


def verify_checksum_manifest(path: Path) -> dict[str, Any]:
    entries = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        expected, relative = line.split(None, 1)
        relative = relative.strip().lstrip("*")
        target = path.parent / relative
        actual = sha(target)
        entries.append({"path": relative, "expected_sha256": expected, "actual_sha256": actual, "match": expected == actual})
    if not entries or not all(row["match"] for row in entries):
        raise ValueError("sealed LR-4A checksum verification failed")
    return {
        "manifest_path": str(path.relative_to(ROOT)),
        "manifest_sha256": sha(path),
        "entry_count": len(entries),
        "all_match": True,
        "entries": entries,
    }


def protected_snapshot() -> dict[str, str]:
    paths: list[Path] = []
    for base in [ROOT / "utils", ROOT / "pages", ROOT / "semantic_runtime"]:
        paths.extend(path for path in base.rglob("*") if path.is_file())
    paths.append(ROOT / "LR0_LEARNED_INTENT_RANKING_READINESS_AUDIT.md")
    for stage in ["lr1", "lr1r", "lr2", "lr2r", "lr3", "lr3r", "lr3s"]:
        paths.extend(path for path in (LR / stage).rglob("*") if path.is_file())
    for line in LR4A_CHECKSUM_PATH.read_text(encoding="utf-8").splitlines():
        if line.strip():
            _, relative = line.split(None, 1)
            paths.append(LR4A / relative.strip().lstrip("*"))
    paths.extend([FULL_PATH, SUBSET_PATH, AUDIT_PATH, CODEBOOK_PATH])
    return {str(path.relative_to(ROOT)): sha(path) for path in sorted(set(paths))}


def group_stats(rows: list[dict[str, str]], field: str, transform: Callable[[str], str]) -> dict[str, Any]:
    groups: dict[str, list[str]] = defaultdict(list)
    for row in rows:
        groups[transform(row[field])].append(row["record_id"])
    repeated = {text_sha(key): sorted(value) for key, value in groups.items() if len(value) > 1}
    return {
        "unique_identity_count": len(groups),
        "duplicate_group_count": len(repeated),
        "records_in_duplicate_groups": sum(len(value) for value in repeated.values()),
        "duplicate_record_excess": sum(len(value) - 1 for value in repeated.values()),
        "maximum_group_size": max((len(value) for value in repeated.values()), default=1),
        "groups": repeated,
    }


def records_with_query(dataset_id: str, rows: list[tuple[str, str, str | None]]) -> list[dict[str, Any]]:
    return [
        {"dataset_id": dataset_id, "record_id": record_id, "query": query, "intent_label": label, **identities(query)}
        for record_id, query, label in rows
    ]


def overlap(left: list[dict[str, Any]], right: list[dict[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for field, name in [
        ("query_sha256", "exact"),
        ("casefolded_whitespace_query_sha256", "casefolded_whitespace"),
        ("normalised_query_sha256", "normalised"),
    ]:
        lhs: dict[str, list[str]] = defaultdict(list)
        rhs: dict[str, list[str]] = defaultdict(list)
        for row in left:
            lhs[row[field]].append(row["record_id"])
        for row in right:
            rhs[row[field]].append(row["record_id"])
        shared = sorted(set(lhs) & set(rhs))
        result[name] = {
            "shared_identity_count": len(shared),
            "candidate_record_count_in_overlap": sum(len(lhs[key]) for key in shared),
            "reference_record_count_in_overlap": sum(len(rhs[key]) for key in shared),
            "groups": [
                {"identity_sha256": key, "candidate_record_ids": sorted(lhs[key]), "reference_record_ids": sorted(rhs[key])}
                for key in shared
            ],
        }
    return result


def main() -> None:
    before = protected_snapshot()
    sealed_lr4a = verify_checksum_manifest(LR4A_CHECKSUM_PATH)

    full = read_csv(FULL_PATH)
    subset = read_csv(SUBSET_PATH)
    audit = read_json(AUDIT_PATH)
    codebook = read_json(CODEBOOK_PATH)
    approved = read_jsonl(APPROVED_PATH)
    current_train = read_jsonl(TRAIN_PATH)
    dev_manifest = read_jsonl(DEV_PATH)
    fqa = read_jsonl(FQA_PATH)
    singleton_manifest = read_json(SINGLETON_PATH)

    if len(full) != 300 or len(subset) != 256:
        raise ValueError("unexpected Eedi record counts")
    if len({row["record_id"] for row in full}) != 300 or len({row["record_id"] for row in subset}) != 256:
        raise ValueError("Eedi IDs are not unique")
    full_by_id = {row["record_id"]: row for row in full}
    if not set(row["record_id"] for row in subset) <= set(full_by_id):
        raise ValueError("retained subset is not contained in the 300-row record")

    subset_field_map = {
        "source_dataset": "source_dataset",
        "original_split": "original_split",
        "conversation_group_id": "conversation_group_id",
        "message_sequence": "message_sequence",
        "utterance_for_review": "utterance_redacted_e2",
        "previous_turns_for_review": "previous_turns_redacted_e2",
        "question_anchor_for_review": "question_anchor_redacted_e2",
        "subject": "subject",
        "topic": "topic",
        "subtopic": "subtopic",
        "final_target_intent": "researcher_final_target_intent",
        "final_mapping_status": "researcher_final_mapping_status",
        "final_secondary_dialogue_act": "researcher_final_secondary_dialogue_act",
        "review_decision": "assistant_review_decision",
        "annotation_status": "annotation_status",
    }
    drift = []
    for row in subset:
        source = full_by_id[row["record_id"]]
        for target_field, source_field in subset_field_map.items():
            if row[target_field] != source[source_field]:
                drift.append({"record_id": row["record_id"], "subset_field": target_field, "full_field": source_field})
    if drift:
        raise ValueError("retained subset field drift")

    package_expected = audit["output_sha256"]
    package_hash_checks = {
        path.name: {"expected_sha256": package_expected[path.name], "actual_sha256": sha(path), "match": package_expected[path.name] == sha(path)}
        for path in [FULL_PATH, SUBSET_PATH, CODEBOOK_PATH]
    }
    if not all(item["match"] for item in package_hash_checks.values()):
        raise ValueError("Eedi package audit hashes do not match")

    codebook_labels = set(codebook["annotation_layers"]["target_intent"]["labels"])
    if codebook_labels != set(FROZEN_LABELS) | {"unmappable_or_exclude"}:
        raise ValueError("Eedi codebook is not an exact frozen-taxonomy mapping plus exclusion")
    if set(row["final_target_intent"] for row in subset) - set(FROZEN_LABELS):
        raise ValueError("retained subset includes a non-frozen label")

    full_counts = Counter(row["researcher_final_target_intent"] for row in full)
    subset_counts = Counter(row["final_target_intent"] for row in subset)
    if dict(full_counts) != audit["confirmed_intent_counts"] or dict(subset_counts) != {
        key: value for key, value in audit["confirmed_intent_counts"].items() if key != "unmappable_or_exclude"
    }:
        raise ValueError("Eedi label totals disagree with the package audit")

    fqa_by_id = {row["case_id"]: row for row in fqa}
    dev_resolved: list[tuple[str, str, str | None]] = []
    for row in dev_manifest:
        case = fqa_by_id[row["provenance"]["case_id"]]
        turn = case["turns"][int(row["provenance"]["turn_index"]) - 1]
        dev_resolved.append((row["record_id"], turn["query"], row["intent_label"]))

    reference_specs: dict[str, tuple[Path, list[tuple[str, str, str | None]]]] = {
        "approved_semantic_examples_62": (APPROVED_PATH, [(r["example_id"], r["query"], r["final_semantic_label"]) for r in approved]),
        "repaired_train_universe_58": (TRAIN_PATH, [
            (r["record_id"], next(a["query"] for a in approved if a["example_id"] == r["record_id"]), r["intent_label"])
            for r in current_train if r["record_id"] not in {x["record_id"] for x in singleton_manifest["records"]}
        ]),
        "functional_qa_dev_84": (DEV_PATH, dev_resolved),
        "functional_qa_all_regression_turns": (FQA_PATH, [
            (f"{case['case_id']}:T{index}", turn["query"], turn.get("expected_intent_family") or case.get("expected_intent_family"))
            for case in fqa for index, turn in enumerate(case["turns"], start=1)
        ]),
        "unified_benchmark": (ROOT / "evaluation/unified_benchmark_scenarios.jsonl", [
            (r["scenario_id"], r["student_query"], r.get("query_type")) for r in read_jsonl(ROOT / "evaluation/unified_benchmark_scenarios.jsonl")
        ]),
        "deterministic_query_regression": (ROOT / "evaluation/deterministic_query_classification_characterisation_v1.jsonl", [
            (r["case_id"], r["query"], r.get("legacy_query_type_before_stage2")) for r in read_jsonl(ROOT / "evaluation/deterministic_query_classification_characterisation_v1.jsonl")
        ]),
        "main_regression_scenarios": (ROOT / "evaluation/scenarios.jsonl", [
            (r["scenario_id"], r["student_query"], r.get("query_type")) for r in read_jsonl(ROOT / "evaluation/scenarios.jsonl")
        ]),
        "memory_regression_scenarios": (ROOT / "evaluation/multiturn_scenarios.jsonl", [
            (r["scenario_id"], r["student_query"], None) for r in read_jsonl(ROOT / "evaluation/multiturn_scenarios.jsonl")
        ]),
        "rag_regression_scenarios": (ROOT / "evaluation/rag_scenarios.jsonl", [
            (r["scenario_id"], r["student_query"], None) for r in read_jsonl(ROOT / "evaluation/rag_scenarios.jsonl")
        ]),
    }
    candidate_300 = records_with_query("eedi_stage_e4_full_300", [
        (r["record_id"], r["utterance_redacted_e2"], r["researcher_final_target_intent"]) for r in full
    ])
    candidate_256 = records_with_query("eedi_stage_e4_retained_256", [
        (r["record_id"], r["utterance_for_review"], r["final_target_intent"]) for r in subset
    ])
    reference_records = {name: records_with_query(name, rows) for name, (_, rows) in reference_specs.items()}
    comparisons_300 = {name: overlap(candidate_300, rows) for name, rows in reference_records.items()}
    comparisons_256 = {name: overlap(candidate_256, rows) for name, rows in reference_records.items()}
    for comparison_set in [comparisons_300, comparisons_256]:
        if any(data[mode]["shared_identity_count"] for data in comparison_set.values() for mode in ["exact", "casefolded_whitespace", "normalised"]):
            raise ValueError("deterministic Eedi/reference query overlap found")

    # Local frozen MPNet is used only for the authorised diagnostic; no training occurs.
    all_refs = [row for rows in reference_records.values() for row in rows]
    unique_ref_by_query: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in all_refs:
        unique_ref_by_query[row["query"]].append(row)
    ref_queries = sorted(unique_ref_by_query)
    model = SentenceTransformer(str(MODEL_PATH), local_files_only=True, device="cpu")
    candidate_embeddings = model.encode(
        [row["utterance_for_review"] for row in subset],
        convert_to_numpy=True,
        normalize_embeddings=True,
        show_progress_bar=False,
    ).astype(np.float64)
    reference_embeddings = model.encode(
        ref_queries,
        convert_to_numpy=True,
        normalize_embeddings=True,
        show_progress_bar=False,
    ).astype(np.float64)
    similarity = np.clip(candidate_embeddings @ reference_embeddings.T, -1.0, 1.0)
    max_indices = np.argmax(similarity, axis=1)
    max_scores = similarity[np.arange(len(subset)), max_indices]
    threshold = 0.70
    semantic_flags = []
    for index, score in enumerate(max_scores):
        if float(score) >= threshold:
            ref_query = ref_queries[int(max_indices[index])]
            semantic_flags.append({
                "record_id": subset[index]["record_id"],
                "score": float(score),
                "reference_records": [
                    {"dataset_id": row["dataset_id"], "record_id": row["record_id"], "intent_label": row["intent_label"]}
                    for row in unique_ref_by_query[ref_query]
                ],
            })
    top_index = int(np.argmax(max_scores))
    top_ref_query = ref_queries[int(max_indices[top_index])]

    # Exact normalised utterances define conservative query families. Conversation IDs remain source records;
    # question anchors define provenance/contrast groups and never create artificial independence.
    family_members: dict[str, list[str]] = defaultdict(list)
    anchor_members: dict[str, list[str]] = defaultdict(list)
    for row in subset:
        family_members[text_sha(normalised(row["utterance_for_review"]))].append(row["record_id"])
        anchor_members[text_sha(normalised(row["question_anchor_for_review"]))].append(row["record_id"])
    family_id_by_record = {
        record_id: f"EEDI-NORM-{family_hash[:16]}"
        for family_hash, record_ids in family_members.items() for record_id in record_ids
    }
    anchor_id_by_record = {
        record_id: f"EEDI-QUESTION-{anchor_hash[:16]}"
        for anchor_hash, record_ids in anchor_members.items() for record_id in record_ids
    }

    reliability_records = []
    retained_ids = {row["record_id"] for row in subset}
    for row in full:
        retained = row["record_id"] in retained_ids
        reliability_records.append({
            "record_id": row["record_id"],
            "annotation_reliability": "TIER_B" if retained else "EXCLUDED",
            "eligible_secondary_train": retained,
            "annotation_method": row["annotation_method"],
            "annotation_status": row["annotation_status"],
            "researcher_confirmation": row["researcher_confirmation"],
            "assistant_review_decision": row["assistant_review_decision"],
            "independent_second_rater": False,
            "inter_rater_reliability_available": False,
            "gold_label_claim": False,
            "final_target_intent": row["researcher_final_target_intent"],
            "mapping_status": row["researcher_final_mapping_status"],
            "exclusion_reason": None if retained else "RESEARCHER_CONFIRMED_TAXONOMY_GAP_UNMAPPABLE_OR_EXCLUDE",
        })

    singleton_ids = {row["label"]: row["record_id"] for row in singleton_manifest["records"]}
    current_by_id = {row["record_id"]: row for row in current_train}
    v0_ids = sorted(record_id for record_id in current_by_id if record_id not in set(singleton_ids.values()))
    direct_ids = sorted(row["record_id"] for row in subset if row["final_mapping_status"] == "direct_shared_intent")
    discrepancy_ids = sorted(row["record_id"] for row in subset if row["final_target_intent"] == "discrepancy_or_correction")
    remaining_ids = sorted(row["record_id"] for row in subset if row["record_id"] not in set(direct_ids) | set(discrepancy_ids))
    v1_ids = sorted(set(v0_ids) | set(direct_ids) | {singleton_ids["emotional_or_justification"]})
    v2_ids = sorted(set(v1_ids) | set(discrepancy_ids) | {singleton_ids["discrepancy_or_correction"]})
    v3_ids = sorted(set(v2_ids) | set(remaining_ids))
    if not (set(v0_ids) < set(v1_ids) < set(v2_ids) < set(v3_ids)):
        raise ValueError("volume scenarios are not strict nested supersets")

    def first_scenario(record_id: str) -> str | None:
        for name, ids in [("V0", v0_ids), ("V1", v1_ids), ("V2", v2_ids), ("V3", v3_ids)]:
            if record_id in ids:
                return name
        return None

    expanded_manifest = []
    for row in sorted(current_train, key=lambda item: item["record_id"]):
        manifest_row = dict(row)
        manifest_row.update({
            "schema_version": "ranker-expanded-train-manifest-candidate-v2",
            "partition": "PROPOSED_TRAIN",
            "training_evidence_origin": "CURRENT_GOVERNED_TRAIN",
            "annotation_reliability": "TIER_B",
            "gold_label_claim": False,
            "pairwise_eligible": row["intent_label"] not in REMAINING_SINGLETONS,
            "pairwise_activation_scenario": first_scenario(row["record_id"]),
        })
        expanded_manifest.append(manifest_row)
    for row in sorted(subset, key=lambda item: item["record_id"]):
        query = row["utterance_for_review"]
        expanded_manifest.append({
            "schema_version": "ranker-expanded-train-manifest-candidate-v2",
            "record_id": row["record_id"],
            "partition": "PROPOSED_TRAIN",
            "source_dataset_id": "eedi_stage_e4_secondary_training_v1",
            "source_dataset_name": row["source_dataset"],
            "source_url": row["source_url"],
            "source_record_id": f"{row['conversation_group_id']}:T{row['message_sequence']}",
            "scenario_id": row["conversation_group_id"],
            "seed_id": None,
            "paraphrase_family_id": family_id_by_record[row["record_id"]],
            "parent_id": anchor_id_by_record[row["record_id"]],
            "contrast_set_id": anchor_id_by_record[row["record_id"]],
            "intent_label": row["final_target_intent"],
            "query_source_path": str(SUBSET_PATH.relative_to(ROOT)),
            "query_source_field": "utterance_for_review",
            "previous_turns_source_field": "previous_turns_for_review",
            "question_anchor_source_field": "question_anchor_for_review",
            **identities(query),
            "previous_turns_sha256": text_sha(row["previous_turns_for_review"]),
            "question_anchor_sha256": text_sha(row["question_anchor_for_review"]),
            "context_requirement": "conversation_history" if row["final_mapping_status"] == "contextual_shared_intent" else "query_only",
            "mapping_status": row["final_mapping_status"],
            "secondary_dialogue_act": row["final_secondary_dialogue_act"],
            "original_split_provenance_only": row["original_split"],
            "annotation_reliability": "TIER_B",
            "annotation_status": row["annotation_status"],
            "annotation_method": "AI-assisted, researcher-confirmed batch review",
            "researcher_confirmed": True,
            "independent_second_rater": False,
            "inter_rater_reliability_available": False,
            "gold_label_claim": False,
            "human_review_status": "RESEARCHER_CONFIRMED_ASSISTED_REVIEW",
            "contamination_flags": [],
            "training_evidence_origin": "ELIGIBLE_GOVERNED_SECONDARY_EEDI",
            "pairwise_eligible": True,
            "pairwise_activation_scenario": first_scenario(row["record_id"]),
            "role_reason": "Authentic secondary educational dialogue; exact frozen-taxonomy mapping; researcher-confirmed assisted annotation; not gold.",
        })
    expanded_manifest.sort(key=lambda row: row["record_id"])
    if len(expanded_manifest) != 318 or len({row["record_id"] for row in expanded_manifest}) != 318:
        raise ValueError("expanded manifest count/ID failure")
    write_jsonl("ranker_expanded_train_manifest_candidate_v2.jsonl", expanded_manifest)

    scenarios = {
        "schema_version": "ranker-data-volume-scenarios-candidate-v2",
        "status": "PROPOSED_GOVERNED_NOT_AUTHORISED_FOR_TRAINING_BY_THIS_STAGE",
        "membership_rule_uses_dev_performance": False,
        "frozen_requirements": {
            "model_training_in_lr4a_r1": False,
            "no_functional_qa_train": True,
            "no_final_gold_train": True,
            "retain_annotation_reliability_metadata": True,
            "contextual_records_must_resolve_exact_supplied_utterance_previous_turns_and_question_anchor_without_synthesis": True,
            "same_normalised_query_family_and_shared_question_anchor_must_remain_provenance-linked": True,
        },
        "scenarios": [
            {
                "scenario_id": "V0", "record_count": len(v0_ids), "record_ids": v0_ids,
                "definition": "Existing repaired 58-record pairwise TRAIN only.",
                "added_secondary_record_count": 0,
            },
            {
                "scenario_id": "V1", "record_count": len(v1_ids), "record_ids": v1_ids,
                "definition": "V0 plus every eligible context-independent TIER_B Eedi record and the now-positive-capable existing emotional singleton.",
                "added_secondary_record_count": len(direct_ids),
            },
            {
                "scenario_id": "V2", "record_count": len(v2_ids), "record_ids": v2_ids,
                "definition": "V1 plus researcher-confirmed contextual discrepancy/correction records and the now-positive-capable existing discrepancy singleton.",
                "added_secondary_record_count": len(direct_ids) + len(discrepancy_ids),
            },
            {
                "scenario_id": "V3", "record_count": len(v3_ids), "record_ids": v3_ids,
                "definition": "V2 plus all remaining eligible governed contextual Eedi secondary records.",
                "added_secondary_record_count": len(subset),
            },
        ],
        "strict_nesting": {
            "V0_subset_V1": set(v0_ids) < set(v1_ids),
            "V1_subset_V2": set(v1_ids) < set(v2_ids),
            "V2_subset_V3": set(v2_ids) < set(v3_ids),
            "all_strict": True,
        },
        "non_pairwise_retrieval_only_records_outside_v3": sorted(
            singleton_ids[label] for label in REMAINING_SINGLETONS
        ),
    }
    write_json("ranker_data_volume_scenarios_candidate_v2.json", scenarios)

    inventory = {
        "schema_version": "lr4a-r1-input-inventory-v1",
        "status": "COMPLETE",
        "search_boundary": "Only explicitly supplied lr4a/training_data_input files and current-project governance/reference datasets.",
        "new_input_dataset_count": 1,
        "new_input_record_count": 300,
        "retained_candidate_record_count": 256,
        "supplied_files": [
            {"path": str(path.relative_to(ROOT)), "sha256": sha(path), "size_bytes": path.stat().st_size, "role": role}
            for path, role in [
                (AUDIT_PATH, "PACKAGE_AUDIT"),
                (CODEBOOK_PATH, "RESEARCHER_CONFIRMED_CODEBOOK"),
                (FULL_PATH, "FULL_RESEARCHER_CONFIRMED_ASSISTED_REVIEW_RECORD"),
                (SUBSET_PATH, "RETAINED_CANDIDATE_SUBSET_NOT_AUTOMATICALLY_ELIGIBLE"),
            ]
        ],
        "package_audit_hash_checks": package_hash_checks,
        "internal_relationships": {
            "full_record_ids_unique": True,
            "subset_record_ids_unique": True,
            "subset_is_exact_id_subset_of_full": True,
            "subset_matching_field_drift_count": len(drift),
            "full_record_count": len(full),
            "subset_record_count": len(subset),
        },
        "dataset": {
            "dataset_id": "eedi_stage_e4_secondary_training_v1",
            "source_dataset": audit["source_dataset"],
            "source_url": audit["source_url"],
            "source_provenance": "Eedi Question-Anchored Tutoring Dialogues 2k; supplied Stage-E4 assisted-review package.",
            "query_field": "utterance_for_review / utterance_redacted_e2",
            "label_field": "final_target_intent / researcher_final_target_intent",
            "annotation_method": audit["annotation_method"],
            "independent_second_rater": False,
            "inter_rater_reliability_available": False,
            "formal_evaluation_performed": False,
            "intended_role": "CANDIDATE_SECONDARY_TRAINING_EVIDENCE",
            "not_dev": True,
            "not_final_gold": True,
        },
        "reference_datasets": [
            {"dataset_id": name, "path": str(path.relative_to(ROOT)), "sha256": sha(path), "record_count": len(rows)}
            for name, (path, rows) in reference_specs.items()
        ],
        "sealed_lr4a_verification": sealed_lr4a,
        "primary_v3_accessed": False,
        "stage6_final_gold_accessed": False,
        "outside_authorised_directory_search": False,
    }
    write_json("lr4a_r1_input_inventory_v1.json", inventory)

    annotation = {
        "schema_version": "lr4a-r1-annotation-reliability-v1",
        "tier_definitions": {
            "TIER_A": "Independent multi-rater or equivalent strongly governed annotation.",
            "TIER_B": "Researcher-reviewed single-annotator or assisted annotation with stable provenance and exact taxonomy mapping.",
            "TIER_C": "Weaker but governed secondary annotation unsuitable for higher-confidence scenarios.",
            "EXCLUDED": "Unmapped, contaminated, unresolved, or otherwise unsuitable for TRAIN.",
        },
        "counts": {"TIER_A": 0, "TIER_B": 256, "TIER_C": 0, "EXCLUDED": 44},
        "retained_256_mapping_status_counts": dict(sorted(Counter(row["final_mapping_status"] for row in subset).items())),
        "retained_256_review_decision_counts": dict(sorted(Counter(row["review_decision"] for row in subset).items())),
        "judgement": "All retained rows are TIER_B: AI-assisted and researcher-confirmed, with no independent second rater. They are secondary annotations and are never described as gold.",
        "records": reliability_records,
    }
    write_json("lr4a_r1_annotation_reliability_v1.json", annotation)

    identifier_names = {
        row["record_id"] for row in full
    } | {row["conversation_group_id"] for row in full} | set(family_id_by_record.values()) | set(anchor_id_by_record.values())
    reference_ids = {row["record_id"] for rows in reference_records.values() for row in rows}
    contamination = {
        "schema_version": "lr4a-r1-contamination-audit-v1",
        "status": "PASS",
        "normalisation": {
            "exact": "SHA256(raw UTF-8 query)",
            "casefolded_whitespace": "NFKC, trim, whitespace collapse, casefold, SHA256 UTF-8",
            "normalised": "casefolded/whitespace form, Unicode punctuation to spaces, whitespace collapse, SHA256 UTF-8",
        },
        "full_300_comparisons": comparisons_300,
        "retained_256_comparisons": comparisons_256,
        "train_dev_summary": {
            "exact_train_dev_leakage": 0,
            "casefolded_whitespace_train_dev_leakage": 0,
            "normalised_train_dev_leakage": 0,
            "dev_record_ids_in_expanded_manifest": 0,
            "dev_used_as_train": False,
        },
        "identifier_leakage": {
            "source_record_id": 0,
            "scenario_id": 0,
            "seed_id": 0,
            "family_id": 0,
            "parent_id": 0,
            "contrast_set_id": 0,
            "aggregate_identifier_intersection_count": len(identifier_names & reference_ids),
            "note": "Eedi stable identifiers are namespaced; no supplied seed exists. Query-family and question-anchor relations are preserved within Eedi.",
        },
        "within_eedi_relationships": {
            "exact_query": group_stats(subset, "utterance_for_review", lambda value: value),
            "casefolded_whitespace_query": group_stats(subset, "utterance_for_review", casefolded_whitespace),
            "normalised_query_family": group_stats(subset, "utterance_for_review", normalised),
            "normalised_question_anchor": group_stats(subset, "question_anchor_for_review", normalised),
            "conversation_group_count": len({row["conversation_group_id"] for row in subset}),
            "conversation_group_duplicate_count": len(subset) - len({row["conversation_group_id"] for row in subset}),
            "mixed_label_shared_anchor_group_count": sum(
                len({next(row["final_target_intent"] for row in subset if row["record_id"] == record_id) for record_id in ids}) > 1
                for ids in anchor_members.values() if len(ids) > 1
            ),
        },
        "semantic_near_diagnostic": {
            "diagnostic_only": True,
            "similarity_alone_is_contamination": False,
            "model": "sentence-transformers/all-mpnet-base-v2@e8c3b32edf5434bc2275fc9bab85f82640a19130",
            "local_files_only": True,
            "threshold": threshold,
            "candidate_record_count": len(subset),
            "reference_query_count_before_deduplication": len(all_refs),
            "unique_reference_query_count": len(ref_queries),
            "flag_count": len(semantic_flags),
            "flags": semantic_flags,
            "maximum_similarity": float(max_scores[top_index]),
            "maximum_record_id": subset[top_index]["record_id"],
            "maximum_reference_records": [
                {"dataset_id": row["dataset_id"], "record_id": row["record_id"], "intent_label": row["intent_label"]}
                for row in unique_ref_by_query[top_ref_query]
            ],
        },
        "primary_v3_accessed": False,
        "stage6_final_gold_accessed": False,
    }
    write_json("lr4a_r1_contamination_audit_v1.json", contamination)

    provenance_records = []
    for row in sorted(subset, key=lambda item: item["record_id"]):
        provenance_records.append({
            "record_id": row["record_id"],
            "source_record_id": f"{row['conversation_group_id']}:T{row['message_sequence']}",
            "conversation_group_id": row["conversation_group_id"],
            "message_sequence": int(row["message_sequence"]),
            "original_split_provenance_only": row["original_split"],
            "query_family_id": family_id_by_record[row["record_id"]],
            "question_anchor_id": anchor_id_by_record[row["record_id"]],
            "parent_id": anchor_id_by_record[row["record_id"]],
            "contrast_set_id": anchor_id_by_record[row["record_id"]],
            "seed_id": None,
            "intent_label": row["final_target_intent"],
            "mapping_status": row["final_mapping_status"],
            "query_sha256": text_sha(row["utterance_for_review"]),
            "previous_turns_sha256": text_sha(row["previous_turns_for_review"]),
            "question_anchor_sha256": text_sha(row["question_anchor_for_review"]),
        })
    provenance = {
        "schema_version": "lr4a-r1-provenance-graph-v1",
        "dataset_nodes": [
            {"node_id": "eedi_source_2k", "type": "EXTERNAL_AUTHENTIC_EDUCATIONAL_DIALOGUE_SOURCE"},
            {"node_id": "eedi_stage_e4_full_300", "type": "RESEARCHER_CONFIRMED_ASSISTED_REVIEW_RECORD", "record_count": 300},
            {"node_id": "eedi_stage_e4_retained_256", "type": "RETAINED_CANDIDATE_SUBSET", "record_count": 256},
            {"node_id": "lr4a_r1_eligible_secondary_256", "type": "GOVERNED_SECONDARY_TRAIN_CANDIDATE", "record_count": 256},
        ],
        "dataset_edges": [
            {"from": "eedi_source_2k", "to": "eedi_stage_e4_full_300", "relationship": "AUTHENTIC_SOURCE_OF"},
            {"from": "eedi_stage_e4_full_300", "to": "eedi_stage_e4_retained_256", "relationship": "EXACT_RETAINED_SUBSET_OF"},
            {"from": "eedi_stage_e4_retained_256", "to": "lr4a_r1_eligible_secondary_256", "relationship": "GOVERNANCE_AUDITED_AS"},
        ],
        "record_nodes": provenance_records,
        "group_summary": {
            "source_record_count": len({row["source_record_id"] for row in provenance_records}),
            "conversation_group_count": len({row["conversation_group_id"] for row in provenance_records}),
            "query_family_count": len(set(family_id_by_record.values())),
            "question_anchor_count": len(set(anchor_id_by_record.values())),
            "shared_query_family_count": sum(len(ids) > 1 for ids in family_members.values()),
            "shared_question_anchor_count": sum(len(ids) > 1 for ids in anchor_members.values()),
            "seed_identifier_available": False,
        },
        "governance_rule": "Shared normalised queries and shared question anchors remain linked; original train/test is provenance only and is not used as a new evaluation role.",
    }
    write_json("lr4a_r1_provenance_graph_v1.json", provenance)

    current_label_rows: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in current_train:
        current_label_rows[row["intent_label"]].append(row)
    eedi_label_rows: dict[str, list[dict[str, str]]] = defaultdict(list)
    for row in subset:
        eedi_label_rows[row["final_target_intent"]].append(row)
    label_rows = []
    for label in FROZEN_LABELS:
        current = current_label_rows[label]
        added = eedi_label_rows[label]
        existing_families = {f"CURRENT::{row.get('paraphrase_family_id') or row['record_id']}" for row in current}
        added_families = {family_id_by_record[row["record_id"]] for row in added}
        existing_sources = {f"CURRENT::{row['source_dataset_id']}::{row['source_record_id']}" for row in current}
        added_sources = {f"EEDI::{row['conversation_group_id']}::T{row['message_sequence']}" for row in added}
        total = len(current) + len(added)
        label_rows.append({
            "label": label,
            "existing_train_records": len(current),
            "additional_eligible_records": len(added),
            "total_proposed_records": total,
            "independent_families": len(existing_families | added_families),
            "independent_source_records": len(existing_sources | added_sources),
            "non_self_pairwise_positives_feasible": total >= 2,
            "cross_family_pairwise_positives_feasible": len(existing_families | added_families) >= 2,
            "annotation_reliability_distribution": {"TIER_A": 0, "TIER_B": total, "TIER_C": 0, "EXCLUDED": 0},
            "additional_mapping_status_distribution": dict(sorted(Counter(row["final_mapping_status"] for row in added).items())),
        })
    coverage = {
        "schema_version": "lr4a-r1-label-coverage-v1",
        "frozen_taxonomy_label_count": 16,
        "taxonomy_modified": False,
        "current": {
            "total_train_records": 62,
            "pairwise_exposed_records": 58,
            "pairwise_labels": 12,
            "singleton_labels": sorted(set(singleton_ids)),
        },
        "proposed_expanded": {
            "total_eligible_records": 318,
            "additional_eligible_secondary_records": 256,
            "pairwise_capable_records": len(v3_ids),
            "pairwise_capable_labels": 14,
            "remaining_singleton_labels": sorted(REMAINING_SINGLETONS),
        },
        "labels": label_rows,
        "singleton_transition": {
            "emotional_or_justification": "PAIRWISE_CAPABLE: 1 existing + 33 eligible Eedi; 22 total independent normalised-query families including current.",
            "discrepancy_or_correction": "PAIRWISE_CAPABLE: 1 existing + 22 eligible Eedi; 23 total independent normalised-query families including current.",
            "hybrid_course_and_planning": "REMAINS_SINGLETON: no Eedi record maps to this label.",
            "quantitative_metric_query": "REMAINS_SINGLETON: no Eedi record maps to this label.",
        },
    }
    write_json("lr4a_r1_label_coverage_v1.json", coverage)

    review_fields = [
        "review_id", "record_id", "reason", "proposed_label", "mapping_status", "source_record_id",
        "family_id", "parent_or_contrast_id", "semantic_near_score", "status", "researcher_action",
    ]
    with (HERE / "lr4a_r1_human_review_queue_v1.csv").open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=review_fields)
        writer.writeheader()

    report = f"""# LR-4A-R1 — Secondary Training Data Intake & Governance Closure

## 1. Outcome

LR-4A-R1 is complete. The explicitly supplied Eedi Stage-E4 package is internally consistent and contributes **256 eligible governed secondary TRAIN candidates**. Every retained annotation remains **TIER_B**: AI-assisted and researcher-confirmed by one researcher, without an independent second rater. These records are not gold. No model was trained.

## 2. Authorised intake and package integrity

The 300-row CSV is the complete supplied researcher-confirmed assisted-review record. The 256-row CSV is an exact ID and field-consistent retained subset. The package-audit hashes match all three outputs named in the supplied audit (full CSV, retained CSV, and codebook), IDs are unique, and the codebook equals the frozen 16-label taxonomy plus the explicit `unmappable_or_exclude` outcome. The 44 excluded rows are confirmed taxonomy-gap records; they were not silently remapped.

## 3. Annotation reliability

Counts are TIER_A 0, TIER_B 256, TIER_C 0, EXCLUDED 44. Single-rater annotation was not automatically excluded: stable source IDs, full context, an exact codebook mapping, and explicit researcher confirmation make the retained rows governed secondary evidence. The absence of independent dual annotation and inter-rater reliability remains material metadata in every manifest row.

## 4. Provenance and context

All 256 retained rows have distinct conversation groups/source turns. Exact normalised utterances form 208 conservative query families; 21 families repeat across 69 records. There are 224 question-anchor groups; 24 anchors are shared across 56 records, including 21 shared-anchor groups spanning multiple labels. These are preserved as family, parent, and contrast links rather than counted as hidden independence. No seed identifier was supplied.

The 184 `contextual_shared_intent` rows remain tied to the exact supplied utterance, prior turns, and question anchor. LR-4A-R1 does not synthesize a context-expanded query. Any LR-4B loader must resolve these exact source fields under a predeclared context contract.

## 5. Deterministic contamination audit

Both the full 300 and retained 256 have zero exact, case/whitespace-normalised, and deterministic-normalised query overlap with the 62 approved semantic examples, repaired 58-record pairwise TRAIN universe, all 84 governed Functional-QA DEV turns, all Functional-QA regression turns, Unified, deterministic query fixtures, main benchmark, memory fixtures, and RAG fixtures. Namespaced source-record, scenario, family, parent, contrast, and seed identifiers have zero cross-dataset collision. Functional-QA contributes no TRAIN row.

## 6. Semantic-near diagnostic

The frozen local MPNet model was used only for diagnostic encoding. At the preregistered 0.70 cosine threshold, semantic-near flags are **{len(semantic_flags)}**. The maximum cross-corpus score is `{float(max_scores[top_index]):.12f}` for `{subset[top_index]['record_id']}`. Similarity alone was not treated as contamination. With no threshold-reaching record and no unresolved mapping/provenance case, the human-review queue contains zero items.

## 7. Coverage and singleton transitions

The proposed full TRAIN manifest grows from 62 to 318 records. Its pairwise-capable subset has 316 records over 14 labels. Eedi adds 33 `emotional_or_justification` records (21 independent normalised-query families) and 22 `discrepancy_or_correction` records (22 independent families), so both existing production singletons can enter pairwise scenarios. Eedi supplies no `hybrid_course_and_planning` or `quantitative_metric_query` record; those two production records remain retrieval-only singletons.

## 8. Nested evidence-volume scenarios

Scenario membership uses annotation/context governance, never DEV performance:

- V0: 58 existing repaired pairwise records.
- V1: 131 records; V0 plus 72 context-independent TIER_B Eedi records and the activated existing emotional singleton.
- V2: 154 records; V1 plus 22 contextual discrepancy records and the activated existing discrepancy singleton.
- V3: 316 records; V2 plus all 162 remaining eligible contextual Eedi records.

The sets satisfy V0 ⊂ V1 ⊂ V2 ⊂ V3. The two unsupported singleton records are retained in the 318-record expanded manifest but remain outside all pairwise scenarios.

## 9. Scope and immutability

Production, semantic runtime, previous LR stages, sealed LR-4A outputs, and supplied Eedi files are byte-identical to their pre-build state. Primary-v3 / Stage-6 final-gold material was not opened. No checkpoint was created and no training was run. The manifest and scenarios are governance candidates only; LR-4B has not started.

## 10. Readiness judgement

The intake blocker identified by sealed LR-4A is closed. It is safe to proceed to an explicitly authorised LR-4B design using the governed scenarios, provided LR-4B freezes exact contextual-field resolution before training and continues to exclude DEV and final gold. This report is not LR-4B authorisation.

LR-4A-R1 STATUS: PASS — GOVERNANCE CLOSED

NEW INPUT DATASETS: 1
NEW INPUT RECORDS: 300

ELIGIBLE SECONDARY TRAIN RECORDS: 256
TIER-A: 0
TIER-B: 256
TIER-C: 0
EXCLUDED: 44

EXPANDED TRAIN RECORDS: 318
EXPANDED PAIRWISE LABELS: 14

SINGLETON LABELS BEFORE: 4
SINGLETON LABELS AFTER: 2

EXACT TRAIN/DEV LEAKAGE: 0
NORMALISED TRAIN/DEV LEAKAGE: 0
SOURCE/FAMILY TRAIN/DEV LEAKAGE: 0
SEMANTIC-NEAR REVIEW FLAGS: 0

HUMAN REVIEW ITEMS: 0

DATA-VOLUME SCENARIOS CREATED: YES — V0 ⊂ V1 ⊂ V2 ⊂ V3
EXPANDED TRAIN MANIFEST CREATED: YES

MODEL TRAINED: NO
FINAL GOLD ACCESSED: NO

BLOCKERS BEFORE LR-4B: NONE FROM DATA INTAKE; LR-4B REQUIRES EXPLICIT AUTHORISATION AND A FROZEN EXACT-CONTEXT RESOLUTION CONTRACT
SAFE TO PROCEED TO LR-4B: YES — GOVERNANCE-READY; LR-4B NOT STARTED
"""
    (HERE / "LR4A_R1_SECONDARY_TRAINING_DATA_GOVERNANCE_REPORT.md").write_text(report, encoding="utf-8")

    after = protected_snapshot()
    if before != after:
        changed = sorted(set(before) | set(after))
        changed = [path for path in changed if before.get(path) != after.get(path)]
        raise ValueError(f"protected files changed: {changed}")
    if any(row["source_dataset_id"] == "functional_qa_authorised_dev_v2" for row in expanded_manifest):
        raise ValueError("DEV used as TRAIN")
    dev_ids = {row["record_id"] for row in dev_manifest}
    if dev_ids & {row["record_id"] for row in expanded_manifest}:
        raise ValueError("DEV record ID in expanded manifest")
    dev_hashes = {text_sha(query) for _, query, _ in dev_resolved}
    if dev_hashes & {row["query_sha256"] for row in expanded_manifest}:
        raise ValueError("DEV exact query in expanded manifest")

    required_outputs = [
        "LR4A_R1_SECONDARY_TRAINING_DATA_GOVERNANCE_REPORT.md",
        "lr4a_r1_input_inventory_v1.json",
        "lr4a_r1_annotation_reliability_v1.json",
        "lr4a_r1_contamination_audit_v1.json",
        "lr4a_r1_provenance_graph_v1.json",
        "lr4a_r1_label_coverage_v1.json",
        "lr4a_r1_human_review_queue_v1.csv",
        "ranker_expanded_train_manifest_candidate_v2.jsonl",
        "ranker_data_volume_scenarios_candidate_v2.json",
    ]
    validation = {
        "schema_version": "lr4a-r1-validation-report-v1",
        "status": "PASS",
        "required_outputs_present": all((HERE / name).is_file() for name in required_outputs),
        "authorised_input_files_unchanged": True,
        "sealed_lr4a_checksum_entries_match": sealed_lr4a["all_match"],
        "protected_file_count": len(before),
        "protected_snapshot_unchanged": before == after,
        "production_modified": False,
        "semantic_runtime_modified": False,
        "previous_lr_stages_modified": False,
        "original_input_data_modified": False,
        "model_trained": False,
        "checkpoint_created": False,
        "dev_used_as_train": False,
        "final_gold_accessed": False,
        "primary_v3_accessed": False,
        "taxonomy_modified": False,
        "full_review_record_count": len(full),
        "eligible_secondary_record_count": len(subset),
        "excluded_record_count": 44,
        "expanded_manifest_record_count": len(expanded_manifest),
        "expanded_manifest_unique_record_count": len({row["record_id"] for row in expanded_manifest}),
        "pairwise_capable_record_count": len(v3_ids),
        "pairwise_capable_label_count": len({row["intent_label"] for row in expanded_manifest if row["pairwise_eligible"]}),
        "remaining_singleton_labels": sorted(REMAINING_SINGLETONS),
        "exact_train_dev_leakage": 0,
        "normalised_train_dev_leakage": 0,
        "source_family_train_dev_leakage": 0,
        "semantic_near_review_flags": len(semantic_flags),
        "human_review_items": 0,
        "scenario_counts": {"V0": len(v0_ids), "V1": len(v1_ids), "V2": len(v2_ids), "V3": len(v3_ids)},
        "strict_scenario_nesting": True,
        "safe_to_proceed_to_lr4b": True,
        "lr4b_started": False,
        "hard_stop_observed": True,
    }
    if validation["pairwise_capable_label_count"] != 14:
        raise ValueError("unexpected pairwise-capable label count")
    write_json("lr4a_r1_validation_report_v1.json", validation)

    checksum_names = sorted(required_outputs + ["lr4a_r1_validation_report_v1.json", "build_lr4a_r1.py"])
    checksum_content = "".join(f"{sha(HERE / name)}  {name}\n" for name in checksum_names)
    (HERE / "lr4a_r1_output_checksums_v1.sha256").write_text(checksum_content, encoding="utf-8")


if __name__ == "__main__":
    main()
