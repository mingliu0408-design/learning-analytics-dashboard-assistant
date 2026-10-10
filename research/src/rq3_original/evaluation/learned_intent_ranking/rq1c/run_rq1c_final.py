"""RQ1-C1-only command line entry point for the sealed final evaluation."""

from __future__ import annotations

import argparse
import json
import os
from typing import Sequence

from . import ROOT
from .final_model_runner import run_final_evaluation_in_memory
from .sealed_access import run_authorised_one_shot


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Sealed RQ1-C one-shot final evaluation")
    parser.add_argument("--execute-final", action="store_true")
    parser.add_argument("--expected-harness-head", required=True)
    parser.add_argument("--authority-contract", required=True)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    lock, result = run_authorised_one_shot(
        execute_final=bool(args.execute_final),
        expected_harness_head=str(args.expected_harness_head),
        authority_contract_argument=str(args.authority_contract),
        environment=os.environ,
        evaluator=lambda records, runtime_bundle: run_final_evaluation_in_memory(
            records, runtime_bundle
        ),
        root=ROOT,
    )
    del result
    print(
        json.dumps(
            {
                "status": lock["state"],
                "result_relative_path": lock["result_relative_path"],
                "result_sha256": lock["result_sha256"],
            },
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
