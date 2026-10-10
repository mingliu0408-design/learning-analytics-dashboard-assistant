"""Local-only RQ1-B runtime, encoder-freeze, and C0 fidelity preflight."""

from __future__ import annotations

import importlib.metadata
import json
import platform
import socket
import sys
from pathlib import Path
from typing import Any
from unittest.mock import patch

import numpy as np
import sentence_transformers
import sklearn
import torch
import transformers

from . import LOCAL_MODEL_RELATIVE, ROOT
from .governed_data_loader import authorised_path, sha256_file


LR3 = ROOT / "evaluation/learned_intent_ranking/lr3"
LR3R = ROOT / "evaluation/learned_intent_ranking/lr3r"
for candidate in (LR3R, LR3, ROOT):
    if str(candidate) not in sys.path:
        sys.path.insert(0, str(candidate))

from compact_models import build_compact_model  # type: ignore[import-not-found]  # noqa: E402
from runtime_fidelity import (  # type: ignore[import-not-found]  # noqa: E402
    run_runtime_fidelity_preflight,
)


REQUIRED_ENVIRONMENT = {
    "PYTHONDONTWRITEBYTECODE": "1",
    "HF_HUB_OFFLINE": "1",
    "TRANSFORMERS_OFFLINE": "1",
    "TOKENIZERS_PARALLELISM": "false",
    "OPENAI_API_KEY": "",
    "CUDA_VISIBLE_DEVICES": "",
}


class RuntimePreflightError(RuntimeError):
    pass


def _deny_network(attempts: list[str]):
    def denied(*_args: Any, **_kwargs: Any) -> None:
        attempts.append("SOCKET_CONNECT_ATTEMPT")
        raise RuntimePreflightError("network access is disabled for RQ1-B")

    return denied


def run_runtime_preflight(bundle: dict[str, Any]) -> dict[str, Any]:
    import os

    mismatches = {
        name: {"expected": expected, "actual": os.environ.get(name)}
        for name, expected in REQUIRED_ENVIRONMENT.items()
        if os.environ.get(name) != expected
    }
    if mismatches:
        raise RuntimePreflightError("required offline runtime environment mismatch")

    model_path = authorised_path(LOCAL_MODEL_RELATIVE)
    if not model_path.is_dir() or model_path.name != "e8c3b32edf5434bc2275fc9bab85f82640a19130":
        raise RuntimePreflightError("fixed local model path is unavailable")
    sentence_config_path = model_path / "sentence_bert_config.json"
    sentence_config = json.loads(sentence_config_path.read_text(encoding="utf-8"))
    configured_max = int(sentence_config["max_seq_length"])
    if configured_max != 384:
        raise RuntimePreflightError("local SentenceTransformer sequence limit drift")

    attempts: list[str] = []
    denied = _deny_network(attempts)
    with patch("socket.create_connection", denied), patch.object(socket.socket, "connect", denied):
        fidelity, dev_vectors, c0_predictions, mpnet_model = run_runtime_fidelity_preflight(
            bundle["dev_records"], bundle["frozen"]
        )
    if attempts or fidelity.get("status") != "PASS":
        raise RuntimePreflightError("runtime fidelity or network-isolation gate failed")
    if next(mpnet_model.parameters()).device.type != "cpu":
        raise RuntimePreflightError("MPNet is not on CPU")
    if int(mpnet_model.max_seq_length) != configured_max:
        raise RuntimePreflightError("loaded model sequence limit differs from local config")
    mpnet_model.eval()
    for parameter in mpnet_model.parameters():
        parameter.requires_grad_(False)
    trainable_mpnet = sum(parameter.numel() for parameter in mpnet_model.parameters() if parameter.requires_grad)
    if trainable_mpnet:
        raise RuntimePreflightError("MPNet remains trainable")

    feature_dimension = int(bundle["frozen"]["embedding_dimension"]) * 2
    head = build_compact_model("M64", feature_dimension).cpu()
    optimizer = torch.optim.AdamW(head.parameters(), lr=1e-3, weight_decay=1e-4)
    optimizer_ids = {id(value) for group in optimizer.param_groups for value in group["params"]}
    leaked_parameters = sum(id(value) in optimizer_ids for value in mpnet_model.parameters())
    if leaked_parameters:
        raise RuntimePreflightError("MPNet parameter entered the M64 optimizer")

    tokenizer = mpnet_model.tokenizer
    tokenizer_source = Path(str(tokenizer.name_or_path))
    if tokenizer_source.name != model_path.name and model_path.name not in tokenizer_source.parts:
        raise RuntimePreflightError("tokenizer did not resolve from the fixed local model")
    if len(dev_vectors) != 84 or any(np.asarray(value).shape != (2, 768) for value in dev_vectors.values()):
        raise RuntimePreflightError("DEV embedding shape drift")

    safe_fidelity = {
        key: value
        for key, value in fidelity.items()
        if key != "records"
    }
    report = {
        "schema_version": "rq1b-runtime-preflight-v1",
        "stage": "RQ1-B",
        "status": "PASS",
        "python_version": platform.python_version(),
        "dependency_versions": {
            "numpy": np.__version__,
            "sentence_transformers": sentence_transformers.__version__,
            "sklearn": sklearn.__version__,
            "torch": torch.__version__,
            "transformers": transformers.__version__,
        },
        "environment": {
            name: {"required_value": value, "match": True}
            for name, value in REQUIRED_ENVIRONMENT.items()
        },
        "device": "cpu",
        "cuda_available": bool(torch.cuda.is_available()),
        "cuda_device_count": int(torch.cuda.device_count()),
        "network_access_disabled": True,
        "network_attempt_count": len(attempts),
        "local_files_only": True,
        "fallback_model_used": False,
        "fallback_embedding_used": False,
        "model": {
            "repo_id": "sentence-transformers/all-mpnet-base-v2",
            "revision": model_path.name,
            "local_path": LOCAL_MODEL_RELATIVE.as_posix(),
            "sentence_bert_config_sha256": sha256_file(sentence_config_path),
            "configured_max_sequence_length": configured_max,
            "loaded_max_sequence_length": int(mpnet_model.max_seq_length),
            "embedding_dimension": int(bundle["frozen"]["embedding_dimension"]),
            "parameter_count": sum(parameter.numel() for parameter in mpnet_model.parameters()),
            "trainable_parameter_count": trainable_mpnet,
            "parameters_in_optimizer": leaked_parameters,
        },
        "m64_parameter_count": sum(parameter.numel() for parameter in head.parameters()),
        "runtime_fidelity": safe_fidelity,
        "dev_logical_record_count": len(dev_vectors),
        "dev_effective_embedding_count": sum(len(value) for value in dev_vectors.values()),
        "deterministic_algorithms_required_during_training": True,
        "final_gold_accessed": False,
        "final_gold_searched": False,
        "provider_calls": 0,
    }
    return {
        "report": report,
        "model": mpnet_model,
        "tokenizer": tokenizer,
        "dev_vectors": dev_vectors,
        "c0_predictions": c0_predictions,
    }
