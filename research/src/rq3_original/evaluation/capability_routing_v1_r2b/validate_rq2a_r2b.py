"""Build and validate the RQ2-A-R2B governed research artifacts."""

from __future__ import annotations

import argparse
import ast
import json
from pathlib import Path
import subprocess
from typing import Any, Iterable, Mapping

from . import (
    AUTHENTIC_LABELS_RELATIVE,
    AUTHENTIC_REGISTRY_LABELS_RELATIVE,
    CANONICAL_ADJUDICATION_RELATIVE,
    CANONICAL_ADJUDICATION_SHA256,
    COMBINED_BANK_SHA256,
    HERE,
    LABEL_ONLY_FIELDS,
    LOCAL_AUTHENTIC_GOLD_RELATIVE,
    LOCAL_AUTHENTIC_REGISTRY_RELATIVE,
    LOCAL_COMBINED_GOLD_RELATIVE,
    LOCAL_SYNTHETIC_GOLD_RELATIVE,
    ROOT,
    RQ2A_R2A_CHECKSUM_COUNT,
    RQ2A_R2A_CHECKSUM_RELATIVE,
    RQ2A_R2A_HEAD,
    RQ2A_R2A_PARENT,
    RQ2A_R2A_REVIEW_ZIP_NAME,
    RQ2A_R2A_REVIEW_ZIP_SHA256,
    RQ2AR2BError,
    SOURCE_MAPPING_SHA256,
    SYNTHETIC_LABELS_RELATIVE,
    TARGET_BRANCH,
    canonical_json_bytes,
    sha256_bytes,
    sha256_file,
)
from .adjudication_canonicalisation import (
    validate_canonical_adjudication,
    write_canonical_adjudication,
)
from .adjudication_packet_identity import verify_adjudication_identity
from .adjudicator_attestation import (
    adjudicator_independence_attestation,
    validate_adjudicator_independence_attestation,
)
from .coverage_validator import validate_synthetic_coverage
from .eligibility_amendment import (
    synthetic_clarification_eligibility_amendment,
    validate_eligibility_amendment,
)
from .gold_policy_v1_1 import capability_gold_policy_document
from .post_gold_diagnostics import (
    run_post_gold_diagnostic,
    verify_frozen_gold_members,
)
from .source_separated_gold_builder import (
    LOCAL_OUTPUTS,
    TRACKED_LABEL_OUTPUTS,
    build_source_separated_gold_bytes,
    validate_persisted_gold,
    write_source_separated_gold,
)


PYTHON_FILES = (
    "__init__.py",
    "adjudication_packet_identity.py",
    "adjudication_canonicalisation.py",
    "adjudicator_attestation.py",
    "eligibility_amendment.py",
    "gold_policy_v1_1.py",
    "source_separated_gold_builder.py",
    "coverage_validator.py",
    "post_gold_diagnostics.py",
    "validate_rq2a_r2b.py",
    "test_rq2a_r2b_unittest.py",
)
DOCUMENT_RELATIVES = (
    Path("docs/thesis_mainline/rq2/RQ2A_R2B_ADJUDICATION_CLOSURE.md"),
    Path("docs/thesis_mainline/rq2/RQ2A_R2B_CAPABILITY_GOLD_POLICY_V1_1.md"),
    Path("docs/thesis_mainline/rq2/RQ2A_R2B_SOURCE_SEPARATED_GOLD_REPORT.md"),
    Path("docs/thesis_mainline/rq2/RQ2A_R2B_COVERAGE_AND_DATA_LIMITATIONS.md"),
)
ATTESTATION_RELATIVE = HERE.relative_to(ROOT) / (
    "human_adjudicator_independence_attestation_v1.json"
)
CANONICALISATION_MANIFEST_RELATIVE = HERE.relative_to(ROOT) / (
    "adjudication_canonicalisation_manifest_v1.json"
)
AMENDMENT_RELATIVE = HERE.relative_to(ROOT) / (
    "synthetic_clarification_eligibility_amendment_v1.json"
)
POLICY_RELATIVE = HERE.relative_to(ROOT) / "capability_gold_policy_v1_1.json"
GOLD_MANIFEST_RELATIVE = HERE.relative_to(ROOT) / (
    "source_separated_capability_gold_manifest_v1.json"
)
GOLD_SUMMARY_RELATIVE = HERE.relative_to(ROOT) / "capability_gold_summary_v1.json"
COVERAGE_RELATIVE = HERE.relative_to(ROOT) / "synthetic_coverage_validation_v1.json"
DIAGNOSTIC_RELATIVE = HERE.relative_to(ROOT) / (
    "post_gold_hidden_proposal_diagnostics_v1.json"
)
PREFLIGHT_RELATIVE = HERE.relative_to(ROOT) / "rq2a_r2b_preflight_report_v1.json"
CHECKSUM_RELATIVE = HERE.relative_to(ROOT) / "rq2a_r2b_output_checksums_v1.sha256"

