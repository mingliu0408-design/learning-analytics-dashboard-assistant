#!/usr/bin/env python3
"""Versioned, fail-closed runner for a future authorized I0-R1 route package.

I0-R1 does not execute this runner. A future invocation must provide every
explicit gate, an untouched extracted package, and a new external output
directory. The runner is serial, durable, non-resumable, and stops a package
at the first non-retryable or terminal integrity error.
"""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
from decimal import Decimal
import hashlib
import json
import os
from pathlib import Path
import re
import tempfile
import time
from typing import Any, Callable, Mapping, MutableMapping, Sequence

try:
    from .route_package_validator_v1 import (
        AUTHORIZATION_ENVIRONMENT_VALUE,
        AUTHORIZATION_ENVIRONMENT_VARIABLE,
        AUTHORIZATION_FIELDS,
        AUTHORIZATION_SCOPE,
        EXPECTED_COMPONENT_TOKENS,
        MODEL,
        canonical_bytes,
        parse_requests,
        validate_package_dir,
    )
except ImportError:  # pragma: no cover - execution from an extracted package
    from validate_route_package_v1 import (  # type: ignore
        AUTHORIZATION_ENVIRONMENT_VALUE,
        AUTHORIZATION_ENVIRONMENT_VARIABLE,
        AUTHORIZATION_FIELDS,
        AUTHORIZATION_SCOPE,
        EXPECTED_COMPONENT_TOKENS,
        MODEL,
        canonical_bytes,
        parse_requests,
        validate_package_dir,
    )


RUNNER_VERSION = "c4-real-p3-route-execution-runner-v2"
PREFLIGHT_NAME = "route_execution_preflight_receipt_v1.json"
ATTEMPTS_NAME = "route_attempt_records_v1.jsonl"
TERMINALS_NAME = "route_terminal_results_v1.jsonl"
ERRORS_NAME = "route_error_registry_v1.jsonl"
STATUS_NAME = "route_execution_status_v1.json"
USAGE_NAME = "route_usage_and_cost_v1.json"
REPORT_NAME = "ROUTE_EXECUTION_REPORT.md"
RETRYABLE_ERRORS = {"INVALID_JSON", "STRICT_SCHEMA_VALIDATION_FAILED"}
ERROR_CLASSES = {
    "AUTHENTICATION_ERROR",
    "PERMISSION_ERROR",
    "REQUEST_CONFIGURATION_ERROR",
    "MODEL_OR_ENDPOINT_NOT_FOUND",
    "RATE_LIMIT_ERROR",
    "TRANSPORT_ERROR",
    "TIMEOUT",
    "PROVIDER_REFUSAL",
    "INVALID_JSON",
    "STRICT_SCHEMA_VALIDATION_FAILED",
    "RETURNED_MODEL_MISMATCH",
    "UNEXPECTED_PROVIDER_RESPONSE",
}
REDACTIONS = (
    (re.compile(r"sk-(?:proj-)?[A-Za-z0-9_-]{8,}", re.IGNORECASE), "[REDACTED_API_KEY]"),
    (re.compile(r"Bearer\s+[A-Za-z0-9._~+/-]{8,}", re.IGNORECASE), "Bearer [REDACTED]"),
    (re.compile(r"(?i)(authorization|api[_ -]?key)\s*[:=]\s*[^\s,;]+"), r"\1=[REDACTED]"),
)

Transport = Callable[[dict[str, Any]], Any]
TransportFactory = Callable[[], Transport]
NowFunction = Callable[[], str]
MonotonicFunction = Callable[[], float]
SleepFunction = Callable[[float], None]


class ExecutionBoundaryError(RuntimeError):
    """Raised before a provider call when a strict execution gate fails."""


def require(condition: bool, message: str) -> None:
    if not condition:
        raise ExecutionBoundaryError(message)


def sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def utc_now() -> str:
    return (
        datetime.now(timezone.utc)
        .isoformat(timespec="milliseconds")
        .replace("+00:00", "Z")
    )


