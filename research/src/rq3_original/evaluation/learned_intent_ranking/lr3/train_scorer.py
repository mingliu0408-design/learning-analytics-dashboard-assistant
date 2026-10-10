"""Deterministic head-only LR-3 training with episodic governed pairs."""

from __future__ import annotations

import copy
import hashlib
import io
import math
import random
from collections import defaultdict
from typing import Any, Callable

import numpy as np
import torch
from torch import nn

from data_loader import generate_epoch_pairs, pair_symmetry_diagnostic
from evaluate_ranker import evaluate_records, learned_score_function
from feature_builder import numpy_pair_features
from metrics import compute_view_metrics
from models import build_model, parameter_counts


TRAINING_SEEDS = (20260813, 20260814, 20260815, 20260816, 20260817)
LEARNING_RATE = 1e-3
WEIGHT_DECAY = 1e-4
BATCH_SIZE = 32
MAX_EPOCHS = 50
EARLY_STOPPING_PATIENCE = 8
GRADIENT_CLIP_NORM = 1.0


def configure_determinism() -> None:
    if torch.get_num_threads() != 1:
        torch.set_num_threads(1)
    try:
        if torch.get_num_interop_threads() != 1:
            torch.set_num_interop_threads(1)
    except RuntimeError:
        pass
    torch.use_deterministic_algorithms(True)
    torch.backends.mkldnn.enabled = False
    if hasattr(torch.backends, "cudnn"):
        torch.backends.cudnn.benchmark = False
        torch.backends.cudnn.deterministic = True


def seed_everything(seed: int) -> None:
    random.seed(seed)
    np.random.seed(seed % (2**32))
    torch.manual_seed(seed)


def batch_seed(training_seed: int, model_family: str, epoch: int) -> int:
    payload = f"lr3-batch-order-v1|{model_family}|{training_seed}|{epoch}".encode("utf-8")
    return int.from_bytes(hashlib.sha256(payload).digest()[:8], "big") % (2**63 - 1)


def parameter_tensor_hash(state_dict: dict[str, torch.Tensor]) -> str:
    digest = hashlib.sha256()
    for name in sorted(state_dict):
        tensor = state_dict[name].detach().cpu().contiguous()
        digest.update(name.encode("utf-8"))
        digest.update(str(tensor.dtype).encode("ascii"))
        digest.update(str(tuple(tensor.shape)).encode("ascii"))
        digest.update(tensor.numpy().tobytes(order="C"))
    return digest.hexdigest()


def optimizer_parameter_ids(optimizer: torch.optim.Optimizer) -> set[int]:
    return {id(parameter) for group in optimizer.param_groups for parameter in group["params"]}


def build_epoch_features(
    pair_rows: list[dict[str, Any]],
    embedding_by_id: dict[str, np.ndarray],
) -> tuple[np.ndarray, np.ndarray]:
    features = np.stack(
        [numpy_pair_features(embedding_by_id[row["anchor_record_id"]], embedding_by_id[row["candidate_record_id"]]) for row in pair_rows],
        axis=0,
    ).astype(np.float32, copy=False)
    targets = np.asarray([row["target"] for row in pair_rows], dtype=np.float32)
    return features, targets


def checkpoint_is_better(candidate: dict[str, float], best: dict[str, float] | None) -> bool:
    if best is None:
        return True
    candidate_key = (candidate["mrr"], candidate["top1_accuracy"], -candidate["epoch"])
    best_key = (best["mrr"], best["top1_accuracy"], -best["epoch"])
    return candidate_key > best_key


