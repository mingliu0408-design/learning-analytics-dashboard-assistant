"""Frozen K0/C0/M64 evaluation and DEV-parity execution."""

from __future__ import annotations

import hashlib
import json
import socket
import subprocess
import sys
from dataclasses import dataclass, replace
from pathlib import Path, PurePosixPath
from types import MappingProxyType
from typing import Any, Mapping, Sequence
from unittest import mock

import numpy as np


_MODULE_ROOT = Path(__file__).resolve().parents[3]
_LR3 = _MODULE_ROOT / "evaluation/learned_intent_ranking/lr3"
_LR3R = _MODULE_ROOT / "evaluation/learned_intent_ranking/lr3r"
for _candidate in (_LR3R, _LR3, _MODULE_ROOT):
    if str(_candidate) not in sys.path:
        sys.path.insert(0, str(_candidate))

from evaluation.learned_intent_ranking.lr3.data_loader import (
    load_dev_views,
    load_frozen_candidate_artifacts,
    resolve_dev_records,
)
from evaluation.learned_intent_ranking.lr3.evaluate_ranker import (
    clipped_cosine_batch,
    evaluate_records,
    learned_score_function,
)
from evaluation.learned_intent_ranking.lr4b_dev.evaluate_dev import evaluate_all_views
from evaluation.learned_intent_ranking.lr4b_dev.runtime_preflight import run_runtime_preflight
from evaluation.learned_intent_ranking.lr4b_r1.keyword_baseline_adapter import (
    SemanticRuntimeForbidden,
    adapt_keyword_query,
)

from . import (
    AUTHORITY_CONTRACT_RELATIVE,
    AUTHORITY_CONTRACT_SHA256,
    EFFECTIVE_EXPERIMENT_CONTRACT_SHA256,
    LABEL_UNIVERSE,
    REPRESENTATIVE_SEED,
    ROOT,
    STATISTICAL_CONTRACT_SHA256,
    STATISTICAL_MODULE_SHA256,
    TARGET_BRANCH,
    V0_SEEDS,
)
from .authority_contract import canonical_json_bytes, validate_authority_contract
from .checkpoint_loader import load_verified_m64, verify_all_checkpoints
from .contamination_audit import (
    EXPECTED_REFERENCE_HASHES,
    build_reference_identity_sets,
)
from .final_input_schema import build_query_variants
from .final_metrics import compute_fixed16_metrics, run_frozen_final_decision


class EvaluatorParityError(RuntimeError):
    pass


DEV_MANIFEST_RELATIVE = PurePosixPath(
    "evaluation/learned_intent_ranking/lr1r/ranker_dev_manifest_candidate_v2.jsonl"
)
DEV_MANIFEST_SHA256 = (
    "7765ffbbe48fcde543b60561f22a03cef596235af07eed58540aacb64334f09f"
)


@dataclass(frozen=True)
class PreloadedEmbeddingBackend:
    """Non-lazy adapter over the MPNet instance loaded during pre-arm."""

    model: Any
    model_version: str
    batch_size: int = 32

    def encode(self, texts: Sequence[str]) -> np.ndarray:
        if not texts or any(not str(text).strip() for text in texts):
            raise EvaluatorParityError("final embedding input is empty")
        return np.asarray(
            self.model.encode(
                list(texts),
                batch_size=self.batch_size,
                device="cpu",
                convert_to_numpy=True,
                show_progress_bar=False,
            ),
            dtype=np.float32,
        )


@dataclass(frozen=True)
class FinalRuntimeBundle:
    """All final-byte-independent assets, frozen in memory before arming."""

    authority_contract: Mapping[str, Any]
    frozen_candidate_artifacts: Mapping[str, Any]
    embedding_backend: PreloadedEmbeddingBackend
    m64_models: Mapping[int, Any]
    label_universe: tuple[str, ...]
    reference_identity_sets: Mapping[str, Any]
    runtime_identity_hashes: Mapping[str, str]
    dev_parity: Mapping[str, Any]
    prearm_report: Mapping[str, Any]


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _git(root: Path, *args: str) -> subprocess.CompletedProcess[bytes]:
    return subprocess.run(["git", *args], cwd=root, capture_output=True, check=False)


