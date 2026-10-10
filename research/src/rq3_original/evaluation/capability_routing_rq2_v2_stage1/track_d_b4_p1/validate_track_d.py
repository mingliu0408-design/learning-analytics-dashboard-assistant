"""Deterministic offline validation report for the Stage 1D harness."""

from __future__ import annotations

from copy import deepcopy
import json
from pathlib import Path
from typing import Any, Callable

from .b4 import (
    B4OfflineHarness,
    FEW_SHOT_PLACEHOLDER,
    PRIMARY_SEMANTIC_INPUT_PROFILE,
    build_b4_prompt,
    parse_b4_response,
)
from .mock_provider import DeterministicMockProvider
from .p1 import P1HybridRouter


PACKAGE_ROOT = Path(__file__).resolve().parent


def _fixture() -> dict[str, Any]:
    return json.loads(
        (PACKAGE_ROOT / "fixtures" / "toy_b4_fixture_v1.json").read_text(
            encoding="utf-8"
        )
    )


def run_validation() -> dict[str, Any]:
    fixture = _fixture()
    model_input = fixture["model_input"]
    valid_response = fixture["mock_responses"]["valid"]
    provider = DeterministicMockProvider(valid_response)
    b4 = B4OfflineHarness(provider)
    p1 = P1HybridRouter(b4)
    checks: dict[str, str] = {}
    failures: list[dict[str, str]] = []

    def check(name: str, function: Callable[[], None]) -> None:
        try:
            function()
            checks[name] = "PASS"
        except Exception as exc:
            checks[name] = "FAIL"
            failures.append({"check": name, "error": f"{type(exc).__name__}: {exc}"})

    def prompt_check() -> None:
        prompt = build_b4_prompt(model_input)
        forbidden = {"gold", "rag_context_state", "memory_context_state"}
        if FEW_SHOT_PLACEHOLDER not in prompt or any(
            value in prompt.casefold() for value in forbidden
        ):
            raise AssertionError("prompt placeholder or hidden-Gold boundary failed")

    def context_state_invariance_check() -> None:
        baseline = build_b4_prompt(model_input)
        variants = {
            "rag_context_state": "PROVIDED_IN_INPUT",
            "memory_context_state": "LONG_TERM_MEMORY_AVAILABLE",
        }
        for field, replacement in variants.items():
            variant = deepcopy(model_input)
            variant[field] = replacement
            if build_b4_prompt(variant) != baseline:
                raise AssertionError(f"prompt changed with compatibility-only {field}")

    def parser_check() -> None:
        if not parse_b4_response(valid_response).planning_required:
            raise AssertionError("valid structured response did not parse")

    def confident_check() -> None:
        prediction = p1.predict(
            case_id="VALIDATE-CONFIDENT",
            model_input=model_input,
            base_probabilities={
                "rag_required": 0.9,
                "memory_required": 0.1,
                "planning_required": 0.9,
            },
            thresholds={field: 0.5 for field in (
                "rag_required", "memory_required", "planning_required"
            )},
            uncertainty_margins={field: 0.05 for field in (
                "rag_required", "memory_required", "planning_required"
            )},
        ).to_dict()
        if prediction["metadata"]["fallback_triggered"] or provider.call_count != 0:
            raise AssertionError("confident route called B4")

    def fallback_check() -> None:
        prediction = p1.predict(
            case_id="VALIDATE-FALLBACK",
            model_input=model_input,
            base_probabilities={
                "rag_required": 0.51,
                "memory_required": 0.1,
                "planning_required": 0.9,
            },
            thresholds={field: 0.5 for field in (
                "rag_required", "memory_required", "planning_required"
            )},
            uncertainty_margins={field: 0.05 for field in (
                "rag_required", "memory_required", "planning_required"
            )},
        ).to_dict()
        if not prediction["metadata"]["fallback_triggered"] or provider.call_count != 1:
            raise AssertionError("uncertain route did not make exactly one B4 call")

    def external_call_check() -> None:
        if provider.network_call_count != 0 or provider.real_provider_call_count != 0:
            raise AssertionError("mock provider reported external activity")

    check("canonical_prompt_and_placeholder", prompt_check)
    check("context_state_prompt_invariance", context_state_invariance_check)
    check("strict_response_parser", parser_check)
    check("confident_path_zero_provider_calls", confident_check)
    check("uncertain_path_one_mock_call", fallback_check)
    check("zero_network_and_real_provider_calls", external_call_check)
    return {
        "schema_version": "rq2-v2-stage1d-r1-validation-report-v1",
        "input_profile": PRIMARY_SEMANTIC_INPUT_PROFILE,
        "status": "PASS" if not failures else "FAIL",
        "check_count": len(checks),
        "pass_count": sum(value == "PASS" for value in checks.values()),
        "failure_count": len(failures),
        "checks": checks,
        "failures": failures,
        "confident_path_mock_provider_calls": 0,
        "fallback_path_mock_provider_calls": provider.call_count,
        "total_mock_provider_calls": provider.call_count,
        "network_calls": provider.network_call_count,
        "real_external_provider_calls": provider.real_provider_call_count,
        "paid_provider_calls": 0,
    }


def main() -> int:
    report = run_validation()
    print(json.dumps(report, indent=2, sort_keys=True))
    return 0 if report["status"] == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