SAFE_JSON_RELATIVES = (
    ATTESTATION_RELATIVE,
    CANONICALISATION_MANIFEST_RELATIVE,
    AMENDMENT_RELATIVE,
    POLICY_RELATIVE,
    GOLD_MANIFEST_RELATIVE,
    GOLD_SUMMARY_RELATIVE,
    COVERAGE_RELATIVE,
    DIAGNOSTIC_RELATIVE,
    PREFLIGHT_RELATIVE,
)
OUTPUT_CHECKSUM_RELATIVES = tuple(
    sorted(
        (
            *DOCUMENT_RELATIVES,
            *(HERE.relative_to(ROOT) / name for name in PYTHON_FILES),
            *SAFE_JSON_RELATIVES,
            *TRACKED_LABEL_OUTPUTS,
        ),
        key=lambda path: path.as_posix(),
    )
)
EXPECTED_TEST_COVERAGE = (
    "starting_head",
    "r2a_review_zip_hash",
    "r2a_output_checksums",
    "completed_adjudication_sha",
    "blank_packet_deterministic_rebuild",
    "blank_packet_sha",
    "fixed_fields_unchanged",
    "reviewer_fields_unchanged",
    "completed_adjudication_fields_filled",
    "adjudicator_id",
    "precanonical_date",
    "uppercase_immutable_booleans",
    "exact_date_replacements",
    "exact_boolean_replacements",
    "canonical_adjudication_sha",
    "canonical_adjudication_schema",
    "third_human_attestation",
    "no_ai_adjudication",
    "three_authentic_missing_context_cases",
    "authentic_missing_context_disposition",
    "synthetic_naturalness_adjudication",
    "context_resolution_adjudication",
    "clarification_amendment_authority",
    "clarification_exception_synthetic_only",
    "authentic_exception_rejected",
    "human_annotations_unchanged",
    "coverage_thresholds_unchanged",
    "canonical_reviewer_hashes",
    "source_mapping_hash",
    "combined_bank_hash",
    "consensus_precedence",
    "adjudication_precedence",
    "unresolved_disagreement_rejection",
    "authentic_gold_count",
    "authentic_registry_count",
    "synthetic_gold_count",
    "combined_gold_count",
    "authentic_capability_counts",
    "synthetic_capability_counts",
    "synthetic_clarification_exception_count",
    "context_resolution_counts",
    "multi_capability_count",
    "all_coverage_gates_pass",
    "gold_freeze_before_unblinding",
    "post_gold_analysis_cannot_mutate_gold",
    "proposal_diagnostic_source_separation",
    "proposal_absence_nonblocking",
    "local_full_text_gold_ignored",
    "tracked_gold_contains_no_query",
    "no_hidden_proposal_in_gold",
    "no_c0_or_legacy_in_gold",
    "track_a_rejected",
    "track_b_rejected",
    "no_production_change",
    "no_provider_network",
    "double_build_byte_identical",
    "output_checksums",
    "governed_text_leak_scan",
    "protected_sources_unchanged",
)