def _verify_prearm_harness_state(root: Path, expected_head: str) -> dict[str, Any]:
    commands = {
        "head": _git(root, "rev-parse", "HEAD"),
        "branch": _git(root, "branch", "--show-current"),
        "tracked": _git(root, "diff", "--quiet"),
        "staged": _git(root, "diff", "--cached", "--quiet"),
        "remote": _git(root, "remote"),
        "tags": _git(root, "tag", "--list"),
    }
    if any(value.returncode for value in commands.values()):
        raise EvaluatorParityError("approved harness Git state is not clean")
    actual_head = commands["head"].stdout.decode("ascii").strip()
    branch = commands["branch"].stdout.decode("utf-8").strip()
    if actual_head != expected_head or branch != TARGET_BRANCH:
        raise EvaluatorParityError("approved RQ1-C0-R2 harness identity mismatch")
    if commands["remote"].stdout.splitlines() or commands["tags"].stdout.splitlines():
        raise EvaluatorParityError("remote or tag appeared after harness approval")
    return {
        "approved_harness_head": actual_head,
        "branch": branch,
        "tracked_worktree_clean": True,
        "index_clean": True,
        "remote_count": 0,
        "tag_count": 0,
    }


def _verify_statistical_contract_hashes(root: Path) -> dict[str, dict[str, Any]]:
    paths = {
        "statistical_contract_json": (
            root
            / "evaluation/learned_intent_ranking/lr4b_r1/"
            "rq1a_r1_statistical_decision_contract_v1.json",
            STATISTICAL_CONTRACT_SHA256,
        ),
        "statistical_contract_module": (
            root
            / "evaluation/learned_intent_ranking/lr4b_r1/"
            "statistical_decision_contract.py",
            STATISTICAL_MODULE_SHA256,
        ),
        "effective_experiment_contract": (
            root
            / "evaluation/learned_intent_ranking/lr4b_r1/"
            "lr4b_experiment_contract_v1_1.json",
            EFFECTIVE_EXPERIMENT_CONTRACT_SHA256,
        ),
    }
    report: dict[str, dict[str, Any]] = {}
    for role, (path, expected) in paths.items():
        actual = _sha256_file(path)
        if actual != expected:
            raise EvaluatorParityError("frozen statistical contract drift")
        report[role] = {"sha256": actual, "match": True}
    return report


