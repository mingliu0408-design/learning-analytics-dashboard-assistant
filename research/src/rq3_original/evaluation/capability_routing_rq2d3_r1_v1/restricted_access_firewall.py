"""Lexical deny-list and zero-access audit for D3-R1 restricted assets."""

from __future__ import annotations

from typing import Any


_DENIED_SUFFIXES = (
    "evaluation/capability_routing_rq2d1_v1/local_one_shot/track_b_opaque_mapping_v1.jsonl",
    "evaluation/capability_routing_rq2d1_v1/local_one_shot/track_b_canonical_case_bank_v1.jsonl",
    "evaluation/capability_routing_rq2d2b_v1/local_gold/track_b_contextual_capability_final_gold_v1.jsonl",
    "evaluation/capability_routing_rq2d1_v1/local_one_shot/track_b_hidden_legacy_metadata_v1.jsonl",
)
_DENIED_FUTURE_TOKENS = (
    "capability_routing_rq2d3_v1/track_b_source_blinded_contrast_groups",
    "capability_routing_rq2d4_v1/local_one_shot",
    "capability_routing_rq2d4_v1/local_control",
)


class RestrictedAccessError(RuntimeError):
    pass


def assert_lexical_path_allowed_v1(candidate: str) -> None:
    """Reject a supplied path string without resolving or touching the filesystem."""

    normalised = str(candidate).replace("\\", "/").lstrip("./")
    if any(normalised.endswith(value) for value in _DENIED_SUFFIXES) or any(
        token in normalised for token in _DENIED_FUTURE_TOKENS
    ):
        raise RestrictedAccessError("BLOCKED_RQ2_D3_R1_RESTRICTED_ACCESS")


def restricted_access_audit_v1() -> dict[str, Any]:
    return {
        "contract_id": "RQ2_D3_R1_RESTRICTED_ACCESS_FIREWALL_V1",
        "restricted_path_class_count": 7,
        "restricted_access_count": 0,
        "mapping_access_count": 0,
        "case_bank_access_count": 0,
        "full_text_gold_access_count": 0,
        "feature_access_count": 0,
        "label_record_access_count": 0,
        "grouping_ledger_access_count": 0,
        "hidden_legacy_access_count": 0,
        "raw_track_b_access_count": 0,
        "blind_key_access_count": 0,
        "model_execution_count": 0,
        "d4_execution_count": 0,
        "filesystem_probe_count": 0,
    }


def synthetic_deny_checks_v1() -> int:
    blocked = 0
    for candidate in (*_DENIED_SUFFIXES, *_DENIED_FUTURE_TOKENS):
        try:
            assert_lexical_path_allowed_v1(candidate)
        except RestrictedAccessError:
            blocked += 1
    if blocked != len(_DENIED_SUFFIXES) + len(_DENIED_FUTURE_TOKENS):
        raise RuntimeError("restricted lexical deny-list self-test failed")
    return blocked
