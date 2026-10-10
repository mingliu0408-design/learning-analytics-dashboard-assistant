#!/usr/bin/env python3
"""Join frozen blind classifications to restricted V2 mappings, aggregating only."""

from __future__ import annotations

import csv
import hashlib
import json
from collections import defaultdict
from pathlib import Path
from typing import Any, Callable


REPO_ROOT = Path(__file__).resolve().parents[3]
OUTPUT_DIR = Path(__file__).resolve().parent
I1_DIR = REPO_ROOT / "evaluation/rq3_real_c4/i1_route_integration"
RESTRICTED_DIR = I1_DIR / "restricted_internal"
AUDIT_PATH = OUTPUT_DIR / "c4_real_g2_prejudge_format_audit_v1.json"
FREEZE_RECEIPT_PATH = OUTPUT_DIR / "c4_real_g2_blind_format_audit_freeze_receipt_v1.json"
V2_MAPPING_PATH = RESTRICTED_DIR / "c4_real_condition_to_unique_request_mapping_frozen_v2.csv"
V2_MANIFEST_PATH = I1_DIR / "c4_real_unique_generation_request_manifest_frozen_v2.jsonl"
V2_METADATA_PATH = I1_DIR / "c4_real_restricted_mapping_metadata_v2.json"


def sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def pretty_json_bytes(value: Any) -> bytes:
    return (json.dumps(value, ensure_ascii=False, sort_keys=True, indent=2) + "\n").encode("utf-8")


def verify_blind_freeze() -> dict[str, Any]:
    receipt = json.loads(FREEZE_RECEIPT_PATH.read_text(encoding="utf-8"))
    if receipt.get("classification_frozen_before_restricted_mapping_access") is not True:
        raise RuntimeError("blind classification is not frozen")
    if receipt.get("restricted_mapping_accessed_by_this_phase") is not False:
        raise RuntimeError("blind phase provenance is invalid")
    for filename, expected_sha256 in receipt["frozen_artifact_sha256"].items():
        actual_sha256 = sha256_bytes((OUTPUT_DIR / filename).read_bytes())
        if actual_sha256 != expected_sha256:
            raise RuntimeError(f"frozen blind artifact changed: {filename}")
    return receipt


def read_jsonl(path: Path) -> list[dict[str, Any]]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line]


def feature_presence_by_response() -> dict[str, dict[str, str]]:
    features: dict[str, dict[str, str]] = {}
    for record in read_jsonl(V2_MANIFEST_PATH):
        messages = record["provider_payload"]["messages"]
        if [message["role"] for message in messages] != ["system", "user"]:
            raise RuntimeError("unexpected V2 message sequence")
        provider_context = json.loads(messages[1]["content"])
        evidence_items = provider_context["evidence"].get("evidence", [])
        sources = {
            item.get("source") for item in evidence_items if isinstance(item, dict)
        }
        planning_support = provider_context.get("planning_support")
        response_blind_id = record["response_blind_id"]
        if response_blind_id in features:
            raise RuntimeError("duplicate response blind ID in V2 manifest")
        features[response_blind_id] = {
            "planning_support": "PRESENT" if planning_support not in (None, {}, []) else "ABSENT",
            "rag_evidence": "PRESENT" if "course_material" in sources else "ABSENT",
            "memory_evidence": "PRESENT" if "learner_memory" in sources else "ABSENT",
        }
    if len(features) != 197:
        raise RuntimeError("V2 unique-manifest population mismatch")
    return features


def aggregate_dimension(
    rows: list[dict[str, str]],
    is_affected: Callable[[str], bool],
    dimension: Callable[[dict[str, str]], str],
) -> dict[str, dict[str, int]]:
    by_value: dict[str, list[dict[str, str]]] = defaultdict(list)
    for row in rows:
        by_value[dimension(row)].append(row)
    output: dict[str, dict[str, int]] = {}
    for value in sorted(by_value):
        group = by_value[value]
        unique_ids = {row["response_blind_id"] for row in group}
        affected_ids = {response_id for response_id in unique_ids if is_affected(response_id)}
        output[value] = {
            "affected_condition_mapping_count": sum(
                1 for row in group if is_affected(row["response_blind_id"])
            ),
            "affected_unique_request_count": len(affected_ids),
            "condition_mapping_count": len(group),
            "unique_request_count": len(unique_ids),
        }
    return output


def markdown_report(audit: dict[str, Any]) -> bytes:
    lines = [
        "# C4 Real G2 Restricted Aggregate Format-Bias Audit",
        "",
        "Status: `AGGREGATE_ONLY_AFTER_BLIND_CLASSIFICATION_FREEZE`",
        "",
        "The frozen blind format labels were joined to the existing restricted V2 mappings only after their hashes were sealed. This report contains aggregates only and does not expose any case-level mapping.",
        "",
        "This is a response-format association audit, not response-quality scoring. It makes no claim that Planning, RAG, or Memory improves or harms response quality.",
        "",
        "## Overall",
        "",
        f"- Non-student-facing unique requests: {audit['overall']['affected_unique_request_count']} / {audit['overall']['unique_request_count']}",
        f"- Affected condition mappings: {audit['overall']['affected_condition_mapping_count']} / {audit['overall']['condition_mapping_count']}",
        "",
    ]

    headings = (
        ("by_mode", "Mode"),
        ("by_page", "Page"),
        ("by_route_signature", "Route signature"),
        ("by_planning_support", "Planning support"),
        ("by_rag_evidence", "RAG evidence"),
        ("by_memory_evidence", "Memory evidence"),
    )
    for key, heading in headings:
        lines.extend(
            [
                f"## {heading}",
                "",
                "| Value | Affected unique / total unique | Affected mappings / total mappings |",
                "| --- | ---: | ---: |",
            ]
        )
        for value, counts in audit[key].items():
            lines.append(
                f"| `{value}` | {counts['affected_unique_request_count']} / {counts['unique_request_count']} | {counts['affected_condition_mapping_count']} / {counts['condition_mapping_count']} |"
            )
        lines.append("")

    planning_present = audit["by_planning_support"]["PRESENT"]
    lines.extend(
        [
            "## Independent observation check",
            "",
            f"Planning support was present in {planning_present['unique_request_count']} unique requests; {planning_present['affected_unique_request_count']} were non-student-facing. This independently reproduces 22 / 26.",
            "",
            "The classifications were not changed after aggregate unblinding. No response-quality score, Judge output, or human rating was created.",
        ]
    )
    return ("\n".join(lines) + "\n").encode("utf-8")


