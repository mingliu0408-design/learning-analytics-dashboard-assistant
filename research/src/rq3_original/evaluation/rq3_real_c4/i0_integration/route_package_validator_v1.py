#!/usr/bin/env python3
"""Validate an extracted RQ3-REAL I0-R1 route package without executing it."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import re
from typing import Any, Mapping


MODEL = "gpt-4o-mini-2024-07-18"
REQUESTS_SHA256 = "b042e454a9508fac4348ce7ba1f2595ca2882227098696589c5e4e214710e326"
AUTHORIZATION_SCOPE = "RQ3_REAL_C4_P3_ROUTE_EXECUTION_R1"
AUTHORIZATION_ENVIRONMENT_VARIABLE = "C4_REAL_P3_ROUTE_EXECUTION_AUTHORIZATION"
AUTHORIZATION_ENVIRONMENT_VALUE = "AUTHORIZED_C4_REAL_P3_ROUTE_EXECUTION_R1"
EXPECTED_COMPONENT_TOKENS = {"RAG": 32, "MEMORY": 32, "B4_PLANNING": 64}
EXPECTED_COMPONENT_IDENTITIES = {
    "RAG": {
        "package_id": "C4_REAL_P3_RAG_ROUTE_EXECUTION_R1",
        "method_id": "R2V2-RAG_SPECIALIST",
        "frozen_configuration_sha256": "19fc104b55ed92ec6c9a988fe6664d5f062f92e473a5ff4d77f8c88aa871c7cc",
        "prompt_sha256": "e0e34a097ec0449e2cedfa305d43c7aad7b096ca5fb0a64dc54ad39e9c035d5c",
        "schema_sha256": "3a304b91bc642e8d04f59077b4f1240bf5f242105f888cfdb634ffa858901866",
        "final_example_set_sha256": "a932596e126ab66c054173bd1b9c454cbba9988e9d0b418da2d80c3e1df1e6eb",
        "few_shot_member_sha256": "39c5bfcfba2f4b91e61bdc05af358798ba72cb32741f699801fd6f4985250fb5",
        "superseded_package_id": "C4_REAL_P3_RAG_ROUTE_EXECUTION_V1",
        "superseded_package_sha256": "9cdd4caf404a2ba8c6743ed08b47a4bb3427d73851c0f7e1ba74c9f9a98c2f2a",
    },
    "MEMORY": {
        "package_id": "C4_REAL_P3_MEMORY_ROUTE_EXECUTION_R1",
        "method_id": "R2V2-MEMORY_SPECIALIST",
        "frozen_configuration_sha256": "8813854b4a73e4c07416e26db0b72f28ab1923f415053f8d48ad31b0eca0a3c3",
        "prompt_sha256": "c8a53b27f16b84ef0373ddfdd20eab997cc986eab10a93a138ede06571ebab04",
        "schema_sha256": "41a0f015b3fd7589bd1a08bd1d3e2a7c8bd5491b22c2531ef43ead634642a3d7",
        "final_example_set_sha256": "57a7aecd53710a1587388711177d7564f4560f1a8729939d445268d2514d3eb4",
        "few_shot_member_sha256": "837057a389de21abd1f7426b43809bcf46e6a0d3a2880f5ddc56790471975b6c",
        "superseded_package_id": "C4_REAL_P3_MEMORY_ROUTE_EXECUTION_V1",
        "superseded_package_sha256": "4ba5f4fe34d32fb4000af66209a0d6bb6d8bb9e6c7959d2a3ddbadaedec1d115",
    },
    "B4_PLANNING": {
        "package_id": "C4_REAL_P3_B4_PLANNING_ROUTE_EXECUTION_R1",
        "method_id": "R2V2-B4_JOINT_LLM",
        "frozen_configuration_sha256": "12a75dd33298f6e1078b326e7c922eb92f2675ee87c7f7858fdf19494072d470",
        "prompt_sha256": "62dd0072b40f812bea9d2400bf5053c1d727187c47cab3c8777a341e0a185541",
        "schema_sha256": "8017f1677e3ddc0bdd5042cff1c87e1e8ef4053da10b5c86da2cf45c35319876",
        "final_example_set_sha256": "020ec80b8b592a62c9975b47bf5bc63c9dd86c029da05a6a4afd43440291aff2",
        "few_shot_member_sha256": "76c1bd755a9ea6d794932c203d639c03594c38a5c99dafd4357104b7bdd6ebb7",
        "superseded_package_id": "C4_REAL_P3_B4_PLANNING_ROUTE_EXECUTION_V1",
        "superseded_package_sha256": "a7baa7fce67420df4e99fbc2cad51c0df258f5278150cec46181bae6bdbaed82",
    },
}
EXPECTED_OUTPUT_FIELDS = {
    "RAG": {"rag_required"},
    "MEMORY": {"memory_required"},
    "B4_PLANNING": {"rag_required", "memory_required", "planning_required"},
}
SCIENTIFIC_MEMBERS = (
    "requests.jsonl",
    "prompt.txt",
    "schema.json",
    "few_shot_examples.json",
)
REQUIRED_MEMBERS = {
    *SCIENTIFIC_MEMBERS,
    "EXECUTION_PLAN.json",
    "EXECUTION_CONTRACT.json",
    "PACKAGE_MANIFEST.json",
    "README.md",
    "execute_route_package_v2.py",
    "validate_route_package_v1.py",
}
FORBIDDEN_MUTABLE_MEMBERS = {
    "ATTEMPT_JOURNAL.jsonl",
    "TERMINAL_JOURNAL.jsonl",
    "route_attempt_records_v1.jsonl",
    "route_terminal_results_v1.jsonl",
    "route_error_registry_v1.jsonl",
    "route_execution_status_v1.json",
}
SEMANTIC_FIELDS = {
    "current_query",
    "current_page",
    "dashboard_context",
    "visible_conversation_history",
}
REQUEST_FIELDS = {
    "schema_version",
    "scenario_id",
    "semantic_input_sha256",
    "status",
    "semantic_input",
}
AUTHORIZATION_FIELDS = [
    "authorization_id",
    "authorization_scope",
    "authorized_by",
    "authorized_at",
    "package_id",
    "component",
    "logical_call_count",
    "maximum_physical_attempt_count",
    "status",
]
SECRET_VALUE = re.compile(
    rb"(?:sk-(?:proj-)?[A-Za-z0-9_-]{12,}|Bearer\s+[A-Za-z0-9._~+/-]{12,})",
    re.IGNORECASE,
)


class PackageValidationError(RuntimeError):
    """Raised when a package violates its frozen execution contract."""


def require(condition: bool, message: str) -> None:
    if not condition:
        raise PackageValidationError(message)


def canonical_bytes(value: Any) -> bytes:
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    ).encode("utf-8")


def sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def load_json_bytes(data: bytes, name: str) -> dict[str, Any]:
    try:
        value = json.loads(data.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        raise PackageValidationError(f"Invalid JSON object in {name}") from error
    require(isinstance(value, dict), f"Expected JSON object in {name}")
    return value


def parse_requests(data: bytes) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    try:
        text = data.decode("utf-8")
    except UnicodeDecodeError as error:
        raise PackageValidationError("requests.jsonl is not UTF-8") from error
    for number, line in enumerate(text.splitlines(), 1):
        require(bool(line.strip()), f"Blank requests.jsonl row at line {number}")
        try:
            row = json.loads(line)
        except json.JSONDecodeError as error:
            raise PackageValidationError(
                f"Invalid requests.jsonl JSON at line {number}"
            ) from error
        require(isinstance(row, dict), f"Request line {number} is not an object")
        rows.append(row)
    return rows


def _regular_member(path: Path) -> bool:
    return path.is_file() and not path.is_symlink()


def validate_package_dir(
    package_dir: Path, *, expected_component: str | None = None
) -> dict[str, Any]:
    """Fail closed on any package, scientific-input, or contract mismatch."""

    root = package_dir.resolve()
    require(root.is_dir(), f"Package directory does not exist: {root}")
    observed_names = sorted(path.name for path in root.iterdir())
    require(
        set(observed_names) == REQUIRED_MEMBERS,
        f"Package member allowlist mismatch: {observed_names}",
    )
    require(
        not (set(observed_names) & FORBIDDEN_MUTABLE_MEMBERS),
        "Authoritative package contains mutable execution output",
    )
    for name in observed_names:
        require(_regular_member(root / name), f"Package member is not a regular file: {name}")

    member_bytes = {name: (root / name).read_bytes() for name in observed_names}
    require(
        not any(SECRET_VALUE.search(data) for data in member_bytes.values()),
        "Potential credential value found in package",
    )
    manifest = load_json_bytes(member_bytes["PACKAGE_MANIFEST.json"], "PACKAGE_MANIFEST.json")
    plan = load_json_bytes(member_bytes["EXECUTION_PLAN.json"], "EXECUTION_PLAN.json")
    contract = load_json_bytes(
        member_bytes["EXECUTION_CONTRACT.json"], "EXECUTION_CONTRACT.json"
    )

    require(
        manifest.get("strict_allowlist") == observed_names,
        "Manifest strict allowlist mismatch",
    )
    declared_hashes = manifest.get("member_sha256_excluding_self")
    require(isinstance(declared_hashes, dict), "Manifest member hashes are missing")
    require(
        set(declared_hashes) == set(observed_names) - {"PACKAGE_MANIFEST.json"},
        "Manifest member-hash population mismatch",
    )
    for name, expected in declared_hashes.items():
        require(sha256(member_bytes[name]) == expected, f"Member SHA-256 mismatch: {name}")

    component = plan.get("route_component")
    require(component in EXPECTED_COMPONENT_TOKENS, "Unknown route component")
    identity = EXPECTED_COMPONENT_IDENTITIES[component]
    if expected_component is not None:
        require(component == expected_component, "CLI component does not match package")
    require(manifest.get("route_component") == component, "Manifest component mismatch")
    require(contract.get("component") == component, "Contract component mismatch")
    require(
        plan.get("package_id") == manifest.get("package_id") == contract.get("package_id"),
        "Package identity mismatch",
    )
    require(plan.get("package_id") == identity["package_id"], "Unexpected R1 package ID")
    require(
        plan.get("frozen_component_method_id") == identity["method_id"],
        "Frozen component method mismatch",
    )
    require(
        plan.get("frozen_configuration_sha256")
        == identity["frozen_configuration_sha256"],
        "Frozen configuration SHA-256 mismatch",
    )
    require(plan.get("prompt_sha256") == identity["prompt_sha256"], "Plan prompt SHA-256 mismatch")
    require(plan.get("schema_sha256") == identity["schema_sha256"], "Plan schema SHA-256 mismatch")
    require(
        plan.get("final_example_set_sha256")
        == identity["final_example_set_sha256"],
        "Plan example-set SHA-256 mismatch",
    )
    require(
        plan.get("supersedes_package_id") == identity["superseded_package_id"]
        and plan.get("supersedes_package_sha256")
        == identity["superseded_package_sha256"],
        "Superseded-package identity mismatch",
    )
    require(plan.get("model") == MODEL, "Frozen model mismatch")
    require(plan.get("endpoint") == "OpenAI Chat Completions", "Endpoint mismatch")
    require(type(plan.get("temperature")) is int and plan["temperature"] == 0, "Temperature mismatch")
    require(
        type(plan.get("max_output_tokens")) is int
        and plan["max_output_tokens"] == EXPECTED_COMPONENT_TOKENS[component],
        "Component-specific output-token limit mismatch",
    )
    require(
        plan.get("max_output_tokens_source")
        == "COMPONENT_SPEC_VERIFIED_AGAINST_FROZEN_RQ2_CONFIGURATION",
        "Component-token provenance mismatch",
    )
    require(plan.get("automatic_sdk_retries") == 0, "SDK retry setting mismatch")
    require(plan.get("streaming") is False, "Streaming must be false")
    require(plan.get("tools") == "NONE", "Tools must be none")
    require(plan.get("serial_execution") is True, "Execution must be serial")
    require(
        float(plan.get("minimum_initial_request_start_interval_seconds", 0)) >= 2.0,
        "Initial-request pacing is below 2.0 seconds",
    )
    require(plan.get("logical_call_count") == 62, "Logical-call count mismatch")
    require(plan.get("maximum_physical_attempt_count") == 124, "Attempt ceiling mismatch")
    require(
        plan.get("manual_retry_only_after")
        == ["INVALID_JSON", "STRICT_SCHEMA_VALIDATION_FAILED"],
        "Manual-retry reasons mismatch",
    )
    require(plan.get("manual_retry_maximum") == 1, "Manual-retry ceiling mismatch")
    require(plan.get("retry_payload_must_be_identical") is True, "Retry identity missing")
    require(plan.get("correction_message_on_retry") is False, "Correction retry forbidden")
    require(plan.get("automatic_resume_permitted") is False, "Automatic resume forbidden")
    require(plan.get("execution_output_location") == "EXTERNAL_NEW_OUTPUT_DIRECTORY", "Output location mismatch")

    require(contract.get("authorization_scope") == AUTHORIZATION_SCOPE, "Authorization scope mismatch")
    require(
        contract.get("authorization_environment_variable")
        == AUTHORIZATION_ENVIRONMENT_VARIABLE,
        "Authorization environment variable mismatch",
    )
    require(
        contract.get("authorization_environment_value")
        == AUTHORIZATION_ENVIRONMENT_VALUE,
        "Authorization environment value mismatch",
    )
    require(
        contract.get("strict_authorization_record_fields") == AUTHORIZATION_FIELDS,
        "Strict authorization-record fields mismatch",
    )
    require(contract.get("output_directory_must_not_exist") is True, "Exclusive output directory not required")
    require(contract.get("package_members_are_read_only") is True, "Package immutability not required")
    require(contract.get("automatic_resume_permitted") is False, "Contract permits resume")

    requests_bytes = member_bytes["requests.jsonl"]
    require(sha256(requests_bytes) == REQUESTS_SHA256, "Frozen requests SHA-256 mismatch")
    rows = parse_requests(requests_bytes)
    require(len(rows) == 62, "Frozen request population is not 62")
    require(
        [row.get("scenario_id") for row in rows]
        == [f"U{number:03d}" for number in range(1, 63)],
        "Scenario identity/order mismatch",
    )
    for row in rows:
        require(set(row) == REQUEST_FIELDS, f"Request fields changed: {row.get('scenario_id')}")
        semantic = row.get("semantic_input")
        require(isinstance(semantic, dict), "Semantic input is not an object")
        require(set(semantic) == SEMANTIC_FIELDS, "Four-field semantic boundary mismatch")
        require(
            sha256(canonical_bytes(semantic)) == row.get("semantic_input_sha256"),
            f"Semantic-input SHA-256 mismatch: {row.get('scenario_id')}",
        )

    schema = load_json_bytes(member_bytes["schema.json"], "schema.json")
    require(set(schema.get("required") or []) == EXPECTED_OUTPUT_FIELDS[component], "Schema output fields mismatch")
    require(schema.get("additionalProperties") is False, "Strict schema allows extra fields")
    properties = schema.get("properties")
    require(isinstance(properties, Mapping), "Schema properties missing")
    require(set(properties) == EXPECTED_OUTPUT_FIELDS[component], "Schema properties mismatch")
    require(
        all(value == {"type": "boolean"} for value in properties.values()),
        "Schema contains non-boolean capability fields",
    )

    scientific_hashes = {
        name: sha256(member_bytes[name]) for name in SCIENTIFIC_MEMBERS
    }
    require(
        scientific_hashes
        == {
            "requests.jsonl": REQUESTS_SHA256,
            "prompt.txt": identity["prompt_sha256"],
            "schema.json": identity["schema_sha256"],
            "few_shot_examples.json": identity["few_shot_member_sha256"],
        },
        "Component scientific member identity mismatch",
    )
    examples_document = load_json_bytes(
        member_bytes["few_shot_examples.json"], "few_shot_examples.json"
    )
    examples = examples_document.get("few_shot_examples")
    require(isinstance(examples, list), "Few-shot example list is missing")
    require(
        sha256(canonical_bytes(examples)) == identity["final_example_set_sha256"],
        "Canonical final example-set SHA-256 mismatch",
    )
    require(
        manifest.get("scientific_member_sha256") == scientific_hashes,
        "Scientific member manifest mismatch",
    )
    require(
        manifest.get("scientific_members_byte_identical_to_original") is True,
        "Old/R1 byte-identity assertion missing",
    )
    for flag in (
        "contains_credentials",
        "contains_gold",
        "contains_generated_routes",
        "contains_generated_answers",
        "contains_judge_outputs",
    ):
        require(manifest.get(flag) is False, f"Unsafe manifest flag: {flag}")
    require(manifest.get("provider_calls_in_i0_r1") == 0, "Nonzero provider-call claim")

    return {
        "status": "PASS_FROZEN_R1_ROUTE_PACKAGE",
        "component": component,
        "package_id": plan["package_id"],
        "logical_call_count": len(rows),
        "maximum_physical_attempt_count": plan["maximum_physical_attempt_count"],
        "max_output_tokens": plan["max_output_tokens"],
        "requests_sha256": scientific_hashes["requests.jsonl"],
        "scientific_member_sha256": scientific_hashes,
        "member_count": len(observed_names),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--package-dir", type=Path, required=True)
    parser.add_argument("--component", choices=sorted(EXPECTED_COMPONENT_TOKENS))
    args = parser.parse_args()
    result = validate_package_dir(
        args.package_dir, expected_component=args.component
    )
    print(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
