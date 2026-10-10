"""Fail-closed loading of frozen LR-3 research inputs."""

from __future__ import annotations

import hashlib
import json
import re
import unicodedata
from collections import defaultdict
from pathlib import Path
from typing import Any

import numpy as np


HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]
LR1 = ROOT / "evaluation/learned_intent_ranking/lr1"
LR1R = ROOT / "evaluation/learned_intent_ranking/lr1r"
LR2 = ROOT / "evaluation/learned_intent_ranking/lr2"
LR2R = ROOT / "evaluation/learned_intent_ranking/lr2r"


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def read_json(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"expected JSON object: {path}")
    return value


def read_jsonl(path: Path) -> list[dict[str, Any]]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line]


def verify_checksum_manifest(path: Path, base: Path) -> list[dict[str, Any]]:
    results = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        expected, relative = line.split(None, 1)
        relative = relative.strip().lstrip("*")
        target = base / relative
        actual = sha256_file(target) if target.is_file() else None
        results.append(
            {
                "path": relative,
                "expected_sha256": expected,
                "actual_sha256": actual,
                "match": expected == actual,
            }
        )
    if not results or not all(result["match"] for result in results):
        raise ValueError(f"checksum verification failed: {path}")
    return results


def casefolded_whitespace(text: str) -> str:
    normalized = unicodedata.normalize("NFKC", str(text))
    return re.sub(r"\s+", " ", normalized.strip()).casefold()


def deterministic_normalized(text: str) -> str:
    folded = casefolded_whitespace(text)
    without_punctuation = "".join(
        "" if unicodedata.category(character).startswith("P") else character
        for character in folded
    )
    return re.sub(r"\s+", " ", without_punctuation).strip()


