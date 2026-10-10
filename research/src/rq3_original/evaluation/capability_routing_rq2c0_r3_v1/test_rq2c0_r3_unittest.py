"""RQ2-C0-R3 state-aware ordering, admission, and payload conformance tests."""

from __future__ import annotations

from dataclasses import replace
import hashlib
import json
import subprocess
import unittest

from evaluation.capability_routing_rq2c0_r2_v1.episode_schema_v1_1 import (
    MemoryEpisodeV1_1,
)
from evaluation.capability_routing_rq2c0_r2_v1.executable_retrieval_contract import (
    DENSE_TOP_K,
    POLICY_IDS,
    PRIMARY_POLICY_ID,
    RETRIEVAL_MAX_RESULTS,
    MemoryIndexRecordV1_1,
    RankedMemoryCandidateV1_1,
    RetrievalPlanV1_1,
    rank_dense_only,
    rank_hybrid_state_aware,
    rank_hybrid_type_temporal,
    rank_kw_legacy,
    temporal_validity,
    type_compatibility,
)
from evaluation.capability_routing_rq2c0_r2_v1.payload_schema import (
    MemoryPayloadRefV1,
)
from evaluation.capability_routing_rq2c0_r2_v1.text_normalisation import (
    normalised_text_hash,
)

from . import (
    EXPECTED_FIXTURE_BANK_SHA256,
    EXPECTED_FIXTURE_BANK_SIZE,
    EXPECTED_FIXTURE_RECORD_COUNT,
    EXPECTED_GOLD_BUNDLE_SHA256,
    EXPECTED_P1_POLICY,
    EXPECTED_PRIMARY_POLICY_ID,
    EXPECTED_R2_REVIEW_ZIP_SHA256,
    FIXTURE_BANK_PATH,
    HERE,
    R2_REVIEW_ZIP,
    RESULT_BRANCH,
    ROOT,
    STARTING_HEAD,
    STARTING_PARENT,
    sha256_file,
)
from .admission_v1_1 import (
    MAX_ADMITTED_MEMORIES_V1_1,
    admission_guard_failure_v1_1,
    admit_ranked_candidates_v1_1,
    effective_admission_support_v1_1,
    pre_guard_relevance_signals_v1_1,
    temporal_admission_contract,
)
from .effective_contract import (
    candidate_ordering_amendment,
    effective_persistent_memory_contract,
    memory_safety_repair_authority,
    payload_scope_amendment,
    rank_effective_policy_v1_2,
    temporal_admission_amendment,
)
from .payload_scope_v1_1 import (
    MemoryPayloadV1_1,
    STRUCTURED_PAYLOAD_BLOCKER,
    canonical_payload_content_hash_v1_1,
    canonical_payload_length_v1_1,
    payload_embedding_text_v1_1,
    payload_retrieval_text_v1_1,
    text_only_payload_contract,
    validate_payload_episode_reference_consistency_v1_1,
    validate_text_only_payload_scope_v1_1,
)
from .r2_identity import (
    protected_manifest,
    verify_fixture_identity,
    verify_r2_output_checksums,
    verify_r2_tracked_history,
    verify_starting_authority,
)
from .state_aware_eligibility import (
    eligibility_contract,
    state_aware_eligible_records_v1_1,
)
from .state_aware_retrieval_v1_1 import (
    rank_hybrid_state_aware_v1_1,
    rank_hybrid_state_aware_v1_1_with_trace,
    state_aware_retrieval_contract,
)
from .validate_rq2c0_r3 import (
    CHECKSUM_RELATIVE,
    assert_partition_access_allowed,
    build_all,
    expected_review_members,
    governed_text_leak_scan,
    parse_output_checksums,
    protected_source_comparison,
    staged_allowlist,
    validate_all,
    validate_feature_isolation,
    validate_no_implementation,
    validate_output_checksums,
    validate_python_ast,
    validate_review_package_contract,
    validate_safe_outputs,
)


ZERO_HASH = "0" * 64


def _git(*args: str) -> str:
    return subprocess.check_output(
        ["git", *args], cwd=ROOT, text=True, stderr=subprocess.STDOUT
    ).strip()


def _plan(
    *,
    target_types: tuple[str, ...] = ("GOAL",),
    memory_required: bool = False,
) -> RetrievalPlanV1_1:
    return RetrievalPlanV1_1(
        student_scope_id="scope-a",
        query_time="2026-08-27T12:00:00+00:00",
        target_memory_types=target_types,
        memory_required=memory_required,
    )