def main() -> int:
    receipt = verify_blind_freeze()
    audit = json.loads(AUDIT_PATH.read_text(encoding="utf-8"))
    classification_by_response = {
        record["opaque_response_blind_id"]: record["classification"]
        for record in audit["records"]
    }
    if len(classification_by_response) != 197:
        raise RuntimeError("blind audit population mismatch")
    if any("score" in key.lower() for record in audit["records"] for key in record):
        raise RuntimeError("quality score found in blind audit")

    metadata = json.loads(V2_METADATA_PATH.read_text(encoding="utf-8"))
    expected_mapping = metadata["v2_mapping_files"][V2_MAPPING_PATH.name]
    if sha256_bytes(V2_MAPPING_PATH.read_bytes()) != expected_mapping["sha256"]:
        raise RuntimeError("restricted V2 mapping hash mismatch")
    with V2_MAPPING_PATH.open(encoding="utf-8", newline="") as handle:
        rows = list(csv.DictReader(handle))
    if len(rows) != expected_mapping["row_count"] or len(rows) != 558:
        raise RuntimeError("restricted condition mapping count mismatch")
    if {row["response_blind_id"] for row in rows} != set(classification_by_response):
        raise RuntimeError("G2 response population and V2 mapping population differ")

    features = feature_presence_by_response()
    is_affected = lambda response_id: (
        classification_by_response[response_id] != "NATURAL_LANGUAGE_RESPONSE"
    )
    dimensions = {
        "by_mode": aggregate_dimension(rows, is_affected, lambda row: row["mode_id"]),
        "by_page": aggregate_dimension(rows, is_affected, lambda row: row["current_page"]),
        "by_route_signature": aggregate_dimension(rows, is_affected, lambda row: row["route_signature"]),
        "by_planning_support": aggregate_dimension(
            rows, is_affected, lambda row: features[row["response_blind_id"]]["planning_support"]
        ),
        "by_rag_evidence": aggregate_dimension(
            rows, is_affected, lambda row: features[row["response_blind_id"]]["rag_evidence"]
        ),
        "by_memory_evidence": aggregate_dimension(
            rows, is_affected, lambda row: features[row["response_blind_id"]]["memory_evidence"]
        ),
    }
    affected_unique = {response_id for response_id in classification_by_response if is_affected(response_id)}
    result = {
        "aggregate_only": True,
        "blind_audit_freeze_receipt_sha256": sha256_bytes(FREEZE_RECEIPT_PATH.read_bytes()),
        "blind_classification_sha256": receipt["frozen_artifact_sha256"][AUDIT_PATH.name],
        "classification_changed_after_unblinding": False,
        "independent_observation_check": {
            "observed": "22 of 26 unique requests containing Planning support were non-student-facing",
            "verified": dimensions["by_planning_support"]["PRESENT"]["affected_unique_request_count"] == 22
            and dimensions["by_planning_support"]["PRESENT"]["unique_request_count"] == 26,
        },
        "overall": {
            "affected_condition_mapping_count": sum(
                1 for row in rows if is_affected(row["response_blind_id"])
            ),
            "affected_unique_request_count": len(affected_unique),
            "condition_mapping_count": len(rows),
            "unique_request_count": len(classification_by_response),
        },
        "quality_scores_calculated": False,
        "restricted_mapping_content_in_output": False,
        "restricted_v2_mapping_sha256": expected_mapping["sha256"],
        "schema_version": "c4-real-g2-restricted-aggregate-format-bias-audit-v1",
        **dimensions,
    }
    if not result["independent_observation_check"]["verified"]:
        raise RuntimeError("Planning-support independent observation was not reproduced")

    json_path = OUTPUT_DIR / "c4_real_g2_restricted_aggregate_format_bias_audit_v1.json"
    markdown_path = OUTPUT_DIR / "C4_REAL_G2_RESTRICTED_AGGREGATE_FORMAT_BIAS_AUDIT.md"
    json_bytes = pretty_json_bytes(result)
    markdown_bytes = markdown_report(result)
    for path, data in ((json_path, json_bytes), (markdown_path, markdown_bytes)):
        if path.exists() and path.read_bytes() != data:
            raise RuntimeError(f"refusing to change aggregate audit: {path}")
        path.write_bytes(data)

    verify_blind_freeze()
    print("G2_RESTRICTED_AGGREGATE_AUDIT_FROZEN")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