class RQ2AR2BValidationError(RQ2AR2BError):
    pass


def _git(*args: str, check: bool = True) -> subprocess.CompletedProcess[bytes]:
    result = subprocess.run(
        ["git", *args], cwd=ROOT, capture_output=True, check=False
    )
    if check and result.returncode:
        raise RQ2AR2BValidationError(f"git command failed: {' '.join(args)}")
    return result


def _json(relative: Path) -> dict[str, Any]:
    return json.loads((ROOT / relative).read_text(encoding="utf-8"))


def _jsonl(relative: Path) -> list[dict[str, Any]]:
    return [
        json.loads(line)
        for line in (ROOT / relative).read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]


def _write_json(relative: Path, value: Any) -> None:
    path = ROOT / relative
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(canonical_json_bytes(value))


def assert_lineage() -> dict[str, Any]:
    if _git("rev-parse", f"{RQ2A_R2A_HEAD}^").stdout.decode().strip() != RQ2A_R2A_PARENT:
        raise RQ2AR2BValidationError("BLOCKED_RQ2_A_R2B_STARTING_STATE_MISMATCH")
    if _git("branch", "--show-current").stdout.decode().strip() != TARGET_BRANCH:
        raise RQ2AR2BValidationError("BLOCKED_RQ2_A_R2B_STARTING_STATE_MISMATCH")
    if _git("merge-base", "--is-ancestor", RQ2A_R2A_HEAD, "HEAD", check=False).returncode:
        raise RQ2AR2BValidationError("BLOCKED_RQ2_A_R2B_STARTING_STATE_MISMATCH")
    relative = int(
        _git("rev-list", "--count", f"{RQ2A_R2A_HEAD}..HEAD").stdout.decode().strip()
    )
    if relative not in {0, 1}:
        raise RQ2AR2BValidationError("BLOCKED_RQ2_A_R2B_GIT_FAILURE")
    if relative == 1 and _git("rev-parse", "HEAD^").stdout.decode().strip() != RQ2A_R2A_HEAD:
        raise RQ2AR2BValidationError("BLOCKED_RQ2_A_R2B_GIT_FAILURE")
    if _git("remote").stdout.strip() or _git("tag", "--list").stdout.strip():
        raise RQ2AR2BValidationError("BLOCKED_RQ2_A_R2B_GIT_FAILURE")
    return {
        "approved_starting_branch": "research/rq2-a-r2a-human-review-closure",
        "approved_starting_head": RQ2A_R2A_HEAD,
        "approved_starting_parent": RQ2A_R2A_PARENT,
        "target_branch": TARGET_BRANCH,
        "relative_commit_count": relative,
        "remote_count": 0,
        "tag_count": 0,
    }


def assert_r2a_artifacts() -> dict[str, Any]:
    review_zip = Path.home() / "Downloads" / RQ2A_R2A_REVIEW_ZIP_NAME
    if (
        not review_zip.is_file()
        or review_zip.is_symlink()
        or sha256_file(review_zip) != RQ2A_R2A_REVIEW_ZIP_SHA256
    ):
        raise RQ2AR2BValidationError("BLOCKED_RQ2_A_R2B_STARTING_STATE_MISMATCH")
    count = 0
    for line in (ROOT / RQ2A_R2A_CHECKSUM_RELATIVE).read_text(
        encoding="utf-8"
    ).splitlines():
        digest, relative = line.split("  ", 1)
        if sha256_file(ROOT / relative) != digest:
            raise RQ2AR2BValidationError(
                "BLOCKED_RQ2_A_R2B_STARTING_STATE_MISMATCH"
            )
        count += 1
    if count != RQ2A_R2A_CHECKSUM_COUNT:
        raise RQ2AR2BValidationError("BLOCKED_RQ2_A_R2B_STARTING_STATE_MISMATCH")
    return {
        "review_zip_sha256": RQ2A_R2A_REVIEW_ZIP_SHA256,
        "output_checksum_count": count,
        "output_checksums_status": "PASS",
    }