def _record(memory_id: str, **overrides: object) -> MemoryIndexRecordV1_1:
    values: dict[str, object] = {
        "memory_id": memory_id,
        "student_scope_id": "scope-a",
        "memory_type": "GOAL",
        "status": "ACTIVE",
        "event_time": "2026-08-26T12:00:00+00:00",
        "valid_from": "2026-08-01T00:00:00+00:00",
        "valid_until": None,
        "governed_entity_set": (),
        "supersession_chain_id": "",
        "supersedes_memory_id": None,
        "explicit_state_link": False,
        "production_memory_trigger": False,
        "exact_lexical_match": False,
        "entity_overlap_count": 0,
        "dense_score": 0.0,
        "dense_rank": None,
        "explicitness": "",
    }
    values.update(overrides)
    return MemoryIndexRecordV1_1(**values)  # type: ignore[arg-type]


def _candidate(
    record: MemoryIndexRecordV1_1,
    *,
    plan: RetrievalPlanV1_1 | None = None,
    temporal: bool | None = None,
) -> RankedMemoryCandidateV1_1:
    current = plan or _plan()
    compatible, unspecified = type_compatibility(record, current.target_memory_types)
    return RankedMemoryCandidateV1_1(
        record=record,
        type_compatible=compatible,
        target_type_unspecified=unspecified,
        temporal_validity=(
            temporal_validity(record, current.query_time) if temporal is None else temporal
        ),
    )


def _invalid_high_records() -> tuple[MemoryIndexRecordV1_1, ...]:
    return tuple(
        _record(f"invalid-{index}", status="STALE", dense_score=1.0 - index / 100)
        for index in range(5)
    )


