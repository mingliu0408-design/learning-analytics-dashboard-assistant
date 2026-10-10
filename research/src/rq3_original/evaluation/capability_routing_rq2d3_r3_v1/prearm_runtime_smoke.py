"""Non-consuming, offline local runtime smoke required before global reservation."""

from __future__ import annotations

from contextlib import ExitStack
import os
from pathlib import Path
import socket
import stat
from typing import Any, Mapping
from unittest.mock import patch

import numpy as np

from . import CAPABILITIES, ROOT, canonical_json_bytes, sha256_bytes
from .fixed_rq2d4_paths_v1_1 import D4PathsV1_1, resolve_fixed_rq2d4_paths_v1_1
from .frozen_capability_predictor_core_v1_1 import (
    CoreRoutingContentV1_1,
    FrozenCapabilityPredictorCoreV1_1,
)


MODEL_RELATIVE = Path(
    "semantic_runtime/models/all-mpnet-base-v2/"
    "e8c3b32edf5434bc2275fc9bab85f82640a19130"
)
EMBEDDINGS_RELATIVE = Path(
    "semantic_runtime/artifacts/intent_index_embeddings_mpnet_base_v2_v1.npz"
)


def _lstat_fixed_input(path: Path, expected_size: int) -> dict[str, Any]:
    value = os.lstat(path)
    if (
        not stat.S_ISREG(value.st_mode)
        or stat.S_ISLNK(value.st_mode)
        or value.st_size != expected_size
        or not path.is_relative_to(ROOT)
    ):
        raise RuntimeError("BLOCKED_RQ2_D3_R3_PREARM_RUNTIME")
    return {"regular_non_symlink": True, "size_bytes": value.st_size, "content_read_count": 0}


def run_prearm_runtime_smoke_v1_1(
    paths: D4PathsV1_1 | None = None,
) -> dict[str, Any]:
    paths = paths or resolve_fixed_rq2d4_paths_v1_1()
    metadata = {
        "combined_source": _lstat_fixed_input(paths.combined_source, 52833),
        "label_only_gold": _lstat_fixed_input(paths.label_gold, 29626),
        "grouping_ledger": _lstat_fixed_input(paths.grouping, 4176),
    }
    attempts = {"network": 0}

    def blocked(*_args: Any, **_kwargs: Any) -> Any:
        attempts["network"] += 1
        raise RuntimeError("offline prearm blocked network")

    environment = {
        "PYTHONDONTWRITEBYTECODE": "1",
        "HF_HUB_OFFLINE": "1",
        "TRANSFORMERS_OFFLINE": "1",
        "TOKENIZERS_PARALLELISM": "false",
        "OPENAI_API_KEY": "",
        "CUDA_VISIBLE_DEVICES": "",
    }
    with ExitStack() as stack:
        stack.enter_context(patch.dict(os.environ, environment, clear=False))
        stack.enter_context(patch("socket.create_connection", blocked))
        stack.enter_context(patch.object(socket.socket, "connect", blocked))
        stack.enter_context(patch.object(socket.socket, "connect_ex", blocked))
        from transformers import AutoTokenizer

        tokenizer = AutoTokenizer.from_pretrained(
            str(ROOT / MODEL_RELATIVE), local_files_only=True
        )
        encoded = tokenizer("offline synthetic smoke", add_special_tokens=True)
        if not encoded.get("input_ids"):
            raise RuntimeError("BLOCKED_RQ2_D3_R3_PREARM_RUNTIME")
        with np.load(ROOT / EMBEDDINGS_RELATIVE, allow_pickle=False) as archive:
            shape = tuple(int(value) for value in archive["embeddings"].shape)
            if shape != (62, 768):
                raise RuntimeError("BLOCKED_RQ2_D3_R3_PREARM_RUNTIME")
        content = CoreRoutingContentV1_1(
            current_query="Can you explain my current progress?",
            current_page="Overview",
            necessary_conversation_history=(),
        )
        with FrozenCapabilityPredictorCoreV1_1() as core:
            outputs = {method: core.predict(method, content) for method in ("B0", "B1", "P1")}
    if attempts["network"] or any(
        not row["predicted_capabilities"]
        or not set(row["predicted_capabilities"]) <= set(CAPABILITIES)
        for row in outputs.values()
    ):
        raise RuntimeError("BLOCKED_RQ2_D3_R3_PREARM_RUNTIME")
    report = {
        "schema_version": "rq2d3-r3-prearm-runtime-smoke-v1",
        "stage": "RQ2-D3-R3",
        "status": "PASS",
        "fixed_input_metadata": metadata,
        "pre_reservation_content_read_count": 0,
        "model_loaded": True,
        "tokenizer_loaded": True,
        "candidate_embedding_shape": list(shape),
        "b0_adapter_constructed": True,
        "b1_adapter_constructed": True,
        "p1_adapter_constructed": True,
        "synthetic_smoke_methods": ["B0", "B1", "P1"],
        "synthetic_smoke_output_valid": True,
        "local_files_only": True,
        "hf_hub_offline": True,
        "transformers_offline": True,
        "network_attempts": attempts["network"],
        "provider_calls": 0,
        "model_downloads": 0,
        "global_reservation_created": False,
    }
    report["prearm_runtime_smoke_receipt_sha256"] = sha256_bytes(canonical_json_bytes(report))
    return report


def prearm_runtime_contract_document_v1_1() -> dict[str, object]:
    return {
        "schema_version": "track-b-prearm-runtime-contract-v1-1",
        "status": "FROZEN",
        "before_global_reservation": True,
        "fixed_input_operation": "LSTAT_METADATA_ONLY",
        "fixed_input_content_reads": 0,
        "model": "sentence-transformers/all-mpnet-base-v2",
        "model_revision": "e8c3b32edf5434bc2275fc9bab85f82640a19130",
        "tokenizer_load_required": True,
        "candidate_shape": [62, 768],
        "adapters": ["B0", "B1", "P1"],
        "synthetic_smoke_required": True,
        "network_and_provider_forbidden": True,
    }
