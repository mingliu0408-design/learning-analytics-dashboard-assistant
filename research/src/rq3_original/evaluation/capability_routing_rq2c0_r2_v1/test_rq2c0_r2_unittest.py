"""Contract and mechanism-specific conformance tests for RQ2-C0-R2."""

from __future__ import annotations

from copy import deepcopy
from dataclasses import replace
import hashlib
import json
import subprocess
import unittest

from . import (
    AMENDMENT_AUTHORITY_TYPE,
    AMENDMENT_CONTRACT_ID,
    EXPECTED_FIXTURE_BANK_SHA256,
    EXPECTED_FIXTURE_BANK_SIZE,
    EXPECTED_FIXTURE_RECORD_COUNT,
    EXPECTED_GOLD_BUNDLE_SHA256,
    EXPECTED_P1_POLICY,
    EXPECTED_R1_REVIEW_ZIP_SHA256,
    HERE,
    R1_FIXTURE_BANK_PATH,
    R1_REVIEW_ZIP,
    RESULT_BRANCH,
    ROOT,
    STARTING_HEAD,
    STARTING_PARENT,
    sha256_file,
)
from .condition_semantics import condition_semantics_contract, validate_condition_semantics
from .episode_schema_v1_1 import (
    MemoryEpisodeV1_1,
    episode_schema_contract,
    validate_episode_payload_consistency,
)
from .event_type_compatibility import (
    EVENT_TO_MEMORY_TYPE,
    evaluate_event_type_compatibility,
)
from .executable_admission_contract import (
    MAX_ADMITTED_MEMORIES,
    admit_ranked_candidates,
    admission_contract,
    evaluate_relevance_support,
)
from .executable_retrieval_contract import (
    DENSE_TOP_K,
    POLICY_IDS,
    PRIMARY_POLICY_ID,
    MemoryIndexRecordV1_1,
    RankedMemoryCandidateV1_1,
    RetrievalPlanV1_1,
    cosine_similarity,
    executable_retrieval_contract,
    hard_safety_filter,
    rank_candidates,
    rank_dense_only,
    rank_hybrid_state_aware,
    rank_hybrid_type_temporal,
    rank_kw_legacy,
    temporal_validity,
    type_compatibility,
)
from .fixture_semantic_commitment import build_semantic_commitments
from .fixture_semantic_validator import (
    GOVERNED_GROUPS,
    PERSISTENT_GROUPS,
    RAG_CANDIDATE_GROUP,
    RAG_SUFFICIENCY_GROUP,
    FixtureSemanticError,
    fixture_validation_amendment_authority,
    load_frozen_fixture_rows,
    mechanism_specific_field_semantics_contract,
    validate_all_fixture_semantics,
    validate_fixture_semantics,
    validate_persistent_memory_fixture,
    validate_rag_candidate_gate_fixture,
    validate_rag_sufficiency_fixture,
)
from .literature_evidence import LITERATURE_EVIDENCE, literature_evidence_manifest
from .multi_hop_contract import evaluate_multi_hop_completeness, multi_hop_contract
from .payload_schema import (
    MemoryPayloadRefV1,
    MemoryPayloadV1,
    computed_payload_content_hash,
    payload_boundary_contract,
    validate_payload_reference,
)
from .text_normalisation import (
    FROZEN_DENSE_ENCODER,
    dense_memory_representation,
    dense_query_representation,
    normalise_lexical_entity,
    normalise_text_for_hash,
    normalised_text_hash,
    representation_contract,
)
from .validate_rq2c0_r2 import (
    CHECKSUM_RELATIVE,
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
    verify_r1_output_checksums,
    verify_starting_authority,
)
from .write_candidate_contract import (
    ALLOWED_CANDIDATE_SOURCES,
    FORBIDDEN_CANDIDATE_SOURCES,
    StructuredWriteCandidateV1,
    evaluate_structured_write_candidate,
    write_candidate_boundary_contract,
)


ZERO_HASH = "0" * 64
ONE_HASH = "1" * 64


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


def _ranked(record: MemoryIndexRecordV1_1, *, plan: RetrievalPlanV1_1 | None = None) -> RankedMemoryCandidateV1_1:
    current = plan or _plan()
    compatible, unspecified = type_compatibility(record, current.target_memory_types)
    return RankedMemoryCandidateV1_1(
        record=record,
        type_compatible=compatible,
        target_type_unspecified=unspecified,
        temporal_validity=temporal_validity(record, current.query_time),
    )