def detect_severe_overfit(history: list[dict[str, Any]], best_epoch: int) -> dict[str, Any]:
    best_index = next(index for index, row in enumerate(history) if row["epoch"] == best_epoch)
    after = history[best_index + 1 :]
    if len(after) < EARLY_STOPPING_PATIENCE:
        return {"flag": False, "reason": "insufficient_complete_patience_window_after_best"}
    window = after[-EARLY_STOPPING_PATIENCE:]
    best_loss = history[best_index]["training_bce"]
    final_loss = window[-1]["training_bce"]
    materially_falling = final_loss <= best_loss * 0.95
    degraded_entire_window = all(row["view_a_mrr"] < history[best_index]["view_a_mrr"] for row in window)
    return {
        "flag": bool(materially_falling and degraded_entire_window),
        "reason": "training_loss_fell_at_least_5_percent_while_view_a_mrr_remained_below_best_for_full_patience_window"
        if materially_falling and degraded_entire_window
        else "severe_overfit_rule_not_met",
        "best_epoch_training_bce": best_loss,
        "window_final_training_bce": final_loss,
        "complete_degraded_patience_window": degraded_entire_window,
    }


def train_one_seed(
    *,
    model_family: str,
    training_seed: int,
    feature_dimension: int,
    sampler: dict[str, Any],
    embedding_by_id: dict[str, np.ndarray],
    dev_records: list[dict[str, Any]],
    dev_query_vectors: dict[str, np.ndarray],
    index_records: list[dict[str, Any]],
    index_embeddings: np.ndarray,
    view_ids: dict[str, list[str]],
    production_labels: list[str],
    mpnet_model: nn.Module,
) -> dict[str, Any]:
    seed_everything(training_seed)
    model = build_model(model_family, feature_dimension).cpu()
    optimizer = torch.optim.AdamW(
        model.parameters(),
        lr=LEARNING_RATE,
        weight_decay=WEIGHT_DECAY,
    )
    criterion = nn.BCEWithLogitsLoss()
    mpnet_parameter_ids = {id(parameter) for parameter in mpnet_model.parameters()}
    optimizer_ids = optimizer_parameter_ids(optimizer)
    if mpnet_parameter_ids & optimizer_ids:
        raise ValueError("MPNet parameter leaked into optimizer")
    if any(parameter.requires_grad for parameter in mpnet_model.parameters()):
        raise ValueError("MPNet parameter remains trainable")
    history = []
    best_metric: dict[str, float] | None = None
    best_state: dict[str, torch.Tensor] | None = None
    best_predictions: list[dict[str, Any]] | None = None
    best_view_metrics: dict[str, Any] | None = None
    stale_epochs = 0
    early_stopped = False
    final_epoch = 0
    for epoch in range(MAX_EPOCHS):
        final_epoch = epoch
        pairs = generate_epoch_pairs(sampler, epoch)
        symmetry = pair_symmetry_diagnostic(pairs, epoch)
        features_np, targets_np = build_epoch_features(pairs, embedding_by_id)
        features = torch.from_numpy(features_np)
        targets = torch.from_numpy(targets_np)
        generator = torch.Generator(device="cpu")
        derived_batch_seed = batch_seed(training_seed, model_family, epoch)
        generator.manual_seed(derived_batch_seed)
        permutation = torch.randperm(len(features), generator=generator)
        model.train()
        loss_numerator = 0.0
        gradient_norms = []
        for start in range(0, len(features), BATCH_SIZE):
            batch_indices = permutation[start : start + BATCH_SIZE]
            batch_features = features[batch_indices]
            batch_targets = targets[batch_indices]
            optimizer.zero_grad(set_to_none=True)
            logits = model(batch_features)
            loss = criterion(logits, batch_targets)
            loss.backward()
            raw_gradient_norm = torch.nn.utils.clip_grad_norm_(model.parameters(), GRADIENT_CLIP_NORM)
            gradient_norms.append(float(raw_gradient_norm.detach().cpu()))
            optimizer.step()
            loss_numerator += float(loss.detach().cpu()) * len(batch_indices)
        training_bce = loss_numerator / len(features)
        predictions = evaluate_records(
            dev_records,
            dev_query_vectors,
            index_records,
            index_embeddings,
            learned_score_function(model),
        )
        view_a = compute_view_metrics(
            predictions,
            view_ids["VIEW_A_PAIRWISE_SEEN"],
            production_labels,
            "PAIRWISE-SEEN DEVELOPMENT EVALUATION",
        )
        parameter_norm = math.sqrt(
            sum(float(torch.sum(parameter.detach() ** 2).cpu()) for parameter in model.parameters())
        )
        row = {
            "epoch": epoch,
            **{key: symmetry[key] for key in [
                "directed_row_count",
                "unique_unordered_record_pair_count",
                "reverse_duplicate_group_count",
                "positive_reverse_duplicate_group_count",
                "negative_reverse_duplicate_group_count",
                "effective_unique_feature_count",
                "positive_count",
                "negative_count",
            ]},
            "training_bce": training_bce,
            "parameter_norm": parameter_norm,
            "gradient_norm_summary": {
                "mean_pre_clip": float(np.mean(gradient_norms)),
                "max_pre_clip": float(np.max(gradient_norms)),
                "clipped_batch_count": sum(value > GRADIENT_CLIP_NORM for value in gradient_norms),
            },
            "view_a_top1_accuracy": view_a["top1_accuracy"],
            "view_a_mrr": view_a["mrr"],
            "view_a_recall_at_3": view_a["recall_at_3"],
            "view_a_macro_f1": view_a["macro_f1"],
            "batch_order_seed": derived_batch_seed,
            "early_stop_status": "CONTINUE",
        }
        metric = {
            "epoch": epoch,
            "mrr": view_a["mrr"],
            "top1_accuracy": view_a["top1_accuracy"],
        }
        if checkpoint_is_better(metric, best_metric):
            best_metric = metric
            best_state = copy.deepcopy(model.state_dict())
            best_predictions = predictions
            best_view_metrics = {"VIEW_A_PAIRWISE_SEEN": view_a}
            stale_epochs = 0
            row["early_stop_status"] = "NEW_BEST"
        else:
            stale_epochs += 1
            row["early_stop_status"] = f"NO_IMPROVEMENT_{stale_epochs}_OF_{EARLY_STOPPING_PATIENCE}"
        history.append(row)
        if stale_epochs >= EARLY_STOPPING_PATIENCE:
            early_stopped = True
            history[-1]["early_stop_status"] = "EARLY_STOP_TRIGGERED"
            break
    if best_state is None or best_predictions is None or best_view_metrics is None or best_metric is None:
        raise RuntimeError("no checkpoint selected")
    model.load_state_dict(best_state)
    selected_predictions = evaluate_records(
        dev_records,
        dev_query_vectors,
        index_records,
        index_embeddings,
        learned_score_function(model),
    )
    if [row["top1_label"] for row in selected_predictions] != [row["top1_label"] for row in best_predictions]:
        raise ValueError("selected checkpoint prediction mismatch")
    view_metrics = {
        view_key: compute_view_metrics(
            selected_predictions,
            ids,
            production_labels,
            {
                "VIEW_A_PAIRWISE_SEEN": "PAIRWISE-SEEN DEVELOPMENT EVALUATION",
                "VIEW_B_SINGLETON_UNSEEN": "UNSEEN-SINGLETON DIAGNOSTIC",
                "VIEW_C_MIXED": "MIXED DEVELOPMENT DIAGNOSTIC",
            }[view_key],
        )
        for view_key, ids in view_ids.items()
    }
    tensor_hash = parameter_tensor_hash(best_state)
    overfit = detect_severe_overfit(history, int(best_metric["epoch"]))
    return {
        "model_family": model_family,
        "training_seed": training_seed,
        "best_epoch": int(best_metric["epoch"]),
        "final_epoch": final_epoch,
        "epochs_completed": final_epoch + 1,
        "early_stopped": early_stopped,
        "early_stopping_gap": final_epoch - int(best_metric["epoch"]),
        "checkpoint_tensor_hash": tensor_hash,
        "parameter_counts": parameter_counts(model),
        "optimizer_parameter_count": sum(parameter.numel() for group in optimizer.param_groups for parameter in group["params"]),
        "mpnet_parameters_in_optimizer": 0,
        "view_metrics": view_metrics,
        "training_history": history,
        "overfit_diagnostic": overfit,
        "state_dict": best_state,
        "predictions": selected_predictions,
    }
