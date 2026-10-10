"""Build the deterministic, research-only LR-2 governed pair dataset."""

from __future__ import annotations

import argparse
import hashlib
import itertools
import json
from collections import Counter, defaultdict
from pathlib import Path

from pair_schema import CONSTRUCTION_VERSION, SCHEMA_VERSION, deterministic_pair_id, validate_pair
from validate_pair_dataset import read_jsonl, sha256_file, validate_pairs, verify_checksum_manifest


HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]
LR1 = ROOT / "evaluation/learned_intent_ranking/lr1"
LR1R = ROOT / "evaluation/learned_intent_ranking/lr1r"
SEED = 20260813
BASELINE_MAX_POSITIVES_PER_ANCHOR = 2

GENERATED_FILES = [
    "LR2_PAIR_CONSTRUCTION_REPORT.md",
    "lr2_researcher_authorisations_v1.json",
    "lr2_label_universe_v1.json",
    "lr2_positive_pair_feasibility_v1.json",
    "ranker_positive_pair_candidates_v1.jsonl",
    "ranker_safe_negative_pair_candidates_v1.jsonl",
    "ranker_hard_negative_candidates_v1.jsonl",
    "ranker_blocked_relationship_statistics_v1.json",
    "ranker_pair_sampling_analysis_v1.json",
    "ranker_pair_dataset_baseline_candidate_v1.jsonl",
    "ranker_dev_reference_manifest_v1.json",
    "lr2_pair_validation_report_v1.json",
    "lr2_output_checksums_v1.sha256",
]


def dump_json(path: Path, value) -> None:
    path.write_text(json.dumps(value, indent=2, sort_keys=True, ensure_ascii=False) + "\n", encoding="utf-8")


def dump_jsonl(path: Path, rows: list[dict]) -> None:
    path.write_text(
        "".join(json.dumps(row, sort_keys=True, ensure_ascii=False, separators=(",", ":")) + "\n" for row in rows),
        encoding="utf-8",
    )


def file_inventory(paths: list[Path]) -> dict[str, str]:
    return {
        str(path.relative_to(ROOT)): sha256_file(path)
        for path in sorted(paths)
        if path.is_file()
    }


def stable_rank(kind: str, anchor_id: str, candidate_id: str) -> str:
    value = f"{SEED}|{kind}|{anchor_id}|{candidate_id}".encode("utf-8")
    return hashlib.sha256(value).hexdigest()


def relationship_key(a: str, b: str) -> tuple[str, str]:
    return tuple(sorted((a, b)))


def provenance_equivalence_reasons(anchor: dict, candidate: dict) -> list[str]:
    reasons = []
    if anchor["query_sha256"] == candidate["query_sha256"]:
        reasons.append("same_exact_query_hash")
    if anchor["normalised_query_sha256"] == candidate["normalised_query_sha256"]:
        reasons.append("same_normalised_query_hash")
    if (
        anchor.get("paraphrase_family_id")
        and anchor["paraphrase_family_id"] == candidate.get("paraphrase_family_id")
    ):
        reasons.append("same_explicit_paraphrase_family")
    if (
        anchor["provenance"].get("source_path"), anchor["source_record_id"]
    ) == (
        candidate["provenance"].get("source_path"), candidate["source_record_id"]
    ):
        reasons.append("same_source_derivation")
    if anchor.get("scenario_id") and anchor["scenario_id"] == candidate.get("scenario_id"):
        reasons.append("same_scenario")
    anchor_seed = anchor.get("seed_query_id") or anchor["provenance"].get("seed_id")
    candidate_seed = candidate.get("seed_query_id") or candidate["provenance"].get("seed_id")
    if anchor_seed and anchor_seed == candidate_seed:
        reasons.append("same_explicit_seed")
    return reasons


def make_pair(anchor: dict, candidate: dict, pair_type: str, relationship_class: str, status: str, reason: str) -> dict:
    same_family = bool(
        anchor.get("paraphrase_family_id")
        and candidate.get("paraphrase_family_id")
        and anchor["paraphrase_family_id"] == candidate["paraphrase_family_id"]
    )
    target = 1 if anchor["intent_label"] == candidate["intent_label"] else 0
    pair = {
        "schema_version": SCHEMA_VERSION,
        "pair_id": "PENDING",
        "anchor_record_id": anchor["record_id"],
        "candidate_record_id": candidate["record_id"],
        "anchor_intent": anchor["intent_label"],
        "candidate_intent": candidate["intent_label"],
        "target": target,
        "candidate_target": target,
        "pair_type": pair_type,
        "anchor_family_id": anchor.get("paraphrase_family_id"),
        "candidate_family_id": candidate.get("paraphrase_family_id"),
        "relationship_class": relationship_class,
        "same_intent": target == 1,
        "same_family": same_family,
        "anchor_query_sha256": anchor["query_sha256"],
        "candidate_query_sha256": candidate["query_sha256"],
        "source_dataset_ids": [anchor["source_dataset_id"], candidate["source_dataset_id"]],
        "source_record_ids": [anchor["source_record_id"], candidate["source_record_id"]],
        "source_paths": [anchor["provenance"].get("source_path"), candidate["provenance"].get("source_path")],
        "scenario_ids": [anchor.get("scenario_id"), candidate.get("scenario_id")],
        "governance_status": status,
        "construction_version": CONSTRUCTION_VERSION,
        "pair_policy_reason": reason,
    }
    pair["pair_id"] = deterministic_pair_id(pair)
    validate_pair(pair)
    return pair


