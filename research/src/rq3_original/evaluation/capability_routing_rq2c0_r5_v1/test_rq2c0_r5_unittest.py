"""Conformance and adversarial tests for the RQ2-C0-R5 contract freeze."""

from __future__ import annotations

from dataclasses import fields, replace
import hashlib
import json
import math
import re
import subprocess
import unicodedata
import unittest
from unittest.mock import patch

from evaluation.capability_routing_rq2c0_r2_v1.executable_retrieval_contract import (
    RetrievalPlanV1_1,
)
from evaluation.capability_routing_rq2c0_r4_v1.composite_payload_episode_validator_v1_3 import (
    PayloadBindingValidationV1_3,
)
from evaluation.capability_routing_rq2c0_r4_v1.payload_linkage_schema import (
    MemoryEpisodeV1_2,
    MemoryPayloadRefV1_2,
    MemoryPayloadV1_2,
)
from evaluation.capability_routing_rq2c0_r4_v1.student_scope_hash_contract import (
    FIXED_TEST_SCOPE_ID,
    derive_storage_namespace_v1,
    derive_student_scope_hash_v1,
)

from . import (
    EXPECTED_EFFECTIVE_ADMISSION,
    EXPECTED_EFFECTIVE_RETRIEVAL,
    EXPECTED_FIXTURE_BANK_SHA256,
    EXPECTED_FIXTURE_BANK_SIZE,
    EXPECTED_FIXTURE_RECORD_COUNT,
    EXPECTED_GOLD_BUNDLE_SHA256,
    EXPECTED_P1_POLICY,
    EXPECTED_PAYLOAD_SCOPE,
    EXPECTED_PRIMARY_POLICY_ID,
    EXPECTED_R4_PAYLOAD_BINDING,
    EXPECTED_R4_REVIEW_ZIP_SHA256,
    FIXTURE_BANK_PATH,
    INTERVAL_CONTRACT_ID,
    R4_REVIEW_ZIP,
    RESULT_BRANCH,
    ROOT,
    STARTING_HEAD,
    STARTING_PARENT,
    VALIDATED_PLAN_ID,
    sha256_file,
)
from .composite_validated_bundle_validator_v1_4 import (
    EXPECTED_VALIDATION_TRACE,
    validate_and_bind_payload_v1_4,
)
from .effective_contract import (
    effective_persistent_memory_contract_v1_4,
    validation_time_integrity_authority,
)
from .opaque_identifier_v1 import (
    OpaqueIdentifierError,
    validate_governed_memory_identifiers_v1,
    validate_opaque_identifier_v1,
)
from .r4_identity import (
    protected_manifest,
    verify_fixture_identity,
    verify_r2_output_checksums,
    verify_r2_tracked_history,
    verify_r3_output_checksums,
    verify_r3_tracked_history,
    verify_r4_output_checksums,
    verify_r4_tracked_history,
    verify_starting_authority,
)
from .retrieval_time_integrity_v1 import (
    RetrievalTimeIntegrityError,
    parse_timezone_aware_iso8601_v1_1,
    temporal_validity_aware_v1_1,
    validate_episode_validity_interval_v1_1,
)
from .validate_rq2c0_r5 import (
    assert_partition_access_allowed,
    build_all,
    expected_review_members,
    governed_text_leak_scan,
    parse_output_checksums,
    protected_source_comparison,
    staged_allowlist,
    validate_all,
    validate_no_implementation,
    validate_output_checksums,
    validate_python_ast,
    validate_review_package_contract,
    validate_safe_outputs,
)
from .validated_bundle_fingerprint_v1 import (
    FingerprintError,
    bundle_fingerprint_contract,
    canonical_component_bytes_v1,
    component_fingerprints_v1,
    episode_fingerprint_v1,
    input_binding_fingerprint_v1_4,
    payload_fingerprint_v1,
    payload_ref_fingerprint_v1,
)
from .validated_bundle_guard_v1_4 import (
    GUARDED_INTERFACES_V1_4,
    require_validated_bundle_for_interface_v1_4,
)
from .validated_memory_bundle_v1_4 import (
    BundleValidationError,
    ValidatedPersistentMemoryBundleV1_4,
    verify_validated_bundle_v1_4,
)
from .validated_retrieval_plan_v1_2 import (
    ValidatedRetrievalPlanError,
    ValidatedRetrievalPlanV1_2,
    validate_and_bind_retrieval_plan_v1_2,
    validated_retrieval_plan_contract,
    verify_validated_retrieval_plan_v1_2,
)


TEST_TEXT = "x"
TEST_QUERY = "q"
COMPOSITE_MODULE = (
    "evaluation.capability_routing_rq2c0_r5_v1."
    "composite_validated_bundle_validator_v1_4"
)


def _git(*args: str) -> str:
    return subprocess.check_output(
        ["git", *args], cwd=ROOT, text=True, stderr=subprocess.STDOUT
    ).strip()