def text_sha256(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def resolve_dev_records(dev_manifest_path: Path) -> list[dict[str, Any]]:
    manifest = read_jsonl(dev_manifest_path)
    source_cache: dict[Path, dict[str, dict[str, Any]]] = {}
    resolved = []
    for row in manifest:
        provenance = row["provenance"]
        source_path = ROOT / provenance["source_path"]
        if source_path not in source_cache:
            source_rows = read_jsonl(source_path)
            source_cache[source_path] = {item["case_id"]: item for item in source_rows}
        case_id = provenance["case_id"]
        turn_index = int(provenance["turn_index"])
        if row["record_id"] != f"{case_id}:T{turn_index}":
            raise ValueError(f"DEV record/turn identity mismatch: {row['record_id']}")
        if row["source_record_id"] != case_id:
            raise ValueError(f"DEV source-record mismatch: {row['record_id']}")
        case = source_cache[source_path].get(case_id)
        if case is None or not (1 <= turn_index <= len(case["turns"])):
            raise ValueError(f"DEV source turn missing: {row['record_id']}")
        turn = case["turns"][turn_index - 1]
        query = str(turn["query"])
        page = str(turn["page"])
        checks = {
            "query_sha256": text_sha256(query),
            "casefolded_whitespace_query_sha256": text_sha256(casefolded_whitespace(query)),
            "normalised_query_sha256": text_sha256(deterministic_normalized(query)),
        }
        for field, actual in checks.items():
            if actual != row[field]:
                raise ValueError(f"DEV {field} mismatch: {row['record_id']}")
        if page != row["current_page"]:
            raise ValueError(f"DEV page mismatch: {row['record_id']}")
        acceptable = list(turn.get("acceptable_intents") or [])
        if acceptable != [row["intent_label"]]:
            raise ValueError(f"DEV authoritative label mismatch: {row['record_id']}")
        resolved.append(
            {
                **row,
                "query": query,
                "resolved_current_page": page,
                "source_resolution_verified": True,
            }
        )
    if len(resolved) != 84 or len({row["record_id"] for row in resolved}) != 84:
        raise ValueError("DEV must resolve to 84 unique records")
    return resolved


def _npz_scalar(archive: Any, name: str) -> str:
    if name not in archive.files:
        raise ValueError(f"embedding artifact missing {name}")
    value = np.asarray(archive[name])
    if value.size != 1:
        raise ValueError(f"embedding artifact {name} must be scalar")
    return str(value.reshape(-1)[0])


def load_frozen_candidate_artifacts() -> dict[str, Any]:
    config_path = ROOT / "semantic_runtime/config/semantic_routing_config.json"
    config = read_json(config_path)
    approved_config = config["artifacts"]["approved_index"]
    embedding_config = config["artifacts"]["embedding_npz"]
    index_path = ROOT / approved_config["path"]
    embedding_path = ROOT / embedding_config["path"]
    if sha256_file(index_path) != approved_config["sha256"]:
        raise ValueError("approved-index hash mismatch")
    if sha256_file(embedding_path) != embedding_config["sha256"]:
        raise ValueError("embedding-artifact hash mismatch")
    index_records = read_jsonl(index_path)
    if len(index_records) != 62 or len({row["example_id"] for row in index_records}) != 62:
        raise ValueError("approved index must contain 62 unique examples")
    with np.load(embedding_path, allow_pickle=False) as archive:
        embeddings = np.asarray(archive["embeddings"]).copy()
        example_ids = [str(item) for item in np.asarray(archive["example_ids"]).tolist()]
        metadata = {
            key: _npz_scalar(archive, key)
            for key in [
                "retrieval_text_version",
                "approved_index_version",
                "approved_index_sha256",
                "model_key",
                "repo_id",
                "model_revision",
                "model_version",
            ]
        }
    if embeddings.shape[0] != 62 or embeddings.ndim != 2:
        raise ValueError("unexpected frozen embedding shape")
    if embeddings.dtype != np.float32:
        raise ValueError("frozen embeddings must be float32")
    if example_ids != [row["example_id"] for row in index_records]:
        raise ValueError("embedding example order mismatch")
    if metadata["approved_index_sha256"] != sha256_file(index_path):
        raise ValueError("embedding/index binding mismatch")
    model = config["model"]
    if metadata["repo_id"] != model["repo_id"] or metadata["model_revision"] != model["revision"]:
        raise ValueError("embedding model identity mismatch")
    if model.get("local_files_only") is not True or config.get("allow_network_downloads") is not False:
        raise ValueError("frozen runtime must be local-only")
    if config.get("aggregation") != "max" or config.get("aggregate_all_examples") is not True:
        raise ValueError("frozen aggregation contract mismatch")
    labels = sorted({row["final_semantic_label"] for row in index_records})
    if len(labels) != 16:
        raise ValueError("production index must expose 16 labels")
    return {
        "config_path": config_path,
        "config": config,
        "index_path": index_path,
        "embedding_path": embedding_path,
        "index_records": index_records,
        "embeddings": embeddings,
        "example_ids": example_ids,
        "embedding_metadata": metadata,
        "embedding_dimension": int(embeddings.shape[1]),
        "production_labels": labels,
        "approved_index_sha256": sha256_file(index_path),
        "embedding_artifact_sha256": sha256_file(embedding_path),
        "embedding_matrix_sha256": hashlib.sha256(embeddings.tobytes(order="C")).hexdigest(),
    }


def _stable_order_key(seed: int, stratum: str, anchor_id: str, candidate_id: str) -> str:
    payload = f"{seed}|{stratum}|{anchor_id}|{candidate_id}".encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def _circular_take(
    pool: list[dict[str, Any]],
    quota: int,
    epoch: int,
    seed: int,
    stratum: str,
    anchor_id: str,
) -> list[dict[str, Any]]:
    ordered = sorted(
        pool,
        key=lambda row: _stable_order_key(seed, stratum, anchor_id, row["candidate_record_id"]),
    )
    if quota <= 0 or not ordered:
        return []
    if quota > len(ordered):
        raise ValueError("episodic quota exceeds pool size")
    start = (epoch * quota) % len(ordered)
    return [ordered[(start + offset) % len(ordered)] for offset in range(quota)]


def build_epoch_sampler_inputs() -> dict[str, Any]:
    lr2r_checks = verify_checksum_manifest(LR2R / "lr2r_output_checksums_v1.sha256", LR2R)
    universe = read_json(LR2R / "lr2r_label_universe_v1.json")
    exclusions = read_json(LR2R / "lr2r_singleton_exclusion_manifest_v1.json")
    spec = read_json(LR2R / "lr2r_episodic_sampling_spec_v1.json")
    validation = read_json(LR2R / "lr2r_validation_report_v1.json")
    old = exclusions["superseded_lr2_baseline_v1"]
    if old["status"] != "SUPERSEDED_NOT_ELIGIBLE_FOR_LR3_AUTHORISATION":
        raise ValueError("old LR-2 v1 baseline is not explicitly superseded")
    old_path = ROOT / old["path"]
    if sha256_file(old_path) != old["sha256"]:
        raise ValueError("superseded LR-2 baseline hash mismatch")
    # The superseded baseline is deliberately never deserialized.
    train_path_text = "evaluation/learned_intent_ranking/lr1/ranker_train_manifest_candidate_v1.jsonl"
    train_path = ROOT / train_path_text
    expected_train_hash = validation["input_hashes"][train_path_text]
    if sha256_file(train_path) != expected_train_hash:
        raise ValueError("TRAIN manifest hash mismatch")
    train = read_jsonl(train_path)
    pairwise_labels = set(universe["pairwise_training_universe"]["labels"])
    singleton_ids = {row["record_id"] for row in exclusions["records"]}
    eligible_train = [
        row for row in train
        if row["intent_label"] in pairwise_labels and row["record_id"] not in singleton_ids
    ]
    eligible_ids = {row["record_id"] for row in eligible_train}
    if len(eligible_train) != 58 or len(pairwise_labels) != 12:
        raise ValueError("repaired pairwise universe mismatch")
    positive_source = spec["source_candidate_pools"]["positive"]
    negative_source = spec["source_candidate_pools"]["safe_negative"]
    positive_path = ROOT / positive_source["path"]
    negative_path = ROOT / negative_source["path"]
    if sha256_file(positive_path) != positive_source["sha256"]:
        raise ValueError("positive-pool hash mismatch")
    if sha256_file(negative_path) != negative_source["sha256"]:
        raise ValueError("safe-negative-pool hash mismatch")
    positives = [
        row for row in read_jsonl(positive_path)
        if row["anchor_record_id"] in eligible_ids and row["candidate_record_id"] in eligible_ids
    ]
    negatives = [
        row for row in read_jsonl(negative_path)
        if row["anchor_record_id"] in eligible_ids and row["candidate_record_id"] in eligible_ids
    ]
    if len(positives) != 280 or len(negatives) != 2210:
        raise ValueError("eligible pair pools mismatch")
    if any(row["target"] != 1 or row["relationship_class"] != "SAME_INTENT_POSITIVE" for row in positives):
        raise ValueError("positive pool governance violation")
    if any(row["target"] != 0 or row["relationship_class"] != "SAFE_RANDOM_NEGATIVE" for row in negatives):
        raise ValueError("negative pool governance violation")
    if any(
        row["anchor_record_id"] in singleton_ids or row["candidate_record_id"] in singleton_ids
        for row in positives + negatives
    ):
        raise ValueError("singleton exposure in eligible pools")
    positive_by_anchor: dict[str, list[dict[str, Any]]] = defaultdict(list)
    negative_by_anchor: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in positives:
        positive_by_anchor[row["anchor_record_id"]].append(row)
    for row in negatives:
        negative_by_anchor[row["anchor_record_id"]].append(row)
    if any(not positive_by_anchor[row["record_id"]] or not negative_by_anchor[row["record_id"]] for row in eligible_train):
        raise ValueError("eligible anchor lacks a pair stratum")
    return {
        "checksum_verification": lr2r_checks,
        "universe": universe,
        "exclusions": exclusions,
        "spec": spec,
        "validation": validation,
        "train_path": train_path,
        "train": train,
        "eligible_train": eligible_train,
        "eligible_ids": eligible_ids,
        "pairwise_labels": pairwise_labels,
        "singleton_ids": singleton_ids,
        "positive_path": positive_path,
        "negative_path": negative_path,
        "positive_pool": positives,
        "negative_pool": negatives,
        "positive_by_anchor": positive_by_anchor,
        "negative_by_anchor": negative_by_anchor,
        "sampling_seed": int(spec["fixed_seed"]),
        "max_positives_per_anchor": 2,
        "old_baseline_path_verified_but_not_loaded": str(old_path.relative_to(ROOT)),
    }


def generate_epoch_pairs(sampler: dict[str, Any], epoch: int) -> list[dict[str, Any]]:
    if not isinstance(epoch, int) or epoch < 0:
        raise ValueError("epoch must be a non-negative integer")
    selected: list[dict[str, Any]] = []
    seed = sampler["sampling_seed"]
    for anchor in sampler["eligible_train"]:
        anchor_id = anchor["record_id"]
        positive_pool = sampler["positive_by_anchor"][anchor_id]
        quota = min(sampler["max_positives_per_anchor"], len(positive_pool))
        positives = _circular_take(positive_pool, quota, epoch, seed, "POSITIVE", anchor_id)
        negatives = _circular_take(
            sampler["negative_by_anchor"][anchor_id], quota, epoch, seed, "SAFE_NEGATIVE", anchor_id
        )
        if len(positives) != len(negatives):
            raise ValueError("per-anchor target balance failed")
        selected.extend(positives)
        selected.extend(negatives)
    selected.sort(key=lambda row: row["pair_id"])
    if len(selected) != 228 or sum(row["target"] == 1 for row in selected) != 114:
        raise ValueError("epoch pair count/balance mismatch")
    if any(
        row["anchor_record_id"] not in sampler["eligible_ids"]
        or row["candidate_record_id"] not in sampler["eligible_ids"]
        for row in selected
    ):
        raise ValueError("epoch includes a record outside repaired TRAIN")
    if any(
        row["anchor_record_id"] in sampler["singleton_ids"]
        or row["candidate_record_id"] in sampler["singleton_ids"]
        for row in selected
    ):
        raise ValueError("epoch includes singleton exposure")
    return selected


def pair_symmetry_diagnostic(rows: list[dict[str, Any]], epoch: int | None = None) -> dict[str, Any]:
    grouped: dict[tuple[str, str], list[dict[str, Any]]] = defaultdict(list)
    for row in rows:
        key = tuple(sorted((row["anchor_record_id"], row["candidate_record_id"])))
        grouped[key].append(row)
    reverse_groups = [items for items in grouped.values() if len(items) > 1]
    return {
        "epoch": epoch,
        "directed_row_count": len(rows),
        "unique_unordered_record_pair_count": len(grouped),
        "reverse_duplicate_group_count": len(reverse_groups),
        "positive_reverse_duplicate_group_count": sum(items[0]["target"] == 1 for items in reverse_groups),
        "negative_reverse_duplicate_group_count": sum(items[0]["target"] == 0 for items in reverse_groups),
        "effective_unique_feature_count": len(grouped),
        "positive_count": sum(row["target"] == 1 for row in rows),
        "negative_count": sum(row["target"] == 0 for row in rows),
    }


def load_dev_views(dev_records: list[dict[str, Any]]) -> dict[str, list[str]]:
    views = read_json(LR2R / "ranker_dev_evaluation_views_v1.json")["views"]
    pairwise_ids = [row["record_id"] for row in views["pairwise_seen_labels"]["records"]]
    singleton_ids = [row["record_id"] for row in views["singleton_unseen_labels"]["records"]]
    mixed_ids = [row["record_id"] for row in dev_records]
    if len(pairwise_ids) != 79 or len(singleton_ids) != 5 or len(mixed_ids) != 84:
        raise ValueError("DEV view counts mismatch")
    if set(pairwise_ids) & set(singleton_ids) or set(pairwise_ids) | set(singleton_ids) != set(mixed_ids):
        raise ValueError("DEV record views are not a disjoint exhaustive partition")
    return {
        "VIEW_A_PAIRWISE_SEEN": pairwise_ids,
        "VIEW_B_SINGLETON_UNSEEN": singleton_ids,
        "VIEW_C_MIXED": mixed_ids,
    }
