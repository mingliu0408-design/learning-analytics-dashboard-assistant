"""Conformance and adversarial tests for the RQ2-C0-R4 integrity freeze."""

from __future__ import annotations

from dataclasses import replace
from datetime import datetime, timezone
import hashlib
import json
import subprocess
import unicodedata
import unittest
from unittest.mock import patch

from evaluation.capability_routing_rq2c0_r3_v1.payload_scope_v1_1 import (
    STRUCTURED_PAYLOAD_BLOCKER,
    validate_text_only_payload_scope_v1_1,
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
    EXPECTED_R3_REVIEW_ZIP_SHA256,
    FIXTURE_BANK_PATH,
    R3_REVIEW_ZIP,
    RESULT_BRANCH,
    ROOT,
    STARTING_HEAD,
    STARTING_PARENT,
    sha256_file,
)
from .composite_payload_episode_validator_v1_3 import (
    GUARDED_INTERFACES,
    PayloadBindingValidationV1_3,
    require_validated_payload_for_interface_v1_3,
    validate_persistent_memory_payload_binding_v1_3,
)
from .effective_contract import (
    effective_persistent_memory_contract_v1_3,
    payload_integrity_repair_authority,
)
from .payload_identity_binding import (
    PayloadIntegrityError,
    validate_payload_identity_binding_v1_2,
)
from .payload_linkage_schema import (
    MemoryEpisodeV1_2,
    MemoryPayloadRefV1_2,
    MemoryPayloadV1_2,
    payload_linkage_schema_contract,
)
from .payload_metadata_consistency import (
    canonical_payload_bytes_v1_2,
    validate_payload_metadata_consistency_v1_2,
)
from .r3_identity import (
    protected_manifest,
    verify_fixture_identity,
    verify_r2_output_checksums,
    verify_r2_tracked_history,
    verify_r3_output_checksums,
    verify_r3_tracked_history,
    verify_starting_authority,
)
from .student_scope_hash_contract import (
    FIXED_TEST_SCOPE_HASH,
    FIXED_TEST_SCOPE_ID,
    SCOPE_HASH_DOMAIN,
    ScopeContractError,
    derive_storage_namespace_v1,
    derive_student_scope_hash_v1,
    validate_pseudonymous_student_scope_id_v1,
    validate_storage_namespace_v1,
)
from .temporal_integrity_v1 import (
    parse_aware_iso8601_v1,
    validate_temporal_integrity_v1,
)
from .validate_rq2c0_r4 import (
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


TEST_TEXT = "x"


def _git(*args: str) -> str:
    return subprocess.check_output(
        ["git", *args], cwd=ROOT, text=True, stderr=subprocess.STDOUT
    ).strip()


def _triplet(
    text: str = TEST_TEXT,
) -> tuple[MemoryEpisodeV1_2, MemoryPayloadRefV1_2, MemoryPayloadV1_2]:
    canonical = text.strip().encode("utf-8")
    content_hash = hashlib.sha256(canonical).hexdigest()
    scope_hash = derive_student_scope_hash_v1(FIXED_TEST_SCOPE_ID)
    namespace = derive_storage_namespace_v1(scope_hash)
    payload = MemoryPayloadV1_2(
        payload_id="p-1",
        memory_id="m-1",
        student_scope_hash=scope_hash,
        storage_namespace=namespace,
        canonical_text=text,
        structured_value=None,
        content_type="text/plain",
        locale="und",
        encoding="UTF-8",
        source_episode_id="e-1",
        source_turn_id="t-1",
        content_hash=content_hash,
    )
    payload_ref = MemoryPayloadRefV1_2(
        payload_id="p-1",
        memory_id="m-1",
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
        memory_id="m-1",
        student_scope_id=FIXED_TEST_SCOPE_ID,
        episode_id="e-1",
        source_turn_id="t-1",
        memory_type="GOAL",
        raw_content_hash=content_hash,
        created_at="2026-08-27T10:01:00Z",
        valid_from="2026-08-27T10:00:00Z",
        valid_until=None,
        status="ACTIVE",
        explicitness="EXPLICIT_STUDENT",
        confidence=1.0,
        entities=(),
        supersedes_memory_id=None,
        provenance={},
        embedding_hash=None,
        payload_id="p-1",
        event_time="2026-08-27T10:00:00Z",
        ingested_at="2026-08-27T10:02:00Z",
        timezone="UTC",
        status_reason="CREATED",
        source_kind="STRUCTURED_EXPLICIT_USER_ASSERTION",
        projection_eligible=True,
    )
    return episode, payload_ref, payload


class RQ2C0R4ContractTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.fixture_sha_before = sha256_file(FIXTURE_BANK_PATH)
        cls.first_build = build_all()

    # Starting authority and historical identities.
    def test_001_starting_branch_head_parent(self) -> None:
        self.assertEqual(_git("branch", "--show-current"), RESULT_BRANCH)
        self.assertEqual(_git("rev-parse", f"{STARTING_HEAD}^"), STARTING_PARENT)
        self.assertEqual(_git("merge-base", STARTING_HEAD, "HEAD"), STARTING_HEAD)
        self.assertIn(int(_git("rev-list", "--count", f"{STARTING_HEAD}..HEAD")), (0, 1))

    def test_002_r3_review_zip_identity(self) -> None:
        self.assertTrue(R3_REVIEW_ZIP.is_file())
        self.assertEqual(sha256_file(R3_REVIEW_ZIP), EXPECTED_R3_REVIEW_ZIP_SHA256)

    def test_003_r2_and_r3_output_checksums(self) -> None:
        self.assertEqual(verify_r2_output_checksums()["checksum_count"], 36)
        self.assertEqual(verify_r3_output_checksums()["checksum_count"], 18)

    def test_004_r2_and_r3_tracked_history(self) -> None:
        self.assertEqual(verify_r2_tracked_history()["tracked_file_count"], 31)
        self.assertEqual(verify_r3_tracked_history()["tracked_file_count"], 16)

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

    def test_007_user_authority_is_narrow(self) -> None:
        authority = payload_integrity_repair_authority()
        self.assertEqual(len(authority["authorised_corrections"]), 5)
        self.assertFalse(authority["fixture_text_change_authorised"])
        self.assertFalse(authority["P1_change_authorised"])
        self.assertFalse(authority["production_behaviour_change_authorised"])

    # Pseudonymous identity and domain-separated hashing.
    def test_008_valid_pseudonymous_id(self) -> None:
        self.assertIsNone(validate_pseudonymous_student_scope_id_v1(FIXED_TEST_SCOPE_ID))

    def test_009_empty_and_whitespace_ids_rejected(self) -> None:
        for value in ("", " " + FIXED_TEST_SCOPE_ID, FIXED_TEST_SCOPE_ID + " "):
            with self.assertRaises(ScopeContractError):
                derive_student_scope_hash_v1(value)

    def test_010_nul_rejected(self) -> None:
        with self.assertRaisesRegex(ScopeContractError, "SCOPE_ID_NUL_PROHIBITED"):
            derive_student_scope_hash_v1(FIXED_TEST_SCOPE_ID + "\x00")

    def test_011_nfc_required(self) -> None:
        decomposed = unicodedata.normalize("NFD", "é")
        self.assertNotEqual(decomposed, unicodedata.normalize("NFC", decomposed))
        with self.assertRaisesRegex(ScopeContractError, "SCOPE_ID_NOT_NFC"):
            derive_student_scope_hash_v1(decomposed)

    def test_012_maximum_utf8_length(self) -> None:
        self.assertEqual(len(("é" * 128).encode("utf-8")), 256)
        self.assertRegex(derive_student_scope_hash_v1("é" * 128), r"^[0-9a-f]{64}$")
        with self.assertRaisesRegex(ScopeContractError, "SCOPE_ID_TOO_LONG"):
            derive_student_scope_hash_v1("é" * 129)

    def test_013_hash_determinism_and_fixed_vector(self) -> None:
        first = derive_student_scope_hash_v1(FIXED_TEST_SCOPE_ID)
        self.assertEqual(first, FIXED_TEST_SCOPE_HASH)
        self.assertEqual(first, derive_student_scope_hash_v1(FIXED_TEST_SCOPE_ID))

    def test_014_hash_domain_separation(self) -> None:
        plain = hashlib.sha256(FIXED_TEST_SCOPE_ID.encode("utf-8")).hexdigest()
        expected = hashlib.sha256(
            SCOPE_HASH_DOMAIN + FIXED_TEST_SCOPE_ID.encode("utf-8")
        ).hexdigest()
        self.assertNotEqual(plain, expected)
        self.assertEqual(expected, FIXED_TEST_SCOPE_HASH)

    def test_015_lowercase_hex_and_distinct_ids(self) -> None:
        other = FIXED_TEST_SCOPE_ID[:-1] + "2"
        left = derive_student_scope_hash_v1(FIXED_TEST_SCOPE_ID)
        right = derive_student_scope_hash_v1(other)
        self.assertRegex(left, r"^[0-9a-f]{64}$")
        self.assertNotEqual(left, right)

    # Namespace contract.
    def test_016_exact_namespace_derivation(self) -> None:
        expected = "persistent-memory-v1:" + FIXED_TEST_SCOPE_HASH
        self.assertEqual(derive_storage_namespace_v1(FIXED_TEST_SCOPE_HASH), expected)
        self.assertIsNone(validate_storage_namespace_v1(expected, FIXED_TEST_SCOPE_HASH))

    def test_017_wrong_prefix_or_suffix_rejected(self) -> None:
        for value in (
            "memory-v1:" + FIXED_TEST_SCOPE_HASH,
            "persistent-memory-v1:" + ("0" * 64),
        ):
            with self.assertRaisesRegex(ScopeContractError, "STORAGE_NAMESPACE_MISMATCH"):
                validate_storage_namespace_v1(value, FIXED_TEST_SCOPE_HASH)

    def test_018_namespace_paths_rejected(self) -> None:
        for value in (
            "persistent-memory-v1:../" + FIXED_TEST_SCOPE_HASH,
            "/persistent-memory-v1:" + FIXED_TEST_SCOPE_HASH,
            "persistent-memory-v1:\\" + FIXED_TEST_SCOPE_HASH,
            "persistent-memory-v1://" + FIXED_TEST_SCOPE_HASH,
        ):
            with self.assertRaisesRegex(ScopeContractError, "STORAGE_NAMESPACE_MISMATCH"):
                validate_storage_namespace_v1(value, FIXED_TEST_SCOPE_HASH)

    # Schema, identity, and provenance.
    def test_019_versioned_schema_and_private_boundary(self) -> None:
        contract = payload_linkage_schema_contract()
        self.assertEqual(contract["effective_episode_schema"], "MemoryEpisodeV1_2")
        self.assertFalse(contract["episode_contains_raw_payload_text"])
        self.assertFalse(contract["private_payload_contains_raw_student_scope_id"])
        self.assertFalse(contract["private_payload_git_eligible"])

    def test_020_valid_identity_and_provenance(self) -> None:
        self.assertIsNone(validate_payload_identity_binding_v1_2(*_triplet()))

    def test_021_memory_id_mismatch_rejected(self) -> None:
        episode, ref, payload = _triplet()
        with self.assertRaisesRegex(PayloadIntegrityError, "MEMORY_ID_MISMATCH"):
            validate_payload_identity_binding_v1_2(
                episode, ref, replace(payload, memory_id="m-2")
            )

    def test_022_payload_id_mismatch_rejected(self) -> None:
        episode, ref, payload = _triplet()
        with self.assertRaisesRegex(PayloadIntegrityError, "PAYLOAD_ID_MISMATCH"):
            validate_payload_identity_binding_v1_2(
                episode, replace(ref, payload_id="p-2"), payload
            )

    def test_023_scope_hash_mismatch_rejected(self) -> None:
        episode, ref, payload = _triplet()
        unrelated = "0" * 64
        with self.assertRaisesRegex(PayloadIntegrityError, "STUDENT_SCOPE_HASH_MISMATCH"):
            validate_payload_identity_binding_v1_2(
                episode, replace(ref, student_scope_hash=unrelated), payload
            )

    def test_024_arbitrary_namespace_rejected(self) -> None:
        episode, ref, payload = _triplet()
        with self.assertRaisesRegex(PayloadIntegrityError, "STORAGE_NAMESPACE_MISMATCH"):
            validate_payload_identity_binding_v1_2(
                episode, replace(ref, storage_namespace="persistent-memory-v1:" + "0" * 64), payload
            )

    def test_025_source_episode_mismatch_rejected(self) -> None:
        episode, ref, payload = _triplet()
        with self.assertRaisesRegex(PayloadIntegrityError, "SOURCE_EPISODE_MISMATCH"):
            validate_payload_identity_binding_v1_2(
                episode, ref, replace(payload, source_episode_id="e-2")
            )

    def test_026_source_turn_mismatch_rejected(self) -> None:
        episode, ref, payload = _triplet()
        with self.assertRaisesRegex(PayloadIntegrityError, "SOURCE_TURN_MISMATCH"):
            validate_payload_identity_binding_v1_2(
                episode, ref, replace(payload, source_turn_id="t-2")
            )

    # Metadata, text-only scope, hash, and byte length.
    def test_027_valid_metadata_and_content(self) -> None:
        self.assertIsNone(validate_payload_metadata_consistency_v1_2(*_triplet()))

    def test_028_content_type_exact_and_matching(self) -> None:
        episode, ref, payload = _triplet()
        for changed_ref, changed_payload in (
            (replace(ref, content_type="application/json"), payload),
            (ref, replace(payload, content_type="text/markdown")),
        ):
            with self.assertRaisesRegex(PayloadIntegrityError, "CONTENT_TYPE_MISMATCH"):
                validate_payload_metadata_consistency_v1_2(
                    episode, changed_ref, changed_payload
                )

    def test_029_encoding_exact_and_matching(self) -> None:
        episode, ref, payload = _triplet()
        for changed_ref, changed_payload in (
            (replace(ref, encoding="utf-8"), payload),
            (ref, replace(payload, encoding="UTF-16")),
        ):
            with self.assertRaisesRegex(PayloadIntegrityError, "ENCODING_MISMATCH"):
                validate_payload_metadata_consistency_v1_2(
                    episode, changed_ref, changed_payload
                )

    def test_030_locale_rules(self) -> None:
        episode, ref, payload = _triplet()
        for changed_ref, changed_payload in (
            (replace(ref, locale="en-GB"), payload),
            (ref, replace(payload, locale=" und")),
            (ref, replace(payload, locale="x" * 36)),
            (ref, replace(payload, locale="")),
        ):
            with self.assertRaisesRegex(PayloadIntegrityError, "LOCALE_MISMATCH"):
                validate_payload_metadata_consistency_v1_2(
                    episode, changed_ref, changed_payload
                )

    def test_031_empty_canonical_payloads_rejected(self) -> None:
        for text in ("", "   ", "\n\t"):
            _, _, payload = _triplet(text)
            with self.assertRaisesRegex(PayloadIntegrityError, "EMPTY_CANONICAL_PAYLOAD"):
                canonical_payload_bytes_v1_2(payload)

    def test_031a_non_string_canonical_payload_rejected(self) -> None:
        _, _, payload = _triplet()
        with self.assertRaisesRegex(
            PayloadIntegrityError, "INVALID_CANONICAL_PAYLOAD_TYPE"
        ):
            canonical_payload_bytes_v1_2(replace(payload, canonical_text=None))  # type: ignore[arg-type]

    def test_032_hash_triplet_mismatch_rejected(self) -> None:
        episode, ref, payload = _triplet()
        for changed_episode, changed_ref, changed_payload in (
            (replace(episode, raw_content_hash="0" * 64), ref, payload),
            (episode, replace(ref, content_hash="0" * 64), payload),
            (episode, ref, replace(payload, content_hash="0" * 64)),
        ):
            with self.assertRaisesRegex(PayloadIntegrityError, "CONTENT_HASH_MISMATCH"):
                validate_payload_metadata_consistency_v1_2(
                    changed_episode, changed_ref, changed_payload
                )

    def test_033_utf8_byte_length_not_character_count(self) -> None:
        episode, ref, payload = _triplet("é")
        self.assertEqual(ref.content_length, 2)
        self.assertEqual(len(payload.canonical_text), 1)
        with self.assertRaisesRegex(PayloadIntegrityError, "CONTENT_LENGTH_MISMATCH"):
            validate_payload_metadata_consistency_v1_2(
                episode, replace(ref, content_length=1), payload
            )
        with self.assertRaisesRegex(PayloadIntegrityError, "CONTENT_LENGTH_MISMATCH"):
            validate_payload_metadata_consistency_v1_2(
                episode, replace(ref, content_length=True), payload  # type: ignore[arg-type]
            )

    def test_034_structured_value_null_or_empty_only(self) -> None:
        _, _, payload = _triplet()
        validate_text_only_payload_scope_v1_1(payload)
        validate_text_only_payload_scope_v1_1(replace(payload, structured_value={}))
        with self.assertRaisesRegex(ValueError, STRUCTURED_PAYLOAD_BLOCKER):
            validate_text_only_payload_scope_v1_1(
                replace(payload, structured_value={"x": 1})
            )

    # Timezone-aware temporal integrity.
    def test_035_aware_z_and_offset_instants(self) -> None:
        zulu = parse_aware_iso8601_v1("2026-08-27T09:00:00Z", "event_time")
        offset = parse_aware_iso8601_v1(
            "2026-08-27T10:00:00+01:00", "event_time"
        )
        self.assertEqual(zulu, offset)
        self.assertEqual(zulu.tzinfo, timezone.utc)

    def test_036_valid_temporal_order_and_equivalent_ref_offset(self) -> None:
        episode, ref, _ = _triplet()
        ref = replace(ref, created_at="2026-08-27T11:02:00+01:00")
        self.assertIsNone(validate_temporal_integrity_v1(episode, ref))

    def test_037_each_naive_timestamp_rejected(self) -> None:
        episode, ref, _ = _triplet()
        cases = (
            (replace(episode, event_time="2026-08-27T10:00:00"), ref, "NAIVE_EVENT_TIME"),
            (replace(episode, created_at="2026-08-27T10:01:00"), ref, "NAIVE_CREATED_AT"),
            (replace(episode, ingested_at="2026-08-27T10:02:00"), ref, "NAIVE_INGESTED_AT"),
            (episode, replace(ref, created_at="2026-08-27T10:02:00"), "NAIVE_PAYLOAD_REF_CREATED_AT"),
        )
        for changed_episode, changed_ref, code in cases:
            with self.assertRaisesRegex(PayloadIntegrityError, code):
                validate_temporal_integrity_v1(changed_episode, changed_ref)

    def test_038_event_after_created_rejected(self) -> None:
        episode, ref, _ = _triplet()
        with self.assertRaisesRegex(PayloadIntegrityError, "EVENT_AFTER_CREATED"):
            validate_temporal_integrity_v1(
                replace(episode, event_time="2026-08-27T10:01:01Z"), ref
            )

    def test_039_created_after_ingested_rejected(self) -> None:
        episode, ref, _ = _triplet()
        with self.assertRaisesRegex(PayloadIntegrityError, "CREATED_AFTER_INGESTED"):
            validate_temporal_integrity_v1(
                replace(episode, created_at="2026-08-27T10:02:01Z"), ref
            )

    def test_040_payload_ref_time_mismatch_rejected(self) -> None:
        episode, ref, _ = _triplet()
        with self.assertRaisesRegex(
            PayloadIntegrityError, "PAYLOAD_REF_TIME_NOT_INGESTION_TIME"
        ):
            validate_temporal_integrity_v1(
                episode, replace(ref, created_at="2026-08-27T10:02:01Z")
            )

    def test_041_invalid_iso_rejected(self) -> None:
        episode, ref, _ = _triplet()
        with self.assertRaisesRegex(PayloadIntegrityError, "INVALID_ISO_TIMESTAMP"):
            validate_temporal_integrity_v1(
                replace(episode, event_time="not-a-timestamp"), ref
            )

    # Composite order, exact invocation, and non-bypass guards.
    def test_042_valid_composite_binding_passes(self) -> None:
        outcome = validate_persistent_memory_payload_binding_v1_3(*_triplet())
        self.assertTrue(outcome.binding_valid)
        self.assertEqual(dict(outcome.stage_call_counts), {"R2": 1, "R3": 1, "R4": 1})

    def test_043_each_composite_stage_invoked_exactly_once(self) -> None:
        module = "evaluation.capability_routing_rq2c0_r4_v1.composite_payload_episode_validator_v1_3"
        with patch(module + "._validate_r2_stage", wraps=__import__(module, fromlist=["_validate_r2_stage"])._validate_r2_stage) as r2, patch(
            module + "._validate_r3_stage", wraps=__import__(module, fromlist=["_validate_r3_stage"])._validate_r3_stage
        ) as r3, patch(module + "._validate_r4_stage", wraps=__import__(module, fromlist=["_validate_r4_stage"])._validate_r4_stage) as r4:
            self.assertTrue(validate_persistent_memory_payload_binding_v1_3(*_triplet()).binding_valid)
            r2.assert_called_once()
            r3.assert_called_once()
            r4.assert_called_once()

    def test_044_r2_failure_cannot_be_overridden(self) -> None:
        module = "evaluation.capability_routing_rq2c0_r4_v1.composite_payload_episode_validator_v1_3"
        with patch(module + "._validate_r2_stage", side_effect=ValueError("fail")), patch(
            module + "._validate_r3_stage"
        ) as r3, patch(module + "._validate_r4_stage") as r4:
            outcome = validate_persistent_memory_payload_binding_v1_3(*_triplet())
            self.assertFalse(outcome.binding_valid)
            self.assertEqual(outcome.failed_stage, "R2")
            r3.assert_not_called()
            r4.assert_not_called()

    def test_045_r3_failure_cannot_be_overridden(self) -> None:
        module = "evaluation.capability_routing_rq2c0_r4_v1.composite_payload_episode_validator_v1_3"
        with patch(module + "._validate_r3_stage", side_effect=ValueError("fail")), patch(
            module + "._validate_r4_stage"
        ) as r4:
            outcome = validate_persistent_memory_payload_binding_v1_3(*_triplet())
            self.assertFalse(outcome.binding_valid)
            self.assertEqual(outcome.failed_stage, "R3")
            r4.assert_not_called()

    def test_046_r4_failure_cannot_be_overridden(self) -> None:
        episode, ref, payload = _triplet()
        outcome = validate_persistent_memory_payload_binding_v1_3(
            episode, ref, replace(payload, source_turn_id="t-2")
        )
        self.assertFalse(outcome.binding_valid)
        self.assertEqual(outcome.failed_stage, "R4")
        self.assertEqual(outcome.failure_code, "SOURCE_TURN_MISMATCH")

    def test_047_all_downstream_interfaces_require_valid_binding(self) -> None:
        valid = validate_persistent_memory_payload_binding_v1_3(*_triplet())
        invalid = PayloadBindingValidationV1_3(False, "R4", "FAIL", (("R2", 1),))
        incomplete = PayloadBindingValidationV1_3(True, None, None, (("R2", 1),))
        for interface in GUARDED_INTERFACES:
            self.assertIsNone(require_validated_payload_for_interface_v1_3(valid, interface))
            with self.assertRaisesRegex(PermissionError, "UNVALIDATED_PAYLOAD_BLOCKED"):
                require_validated_payload_for_interface_v1_3(invalid, interface)
            with self.assertRaisesRegex(PermissionError, "UNVALIDATED_PAYLOAD_BLOCKED"):
                require_validated_payload_for_interface_v1_3(incomplete, interface)

    def test_048_effective_contract_points_only_to_composite(self) -> None:
        effective = effective_persistent_memory_contract_v1_3()
        self.assertTrue(effective["composite_validator_required"])
        self.assertIn("validate_persistent_memory_payload_binding_v1_3", effective["rq2c1_import_contract"]["payload_binding"])
        self.assertFalse(effective["rq2c1_import_contract"]["direct_r2_only_validation_allowed"])
        self.assertFalse(effective["rq2c1_import_contract"]["direct_r3_only_validation_allowed"])
        self.assertFalse(effective["rq2c1_import_contract"]["direct_r4_only_validation_allowed"])

    # Research invariants, deterministic build, and package gates.
    def test_049_fixture_p1_gold_primary_unchanged(self) -> None:
        self.assertEqual(sha256_file(FIXTURE_BANK_PATH), self.fixture_sha_before)
        effective = effective_persistent_memory_contract_v1_3()
        self.assertTrue(effective["unchanged"]["fixtures"])
        self.assertTrue(effective["unchanged"]["P1"])
        self.assertTrue(effective["unchanged"]["Capability_Gold"])
        self.assertEqual(effective["unchanged"]["primary_policy_identity"], EXPECTED_PRIMARY_POLICY_ID)

    def test_050_r2_r3_and_protected_sources_unchanged(self) -> None:
        self.assertEqual(verify_r2_tracked_history()["status"], "PASS")
        self.assertEqual(verify_r3_tracked_history()["status"], "PASS")
        self.assertEqual(protected_manifest()["status"], "PASS")
        self.assertEqual(protected_source_comparison()["protected_existing_change_count"], 0)

    def test_051_no_track_a_or_track_b_access(self) -> None:
        for partition in ("TRACK_A", "TRACK_B"):
            with self.assertRaises(PermissionError):
                assert_partition_access_allowed(partition)

    def test_052_no_implementation_or_external_activity(self) -> None:
        self.assertEqual(validate_no_implementation()["forbidden_implementation_count"], 0)

    def test_053_python_ast_and_safe_outputs(self) -> None:
        self.assertEqual(validate_python_ast()["python_file_count"], 11)
        self.assertEqual(validate_safe_outputs()["safe_output_count"], 8)

    def test_054_double_build_is_byte_identical(self) -> None:
        second = build_all()
        self.assertEqual(
            self.first_build["build_commitment_sha256"],
            second["build_commitment_sha256"],
        )

    def test_055_output_checksums_and_review_completeness(self) -> None:
        self.assertEqual(len(parse_output_checksums()), 22)
        self.assertEqual(validate_output_checksums()["referenced_output_count"], 22)
        self.assertEqual(validate_review_package_contract()["expected_review_member_count"], 27)
        self.assertEqual(len(expected_review_members()), 27)

    def test_056_governed_text_and_staged_allowlist(self) -> None:
        self.assertEqual(governed_text_leak_scan()["leak_count"], 0)
        self.assertEqual(staged_allowlist()["status"], "PASS")

    def test_057_composite_validator_deterministic(self) -> None:
        first = validate_persistent_memory_payload_binding_v1_3(*_triplet())
        second = validate_persistent_memory_payload_binding_v1_3(*_triplet())
        self.assertEqual(first, second)

    def test_058_full_validator_passes(self) -> None:
        self.assertEqual(validate_all()["status"], "PASS_PAYLOAD_INTEGRITY_CONTRACT_FREEZE")


if __name__ == "__main__":
    unittest.main()