def assert_gitignore_contract() -> None:
    base = _git("show", f"{RQ2A_R2A_HEAD}:.gitignore").stdout.decode("utf-8")
    additions = (
        "evaluation/capability_routing_v1_r2b/local_adjudication/",
        "evaluation/capability_routing_v1_r2b/local_gold/",
        "evaluation/capability_routing_v1_r2b/local_artifacts/",
    )
    expected = base.rstrip("\n") + "\n" + "\n".join(additions) + "\n"
    if (ROOT / ".gitignore").read_text(encoding="utf-8") != expected:
        raise RQ2AR2BValidationError(".gitignore differs from exact R2B additions")


def _allowed_changed_path(relative: str) -> bool:
    return (
        relative == ".gitignore"
        or relative.startswith("evaluation/capability_routing_v1_r2b/")
        or relative.startswith("docs/thesis_mainline/rq2/RQ2A_R2B_")
    )


def assert_change_scope() -> None:
    for args in (
        ("diff", "--name-only", RQ2A_R2A_HEAD),
        ("diff", "--cached", "--name-only", RQ2A_R2A_HEAD),
    ):
        names = _git(*args).stdout.decode().splitlines()
        if any(not _allowed_changed_path(name) for name in names):
            raise RQ2AR2BValidationError(
                "BLOCKED_RQ2_A_R2B_PROTECTED_SOURCE_MUTATED"
            )
    status = _git("status", "--porcelain=v1", "--untracked-files=all").stdout.decode()
    for line in status.splitlines():
        relative = line[3:]
        if " -> " in relative:
            relative = relative.split(" -> ", 1)[1]
        if not _allowed_changed_path(relative):
            raise RQ2AR2BValidationError(
                "BLOCKED_RQ2_A_R2B_PROTECTED_SOURCE_MUTATED"
            )


def assert_python_ast_and_offline_surface() -> None:
    prohibited_imports = {
        "openai",
        "requests",
        "httpx",
        "urllib",
        "urllib3",
        "socket",
        "firebase_admin",
    }
    for name in PYTHON_FILES:
        path = HERE / name
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        imports = {
            node.names[0].name.split(".")[0]
            for node in ast.walk(tree)
            if isinstance(node, ast.Import) and node.names
        } | {
            (node.module or "").split(".")[0]
            for node in ast.walk(tree)
            if isinstance(node, ast.ImportFrom)
        }
        if imports & prohibited_imports:
            raise RQ2AR2BValidationError("provider/network import surface detected")


def _gold_bundle_descriptor(
    gold_members: Mapping[str, Mapping[str, Any]],
) -> dict[str, Any]:
    return {
        "schema_version": "source-separated-gold-bundle-descriptor-v1",
        "gold_members": dict(sorted(gold_members.items())),
        "supporting_contract_sha256": {
            "human_adjudicator_independence_attestation_v1.json": sha256_file(
                ROOT / ATTESTATION_RELATIVE
            ),
            "synthetic_clarification_eligibility_amendment_v1.json": sha256_file(
                ROOT / AMENDMENT_RELATIVE
            ),
            "capability_gold_policy_v1_1.json": sha256_file(ROOT / POLICY_RELATIVE),
            "synthetic_coverage_validation_v1.json": sha256_file(
                ROOT / COVERAGE_RELATIVE
            ),
        },
    }


def _safe_gold_summary(build: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "schema_version": "capability-gold-summary-v1",
        "stage": "RQ2-A-R2B",
        "status": "PASS",
        "composition": build["composition"],
        "authentic_capability_distribution": build["authentic_distribution"],
        "synthetic_capability_distribution": build["synthetic_distribution"],
        "authentic_limitations": {
            "student_origin": True,
            "high_overlap_with_frozen_c0_rq1_training_material": True,
            "development_codebook_use_only": True,
            "independent_performance_evidence": False,
            "episodic_memory_positive_count": 0,
            "clarification_positive_count": 0,
            "context_missing_excluded_count": 3,
        },
        "synthetic_limitations": {
            "researcher_authored": True,
            "authentic_student_language": False,
            "controlled_mechanism_threshold_development_only": True,
            "final_evaluation_eligible": False,
            "clarification_exception_case_count": 3,
        },
        "track_b_status": "SEALED_FUTURE_INDEPENDENT_CONTEXTUAL_FINAL_HELDOUT",
    }


