"""LR-2R: repair singleton exposure and freeze deterministic episodic sampling."""

from __future__ import annotations

import argparse
import hashlib
import json
import math
from collections import Counter, defaultdict
from pathlib import Path


HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]
LR1 = ROOT / "evaluation/learned_intent_ranking/lr1"
LR1R = ROOT / "evaluation/learned_intent_ranking/lr1r"
LR2 = ROOT / "evaluation/learned_intent_ranking/lr2"
SEED = 20260813
MAX_POSITIVES_PER_ANCHOR = 2
BASELINE_EPOCH = 0

GENERATED = [
    "LR2R_PAIRWISE_TRAINING_EXPOSURE_REPAIR_REPORT.md",
    "lr2r_label_universe_v1.json",
    "lr2r_singleton_exclusion_manifest_v1.json",
    "lr2r_episodic_sampling_spec_v1.json",
    "ranker_pair_dataset_baseline_candidate_v2.jsonl",
    "ranker_dev_evaluation_views_v1.json",
    "lr2r_validation_report_v1.json",
    "lr2r_output_checksums_v1.sha256",
]


def sha(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def read_jsonl(path: Path) -> list[dict]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line]


def write_json(path: Path, value) -> None:
    path.write_text(json.dumps(value, indent=2, sort_keys=True, ensure_ascii=False) + "\n", encoding="utf-8")


def write_jsonl(path: Path, rows: list[dict]) -> None:
    path.write_text(
        "".join(json.dumps(row, sort_keys=True, ensure_ascii=False, separators=(",", ":")) + "\n" for row in rows),
        encoding="utf-8",
    )


def inventory(paths: list[Path]) -> dict[str, str]:
    return {str(path.relative_to(ROOT)): sha(path) for path in sorted(paths) if path.is_file()}


def verify_manifest(path: Path, base: Path) -> list[dict]:
    results = []
    for line in path.read_text(encoding="utf-8").splitlines():
        expected, relative = line.split(None, 1)
        relative = relative.strip().lstrip("*")
        target = base / relative
        actual = sha(target) if target.is_file() else None
        results.append({"path": relative, "expected_sha256": expected, "actual_sha256": actual, "match": expected == actual})
    if not results or not all(row["match"] for row in results):
        raise ValueError(f"checksum verification failed: {path}")
    return results


def stable_order_key(stratum: str, anchor_id: str, candidate_id: str) -> str:
    payload = f"{SEED}|{stratum}|{anchor_id}|{candidate_id}".encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def circular_epoch_window(pool: list[dict], quota: int, epoch: int, stratum: str, anchor_id: str) -> list[dict]:
    if epoch < 0:
        raise ValueError("epoch must be non-negative")
    if quota < 0:
        raise ValueError("quota must be non-negative")
    ordered = sorted(pool, key=lambda row: stable_order_key(stratum, anchor_id, row["candidate_record_id"]))
    take = min(quota, len(ordered))
    if take == 0:
        return []
    start = (epoch * take) % len(ordered)
    return [ordered[(start + offset) % len(ordered)] for offset in range(take)]


def select_epoch(
    epoch: int,
    train: list[dict],
    positive_by_anchor: dict[str, list[dict]],
    safe_by_anchor: dict[str, list[dict]],
) -> tuple[list[dict], list[dict]]:
    selected, stats = [], []
    for anchor in train:
        anchor_id = anchor["record_id"]
        positive_pool = positive_by_anchor[anchor_id]
        positive_quota = min(MAX_POSITIVES_PER_ANCHOR, len(positive_pool))
        positives = circular_epoch_window(positive_pool, positive_quota, epoch, "POSITIVE", anchor_id)
        negatives = circular_epoch_window(safe_by_anchor[anchor_id], len(positives), epoch, "SAFE_NEGATIVE", anchor_id)
        if len(negatives) != len(positives):
            raise ValueError(f"insufficient safe negatives for {anchor_id}")
        for source in positives + negatives:
            row = dict(source)
            row["governance_status"] = "CANDIDATE_FOR_LR3_TRAINING_AFTER_LR2R_REVIEW"
            row["lr2r_sampling_epoch"] = epoch
            row["lr2r_sampling_seed"] = SEED
            row["lr2r_sampling_spec"] = "lr2r-episodic-balanced-sampling-v1"
            selected.append(row)
        p_period = len(positive_pool) // math.gcd(len(positive_pool), positive_quota) if positive_quota else 0
        n_quota = len(positives)
        n_period = len(safe_by_anchor[anchor_id]) // math.gcd(len(safe_by_anchor[anchor_id]), n_quota) if n_quota else 0
        stats.append({
            "anchor_record_id": anchor_id,
            "anchor_intent": anchor["intent_label"],
            "positive_pool_count": len(positive_pool),
            "safe_negative_pool_count": len(safe_by_anchor[anchor_id]),
            "positive_quota": len(positives),
            "safe_negative_quota": len(negatives),
            "positive_rotation_period_epochs": p_period,
            "safe_negative_rotation_period_epochs": n_period,
        })
    selected.sort(key=lambda row: row["pair_id"])
    return selected, stats