def build(check_only: bool = False) -> None:
    prior = {
        name: (HERE / name).read_bytes()
        for name in GENERATED_FILES
        if (HERE / name).is_file()
    } if check_only else {}

    production = [ROOT / path for path in [
        "utils/c_full_service.py", "utils/production_intent_router.py", "utils/semantic_intent_router.py",
        "utils/intent_schema.py", "utils/intent_example_index.py", "utils/evidence_synthesiser.py",
        "utils/conversation_memory.py", "utils/recommendation_planner.py",
    ]]
    protected_groups = {
        "production": production,
        "semantic_runtime": list((ROOT / "semantic_runtime").rglob("*")),
        "lr1": list(LR1.rglob("*")),
        "lr1r": list(LR1R.rglob("*")),
        "original_data": [ROOT / path for path in [
            "evaluation/functional_qa/functional_qa_cases_v1.jsonl",
            "evaluation/unified_benchmark_scenarios.jsonl",
            "evaluation/unified_benchmark_gold_labels.jsonl",
            "semantic_runtime/artifacts/intent_examples_approved_index_v1.jsonl",
        ]],
    }
    before = {name: file_inventory(paths) for name, paths in protected_groups.items()}

    lr1_checks = verify_checksum_manifest(LR1 / "LR1_OUTPUT_HASHES.sha256", LR1)
    lr1r_checks = verify_checksum_manifest(LR1R / "lr1r_output_checksums_v1.sha256", LR1R)

    train_path = LR1 / "ranker_train_manifest_candidate_v1.jsonl"
    dev_path = LR1R / "ranker_dev_manifest_candidate_v2.jsonl"
    universe_path = LR1R / "ranker_label_universe_candidate_v1.json"
    policy_path = LR1R / "ranker_negative_pair_policy_candidate_v1.json"
    review_path = LR1R / "ranker_review_adjudications_v1.json"
    semantic_path = LR1R / "ranker_semantic_near_adjudications_v1.json"
    authoritative_inputs = [train_path, dev_path, universe_path, policy_path, review_path, semantic_path,
                            LR1R / "lr1r_output_checksums_v1.sha256"]
    input_hashes = {str(path.relative_to(ROOT)): sha256_file(path) for path in authoritative_inputs}

    train = read_jsonl(train_path)
    dev = read_jsonl(dev_path)
    universe_source = json.loads(universe_path.read_text(encoding="utf-8"))
    policy_source = json.loads(policy_path.read_text(encoding="utf-8"))
    assert len(train) == 62 and len(dev) == 84
    labels = universe_source["included_labels"]
    label_set = set(labels)
    assert len(labels) == 16 and universe_source["excluded_labels"] == ["ambiguous", "memory_state_query"]
    assert {row["intent_label"] for row in train} == label_set
    assert {row["intent_label"] for row in dev} <= label_set
    assert policy_source["status"] == "CANDIDATE_REQUIRES_RESEARCHER_APPROVAL_BEFORE_LR2"
    assert policy_source["relationship_count"] == 120

    authorisations = {
        "schema_version": "lr2-researcher-authorisations-v1",
        "status": "FROZEN_FOR_LR2",
        "decisions": [
            {
                "review_id": "LR1R-HR-001", "decision": "APPROVE_AS_DEVELOPMENT_ONLY",
                "scope": "84-record revised Functional-QA DEV candidate",
                "constraints": ["DEVELOPMENT_OR_MODEL_SELECTION_ONLY", "NOT_FINAL_GOLD", "NO_UNTOUCHED_GENERALISATION_CLAIM"],
            },
            {
                "review_id": "LR1R-HR-002", "decision": "APPROVE_POLICY",
                "scope": "LR-1R negative-label relationship policy",
                "baseline_rules": {
                    "SAFE_RANDOM_NEGATIVE": "ELIGIBLE_FOR_AUTOMATIC_NEGATIVE_GENERATION",
                    "HARD_NEGATIVE_CANDIDATE": "SEPARATE_AUDITABLE_POOL_ONLY",
                    "BLOCKED_WITHOUT_REVIEW": "PROHIBITED_FROM_QUERY_LEVEL_GENERATION",
                },
            },
            {
                "review_id": "LR1R-HR-003", "decision": "DEFER_FINAL_GOLD",
                "scope": "Primary-v3 / Stage-6",
                "constraints": ["DEVELOPMENT_WORK_ONLY", "NO_FINAL_EVALUATION", "NO_SUBSTITUTE_FINAL_GOLD", "NO_FINAL_GENERALISATION_CLAIM"],
            },
        ],
        "final_gold_status": "DEFERRED_NOT_AVAILABLE",
        "source_thread_instruction": "LR-2 researcher authorisations supplied with the LR-2 brief",
    }
    dump_json(HERE / "lr2_researcher_authorisations_v1.json", authorisations)

    frozen_universe = {
        "schema_version": "lr2-label-universe-v1",
        "status": "FROZEN_FOR_LR2_BY_REFERENCE",
        "source_path": str(universe_path.relative_to(ROOT)),
        "source_sha256": sha256_file(universe_path),
        "included_labels": labels,
        "excluded_labels": universe_source["excluded_labels"],
        "train_record_count": len(train),
        "production_taxonomy_modified": False,
    }
    dump_json(HERE / "lr2_label_universe_v1.json", frozen_universe)

    by_label = defaultdict(list)
    for row in train:
        by_label[row["intent_label"]].append(row)
    feasibility_rows = []
    for label in labels:
        rows = by_label[label]
        family_counts = Counter(row.get("paraphrase_family_id") for row in rows)
        all_directed = len(rows) * (len(rows) - 1)
        same_family = sum(count * (count - 1) for family, count in family_counts.items() if family)
        cross_family = all_directed - same_family
        feasibility_rows.append({
            "label": label,
            "example_count": len(rows),
            "family_count": len({row.get("paraphrase_family_id") for row in rows if row.get("paraphrase_family_id")}),
            "source_count": len({(row["provenance"].get("source_path"), row["source_record_id"]) for row in rows}),
            "number_of_possible_nonself_same_label_pairs": all_directed,
            "number_of_possible_cross_family_positive_pairs": cross_family,
            "number_of_possible_same_family_positive_pairs": same_family,
            "ordinary_example_to_example_positive_supported": len(rows) >= 2,
        })
    singleton_labels = [row["label"] for row in feasibility_rows if row["example_count"] == 1]
    no_positive_labels = [row["label"] for row in feasibility_rows if row["number_of_possible_nonself_same_label_pairs"] == 0]
    feasibility = {
        "schema_version": "lr2-positive-pair-feasibility-v1",
        "pair_directionality": "DIRECTED",
        "self_pairing_allowed": False,
        "labels_total": 16,
        "labels_supporting_nonself_positive_pairs": 16 - len(no_positive_labels),
        "labels_without_nonself_positive_pairs": no_positive_labels,
        "singleton_labels": singleton_labels,
        "remediation_prohibited": ["SELF_PAIRING", "DUPLICATION", "SYNTHETIC_PARAPHRASES", "LLM_GENERATION"],
        "per_label": feasibility_rows,
        "totals": {
            "examples": len(train),
            "possible_nonself_same_label_pairs": sum(row["number_of_possible_nonself_same_label_pairs"] for row in feasibility_rows),
            "possible_cross_family_positive_pairs": sum(row["number_of_possible_cross_family_positive_pairs"] for row in feasibility_rows),
            "possible_same_family_positive_pairs": sum(row["number_of_possible_same_family_positive_pairs"] for row in feasibility_rows),
        },
    }
    dump_json(HERE / "lr2_positive_pair_feasibility_v1.json", feasibility)

    positive_pairs = []
    for anchor in train:
        for candidate in train:
            if anchor["record_id"] == candidate["record_id"] or anchor["intent_label"] != candidate["intent_label"]:
                continue
            same_family = anchor.get("paraphrase_family_id") == candidate.get("paraphrase_family_id")
            pair_type = "SAME_FAMILY_POSITIVE" if same_family else "CROSS_FAMILY_POSITIVE"
            positive_pairs.append(make_pair(
                anchor, candidate, pair_type, "SAME_INTENT_POSITIVE", "GOVERNED_POSITIVE_CANDIDATE",
                "Different governed TRAIN examples share the same intent; self-pairs are prohibited.",
            ))
    positive_pairs.sort(key=lambda row: row["pair_id"])
    dump_jsonl(HERE / "ranker_positive_pair_candidates_v1.jsonl", positive_pairs)

    policy = {
        relationship_key(row["label_a"], row["label_b"]): row
        for row in policy_source["relationships"]
    }
    safe_pairs, hard_pairs, pair_review_required = [], [], []
    for anchor in train:
        for candidate in train:
            if anchor["record_id"] == candidate["record_id"] or anchor["intent_label"] == candidate["intent_label"]:
                continue
            rule = policy[relationship_key(anchor["intent_label"], candidate["intent_label"])]
            cls = rule["relationship_class"]
            if cls == "BLOCKED_WITHOUT_REVIEW":
                continue
            equivalence = provenance_equivalence_reasons(anchor, candidate)
            if equivalence:
                pair_review_required.append({
                    "anchor_record_id": anchor["record_id"], "candidate_record_id": candidate["record_id"],
                    "relationship_class": cls, "reasons": equivalence,
                })
                continue
            if cls == "SAFE_RANDOM_NEGATIVE":
                safe_pairs.append(make_pair(
                    anchor, candidate, cls, cls, "GOVERNED_SAFE_NEGATIVE_CANDIDATE",
                    "Approved SAFE_RANDOM_NEGATIVE label relationship and no explicit record-level equivalence provenance.",
                ))
            elif cls == "HARD_NEGATIVE_CANDIDATE":
                hard_pairs.append(make_pair(
                    anchor, candidate, cls, cls, "NOT_AUTHORISED_FOR_BASELINE_TRAINING",
                    "Approved policy marks this as a separately auditable hard-negative candidate; excluded from baseline.",
                ))
            else:
                raise AssertionError(f"unexpected relationship class: {cls}")
    safe_pairs.sort(key=lambda row: row["pair_id"])
    hard_pairs.sort(key=lambda row: row["pair_id"])
    dump_jsonl(HERE / "ranker_safe_negative_pair_candidates_v1.jsonl", safe_pairs)
    dump_jsonl(HERE / "ranker_hard_negative_candidates_v1.jsonl", hard_pairs)

    blocked_stats = []
    for rule in policy_source["relationships"]:
        if rule["relationship_class"] != "BLOCKED_WITHOUT_REVIEW":
            continue
        a, b = rule["label_a"], rule["label_b"]
        count_a, count_b = len(by_label[a]), len(by_label[b])
        blocked_stats.append({
            "label_a": a, "label_b": b,
            "possible_anchor_count": count_a + count_b,
            "possible_candidate_count": count_a + count_b,
            "direction_a_to_b_pair_count": count_a * count_b,
            "direction_b_to_a_pair_count": count_b * count_a,
            "possible_pair_count": 2 * count_a * count_b,
            "reason_blocked": rule["reason"],
            "query_level_pairs_generated": 0,
        })
    blocked_stats.sort(key=lambda row: (row["label_a"], row["label_b"]))
    dump_json(HERE / "ranker_blocked_relationship_statistics_v1.json", {
        "schema_version": "lr2-blocked-relationship-statistics-v1",
        "status": "AGGREGATE_STATISTICS_ONLY",
        "relationship_count": len(blocked_stats),
        "query_level_pair_count": 0,
        "total_possible_directed_pair_count": sum(row["possible_pair_count"] for row in blocked_stats),
        "relationships": blocked_stats,
    })

    positives_by_anchor = defaultdict(list)
    negatives_by_anchor = defaultdict(list)
    for row in positive_pairs:
        positives_by_anchor[row["anchor_record_id"]].append(row)
    for row in safe_pairs:
        negatives_by_anchor[row["anchor_record_id"]].append(row)
    baseline = []
    baseline_anchor_stats = []
    for anchor in train:
        aid = anchor["record_id"]
        ordered_pos = sorted(
            positives_by_anchor[aid],
            key=lambda row: (
                0 if row["pair_type"] == "CROSS_FAMILY_POSITIVE" else 1,
                stable_rank("positive", aid, row["candidate_record_id"]),
            ),
        )
        selected_pos = ordered_pos[:BASELINE_MAX_POSITIVES_PER_ANCHOR]
        selected_neg = sorted(
            negatives_by_anchor[aid],
            key=lambda row: stable_rank("safe_negative", aid, row["candidate_record_id"]),
        )[:len(selected_pos)]
        if len(selected_neg) != len(selected_pos):
            raise ValueError(f"insufficient SAFE_RANDOM_NEGATIVE support for {aid}")
        selected = selected_pos + selected_neg
        for row in selected:
            copied = dict(row)
            copied["governance_status"] = "CANDIDATE_FOR_LR3_TRAINING"
            validate_pair(copied, baseline=True)
            baseline.append(copied)
        baseline_anchor_stats.append({
            "anchor_record_id": aid, "anchor_intent": anchor["intent_label"],
            "available_positive_count": len(ordered_pos), "selected_positive_count": len(selected_pos),
            "available_safe_negative_count": len(negatives_by_anchor[aid]), "selected_safe_negative_count": len(selected_neg),
        })
    baseline.sort(key=lambda row: row["pair_id"])
    dump_jsonl(HERE / "ranker_pair_dataset_baseline_candidate_v1.jsonl", baseline)

    capable_labels = [row["label"] for row in feasibility_rows if row["ordinary_example_to_example_positive_supported"]]
    strict_intent_cap = min(
        row["number_of_possible_nonself_same_label_pairs"]
        for row in feasibility_rows if row["ordinary_example_to_example_positive_supported"]
    )
    sampling = {
        "schema_version": "lr2-pair-sampling-analysis-v1",
        "fixed_seed": SEED,
        "selection_hash": "sha256(seed|stratum|anchor_record_id|candidate_record_id)",
        "strategies": [
            {
                "strategy": "A_ALL_ELIGIBLE_PAIRS", "positive_count": len(positive_pairs),
                "negative_count": len(safe_pairs), "total_count": len(positive_pairs) + len(safe_pairs),
                "reproduction": "Use all records from positive and safe-negative candidate artifacts.",
                "assessment": "Complete but strongly dominated by high-support labels; not recommended as baseline.",
            },
            {
                "strategy": "B_PER_ANCHOR_BALANCED", "positive_count": sum(row["selected_positive_count"] for row in baseline_anchor_stats),
                "negative_count": sum(row["selected_safe_negative_count"] for row in baseline_anchor_stats),
                "total_count": len(baseline), "recommended_for_lr3": True,
                "parameters": {"max_positive_candidates_per_anchor": BASELINE_MAX_POSITIVES_PER_ANCHOR,
                               "safe_negatives_per_anchor": "equal_to_selected_positive_count",
                               "positive_priority": ["CROSS_FAMILY_POSITIVE", "SAME_FAMILY_POSITIVE"],
                               "singleton_anchor_behavior": "zero baseline pairs; never self-pair"},
                "assessment": "Uses every positive-capable anchor, caps class-support influence, and keeps targets exactly balanced per anchor.",
            },
            {
                "strategy": "C_PER_INTENT_STRICT_BALANCED", "positive_count": strict_intent_cap * len(capable_labels),
                "negative_count": strict_intent_cap * len(capable_labels),
                "total_count": 2 * strict_intent_cap * len(capable_labels),
                "parameters": {"positive_pairs_per_positive_capable_intent": strict_intent_cap,
                               "negative_pairs_per_positive_capable_intent": strict_intent_cap,
                               "selection_order": "same fixed-seed hash order"},
                "assessment": "Strictly equal intent contribution but discards most evidence because the smallest supported intent has only two directed positives.",
            },
        ],
        "observed_feasibility": {
            "positive_candidates_per_anchor_min_for_capable_anchors": min(len(positives_by_anchor[row["record_id"]]) for row in train if positives_by_anchor[row["record_id"]]),
            "positive_candidates_per_anchor_max": max(len(positives_by_anchor[row["record_id"]]) for row in train),
            "safe_negative_candidates_per_anchor_min": min(len(negatives_by_anchor[row["record_id"]]) for row in train),
            "safe_negative_candidates_per_anchor_max": max(len(negatives_by_anchor[row["record_id"]]) for row in train),
            "singleton_anchor_count": len(singleton_labels),
        },
        "baseline_anchor_selection": baseline_anchor_stats,
    }
    dump_json(HERE / "ranker_pair_sampling_analysis_v1.json", sampling)

    dev_counts = Counter(row["intent_label"] for row in dev)
    dev_labels = sorted(dev_counts)
    absent_dev_labels = sorted(label_set - set(dev_labels))
    dump_json(HERE / "ranker_dev_reference_manifest_v1.json", {
        "schema_version": "lr2-dev-reference-manifest-v1",
        "status": "FROZEN_DEVELOPMENT_ONLY_REFERENCE",
        "source_path": str(dev_path.relative_to(ROOT)),
        "source_sha256": sha256_file(dev_path),
        "record_count": len(dev),
        "dev_covered_labels": dev_labels,
        "train_labels_absent_from_dev": absent_dev_labels,
        "per_label_support": dict(sorted(dev_counts.items())),
        "metric_scope_requirement": "DEV_SUPPORTED_LABEL_EVALUATION_9_OF_16",
        "prohibitions": ["NO_TRAINING_PAIRS", "NO_NEGATIVE_CANDIDATES", "NO_HARD_NEGATIVE_MINING", "NOT_FINAL_GOLD"],
        "records": [{
            "record_id": row["record_id"], "intent_label": row["intent_label"], "query_sha256": row["query_sha256"],
            "source_dataset_id": row["source_dataset_id"], "source_record_id": row["source_record_id"],
            "governance_status": row["governance_status"], "functional_qa_role": row["functional_qa_role"],
        } for row in dev],
    })

    train_ids = {row["record_id"] for row in train}
    dev_ids = {row["record_id"] for row in dev}
    positive_validation = validate_pairs(positive_pairs, train_ids=train_ids, dev_ids=dev_ids, label_universe=label_set)
    safe_validation = validate_pairs(safe_pairs, train_ids=train_ids, dev_ids=dev_ids, label_universe=label_set)
    hard_validation = validate_pairs(hard_pairs, train_ids=train_ids, dev_ids=dev_ids, label_universe=label_set)
    baseline_validation = validate_pairs(baseline, train_ids=train_ids, dev_ids=dev_ids, label_universe=label_set, baseline=True)
    assert all(v["failure_count"] == 0 for v in [positive_validation, safe_validation, hard_validation, baseline_validation])
    baseline_hard_ids = {row["pair_id"] for row in baseline} & {row["pair_id"] for row in hard_pairs}
    blocked_keys = {relationship_key(row["label_a"], row["label_b"]) for row in blocked_stats}
    baseline_blocked = [row["pair_id"] for row in baseline if row["target"] == 0 and relationship_key(row["anchor_intent"], row["candidate_intent"]) in blocked_keys]
    assert not baseline_hard_ids and not baseline_blocked and not pair_review_required

    validation_report = {
        "schema_version": "lr2-pair-validation-report-v1",
        "overall_status": "PASS",
        "input_checksum_verification": {"lr1": lr1_checks, "lr1r": lr1r_checks},
        "authoritative_input_hashes": input_hashes,
        "validations": {
            "positive_candidates": positive_validation, "safe_negative_candidates": safe_validation,
            "hard_negative_candidates": hard_validation, "baseline_candidate": baseline_validation,
        },
        "cross_artifact_checks": {
            "hard_negative_pair_ids_in_baseline": len(baseline_hard_ids),
            "blocked_relationship_pairs_in_baseline": len(baseline_blocked),
            "policy_violating_negatives_in_baseline": sum(row["target"] == 0 and row["relationship_class"] != "SAFE_RANDOM_NEGATIVE" for row in baseline),
            "dev_records_in_train_pairs": baseline_validation["dev_record_reference_count"],
            "pair_review_required_count": len(pair_review_required),
            "all_train_pair_ids_resolve": all(row["anchor_record_id"] in train_ids and row["candidate_record_id"] in train_ids for row in positive_pairs + safe_pairs + hard_pairs + baseline),
            "all_labels_in_universe": all(row["anchor_intent"] in label_set and row["candidate_intent"] in label_set for row in positive_pairs + safe_pairs + hard_pairs + baseline),
            "blocked_query_level_pairs_generated": 0,
            "dev_training_pair_count": 0,
        },
        "determinism_contract": {"fixed_seed": SEED, "pair_id_algorithm": "SHA-256 over canonical identity fields; 24 uppercase hex characters", "serialization": "sorted-key compact JSONL with LF", "rerun_check_supported": "python3 build_pair_dataset.py --check"},
        "protected_snapshot_before": before,
    }
    dump_json(HERE / "lr2_pair_validation_report_v1.json", validation_report)

    intent_counts = Counter(row["intent_label"] for row in train)
    positive_type_counts = Counter(row["pair_type"] for row in positive_pairs)
    baseline_counts = Counter(row["target"] for row in baseline)
    blocked_possible = sum(row["possible_pair_count"] for row in blocked_stats)
    input_table = "\n".join(f"| `{path}` | `{digest}` |" for path, digest in sorted(input_hashes.items()))
    feasibility_table = "\n".join(
        f"| `{row['label']}` | {row['example_count']} | {row['family_count']} | {row['source_count']} | {row['number_of_possible_nonself_same_label_pairs']} | {row['number_of_possible_cross_family_positive_pairs']} | {row['number_of_possible_same_family_positive_pairs']} |"
        for row in feasibility_rows
    )
    dev_table = "\n".join(f"| `{label}` | {dev_counts[label]} |" for label in dev_labels)
    protected_table = "\n".join(f"| {name} | {len(files)} | UNCHANGED |" for name, files in before.items())
    report = f'''# LR-2 — Governed Learned-Intent Pair Dataset Construction

## 1. Status

LR-2 constructed a deterministic, reference-and-hash-based candidate pair layer without model training or production change. The exhaustive pools contain {len(positive_pairs)} directed positive candidates, {len(safe_pairs)} directed safe-negative candidates, and {len(hard_pairs)} separately governed hard-negative candidates. The conservative baseline contains {len(baseline)} records and is labelled `CANDIDATE_FOR_LR3_TRAINING`, not training-authorised.

## 2. Researcher authorisations

- `LR1R-HR-001 = APPROVE_AS_DEVELOPMENT_ONLY`: the 84 Functional-QA records are DEV/model-selection only.
- `LR1R-HR-002 = APPROVE_POLICY`: only `SAFE_RANDOM_NEGATIVE` relationships enter automatic baseline negatives; hard candidates remain separate; blocked relationships have aggregate statistics only.
- `LR1R-HR-003 = DEFER_FINAL_GOLD`: development work may continue, but final evaluation and final-generalisation claims are unauthorised.

The frozen record is `lr2_researcher_authorisations_v1.json`.

## 3. Input hashes

All seven LR-1 checksum entries and all nine LR-1R checksum entries matched before construction. No dataset substitution occurred.

| Authoritative input | SHA-256 |
|---|---|
{input_table}

## 4. TRAIN structure

TRAIN contains 62 governed record references across 16 labels and 43 explicit families. Label support ranges from 1 to 9 examples. Pair records copy stable IDs, provenance fields, and query hashes—not query text.

## 5. Positive-pair feasibility

Counts are directed and exclude self-pairs.

| Label | Examples | Families | Sources | Nonself positives | Cross-family | Same-family |
|---|---:|---:|---:|---:|---:|---:|
{feasibility_table}

Exactly {16 - len(no_positive_labels)} of 16 labels can support ordinary example-to-example positives; {len(no_positive_labels)} cannot.

## 6. Singleton / low-support labels

Singleton/no-nonself-positive labels are: {', '.join(f'`{label}`' for label in singleton_labels)}. They were not duplicated, synthesised, LLM-augmented, or self-paired. `reflection_structure_question` has two examples and therefore only two directed positives. `cross_page_relationship` has four examples but one family, so all 12 of its positives are same-family.

## 7. Positive-pair construction

The positive candidate artifact has {len(positive_pairs)} directed nonself pairs: {positive_type_counts['CROSS_FAMILY_POSITIVE']} `CROSS_FAMILY_POSITIVE` and {positive_type_counts['SAME_FAMILY_POSITIVE']} `SAME_FAMILY_POSITIVE`. Full source IDs, family IDs, record IDs, query hashes, policy reasons, and deterministic pair IDs are retained. Same-family positives remain auditable rather than deleted.

## 8. Safe-negative construction

The safe-negative candidate artifact has {len(safe_pairs)} directed pairs. Every pair uses a policy-approved `SAFE_RANDOM_NEGATIVE` relationship, different labels and records, and passes exact/normalised-query, explicit-family, source-record, scenario, and explicit-seed equivalence safeguards. `PAIR_REVIEW_REQUIRED` exclusions: {len(pair_review_required)}.

## 9. Hard-negative candidate pool

The separate pool contains {len(hard_pairs)} directed records across seven approved hard relationship classes. Every record is `NOT_AUTHORISED_FOR_BASELINE_TRAINING`; none appears in the baseline.

## 10. Blocked negative boundaries

Thirteen blocked relationships represent {blocked_possible} possible directed query pairs. No query-level blocked pair was generated. `ranker_blocked_relationship_statistics_v1.json` records only label counts, directional availability, possible-pair counts, and policy reasons.

## 11. Pair balancing analysis

Three reproducible strategies were compared:

- A, all eligible: {len(positive_pairs)} positives + {len(safe_pairs)} safe negatives = {len(positive_pairs) + len(safe_pairs)}; complete but dominated by high-support labels.
- B, per-anchor balanced: {baseline_counts[1]} positives + {baseline_counts[0]} safe negatives = {len(baseline)}; recommended.
- C, strict per-intent: {strict_intent_cap * len(capable_labels)} positives + the same number of negatives = {2 * strict_intent_cap * len(capable_labels)}; balanced but discards most evidence because the smallest capable class supplies only {strict_intent_cap} directed positives.

All sampling metadata, per-anchor availability/selection, fixed seed `{SEED}`, and hash-order rule are frozen in `ranker_pair_sampling_analysis_v1.json`.

## 12. Recommended LR-3 baseline sampling

For each positive-capable anchor, select up to 2 positives, prioritising cross-family before same-family, then select exactly the same number of safe negatives. Ties use SHA-256 order over seed, stratum, anchor ID, and candidate ID. This yields a target-balanced {len(baseline)}-record baseline using all 58 non-singleton anchors. Singleton anchors contribute no baseline rows rather than trivial positives or negative-only supervision. LR-3 must still be separately authorised.

## 13. DEV coverage limitation

DEV contains 84 records but covers only 9 of the 16 TRAIN labels.

| DEV-covered label | Support |
|---|---:|
{dev_table}

TRAIN labels absent from DEV: {', '.join(f'`{label}`' for label in absent_dev_labels)}. Future Accuracy, Macro-F1, MRR, and Recall@K on this data must be labelled `DEV-supported-label evaluation`; they cannot establish 16-label full-universe validation. No DEV record or text was used for pair construction or mining.

## 14. Final-gold status

`FINAL_GOLD_STATUS = DEFERRED_NOT_AVAILABLE`. LR-2 did not search outside the project, construct a substitute, or use Unified/Functional-QA as final gold.

## 15. Pair-validation results

All candidate and baseline artifacts pass schema and cross-artifact validation. Self-pairs: 0. Baseline policy-violating negatives: 0. Hard pairs in baseline: 0. Blocked relationships in baseline: 0. DEV records in TRAIN pairs: 0. Unresolved pair-provenance review flags: 0. All record IDs resolve to governed TRAIN, all labels belong to the frozen universe, and deterministic IDs recalculate exactly. The research-only test suite also verifies byte-identical reconstruction.

## 16. Remaining human review

No query-level pair requires human review under the supplied provenance. The candidate artifacts and recommended baseline still require researcher inspection before LR-3 authorisation.

## 17. Remaining blockers

Before LR-3: inspect LR-2 artifacts, accept or amend the baseline sampling design, and explicitly authorise model training. Final-gold remains deferred and unavailable but is not replaced by DEV.

## 18. Recommendation for LR-3

Do not begin LR-3 automatically. The {len(baseline)}-record per-anchor-balanced artifact is the recommended initial candidate after explicit authorisation. LR-3 must preserve the 16-label universe, report singleton limitations, and restrict any DEV metrics to the 9 supported labels.

## 19. Files created

- `build_pair_dataset.py`, `pair_schema.py`, `validate_pair_dataset.py`, `test_pair_dataset.py`
- `LR2_PAIR_CONSTRUCTION_REPORT.md`
- `lr2_researcher_authorisations_v1.json`
- `lr2_label_universe_v1.json`
- `lr2_positive_pair_feasibility_v1.json`
- `ranker_positive_pair_candidates_v1.jsonl`
- `ranker_safe_negative_pair_candidates_v1.jsonl`
- `ranker_hard_negative_candidates_v1.jsonl`
- `ranker_blocked_relationship_statistics_v1.json`
- `ranker_pair_sampling_analysis_v1.json`
- `ranker_pair_dataset_baseline_candidate_v1.jsonl`
- `ranker_dev_reference_manifest_v1.json`
- `lr2_pair_validation_report_v1.json`
- `lr2_output_checksums_v1.sha256`

The checksum manifest hashes all other LR-2 files and excludes itself to avoid self-reference.

## 20. Files verified unchanged

Protected files were hashed before and after construction.

| Protected group | File count | Result |
|---|---:|---|
{protected_table}

LR-2 STATUS:

PRODUCTION CODE MODIFIED: NO
SEMANTIC RUNTIME MODIFIED: NO
ORIGINAL DATA MODIFIED: NO
LR-1/LR-1R MODIFIED: NO

MODEL TRAINED: NO
CHECKPOINT CREATED: NO

RESEARCHER DEV AUTHORISATION: APPROVE_AS_DEVELOPMENT_ONLY
RESEARCHER NEGATIVE-POLICY AUTHORISATION: APPROVE_POLICY
FINAL-GOLD DECISION: DEFER_FINAL_GOLD

TRAIN RECORDS: 62
TRAIN LABELS: 16
DEV RECORDS: 84
DEV-COVERED LABELS: 9
TRAIN LABELS ABSENT FROM DEV: 7

POSITIVE PAIR CANDIDATES: {len(positive_pairs)}
SAFE NEGATIVE PAIR CANDIDATES: {len(safe_pairs)}
HARD NEGATIVE CANDIDATES: {len(hard_pairs)}
BLOCKED RELATIONSHIPS: {len(blocked_stats)}

BASELINE PAIR DATASET RECORDS: {len(baseline)}
SELF PAIRS: 0
POLICY-VIOLATING NEGATIVES: 0
DEV RECORDS IN TRAIN PAIRS: 0

SINGLETON / NO-NONSELF-POSITIVE LABELS: {', '.join(singleton_labels)}

FINAL GOLD AVAILABLE: NO

REMAINING HUMAN REVIEW: LR-2 ARTIFACT/BASELINE INSPECTION BEFORE LR-3 AUTHORISATION
BLOCKERS BEFORE LR-3: EXPLICIT LR-3 TRAINING AUTHORISATION
SAFE TO PROCEED TO LR-3: NO
'''
    (HERE / "LR2_PAIR_CONSTRUCTION_REPORT.md").write_text(report, encoding="utf-8")

    after = {name: file_inventory(paths) for name, paths in protected_groups.items()}
    if before != after:
        raise ValueError("protected input changed during LR-2 construction")
    validation_report["protected_snapshot_after"] = after
    validation_report["protected_files_unchanged"] = before == after
    dump_json(HERE / "lr2_pair_validation_report_v1.json", validation_report)

    checksum_targets = sorted(
        path for path in HERE.iterdir()
        if path.is_file() and path.name != "lr2_output_checksums_v1.sha256" and path.name != "__pycache__"
    )
    (HERE / "lr2_output_checksums_v1.sha256").write_text(
        "".join(f"{sha256_file(path)}  {path.name}\n" for path in checksum_targets), encoding="utf-8"
    )

    if check_only:
        missing_prior = [name for name in GENERATED_FILES if name not in prior]
        changed = [name for name, content in prior.items() if (HERE / name).read_bytes() != content]
        if missing_prior or changed:
            raise SystemExit(f"byte-identical rerun failed; missing_prior={missing_prior}, changed={changed}")
        print("BYTE_IDENTICAL_RERUN_OK")
    else:
        print(json.dumps({
            "positive_pairs": len(positive_pairs), "safe_negative_pairs": len(safe_pairs),
            "hard_negative_pairs": len(hard_pairs), "blocked_relationships": len(blocked_stats),
            "baseline_pairs": len(baseline), "singleton_labels": singleton_labels,
            "dev_labels": len(dev_labels), "pair_review_required": len(pair_review_required),
        }, indent=2, sort_keys=True))


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--check", action="store_true", help="rebuild and require byte-identical generated outputs")
    build(check_only=parser.parse_args().check)