def _gold_manifest(
    *, gold_members: Mapping[str, Mapping[str, Any]], bundle_sha256: str
) -> dict[str, Any]:
    return {
        "schema_version": "source-separated-capability-gold-manifest-v1",
        "stage": "RQ2-A-R2B",
        "status": "HUMAN_GOLD_FROZEN",
        "authentic_gold_count": 22,
        "synthetic_gold_count": 35,
        "context_missing_registry_count": 3,
        "combined_gold_count": 57,
        "human_only_freeze": True,
        "hidden_proposal_used_to_form_gold": False,
        "legacy_output_used_to_form_gold": False,
        "c0_used_to_form_gold": False,
        "intent_prediction_used_to_form_gold": False,
        "hidden_proposal_accessed": False,
        "model_output_accessed": False,
        "gold_frozen_before_unblinding": True,
        "query_rewrite_performed": False,
        "assistant_context_attached": False,
        "gold_members": dict(sorted(gold_members.items())),
        "source_separated_gold_bundle_sha256": bundle_sha256,
        "bundle_hash_definition": (
            "SHA256_OF_CANONICAL_SOURCE_SEPARATED_GOLD_BUNDLE_DESCRIPTOR_V1"
        ),
    }


def _governed_text_values() -> set[str]:
    values: set[str] = set()
    for line in (ROOT / "evaluation/capability_routing_v1_r1c/local_case_bank/combined_calibration_review_bank_v1_3.jsonl").read_text(
        encoding="utf-8"
    ).splitlines():
        if not line.strip():
            continue
        row = json.loads(line)
        for value in (row.get("current_query"), row.get("current_page")):
            if isinstance(value, str) and len(value.strip()) >= 12:
                values.add(value)
        for item in row.get("necessary_conversation_history") or []:
            content = item.get("content") if isinstance(item, dict) else None
            if isinstance(content, str) and len(content.strip()) >= 12:
                values.add(content)
    return values


def governed_text_leak_scan(relatives: Iterable[Path]) -> dict[str, Any]:
    governed = _governed_text_values()
    leaks: list[str] = []
    scanned = 0
    absolute_user_marker = "/" + "Users" + "/"
    for relative in relatives:
        path = ROOT / relative
        if not path.is_file() or path.is_symlink():
            continue
        text = path.read_text(encoding="utf-8", errors="strict")
        scanned += 1
        if any(value in text for value in governed):
            leaks.append(relative.as_posix())
        if absolute_user_marker in text:
            leaks.append(relative.as_posix())
    if leaks:
        raise RQ2AR2BValidationError("governed-text leak detected")
    return {
        "status": "PASS",
        "governed_text_value_count": len(governed),
        "scanned_file_count": scanned,
        "leak_count": 0,
    }


def _write_output_checksums() -> int:
    lines = []
    for relative in OUTPUT_CHECKSUM_RELATIVES:
        path = ROOT / relative
        if not path.is_file() or path.is_symlink():
            raise RQ2AR2BValidationError(f"missing checksum output: {relative}")
        lines.append(f"{sha256_file(path)}  {relative.as_posix()}\n")
    (ROOT / CHECKSUM_RELATIVE).write_text("".join(lines), encoding="utf-8")
    return len(lines)