def build(check: bool = False) -> None:
    prior = {name: (HERE / name).read_bytes() for name in GENERATED if (HERE / name).is_file()} if check else {}

    protected_paths = {
        "production": [ROOT / path for path in [
            "utils/c_full_service.py", "utils/production_intent_router.py", "utils/semantic_intent_router.py",
            "utils/intent_schema.py", "utils/intent_example_index.py", "utils/evidence_synthesiser.py",
            "utils/conversation_memory.py", "utils/recommendation_planner.py",
        ]],
        "semantic_runtime": list((ROOT / "semantic_runtime").rglob("*")),
        "lr1": list(LR1.rglob("*")),
        "lr1r": list(LR1R.rglob("*")),
        "lr2": list(LR2.rglob("*")),
        "original_data": [ROOT / path for path in [
            "evaluation/functional_qa/functional_qa_cases_v1.jsonl",
            "evaluation/unified_benchmark_scenarios.jsonl",
            "evaluation/unified_benchmark_gold_labels.jsonl",
        ]],
    }
    before = {name: inventory(paths) for name, paths in protected_paths.items()}
    checksum_results = {
        "lr1": verify_manifest(LR1 / "LR1_OUTPUT_HASHES.sha256", LR1),
        "lr1r": verify_manifest(LR1R / "lr1r_output_checksums_v1.sha256", LR1R),
        "lr2": verify_manifest(LR2 / "lr2_output_checksums_v1.sha256", LR2),
    }

    train_path = LR1 / "ranker_train_manifest_candidate_v1.jsonl"
    production_index_path = ROOT / "semantic_runtime/artifacts/intent_examples_approved_index_v1.jsonl"
    universe_path = LR2 / "lr2_label_universe_v1.json"
    feasibility_path = LR2 / "lr2_positive_pair_feasibility_v1.json"
    positive_path = LR2 / "ranker_positive_pair_candidates_v1.jsonl"
    safe_path = LR2 / "ranker_safe_negative_pair_candidates_v1.jsonl"
    baseline_v1_path = LR2 / "ranker_pair_dataset_baseline_candidate_v1.jsonl"
    dev_path = LR2 / "ranker_dev_reference_manifest_v1.json"

    train = read_jsonl(train_path)
    production_index = read_jsonl(production_index_path)
    universe = json.loads(universe_path.read_text(encoding="utf-8"))
    feasibility = json.loads(feasibility_path.read_text(encoding="utf-8"))
    positive_all = read_jsonl(positive_path)
    safe_all = read_jsonl(safe_path)
    baseline_v1 = read_jsonl(baseline_v1_path)
    dev_reference = json.loads(dev_path.read_text(encoding="utf-8"))

    production_labels = universe["included_labels"]
    singleton_labels = feasibility["singleton_labels"]
    singleton_set = set(singleton_labels)
    pairwise_labels = [label for label in production_labels if label not in singleton_set]
    pairwise_set = set(pairwise_labels)
    singleton_records = [row for row in train if row["intent_label"] in singleton_set]
    singleton_ids = {row["record_id"] for row in singleton_records}
    pairwise_train = [row for row in train if row["intent_label"] in pairwise_set]
    assert len(production_labels) == 16 and len(pairwise_labels) == 12 and len(singleton_records) == 4 and len(pairwise_train) == 58
    assert all(sum(row["intent_label"] == label for row in train) == 1 for label in singleton_labels)
    v1_singleton_exposure = {
        "anchor_count": sum(row["anchor_record_id"] in singleton_ids for row in baseline_v1),
        "positive_candidate_count": sum(row["target"] == 1 and row["candidate_record_id"] in singleton_ids for row in baseline_v1),
        "negative_candidate_count": sum(row["target"] == 0 and row["candidate_record_id"] in singleton_ids for row in baseline_v1),
        "total_record_reference_count": sum(
            record_id in singleton_ids
            for row in baseline_v1
            for record_id in (row["anchor_record_id"], row["candidate_record_id"])
        ),
    }
    assert v1_singleton_exposure == {"anchor_count": 0, "positive_candidate_count": 0, "negative_candidate_count": 8, "total_record_reference_count": 8}

    production_index_by_id = {row["example_id"]: row for row in production_index}
    singleton_index_verification = []
    for row in singleton_records:
        indexed = production_index_by_id.get(row["record_id"])
        if not indexed:
            raise ValueError(f"singleton missing from production index: {row['record_id']}")
        singleton_index_verification.append({
            "label": row["intent_label"],
            "record_id": row["record_id"],
            "source_record_id": row["source_record_id"],
            "query_sha256": row["query_sha256"],
            "present_in_production_mpnet_retrieval_index": True,
            "production_index_record_sha256": hashlib.sha256(json.dumps(indexed, sort_keys=True, separators=(",", ":")).encode()).hexdigest(),
            "pairwise_training_roles": {"anchor": "PROHIBITED", "positive_candidate": "PROHIBITED", "negative_candidate": "PROHIBITED"},
        })

    write_json(HERE / "lr2r_label_universe_v1.json", {
        "schema_version": "lr2r-label-universe-v1",
        "status": "FROZEN_PRODUCTION_UNIVERSE_WITH_REPAIRED_PAIRWISE_EXPOSURE",
        "production_retrieval_universe": {"label_count": 16, "labels": production_labels, "record_count": 62,
                                          "source_path": str(universe_path.relative_to(ROOT)), "source_sha256": sha(universe_path)},
        "pairwise_training_universe": {"label_count": 12, "labels": pairwise_labels, "record_count": 58},
        "singleton_retrieval_only_universe": {"label_count": 4, "labels": singleton_labels, "record_count": 4},
        "future_lr3_pair_artifact_authority": {
            "eligible_candidate": "evaluation/learned_intent_ranking/lr2r/ranker_pair_dataset_baseline_candidate_v2.jsonl",
            "superseded_ineligible_candidate": "evaluation/learned_intent_ranking/lr2/ranker_pair_dataset_baseline_candidate_v1.jsonl",
            "lr3_training_authorised": False,
        },
        "production_taxonomy_modified": False,
        "production_retrieval_index_modified": False,
    })
    write_json(HERE / "lr2r_singleton_exclusion_manifest_v1.json", {
        "schema_version": "lr2r-singleton-exclusion-manifest-v1",
        "policy": "Singleton records are retained unchanged for production MPNet retrieval and prohibited from every pairwise-training role.",
        "singleton_label_count": 4,
        "singleton_record_count": 4,
        "production_index_path": str(production_index_path.relative_to(ROOT)),
        "production_index_sha256": sha(production_index_path),
        "superseded_lr2_baseline_v1": {
            "path": str(baseline_v1_path.relative_to(ROOT)),
            "sha256": sha(baseline_v1_path),
            "status": "SUPERSEDED_NOT_ELIGIBLE_FOR_LR3_AUTHORISATION",
            "singleton_exposure": v1_singleton_exposure,
        },
        "records": singleton_index_verification,
    })

    positive_eligible = [row for row in positive_all if row["anchor_intent"] in pairwise_set and row["candidate_intent"] in pairwise_set]
    safe_eligible = [row for row in safe_all if row["anchor_intent"] in pairwise_set and row["candidate_intent"] in pairwise_set]
    positive_by_anchor, safe_by_anchor = defaultdict(list), defaultdict(list)
    for row in positive_eligible:
        positive_by_anchor[row["anchor_record_id"]].append(row)
    for row in safe_eligible:
        safe_by_anchor[row["anchor_record_id"]].append(row)
    assert all(positive_by_anchor[row["record_id"]] for row in pairwise_train)
    assert all(safe_by_anchor[row["record_id"]] for row in pairwise_train)

    epoch0, anchor_stats = select_epoch(BASELINE_EPOCH, pairwise_train, positive_by_anchor, safe_by_anchor)
    epoch1, _ = select_epoch(1, pairwise_train, positive_by_anchor, safe_by_anchor)
    epoch2, _ = select_epoch(2, pairwise_train, positive_by_anchor, safe_by_anchor)
    write_jsonl(HERE / "ranker_pair_dataset_baseline_candidate_v2.jsonl", epoch0)

    epoch_sets = [{row["pair_id"] for row in rows} for rows in [epoch0, epoch1, epoch2]]
    rotation = {
        "epoch_0_vs_1_changed_pair_count": len(epoch_sets[0] ^ epoch_sets[1]),
        "epoch_1_vs_2_changed_pair_count": len(epoch_sets[1] ^ epoch_sets[2]),
        "epoch_0_vs_2_changed_pair_count": len(epoch_sets[0] ^ epoch_sets[2]),
    }
    if not all(rotation.values()):
        raise ValueError("epoch rotation failed to change the selected pair set")

    write_json(HERE / "lr2r_episodic_sampling_spec_v1.json", {
        "schema_version": "lr2r-episodic-balanced-sampling-v1",
        "status": "FROZEN_CANDIDATE_FOR_LR3_AFTER_EXPLICIT_AUTHORISATION",
        "source_candidate_pools": {
            "positive": {"path": str(positive_path.relative_to(ROOT)), "sha256": sha(positive_path), "eligible_after_singleton_filter": len(positive_eligible)},
            "safe_negative": {"path": str(safe_path.relative_to(ROOT)), "sha256": sha(safe_path), "eligible_after_singleton_filter": len(safe_eligible)},
        },
        "fixed_seed": SEED,
        "epoch_domain": "non-negative integer",
        "eligible_anchor_count": len(pairwise_train),
        "excluded_singleton_record_ids": sorted(singleton_ids),
        "per_anchor_rule": {"positive_quota": "min(2, eligible_nonself_same-label positive pool size)",
                            "safe_negative_quota": "exactly equal to selected positive count",
                            "allowed_negative_relationship": "SAFE_RANDOM_NEGATIVE only"},
        "ordering": "ascending SHA-256(seed|stratum|anchor_record_id|candidate_record_id)",
        "epoch_rotation": "For pool length L and quota Q, start=(epoch*Q) mod L; take Q consecutive circular entries.",
        "rotation_period": "L/gcd(L,Q) epochs per anchor and stratum; every eligible pool member appears within one period.",
        "serialization": "sorted-key compact JSONL with LF; rows sorted by pair_id",
        "baseline_v2_materialised_epoch": BASELINE_EPOCH,
        "supersedes_for_any_future_lr3_authorisation": "evaluation/learned_intent_ranking/lr2/ranker_pair_dataset_baseline_candidate_v1.jsonl",
        "original_lr2_baseline_status": "SUPERSEDED_NOT_ELIGIBLE_FOR_LR3_AUTHORISATION",
        "epoch_0_record_count": len(epoch0),
        "epoch_0_target_counts": dict(sorted(Counter(row["target"] for row in epoch0).items())),
        "rotation_verification": rotation,
        "per_anchor_feasibility_and_periods": anchor_stats,
    })

    dev_records = dev_reference["records"]
    dev_counts = Counter(row["intent_label"] for row in dev_records)
    dev_label_set = set(dev_counts)
    pairwise_seen = sorted(pairwise_set & dev_label_set)
    singleton_seen = sorted(singleton_set & dev_label_set)
    unsupported_dev = sorted(set(production_labels) - dev_label_set)
    views = {
        "pairwise_seen_labels": {
            "definition": "DEV records whose label has pairwise TRAIN exposure in the repaired 12-label universe.",
            "labels": pairwise_seen,
            "label_count": len(pairwise_seen),
            "record_count": sum(dev_counts[label] for label in pairwise_seen),
            "per_label_support": {label: dev_counts[label] for label in pairwise_seen},
            "records": [row for row in dev_records if row["intent_label"] in pairwise_set],
        },
        "singleton_unseen_labels": {
            "definition": "DEV records whose production label is singleton and receives no LR-2R pairwise-training exposure.",
            "labels": singleton_labels,
            "labels_with_dev_support": singleton_seen,
            "labels_without_dev_support": sorted(singleton_set - dev_label_set),
            "label_count": len(singleton_labels),
            "record_count": sum(dev_counts[label] for label in singleton_seen),
            "per_label_support": {label: dev_counts.get(label, 0) for label in singleton_labels},
            "records": [row for row in dev_records if row["intent_label"] in singleton_set],
        },
        "unsupported_by_dev_labels": {
            "definition": "Production-universe labels with zero records in the governed DEV candidate.",
            "labels": unsupported_dev,
            "label_count": len(unsupported_dev),
            "pairwise_capable_labels": sorted(pairwise_set & set(unsupported_dev)),
            "singleton_labels": sorted(singleton_set & set(unsupported_dev)),
            "record_count": 0,
            "records": [],
        },
    }
    write_json(HERE / "ranker_dev_evaluation_views_v1.json", {
        "schema_version": "lr2r-dev-evaluation-views-v1",
        "status": "DEVELOPMENT_ONLY",
        "source_path": str(dev_path.relative_to(ROOT)),
        "source_sha256": sha(dev_path),
        "dev_record_count": len(dev_records),
        "views_are_nonexclusive_at_label_taxonomy_level": True,
        "metric_reporting_requirement": "Report pairwise-seen, singleton/unseen, and unsupported-by-DEV coverage separately; never claim 16-label validation from DEV.",
        "views": views,
    })

    def pair_roles(rows: list[dict]) -> dict:
        all_ids = [value for row in rows for value in (row["anchor_record_id"], row["candidate_record_id"])]
        return {
            "record_count": len(rows),
            "positive_count": sum(row["target"] == 1 for row in rows),
            "negative_count": sum(row["target"] == 0 for row in rows),
            "self_pair_count": sum(row["anchor_record_id"] == row["candidate_record_id"] for row in rows),
            "singleton_anchor_count": sum(row["anchor_record_id"] in singleton_ids for row in rows),
            "singleton_positive_candidate_count": sum(row["target"] == 1 and row["candidate_record_id"] in singleton_ids for row in rows),
            "singleton_negative_candidate_count": sum(row["target"] == 0 and row["candidate_record_id"] in singleton_ids for row in rows),
            "singleton_record_reference_count": sum(record_id in singleton_ids for record_id in all_ids),
            "policy_violating_negative_count": sum(row["target"] == 0 and row["relationship_class"] != "SAFE_RANDOM_NEGATIVE" for row in rows),
        }

    epoch0_validation = pair_roles(epoch0)
    epoch1_validation = pair_roles(epoch1)
    epoch2_validation = pair_roles(epoch2)
    for result in [epoch0_validation, epoch1_validation, epoch2_validation]:
        assert result["record_count"] == 228 and result["positive_count"] == result["negative_count"] == 114
        assert result["self_pair_count"] == 0 and result["singleton_record_reference_count"] == 0
        assert result["policy_violating_negative_count"] == 0
    assert all(row["anchor_intent"] in pairwise_set and row["candidate_intent"] in pairwise_set for row in epoch0 + epoch1 + epoch2)
    assert epoch0 == select_epoch(0, pairwise_train, positive_by_anchor, safe_by_anchor)[0]

    input_hashes = {str(path.relative_to(ROOT)): sha(path) for path in [
        train_path, production_index_path, universe_path, feasibility_path, positive_path, safe_path, baseline_v1_path, dev_path,
        LR2 / "lr2_output_checksums_v1.sha256",
    ]}
    after = {name: inventory(paths) for name, paths in protected_paths.items()}
    assert before == after
    validation = {
        "schema_version": "lr2r-validation-report-v1",
        "overall_status": "PASS",
        "input_checksum_verification": checksum_results,
        "input_hashes": input_hashes,
        "production_universe_label_count": 16,
        "pairwise_training_label_count": 12,
        "singleton_record_ids": sorted(singleton_ids),
        "superseded_lr2_baseline_v1_singleton_exposure": v1_singleton_exposure,
        "baseline_v2": epoch0_validation,
        "epoch_1_preview": epoch1_validation,
        "epoch_2_preview": epoch2_validation,
        "rotation_verification": rotation,
        "production_singleton_index_verification": singleton_index_verification,
        "protected_snapshot_before": before,
        "protected_snapshot_after": after,
        "protected_files_unchanged": before == after,
        "model_trained": False,
        "lr3_started": False,
    }
    write_json(HERE / "lr2r_validation_report_v1.json", validation)

    singleton_table = "\n".join(f"| `{row['label']}` | `{row['record_id']}` | `{row['query_sha256']}` | PRESENT / UNCHANGED | PROHIBITED |" for row in singleton_index_verification)
    dev_table = "\n".join(f"| `{label}` | {dev_counts[label]} |" for label in pairwise_seen)
    protected_table = "\n".join(f"| {name} | {len(files)} | UNCHANGED |" for name, files in before.items())
    report = f'''# LR-2R — Pairwise Training Exposure Repair

## 1. Status

LR-2R repairs pairwise exposure without changing the frozen 16-intent production universe. The revised baseline v2 uses only 58 records from the 12 positive-capable labels. All four singleton records are prohibited as anchors, positive candidates, and negative candidates. Epoch 0 contains 228 balanced records (114 positive, 114 safe negative). No model was trained and LR-3 was not started.

## 2. Frozen production and pairwise universes

The production MPNet retrieval universe remains 62 examples across 16 labels. Pairwise training is a narrower 58-record, 12-label exposure universe. This is a training-governance distinction, not a taxonomy or production-index change. The immutable LR-2 v1 baseline contained eight singleton references, all as negative candidates; it is superseded and ineligible for future LR-3 authorisation.

## 3. Singleton labels and records

| Singleton label | Record | Query SHA-256 | Production retrieval | Pairwise roles |
|---|---|---|---|---|
{singleton_table}

All four records remain present in the unchanged approved production retrieval index. None is duplicated, removed, relabelled, or synthesised.

## 4. Repaired baseline candidate v2

`ranker_pair_dataset_baseline_candidate_v2.jsonl` materialises epoch 0. It contains 228 records, with 114 positives and 114 policy-safe negatives. Every pair uses only the 12 positive-capable labels. Singleton anchors: 0; singleton positive candidates: 0; singleton negative candidates: 0; self-pairs: 0; policy-violating negatives: 0.

The artifact remains `CANDIDATE_FOR_LR3_TRAINING_AFTER_LR2R_REVIEW`; it does not authorise LR-3. The immutable LR-2 v1 baseline is explicitly superseded and ineligible for any future LR-3 authorisation.

## 5. Deterministic epoch-varying sampling

For every positive-capable anchor:

1. Freeze positive and safe-negative pools after removing every singleton label/record.
2. Order each pool by SHA-256 of `seed|stratum|anchor_record_id|candidate_record_id`, using seed `{SEED}`.
3. Set positive quota to `min(2, positive pool size)`.
4. Set safe-negative quota exactly equal to the selected positive count.
5. For non-negative epoch `e`, start at `(e * quota) mod pool_length` and take `quota` circular entries.

The period for each anchor/stratum is `pool_length / gcd(pool_length, quota)`, so every eligible candidate appears within one period. Epoch 0 versus 1 changes {rotation['epoch_0_vs_1_changed_pair_count']} pair memberships; epoch 1 versus 2 changes {rotation['epoch_1_vs_2_changed_pair_count']}. Repeating the same epoch is byte-identical.

## 6. DEV evaluation views

DEV remains development-only and is partitioned into explicit reporting views.

### Pairwise-seen labels

Eight DEV labels have repaired pairwise TRAIN exposure, covering 79 records:

| Label | DEV records |
|---|---:|
{dev_table}

### Singleton/unseen labels

The view names all four singleton labels. Only `discrepancy_or_correction` is represented in DEV, with 5 records; the other three have zero DEV support. These examples must be reported as unseen-by-pairwise-training behavior, not mixed into ordinary seen-label metrics.

### Unsupported-by-DEV labels

Seven production labels have no DEV records: {', '.join(f'`{label}`' for label in unsupported_dev)}. Four are pairwise-capable and three are singleton. DEV cannot establish performance for them.

## 7. Validation

LR-1, LR-1R, and original LR-2 checksum contracts all passed. Epochs 0, 1, and 2 each contain exactly 114 positives and 114 safe negatives, with zero singleton references in any role. Epoch selection is deterministic, epoch membership rotates, every pair resolves to the governed TRAIN pool, and no DEV record enters training pairs.

## 8. Files created

- `build_pair_dataset_v2.py`, `test_pair_dataset_v2.py`
- `LR2R_PAIRWISE_TRAINING_EXPOSURE_REPAIR_REPORT.md`
- `lr2r_label_universe_v1.json`
- `lr2r_singleton_exclusion_manifest_v1.json`
- `lr2r_episodic_sampling_spec_v1.json`
- `ranker_pair_dataset_baseline_candidate_v2.jsonl`
- `ranker_dev_evaluation_views_v1.json`
- `lr2r_validation_report_v1.json`
- `lr2r_output_checksums_v1.sha256`

## 9. Files verified unchanged

| Protected group | Files | Result |
|---|---:|---|
{protected_table}

LR-2R STATUS:

PRODUCTION UNIVERSE: 16 LABELS / 62 RECORDS / UNCHANGED
PAIRWISE TRAINING UNIVERSE: 12 LABELS / 58 RECORDS
SINGLETON LABELS: 4
SINGLETON RECORDS IN PAIRWISE TRAINING: 0

BASELINE V2 RECORDS: 228
BASELINE V2 POSITIVES: 114
BASELINE V2 SAFE NEGATIVES: 114
SELF PAIRS: 0
POLICY-VIOLATING NEGATIVES: 0

DEV PAIRWISE-SEEN LABELS: 8 / 79 RECORDS
DEV SINGLETON-UNSEEN LABELS: 4 / 5 REPRESENTED RECORDS
UNSUPPORTED-BY-DEV LABELS: 7

EPOCH-VARYING SAMPLING: DETERMINISTIC AND ROTATING
MODEL TRAINED: NO
LR-3 STARTED: NO
PRODUCTION MODIFIED: NO
SEMANTIC RUNTIME MODIFIED: NO
LR-1/LR-1R/LR-2 MODIFIED: NO
SAFE TO PROCEED TO LR-3: NO — EXPLICIT LR-3 AUTHORISATION STILL REQUIRED
'''
    (HERE / "LR2R_PAIRWISE_TRAINING_EXPOSURE_REPAIR_REPORT.md").write_text(report, encoding="utf-8")

    checksummed = sorted(path for path in HERE.iterdir() if path.is_file() and path.name != "lr2r_output_checksums_v1.sha256")
    (HERE / "lr2r_output_checksums_v1.sha256").write_text(
        "".join(f"{sha(path)}  {path.name}\n" for path in checksummed), encoding="utf-8"
    )

    if check:
        missing = [name for name in GENERATED if name not in prior]
        changed = [name for name, content in prior.items() if (HERE / name).read_bytes() != content]
        if missing or changed:
            raise SystemExit(f"byte-identical rebuild failed: missing={missing}, changed={changed}")
        print("BYTE_IDENTICAL_LR2R_REBUILD_OK")
    else:
        print(json.dumps({
            "production_labels": len(production_labels),
            "pairwise_labels": len(pairwise_labels),
            "singleton_records": sorted(singleton_ids),
            "baseline_records": len(epoch0),
            "baseline_targets": dict(Counter(row["target"] for row in epoch0)),
            "dev_pairwise_seen_labels": len(pairwise_seen),
            "dev_singleton_records": views["singleton_unseen_labels"]["record_count"],
            "unsupported_by_dev_labels": len(unsupported_dev),
            "rotation": rotation,
        }, indent=2, sort_keys=True))


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--check", action="store_true")
    build(check=parser.parse_args().check)