def load_json(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as error:
        raise ExecutionBoundaryError(f"Invalid JSON object: {path.name}") from error
    require(isinstance(value, dict), f"Expected JSON object: {path.name}")
    return value


def load_jsonl(path: Path) -> list[dict[str, Any]]:
    rows = []
    if not path.exists():
        return rows
    for number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        if not line.strip():
            continue
        try:
            value = json.loads(line)
        except json.JSONDecodeError as error:
            raise ExecutionBoundaryError(f"Corrupt output journal {path.name}:{number}") from error
        require(isinstance(value, dict), f"Output journal row is not an object: {path.name}:{number}")
        rows.append(value)
    return rows


def _fsync_directory(path: Path) -> None:
    descriptor = os.open(path, os.O_RDONLY)
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def atomic_write_bytes(path: Path, data: bytes) -> None:
    descriptor, temporary_name = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    temporary = Path(temporary_name)
    try:
        with os.fdopen(descriptor, "wb", buffering=0) as handle:
            handle.write(data)
            os.fsync(handle.fileno())
        os.replace(temporary, path)
        _fsync_directory(path.parent)
    finally:
        if temporary.exists():
            temporary.unlink()


def atomic_write_json(path: Path, value: Mapping[str, Any]) -> None:
    data = (
        json.dumps(dict(value), ensure_ascii=False, indent=2, sort_keys=True) + "\n"
    ).encode("utf-8")
    atomic_write_bytes(path, data)


def append_fsync(path: Path, value: Mapping[str, Any]) -> None:
    encoded = canonical_bytes(dict(value)) + b"\n"
    with path.open("ab", buffering=0) as handle:
        handle.write(encoded)
        handle.flush()
        os.fsync(handle.fileno())


def create_empty_exclusive(path: Path) -> None:
    with path.open("xb", buffering=0) as handle:
        handle.flush()
        os.fsync(handle.fileno())


def create_output_directory(path: Path) -> Path:
    target = path.absolute()
    require(target.parent.is_dir(), f"Output parent does not exist: {target.parent}")
    require(not target.exists(), f"Output directory already exists: {target}")
    target.mkdir(mode=0o700, parents=False, exist_ok=False)
    _fsync_directory(target.parent)
    return target


def redact(value: str) -> str:
    result = value
    for pattern, replacement in REDACTIONS:
        result = pattern.sub(replacement, result)
    return result[:2000]


def _attr(value: Any, name: str, default: Any = None) -> Any:
    if isinstance(value, Mapping):
        return value.get(name, default)
    return getattr(value, name, default)


def classify_provider_exception(error: BaseException) -> str:
    name = type(error).__name__.lower()
    status = _attr(error, "status_code")
    if "authentication" in name or status == 401:
        return "AUTHENTICATION_ERROR"
    if "permission" in name or status == 403:
        return "PERMISSION_ERROR"
    if "notfound" in name or "not_found" in name or status == 404:
        return "MODEL_OR_ENDPOINT_NOT_FOUND"
    if "ratelimit" in name or "rate_limit" in name or status == 429:
        return "RATE_LIMIT_ERROR"
    if "timeout" in name or status == 408:
        return "TIMEOUT"
    if "badrequest" in name or "unprocessable" in name or status in {400, 409, 422}:
        return "REQUEST_CONFIGURATION_ERROR"
    if "connection" in name or "transport" in name or (
        isinstance(status, int) and status >= 500
    ):
        return "TRANSPORT_ERROR"
    return "UNEXPECTED_PROVIDER_RESPONSE"


def sanitized_provider_error(error: BaseException) -> dict[str, Any]:
    body = _attr(error, "body")
    body_error = body.get("error") if isinstance(body, Mapping) else None
    if not isinstance(body_error, Mapping):
        body_error = {}
    code = _attr(error, "code", body_error.get("code"))
    param = _attr(error, "param", body_error.get("param"))
    return {
        "exception_type": type(error).__name__,
        "status_code": _attr(error, "status_code"),
        "code": None if code is None else redact(str(code)),
        "param": None if param is None else redact(str(param)),
        "message": redact(str(error)),
        "headers_recorded": False,
        "environment_recorded": False,
    }


def validate_authorization(
    authorization: Mapping[str, Any], *, plan: Mapping[str, Any], component: str
) -> None:
    require(
        set(authorization) == set(AUTHORIZATION_FIELDS),
        "Authorization record strict fields mismatch",
    )
    require(authorization["authorization_scope"] == AUTHORIZATION_SCOPE, "Authorization scope mismatch")
    require(authorization["status"] == "AUTHORIZED", "Authorization status is not AUTHORIZED")
    require(authorization["package_id"] == plan["package_id"], "Authorization package mismatch")
    require(authorization["component"] == component, "Authorization component mismatch")
    require(authorization["logical_call_count"] == plan["logical_call_count"], "Authorization logical-call count mismatch")
    require(
        authorization["maximum_physical_attempt_count"]
        == plan["maximum_physical_attempt_count"],
        "Authorization physical-attempt ceiling mismatch",
    )
    for field in ("authorization_id", "authorized_by", "authorized_at"):
        require(isinstance(authorization[field], str) and bool(authorization[field].strip()), f"Authorization field is empty: {field}")


def strict_parse(raw_text: str, schema: Mapping[str, Any]) -> tuple[dict[str, bool] | None, str]:
    try:
        value = json.loads(raw_text)
    except json.JSONDecodeError:
        return None, "INVALID_JSON"
    if not isinstance(value, dict):
        return None, "STRICT_SCHEMA_VALIDATION_FAILED"
    required = schema.get("required")
    properties = schema.get("properties")
    if not isinstance(required, list) or not isinstance(properties, Mapping):
        return None, "STRICT_SCHEMA_VALIDATION_FAILED"
    expected = set(required)
    if set(value) != expected or set(properties) != expected:
        return None, "STRICT_SCHEMA_VALIDATION_FAILED"
    if schema.get("additionalProperties") is not False:
        return None, "STRICT_SCHEMA_VALIDATION_FAILED"
    if any(properties[field] != {"type": "boolean"} for field in expected):
        return None, "STRICT_SCHEMA_VALIDATION_FAILED"
    if any(type(value[field]) is not bool for field in expected):
        return None, "STRICT_SCHEMA_VALIDATION_FAILED"
    return {field: value[field] for field in required}, "PASS"


def build_payload(
    *,
    plan: Mapping[str, Any],
    prompt: str,
    schema: Mapping[str, Any],
    examples: Sequence[Mapping[str, Any]],
    request: Mapping[str, Any],
) -> dict[str, Any]:
    messages: list[dict[str, str]] = [{"role": "system", "content": prompt}]
    for example in examples:
        require(set(example) >= {"input", "output"}, "Few-shot example fields are missing")
        messages.append(
            {"role": "user", "content": canonical_bytes(example["input"]).decode("utf-8")}
        )
        messages.append(
            {"role": "assistant", "content": canonical_bytes(example["output"]).decode("utf-8")}
        )
    messages.append(
        {
            "role": "user",
            "content": canonical_bytes(request["semantic_input"]).decode("utf-8"),
        }
    )
    return {
        "model": plan["model"],
        "messages": messages,
        "temperature": plan["temperature"],
        "max_tokens": plan["max_output_tokens"],
        "stream": False,
        "response_format": {
            "type": "json_schema",
            "json_schema": {
                "name": plan["response_schema_name"],
                "strict": True,
                "schema": dict(schema),
            },
        },
    }


def _usage(response: Any) -> dict[str, int | None]:
    usage = _attr(response, "usage")
    if usage is None:
        return {
            "input_tokens": None,
            "cached_input_tokens": None,
            "output_tokens": None,
            "total_tokens": None,
        }
    details = _attr(usage, "prompt_tokens_details")
    return {
        "input_tokens": _attr(usage, "prompt_tokens"),
        "cached_input_tokens": _attr(details, "cached_tokens") if details is not None else None,
        "output_tokens": _attr(usage, "completion_tokens"),
        "total_tokens": _attr(usage, "total_tokens"),
    }


def inspect_response(response: Any, schema: Mapping[str, Any]) -> dict[str, Any]:
    returned_model = _attr(response, "model")
    response_id = _attr(response, "id")
    fingerprint = _attr(response, "system_fingerprint")
    choices = _attr(response, "choices")
    base = {
        "returned_model": returned_model,
        "response_id": response_id,
        "system_fingerprint": fingerprint,
        "finish_reason": None,
        "raw_response_content": None,
        "provider_refusal": None,
        "parsed_strict_output": None,
        "strict_schema_status": "NOT_EVALUATED",
        **_usage(response),
    }
    if not isinstance(choices, Sequence) or isinstance(choices, (str, bytes)) or len(choices) != 1:
        return {**base, "outcome": "UNEXPECTED_PROVIDER_RESPONSE"}
    choice = choices[0]
    message = _attr(choice, "message")
    base["finish_reason"] = _attr(choice, "finish_reason")
    if message is None:
        return {**base, "outcome": "UNEXPECTED_PROVIDER_RESPONSE"}
    raw_text = _attr(message, "content")
    refusal = _attr(message, "refusal")
    base["raw_response_content"] = raw_text
    base["provider_refusal"] = refusal
    if returned_model != MODEL:
        return {**base, "outcome": "RETURNED_MODEL_MISMATCH"}
    if isinstance(refusal, str) and refusal.strip():
        return {**base, "outcome": "PROVIDER_REFUSAL"}
    if not isinstance(raw_text, str):
        return {**base, "outcome": "UNEXPECTED_PROVIDER_RESPONSE"}
    parsed, schema_status = strict_parse(raw_text, schema)
    base["parsed_strict_output"] = parsed
    base["strict_schema_status"] = schema_status
    return {**base, "outcome": "VALID" if parsed is not None else schema_status}


def _attempt_base(
    *,
    event: str,
    component: str,
    package_id: str,
    request: Mapping[str, Any],
    logical_order: int,
    attempt_number: int,
    payload_sha256: str,
    reserved_at: str,
) -> dict[str, Any]:
    return {
        "schema_version": "c4-real-route-attempt-record-v1",
        "event": event,
        "route_component": component,
        "package_id": package_id,
        "scenario_id": request["scenario_id"],
        "semantic_input_sha256": request["semantic_input_sha256"],
        "logical_order": logical_order,
        "attempt_number": attempt_number,
        "provider_payload_sha256": payload_sha256,
        "requested_model": MODEL,
        "returned_model": None,
        "response_id": None,
        "system_fingerprint": None,
        "finish_reason": None,
        "raw_response_content": None,
        "provider_refusal": None,
        "parsed_strict_output": None,
        "strict_schema_status": "PENDING",
        "input_tokens": None,
        "cached_input_tokens": None,
        "output_tokens": None,
        "total_tokens": None,
        "reserved_at": reserved_at,
        "started_at": None,
        "ended_at": None,
        "latency_seconds": None,
        "initial_start_interval_seconds": None,
        "sanitized_provider_error": None,
        "outcome": "PENDING",
        "terminal": False,
    }


def _status(
    *,
    state: str,
    component: str,
    package_id: str,
    logical_requests: int,
    logical_completed: int,
    logical_failed: int,
    physical_attempts: int,
    retry_count: int,
    provider_calls: int,
    last_scenario_id: str | None,
    stop_reason: str | None,
    now: NowFunction,
) -> dict[str, Any]:
    return {
        "schema_version": "c4-real-route-execution-status-v1",
        "runner_version": RUNNER_VERSION,
        "state": state,
        "component": component,
        "package_id": package_id,
        "logical_requests": logical_requests,
        "logical_completed": logical_completed,
        "logical_failed": logical_failed,
        "physical_attempts": physical_attempts,
        "retry_count": retry_count,
        "provider_calls": provider_calls,
        "last_scenario_id": last_scenario_id,
        "stop_reason": stop_reason,
        "automatic_resume_permitted": False,
        "continuation_requires_new_direct_user_authorization": True,
        "updated_at": now(),
    }


def _pace_initial_request(
    *,
    previous_start: float | None,
    minimum_interval: float,
    monotonic: MonotonicFunction,
    sleep: SleepFunction,
) -> tuple[float, float | None]:
    if previous_start is not None:
        elapsed = monotonic() - previous_start
        if elapsed < minimum_interval:
            sleep(minimum_interval - elapsed)
    started = monotonic()
    interval = None if previous_start is None else started - previous_start
    require(
        interval is None or interval + 1e-9 >= minimum_interval,
        "Initial logical-request starts are less than 2.0 seconds apart",
    )
    return started, interval


def _error_event(
    *,
    component: str,
    package_id: str,
    request: Mapping[str, Any],
    logical_order: int,
    attempt_number: int,
    payload_sha256: str,
    error_class: str,
    terminal: bool,
    provider_error: Mapping[str, Any] | None,
    now: NowFunction,
) -> dict[str, Any]:
    require(error_class in ERROR_CLASSES, f"Unknown error class: {error_class}")
    return {
        "schema_version": "c4-real-route-error-registry-v1",
        "route_component": component,
        "package_id": package_id,
        "scenario_id": request["scenario_id"],
        "semantic_input_sha256": request["semantic_input_sha256"],
        "logical_order": logical_order,
        "attempt_number": attempt_number,
        "provider_payload_sha256": payload_sha256,
        "error_class": error_class,
        "sanitized_provider_error": None if provider_error is None else dict(provider_error),
        "terminal": terminal,
        "recorded_at": now(),
    }


def _terminal_event(
    *,
    component: str,
    package_id: str,
    request: Mapping[str, Any],
    logical_order: int,
    attempt_number: int,
    payload_sha256: str,
    outcome: str,
    parsed_output: Mapping[str, bool] | None,
    raw_content: str | None,
    returned_model: str | None,
    now: NowFunction,
) -> dict[str, Any]:
    return {
        "schema_version": "c4-real-route-terminal-result-v1",
        "event": "TERMINAL_SUCCESS" if outcome == "VALID" else "TERMINAL_ERROR",
        "route_component": component,
        "package_id": package_id,
        "scenario_id": request["scenario_id"],
        "semantic_input_sha256": request["semantic_input_sha256"],
        "logical_order": logical_order,
        "physical_attempts_for_logical_request": attempt_number,
        "provider_payload_sha256": payload_sha256,
        "returned_model": returned_model,
        "raw_response_content": raw_content,
        "output": None if parsed_output is None else dict(parsed_output),
        "terminal_status": "VALID_OUTPUT" if outcome == "VALID" else outcome,
        "recorded_at": now(),
    }


def _output_hashes(output_dir: Path, names: Sequence[str]) -> dict[str, str]:
    return {name: sha256((output_dir / name).read_bytes()) for name in names}


def _usage_report(output_dir: Path, *, component: str, package_id: str) -> dict[str, Any]:
    completed = [row for row in load_jsonl(output_dir / ATTEMPTS_NAME) if row.get("event") == "ATTEMPT_COMPLETED"]
    terminals = load_jsonl(output_dir / TERMINALS_NAME)
    usage_complete = all(
        type(row.get(field)) is int
        for row in completed
        for field in ("input_tokens", "output_tokens", "total_tokens")
    )
    input_tokens = sum(int(row["input_tokens"]) for row in completed if type(row.get("input_tokens")) is int)
    output_tokens = sum(int(row["output_tokens"]) for row in completed if type(row.get("output_tokens")) is int)
    total_tokens = sum(int(row["total_tokens"]) for row in completed if type(row.get("total_tokens")) is int)
    cached_available = all(type(row.get("cached_input_tokens")) is int for row in completed)
    cached_tokens = (
        sum(int(row["cached_input_tokens"]) for row in completed)
        if cached_available
        else None
    )
    approximate_cost: str | None = None
    cost_assumption: str
    if usage_complete:
        cached_for_cost = cached_tokens if cached_tokens is not None else 0
        regular_input = max(0, input_tokens - cached_for_cost)
        cost = (
            Decimal(regular_input) * Decimal("0.15")
            + Decimal(cached_for_cost) * Decimal("0.075")
            + Decimal(output_tokens) * Decimal("0.60")
        ) / Decimal(1_000_000)
        approximate_cost = format(cost.quantize(Decimal("0.00000001")), "f")
        cost_assumption = (
            "REPORTED_CACHED_INPUT_USED"
            if cached_tokens is not None
            else "CACHED_INPUT_DETAIL_UNAVAILABLE_ASSUMED_ZERO"
        )
    else:
        cost_assumption = "USAGE_INCOMPLETE_COST_UNAVAILABLE"
    return {
        "schema_version": "c4-real-route-usage-and-cost-v1",
        "status": "COMPLETE_VALID_OUTPUTS",
        "component": component,
        "package_id": package_id,
        "logical_requests": len(terminals),
        "physical_attempts": len(completed),
        "retry_count": sum(row.get("attempt_number") == 2 for row in completed),
        "valid_outputs": sum(row.get("event") == "TERMINAL_SUCCESS" for row in terminals),
        "input_tokens": input_tokens,
        "cached_input_tokens": cached_tokens,
        "cached_input_tokens_available_for_all_attempts": cached_available,
        "output_tokens": output_tokens,
        "total_tokens": total_tokens,
        "usage_complete": usage_complete,
        "approximate_cost_usd": approximate_cost,
        "cost_assumption": cost_assumption,
        "pricing_usd_per_1m_tokens": {
            "input": 0.15,
            "cached_input": 0.075,
            "output": 0.60,
            "status": "APPROXIMATE_ONLY_CURRENT_AT_I0_R1_FREEZE",
        },
        "requested_model": MODEL,
        "returned_model_identity_required": MODEL,
        "output_hashes_before_usage_report": _output_hashes(
            output_dir, [PREFLIGHT_NAME, ATTEMPTS_NAME, TERMINALS_NAME, ERRORS_NAME]
        ),
        "routing_accuracy_calculated": False,
        "expected_labels_accessed": False,
    }


def _markdown_report(usage: Mapping[str, Any]) -> bytes:
    lines = [
        "# C4 Real P3 Route Execution Report",
        "",
        f"- Status: `{usage['status']}`",
        f"- Component/package: `{usage['component']}` / `{usage['package_id']}`",
        f"- Model: `{usage['requested_model']}`",
        f"- Logical requests: {usage['logical_requests']}",
        f"- Physical attempts: {usage['physical_attempts']}",
        f"- Retries: {usage['retry_count']}",
        f"- Valid outputs: {usage['valid_outputs']}",
        f"- Input tokens: {usage['input_tokens']}",
        f"- Cached-input tokens: {usage['cached_input_tokens']}",
        f"- Output tokens: {usage['output_tokens']}",
        f"- Total tokens: {usage['total_tokens']}",
        f"- Approximate cost USD: {usage['approximate_cost_usd']}",
        f"- Cost assumption: `{usage['cost_assumption']}`",
        "- Routing accuracy or expected-label comparison: not performed",
        "",
        "## Durable output hashes",
        "",
    ]
    for name, digest in usage["output_hashes_before_usage_report"].items():
        lines.append(f"- `{name}`: `{digest}`")
    lines.append("")
    return ("\n".join(lines)).encode("utf-8")


def execute_package(
    *,
    package_dir: Path,
    authorization_record: Path,
    output_dir: Path,
    component: str,
    transport_factory: TransportFactory,
    environment: Mapping[str, str] | None = None,
    now: NowFunction = utc_now,
    monotonic: MonotonicFunction = time.monotonic,
    sleep: SleepFunction = time.sleep,
) -> dict[str, Any]:
    """Execute only after all R1 gates; tests inject a mocked transport factory."""

    env = os.environ if environment is None else environment
    package_root = package_dir.resolve()
    output_candidate = output_dir.expanduser().resolve(strict=False)
    require(
        output_candidate != package_root
        and package_root not in output_candidate.parents,
        "Output directory must be external to the extracted package",
    )
    package_validation = validate_package_dir(
        package_root, expected_component=component
    )
    plan = load_json(package_root / "EXECUTION_PLAN.json")
    contract = load_json(package_root / "EXECUTION_CONTRACT.json")
    authorization = load_json(authorization_record.resolve())
    validate_authorization(authorization, plan=plan, component=component)
    require(
        env.get(AUTHORIZATION_ENVIRONMENT_VARIABLE)
        == AUTHORIZATION_ENVIRONMENT_VALUE,
        "Exact R1 execution environment gate is absent",
    )
    require(bool(env.get("OPENAI_API_KEY")), "OPENAI_API_KEY is absent")
    require(plan["max_output_tokens"] == EXPECTED_COMPONENT_TOKENS[component], "Component token limit mismatch")
    require(contract["automatic_resume_permitted"] is False, "Automatic resume is forbidden")

    requests_data = (package_root / "requests.jsonl").read_bytes()
    requests = parse_requests(requests_data)
    prompt = (package_root / "prompt.txt").read_text(encoding="utf-8")
    schema = load_json(package_root / "schema.json")
    examples_document = load_json(package_root / "few_shot_examples.json")
    examples = examples_document.get("few_shot_examples")
    require(isinstance(examples, list), "Few-shot examples are missing")

    output_root = create_output_directory(output_candidate)
    attempts_path = output_root / ATTEMPTS_NAME
    terminals_path = output_root / TERMINALS_NAME
    errors_path = output_root / ERRORS_NAME
    status_path = output_root / STATUS_NAME
    for path in (attempts_path, terminals_path, errors_path):
        create_empty_exclusive(path)
    _fsync_directory(output_root)

    preflight = {
        "schema_version": "c4-real-route-execution-preflight-receipt-v1",
        "status": "PASS_CREATED_BEFORE_FIRST_PROVIDER_CALL",
        "runner_version": RUNNER_VERSION,
        "component": component,
        "package_id": plan["package_id"],
        "package_validation": package_validation,
        "authorization_record_sha256": sha256(authorization_record.resolve().read_bytes()),
        "authorization_id": authorization["authorization_id"],
        "authorization_scope": authorization["authorization_scope"],
        "authorized_by": authorization["authorized_by"],
        "authorized_at": authorization["authorized_at"],
        "environment_gate": "PASS_EXACT_R1_VALUE",
        "api_key_present_not_recorded": True,
        "output_directory": str(output_root),
        "output_directory_exclusive_creation": True,
        "provider_calls_before_receipt": 0,
        "automatic_resume_permitted": False,
        "created_at": now(),
    }
    atomic_write_json(output_root / PREFLIGHT_NAME, preflight)
    status = _status(
        state="PREFLIGHT_COMPLETE",
        component=component,
        package_id=plan["package_id"],
        logical_requests=len(requests),
        logical_completed=0,
        logical_failed=0,
        physical_attempts=0,
        retry_count=0,
        provider_calls=0,
        last_scenario_id=None,
        stop_reason=None,
        now=now,
    )
    atomic_write_json(status_path, status)

    logical_completed = logical_failed = physical_attempts = retry_count = provider_calls = 0
    previous_initial_start: float | None = None
    try:
        transport = transport_factory()
    except Exception as error:
        error_class = classify_provider_exception(error)
        status = _status(
            state="INCOMPLETE_STOPPED",
            component=component,
            package_id=plan["package_id"],
            logical_requests=len(requests),
            logical_completed=0,
            logical_failed=0,
            physical_attempts=0,
            retry_count=0,
            provider_calls=0,
            last_scenario_id=None,
            stop_reason=error_class,
            now=now,
        )
        atomic_write_json(status_path, status)
        return status

    for logical_order, request in enumerate(requests, 1):
        payload = build_payload(
            plan=plan,
            prompt=prompt,
            schema=schema,
            examples=examples,
            request=request,
        )
        payload_bytes = canonical_bytes(payload)
        payload_hash = sha256(payload_bytes)

        for attempt_number in (1, 2):
            if attempt_number == 2:
                retry_count += 1
            require(
                physical_attempts < plan["maximum_physical_attempt_count"],
                "Physical-attempt ceiling exceeded",
            )
            reservation_record = _attempt_base(
                event="ATTEMPT_RESERVED",
                component=component,
                package_id=plan["package_id"],
                request=request,
                logical_order=logical_order,
                attempt_number=attempt_number,
                payload_sha256=payload_hash,
                reserved_at=now(),
            )
            append_fsync(attempts_path, reservation_record)
            physical_attempts += 1
            status = _status(
                state="PROVIDER_CALL_RESERVED",
                component=component,
                package_id=plan["package_id"],
                logical_requests=len(requests),
                logical_completed=logical_completed,
                logical_failed=logical_failed,
                physical_attempts=physical_attempts,
                retry_count=retry_count,
                provider_calls=provider_calls,
                last_scenario_id=request["scenario_id"],
                stop_reason=None,
                now=now,
            )
            atomic_write_json(status_path, status)

            initial_interval: float | None = None
            if attempt_number == 1:
                initial_start, initial_interval = _pace_initial_request(
                    previous_start=previous_initial_start,
                    minimum_interval=float(
                        plan["minimum_initial_request_start_interval_seconds"]
                    ),
                    monotonic=monotonic,
                    sleep=sleep,
                )
                previous_initial_start = initial_start
            started_at = now()
            started_monotonic = monotonic()
            provider_calls += 1

            provider_error: dict[str, Any] | None = None
            try:
                response = transport(json.loads(payload_bytes.decode("utf-8")))
                inspected = inspect_response(response, schema)
            except Exception as error:
                outcome = classify_provider_exception(error)
                provider_error = sanitized_provider_error(error)
                inspected = {
                    "outcome": outcome,
                    "returned_model": None,
                    "response_id": None,
                    "system_fingerprint": None,
                    "finish_reason": None,
                    "raw_response_content": None,
                    "provider_refusal": None,
                    "parsed_strict_output": None,
                    "strict_schema_status": "NOT_EVALUATED",
                    "input_tokens": None,
                    "cached_input_tokens": None,
                    "output_tokens": None,
                    "total_tokens": None,
                }
            ended_at = now()
            latency = max(0.0, monotonic() - started_monotonic)
            outcome = str(inspected["outcome"])
            retryable = outcome in RETRYABLE_ERRORS and attempt_number == 1
            terminal = outcome == "VALID" or not retryable
            completed_record = {
                **reservation_record,
                "event": "ATTEMPT_COMPLETED",
                "returned_model": inspected.get("returned_model"),
                "response_id": inspected.get("response_id"),
                "system_fingerprint": inspected.get("system_fingerprint"),
                "finish_reason": inspected.get("finish_reason"),
                "raw_response_content": inspected.get("raw_response_content"),
                "provider_refusal": inspected.get("provider_refusal"),
                "parsed_strict_output": inspected.get("parsed_strict_output"),
                "strict_schema_status": inspected.get("strict_schema_status"),
                "input_tokens": inspected.get("input_tokens"),
                "cached_input_tokens": inspected.get("cached_input_tokens"),
                "output_tokens": inspected.get("output_tokens"),
                "total_tokens": inspected.get("total_tokens"),
                "started_at": started_at,
                "ended_at": ended_at,
                "latency_seconds": round(latency, 6),
                "initial_start_interval_seconds": initial_interval,
                "sanitized_provider_error": provider_error,
                "outcome": outcome,
                "terminal": terminal,
            }
            append_fsync(attempts_path, completed_record)

            if outcome == "VALID":
                terminal_event = _terminal_event(
                    component=component,
                    package_id=plan["package_id"],
                    request=request,
                    logical_order=logical_order,
                    attempt_number=attempt_number,
                    payload_sha256=payload_hash,
                    outcome=outcome,
                    parsed_output=inspected["parsed_strict_output"],
                    raw_content=inspected.get("raw_response_content"),
                    returned_model=inspected.get("returned_model"),
                    now=now,
                )
                append_fsync(terminals_path, terminal_event)
                logical_completed += 1
                status = _status(
                    state="RUNNING",
                    component=component,
                    package_id=plan["package_id"],
                    logical_requests=len(requests),
                    logical_completed=logical_completed,
                    logical_failed=logical_failed,
                    physical_attempts=physical_attempts,
                    retry_count=retry_count,
                    provider_calls=provider_calls,
                    last_scenario_id=request["scenario_id"],
                    stop_reason=None,
                    now=now,
                )
                atomic_write_json(status_path, status)
                break

            append_fsync(
                errors_path,
                _error_event(
                    component=component,
                    package_id=plan["package_id"],
                    request=request,
                    logical_order=logical_order,
                    attempt_number=attempt_number,
                    payload_sha256=payload_hash,
                    error_class=outcome,
                    terminal=terminal,
                    provider_error=provider_error,
                    now=now,
                ),
            )
            if retryable:
                status = _status(
                    state="IDENTICAL_RETRY_AUTHORIZED",
                    component=component,
                    package_id=plan["package_id"],
                    logical_requests=len(requests),
                    logical_completed=logical_completed,
                    logical_failed=logical_failed,
                    physical_attempts=physical_attempts,
                    retry_count=retry_count,
                    provider_calls=provider_calls,
                    last_scenario_id=request["scenario_id"],
                    stop_reason=outcome,
                    now=now,
                )
                atomic_write_json(status_path, status)
                continue

            terminal_event = _terminal_event(
                component=component,
                package_id=plan["package_id"],
                request=request,
                logical_order=logical_order,
                attempt_number=attempt_number,
                payload_sha256=payload_hash,
                outcome=outcome,
                parsed_output=None,
                raw_content=inspected.get("raw_response_content"),
                returned_model=inspected.get("returned_model"),
                now=now,
            )
            append_fsync(terminals_path, terminal_event)
            logical_failed += 1
            status = _status(
                state="INCOMPLETE_STOPPED",
                component=component,
                package_id=plan["package_id"],
                logical_requests=len(requests),
                logical_completed=logical_completed,
                logical_failed=logical_failed,
                physical_attempts=physical_attempts,
                retry_count=retry_count,
                provider_calls=provider_calls,
                last_scenario_id=request["scenario_id"],
                stop_reason=outcome,
                now=now,
            )
            atomic_write_json(status_path, status)
            return status

    require(logical_completed == len(requests), "Execution ended without all logical results")
    usage = _usage_report(
        output_root, component=component, package_id=plan["package_id"]
    )
    atomic_write_json(output_root / USAGE_NAME, usage)
    atomic_write_bytes(output_root / REPORT_NAME, _markdown_report(usage))
    final_hashes = _output_hashes(
        output_root,
        [
            PREFLIGHT_NAME,
            ATTEMPTS_NAME,
            TERMINALS_NAME,
            ERRORS_NAME,
            USAGE_NAME,
            REPORT_NAME,
        ],
    )
    status = _status(
        state="COMPLETED",
        component=component,
        package_id=plan["package_id"],
        logical_requests=len(requests),
        logical_completed=logical_completed,
        logical_failed=0,
        physical_attempts=physical_attempts,
        retry_count=retry_count,
        provider_calls=provider_calls,
        last_scenario_id=requests[-1]["scenario_id"],
        stop_reason=None,
        now=now,
    )
    status["output_sha256_excluding_status"] = final_hashes
    status["routing_accuracy_calculated"] = False
    status["expected_labels_accessed"] = False
    atomic_write_json(status_path, status)
    return status


def _openai_transport_factory(api_key: str) -> TransportFactory:
    def factory() -> Transport:
        from openai import OpenAI  # type: ignore

        client = OpenAI(api_key=api_key, max_retries=0)

        def call(payload: dict[str, Any]) -> Any:
            return client.chat.completions.create(**payload)

        return call

    return factory


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--package-dir", type=Path, required=True)
    parser.add_argument("--authorization-record", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--component", choices=sorted(EXPECTED_COMPONENT_TOKENS), required=True)
    parser.add_argument("--execute", action="store_true")
    args = parser.parse_args()
    if not args.execute:
        raise SystemExit("NO_EXECUTION: --execute was not supplied")
    api_key = os.environ.get("OPENAI_API_KEY", "")
    result = execute_package(
        package_dir=args.package_dir,
        authorization_record=args.authorization_record,
        output_dir=args.output_dir,
        component=args.component,
        transport_factory=_openai_transport_factory(api_key),
    )
    print(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True))
    return 0 if result["state"] == "COMPLETED" else 2


if __name__ == "__main__":
    raise SystemExit(main())