class RQ2C0R3Tests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.fixture_bytes_before = FIXTURE_BANK_PATH.read_bytes()
        cls.fixture_rows_before = [
            json.loads(line) for line in cls.fixture_bytes_before.splitlines()
        ]
        cls.fixture_ids_before = tuple(
            row["fixture_id"] for row in cls.fixture_rows_before
        )
        cls.fixture_decisions_before = tuple(
            (
                row["fixture_id"],
                row["expected_write_decision"],
                row["expected_retrieval_ids"],
                row["expected_admission_ids"],
                row["expected_rejection_reasons"],
                row["expected_clarification"],
                row["expected_security_state"],
                row["coverage_tags"],
            )
            for row in cls.fixture_rows_before
        )
        cls.r2_manifest_before = verify_r2_tracked_history()[
            "tracked_manifest_sha256"
        ]
        build_all()

    # Starting authority and frozen identities.
    def test_001_starting_branch_and_head(self) -> None:
        self.assertEqual(_git("branch", "--show-current"), RESULT_BRANCH)
        self.assertEqual(_git("rev-parse", f"{STARTING_HEAD}^"), STARTING_PARENT)
        self.assertEqual(_git("merge-base", STARTING_HEAD, "HEAD"), STARTING_HEAD)
        self.assertIn(int(_git("rev-list", "--count", f"{STARTING_HEAD}..HEAD")), (0, 1))

    def test_002_r2_review_zip_sha(self) -> None:
        self.assertTrue(R2_REVIEW_ZIP.is_file())
        self.assertEqual(sha256_file(R2_REVIEW_ZIP), EXPECTED_R2_REVIEW_ZIP_SHA256)

    def test_003_r2_output_checksums_36_of_36(self) -> None:
        result = verify_r2_output_checksums()
        self.assertEqual(result["checksum_count"], 36)
        self.assertEqual(result["failure_count"], 0)

    def test_004_fixture_bank_identity(self) -> None:
        result = verify_fixture_identity()
        self.assertEqual(result["sha256"], EXPECTED_FIXTURE_BANK_SHA256)
        self.assertEqual(result["size_bytes"], EXPECTED_FIXTURE_BANK_SIZE)
        self.assertEqual(result["record_count"], EXPECTED_FIXTURE_RECORD_COUNT)

    def test_005_p1_identity_unchanged(self) -> None:
        result = verify_starting_authority()
        self.assertEqual(result["p1_policy"], EXPECTED_P1_POLICY)
        self.assertTrue(result["p1_immutable"])

    def test_006_gold_bundle_unchanged(self) -> None:
        self.assertEqual(
            verify_starting_authority()["gold_bundle_sha256"],
            EXPECTED_GOLD_BUNDLE_SHA256,
        )

    def test_007_primary_policy_identity_unchanged(self) -> None:
        self.assertEqual(PRIMARY_POLICY_ID, EXPECTED_PRIMARY_POLICY_ID)
        self.assertEqual(
            verify_starting_authority()["primary_policy_id"],
            EXPECTED_PRIMARY_POLICY_ID,
        )

    # Pre-candidate state and temporal eligibility.
    def _assert_rejected(self, record: MemoryIndexRecordV1_1, reason: str, plan: RetrievalPlanV1_1 | None = None) -> None:
        result = state_aware_eligible_records_v1_1(plan or _plan(), (record,))
        self.assertEqual(result.eligible_records, ())
        self.assertEqual(result.rejected_record_reasons[record.memory_id], reason)

    def test_008_cross_scope_removed_before_dense_top_k(self) -> None:
        self._assert_rejected(_record("cross", student_scope_id="scope-b", dense_score=1.0), "CROSS_STUDENT_SCOPE")

    def test_009_deleted_removed_before_dense_top_k(self) -> None:
        self._assert_rejected(_record("deleted", status="DELETED", dense_score=1.0), "DELETED_MEMORY")

    def test_010_stale_removed_before_dense_top_k(self) -> None:
        self._assert_rejected(_record("stale", status="STALE", dense_score=1.0), "STALE")

    def test_011_superseded_removed_before_dense_top_k(self) -> None:
        self._assert_rejected(_record("superseded", status="SUPERSEDED", dense_score=1.0), "SUPERSEDED")

    def test_012_cancelled_removed_before_dense_top_k(self) -> None:
        self._assert_rejected(_record("cancelled", status="CANCELLED", dense_score=1.0), "CANCELLED")

    def test_013_non_targeted_completed_removed_before_dense_top_k(self) -> None:
        self._assert_rejected(_record("completed", status="COMPLETED", dense_score=1.0), "COMPLETED_NOT_REQUESTED")

    def test_014_targeted_completion_remains_eligible(self) -> None:
        record = _record("completed", status="COMPLETED", memory_type="COMPLETION")
        result = state_aware_eligible_records_v1_1(_plan(target_types=("COMPLETION",)), (record,))
        self.assertEqual(result.eligible_records, (record,))

    def test_015_temporally_invalid_active_removed_before_dense_top_k(self) -> None:
        expired = _record("expired", valid_until="2026-08-20T00:00:00+00:00", dense_score=1.0)
        self._assert_rejected(expired, "TEMPORALLY_INVALID")

    def test_016_unknown_inactive_state_removed(self) -> None:
        self._assert_rejected(_record("inactive", status="PAUSED"), "INACTIVE_STATUS")

    def test_017_invalid_candidates_receive_no_dense_rank(self) -> None:
        valid = _record("valid", dense_score=0.1)
        outcome = rank_hybrid_state_aware_v1_1_with_trace(_plan(), (*_invalid_high_records(), valid))
        self.assertEqual(outcome.dense_rank_by_id, {"valid": 1})
        self.assertFalse(set(outcome.dense_rank_by_id) & {record.memory_id for record in _invalid_high_records()})

    def test_018_invalid_candidates_occupy_no_candidate_union_slot(self) -> None:
        valid = _record("valid", dense_score=0.1)
        invalid = _invalid_high_records()
        outcome = rank_hybrid_state_aware_v1_1_with_trace(_plan(), (*invalid, valid))
        self.assertEqual(outcome.candidate_union_ids, ("valid",))

    def test_019_invalid_high_scores_cannot_crowd_out_valid_record(self) -> None:
        valid = _record("valid", dense_score=0.1)
        result = rank_hybrid_state_aware_v1_1(_plan(), (*_invalid_high_records(), valid))
        self.assertEqual([item.record.memory_id for item in result], ["valid"])

    def test_020_valid_lower_score_record_remains_returned(self) -> None:
        valid = _record("valid-low", dense_score=-1.0, exact_lexical_match=True)
        result = rank_hybrid_state_aware_v1_1(_plan(), (*_invalid_high_records(), valid))
        self.assertIn("valid-low", [item.record.memory_id for item in result])

    def test_021_active_explicit_correction_suppresses_older_before_top_k(self) -> None:
        old = _record("old", dense_score=1.0)
        correction = _record(
            "correction",
            memory_type="CORRECTION",
            explicitness="EXPLICIT_STUDENT",
            supersedes_memory_id="old",
            dense_score=0.1,
        )
        result = rank_hybrid_state_aware_v1_1_with_trace(_plan(), (old, correction))
        self.assertEqual(
            result.eligibility.suppressed_record_reasons["old"],
            "SUPERSEDED_BY_ACTIVE_EXPLICIT_CORRECTION",
        )
        self.assertNotIn("old", result.dense_rank_by_id)

    def test_022_conflict_projection_occurs_before_top_k(self) -> None:
        common = {"governed_entity_set": ("entity",), "supersession_chain_id": "chain"}
        old = _record("old", dense_score=1.0, event_time="2026-08-25T00:00:00+00:00", **common)
        new = _record("new", dense_score=0.1, event_time="2026-08-26T00:00:00+00:00", **common)
        outcome = rank_hybrid_state_aware_v1_1_with_trace(_plan(), (old, new))
        self.assertEqual(outcome.eligibility.suppressed_record_reasons["old"], "CONFLICT_GROUP_OLDER_EPISODE")
        self.assertEqual(outcome.dense_rank_by_id, {"new": 1})

    def test_023_deterministic_ranking_and_tie_break(self) -> None:
        records = tuple(_record(identifier, dense_score=0.5) for identifier in ("c", "a", "b"))
        first = rank_hybrid_state_aware_v1_1(_plan(), records)
        second = rank_hybrid_state_aware_v1_1(_plan(), reversed(records))
        self.assertEqual(first, second)
        self.assertEqual([item.record.memory_id for item in first], ["a", "b", "c"])

    def test_024_maximum_five_retrieval_results(self) -> None:
        records = tuple(_record(f"m-{index}", dense_score=1.0 - index / 100) for index in range(9))
        self.assertEqual(len(rank_hybrid_state_aware_v1_1(_plan(), records)), RETRIEVAL_MAX_RESULTS)
        self.assertEqual(DENSE_TOP_K, 5)

    def test_025_eligibility_trace_is_total_and_deterministic(self) -> None:
        records = (_record("valid"), _record("stale", status="STALE"))
        one = state_aware_eligible_records_v1_1(_plan(), records)
        two = state_aware_eligible_records_v1_1(_plan(), records)
        self.assertEqual(one, two)
        self.assertEqual(len(one.eligibility_trace), len(records))

    # R2 parity for unaffected policies and effective identity.
    def _parity_records(self) -> tuple[MemoryIndexRecordV1_1, ...]:
        return (
            _record("a", dense_score=0.8, exact_lexical_match=True),
            _record("b", dense_score=0.9, memory_type="PLAN", entity_overlap_count=1),
            _record("c", dense_score=0.7, explicit_state_link=True),
            _record("cross", dense_score=1.0, student_scope_id="scope-b"),
            _record("deleted", dense_score=1.0, status="DELETED"),
        )

    def test_026_kw_legacy_parity_with_r2(self) -> None:
        records = self._parity_records()
        self.assertEqual(rank_effective_policy_v1_2("PMR_KW_LEGACY", _plan(), records), rank_kw_legacy(_plan(), records))

    def test_027_dense_only_parity_with_r2(self) -> None:
        records = self._parity_records()
        self.assertEqual(rank_effective_policy_v1_2("PMR_DENSE_ONLY", _plan(), records), rank_dense_only(_plan(), records))

    def test_028_hybrid_type_temporal_parity_with_r2(self) -> None:
        records = self._parity_records()
        self.assertEqual(rank_effective_policy_v1_2("PMR_HYBRID_TYPE_TEMPORAL", _plan(), records), rank_hybrid_type_temporal(_plan(), records))

    def test_029_only_state_aware_effective_algorithm_is_superseded(self) -> None:
        contract = effective_persistent_memory_contract()
        self.assertTrue(contract["only_state_aware_effective_algorithm_superseded"])
        self.assertEqual(contract["unchanged"]["policy_family_ids"], list(POLICY_IDS))
        records = (*_invalid_high_records(), _record("valid", dense_score=0.1))
        self.assertNotEqual(rank_effective_policy_v1_2(PRIMARY_POLICY_ID, _plan(), records), rank_hybrid_state_aware(_plan(), records))

    def test_030_primary_policy_thresholds_unchanged(self) -> None:
        contract = effective_persistent_memory_contract()["unchanged"]
        self.assertEqual(contract["dense_top_k"], 5)
        self.assertEqual(contract["maximum_retrieval_results"], 5)

    # Temporal admission hard guards and support separation.
    def _expired_link(self, **overrides: object) -> RankedMemoryCandidateV1_1:
        record = _record(
            "expired",
            explicit_state_link=True,
            valid_until="2026-08-20T00:00:00+00:00",
            **overrides,
        )
        return _candidate(record)

    def test_031_temporal_invalid_explicit_link_rejected(self) -> None:
        outcome = admit_ranked_candidates_v1_1((self._expired_link(),), _plan())
        decision = outcome.decisions[0]
        self.assertFalse(decision.admitted)
        self.assertFalse(decision.guard_eligible)
        self.assertEqual(decision.guard_failure_reason, "TEMPORALLY_INVALID")

    def test_032_temporal_invalid_link_cannot_create_direct_support(self) -> None:
        decision = admit_ranked_candidates_v1_1((self._expired_link(),), _plan()).decisions[0]
        self.assertIn("DIRECT_RELEVANCE_SIGNAL", decision.pre_guard_relevance_signals)
        self.assertEqual(decision.admission_support_basis, ())
        self.assertFalse(decision.relevance_supported_after_guards)

    def test_033_temporal_invalid_structured_signal_rejected(self) -> None:
        candidate = self._expired_link(entity_overlap_count=1)
        self.assertIn("STRUCTURED_RELEVANCE_SIGNAL", pre_guard_relevance_signals_v1_1(candidate))
        self.assertEqual(effective_admission_support_v1_1(candidate), ())

    def test_034_temporal_invalid_dense_signal_rejected(self) -> None:
        candidate = self._expired_link(dense_rank=1)
        self.assertIn("DENSE_RELEVANCE_SIGNAL", pre_guard_relevance_signals_v1_1(candidate))
        self.assertEqual(effective_admission_support_v1_1(candidate), ())

    def test_035_temporal_valid_explicit_link_may_create_direct_support(self) -> None:
        candidate = _candidate(_record("direct", explicit_state_link=True))
        outcome = admit_ranked_candidates_v1_1((candidate,), _plan())
        self.assertTrue(outcome.decisions[0].admitted)
        self.assertIn("DIRECT_SUPPORT", outcome.decisions[0].admission_support_basis)

    def test_036_scope_guard_overrides_relevance(self) -> None:
        candidate = _candidate(_record("cross", student_scope_id="scope-b", explicit_state_link=True))
        self.assertEqual(admission_guard_failure_v1_1(candidate, _plan()), "CROSS_STUDENT_SCOPE")
        self.assertFalse(admit_ranked_candidates_v1_1((candidate,), _plan()).decisions[0].admitted)

    def test_037_deletion_guard_overrides_relevance(self) -> None:
        candidate = _candidate(_record("deleted", status="DELETED", explicit_state_link=True))
        self.assertEqual(admission_guard_failure_v1_1(candidate, _plan()), "DELETED_MEMORY")

    def test_038_stale_guard_overrides_relevance(self) -> None:
        candidate = _candidate(_record("stale", status="STALE", explicit_state_link=True))
        self.assertEqual(admission_guard_failure_v1_1(candidate, _plan()), "STALE")

    def test_039_superseded_guard_overrides_relevance(self) -> None:
        candidate = _candidate(_record("superseded", status="SUPERSEDED", explicit_state_link=True))
        self.assertEqual(admission_guard_failure_v1_1(candidate, _plan()), "SUPERSEDED")

    def test_040_cancelled_guard_overrides_relevance(self) -> None:
        candidate = _candidate(_record("cancelled", status="CANCELLED", explicit_state_link=True))
        self.assertEqual(admission_guard_failure_v1_1(candidate, _plan()), "CANCELLED")

    def test_041_completed_not_requested_guard_overrides_relevance(self) -> None:
        candidate = _candidate(_record("completed", status="COMPLETED", explicit_state_link=True))
        self.assertEqual(admission_guard_failure_v1_1(candidate, _plan()), "COMPLETED_NOT_REQUESTED")

    def test_042_inactive_guard_overrides_relevance(self) -> None:
        candidate = _candidate(_record("inactive", status="PAUSED", explicit_state_link=True))
        self.assertEqual(admission_guard_failure_v1_1(candidate, _plan()), "INACTIVE_STATUS")

    def test_043_targeted_completion_may_be_admitted(self) -> None:
        plan = _plan(target_types=("COMPLETION",))
        candidate = _candidate(_record("completed", status="COMPLETED", memory_type="COMPLETION", explicit_state_link=True), plan=plan)
        self.assertTrue(admit_ranked_candidates_v1_1((candidate,), plan).decisions[0].admitted)

    def test_044_no_automatic_top1_admission(self) -> None:
        candidate = _candidate(_record("top-one", dense_rank=None))
        result = admit_ranked_candidates_v1_1((candidate,), _plan())
        self.assertEqual(result.admitted_memory_count, 0)
        self.assertFalse(result.automatic_top1_admission)

    def test_045_maximum_three_admissions(self) -> None:
        candidates = tuple(_candidate(_record(f"m-{index}", explicit_state_link=True)) for index in range(5))
        result = admit_ranked_candidates_v1_1(candidates, _plan())
        self.assertEqual(MAX_ADMITTED_MEMORIES_V1_1, 3)
        self.assertEqual(result.admitted_memory_count, 3)
        self.assertTrue(all(item.failure_reason == "ADMISSION_LIMIT_REACHED" for item in result.decisions[3:]))

    def test_046_no_admission_memory_required_clarifies(self) -> None:
        result = admit_ranked_candidates_v1_1((), _plan(memory_required=True))
        self.assertTrue(result.clarification)
        self.assertFalse(result.continue_without_memory)

    def test_047_no_admission_optional_memory_continues_safely(self) -> None:
        result = admit_ranked_candidates_v1_1((), _plan(memory_required=False))
        self.assertFalse(result.clarification)
        self.assertTrue(result.continue_without_memory)

    def test_048_admission_double_run_deterministic(self) -> None:
        candidates = (_candidate(_record("direct", explicit_state_link=True)), self._expired_link())
        self.assertEqual(admit_ranked_candidates_v1_1(candidates, _plan()), admit_ranked_candidates_v1_1(candidates, _plan()))

    # Text-only private payload scope.
    def _payload(self, structured: object = None, canonical: str = "") -> MemoryPayloadV1_1:
        return MemoryPayloadV1_1(
            payload_id="payload-1",
            memory_id="memory-1",
            canonical_text=canonical,
            structured_value=structured,  # type: ignore[arg-type]
            content_type="text/plain",
            locale="en-GB",
            source_episode_id="episode-1",
            source_turn_id="turn-1",
            content_hash=normalised_text_hash(canonical),
        )

    def test_049_structured_value_null_passes(self) -> None:
        validate_text_only_payload_scope_v1_1(self._payload(None))

    def test_050_structured_value_empty_mapping_passes(self) -> None:
        validate_text_only_payload_scope_v1_1(self._payload({}))

    def test_051_nonempty_structured_value_fails_closed(self) -> None:
        with self.assertRaisesRegex(ValueError, STRUCTURED_PAYLOAD_BLOCKER):
            validate_text_only_payload_scope_v1_1(self._payload({"key": 1}))

    def test_052_canonical_text_is_sole_hashed_content(self) -> None:
        canonical = chr(65) + "\r\n"
        one = self._payload(None, canonical)
        two = self._payload({}, canonical)
        self.assertEqual(canonical_payload_content_hash_v1_1(one), canonical_payload_content_hash_v1_1(two))
        self.assertEqual(canonical_payload_content_hash_v1_1(one), normalised_text_hash(canonical))

    def test_053_canonical_text_is_sole_embedding_and_retrieval_content(self) -> None:
        canonical = chr(65)
        payload = self._payload(None, canonical)
        self.assertEqual(payload_embedding_text_v1_1(payload), canonical)
        self.assertEqual(payload_retrieval_text_v1_1(payload), canonical)
        self.assertEqual(canonical_payload_length_v1_1(payload), 1)

    def test_054_typed_metadata_remains_outside_payload_body(self) -> None:
        contract = text_only_payload_contract()
        fields = set(contract["payload_fields"])
        for value in ("memory_type", "entities", "status", "explicitness", "valid_from", "valid_until", "supersedes_memory_id", "event_type"):
            self.assertNotIn(value, fields)
        self.assertFalse(contract["typed_values_duplicated_into_structured_value"])

    def _payload_triplet(self) -> tuple[MemoryEpisodeV1_1, MemoryPayloadRefV1, MemoryPayloadV1_1]:
        payload = self._payload(None, "")
        payload_ref = MemoryPayloadRefV1(
            payload_id="payload-1",
            memory_id="memory-1",
            student_scope_hash=ZERO_HASH,
            content_hash=payload.content_hash,
            content_length=0,
            content_type="text/plain",
            locale="en-GB",
            encoding="UTF-8",
            storage_namespace="private-local-v1",
            local_only=True,
            encrypted_at_rest_required=True,
            created_at="2026-08-27T12:00:01+00:00",
        )
        episode = MemoryEpisodeV1_1(
            memory_id="memory-1",
            student_scope_id="scope-a",
            episode_id="episode-1",
            source_turn_id="turn-1",
            memory_type="GOAL",
            raw_content_hash=payload.content_hash,
            created_at="2026-08-27T12:00:01+00:00",
            valid_from="2026-08-27T12:00:00+00:00",
            valid_until=None,
            status="ACTIVE",
            explicitness="EXPLICIT_STUDENT",
            confidence=1.0,
            entities=(),
            supersedes_memory_id=None,
            provenance={},
            embedding_hash=None,
            payload_id="payload-1",
            event_time="2026-08-27T12:00:00+00:00",
            ingested_at="2026-08-27T12:00:01+00:00",
            timezone="Europe/London",
            status_reason="CREATED",
            source_kind="STRUCTURED_EXPLICIT_USER_ASSERTION",
            projection_eligible=True,
        )
        return episode, payload_ref, payload

    def test_055_payload_episode_reference_hash_consistency(self) -> None:
        validate_payload_episode_reference_consistency_v1_1(*self._payload_triplet())

    def test_056_general_structured_payload_support_false(self) -> None:
        contract = text_only_payload_contract()
        self.assertFalse(contract["general_structured_payload_support"])
        self.assertEqual(contract["general_canonical_json_serialisation"], "FUTURE_WORK")

    # Effective authority and future import contract.
    def test_057_user_authority_contains_only_three_corrections(self) -> None:
        authority = memory_safety_repair_authority()
        self.assertEqual(len(authority["authorised_corrections"]), 3)
        self.assertFalse(authority["production_behaviour_change_authorised"])

    def test_058_amendment_invariants_are_false(self) -> None:
        for amendment in (candidate_ordering_amendment(), temporal_admission_amendment(), payload_scope_amendment()):
            self.assertEqual(amendment["authority_basis"], "USER_EXPLICIT_AUTHORISATION")
            self.assertFalse(amendment["fixture_changed"])
            self.assertFalse(amendment["primary_policy_identity_changed"])
            self.assertFalse(amendment["production_behaviour_changed"])

    def test_059_effective_contract_points_to_r3_functions(self) -> None:
        imports = effective_persistent_memory_contract()["rq2c1_import_contract"]
        self.assertIn("capability_routing_rq2c0_r3_v1", imports["state_aware_retrieval"])
        self.assertIn("capability_routing_rq2c0_r3_v1", imports["admission"])
        self.assertIn("capability_routing_rq2c0_r3_v1", imports["payload_scope"])
        self.assertFalse(imports["superseded_r2_state_aware_import_allowed"])

    def test_060_effective_contract_exact_identity(self) -> None:
        contract = effective_persistent_memory_contract()
        self.assertEqual(contract["schema_version"], "effective-persistent-memory-contract-v1.2")
        self.assertEqual(contract["effective_primary_policy_id"], "PMR_HYBRID_STATE_AWARE")
        self.assertEqual(contract["effective_state_aware_algorithm"], "PMR_HYBRID_STATE_AWARE_V1_1")
        self.assertEqual(contract["effective_admission_algorithm"], "MEMORY_ADMISSION_V1_1")
        self.assertEqual(contract["effective_payload_scope"], "TEXT_ONLY_PRIVATE_PAYLOAD_V1_1")

    # Fixture, research, source, and packaging invariants.
    def test_061_fixture_bank_bytes_and_sha_unchanged(self) -> None:
        self.assertEqual(FIXTURE_BANK_PATH.read_bytes(), self.fixture_bytes_before)
        self.assertEqual(sha256_file(FIXTURE_BANK_PATH), EXPECTED_FIXTURE_BANK_SHA256)

    def test_062_fixture_membership_unchanged(self) -> None:
        rows = [json.loads(line) for line in FIXTURE_BANK_PATH.read_bytes().splitlines()]
        self.assertEqual(tuple(row["fixture_id"] for row in rows), self.fixture_ids_before)

    def test_063_expected_fixture_decisions_and_coverage_unchanged(self) -> None:
        rows = [json.loads(line) for line in FIXTURE_BANK_PATH.read_bytes().splitlines()]
        observed = tuple((row["fixture_id"], row["expected_write_decision"], row["expected_retrieval_ids"], row["expected_admission_ids"], row["expected_rejection_reasons"], row["expected_clarification"], row["expected_security_state"], row["coverage_tags"]) for row in rows)
        self.assertEqual(observed, self.fixture_decisions_before)

    def test_064_r2_history_byte_identical(self) -> None:
        self.assertEqual(verify_r2_tracked_history()["tracked_manifest_sha256"], self.r2_manifest_before)

    def test_065_no_human_annotation_p2_store_retrieval_or_production_change(self) -> None:
        report = json.loads((HERE / "rq2c0_r3_preflight_report_v1.json").read_text())
        for key in ("human_annotation_changed", "p2_implemented", "persistent_store_implemented", "actual_retrieval_executed", "production_routing_changed", "rag_memory_planner_behaviour_changed"):
            self.assertFalse(report[key])
        self.assertEqual(validate_no_implementation()["forbidden_implementation_count"], 0)

    def test_066_track_a_and_track_b_access_rejected(self) -> None:
        for partition in ("TRACK_A", "TRACK_B"):
            with self.assertRaises(PermissionError):
                assert_partition_access_allowed(partition)

    def test_067_no_model_training_provider_or_network(self) -> None:
        report = json.loads((HERE / "rq2c0_r3_preflight_report_v1.json").read_text())
        self.assertFalse(report["model_training"])
        self.assertEqual(report["provider_calls"], 0)
        self.assertFalse(report["network_access"])

    def test_068_feature_isolation_and_new_python_ast(self) -> None:
        self.assertEqual(validate_feature_isolation()["forbidden_feature_reference_count"], 0)
        self.assertEqual(validate_python_ast()["python_file_count"], 9)

    def test_069_corrected_algorithm_double_run_identical(self) -> None:
        records = (*_invalid_high_records(), _record("valid", dense_score=0.1))
        self.assertEqual(rank_hybrid_state_aware_v1_1_with_trace(_plan(), records), rank_hybrid_state_aware_v1_1_with_trace(_plan(), records))

    def test_070_double_build_byte_identical(self) -> None:
        build_all()
        paths = [ROOT / relative for relative in parse_output_checksums()]
        paths.append(ROOT / CHECKSUM_RELATIVE)
        before = {path.relative_to(ROOT).as_posix(): path.read_bytes() for path in paths}
        build_all()
        after = {path.relative_to(ROOT).as_posix(): path.read_bytes() for path in paths}
        self.assertEqual(before, after)

    def test_071_output_checksums_18_of_18(self) -> None:
        self.assertEqual(validate_output_checksums()["referenced_output_count"], 18)

    def test_072_review_package_completeness(self) -> None:
        result = validate_review_package_contract()
        self.assertEqual(result["referenced_output_member_count"], 18)
        self.assertEqual(result["expected_review_member_count"], 23)
        self.assertEqual(len(expected_review_members()), 23)

    def test_073_governed_text_leak_scan(self) -> None:
        self.assertEqual(governed_text_leak_scan()["leak_count"], 0)

    def test_074_safe_outputs(self) -> None:
        self.assertEqual(validate_safe_outputs()["safe_output_count"], 6)

    def test_075_protected_sources_unchanged(self) -> None:
        self.assertEqual(protected_manifest()["status"], "PASS")
        self.assertEqual(protected_source_comparison()["protected_existing_change_count"], 0)

    def test_076_staged_allowlist(self) -> None:
        self.assertEqual(staged_allowlist()["status"], "PASS")

    def test_077_full_validator_passes(self) -> None:
        self.assertEqual(validate_all()["status"], "PASS_MEMORY_SAFETY_CONTRACT_FREEZE")

    @classmethod
    def tearDownClass(cls) -> None:
        if FIXTURE_BANK_PATH.read_bytes() != cls.fixture_bytes_before:
            raise AssertionError("fixture bank changed during RQ2-C0-R3 tests")
        if verify_r2_tracked_history()["tracked_manifest_sha256"] != cls.r2_manifest_before:
            raise AssertionError("R2 history changed during RQ2-C0-R3 tests")


if __name__ == "__main__":
    unittest.main()
