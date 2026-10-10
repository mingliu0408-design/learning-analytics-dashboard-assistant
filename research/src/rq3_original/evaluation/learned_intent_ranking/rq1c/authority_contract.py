"""Validation and transformation of the safe RQ1-C authority bridge."""

from __future__ import annotations

import hashlib
import json
import stat
import zipfile
from pathlib import Path, PurePosixPath
from typing import Any, Mapping

from . import (
    AUTHORITY_BRIDGE_MEMBERS,
    AUTHORITY_BRIDGE_SHA256,
    AUTHORITY_CANDIDATE_NAME,
    AUTHORITY_CANDIDATE_SHA256,
    LABEL_UNIVERSE,
    TRACK_A_ALIAS,
    TRACK_A_FILE_NAME,
    TRACK_A_RELATIVE_PATH,
    TRACK_A_SHA256,
    TRACK_A_SIZE_BYTES,
    TRACK_B_FILE_NAME,
    TRACK_B_SHA256,
)


class AuthorityContractError(RuntimeError):
    """Fail-closed authority-bridge or authority-contract error."""


def canonical_json_bytes(value: object) -> bytes:
    return (json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n").encode(
        "utf-8"
    )


def sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _parse_checksum_manifest(value: bytes) -> dict[str, str]:
    try:
        text = value.decode("ascii")
    except UnicodeDecodeError as exc:
        raise AuthorityContractError("authority checksum manifest must be ASCII") from exc
    result: dict[str, str] = {}
    for line in text.splitlines():
        if not line.strip():
            continue
        parts = line.split(None, 1)
        if len(parts) != 2:
            raise AuthorityContractError("authority checksum line is malformed")
        digest, name = parts
        name = name.strip().lstrip("*")
        if len(digest) != 64 or any(char not in "0123456789abcdef" for char in digest):
            raise AuthorityContractError("authority checksum digest is malformed")
        if name in result:
            raise AuthorityContractError("authority checksum member is duplicated")
        result[name] = digest
    return result


def validate_candidate_manifest(candidate: Mapping[str, Any]) -> None:
    """Validate only safe metadata; never infer values from a raw asset."""

    if candidate.get("schema_version") != "rq1c-final-gold-authority-candidate-v1":
        raise AuthorityContractError("candidate schema mismatch")
    asset = candidate.get("asset")
    safety = candidate.get("content_safety")
    fields = candidate.get("field_contract")
    distribution = candidate.get("distribution")
    exclusion = candidate.get("explicit_exclusion")
    policy = candidate.get("sealed_use_policy")
    if not all(isinstance(value, Mapping) for value in (asset, safety, fields, distribution, exclusion, policy)):
        raise AuthorityContractError("candidate metadata section missing")
    expected_asset = {
        "alias": TRACK_A_ALIAS,
        "file_name": TRACK_A_FILE_NAME,
        "expected_local_relative_path": TRACK_A_RELATIVE_PATH.as_posix(),
        "sha256": TRACK_A_SHA256,
        "size_bytes": TRACK_A_SIZE_BYTES,
        "container_format": "CSV",
        "encoding": "UTF-8 with BOM",
        "newline": "CRLF",
        "record_count": 128,
        "unique_record_id_count": 128,
        "unique_query_count": 128,
        "unique_normalised_query_count": 128,
        "duplicate_record_id_count": 0,
        "duplicate_query_count": 0,
        "duplicate_normalised_query_count": 0,
        "dataset_version": "primary-v3-candidate-v1",
        "record_schema_version": "primary-v3-track-a-blank-template-v1",
    }
    if any(asset.get(key) != value for key, value in expected_asset.items()):
        raise AuthorityContractError("candidate Track-A identity mismatch")
    if tuple(candidate.get("label_universe") or ()) != LABEL_UNIVERSE:
        raise AuthorityContractError("candidate label universe mismatch")
    expected_safety = {
        "contains_conversation_history": False,
        "contains_query_text": False,
        "contains_raw_final_gold": False,
        "contains_secrets": False,
        "contains_student_records": False,
    }
    if any(safety.get(key) is not value for key, value in expected_safety.items()):
        raise AuthorityContractError("candidate content-safety declaration mismatch")
    if any(key in candidate for key in ("records", "queries", "raw_records", "conversation_history")):
        raise AuthorityContractError("candidate contains a prohibited record collection")
    required_fields = {
        "record_id": "probe_id",
        "student_query": "query",
        "precomputed_normalised_query_for_audit_only": "normalised_query",
        "gold_intent": "human_final_label",
        "gold_intent_consistency_check": "final_semantic_label",
        "context_requirement": "human_final_context_requirement",
        "page_context": "human_final_page_context",
        "family_id": "final_heldout_family_id",
        "contrast_set_id": "contrast_set_id",
        "contrast_role": "contrast_role",
        "difficulty": "difficulty",
        "eligibility": "primary_heldout_eligible",
        "review_decision": "human_decision",
        "review_status": "review_status",
        "privacy_check": "human_privacy_check",
        "independence_check": "human_independence_confirmed",
    }
    if any(fields.get(key) != value for key, value in required_fields.items()):
        raise AuthorityContractError("candidate field contract mismatch")
    if distribution.get("per_label_count") != 8:
        raise AuthorityContractError("candidate per-label distribution mismatch")
    if distribution.get("heldout_family_count") != 128:
        raise AuthorityContractError("candidate family distribution mismatch")
    if distribution.get("contrast_set_count") != 32:
        raise AuthorityContractError("candidate contrast-set distribution mismatch")
    if exclusion.get("asset_name") != TRACK_B_FILE_NAME or exclusion.get("sha256") != TRACK_B_SHA256:
        raise AuthorityContractError("candidate Track-B exclusion mismatch")
    if exclusion.get("record_count") != 48:
        raise AuthorityContractError("candidate Track-B record count mismatch")
    if policy.get("final_gold_use") != "ONE_SHOT_RQ1_C1_ONLY":
        raise AuthorityContractError("candidate sealed-use policy mismatch")
    if any(
        policy.get(key) is not False
        for key in (
            "may_be_used_for_development_selection",
            "may_be_used_for_threshold_selection",
            "may_be_used_for_training",
            "may_be_used_to_change_schema_or_model",
        )
    ):
        raise AuthorityContractError("candidate permits a prohibited use")


