"""Safe CPU-only verification and loading of the five frozen V0 checkpoints."""

from __future__ import annotations

import hashlib
from pathlib import Path
from typing import Any

import torch

from evaluation.learned_intent_ranking.lr4b_dev.model import build_m64_model

from . import REPRESENTATIVE_SEED, ROOT, V0_SEEDS


class CheckpointContractError(RuntimeError):
    """Fail-closed frozen-checkpoint mismatch."""


CHECKPOINT_SPECS: dict[int, dict[str, Any]] = {
    20260813: {
        "file_sha256": "f56d0be9bef9fc455c35f4620f12070ed0cd4e8387da5b08c47b9c5efa97adc0",
        "tensor_sha256": "abcfad66bc1cc5cd4d189b0278f55960287a78a65e2b11afec46a0a7bee38b77",
        "best_epoch": 8,
    },
    20260814: {
        "file_sha256": "ff85bf2caf70f9e7737b252c6b91181a797ebe30fe566468776e4bfb957f7bc3",
        "tensor_sha256": "0a1f55b4142f7c111a7ec0b72c4371622ec926502a2977a25daaf1384ad408c0",
        "best_epoch": 7,
    },
    20260815: {
        "file_sha256": "73cd583e3a036792322bf6dcbf6968a56daede5057b3ec6df1bf5eb41c821b03",
        "tensor_sha256": "54ba31fdb5019f33b9815693357910f272fa44ac8031a675064e56a1aa159317",
        "best_epoch": 8,
    },
    20260816: {
        "file_sha256": "9aa5ebb450aa417f927f120fb2ad0dae030d73e31c146a01a922657dcf83bbbe",
        "tensor_sha256": "57e51ffecde6c3c643cc085eb57f9bc9c39302188d2227230d9f6402b6a29f6b",
        "best_epoch": 16,
    },
    20260817: {
        "file_sha256": "cbc5b3788a04d990eb5391806694376bcf36479aebd3bfd9230a6adbc9f06644",
        "tensor_sha256": "6f5e98f2ed308277fe944263456aeb747a36804ed7834c0c44d22e0aef6f8531",
        "best_epoch": 4,
    },
}


def checkpoint_path(seed: int, root: Path = ROOT) -> Path:
    if seed not in CHECKPOINT_SPECS:
        raise CheckpointContractError("checkpoint seed is outside the frozen V0 set")
    return (
        root
        / "evaluation/learned_intent_ranking/lr4b_dev/checkpoints"
        / f"rq1b_m64_v0_seed_{seed}_best_v1.pt"
    )


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def parameter_tensor_hash(state_dict: dict[str, torch.Tensor]) -> str:
    digest = hashlib.sha256()
    for name in sorted(state_dict):
        tensor = state_dict[name].detach().cpu().contiguous()
        digest.update(name.encode("utf-8"))
        digest.update(str(tensor.dtype).encode("ascii"))
        digest.update(str(tuple(tensor.shape)).encode("ascii"))
        digest.update(tensor.numpy().tobytes(order="C"))
    return digest.hexdigest()


def _verify_one(seed: int, root: Path = ROOT) -> tuple[dict[str, Any], dict[str, torch.Tensor]]:
    spec = CHECKPOINT_SPECS[seed]
    path = checkpoint_path(seed, root)
    if not path.is_file() or path.is_symlink():
        raise CheckpointContractError("checkpoint is missing or not a regular non-symlink file")
    actual_file_sha = _sha256_file(path)
    if actual_file_sha != spec["file_sha256"]:
        raise CheckpointContractError("checkpoint file SHA-256 mismatch")
    payload = torch.load(path, map_location="cpu", weights_only=True)
    expected_top = {
        "schema_version",
        "scenario",
        "training_seed",
        "best_epoch",
        "architecture",
        "state_dict",
        "final_gold_used",
    }
    if not isinstance(payload, dict) or set(payload) != expected_top:
        raise CheckpointContractError("checkpoint top-level schema mismatch")
    if (
        payload["schema_version"] != "rq1b-m64-development-checkpoint-v1"
        or payload["scenario"] != "V0"
        or payload["training_seed"] != seed
        or payload["best_epoch"] != spec["best_epoch"]
        or payload["architecture"] != "M64"
        or payload["final_gold_used"] is not False
    ):
        raise CheckpointContractError("checkpoint governed metadata mismatch")
    state_dict = payload["state_dict"]
    expected_state = build_m64_model().state_dict()
    if not isinstance(state_dict, dict) or set(state_dict) != set(expected_state):
        raise CheckpointContractError("checkpoint state_dict key set mismatch")
    for name, value in state_dict.items():
        if (
            not isinstance(value, torch.Tensor)
            or value.device.type != "cpu"
            or tuple(value.shape) != tuple(expected_state[name].shape)
            or value.dtype != expected_state[name].dtype
        ):
            raise CheckpointContractError("checkpoint tensor shape, dtype, or device mismatch")
    tensor_sha = parameter_tensor_hash(state_dict)
    if tensor_sha != spec["tensor_sha256"]:
        raise CheckpointContractError("checkpoint tensor SHA-256 mismatch")
    report = {
        "seed": seed,
        "relative_path": str(path.relative_to(root)),
        "regular_file": True,
        "non_symlink": True,
        "file_sha256": actual_file_sha,
        "file_sha256_match": True,
        "tensor_sha256": tensor_sha,
        "tensor_sha256_match": True,
        "schema_version": payload["schema_version"],
        "scenario": payload["scenario"],
        "best_epoch": payload["best_epoch"],
        "architecture": payload["architecture"],
        "state_dict_key_count": len(state_dict),
        "state_dict_keys_and_shapes_match": True,
        "weights_only": True,
        "map_location": "cpu",
        "pass": True,
    }
    return report, state_dict


def verify_all_checkpoints(root: Path = ROOT) -> dict[str, Any]:
    rows = [_verify_one(seed, root)[0] for seed in V0_SEEDS]
    representative = next(row for row in rows if row["seed"] == REPRESENTATIVE_SEED)
    return {
        "schema_version": "rq1c-checkpoint-preflight-v1",
        "stage": "RQ1-C0-R1",
        "status": "PASS",
        "checkpoint_count": len(rows),
        "all_checkpoints_verified": True,
        "representative_seed": REPRESENTATIVE_SEED,
        "representative_checkpoint_sha256": representative["file_sha256"],
        "representative_tensor_sha256": representative["tensor_sha256"],
        "checkpoints": rows,
        "checkpoint_modified": False,
        "model_training_performed": False,
        "raw_final_gold_accessed": False,
    }


def load_verified_m64(seed: int, root: Path = ROOT) -> torch.nn.Module:
    _report, state_dict = _verify_one(seed, root)
    model = build_m64_model().cpu()
    model.load_state_dict(state_dict, strict=True)
    model.eval()
    for parameter in model.parameters():
        parameter.requires_grad_(False)
    return model