def _read_json(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise EvaluatorParityError("expected JSON object")
    return value


def _safe_prediction(row: Mapping[str, Any]) -> dict[str, Any]:
    ranking = tuple(str(value["label"]) for value in row["intent_ranking"])
    return {
        "record_id": str(row["record_id"]),
        "gold_label": str(row["gold_label"]),
        "ranking": ranking,
        "top1_label": str(row["top1_label"]),
        "gold_rank": row["gold_rank"],
    }


def _ranking_identity(row: Mapping[str, Any]) -> tuple[Any, ...]:
    return (
        row["record_id"],
        row["gold_rank"],
        row["top1_label"],
        tuple(
            (candidate["label"], tuple(candidate["example_ids"]))
            for candidate in row["intent_ranking"]
        ),
    )


def _load_dev_and_frozen(root: Path = ROOT) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    dev_path = root.joinpath(*DEV_MANIFEST_RELATIVE.parts)
    if not dev_path.is_file() or dev_path.is_symlink() or _sha256_file(dev_path) != DEV_MANIFEST_SHA256:
        raise EvaluatorParityError("frozen DEV manifest mismatch")
    dev_records = resolve_dev_records(dev_path)
    frozen = load_frozen_candidate_artifacts()
    if len(dev_records) != 84 or len(frozen["index_records"]) != 62:
        raise EvaluatorParityError("DEV or candidate count mismatch")
    if tuple(frozen["production_labels"]) != LABEL_UNIVERSE:
        raise EvaluatorParityError("candidate label universe mismatch")
    return dev_records, frozen


def _keyword_predictions(records: Sequence[Mapping[str, Any]]) -> tuple[list[dict[str, Any]], int]:
    def forbidden_loader(*_args: object, **_kwargs: object) -> object:
        raise SemanticRuntimeForbidden("semantic runtime called during K0 evaluation")

    predictions: list[dict[str, Any]] = []
    with mock.patch(
        "utils.production_intent_router.load_production_semantic_router",
        side_effect=forbidden_loader,
    ) as semantic_loader:
        for row in records:
            result = adapt_keyword_query(str(row["record_id"]), str(row["query"]))
            if not result.is_contract_match or len(result.ranking) != 1:
                raise EvaluatorParityError("K0 production adapter parity failed")
            gold = str(row.get("gold_label") or row.get("intent_label"))
            predictions.append(
                {
                    "record_id": str(row["record_id"]),
                    "gold_label": gold,
                    "ranking": result.ranking,
                    "top1_label": result.ranking[0],
                    "gold_rank": 1 if result.ranking[0] == gold else None,
                }
            )
        loader_calls = semantic_loader.call_count
    if loader_calls != 0:
        raise EvaluatorParityError("K0 called the semantic loader")
    return predictions, loader_calls


def _authorised_local_ledger(
    root: Path,
    relative: str,
    expected_sha256: str,
    expected_name: str,
) -> list[dict[str, Any]]:
    candidate = PurePosixPath(str(relative).replace("\\", "/"))
    expected_parent = PurePosixPath(
        "evaluation/learned_intent_ranking/lr4b_dev/local_artifacts/prediction_ledgers"
    )
    if (
        candidate.is_absolute()
        or ".." in candidate.parts
        or candidate.parent != expected_parent
        or candidate.name != expected_name
    ):
        raise EvaluatorParityError("prediction-ledger path contract mismatch")
    path = root.joinpath(*candidate.parts)
    if not path.is_file() or path.is_symlink() or _sha256_file(path) != expected_sha256:
        raise EvaluatorParityError("prediction-ledger identity mismatch")
    payload = _read_json(path)
    rows = payload.get("predictions")
    if not isinstance(rows, list) or len(rows) != 84:
        raise EvaluatorParityError("prediction-ledger record count mismatch")
    return rows


def _run_dev_parity_from_assets(
    *,
    root: Path,
    dev_records: list[dict[str, Any]],
    frozen: dict[str, Any],
    runtime: Mapping[str, Any],
    models: Mapping[int, Any],
) -> dict[str, Any]:
    c0_predictions = runtime["c0_predictions"]
    dev_vectors = runtime["dev_vectors"]
    if len(c0_predictions) != 84 or len(dev_vectors) != 84:
        raise EvaluatorParityError("C0 runtime output count mismatch")
    k0_predictions, semantic_loader_calls = _keyword_predictions(dev_records)

    c0_report = _read_json(
        root / "evaluation/learned_intent_ranking/lr4b_dev/rq1b_c0_reproduction_v1.json"
    )
    c0_reference = _authorised_local_ledger(
        root,
        str(c0_report["local_prediction_ledger_relative_path"]),
        str(c0_report["local_prediction_ledger_sha256"]),
        "rq1b_c0_dev_predictions_v1.json",
    )
    c0_by_id = {str(row["record_id"]): row for row in c0_reference}
    c0_matches = sum(
        _ranking_identity(row) == _ranking_identity(c0_by_id[str(row["record_id"])])
        for row in c0_predictions
    )
    bundle = {
        "view_ids": load_dev_views(dev_records),
        "frozen": frozen,
    }
    c0_metrics = evaluate_all_views(c0_predictions, bundle)
    c0_metric_match = c0_metrics == c0_report["actual_view_metrics"]
    if c0_matches != 84 or not c0_metric_match:
        raise EvaluatorParityError("C0 DEV parity failed")

    per_seed = _read_json(
        root / "evaluation/learned_intent_ranking/lr4b_dev/rq1b_per_seed_metrics_v1.json"
    )
    references = {
        int(row["seed"]): row
        for row in per_seed["runs"]
        if row["scenario"] == "V0"
    }
    if tuple(sorted(references)) != V0_SEEDS:
        raise EvaluatorParityError("V0 reference seed set mismatch")
    seed_reports: list[dict[str, Any]] = []
    for seed in V0_SEEDS:
        model = models[seed]
        predictions = evaluate_records(
            dev_records,
            dev_vectors,
            frozen["index_records"],
            frozen["embeddings"],
            learned_score_function(model),
        )
        reference_run = references[seed]
        reference_rows = _authorised_local_ledger(
            root,
            str(reference_run["prediction_ledger_relative_path"]),
            str(reference_run["prediction_ledger_sha256"]),
            f"rq1b_m64_v0_seed_{seed}_dev_predictions_v1.json",
        )
        reference_by_id = {str(row["record_id"]): row for row in reference_rows}
        matches = sum(
            _ranking_identity(row)
            == _ranking_identity(reference_by_id[str(row["record_id"])])
            for row in predictions
        )
        actual_metrics = evaluate_all_views(predictions, bundle)
        metric_match = actual_metrics == reference_run["view_metrics"]
        if matches != 84 or not metric_match:
            raise EvaluatorParityError("M64 DEV parity failed")
        seed_reports.append(
            {
                "seed": seed,
                "ranking_identity_match_count": matches,
                "ranking_identity_required": 84,
                "metrics_exact_match": metric_match,
                "view_metrics": actual_metrics,
                "pass": True,
            }
        )
    k0_metrics = compute_fixed16_metrics(k0_predictions)
    return {
        "schema_version": "rq1c-dev-parity-v1",
        "stage": "RQ1-C0-R1",
        "status": "PASS",
        "development_only": True,
        "dev_record_count": 84,
        "k0": {
            "record_count": len(k0_predictions),
            "semantic_loader_call_count": semantic_loader_calls,
            "ranking_length": 1,
            "mrr_equals_top1": k0_metrics["mrr"] == k0_metrics["top1_accuracy"],
            "fixed16_metrics": k0_metrics,
            "pass": True,
        },
        "c0": {
            "ranking_identity_match_count": c0_matches,
            "ranking_identity_required": 84,
            "metrics_exact_match": c0_metric_match,
            "view_metrics": c0_metrics,
            "pass": True,
        },
        "m64_v0": {
            "seed_count": len(seed_reports),
            "seeds": seed_reports,
            "all_seed_ranking_identity_match": True,
            "all_seed_metrics_exact_match": True,
            "representative_seed": REPRESENTATIVE_SEED,
            "pass": True,
        },
        "contains_dev_query": False,
        "contains_prediction_ledger": False,
        "raw_final_gold_accessed": False,
        "provider_calls": 0,
        "network_access": False,
    }


def run_dev_parity(root: Path = ROOT) -> dict[str, Any]:
    """Reproduce the frozen RQ1-C0-R1 DEV report byte-for-byte."""

    dev_records, frozen = _load_dev_and_frozen(root)
    runtime = run_runtime_preflight({"dev_records": dev_records, "frozen": frozen})
    models = {seed: load_verified_m64(seed, root) for seed in V0_SEEDS}
    return _run_dev_parity_from_assets(
        root=root,
        dev_records=dev_records,
        frozen=frozen,
        runtime=runtime,
        models=models,
    )


def _immutable_reference_sets(references: Mapping[str, Any]) -> Mapping[str, Any]:
    return MappingProxyType(
        {
            role: MappingProxyType(
                {
                    "record_count": int(value["record_count"]),
                    "exact_query_hashes": frozenset(value["exact_query_hashes"]),
                    "normalised_query_hashes": frozenset(
                        value["normalised_query_hashes"]
                    ),
                    "family_ids": frozenset(value["family_ids"]),
                }
            )
            for role, value in references.items()
        }
    )


def _prepare_runtime_assets(root: Path) -> FinalRuntimeBundle:
    contract_path = root.joinpath(*AUTHORITY_CONTRACT_RELATIVE.parts)
    if (
        not contract_path.is_file()
        or contract_path.is_symlink()
        or _sha256_file(contract_path) != AUTHORITY_CONTRACT_SHA256
    ):
        raise EvaluatorParityError("frozen authority contract identity mismatch")
    authority_contract = _read_json(contract_path)
    validate_authority_contract(authority_contract)

    checkpoint_report = verify_all_checkpoints(root)
    dev_records, frozen = _load_dev_and_frozen(root)
    references = build_reference_identity_sets(root)
    statistics = _verify_statistical_contract_hashes(root)
    runtime = run_runtime_preflight({"dev_records": dev_records, "frozen": frozen})
    models = {seed: load_verified_m64(seed, root) for seed in V0_SEEDS}
    dev_parity = _run_dev_parity_from_assets(
        root=root,
        dev_records=dev_records,
        frozen=frozen,
        runtime=runtime,
        models=models,
    )
    frozen_dev_path = root / "evaluation/learned_intent_ranking/rq1c/rq1c_dev_parity_v1.json"
    if canonical_json_bytes(dev_parity) != frozen_dev_path.read_bytes():
        raise EvaluatorParityError("RQ1-C0-R1 DEV parity bytes changed")

    embeddings = np.asarray(frozen["embeddings"])
    embeddings.setflags(write=False)
    model = runtime["model"]
    tokenizer = runtime["tokenizer"]
    if getattr(model, "tokenizer", None) is not tokenizer:
        raise EvaluatorParityError("preloaded tokenizer identity mismatch")
    runtime_report = runtime["report"]
    model_report = runtime_report["model"]
    model_revision = str(model_report["revision"])
    tokenizer_source = Path(str(tokenizer.name_or_path))
    if tokenizer_source.name != model_revision and model_revision not in tokenizer_source.parts:
        raise EvaluatorParityError("preloaded tokenizer source mismatch")
    embedding_backend = PreloadedEmbeddingBackend(
        model=model,
        model_version=f"{model_report['repo_id']}@{model_revision}",
    )
    immutable_references = _immutable_reference_sets(references)

    checkpoint_hashes = {
        str(row["seed"]): str(row["file_sha256"])
        for row in checkpoint_report["checkpoints"]
    }
    reference_report = {
        role: {
            "record_count": int(immutable_references[role]["record_count"]),
            "manifest_sha256": EXPECTED_REFERENCE_HASHES[relative],
        }
        for role, relative in (
            (
                "TRAIN",
                "evaluation/learned_intent_ranking/lr4a/lr4a_r1/"
                "ranker_expanded_train_manifest_candidate_v2.jsonl",
            ),
            (
                "DEV",
                "evaluation/learned_intent_ranking/lr1r/"
                "ranker_dev_manifest_candidate_v2.jsonl",
            ),
            (
                "CANDIDATE",
                "semantic_runtime/artifacts/intent_examples_approved_index_v1.jsonl",
            ),
        )
    }
    identity_hashes = {
        "authority_contract_sha256": AUTHORITY_CONTRACT_SHA256,
        "candidate_index_sha256": str(frozen["approved_index_sha256"]),
        "candidate_embedding_artifact_sha256": str(
            frozen["embedding_artifact_sha256"]
        ),
        "candidate_embedding_matrix_sha256": str(
            frozen["embedding_matrix_sha256"]
        ),
        "dev_manifest_sha256": DEV_MANIFEST_SHA256,
        "local_sentence_bert_config_sha256": str(
            model_report["sentence_bert_config_sha256"]
        ),
        "statistical_contract_sha256": STATISTICAL_CONTRACT_SHA256,
        "statistical_module_sha256": STATISTICAL_MODULE_SHA256,
        "effective_experiment_contract_sha256": (
            EFFECTIVE_EXPERIMENT_CONTRACT_SHA256
        ),
    }
    prearm_report = {
        "schema_version": "rq1c-r2-prearm-runtime-v1",
        "stage": "RQ1-C0-R2",
        "status": "PASS",
        "authority_contract": {
            "sha256": AUTHORITY_CONTRACT_SHA256,
            "hash_match": True,
            "content_valid": True,
        },
        "approved_harness_gate": {
            "enforced_by_prepare_final_runtime_bundle": True,
            "required_branch": TARGET_BRANCH,
            "clean_tracked_worktree_required": True,
            "clean_index_required": True,
            "remote_count_required": 0,
            "tag_count_required": 0,
        },
        "checkpoint_count": checkpoint_report["checkpoint_count"],
        "all_checkpoints_preloaded": True,
        "checkpoint_file_sha256_by_seed": checkpoint_hashes,
        "candidate_artifacts": {
            "record_count": len(frozen["index_records"]),
            "embedding_shape": list(embeddings.shape),
            "embedding_dtype": str(embeddings.dtype),
            "index_sha256": frozen["approved_index_sha256"],
            "embedding_artifact_sha256": frozen["embedding_artifact_sha256"],
            "embedding_matrix_sha256": frozen["embedding_matrix_sha256"],
        },
        "embedding_runtime": {
            "backend_preloaded": True,
            "model_preloaded": True,
            "tokenizer_preloaded": True,
            "repo_id": model_report["repo_id"],
            "revision": model_revision,
            "tokenizer_source_revision_match": True,
            "device": "cpu",
            "local_files_only": True,
            "network_access_disabled": True,
        },
        "contamination_references": reference_report,
        "statistical_contract": statistics,
        "dev_parity": {
            "r1_canonical_bytes_match": True,
            "k0_semantic_loader_call_count": dev_parity["k0"][
                "semantic_loader_call_count"
            ],
            "c0_ranking_identity_match_count": dev_parity["c0"][
                "ranking_identity_match_count"
            ],
            "m64_seed_ranking_identity_match_count": [
                row["ranking_identity_match_count"]
                for row in dev_parity["m64_v0"]["seeds"]
            ],
        },
        "preloaded_assets": {
            "frozen_candidate_artifacts": True,
            "embedding_backend": True,
            "five_m64_models": True,
            "label_universe": True,
            "reference_identity_sets": True,
        },
        "runtime_identity_hash_count": len(identity_hashes),
        "raw_final_open_calls": 0,
        "raw_final_stat_calls": 0,
        "raw_final_hash_calls": 0,
        "raw_final_list_calls": 0,
        "real_lock_created": False,
        "provider_calls": 0,
        "network_access": False,
    }
    return FinalRuntimeBundle(
        authority_contract=MappingProxyType(dict(authority_contract)),
        frozen_candidate_artifacts=MappingProxyType(dict(frozen)),
        embedding_backend=embedding_backend,
        m64_models=MappingProxyType(models),
        label_universe=tuple(LABEL_UNIVERSE),
        reference_identity_sets=immutable_references,
        runtime_identity_hashes=MappingProxyType(identity_hashes),
        dev_parity=MappingProxyType(dict(dev_parity)),
        prearm_report=MappingProxyType(prearm_report),
    )


def prepare_final_runtime_bundle(
    root: Path = ROOT,
    expected_harness_head: str | None = None,
) -> FinalRuntimeBundle:
    """Verify and preload every non-final dependency before lock creation."""

    if expected_harness_head is None:
        head = _git(root, "rev-parse", "HEAD")
        if head.returncode:
            raise EvaluatorParityError("unable to resolve approved harness HEAD")
        expected_harness_head = head.stdout.decode("ascii").strip()
    harness = _verify_prearm_harness_state(root, expected_harness_head)
    bundle = _prepare_runtime_assets(root)
    identities = dict(bundle.runtime_identity_hashes)
    identities["approved_harness_head"] = harness["approved_harness_head"]
    return replace(bundle, runtime_identity_hashes=MappingProxyType(identities))


def prepare_final_runtime_bundle_for_validation(
    root: Path = ROOT,
) -> FinalRuntimeBundle:
    """Run the complete asset dry-run while the R2 commit is being assembled."""

    return _prepare_runtime_assets(root)


def _deny_network(*_args: object, **_kwargs: object) -> None:
    raise EvaluatorParityError("network access is disabled")


def _encode_final_records(
    records: Sequence[Mapping[str, Any]],
    embedding_backend: PreloadedEmbeddingBackend,
) -> dict[str, np.ndarray]:
    texts: list[str] = []
    for record in records:
        texts.extend(build_query_variants(record))
    with mock.patch("socket.create_connection", side_effect=_deny_network), mock.patch.object(
        socket.socket, "connect", side_effect=_deny_network
    ):
        matrix = np.asarray(embedding_backend.encode(texts), dtype=np.float32)
    if matrix.shape != (len(records) * 2, 768) or not np.isfinite(matrix).all():
        raise EvaluatorParityError("final embedding output mismatch")
    return {
        str(record["record_id"]): matrix[position * 2 : position * 2 + 2].copy()
        for position, record in enumerate(records)
    }


def run_final_evaluation_in_memory(
    records: list[Mapping[str, Any]],
    runtime_bundle: FinalRuntimeBundle,
) -> dict[str, Any]:
    """RQ1-C1-only model execution over already parsed in-memory records."""

    frozen = runtime_bundle.frozen_candidate_artifacts
    if (
        tuple(frozen["production_labels"]) != LABEL_UNIVERSE
        or runtime_bundle.label_universe != LABEL_UNIVERSE
    ):
        raise EvaluatorParityError("final candidate label universe mismatch")
    vectors = _encode_final_records(records, runtime_bundle.embedding_backend)
    evaluation_records = [
        {
            "record_id": str(row["record_id"]),
            "query": str(row["query"]),
            "current_page": str(row["current_page"]),
            "intent_label": str(row["gold_label"]),
        }
        for row in records
    ]
    k0_predictions, semantic_loader_calls = _keyword_predictions(evaluation_records)
    c0_full = evaluate_records(
        evaluation_records,
        vectors,
        frozen["index_records"],
        frozen["embeddings"],
        clipped_cosine_batch,
    )
    c0_safe = [_safe_prediction(row) for row in c0_full]
    m64_safe: dict[int, list[dict[str, Any]]] = {}
    for seed in V0_SEEDS:
        model = runtime_bundle.m64_models[seed]
        predictions = evaluate_records(
            evaluation_records,
            vectors,
            frozen["index_records"],
            frozen["embeddings"],
            learned_score_function(model),
        )
        m64_safe[seed] = [_safe_prediction(row) for row in predictions]
    decision = run_frozen_final_decision(
        c0_predictions=c0_safe,
        m64_predictions_by_seed=m64_safe,
    )
    unique_normalised_count = len(
        {str(row["normalised_query"]) for row in records}
    )
    family_count = len({str(row["family_id"]) for row in records})
    return {
        "schema_version": "rq1c-final-evaluation-results-v1",
        "status": "COMPLETED",
        "record_count": len(records),
        "k0_metrics": compute_fixed16_metrics(k0_predictions),
        "k0_semantic_loader_call_count": semantic_loader_calls,
        "frozen_decision": decision,
        "secondary_sensitivity": {
            "unique_query_record_count": unique_normalised_count,
            "unique_query_metrics_identical_to_primary": (
                unique_normalised_count == len(records)
            ),
            "family_cluster_count": family_count,
            "family_cluster_metrics_identical_to_primary": (
                family_count == len(records)
            ),
            "role": "SECONDARY_ONLY_NO_MODEL_OR_PRIMARY_SET_CHANGE",
        },
        "representative_seed": REPRESENTATIVE_SEED,
        "raw_query_emitted": False,
        "provider_calls": 0,
        "network_access": False,
    }
