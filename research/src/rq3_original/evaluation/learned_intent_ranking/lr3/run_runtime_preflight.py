"""Run the mandatory LR-3 input and cosine-fidelity gate without training."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys


HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from data_loader import (
    LR1R,
    LR2R,
    build_epoch_sampler_inputs,
    load_dev_views,
    load_frozen_candidate_artifacts,
    read_jsonl,
    resolve_dev_records,
    verify_checksum_manifest,
)
from runtime_fidelity import run_runtime_fidelity_preflight


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    verify_checksum_manifest(LR2R / "lr2r_output_checksums_v1.sha256", LR2R)
    sampler = build_epoch_sampler_inputs()
    frozen = load_frozen_candidate_artifacts()
    dev = resolve_dev_records(LR1R / "ranker_dev_manifest_candidate_v2.jsonl")
    views = load_dev_views(dev)
    report, query_vectors, predictions, _ = run_runtime_fidelity_preflight(dev, frozen)
    summary = {
        "runtime_fidelity": report,
        "train_records": len(sampler["eligible_train"]),
        "pairwise_labels": len(sampler["pairwise_labels"]),
        "dev_records": len(dev),
        "dev_view_counts": {key: len(value) for key, value in views.items()},
        "embedding_shape": list(frozen["embeddings"].shape),
        "query_vector_count": len(query_vectors),
        "cosine_prediction_count": len(predictions),
    }
    if args.output:
        args.output.write_text(json.dumps(summary, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps({
        "status": report["status"],
        "records": report["record_count"],
        "max_example_score_abs_diff": report["max_example_score_abs_diff"],
        "max_intent_score_abs_diff": report["max_intent_score_abs_diff"],
        "embedding_shape": list(frozen["embeddings"].shape),
    }, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