def _triplet(
    *,
    suffix: str = "001",
    text: str = TEST_TEXT,
    valid_from: str = "2026-08-27T09:00:00Z",
    valid_until: str | None = "2026-08-27T12:00:00Z",
) -> tuple[MemoryEpisodeV1_2, MemoryPayloadRefV1_2, MemoryPayloadV1_2]:
    canonical = text.strip().encode("utf-8")
    content_hash = hashlib.sha256(canonical).hexdigest()
    scope_hash = derive_student_scope_hash_v1(FIXED_TEST_SCOPE_ID)
    namespace = derive_storage_namespace_v1(scope_hash)
    memory_id = f"memory-{suffix}"
    payload_id = f"payload-{suffix}"
    episode_id = f"episode-{suffix}"
    turn_id = f"turn-{suffix}"
    payload = MemoryPayloadV1_2(
        payload_id=payload_id,
        memory_id=memory_id,
        student_scope_hash=scope_hash,
        storage_namespace=namespace,
        canonical_text=text,
        structured_value=None,
        content_type="text/plain",
        locale="und",
        encoding="UTF-8",
        source_episode_id=episode_id,
        source_turn_id=turn_id,
        content_hash=content_hash,
    )
    payload_ref = MemoryPayloadRefV1_2(
        payload_id=payload_id,
        memory_id=memory_id,
        student_scope_hash=scope_hash,
        content_hash=content_hash,
        content_length=len(canonical),
        content_type="text/plain",
        locale="und",
        encoding="UTF-8",
        storage_namespace=namespace,
        local_only=True,
        encrypted_at_rest_required=True,
        created_at="2026-08-27T10:02:00Z",
    )
    episode = MemoryEpisodeV1_2(
        memory_id=memory_id,
        student_scope_id=FIXED_TEST_SCOPE_ID,
        episode_id=episode_id,
        source_turn_id=turn_id,
        memory_type="GOAL",
        raw_content_hash=content_hash,
        created_at="2026-08-27T10:01:00Z",
        valid_from=valid_from,
        valid_until=valid_until,
        status="ACTIVE",
        explicitness="EXPLICIT_STUDENT",
        confidence=1.0,
        entities=(),
        supersedes_memory_id=None,
        provenance={},
        embedding_hash=None,
        payload_id=payload_id,
        event_time="2026-08-27T10:00:00Z",
        ingested_at="2026-08-27T10:02:00Z",
        timezone="UTC",
        status_reason="CREATED",
        source_kind="STRUCTURED_EXPLICIT_USER_ASSERTION",
        projection_eligible=True,
    )
    return episode, payload_ref, payload


def _plan(
    *, query_time: str = "2026-08-27T10:00:00Z", query: str = TEST_QUERY
) -> RetrievalPlanV1_1:
    return RetrievalPlanV1_1(
        student_scope_id=FIXED_TEST_SCOPE_ID,
        query_time=query_time,
        target_memory_types=("GOAL",),
        original_query=query,
        resolved_query=query,
        resolver_authorised=False,
        memory_required=True,
    )