class RQ2C0R2ContractTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.fixture_sha_before = sha256_file(R1_FIXTURE_BANK_PATH)
        cls.rows = load_frozen_fixture_rows()
        cls.fixtures = [row for row, _ in cls.rows]
        cls.by_id = {row["fixture_id"]: row for row in cls.fixtures}
        cls.by_category = {row["fixture_category"]: row for row in cls.fixtures}
        cls.global_store_ids = {
            str(item.get("memory_id") or item.get("evidence_id"))
            for fixture in cls.fixtures
            for item in fixture["initial_store_state"]
            if item.get("memory_id") or item.get("evidence_id")
        }
        build_all()
        cls.validation = validate_all_fixture_semantics()
        cls.commitments = build_semantic_commitments(cls.validation)

    # Starting authority and immutable inputs.
    def test_001_result_branch_and_starting_head(self) -> None:
        self.assertEqual(_git("branch", "--show-current"), RESULT_BRANCH)
        self.assertEqual(_git("rev-parse", f"{STARTING_HEAD}^"), STARTING_PARENT)
        self.assertEqual(_git("merge-base", STARTING_HEAD, "HEAD"), STARTING_HEAD)
        self.assertIn(int(_git("rev-list", "--count", f"{STARTING_HEAD}..HEAD")), (0, 1))

    def test_002_r1_review_zip_sha(self) -> None:
        self.assertTrue(R1_REVIEW_ZIP.is_file())
        self.assertEqual(sha256_file(R1_REVIEW_ZIP), EXPECTED_R1_REVIEW_ZIP_SHA256)

    def test_003_r1_output_checksums_30_of_30(self) -> None:
        self.assertEqual(verify_r1_output_checksums(), 30)

    def test_004_fixture_bank_identity(self) -> None:
        self.assertEqual(sha256_file(R1_FIXTURE_BANK_PATH), EXPECTED_FIXTURE_BANK_SHA256)
        self.assertEqual(R1_FIXTURE_BANK_PATH.stat().st_size, EXPECTED_FIXTURE_BANK_SIZE)
        self.assertEqual(len(self.rows), EXPECTED_FIXTURE_RECORD_COUNT)

    def test_005_p1_and_gold_immutable(self) -> None:
        authority = verify_starting_authority()
        self.assertEqual(authority["p1_policy"], EXPECTED_P1_POLICY)
        self.assertTrue(authority["p1_policy_immutable"])
        self.assertEqual(authority["gold_bundle_sha256"], EXPECTED_GOLD_BUNDLE_SHA256)

    # Payload, episode, and write boundaries.
    def test_006_payload_reference_schema(self) -> None:
        contract = payload_boundary_contract()
        self.assertEqual(contract["tracked_safe_schema"]["name"], "MemoryPayloadRefV1")
        self.assertFalse(contract["tracked_safe_schema"]["actual_text_allowed"])
        self.assertNotIn("canonical_text", contract["tracked_safe_schema"]["fields"])

    def test_007_private_payload_schema(self) -> None:
        contract = payload_boundary_contract()["private_local_schema"]
        self.assertEqual(contract["storage"], "IGNORED_LOCAL_ONLY_PRIVATE_STORE")
        self.assertFalse(contract["git_eligible"])
        self.assertFalse(contract["review_zip_eligible"])
        self.assertIn("canonical_text", contract["fields"])

    def _payload_triplet(self) -> tuple[MemoryEpisodeV1_1, MemoryPayloadRefV1, MemoryPayloadV1]:
        content_hash = normalised_text_hash("")
        payload = MemoryPayloadV1(
            payload_id="payload-1",
            memory_id="memory-1",
            canonical_text="",
            structured_value=None,
            content_type="text/plain",
            locale="en-GB",
            source_episode_id="episode-1",
            source_turn_id="turn-1",
            content_hash=content_hash,
        )
        payload_ref = MemoryPayloadRefV1(
            payload_id="payload-1",
            memory_id="memory-1",
            student_scope_hash=ZERO_HASH,
            content_hash=content_hash,
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
            raw_content_hash=content_hash,
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

    def test_008_episode_payload_hash_consistency(self) -> None:
        episode, payload_ref, payload = self._payload_triplet()
        validate_payload_reference(payload_ref)
        self.assertEqual(computed_payload_content_hash(payload), episode.raw_content_hash)
        validate_episode_payload_consistency(episode, payload_ref, payload)

    def test_009_episode_payload_hash_mismatch_rejected(self) -> None:
        episode, payload_ref, payload = self._payload_triplet()
        with self.assertRaisesRegex(ValueError, "content hash mismatch"):
            validate_episode_payload_consistency(
                replace(episode, raw_content_hash=ONE_HASH), payload_ref, payload
            )

    def test_010_event_and_ingestion_time_separated(self) -> None:
        episode, payload_ref, payload = self._payload_triplet()
        self.assertNotEqual(episode.event_time, episode.ingested_at)
        with self.assertRaisesRegex(ValueError, "ingestion precedes event"):
            validate_episode_payload_consistency(
                replace(episode, ingested_at="2026-08-27T11:59:59+00:00"),
                payload_ref,
                payload,
            )

    def test_011_episode_schema_has_versioned_fields(self) -> None:
        contract = episode_schema_contract()
        self.assertEqual(contract["current_contract"], "PersistentLearnerMemoryV1_1")
        self.assertFalse(contract["episode_contains_raw_text"])
        self.assertIn("payload_id", contract["added_fields"])
        self.assertIn("projection_eligible", contract["added_fields"])

    def test_012_allowed_candidate_sources(self) -> None:
        for source in ALLOWED_CANDIDATE_SOURCES:
            candidate = StructuredWriteCandidateV1(
                candidate_source=source,
                event_type="EXPLICIT_STUDENT_GOAL",
                supplied_memory_type="GOAL",
                source_structured=True,
                explicit_user_source=source.startswith("STRUCTURED") or source.startswith("EXPLICIT"),
                verified_system_event=source.startswith("VERIFIED"),
                sensitive_inference=False,
            )
            self.assertTrue(evaluate_structured_write_candidate(candidate).write_authorised)

    def test_013_free_form_and_sensitive_inference_rejected(self) -> None:
        for source in FORBIDDEN_CANDIDATE_SOURCES:
            candidate = StructuredWriteCandidateV1(
                candidate_source=source,
                event_type="EXPLICIT_STUDENT_PREFERENCE",
                supplied_memory_type="PREFERENCE",
                source_structured=True,
                explicit_user_source=True,
                verified_system_event=False,
                sensitive_inference=source.startswith("MODEL_DERIVED"),
            )
            self.assertFalse(evaluate_structured_write_candidate(candidate).write_authorised)
        self.assertFalse(
            write_candidate_boundary_contract()[
                "open_ended_free_text_memory_candidate_extraction_evaluated_in_rq2c1"
            ]
        )

    def test_014_exact_event_to_type_mapping(self) -> None:
        self.assertEqual(len(EVENT_TO_MEMORY_TYPE), 8)
        for event_type, memory_type in EVENT_TO_MEMORY_TYPE.items():
            decision = evaluate_event_type_compatibility(event_type, memory_type)
            self.assertTrue(decision.write_authorised)
            self.assertFalse(decision.automatic_reclassification)

    def test_015_unknown_and_mismatched_event_type_rejected(self) -> None:
        unknown = evaluate_event_type_compatibility("UNKNOWN", "GOAL")
        mismatch = evaluate_event_type_compatibility("EXPLICIT_STUDENT_GOAL", "PLAN")
        self.assertEqual(unknown.failure_reason, "UNSUPPORTED_EVENT_TYPE")
        self.assertEqual(mismatch.failure_reason, "EVENT_MEMORY_TYPE_MISMATCH")
        self.assertFalse(unknown.write_authorised)
        self.assertFalse(mismatch.write_authorised)

    # Deterministic representation and frozen encoder.
    def test_016_text_hash_normalisation(self) -> None:
        left = "  A\r\nB  "
        right = "A\nB"
        self.assertEqual(normalise_text_for_hash(left), right)
        self.assertEqual(normalised_text_hash(left), normalised_text_hash(right))
        self.assertNotEqual(normalised_text_hash("A B"), normalised_text_hash("a b"))

    def test_017_lexical_normalisation(self) -> None:
        self.assertEqual(normalise_lexical_entity("  A，  B!  "), "a b")

    def test_018_frozen_mpnet_identity(self) -> None:
        self.assertEqual(FROZEN_DENSE_ENCODER["model"], "sentence-transformers/all-mpnet-base-v2")
        self.assertEqual(
            FROZEN_DENSE_ENCODER["revision"],
            "e8c3b32edf5434bc2275fc9bab85f82640a19130",
        )
        self.assertTrue(FROZEN_DENSE_ENCODER["local_files_only"])
        self.assertEqual(FROZEN_DENSE_ENCODER["device"], "CPU")
        self.assertFalse(FROZEN_DENSE_ENCODER["fallback_encoder_allowed"])

    def test_019_dense_query_representation(self) -> None:
        self.assertEqual(
            dense_query_representation(
                original_query="original", resolved_query="resolved", resolver_authorised=True
            ),
            "resolved",
        )
        self.assertEqual(
            dense_query_representation(
                original_query="original", resolved_query="resolved", resolver_authorised=False
            ),
            "original",
        )

    def test_020_dense_memory_representation(self) -> None:
        _, _, payload = self._payload_triplet()
        self.assertEqual(dense_memory_representation(payload), "")
        with self.assertRaises(TypeError):
            dense_memory_representation(object())

    def test_021_cosine_and_representation_exclusions(self) -> None:
        self.assertAlmostEqual(cosine_similarity((1.0, 0.0), (1.0, 0.0)), 1.0)
        contract = representation_contract()
        self.assertIn("GOLD_LABELS", contract["forbidden_embedding_components"])
        self.assertFalse(contract["encoder_executed"])

    # Four executable metadata-only retrieval policies.
    def test_022_dense_top_k_and_deterministic_tie_break(self) -> None:
        records = [
            _record(f"m-{index:02d}", dense_score=0.5, event_time="2026-08-26T12:00:00+00:00")
            for index in range(7)
        ]
        result = rank_dense_only(_plan(), reversed(records))
        self.assertEqual(DENSE_TOP_K, 5)
        self.assertEqual([item.record.memory_id for item in result], [f"m-{i:02d}" for i in range(5)])
        self.assertEqual([item.record.dense_rank for item in result], [1, 2, 3, 4, 5])

    def test_023_dense_tie_break_prefers_newer_event(self) -> None:
        older = _record("a", dense_score=0.9, event_time="2026-08-25T00:00:00+00:00")
        newer = _record("z", dense_score=0.9, event_time="2026-08-26T00:00:00+00:00")
        result = rank_dense_only(_plan(), (older, newer))
        self.assertEqual(result[0].record.memory_id, "z")

    def test_024_hard_scope_and_deleted_filters(self) -> None:
        valid = _record("valid")
        cross = _record("cross", student_scope_id="scope-b")
        deleted = _record("deleted", status="DELETED")
        eligible, rejected = hard_safety_filter((cross, deleted, valid), _plan())
        self.assertEqual([item.memory_id for item in eligible], ["valid"])
        self.assertEqual(rejected, {"cross": "CROSS_STUDENT_SCOPE", "deleted": "DELETED_MEMORY"})

    def test_025_kw_policy_exact_contract(self) -> None:
        explicit = _record("explicit", explicit_state_link=True)
        lexical = _record("lexical", exact_lexical_match=True, entity_overlap_count=2)
        unrelated = _record("unrelated", dense_score=1.0)
        result = rank_kw_legacy(_plan(), (lexical, unrelated, explicit))
        self.assertEqual([item.record.memory_id for item in result], ["explicit", "lexical"])

    def test_026_dense_only_ignores_type_time_and_keywords_for_ranking(self) -> None:
        incompatible = _record(
            "dense",
            memory_type="PLAN",
            valid_until="2026-08-02T00:00:00+00:00",
            dense_score=0.9,
        )
        keyword = _record("keyword", exact_lexical_match=True, dense_score=0.1)
        result = rank_dense_only(_plan(), (keyword, incompatible))
        self.assertEqual(result[0].record.memory_id, "dense")
        self.assertFalse(result[0].type_compatible)
        self.assertFalse(result[0].temporal_validity)

    def test_027_hybrid_candidate_union_and_deduplication(self) -> None:
        records = [_record(f"dense-{i}", dense_score=1.0 - i / 10) for i in range(6)]
        records.append(
            _record(
                "lexical-extra",
                dense_score=-1.0,
                exact_lexical_match=True,
                entity_overlap_count=1,
            )
        )
        result = rank_hybrid_type_temporal(_plan(), records)
        ids = [item.record.memory_id for item in result]
        self.assertEqual(len(ids), len(set(ids)))
        self.assertIn("lexical-extra", ids)
        self.assertLessEqual(len(ids), 5)

    def test_028_hybrid_lexicographic_ranking(self) -> None:
        explicit = _record("explicit", explicit_state_link=True, dense_score=-1.0)
        typed = _record("typed", dense_score=0.1)
        wrong_type = _record("wrong", memory_type="PLAN", dense_score=1.0)
        result = rank_hybrid_type_temporal(_plan(), (wrong_type, typed, explicit))
        self.assertEqual([item.record.memory_id for item in result], ["explicit", "typed", "wrong"])

    def test_029_empty_target_types_are_neutral_and_audited(self) -> None:
        result = rank_hybrid_type_temporal(_plan(target_types=()), (_record("m", dense_score=1.0),))
        self.assertTrue(result[0].type_compatible)
        self.assertTrue(result[0].target_type_unspecified)

    def test_030_state_aware_rejections(self) -> None:
        records = (
            _record("active", dense_score=1.0),
            _record("stale", status="STALE", dense_score=0.9),
            _record("superseded", status="SUPERSEDED", dense_score=0.8),
            _record("cancelled", status="CANCELLED", dense_score=0.7),
            _record("completed", status="COMPLETED", dense_score=0.6),
        )
        result = rank_hybrid_state_aware(_plan(), records)
        self.assertEqual([item.record.memory_id for item in result], ["active"])

    def test_031_completion_exception(self) -> None:
        completed = _record("completed", status="COMPLETED", memory_type="COMPLETION", dense_score=1.0)
        without = rank_hybrid_state_aware(_plan(target_types=("GOAL",)), (completed,))
        with_target = rank_hybrid_state_aware(_plan(target_types=("COMPLETION",)), (completed,))
        self.assertEqual(without, ())
        self.assertEqual([item.record.memory_id for item in with_target], ["completed"])

    def test_032_latest_active_conflict_group_wins(self) -> None:
        common = {
            "governed_entity_set": ("entity",),
            "supersession_chain_id": "chain",
            "explicit_state_link": True,
        }
        old = _record("old", event_time="2026-08-25T00:00:00+00:00", **common)
        new = _record("new", event_time="2026-08-26T00:00:00+00:00", **common)
        result = rank_hybrid_state_aware(_plan(), (old, new))
        self.assertEqual([item.record.memory_id for item in result], ["new"])

    def test_033_latest_explicit_correction_wins(self) -> None:
        old = _record("old", explicit_state_link=True)
        correction = _record(
            "correction",
            memory_type="CORRECTION",
            explicit_state_link=True,
            explicitness="EXPLICIT_STUDENT",
            supersedes_memory_id="old",
            event_time="2026-08-27T00:00:00+00:00",
        )
        result = rank_hybrid_state_aware(_plan(), (old, correction))
        self.assertEqual([item.record.memory_id for item in result], ["correction"])

    def test_034_primary_policy_predesignated_not_selected(self) -> None:
        contract = executable_retrieval_contract()
        self.assertEqual(tuple(contract["policy_ids"]), POLICY_IDS)
        self.assertEqual(PRIMARY_POLICY_ID, "PMR_HYBRID_STATE_AWARE")
        self.assertEqual(
            contract["primary_policy_selection_basis"],
            "PREDESIGNATED_BY_CONTRACT_NOT_FIXTURE_SELECTION",
        )

    def test_035_policy_dispatch_and_unknown_failure(self) -> None:
        for policy_id in POLICY_IDS:
            self.assertIsInstance(rank_candidates(policy_id, _plan(), ()), tuple)
        with self.assertRaisesRegex(ValueError, "unknown policy"):
            rank_candidates("UNREGISTERED", _plan(), ())

    # Admission and multi-hop contracts.
    def test_036_admission_max_three(self) -> None:
        candidates = tuple(
            _ranked(_record(f"m-{i}", explicit_state_link=True)) for i in range(5)
        )
        outcome = admit_ranked_candidates(candidates, _plan())
        self.assertEqual(MAX_ADMITTED_MEMORIES, 3)
        self.assertEqual(outcome.admitted_memory_count, 3)
        self.assertTrue(all(item.failure_reason == "ADMISSION_LIMIT_REACHED" for item in outcome.decisions[3:]))

    def test_037_direct_support(self) -> None:
        supported, basis = evaluate_relevance_support(
            _ranked(_record("direct", explicit_state_link=True))
        )
        self.assertTrue(supported)
        self.assertIn("DIRECT_SUPPORT", basis)

    def test_038_structured_support(self) -> None:
        supported, basis = evaluate_relevance_support(
            _ranked(_record("structured", entity_overlap_count=1))
        )
        self.assertTrue(supported)
        self.assertIn("STRUCTURED_SUPPORT", basis)

    def test_039_dense_support_and_no_automatic_top1(self) -> None:
        supported, basis = evaluate_relevance_support(
            _ranked(_record("dense", dense_rank=3))
        )
        self.assertTrue(supported)
        self.assertIn("DENSE_SUPPORT", basis)
        unsupported = admit_ranked_candidates(
            (_ranked(_record("top-one", dense_rank=None)),), _plan()
        )
        self.assertEqual(unsupported.admitted_memory_count, 0)
        self.assertFalse(unsupported.automatic_top1_admission)

    def test_040_dense_support_still_checks_type_and_time(self) -> None:
        record = _record(
            "dense",
            memory_type="PLAN",
            valid_until="2026-08-02T00:00:00+00:00",
            dense_rank=1,
        )
        supported, basis = evaluate_relevance_support(_ranked(record))
        self.assertFalse(supported)
        self.assertEqual(basis, ())

    def test_041_no_memory_abstention(self) -> None:
        required = admit_ranked_candidates((), _plan(memory_required=True))
        optional = admit_ranked_candidates((), _plan(memory_required=False))
        self.assertTrue(required.clarification)
        self.assertFalse(required.continue_without_memory)
        self.assertTrue(optional.continue_without_memory)
        self.assertFalse(optional.clarification)

    def test_042_admission_contract_separates_retrieval(self) -> None:
        contract = admission_contract()
        self.assertTrue(contract["retrieval_separate_from_admission"])
        self.assertFalse(contract["automatic_top1_admission"])
        self.assertFalse(contract["admission_executed"])

    def test_043_multi_hop_complete(self) -> None:
        plan = _plan(target_types=("GOAL", "PLAN"))
        candidates = (
            _ranked(_record("goal", memory_type="GOAL"), plan=plan),
            _ranked(_record("plan", memory_type="PLAN"), plan=plan),
        )
        result = evaluate_multi_hop_completeness(
            plan.target_memory_types, candidates, task_requires_complete_memory=True
        )
        self.assertTrue(result.multi_hop_request)
        self.assertTrue(result.multi_hop_complete)
        self.assertTrue(result.personalisation_complete_claim_allowed)

    def test_044_multi_hop_incomplete_clarifies_or_safe_partial(self) -> None:
        plan = _plan(target_types=("GOAL", "PLAN"))
        one = (_ranked(_record("goal", memory_type="GOAL"), plan=plan),)
        strict = evaluate_multi_hop_completeness(
            plan.target_memory_types, one, task_requires_complete_memory=True
        )
        partial = evaluate_multi_hop_completeness(
            plan.target_memory_types, one, task_requires_complete_memory=False
        )
        self.assertFalse(strict.multi_hop_complete)
        self.assertTrue(strict.clarification)
        self.assertTrue(partial.safe_partial_response)
        self.assertTrue(partial.explicit_missing_evidence_statement_required)
        self.assertFalse(partial.personalisation_complete_claim_allowed)
        self.assertFalse(multi_hop_contract()["fabricate_missing_memory"])

    # Condition isolation.
    def test_045_p1_context_routing_semantics(self) -> None:
        condition = condition_semantics_contract()["conditions"]["P1_BASE"]
        self.assertTrue(condition["context_envelope_for_capability_routing"])
        self.assertFalse(condition["new_session_state_evidence_admission"])
        self.assertFalse(condition["persistent_store_search"])
        self.assertFalse(condition["dual_gated_rag"])

    def test_046_session_state_evidence_semantics(self) -> None:
        condition = condition_semantics_contract()["conditions"]["P2_SESSION_STATE_ONLY"]
        self.assertTrue(condition["new_session_state_evidence_admission"])
        self.assertTrue(condition["session_state_relevance_and_freshness_gate"])
        self.assertFalse(condition["persistent_store_search"])
        self.assertFalse(condition["dual_gated_rag"])

    def test_047_persistent_only_condition_isolation(self) -> None:
        condition = condition_semantics_contract()["conditions"]["P2_PERSISTENT_MEMORY_ONLY"]
        self.assertFalse(condition["new_session_state_evidence_admission"])
        self.assertTrue(condition["persistent_store_search"])
        self.assertEqual(condition["persistent_policy"], PRIMARY_POLICY_ID)
        self.assertFalse(condition["dual_gated_rag"])

    def test_048_p2_full_composition_and_validation(self) -> None:
        contract = condition_semantics_contract()
        condition = contract["conditions"]["P2_FULL"]
        self.assertTrue(condition["dual_gated_rag"])
        self.assertTrue(condition["new_session_state_evidence_admission"])
        self.assertTrue(condition["persistent_store_search"])
        self.assertTrue(validate_condition_semantics(contract))
        altered = deepcopy(contract)
        altered["conditions"]["P2_FULL"]["dual_gated_rag"] = False
        self.assertFalse(validate_condition_semantics(altered))

    # User-authorised mechanism-specific amendment.
    def test_049_amendment_authority_fields(self) -> None:
        authority = fixture_validation_amendment_authority()
        self.assertEqual(authority["authority_type"], AMENDMENT_AUTHORITY_TYPE)
        self.assertEqual(authority["field_semantics_contract_id"], AMENDMENT_CONTRACT_ID)
        self.assertFalse(authority["fixture_text_change_authorised"])
        self.assertFalse(authority["expected_decision_change_authorised"])

    def test_050_mechanism_specific_contract_exact_groups(self) -> None:
        contract = mechanism_specific_field_semantics_contract()
        detail_groups = {
            row["mechanism_group"] for row in contract["governed_persistent_group_rows"]
        }
        self.assertEqual(detail_groups, set(PERSISTENT_GROUPS))
        self.assertTrue(contract["dispatch_by_exact_mechanism_group"])
        self.assertEqual(contract["unknown_group_policy"], "FAIL_CLOSED")

    def test_051_fx_001_and_fx_002_exact_candidate_group(self) -> None:
        for fixture_id in ("RQ2P2-FX-001", "RQ2P2-FX-002"):
            self.assertEqual(self.by_id[fixture_id]["mechanism_group"], RAG_CANDIDATE_GROUP)

    def test_052_candidate_gate_allows_empty_pre_retrieval_state(self) -> None:
        for fixture in self.fixtures:
            if fixture["mechanism_group"] == RAG_CANDIDATE_GROUP:
                result = validate_rag_candidate_gate_fixture(fixture, self.global_store_ids)
                self.assertTrue(result["empty_pre_retrieval_state"])
                self.assertEqual(result["initial_store_state_semantics"], "PRE_RETRIEVAL_STATE")

    def test_053_candidate_downstream_id_need_not_preexist(self) -> None:
        fixture = self.by_id["RQ2P2-FX-001"]
        self.assertTrue(fixture["expected_retrieval_ids"])
        self.assertFalse(set(fixture["expected_retrieval_ids"]) & self.global_store_ids)
        result = validate_rag_candidate_gate_fixture(fixture, self.global_store_ids)
        self.assertTrue(result["downstream_retrieval_id_commitment"])

    def test_054_candidate_admission_ids_must_be_empty(self) -> None:
        fixture = deepcopy(self.by_id["RQ2P2-FX-001"])
        fixture["expected_admission_ids"] = list(fixture["expected_retrieval_ids"])
        with self.assertRaisesRegex(FixtureSemanticError, "admission IDs must be empty"):
            validate_rag_candidate_gate_fixture(fixture, self.global_store_ids)

    def test_055_candidate_cannot_emit_sufficiency_outcome(self) -> None:
        fixture = deepcopy(self.by_id["RQ2P2-FX-001"])
        fixture["initial_store_state"] = [{"support_status": "SUPPORTED"}]
        with self.assertRaisesRegex(FixtureSemanticError, "cannot encode evidence sufficiency"):
            validate_rag_candidate_gate_fixture(fixture, self.global_store_ids)

    def test_056_candidate_blocked_categories_have_empty_retrieval(self) -> None:
        categories = {
            "RAG_CLARIFICATION_BLOCKS_RETRIEVAL",
            "RAG_EXPLICIT_SOURCE_RESTRICTION",
            "RAG_COURSE_CAPABILITY_ABSENT",
        }
        for category in categories:
            fixture = self.by_category[category]
            self.assertEqual(fixture["expected_retrieval_ids"], [])
            validate_rag_candidate_gate_fixture(fixture, self.global_store_ids)

    def test_057_candidate_blocked_decision_rejects_retrieval_ids(self) -> None:
        fixture = deepcopy(self.by_category["RAG_CLARIFICATION_BLOCKS_RETRIEVAL"])
        fixture["expected_retrieval_ids"] = ["downstream-mutated"]
        with self.assertRaisesRegex(FixtureSemanticError, "candidate decision mismatch"):
            validate_rag_candidate_gate_fixture(fixture, self.global_store_ids)

    def test_058_rag_sufficiency_retrieval_ids_must_exist(self) -> None:
        fixture = deepcopy(self.by_category["RAG_SUFFICIENCY_SUPPORTED"])
        fixture["expected_retrieval_ids"] = ["missing"]
        fixture["expected_admission_ids"] = []
        with self.assertRaisesRegex(FixtureSemanticError, "strict RAG retrieval-ID existence"):
            validate_rag_sufficiency_fixture(fixture)

    def test_059_rag_sufficiency_admission_must_be_retrieved(self) -> None:
        fixture = deepcopy(self.by_category["RAG_SUFFICIENCY_AMBIGUOUS"])
        fixture["expected_admission_ids"] = ["missing"]
        with self.assertRaisesRegex(FixtureSemanticError, "strict RAG retrieval-ID existence"):
            validate_rag_sufficiency_fixture(fixture)

    def test_060_rag_sufficiency_states_derived_from_fields(self) -> None:
        for status in ("SUPPORTED", "AMBIGUOUS", "UNSUPPORTED", "NO_RESULT"):
            fixture = self.by_category[f"RAG_SUFFICIENCY_{status}"]
            result = validate_rag_sufficiency_fixture(fixture)
            self.assertEqual(result["derived_evidence_sufficiency"], status)

    def test_061_persistent_retrieval_id_must_exist(self) -> None:
        fixture = deepcopy(self.by_category["PM_RETRIEVE_PARAPHRASED_PREFERENCE"])
        fixture["expected_retrieval_ids"] = ["missing"]
        fixture["expected_admission_ids"] = []
        with self.assertRaisesRegex(FixtureSemanticError, "strict persistent retrieval-ID existence"):
            validate_persistent_memory_fixture(fixture)

    def test_062_persistent_admission_id_must_be_retrieved(self) -> None:
        fixture = deepcopy(self.by_category["PM_RETRIEVE_NO_RELEVANT_ABSTENTION"])
        fixture["expected_admission_ids"] = [next(iter(self.global_store_ids))]
        with self.assertRaisesRegex(FixtureSemanticError, "strict persistent retrieval-ID existence"):
            validate_persistent_memory_fixture(fixture)

    def test_063_stale_superseded_deleted_cross_scope_are_field_derived(self) -> None:
        categories = (
            "PM_FRESHNESS_STALE_REJECTION",
            "PM_FRESHNESS_LATEST_CORRECTION_WINS",
            "PM_PRIVACY_DELETED_TOMBSTONE_REJECTION",
            "PM_PRIVACY_CROSS_STUDENT_ISOLATION",
        )
        for category in categories:
            result = validate_persistent_memory_fixture(self.by_category[category])
            self.assertEqual(result["semantic_validation_status"], "PASS")

    def test_064_completed_cancelled_and_correction_relations_are_field_derived(self) -> None:
        categories = (
            "PM_FRESHNESS_COMPLETED_CANCELLED_REJECTION",
            "PM_WRITE_CORRECTION_SUPERSEDES",
        )
        for category in categories:
            self.assertEqual(
                validate_persistent_memory_fixture(self.by_category[category])[
                    "semantic_validation_status"
                ],
                "PASS",
            )

    def test_065_multi_hop_fixture_has_two_admitted_types(self) -> None:
        fixture = self.by_category["PM_RETRIEVE_MULTI_HOP_PREFERENCE_CONSTRAINT"]
        store = {item["memory_id"]: item for item in fixture["initial_store_state"]}
        types = {store[item]["memory_type"] for item in fixture["expected_admission_ids"]}
        self.assertGreaterEqual(len(types), 2)
        validate_persistent_memory_fixture(fixture)

    def test_066_no_result_and_write_rejection_are_field_derived(self) -> None:
        no_result = self.by_category["PM_RETRIEVE_NO_RELEVANT_ABSTENTION"]
        rejected = self.by_category["PM_WRITE_SENSITIVE_INFERRED_REJECTED"]
        self.assertEqual(no_result["expected_admission_ids"], [])
        self.assertFalse(rejected["expected_write_decision"]["write_authorised"])
        validate_persistent_memory_fixture(no_result)
        validate_persistent_memory_fixture(rejected)

    def test_067_unknown_group_fails_closed(self) -> None:
        fixture = deepcopy(self.fixtures[0])
        fixture["mechanism_group"] = "UNKNOWN_GROUP"
        with self.assertRaisesRegex(FixtureSemanticError, "unknown mechanism group"):
            validate_fixture_semantics(fixture)

    def test_068_candidate_exception_cannot_apply_to_other_groups(self) -> None:
        sufficiency = next(
            item for item in self.fixtures if item["mechanism_group"] == RAG_SUFFICIENCY_GROUP
        )
        persistent = next(
            item for item in self.fixtures if item["mechanism_group"] in PERSISTENT_GROUPS
        )
        with self.assertRaisesRegex(FixtureSemanticError, "GROUP_MISMATCH"):
            validate_rag_candidate_gate_fixture(sufficiency, self.global_store_ids)
        with self.assertRaisesRegex(FixtureSemanticError, "GROUP_MISMATCH"):
            validate_rag_candidate_gate_fixture(persistent, self.global_store_ids)
        with self.assertRaisesRegex(FixtureSemanticError, "cannot apply to RAG Sufficiency"):
            validate_rag_sufficiency_fixture(persistent)

    def test_069_category_and_tag_derived_validation(self) -> None:
        fixture = deepcopy(self.by_id["RQ2P2-FX-001"])
        fixture["coverage_tags"] = ["WRONG"]
        with self.assertRaisesRegex(FixtureSemanticError, "category or tag mismatch"):
            validate_rag_candidate_gate_fixture(fixture, self.global_store_ids)

    def test_070_semantic_commitments_count_contract_and_no_text(self) -> None:
        self.assertEqual(len(self.commitments), 28)
        allowed = {
            "fixture_id",
            "record_hash",
            "mechanism_group",
            "fixture_category",
            "initial_store_item_count",
            "initial_status_distribution",
            "initial_scope_count",
            "input_text_hash",
            "expected_write_authorised",
            "expected_retrieval_count",
            "expected_admission_count",
            "expected_rejection_reason_codes",
            "expected_clarification",
            "expected_security_state",
            "coverage_tags",
            "field_semantics_contract_id",
            "initial_store_state_semantics",
            "retrieval_id_existence_rule_applied",
            "evidence_sufficiency_applicable",
            "evidence_admission_applicable",
            "semantic_validation_status",
        }
        for commitment in self.commitments:
            self.assertEqual(set(commitment), allowed)
            self.assertEqual(commitment["field_semantics_contract_id"], AMENDMENT_CONTRACT_ID)

    def test_071_all_28_fixtures_pass_with_expected_counts(self) -> None:
        self.assertEqual(self.validation["passed_fixture_count"], 28)
        self.assertEqual(self.validation["failed_fixture_count"], 0)
        self.assertEqual(self.validation["rag_candidate_gate_count"], 6)
        self.assertEqual(self.validation["rag_sufficiency_gate_count"], 8)
        self.assertEqual(self.validation["persistent_fixture_count"], 14)
        self.assertEqual(set(self.validation["group_counts"]), set(GOVERNED_GROUPS))

    def test_072_fixture_bank_text_membership_decisions_and_coverage_unchanged(self) -> None:
        self.assertEqual(sha256_file(R1_FIXTURE_BANK_PATH), self.fixture_sha_before)
        self.assertEqual(self.validation["fixture_text_change_count"], 0)
        self.assertEqual(self.validation["fixture_membership_change_count"], 0)
        self.assertEqual(self.validation["expected_decision_change_count"], 0)
        self.assertEqual(self.validation["coverage_change_count"], 0)

    # Literature, safety, deterministic finalisation, and packaging gates.
    def test_073_literature_identities_and_traceability(self) -> None:
        expected = {
            "LoCoMo",
            "MemoryOS",
            "PREMem",
            "ScaffoldLM",
            "IntelliCode",
            "APEX-MEM",
            "LoCoMo-Plus",
        }
        manifest = literature_evidence_manifest()
        self.assertEqual({row["source_identity"] for row in manifest["sources"]}, expected)
        self.assertEqual(len(LITERATURE_EVIDENCE), 7)
        self.assertTrue(all(row["contract_fields"] for row in manifest["sources"]))

    def test_074_no_unverified_literature_metrics_or_causal_claim(self) -> None:
        manifest = literature_evidence_manifest()
        self.assertEqual(manifest["unverified_experimental_metric_count"], 0)
        self.assertFalse(manifest["causal_proof_claimed"])
        self.assertFalse(manifest["network_lookup_performed"])

    def test_075_track_a_and_track_b_rejected(self) -> None:
        for partition in ("TRACK_A", "TRACK_B"):
            with self.assertRaises(PermissionError):
                assert_partition_access_allowed(partition)

    def test_076_no_implementation_provider_network_or_training(self) -> None:
        self.assertEqual(validate_no_implementation()["implementation_count"], 0)
        report = json.loads((HERE / "rq2c0_r2_preflight_report_v1.json").read_text(encoding="utf-8"))
        self.assertEqual(report["provider_calls"], 0)
        self.assertFalse(report["network_access"])
        self.assertFalse(report["model_training"])
        self.assertFalse(report["p2_implemented"])
        self.assertFalse(report["persistent_store_implemented"])
        self.assertFalse(report["production_routing_changed"])

    def test_077_python_ast_and_safe_outputs(self) -> None:
        self.assertEqual(validate_python_ast()["python_file_count"], 15)
        self.assertEqual(validate_safe_outputs()["safe_output_count"], 15)

    def test_078_double_build_byte_identical(self) -> None:
        build_all()
        paths = [ROOT / relative for relative in parse_output_checksums()]
        paths.append(ROOT / CHECKSUM_RELATIVE)
        before = {path.relative_to(ROOT).as_posix(): path.read_bytes() for path in paths}
        build_all()
        after = {path.relative_to(ROOT).as_posix(): path.read_bytes() for path in paths}
        self.assertEqual(before, after)

    def test_079_output_checksums_36_of_36(self) -> None:
        result = validate_output_checksums()
        self.assertEqual(result["referenced_tracked_output_path_count"], 36)

    def test_080_review_package_completeness_contract(self) -> None:
        result = validate_review_package_contract()
        self.assertEqual(result["referenced_output_member_count"], 36)
        self.assertEqual(result["expected_review_member_count"], 41)
        self.assertEqual(len(expected_review_members()), 41)

    def test_081_governed_text_leak_scan(self) -> None:
        self.assertEqual(governed_text_leak_scan()["leak_count"], 0)

    def test_082_protected_sources_and_staged_allowlist(self) -> None:
        self.assertEqual(protected_source_comparison()["protected_existing_file_change_count"], 0)
        self.assertEqual(staged_allowlist()["status"], "PASS")

    def test_083_full_validator_passes(self) -> None:
        self.assertEqual(validate_all()["status"], "PASS_EXECUTABLE_CONTRACT_FREEZE")

    @classmethod
    def tearDownClass(cls) -> None:
        if sha256_file(R1_FIXTURE_BANK_PATH) != cls.fixture_sha_before:
            raise AssertionError("fixture bank changed during RQ2-C0-R2 tests")


if __name__ == "__main__":
    unittest.main()