def validate_output_checksums() -> int:
    lines = (ROOT / CHECKSUM_RELATIVE).read_text(encoding="utf-8").splitlines()
    expected_names = [relative.as_posix() for relative in OUTPUT_CHECKSUM_RELATIVES]
    observed_names: list[str] = []
    for line in lines:
        digest, relative = line.split("  ", 1)
        observed_names.append(relative)
        if sha256_file(ROOT / relative) != digest:
            raise RQ2AR2BValidationError(f"output checksum mismatch: {relative}")
    if observed_names != expected_names:
        raise RQ2AR2BValidationError("output checksum allowlist mismatch")
    return len(lines)


def build_rq2a_r2b() -> dict[str, Any]:
    if (ROOT / GOLD_MANIFEST_RELATIVE).exists():
        raise RQ2AR2BValidationError("BLOCKED_RQ2_A_R2B_GOLD_FREEZE_ORDER")
    lineage = assert_lineage()
    r2a = assert_r2a_artifacts()
    assert_gitignore_contract()
    assert_change_scope()
    completed_path, identity = verify_adjudication_identity(ROOT)
    canonical_path, canonicalisation = write_canonical_adjudication(
        completed_path, ROOT
    )
    canonical_schema = validate_canonical_adjudication(canonical_path)

    attestation = adjudicator_independence_attestation()
    amendment = synthetic_clarification_eligibility_amendment()
    policy = capability_gold_policy_document()
    validate_adjudicator_independence_attestation(attestation)
    validate_eligibility_amendment(amendment)
    _write_json(ATTESTATION_RELATIVE, attestation)
    _write_json(CANONICALISATION_MANIFEST_RELATIVE, canonicalisation)
    _write_json(AMENDMENT_RELATIVE, amendment)
    _write_json(POLICY_RELATIVE, policy)

    build = build_source_separated_gold_bytes(canonical_path, ROOT)
    write_source_separated_gold(build, ROOT)
    coverage = validate_synthetic_coverage(
        build["output_rows"][SYNTHETIC_LABELS_RELATIVE]
    )
    if coverage["synthetic_clarification_exception_cases"] != 3:
        raise RQ2AR2BValidationError(
            "BLOCKED_RQ2_A_R2B_CAPABILITY_DISTRIBUTION_MISMATCH"
        )
    _write_json(COVERAGE_RELATIVE, coverage)
    _write_json(GOLD_SUMMARY_RELATIVE, _safe_gold_summary(build))

    gold_members = validate_persisted_gold(build, ROOT)
    descriptor = _gold_bundle_descriptor(gold_members)
    bundle_sha256 = sha256_bytes(canonical_json_bytes(descriptor))
    manifest = _gold_manifest(
        gold_members=gold_members, bundle_sha256=bundle_sha256
    )
    _write_json(GOLD_MANIFEST_RELATIVE, manifest)
    frozen = _json(GOLD_MANIFEST_RELATIVE)
    if (
        frozen["status"] != "HUMAN_GOLD_FROZEN"
        or not frozen["gold_frozen_before_unblinding"]
        or frozen["hidden_proposal_accessed"]
        or frozen["model_output_accessed"]
        or verify_frozen_gold_members(ROOT, frozen["gold_members"])
        != {key: value["sha256"] for key, value in frozen["gold_members"].items()}
    ):
        raise RQ2AR2BValidationError("BLOCKED_RQ2_A_R2B_GOLD_FREEZE_ORDER")

    diagnostic = run_post_gold_diagnostic(
        root=ROOT,
        source_separated_gold_bundle_sha256=bundle_sha256,
        frozen_members=frozen["gold_members"],
        authentic_gold=build["output_rows"][AUTHENTIC_LABELS_RELATIVE],
        synthetic_gold=build["output_rows"][SYNTHETIC_LABELS_RELATIVE],
        authentic_registry=build["output_rows"][AUTHENTIC_REGISTRY_LABELS_RELATIVE],
    )
    _write_json(DIAGNOSTIC_RELATIVE, diagnostic)

    preflight = {
        "schema_version": "rq2a-r2b-preflight-report-v1",
        "stage": "RQ2-A-R2B",
        "status": "PASS",
        "lineage": lineage,
        "rq2a_artifacts": r2a,
        "adjudication_identity": identity,
        "adjudication_canonicalisation": canonicalisation,
        "canonical_adjudication_schema": canonical_schema,
        "canonical_adjudication_sha256": CANONICAL_ADJUDICATION_SHA256,
        "source_mapping_sha256": SOURCE_MAPPING_SHA256,
        "combined_bank_sha256": COMBINED_BANK_SHA256,
        "gold_composition": build["composition"],
        "gold_bundle_sha256": bundle_sha256,
        "coverage_status": coverage["status"],
        "post_gold_diagnostic_status": diagnostic["status"],
        "gold_frozen_before_unblinding": True,
        "hidden_proposal_used_to_form_gold": False,
        "model_output_used_to_form_gold": False,
        "human_annotation_changed": False,
        "adjudication_decision_changed": False,
        "coverage_threshold_changed": False,
        "capability_definition_changed": False,
        "query_rewrite_performed": False,
        "assistant_context_attached": False,
        "production_source_change_count": 0,
        "track_a_accessed": False,
        "track_b_accessed": False,
        "model_training_performed": False,
        "provider_calls": 0,
        "network_access": False,
        "b0_implemented": False,
        "p1_implemented": False,
        "p2_implemented": False,
        "expected_test_coverage": list(EXPECTED_TEST_COVERAGE),
        "expected_test_coverage_count": len(EXPECTED_TEST_COVERAGE),
    }
    _write_json(PREFLIGHT_RELATIVE, preflight)
    leak = governed_text_leak_scan(OUTPUT_CHECKSUM_RELATIVES)
    preflight["governed_text_leak_scan"] = leak
    _write_json(PREFLIGHT_RELATIVE, preflight)
    leak = governed_text_leak_scan(OUTPUT_CHECKSUM_RELATIVES)
    if leak["status"] != "PASS":
        raise RQ2AR2BValidationError("governed-text leak scan failed")
    checksum_count = _write_output_checksums()
    validate_existing_outputs()
    return {
        "status": "READY_FOR_RQ2_B_CAPABILITY_ROUTING_DEVELOPMENT",
        "gold_bundle_sha256": bundle_sha256,
        "gold_composition": build["composition"],
        "coverage_status": coverage["status"],
        "diagnostic_status": diagnostic["status"],
        "output_checksum_count": checksum_count,
    }