def verify_authority_bridge(zip_path: Path) -> tuple[dict[str, Any], dict[str, Any]]:
    """Verify the safe three-member bridge and return metadata only."""

    if not zip_path.is_file() or zip_path.is_symlink():
        raise AuthorityContractError("authority bridge is missing or not a regular file")
    actual_zip_sha = sha256_file(zip_path)
    if actual_zip_sha != AUTHORITY_BRIDGE_SHA256:
        raise AuthorityContractError("authority bridge SHA-256 mismatch")
    with zipfile.ZipFile(zip_path, "r") as archive:
        infos = archive.infolist()
        names = tuple(info.filename for info in infos)
        if len(names) != len(set(names)) or set(names) != set(AUTHORITY_BRIDGE_MEMBERS):
            raise AuthorityContractError("authority bridge member list mismatch")
        for info in infos:
            pure = PurePosixPath(info.filename)
            unix_mode = (info.external_attr >> 16) & 0xFFFF
            if (
                pure.is_absolute()
                or ".." in pure.parts
                or len(pure.parts) != 1
                or info.is_dir()
                or stat.S_ISLNK(unix_mode)
            ):
                raise AuthorityContractError("authority bridge contains an unsafe member")
        if archive.testzip() is not None:
            raise AuthorityContractError("authority bridge integrity check failed")
        payloads = {name: archive.read(name) for name in AUTHORITY_BRIDGE_MEMBERS}
    checksums = _parse_checksum_manifest(
        payloads["RQ1C_AUTHORITY_BRIDGE_CHECKSUMS.sha256"]
    )
    expected_checksum_members = set(AUTHORITY_BRIDGE_MEMBERS) - {
        "RQ1C_AUTHORITY_BRIDGE_CHECKSUMS.sha256"
    }
    if set(checksums) != expected_checksum_members:
        raise AuthorityContractError("authority bridge checksum coverage mismatch")
    if any(sha256_bytes(payloads[name]) != checksums[name] for name in checksums):
        raise AuthorityContractError("authority bridge internal checksum mismatch")
    candidate_bytes = payloads[AUTHORITY_CANDIDATE_NAME]
    if sha256_bytes(candidate_bytes) != AUTHORITY_CANDIDATE_SHA256:
        raise AuthorityContractError("authority candidate SHA-256 mismatch")
    try:
        candidate = json.loads(candidate_bytes.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise AuthorityContractError("authority candidate is not valid UTF-8 JSON") from exc
    if not isinstance(candidate, dict):
        raise AuthorityContractError("authority candidate must be a JSON object")
    validate_candidate_manifest(candidate)
    report = {
        "schema_version": "rq1c-authority-bridge-verification-v1",
        "status": "PASS",
        "zip_sha256": actual_zip_sha,
        "zip_integrity": "PASS",
        "member_count": len(infos),
        "member_names": sorted(names),
        "member_list_exact": True,
        "internal_checksum_match_count": len(checksums),
        "internal_checksum_required": len(checksums),
        "candidate_manifest_sha256": sha256_bytes(candidate_bytes),
        "candidate_contains_query_text": False,
        "candidate_contains_conversation_history": False,
        "candidate_contains_raw_final_gold": False,
        "raw_asset_opened": False,
        "raw_asset_statted": False,
        "raw_asset_hashed": False,
    }
    return report, candidate


def build_authority_contract(
    bridge_report: Mapping[str, Any], candidate: Mapping[str, Any]
) -> dict[str, Any]:
    validate_candidate_manifest(candidate)
    if bridge_report.get("status") != "PASS":
        raise AuthorityContractError("verified bridge report required")
    asset = dict(candidate["asset"])
    return {
        "schema_version": "rq1c-final-gold-authority-contract-v1",
        "stage": "RQ1-C0-R1",
        "status": "AUTHORISED_FOR_RQ1_C1_ONE_SHOT_FINAL_EVALUATION",
        "authority_basis": "USER_EXPLICIT_AUTHORITY_USING_VERIFIED_SAFE_BRIDGE",
        "authority_bridge": {
            "zip_sha256": AUTHORITY_BRIDGE_SHA256,
            "candidate_manifest_sha256": AUTHORITY_CANDIDATE_SHA256,
            "member_count": 3,
            "verified": True,
            "tracked": False,
        },
        "track_a": {
            **asset,
            "sole_rq1_final_gold": True,
        },
        "field_contract": dict(candidate["field_contract"]),
        "record_validation": {
            "primary_heldout_eligible": True,
            "threshold_selection_eligible": False,
            "human_decision": "approved",
            "review_status": "completed_researcher_human_review",
            "human_privacy_check": "pass",
            "human_independence_confirmed": "yes",
            "gold_fields_must_match": True,
        },
        "label_universe": list(LABEL_UNIVERSE),
        "distribution": dict(candidate["distribution"]),
        "evaluation_input_contract": dict(candidate["evaluation_input_contract"]),
        "contamination_policy": {
            "duplicate_record_id_count_gt_zero": "FINAL_EVALUATION_INVALID",
            "train_dev_candidate_exact_or_normalised_overlap_gt_zero": "FINAL_EVALUATION_INVALID",
            "conflicting_identical_query_count_gt_zero": "FINAL_EVALUATION_INVALID",
            "same_label_internal_duplicates": "RETAIN_PRIMARY_AND_REPORT_UNIQUE_QUERY_SENSITIVITY",
            "family_overlap": "REPORT_SECONDARY_CLUSTER_SENSITIVITY_WITHOUT_MODEL_CHANGE",
            "audit_before_scoring": True,
        },
        "sealed_use_policy": dict(candidate["sealed_use_policy"]),
        "track_b": {
            "file_name": TRACK_B_FILE_NAME,
            "sha256": TRACK_B_SHA256,
            "record_count": 48,
            "track_b_excluded_from_rq1": True,
            "reserved_for_rq2": True,
        },
        "contains_raw_final_gold": False,
        "raw_asset_opened": False,
        "raw_asset_statted": False,
        "raw_asset_hashed": False,
        "raw_final_gold_access_authorised_in_this_stage": False,
        "rq1c1_evaluation_performed": False,
    }


def validate_authority_contract(contract: Mapping[str, Any]) -> None:
    if contract.get("schema_version") != "rq1c-final-gold-authority-contract-v1":
        raise AuthorityContractError("authority contract schema mismatch")
    if contract.get("status") != "AUTHORISED_FOR_RQ1_C1_ONE_SHOT_FINAL_EVALUATION":
        raise AuthorityContractError("authority contract status mismatch")
    if contract.get("authority_basis") != "USER_EXPLICIT_AUTHORITY_USING_VERIFIED_SAFE_BRIDGE":
        raise AuthorityContractError("authority basis mismatch")
    track_a = contract.get("track_a") or {}
    if (
        track_a.get("alias") != TRACK_A_ALIAS
        or track_a.get("expected_local_relative_path") != TRACK_A_RELATIVE_PATH.as_posix()
        or track_a.get("sha256") != TRACK_A_SHA256
        or track_a.get("size_bytes") != TRACK_A_SIZE_BYTES
        or track_a.get("sole_rq1_final_gold") is not True
    ):
        raise AuthorityContractError("authority contract Track-A mismatch")
    if tuple(contract.get("label_universe") or ()) != LABEL_UNIVERSE:
        raise AuthorityContractError("authority contract label universe mismatch")
    track_b = contract.get("track_b") or {}
    if track_b.get("track_b_excluded_from_rq1") is not True or track_b.get("reserved_for_rq2") is not True:
        raise AuthorityContractError("authority contract Track-B exclusion mismatch")
    for key in (
        "contains_raw_final_gold",
        "raw_asset_opened",
        "raw_asset_statted",
        "raw_asset_hashed",
        "raw_final_gold_access_authorised_in_this_stage",
        "rq1c1_evaluation_performed",
    ):
        if contract.get(key) is not False:
            raise AuthorityContractError(f"authority contract unsafe flag: {key}")


def validate_requested_asset_name(file_name: str) -> None:
    if file_name == TRACK_B_FILE_NAME:
        raise AuthorityContractError("Track B is excluded from RQ1 and reserved for RQ2")
    if file_name != TRACK_A_FILE_NAME:
        raise AuthorityContractError("requested asset is not the authorised RQ1 Track A")
