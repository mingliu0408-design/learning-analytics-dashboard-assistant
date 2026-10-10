"""Minimal local canonical-case JSONL to canonical-prediction JSONL runner."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

from . import B0_MODEL_ID, B1_MODEL_ID
from .b0_rule_router import B0RuleRouter, DEFAULT_CONFIG_PATH
from .b1_legacy_intent_adapter import B1LegacyIntentRouter, DEFAULT_MAPPING_PATH


class RunnerError(RuntimeError):
    """Raised before output is written when local runner input is invalid."""


def _load_jsonl(path: Path) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except OSError as exc:
        raise RunnerError(f"cannot read input JSONL: {path}") from exc
    for line_number, line in enumerate(lines, start=1):
        if not line.strip():
            continue
        try:
            value = json.loads(line)
        except json.JSONDecodeError as exc:
            raise RunnerError(f"invalid JSON at {path}:{line_number}") from exc
        if not isinstance(value, dict):
            raise RunnerError(f"JSONL row must be an object at {path}:{line_number}")
        rows.append(value)
    if not rows:
        raise RunnerError("input JSONL contains no cases")
    case_ids = [str(row.get("case_id") or "") for row in rows]
    if any(not value for value in case_ids) or len(case_ids) != len(set(case_ids)):
        raise RunnerError("input case IDs must be non-empty and unique")
    return rows


def _router(
    model_id: str,
    *,
    b0_config: Path,
    b1_mapping: Path,
) -> Any:
    if model_id == B0_MODEL_ID:
        return B0RuleRouter(b0_config)
    if model_id == B1_MODEL_ID:
        # Strict is intentional.  The shipped UNFROZEN template fails here
        # until a later authorised development-only mapping freeze exists.
        return B1LegacyIntentRouter(b1_mapping)
    raise RunnerError(f"unsupported Track B model_id: {model_id}")


def run_jsonl(
    input_path: str | Path,
    output_path: str | Path,
    *,
    model_id: str,
    b0_config: str | Path = DEFAULT_CONFIG_PATH,
    b1_mapping: str | Path = DEFAULT_MAPPING_PATH,
) -> dict[str, Any]:
    source = Path(input_path)
    destination = Path(output_path)
    if source.resolve() == destination.resolve():
        raise RunnerError("input and output paths must differ")
    if destination.exists():
        raise FileExistsError(f"refusing to overwrite prediction JSONL: {destination}")
    cases = _load_jsonl(source)
    router = _router(
        model_id,
        b0_config=Path(b0_config),
        b1_mapping=Path(b1_mapping),
    )
    # Compute and schema-validate every prediction before creating the output.
    predictions = [router.predict(case).to_dict() for case in cases]
    payload = "".join(
        json.dumps(row, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
        + "\n"
        for row in predictions
    )
    try:
        with destination.open("x", encoding="utf-8", newline="\n") as handle:
            handle.write(payload)
    except OSError as exc:
        raise RunnerError(f"cannot create output JSONL: {destination}") from exc
    return {
        "status": "PASS",
        "model_id": model_id,
        "input_case_count": len(cases),
        "prediction_count": len(predictions),
        "provider_call_count": 0,
        "network_access": False,
        "training_performed": False,
        "output": str(destination),
    }


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Run one local RQ2-V2 Stage 1 Track B baseline."
    )
    parser.add_argument("--input", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--model", choices=(B0_MODEL_ID, B1_MODEL_ID), required=True)
    parser.add_argument("--b0-config", type=Path, default=DEFAULT_CONFIG_PATH)
    parser.add_argument("--b1-mapping", type=Path, default=DEFAULT_MAPPING_PATH)
    args = parser.parse_args()
    report = run_jsonl(
        args.input,
        args.output,
        model_id=args.model,
        b0_config=args.b0_config,
        b1_mapping=args.b1_mapping,
    )
    print(json.dumps(report, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