def validate_existing_outputs() -> dict[str, Any]:
    assert_lineage()
    assert_r2a_artifacts()
    assert_gitignore_contract()
    assert_change_scope()
    assert_python_ast_and_offline_surface()
    canonical_path = ROOT / CANONICAL_ADJUDICATION_RELATIVE
    validate_canonical_adjudication(canonical_path)
    validate_adjudicator_independence_attestation(_json(ATTESTATION_RELATIVE))
    validate_eligibility_amendment(_json(AMENDMENT_RELATIVE))
    manifest = _json(GOLD_MANIFEST_RELATIVE)
    if (
        manifest["status"] != "HUMAN_GOLD_FROZEN"
        or not manifest["human_only_freeze"]
        or not manifest["gold_frozen_before_unblinding"]
        or manifest["hidden_proposal_used_to_form_gold"]
        or manifest["legacy_output_used_to_form_gold"]
        or manifest["c0_used_to_form_gold"]
        or manifest["intent_prediction_used_to_form_gold"]
    ):
        raise RQ2AR2BValidationError("BLOCKED_RQ2_A_R2B_GOLD_FREEZE_ORDER")
    verify_frozen_gold_members(ROOT, manifest["gold_members"])
    descriptor = _gold_bundle_descriptor(manifest["gold_members"])
    if sha256_bytes(canonical_json_bytes(descriptor)) != manifest[
        "source_separated_gold_bundle_sha256"
    ]:
        raise RQ2AR2BValidationError("BLOCKED_RQ2_A_R2B_GOLD_FREEZE_ORDER")
    authentic = _jsonl(AUTHENTIC_LABELS_RELATIVE)
    synthetic = _jsonl(SYNTHETIC_LABELS_RELATIVE)
    registry = _jsonl(AUTHENTIC_REGISTRY_LABELS_RELATIVE)
    if (len(authentic), len(synthetic), len(registry)) != (22, 35, 3):
        raise RQ2AR2BValidationError(
            "BLOCKED_RQ2_A_R2B_GOLD_COMPOSITION_MISMATCH"
        )
    for rows in (authentic, synthetic, registry):
        if any(set(row) != set(LABEL_ONLY_FIELDS) for row in rows):
            raise RQ2AR2BValidationError("tracked Gold field allowlist mismatch")
    coverage = validate_synthetic_coverage(synthetic)
    if coverage != _json(COVERAGE_RELATIVE):
        raise RQ2AR2BValidationError("coverage output mismatch")
    diagnostic = _json(DIAGNOSTIC_RELATIVE)
    if not diagnostic["gold_hashes_verified_before_unblinding"] or not diagnostic[
        "gold_hashes_unchanged_after_diagnostic"
    ]:
        raise RQ2AR2BValidationError("BLOCKED_RQ2_A_R2B_GOLD_FREEZE_ORDER")
    checksum_count = validate_output_checksums()
    governed_text_leak_scan(OUTPUT_CHECKSUM_RELATIVES)
    return {
        "status": "PASS",
        "gold_bundle_sha256": manifest["source_separated_gold_bundle_sha256"],
        "output_checksum_count": checksum_count,
        "coverage_status": coverage["status"],
        "diagnostic_status": diagnostic["status"],
    }