class RQ2C0R5ContractTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.fixture_bytes_before = FIXTURE_BANK_PATH.read_bytes()
        cls.first_build = build_all()

    # Starting identities and the narrow user authority.
    def test_001_starting_branch_head_parent(self) -> None:
        self.assertEqual(_git("branch", "--show-current"), RESULT_BRANCH)
        self.assertEqual(_git("rev-parse", f"{STARTING_HEAD}^"), STARTING_PARENT)
        self.assertEqual(_git("merge-base", STARTING_HEAD, "HEAD"), STARTING_HEAD)
        self.assertIn(
            int(_git("rev-list", "--count", f"{STARTING_HEAD}..HEAD")), (0, 1)
        )

    def test_002_r4_review_zip_identity(self) -> None:
        self.assertTrue(R4_REVIEW_ZIP.is_file())
        self.assertEqual(sha256_file(R4_REVIEW_ZIP), EXPECTED_R4_REVIEW_ZIP_SHA256)

    def test_003_r2_r3_r4_output_checksums(self) -> None:
        self.assertEqual(verify_r2_output_checksums()["checksum_count"], 36)
        self.assertEqual(verify_r3_output_checksums()["checksum_count"], 18)
        self.assertEqual(verify_r4_output_checksums()["checksum_count"], 22)

    def test_004_r2_r3_r4_tracked_history(self) -> None:
        self.assertEqual(verify_r2_tracked_history()["tracked_file_count"], 31)
        self.assertEqual(verify_r3_tracked_history()["tracked_file_count"], 16)
        self.assertEqual(verify_r4_tracked_history()["tracked_file_count"], 20)

    def test_005_fixture_identity(self) -> None:
        observed = verify_fixture_identity()
        self.assertEqual(observed["sha256"], EXPECTED_FIXTURE_BANK_SHA256)
        self.assertEqual(observed["size_bytes"], EXPECTED_FIXTURE_BANK_SIZE)
        self.assertEqual(observed["record_count"], EXPECTED_FIXTURE_RECORD_COUNT)

    def test_006_frozen_research_identities(self) -> None:
        authority = verify_starting_authority()
        self.assertEqual(authority["p1_policy"], EXPECTED_P1_POLICY)
        self.assertEqual(authority["gold_bundle_sha256"], EXPECTED_GOLD_BUNDLE_SHA256)
        self.assertEqual(authority["primary_policy_id"], EXPECTED_PRIMARY_POLICY_ID)
        self.assertEqual(authority["effective_retrieval"], EXPECTED_EFFECTIVE_RETRIEVAL)
        self.assertEqual(authority["effective_admission"], EXPECTED_EFFECTIVE_ADMISSION)
        self.assertEqual(authority["payload_scope"], EXPECTED_PAYLOAD_SCOPE)
        self.assertEqual(authority["r4_payload_binding"], EXPECTED_R4_PAYLOAD_BINDING)

    def test_007_user_authority_is_final_but_narrow(self) -> None:
        authority = validation_time_integrity_authority()
        self.assertEqual(len(authority["authorised_corrections"]), 6)
        for key in (
            "fixture_text_change_authorised",
            "fixture_membership_change_authorised",
            "fixture_expected_decision_change_authorised",
            "fixture_hash_change_authorised",
            "P1_change_authorised",
            "Capability_Gold_change_authorised",
            "human_annotation_change_authorised",
            "retrieval_threshold_change_authorised",
            "primary_policy_identity_change_authorised",
            "model_output_change_authorised",
            "production_behaviour_change_authorised",
        ):
            self.assertFalse(authority[key])

    # Opaque governed identifiers.
    def test_008_valid_opaque_ids_and_all_occurrences(self) -> None:
        self.assertIsNone(validate_opaque_identifier_v1("memory-001", "memory_id"))
        self.assertIsNone(validate_governed_memory_identifiers_v1(*_triplet()))

    def test_009_each_governed_id_empty_rejected(self) -> None:
        for field_name in ("memory_id", "payload_id", "episode_id", "source_turn_id"):
            with self.subTest(field_name=field_name), self.assertRaisesRegex(
                OpaqueIdentifierError, "IDENTIFIER_EMPTY"
            ):
                validate_opaque_identifier_v1("", field_name)

    def test_010_non_string_whitespace_and_surrounding_whitespace_rejected(self) -> None:
        cases = (
            (None, "IDENTIFIER_NOT_STRING"),
            ("   ", "IDENTIFIER_SURROUNDING_WHITESPACE"),
            (" memory-001", "IDENTIFIER_SURROUNDING_WHITESPACE"),
            ("memory-001 ", "IDENTIFIER_SURROUNDING_WHITESPACE"),
        )
        for value, code in cases:
            with self.subTest(value=value), self.assertRaisesRegex(
                OpaqueIdentifierError, code
            ):
                validate_opaque_identifier_v1(value, "memory_id")  # type: ignore[arg-type]

    def test_011_nul_and_non_nfc_rejected(self) -> None:
        with self.assertRaisesRegex(OpaqueIdentifierError, "IDENTIFIER_CONTAINS_NUL"):
            validate_opaque_identifier_v1("memory\x00001", "memory_id")
        decomposed = unicodedata.normalize("NFD", "é")
        with self.assertRaisesRegex(OpaqueIdentifierError, "IDENTIFIER_NOT_NFC"):
            validate_opaque_identifier_v1(decomposed, "memory_id")

    def test_012_utf8_length_boundary(self) -> None:
        exactly_256 = "é" * 128
        self.assertEqual(len(exactly_256.encode("utf-8")), 256)
        self.assertIsNone(validate_opaque_identifier_v1(exactly_256, "memory_id"))
        with self.assertRaisesRegex(OpaqueIdentifierError, "IDENTIFIER_TOO_LONG"):
            validate_opaque_identifier_v1(exactly_256 + "x", "memory_id")

    def test_013_equal_empty_ids_cannot_create_bundle(self) -> None:
        episode, ref, payload = _triplet()
        empty = (
            replace(episode, memory_id=""),
            replace(ref, memory_id=""),
            replace(payload, memory_id=""),
        )
        with self.assertRaisesRegex(OpaqueIdentifierError, "IDENTIFIER_EMPTY"):
            validate_and_bind_payload_v1_4(*empty)

    def test_014_each_occurrence_is_independently_validated(self) -> None:
        episode, ref, payload = _triplet()
        cases = (
            (replace(episode, source_turn_id=""), ref, payload),
            (episode, replace(ref, payload_id=""), payload),
            (episode, ref, replace(payload, source_episode_id="")),
            (episode, ref, replace(payload, source_turn_id="")),
        )
        for values in cases:
            with self.subTest(values=values), self.assertRaises(OpaqueIdentifierError):
                validate_governed_memory_identifiers_v1(*values)

    # Timezone-aware intervals and query times.
    def test_015_aware_time_parsing_and_offset_equivalence(self) -> None:
        zulu = parse_timezone_aware_iso8601_v1_1(
            "2026-08-27T09:00:00Z", "valid_from"
        )
        offset = parse_timezone_aware_iso8601_v1_1(
            "2026-08-27T10:00:00+01:00", "valid_from"
        )
        self.assertEqual(zulu, offset)
        self.assertEqual(zulu.isoformat(), "2026-08-27T09:00:00+00:00")

    def test_016_valid_from_naive_and_invalid_rejected(self) -> None:
        for value, code in (
            ("2026-08-27T09:00:00", "NAIVE_VALID_FROM"),
            ("not-time", "INVALID_VALID_FROM"),
        ):
            with self.subTest(value=value), self.assertRaisesRegex(
                RetrievalTimeIntegrityError, code
            ):
                parse_timezone_aware_iso8601_v1_1(value, "valid_from")

    def test_017_valid_until_naive_and_invalid_rejected(self) -> None:
        for value, code in (
            ("2026-08-27T12:00:00", "NAIVE_VALID_UNTIL"),
            ("not-time", "INVALID_VALID_UNTIL"),
        ):
            with self.subTest(value=value), self.assertRaisesRegex(
                RetrievalTimeIntegrityError, code
            ):
                parse_timezone_aware_iso8601_v1_1(value, "valid_until")

    def test_018_null_and_increasing_episode_intervals_accepted(self) -> None:
        for end in (None, "2026-08-27T12:00:00Z"):
            episode, _, _ = _triplet(valid_until=end)
            starts, ends = validate_episode_validity_interval_v1_1(episode)
            self.assertIsNotNone(starts.tzinfo)
            self.assertEqual(ends is None, end is None)

    def test_019_equal_and_reversed_intervals_rejected(self) -> None:
        for start, end in (
            ("2026-08-27T12:00:00Z", "2026-08-27T12:00:00Z"),
            ("2026-08-27T13:00:00Z", "2026-08-27T12:00:00Z"),
        ):
            episode, _, _ = _triplet(valid_from=start, valid_until=end)
            with self.assertRaisesRegex(
                RetrievalTimeIntegrityError,
                "VALID_INTERVAL_NOT_STRICTLY_INCREASING",
            ):
                validate_episode_validity_interval_v1_1(episode)

    def test_020_query_time_aware_accepted_naive_and_invalid_rejected(self) -> None:
        self.assertIsNotNone(
            parse_timezone_aware_iso8601_v1_1(
                "2026-08-27T10:00:00+01:00", "query_time"
            ).tzinfo
        )
        for value, code in (
            ("2026-08-27T10:00:00", "NAIVE_QUERY_TIME"),
            ("not-time", "INVALID_QUERY_TIME"),
        ):
            with self.subTest(value=value), self.assertRaisesRegex(
                RetrievalTimeIntegrityError, code
            ):
                parse_timezone_aware_iso8601_v1_1(value, "query_time")

    def test_021_start_inclusive_and_before_start_invalid(self) -> None:
        self.assertTrue(
            temporal_validity_aware_v1_1(
                "2026-08-27T09:00:00Z",
                "2026-08-27T12:00:00Z",
                "2026-08-27T09:00:00Z",
            )
        )
        self.assertFalse(
            temporal_validity_aware_v1_1(
                "2026-08-27T09:00:00Z",
                "2026-08-27T12:00:00Z",
                "2026-08-27T08:59:59Z",
            )
        )

    def test_022_end_exclusive_and_after_end_invalid(self) -> None:
        for query, expected in (
            ("2026-08-27T11:59:59Z", True),
            ("2026-08-27T12:00:00Z", False),
            ("2026-08-27T12:00:01Z", False),
        ):
            self.assertEqual(
                temporal_validity_aware_v1_1(
                    "2026-08-27T09:00:00Z",
                    "2026-08-27T12:00:00Z",
                    query,
                ),
                expected,
            )

    def test_023_null_end_and_offset_equivalent_instants(self) -> None:
        self.assertTrue(
            temporal_validity_aware_v1_1(
                "2026-08-27T09:00:00Z", None, "2027-08-27T09:00:00Z"
            )
        )
        left = temporal_validity_aware_v1_1(
            "2026-08-27T09:00:00Z",
            "2026-08-27T12:00:00Z",
            "2026-08-27T10:00:00Z",
        )
        right = temporal_validity_aware_v1_1(
            "2026-08-27T10:00:00+01:00",
            "2026-08-27T07:00:00-05:00",
            "2026-08-27T11:00:00+01:00",
        )
        self.assertEqual(left, right)

    def test_024_descriptive_timezone_cannot_repair_naive_fields(self) -> None:
        episode, _, _ = _triplet()
        for field_name in ("valid_from", "valid_until"):
            changed = replace(episode, **{field_name: "2026-08-27T09:00:00"})
            with self.subTest(field_name=field_name), self.assertRaises(
                RetrievalTimeIntegrityError
            ):
                validate_episode_validity_interval_v1_1(changed)
        with self.assertRaisesRegex(RetrievalTimeIntegrityError, "NAIVE_QUERY_TIME"):
            parse_timezone_aware_iso8601_v1_1(
                "2026-08-27T09:00:00", "query_time"
            )

    # Canonical component and composite fingerprinting.
    def test_025_component_fingerprints_are_deterministic(self) -> None:
        episode, ref, payload = _triplet()
        self.assertEqual(episode_fingerprint_v1(episode), episode_fingerprint_v1(episode))
        self.assertEqual(payload_ref_fingerprint_v1(ref), payload_ref_fingerprint_v1(ref))
        self.assertEqual(payload_fingerprint_v1(payload), payload_fingerprint_v1(payload))
        self.assertEqual(
            component_fingerprints_v1(episode, ref, payload),
            component_fingerprints_v1(episode, ref, payload),
        )

    def test_026_one_bound_field_changes_fingerprint(self) -> None:
        episode, ref, payload = _triplet()
        original = component_fingerprints_v1(episode, ref, payload)
        changed = component_fingerprints_v1(
            replace(episode, valid_until="2026-08-27T12:30:00Z"), ref, payload
        )
        self.assertNotEqual(original.episode_fingerprint, changed.episode_fingerprint)
        self.assertNotEqual(
            original.input_binding_fingerprint, changed.input_binding_fingerprint
        )

    def test_027_mapping_order_canonical_and_sequence_order_significant(self) -> None:
        self.assertEqual(
            canonical_component_bytes_v1({"b": 2, "a": 1}),
            canonical_component_bytes_v1({"a": 1, "b": 2}),
        )
        self.assertNotEqual(
            canonical_component_bytes_v1(["a", "b"]),
            canonical_component_bytes_v1(["b", "a"]),
        )
        self.assertNotEqual(
            canonical_component_bytes_v1(("a", "b")),
            canonical_component_bytes_v1(("b", "a")),
        )

    def test_028_nan_and_infinity_rejected(self) -> None:
        for value in (math.nan, math.inf, -math.inf):
            with self.subTest(value=value), self.assertRaisesRegex(
                FingerprintError, "NON_FINITE_NUMBER_PROHIBITED"
            ):
                canonical_component_bytes_v1({"value": value})

    def test_029_all_fingerprints_are_lowercase_hex(self) -> None:
        fingerprints = component_fingerprints_v1(*_triplet())
        for value in (
            fingerprints.episode_fingerprint,
            fingerprints.payload_ref_fingerprint,
            fingerprints.payload_fingerprint,
            fingerprints.input_binding_fingerprint,
        ):
            self.assertRegex(value, r"^[0-9a-f]{64}$")
        with self.assertRaisesRegex(FingerprintError, "INVALID_COMPONENT_FINGERPRINT"):
            input_binding_fingerprint_v1_4("A" * 64, "0" * 64, "0" * 64)

    def test_030_fingerprint_is_integrity_binding_not_authentication(self) -> None:
        contract = bundle_fingerprint_contract()
        self.assertTrue(contract["integrity_binding"])
        self.assertFalse(contract["secret_mac"])
        self.assertFalse(contract["digital_signature"])
        self.assertFalse(contract["caller_identity_authentication"])

    # Exact-input-bound validated bundle and transfer resistance.
    def test_031_valid_inputs_produce_exact_bundle(self) -> None:
        episode, ref, payload = _triplet()
        bundle = validate_and_bind_payload_v1_4(episode, ref, payload)
        self.assertIs(bundle.episode, episode)
        self.assertIs(bundle.payload_ref, ref)
        self.assertIs(bundle.payload, payload)
        self.assertEqual(bundle.validation_trace, EXPECTED_VALIDATION_TRACE)
        self.assertIsNone(verify_validated_bundle_v1_4(bundle))

    def test_032_invalid_r4_binding_produces_no_bundle(self) -> None:
        episode, ref, payload = _triplet()
        with self.assertRaisesRegex(BundleValidationError, "R4_COMPOSITE"):
            validate_and_bind_payload_v1_4(
                episode, ref, replace(payload, content_hash="0" * 64)
            )

    def test_033_invalid_identifier_and_interval_produce_no_bundle(self) -> None:
        episode, ref, payload = _triplet()
        with self.assertRaises(OpaqueIdentifierError):
            validate_and_bind_payload_v1_4(
                replace(episode, source_turn_id=""),
                ref,
                replace(payload, source_turn_id=""),
            )
        with self.assertRaises(RetrievalTimeIntegrityError):
            validate_and_bind_payload_v1_4(
                replace(episode, valid_until="2026-08-27T08:00:00Z"), ref, payload
            )

    def test_034_free_standing_receipts_and_tokens_rejected(self) -> None:
        receipt = PayloadBindingValidationV1_3(
            binding_valid=True,
            failed_stage=None,
            failure_code=None,
            stage_call_counts=(("R2", 1), ("R3", 1), ("R4", 1)),
        )
        for value in (receipt, True, {"binding_valid": True}, "0" * 64):
            with self.subTest(value=type(value).__name__), self.assertRaisesRegex(
                PermissionError, "UNVALIDATED_OR_STALE_BUNDLE_BLOCKED"
            ):
                require_validated_bundle_for_interface_v1_4(
                    value, "EMBEDDING_INPUT_BUILDER"  # type: ignore[arg-type]
                )

    def test_035_payload_plus_separate_receipt_rejected_by_interface_shape(self) -> None:
        _, _, payload = _triplet()
        receipt = PayloadBindingValidationV1_3(True, None, None, (("R2", 1),))
        with self.assertRaises(TypeError):
            require_validated_bundle_for_interface_v1_4(  # type: ignore[call-arg]
                payload, receipt, "EMBEDDING_INPUT_BUILDER"
            )

    def test_036_bundle_reused_for_different_payload_rejected(self) -> None:
        bundle = validate_and_bind_payload_v1_4(*_triplet())
        _, _, other_payload = _triplet(suffix="002", text="y")
        with self.assertRaisesRegex(PermissionError, "UNVALIDATED_OR_STALE"):
            require_validated_bundle_for_interface_v1_4(
                replace(bundle, payload=other_payload), "EMBEDDING_INPUT_BUILDER"
            )

    def test_037_bundle_reused_for_different_episode_rejected(self) -> None:
        bundle = validate_and_bind_payload_v1_4(*_triplet())
        other_episode, _, _ = _triplet(suffix="002", text="y")
        with self.assertRaisesRegex(PermissionError, "UNVALIDATED_OR_STALE"):
            require_validated_bundle_for_interface_v1_4(
                replace(bundle, episode=other_episode),
                "PERSISTENT_RETRIEVAL_CANDIDATE_BUILDER",
            )

    def test_038_episode_mutations_rejected(self) -> None:
        bundle = validate_and_bind_payload_v1_4(*_triplet())
        changes = (
            {"valid_until": "2026-08-27T12:30:00Z"},
            {"source_turn_id": "turn-002"},
            {"memory_id": "memory-002"},
        )
        for change in changes:
            mutated = replace(bundle, episode=replace(bundle.episode, **change))
            with self.subTest(change=change), self.assertRaises(PermissionError):
                require_validated_bundle_for_interface_v1_4(
                    mutated, "STATE_PROJECTION_BUILDER"
                )

    def test_039_payload_reference_mutations_rejected(self) -> None:
        bundle = validate_and_bind_payload_v1_4(*_triplet())
        changes = (
            {"student_scope_hash": "0" * 64},
            {"content_length": bundle.payload_ref.content_length + 1},
            {"created_at": "2026-08-27T10:03:00Z"},
            {"storage_namespace": "persistent-memory-v1:" + "0" * 64},
        )
        for change in changes:
            mutated = replace(bundle, payload_ref=replace(bundle.payload_ref, **change))
            with self.subTest(change=change), self.assertRaises(PermissionError):
                require_validated_bundle_for_interface_v1_4(
                    mutated, "MEMORY_ADMISSION_BUILDER"
                )

    def test_040_payload_mutation_rejected(self) -> None:
        bundle = validate_and_bind_payload_v1_4(*_triplet())
        mutated = replace(
            bundle,
            payload=replace(bundle.payload, source_turn_id="turn-002"),
        )
        with self.assertRaises(PermissionError):
            require_validated_bundle_for_interface_v1_4(
                mutated, "GENERATION_EVIDENCE_BUILDER"
            )

    def test_041_component_and_composite_fingerprint_swaps_rejected(self) -> None:
        first = validate_and_bind_payload_v1_4(*_triplet())
        second = validate_and_bind_payload_v1_4(*_triplet(suffix="002", text="y"))
        changes = (
            {"episode_fingerprint": second.episode_fingerprint},
            {"payload_ref_fingerprint": second.payload_ref_fingerprint},
            {"payload_fingerprint": second.payload_fingerprint},
            {"input_binding_fingerprint": second.input_binding_fingerprint},
        )
        for change in changes:
            with self.subTest(change=next(iter(change))), self.assertRaises(
                BundleValidationError
            ):
                verify_validated_bundle_v1_4(replace(first, **change))

    def test_042_manually_constructed_invalid_bundle_rejected(self) -> None:
        valid = validate_and_bind_payload_v1_4(*_triplet())
        forged = ValidatedPersistentMemoryBundleV1_4(
            **{**valid.__dict__, "r5_validator_id": "FORGED"}
        )
        with self.assertRaisesRegex(BundleValidationError, "VALIDATOR_ID_MISMATCH"):
            verify_validated_bundle_v1_4(forged)

    def test_043_legal_bundle_deterministic_double_validation(self) -> None:
        first = validate_and_bind_payload_v1_4(*_triplet())
        second = validate_and_bind_payload_v1_4(*_triplet())
        self.assertEqual(first, second)
        self.assertIsNone(verify_validated_bundle_v1_4(first))
        self.assertIsNone(verify_validated_bundle_v1_4(first))

    def test_044_all_five_downstream_interfaces_guarded(self) -> None:
        bundle = validate_and_bind_payload_v1_4(*_triplet())
        self.assertEqual(len(GUARDED_INTERFACES_V1_4), 5)
        for interface in GUARDED_INTERFACES_V1_4:
            with self.subTest(interface=interface):
                self.assertIsNone(
                    require_validated_bundle_for_interface_v1_4(bundle, interface)
                )

    def test_045_unknown_interface_rejected(self) -> None:
        with self.assertRaisesRegex(ValueError, "UNKNOWN_GUARDED_INTERFACE"):
            require_validated_bundle_for_interface_v1_4(
                validate_and_bind_payload_v1_4(*_triplet()), "UNKNOWN"
            )

    # Validated retrieval plan.
    def test_046_valid_plan_is_utc_bound_and_verifiable(self) -> None:
        validated = validate_and_bind_retrieval_plan_v1_2(_plan())
        self.assertIsInstance(validated, ValidatedRetrievalPlanV1_2)
        self.assertEqual(validated.query_time_utc, "2026-08-27T10:00:00+00:00")
        self.assertEqual(validated.validation_contract_id, VALIDATED_PLAN_ID)
        self.assertIsNone(verify_validated_retrieval_plan_v1_2(validated))

    def test_047_naive_and_invalid_query_time_plans_rejected(self) -> None:
        for query_time, code in (
            ("2026-08-27T10:00:00", "NAIVE_QUERY_TIME"),
            ("bad", "INVALID_QUERY_TIME"),
        ):
            with self.subTest(query_time=query_time), self.assertRaisesRegex(
                RetrievalTimeIntegrityError, code
            ):
                validate_and_bind_retrieval_plan_v1_2(_plan(query_time=query_time))

    def test_048_plan_fingerprint_deterministic_and_change_sensitive(self) -> None:
        first = validate_and_bind_retrieval_plan_v1_2(_plan())
        second = validate_and_bind_retrieval_plan_v1_2(_plan())
        changed = validate_and_bind_retrieval_plan_v1_2(_plan(query="q2"))
        self.assertEqual(first.plan_fingerprint, second.plan_fingerprint)
        self.assertNotEqual(first.plan_fingerprint, changed.plan_fingerprint)
        self.assertRegex(first.plan_fingerprint, r"^[0-9a-f]{64}$")

    def test_049_plan_mutation_and_raw_plan_not_authorised(self) -> None:
        valid = validate_and_bind_retrieval_plan_v1_2(_plan())
        with self.assertRaisesRegex(
            ValidatedRetrievalPlanError, "STALE_OR_MUTATED_RETRIEVAL_PLAN"
        ):
            verify_validated_retrieval_plan_v1_2(
                replace(valid, original_query="different")
            )
        effective = effective_persistent_memory_contract_v1_4()
        self.assertTrue(
            effective["prohibited_rq2c1_interfaces"][
                "r2_unvalidated_retrieval_plan_v1_1"
            ]
        )

    def test_050_plan_has_no_gold_source_or_fixture_expected_fields(self) -> None:
        names = {field.name for field in fields(ValidatedRetrievalPlanV1_2)}
        prohibited = {
            "gold",
            "source_role",
            "expected_decision",
            "fixture_expected_fields",
        }
        self.assertTrue(names.isdisjoint(prohibited))
        contract = validated_retrieval_plan_contract()
        self.assertFalse(contract["gold_fields_allowed"])
        self.assertFalse(contract["source_role_allowed"])
        self.assertFalse(contract["fixture_expected_fields_allowed"])

    # Composite stage order, exact invocation, and short-circuiting.
    def test_051_creation_stages_called_exactly_once(self) -> None:
        import evaluation.capability_routing_rq2c0_r5_v1.composite_validated_bundle_validator_v1_4 as module

        with patch(
            COMPOSITE_MODULE + ".validate_persistent_memory_payload_binding_v1_3",
            wraps=module.validate_persistent_memory_payload_binding_v1_3,
        ) as r4, patch(
            COMPOSITE_MODULE + ".validate_governed_memory_identifiers_v1",
            wraps=module.validate_governed_memory_identifiers_v1,
        ) as identifiers, patch(
            COMPOSITE_MODULE + ".validate_episode_validity_interval_v1_1",
            wraps=module.validate_episode_validity_interval_v1_1,
        ) as interval, patch(
            COMPOSITE_MODULE + ".component_fingerprints_v1",
            wraps=module.component_fingerprints_v1,
        ) as fingerprint:
            validate_and_bind_payload_v1_4(*_triplet())
            r4.assert_called_once()
            identifiers.assert_called_once()
            interval.assert_called_once()
            fingerprint.assert_called_once()

    def test_052_r4_failure_short_circuits_every_r5_stage(self) -> None:
        with patch(
            COMPOSITE_MODULE + ".validate_persistent_memory_payload_binding_v1_3",
            side_effect=ValueError("R4 failure"),
        ), patch(
            COMPOSITE_MODULE + ".validate_governed_memory_identifiers_v1"
        ) as identifiers, patch(
            COMPOSITE_MODULE + ".validate_episode_validity_interval_v1_1"
        ) as interval, patch(
            COMPOSITE_MODULE + ".component_fingerprints_v1"
        ) as fingerprint:
            with self.assertRaisesRegex(ValueError, "R4 failure"):
                validate_and_bind_payload_v1_4(*_triplet())
            identifiers.assert_not_called()
            interval.assert_not_called()
            fingerprint.assert_not_called()

    def test_053_identifier_failure_short_circuits_later_stages(self) -> None:
        with patch(
            COMPOSITE_MODULE + ".validate_governed_memory_identifiers_v1",
            side_effect=OpaqueIdentifierError("IDENTIFIER_EMPTY", "memory_id"),
        ), patch(
            COMPOSITE_MODULE + ".validate_episode_validity_interval_v1_1"
        ) as interval, patch(
            COMPOSITE_MODULE + ".component_fingerprints_v1"
        ) as fingerprint:
            with self.assertRaises(OpaqueIdentifierError):
                validate_and_bind_payload_v1_4(*_triplet())
            interval.assert_not_called()
            fingerprint.assert_not_called()

    def test_054_interval_failure_short_circuits_fingerprint(self) -> None:
        with patch(
            COMPOSITE_MODULE + ".validate_episode_validity_interval_v1_1",
            side_effect=RetrievalTimeIntegrityError("INVALID_VALID_FROM"),
        ), patch(
            COMPOSITE_MODULE + ".component_fingerprints_v1"
        ) as fingerprint:
            with self.assertRaises(RetrievalTimeIntegrityError):
                validate_and_bind_payload_v1_4(*_triplet())
            fingerprint.assert_not_called()

    def test_055_creation_trace_is_complete_and_effective(self) -> None:
        bundle = validate_and_bind_payload_v1_4(*_triplet())
        self.assertEqual(
            dict(bundle.validation_trace),
            {
                "R2": 1,
                "R3": 1,
                "R4": 1,
                "R5_IDENTIFIER": 1,
                "R5_INTERVAL": 1,
                "R5_FINGERPRINT": 1,
            },
        )

    # Effective contract, immutable history, and safe deliverables.
    def test_056_effective_contract_points_only_to_r5_interfaces(self) -> None:
        effective = effective_persistent_memory_contract_v1_4()
        self.assertEqual(
            effective["effective_validated_bundle"],
            "PERSISTENT_MEMORY_VALIDATED_BUNDLE_V1_4",
        )
        self.assertEqual(effective["effective_retrieval_plan"], VALIDATED_PLAN_ID)
        self.assertEqual(effective["effective_interval_contract"], INTERVAL_CONTRACT_ID)
        self.assertTrue(effective["bundle_required_for_all_downstream_interfaces"])
        self.assertFalse(effective["free_standing_validation_receipt_authorised"])
        self.assertFalse(effective["episode_timezone_authoritative"])
        self.assertEqual(len(effective["rq2c1_import_contract"]), 5)
        self.assertTrue(
            effective["prohibited_rq2c1_interfaces"][
                "r4_free_standing_validation_receipt"
            ]
        )
        self.assertTrue(
            effective["prohibited_rq2c1_interfaces"][
                "r2_naive_time_temporal_validity"
            ]
        )

    def test_057_fixture_membership_decisions_and_hash_unchanged(self) -> None:
        current = FIXTURE_BANK_PATH.read_bytes()
        self.assertEqual(current, self.fixture_bytes_before)
        self.assertEqual(hashlib.sha256(current).hexdigest(), EXPECTED_FIXTURE_BANK_SHA256)
        before_records = [json.loads(line) for line in self.fixture_bytes_before.splitlines()]
        after_records = [json.loads(line) for line in current.splitlines()]
        self.assertEqual(before_records, after_records)

    def test_058_p1_gold_human_and_primary_invariants(self) -> None:
        effective = effective_persistent_memory_contract_v1_4()
        self.assertTrue(effective["unchanged"]["fixtures"])
        self.assertTrue(effective["unchanged"]["P1"])
        self.assertTrue(effective["unchanged"]["Capability_Gold"])
        self.assertEqual(
            effective["unchanged"]["primary_policy_identity"],
            EXPECTED_PRIMARY_POLICY_ID,
        )
        preflight = json.loads(
            (
                ROOT
                / "evaluation/capability_routing_rq2c0_r5_v1/"
                "rq2c0_r5_preflight_report_v1.json"
            ).read_text(encoding="utf-8")
        )
        self.assertFalse(preflight["human_annotation_changed"])
        self.assertFalse(preflight["retrieval_threshold_changed"])

    def test_059_r2_r3_r4_and_protected_sources_unchanged(self) -> None:
        for verifier in (
            verify_r2_tracked_history,
            verify_r3_tracked_history,
            verify_r4_tracked_history,
        ):
            self.assertEqual(verifier()["status"], "PASS")
        self.assertEqual(protected_manifest()["status"], "PASS")
        self.assertEqual(
            protected_source_comparison()["protected_existing_change_count"], 0
        )

    def test_060_track_a_and_track_b_remain_sealed(self) -> None:
        for partition in ("TRACK_A", "TRACK_B"):
            with self.assertRaises(PermissionError):
                assert_partition_access_allowed(partition)

    def test_061_no_p2_store_retrieval_training_provider_or_network(self) -> None:
        self.assertEqual(validate_no_implementation()["forbidden_implementation_count"], 0)

    def test_062_python_ast_safe_outputs_and_staged_allowlist(self) -> None:
        self.assertEqual(validate_python_ast()["python_file_count"], 12)
        self.assertEqual(validate_safe_outputs()["safe_output_count"], 10)
        self.assertEqual(staged_allowlist()["status"], "PASS")

    def test_063_double_build_is_byte_identical(self) -> None:
        second = build_all()
        self.assertEqual(
            self.first_build["build_commitment_sha256"],
            second["build_commitment_sha256"],
        )

    def test_064_output_checksums_and_review_completeness(self) -> None:
        self.assertEqual(len(parse_output_checksums()), 26)
        self.assertEqual(validate_output_checksums()["referenced_output_count"], 26)
        self.assertEqual(
            validate_review_package_contract()["expected_review_member_count"], 31
        )
        self.assertEqual(len(expected_review_members()), 31)

    def test_065_governed_text_leak_scan(self) -> None:
        self.assertEqual(governed_text_leak_scan()["leak_count"], 0)

    def test_066_full_validator_passes(self) -> None:
        self.assertEqual(
            validate_all()["status"],
            "PASS_VALIDATED_BUNDLE_TIME_INTEGRITY_FREEZE",
        )


if __name__ == "__main__":
    unittest.main()