def finalize_post_freeze_outputs() -> dict[str, Any]:
    """Resume only non-Gold finalisation after an already verified freeze.

    This function never writes a Gold data member, the Gold summary, coverage,
    policy, amendment, attestation, canonical adjudication, diagnostic, or
    freeze manifest.  It may only complete the preflight leak-scan record and
    the derived output-checksum manifest.
    """

    assert_lineage()
    assert_r2a_artifacts()
    assert_gitignore_contract()
    assert_change_scope()
    assert_python_ast_and_offline_surface()
    manifest = _json(GOLD_MANIFEST_RELATIVE)
    if (
        manifest["status"] != "HUMAN_GOLD_FROZEN"
        or not manifest["gold_frozen_before_unblinding"]
        or manifest["hidden_proposal_used_to_form_gold"]
        or manifest["model_output_accessed"]
    ):
        raise RQ2AR2BValidationError("BLOCKED_RQ2_A_R2B_GOLD_FREEZE_ORDER")
    before = verify_frozen_gold_members(ROOT, manifest["gold_members"])
    preflight = _json(PREFLIGHT_RELATIVE)
    leak = governed_text_leak_scan(OUTPUT_CHECKSUM_RELATIVES)
    preflight["governed_text_leak_scan"] = leak
    _write_json(PREFLIGHT_RELATIVE, preflight)
    governed_text_leak_scan(OUTPUT_CHECKSUM_RELATIVES)
    after = verify_frozen_gold_members(ROOT, manifest["gold_members"])
    if before != after:
        raise RQ2AR2BValidationError("BLOCKED_RQ2_A_R2B_GOLD_FREEZE_ORDER")
    checksum_count = _write_output_checksums()
    validated = validate_existing_outputs()
    return {
        "status": "PASS",
        "gold_members_unchanged": True,
        "gold_bundle_sha256": manifest["source_separated_gold_bundle_sha256"],
        "governed_text_leak_scan": leak["status"],
        "output_checksum_count": checksum_count,
        "validation": validated,
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--build", action="store_true")
    parser.add_argument("--finalize-post-freeze", action="store_true")
    args = parser.parse_args()
    if args.build and args.finalize_post_freeze:
        parser.error("choose only one write mode")
    if args.build:
        result = build_rq2a_r2b()
    elif args.finalize_post_freeze:
        result = finalize_post_freeze_outputs()
    else:
        result = validate_existing_outputs()
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
