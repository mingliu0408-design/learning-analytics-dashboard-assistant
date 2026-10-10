from __future__ import annotations

import ast
import inspect
import json
import math
import os
from pathlib import Path
import tempfile
import unittest

from evaluation.rq3_real_c4.track_m_memory.evaluate_memory_mechanism import (
    NetworkAccessAttempt,
    deny_network,
)
from utils.c4_memory.c4_memory_provider import C4LearnerMemoryProvider
from utils.c4_memory.c4_memory_retriever import (
    FrozenLocalMPNetBackend,
    MPNET_REVISION,
)
from utils.c4_memory.c4_memory_store import (
    C4MemoryStore,
    C4MemoryStoreError,
    DELETED_CONTENT,
    sha256_object,
)
from utils.c4_memory.c4_memory_writer import (
    C4MemoryWriteError,
    StructuredMemoryCandidate,
)


QUERY_TIME = "2026-09-01T12:00:00+00:00"
EVENT_TIME = "2026-08-20T09:00:00+00:00"
PROJECT_ROOT = Path(__file__).resolve().parents[4]


class DeterministicSemanticBackend:
    """Test double for semantic similarity; never opens a network connection."""

    CONCEPTS = (
        ("goal", "objective", "outcome", "improve", "working toward", "achieve"),
        ("prefer", "preference", "like", "schedule", "morning", "evening", "environment", "suits", "format"),
        ("constraint", "limit", "minute", "available time", "deadline"),
        ("difficult", "difficulty", "struggle", "hard"),
        ("completed", "finished", "already", "done"),
        ("active plan", "plan", "commit", "next action", "will reply"),
        ("progress", "how far", "two of", "prompts"),
        ("correction", "actually", "meant", "finally", "rather than", "replacing"),
    )

    @property
    def identity(self):
        return {
            "backend": "DETERMINISTIC_TEST_SEMANTIC",
            "network_allowed": False,
            "revision": "test-v1",
        }

    def encode(self, texts):
        output = []
        for text in texts:
            lowered = str(text).casefold()
            vector = [float(sum(1 for term in terms if term in lowered)) for terms in self.CONCEPTS]
            norm = math.sqrt(sum(value * value for value in vector))
            if norm:
                vector = [value / norm for value in vector]
            output.append(vector)
        return output


class StrongTypeLowContentBackend:
    @property
    def identity(self):
        return {"backend": "STRONG_TYPE_TEST", "network_allowed": False}

    def encode(self, texts):
        vectors = []
        for text in texts:
            lowered = str(text).casefold()
            if "what study action" in lowered:
                vectors.append([1.0, 0.0, 0.0])
            elif "i will reply" in lowered:
                vectors.append([0.15, math.sqrt(1.0 - 0.15**2), 0.0])
            elif "current learner-accepted action" in lowered:
                vectors.append([1.0, 0.0, 0.0])
            else:
                vectors.append([0.0, 0.0, 1.0])
        return vectors


def candidate(
    operation: str,
    memory_type: str | None,
    content: str | None,
    *,
    target: str | None = None,
    confidence: float = 0.99,
    evidence: str | None = None,
) -> StructuredMemoryCandidate:
    return StructuredMemoryCandidate(
        operation=operation,
        memory_type=memory_type,
        content=content,
        target_memory_id=target,
        confidence=confidence,
        evidence_span=(content or "") if evidence is None else evidence,
    )


class C4MemoryTestCase(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory(prefix="c4_memory_test_")
        self.db_path = Path(self.temp.name) / "run.sqlite"
        self.store = C4MemoryStore(self.db_path, clock=lambda: QUERY_TIME)
        self.backend = DeterministicSemanticBackend()
        self.provider = C4LearnerMemoryProvider(
            self.store,
            semantic_backend=self.backend,
            clock=lambda: QUERY_TIME,
        )

    def tearDown(self) -> None:
        try:
            self.store.close()
        except Exception:
            pass
        self.temp.cleanup()

    def apply(
        self,
        *,
        student_id: str = "synthetic_a",
        operation: str = "ADD",
        memory_type: str | None = "GOAL",
        content: str | None = "I want to improve debate participation.",
        target: str | None = None,
        confidence: float = 0.99,
        evidence: str | None = None,
        source_text: str | None = None,
        source_role: str = "USER",
        claim_basis: str = "EXPLICIT_USER_STATEMENT",
        unrelated_sensitive: bool = False,
        event_at: str = EVENT_TIME,
        valid_from: str | None = None,
        valid_to: str | None = None,
        turn: str = "turn-1",
    ):
        evidence_value = (content or "") if evidence is None else evidence
        return self.provider.writer.apply_candidate(
            student_id=student_id,
            source_session_id="session-1",
            source_turn_id=turn,
            source_text=source_text if source_text is not None else evidence_value,
            candidate=candidate(
                operation,
                memory_type,
                content,
                target=target,
                confidence=confidence,
                evidence=evidence_value,
            ),
            source_role=source_role,
            claim_basis=claim_basis,
            unrelated_sensitive_information=unrelated_sensitive,
            event_at=event_at,
            valid_from=valid_from,
            valid_to=valid_to,
        )

    def test_001_file_database_is_required_per_run(self) -> None:
        with self.assertRaisesRegex(C4MemoryStoreError, "FILE_DATABASE_REQUIRED"):
            C4MemoryStore(":memory:")

    def test_002_schema_and_contract_contain_required_fields(self) -> None:
        contract_path = PROJECT_ROOT / "utils/c4_memory/c4_memory_contract_v1.json"
        contract = json.loads(contract_path.read_text(encoding="utf-8"))
        required = set(contract["schema"]["required_memory_fields"])
        self.assertTrue(
            {
                "memory_id", "student_id", "memory_type", "content", "source_session_id",
                "source_turn_id", "created_at", "valid_from", "valid_to", "last_confirmed_at",
                "status", "importance", "confidence", "supersedes_memory_id", "consent_status",
                "content_sha256",
            }
            <= required
        )
        self.assertEqual(contract["architecture_id"], "C4_LEARNER_MEMORY_V1")

    def test_003_add_persists_after_close_and_reopen(self) -> None:
        result = self.apply()
        self.assertEqual(result.applied_operation, "ADD")
        self.store.close()
        self.store = C4MemoryStore(self.db_path, clock=lambda: QUERY_TIME)
        record = self.store.get_memory("synthetic_a", result.memory_id)
        self.assertIsNotNone(record)
        self.assertEqual(record.content, "I want to improve debate participation.")

    def test_004_learner_isolation(self) -> None:
        self.apply(student_id="synthetic_a", content="I want to improve reflection writing.")
        self.apply(student_id="synthetic_b", memory_type="PREFERENCE", content="I prefer audio summaries.", turn="turn-b")
        envelope = self.provider.retrieve("synthetic_a", "What reflection objective was I pursuing?", [])
        self.assertEqual(len(envelope["selected_memory_items"]), 1)
        self.assertIn("reflection writing", envelope["selected_memory_items"][0]["content"])
        self.assertNotIn("audio", json.dumps(envelope))

    def test_005_update_appends_version_and_supersedes_old(self) -> None:
        old = self.apply(memory_type="PREFERENCE", content="I prefer studying in the morning.")
        new = self.apply(
            operation="UPDATE",
            memory_type="PREFERENCE",
            content="I prefer studying in the evening.",
            target=old.memory_id,
            event_at="2026-08-21T09:00:00+00:00",
            turn="turn-2",
        )
        self.assertEqual(new.applied_operation, "UPDATE")
        self.assertEqual(self.store.get_memory("synthetic_a", old.memory_id).status, "SUPERSEDED")
        self.assertEqual(self.store.get_memory("synthetic_a", new.memory_id).version, 2)

    def test_006_explicit_correction_supersedes_old_item(self) -> None:
        old = self.apply(content="I want to catch up with the W4 lecture.")
        correction = self.apply(
            operation="SUPERSEDE",
            memory_type="CORRECTION",
            content="Actually, I meant W5 rather than W4.",
            target=old.memory_id,
            event_at="2026-08-21T09:00:00+00:00",
            turn="turn-2",
        )
        self.assertEqual(correction.applied_operation, "SUPERSEDE")
        envelope = self.provider.retrieve("synthetic_a", "Which week did I finally mean?", [])
        self.assertEqual(envelope["selected_memory_items"][0]["memory_id"], correction.memory_id)
        self.assertNotIn(old.memory_id, [item["memory_id"] for item in envelope["selected_memory_items"]])

    def test_007_delete_creates_redacted_tombstone(self) -> None:
        old = self.apply()
        deleted = self.apply(
            operation="DELETE",
            memory_type=None,
            content=None,
            target=old.memory_id,
            evidence="Forget that goal.",
            source_text="Forget that goal.",
            event_at="2026-08-21T09:00:00+00:00",
            turn="turn-2",
        )
        self.assertEqual(deleted.applied_operation, "DELETE")
        record = self.store.get_memory("synthetic_a", old.memory_id)
        self.assertEqual(record.status, "DELETED")
        self.assertEqual(record.content, DELETED_CONTENT)
        self.assertIsNotNone(record.deletion_event_sha256)

    def test_008_noop_operation_writes_no_memory(self) -> None:
        result = self.apply(operation="NOOP", memory_type=None, content=None, evidence="")
        self.assertEqual(result.applied_operation, "NOOP")
        self.assertEqual(self.store.list_memories("synthetic_a"), [])

    def test_009_duplicate_active_fact_is_suppressed(self) -> None:
        first = self.apply()
        second = self.apply(turn="turn-2", event_at="2026-08-20T09:01:00+00:00")
        self.assertTrue(first.accepted)
        self.assertFalse(second.accepted)
        self.assertEqual(second.reason_code, "DUPLICATE_ACTIVE_FACT")
        self.assertEqual(second.duplicate_memory_id, first.memory_id)

    def test_010_low_confidence_is_rejected(self) -> None:
        result = self.apply(confidence=0.79)
        self.assertEqual(result.reason_code, "LOW_CONFIDENCE")
        self.assertEqual(self.store.list_memories("synthetic_a"), [])

    def test_011_assistant_advice_is_not_stored_as_learner_fact(self) -> None:
        result = self.apply(
            memory_type="ACTIVE_PLAN",
            content="Review the lecture tomorrow.",
            source_role="ASSISTANT",
            claim_basis="ASSISTANT_ADVICE",
        )
        self.assertEqual(result.reason_code, "ASSISTANT_ADVICE_NOT_LEARNER_FACT")
        self.assertEqual(self.store.list_memories("synthetic_a"), [])

    def test_012_inferred_ability_is_rejected(self) -> None:
        result = self.apply(
            memory_type="DIFFICULTY",
            content="I am bad at statistics.",
            evidence="I got two answers wrong.",
            source_text="I got two answers wrong.",
            claim_basis="INFERRED_ABILITY",
        )
        self.assertEqual(result.reason_code, "INFERRED_ABILITY")

    def test_013_unsupported_dashboard_interpretation_is_rejected(self) -> None:
        result = self.apply(
            memory_type="DIFFICULTY",
            content="Dashboard completion is 40 percent.",
            source_role="SYSTEM",
            claim_basis="UNVERIFIED_DASHBOARD_INTERPRETATION",
        )
        self.assertEqual(result.reason_code, "UNVERIFIED_DASHBOARD_INTERPRETATION")

    def test_014_unrelated_sensitive_information_is_rejected(self) -> None:
        result = self.apply(
            memory_type="CONSTRAINT",
            content="A private identifier is unrelated to studying.",
            unrelated_sensitive=True,
        )
        self.assertEqual(result.reason_code, "UNRELATED_SENSITIVE_INFORMATION")

    def test_015_evidence_span_must_come_from_source(self) -> None:
        result = self.apply(source_text="Different user statement.")
        self.assertEqual(result.reason_code, "EVIDENCE_SPAN_NOT_IN_SOURCE")

    def test_016_content_must_be_supported_by_evidence_span(self) -> None:
        result = self.apply(
            memory_type="DIFFICULTY",
            content="I have low ability.",
            evidence="I missed two questions.",
            source_text="I missed two questions.",
        )
        self.assertEqual(result.reason_code, "CONTENT_NOT_SUPPORTED_BY_EVIDENCE_SPAN")

    def test_017_expired_memory_is_temporally_invalid(self) -> None:
        self.apply(
            memory_type="CONSTRAINT",
            content="I only have ten minutes this week.",
            event_at="2026-08-01T09:00:00+00:00",
            valid_to="2026-08-15T09:00:00+00:00",
        )
        envelope = self.provider.retrieve("synthetic_a", "How much time was available?", [])
        self.assertEqual(envelope["status"], "NO_MATCH")

    def test_018_future_memory_is_temporally_invalid(self) -> None:
        self.apply(
            content="I want to review the Week 8 lecture.",
            valid_from="2026-09-10T09:00:00+00:00",
        )
        envelope = self.provider.retrieve("synthetic_a", "What Week 8 goal did I set?", [])
        self.assertEqual(envelope["status"], "NO_MATCH")

    def test_019_fts_lexical_retrieval(self) -> None:
        result = self.apply(content="I want to improve debate participation.")
        envelope = self.provider.retrieve("synthetic_a", "debate participation", [])
        item = envelope["selected_memory_items"][0]
        self.assertEqual(item["memory_id"], result.memory_id)
        self.assertGreater(item["relevance_components"]["lexical"], 0.0)

    def test_020_semantic_retrieval_without_lexical_overlap(self) -> None:
        result = self.apply(memory_type="PREFERENCE", content="I prefer quiet rooms.")
        envelope = self.provider.retrieve("synthetic_a", "Which study environment suits me?", [])
        item = envelope["selected_memory_items"][0]
        self.assertEqual(item["memory_id"], result.memory_id)
        self.assertEqual(item["relevance_components"]["lexical"], 0.0)
        self.assertTrue(item["relevance_components"]["semantic_supported"])

    def test_021_no_match_abstains_instead_of_forcing_nearest(self) -> None:
        self.apply(memory_type="PREFERENCE", content="I prefer quiet rooms.")
        envelope = self.provider.retrieve("synthetic_a", "What does Total_chars mean?", [])
        self.assertEqual(envelope["status"], "NO_MATCH")
        self.assertEqual(envelope["selected_memory_items"], [])

    def test_022_visible_history_content_is_excluded(self) -> None:
        self.apply(content="I want to review the W5 reading.")
        history = [{"role": "user", "content": "I want to review the W5 reading."}]
        envelope = self.provider.retrieve("synthetic_a", "What was my goal?", history)
        self.assertEqual(envelope["status"], "NO_MATCH")
        self.assertEqual(envelope["retrieval"]["visible_history_excluded_count"], 1)

    def test_023_envelope_contains_type_version_relevance_and_provenance(self) -> None:
        self.apply()
        envelope = self.provider.retrieve("synthetic_a", "What goal did I want to achieve?", [])
        item = envelope["selected_memory_items"][0]
        self.assertEqual(item["memory_type"], "GOAL")
        self.assertEqual(item["timestamp_version"]["version"], 1)
        self.assertIn("fusion", item["relevance_components"])
        self.assertIn("source_session_id", item["provenance"])
        self.assertFalse(item["read_only_evidence"]["mutable"])

    def test_024_envelope_sha256_is_canonical(self) -> None:
        self.apply()
        envelope = self.provider.retrieve("synthetic_a", "What goal did I want to achieve?", [])
        observed = envelope.pop("envelope_sha256")
        self.assertEqual(observed, sha256_object(envelope))

    def test_025_internal_embeddings_are_not_exposed(self) -> None:
        self.apply()
        envelope = self.provider.retrieve("synthetic_a", "What goal did I want to achieve?", [])
        serialised = json.dumps(envelope, sort_keys=True)
        self.assertNotIn('"embedding"', serialised)
        self.assertNotIn('"vector"', serialised)
        self.assertFalse(envelope["retrieval"]["embeddings_exposed"])

    def test_026_disable_memory_for_learner(self) -> None:
        self.apply()
        self.provider.disable_memory_for_learner("synthetic_a", event_at="2026-08-21T09:00:00+00:00")
        envelope = self.provider.retrieve("synthetic_a", "What goal did I want to achieve?", [])
        self.assertEqual(envelope["status"], "NO_MATCH")
        self.assertIn("MEMORY_DISABLED_FOR_LEARNER", envelope["limitations"])

    def test_027_disabled_learner_cannot_write(self) -> None:
        self.provider.disable_memory_for_learner("synthetic_a", event_at="2026-08-19T09:00:00+00:00")
        result = self.apply()
        self.assertEqual(result.reason_code, "MEMORY_DISABLED_FOR_LEARNER")

    def test_028_list_active_memories_control(self) -> None:
        self.apply()
        rows = self.provider.list_active_memories("synthetic_a")
        self.assertEqual(len(rows), 1)
        self.assertTrue(rows[0]["read_only"])

    def test_029_correct_memory_control(self) -> None:
        old = self.apply(content="I want to review W4.")
        result = self.provider.correct_memory(
            student_id="synthetic_a",
            target_memory_id=old.memory_id,
            corrected_content="Actually, I meant W5.",
            source_session_id="session-2",
            source_turn_id="turn-2",
            user_turn="Actually, I meant W5.",
            evidence_span="Actually, I meant W5.",
            event_at="2026-08-21T09:00:00+00:00",
        )
        self.assertEqual(result.applied_operation, "SUPERSEDE")
        self.assertEqual(self.store.get_memory("synthetic_a", old.memory_id).status, "SUPERSEDED")

    def test_030_delete_memory_control(self) -> None:
        old = self.apply()
        result = self.provider.delete_memory(
            student_id="synthetic_a",
            target_memory_id=old.memory_id,
            source_session_id="session-2",
            source_turn_id="turn-2",
            user_turn="Delete that stored goal.",
            evidence_span="Delete that stored goal.",
            event_at="2026-08-21T09:00:00+00:00",
        )
        self.assertEqual(result.applied_operation, "DELETE")

    def test_031_clear_experimental_state_is_deterministic(self) -> None:
        self.apply()
        first = self.provider.clear_experimental_learner_state("synthetic_a")
        second = self.provider.clear_experimental_learner_state("synthetic_a")
        self.assertEqual(first["memories_removed"], 1)
        self.assertEqual(second, {"memories_removed": 0, "events_removed": 0})
        self.assertEqual(self.store.list_memories("synthetic_a"), [])

    def test_032_reset_does_not_clear_another_learner(self) -> None:
        self.apply(student_id="synthetic_a")
        self.apply(student_id="synthetic_b", content="I want to improve reflection writing.", turn="turn-b")
        self.provider.clear_experimental_learner_state("synthetic_a")
        self.assertEqual(len(self.store.list_memories("synthetic_b")), 1)

    def test_033_integrity_and_fts_counts_match(self) -> None:
        self.apply()
        check = self.store.integrity_check()
        self.assertEqual(check["integrity_check"], "ok")
        self.assertEqual(check["foreign_key_issue_count"], 0)
        self.assertEqual(check["memory_row_count"], check["fts_row_count"])

    def test_034_cross_learner_update_target_fails_closed(self) -> None:
        other = self.apply(student_id="synthetic_b")
        result = self.apply(
            operation="UPDATE",
            memory_type="GOAL",
            content="I want to revise the reflection.",
            target=other.memory_id,
            event_at="2026-08-21T09:00:00+00:00",
            turn="turn-2",
        )
        self.assertEqual(result.reason_code, "TARGET_MEMORY_NOT_FOUND_OR_CROSS_LEARNER")

    def test_035_strict_candidate_rejects_extra_keys(self) -> None:
        value = candidate("ADD", "GOAL", "I want to study.").as_dict()
        value["extra"] = True
        with self.assertRaisesRegex(C4MemoryWriteError, "STRICT_CANDIDATE_KEYS_MISMATCH"):
            StructuredMemoryCandidate.from_mapping(value)

    def test_036_boolean_confidence_is_rejected(self) -> None:
        value = candidate("ADD", "GOAL", "I want to study.").as_dict()
        value["confidence"] = True
        with self.assertRaisesRegex(C4MemoryWriteError, "CONFIDENCE_MUST_BE_NUMBER"):
            StructuredMemoryCandidate.from_mapping(value)

    def test_037_update_type_mismatch_is_rejected(self) -> None:
        old = self.apply(memory_type="GOAL", content="I want to study W4.")
        result = self.apply(
            operation="UPDATE",
            memory_type="PREFERENCE",
            content="I prefer studying W4.",
            target=old.memory_id,
            event_at="2026-08-21T09:00:00+00:00",
            turn="turn-2",
        )
        self.assertEqual(result.reason_code, "UPDATE_TYPE_MISMATCH")

    def test_038_retrieval_signature_matches_contract(self) -> None:
        signature = inspect.signature(C4LearnerMemoryProvider.retrieve)
        self.assertEqual(
            list(signature.parameters),
            ["self", "student_id", "student_query", "visible_history", "top_k"],
        )
        self.assertEqual(signature.parameters["top_k"].default, 5)

    def test_039_top_k_bounds_fail_closed(self) -> None:
        with self.assertRaisesRegex(ValueError, "TOP_K_OUT_OF_RANGE"):
            self.provider.retrieve("synthetic_a", "query", [], top_k=0)

    def test_040_fts_query_metacharacters_do_not_escape_scope(self) -> None:
        self.apply()
        envelope = self.provider.retrieve("synthetic_a", '" OR student_id:*', [])
        self.assertIn(envelope["status"], {"AVAILABLE", "NO_MATCH"})
        self.assertNotIn("synthetic_a", json.dumps(envelope))

    def test_041_deterministic_memory_identity_across_fresh_runs(self) -> None:
        first = self.apply()
        other_path = Path(self.temp.name) / "second.sqlite"
        with C4MemoryStore(other_path, clock=lambda: QUERY_TIME) as second_store:
            second_provider = C4LearnerMemoryProvider(second_store, semantic_backend=self.backend, clock=lambda: QUERY_TIME)
            second = second_provider.writer.apply_candidate(
                student_id="synthetic_a",
                source_session_id="session-1",
                source_turn_id="turn-1",
                source_text="I want to improve debate participation.",
                candidate=candidate("ADD", "GOAL", "I want to improve debate participation."),
                event_at=EVENT_TIME,
            )
        self.assertEqual(first.memory_id, second.memory_id)

    def test_042_memory_event_audit_records_operations(self) -> None:
        old = self.apply()
        self.apply(
            operation="DELETE",
            memory_type=None,
            content=None,
            target=old.memory_id,
            evidence="Delete that goal.",
            source_text="Delete that goal.",
            event_at="2026-08-21T09:00:00+00:00",
            turn="turn-2",
        )
        self.assertEqual([event["operation"] for event in self.store.list_events("synthetic_a")], ["ADD", "DELETE"])

    def test_043_no_provider_or_network_imports_in_runtime_package(self) -> None:
        forbidden = {"openai", "requests", "httpx", "urllib", "socket", "streamlit", "firebase_admin"}
        runtime_root = PROJECT_ROOT / "utils/c4_memory"
        for path in runtime_root.glob("*.py"):
            tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
            imported: set[str] = set()
            for node in ast.walk(tree):
                if isinstance(node, ast.Import):
                    imported.update(alias.name.split(".")[0] for alias in node.names)
                elif isinstance(node, ast.ImportFrom) and node.module:
                    imported.add(node.module.split(".")[0])
            self.assertFalse(imported & forbidden, f"{path.name}: {sorted(imported & forbidden)}")

    def test_044_frozen_local_mpnet_identity_and_hashes_when_available(self) -> None:
        configured = os.environ.get("C4_MEMORY_MPNET_PATH")
        if not configured:
            self.skipTest("C4_MEMORY_MPNET_PATH not configured")
        backend = FrozenLocalMPNetBackend(configured)
        identity = backend.identity
        self.assertEqual(identity["revision"], MPNET_REVISION)
        self.assertEqual(len(identity["verified_file_sha256"]), 3)
        self.assertFalse(identity["network_allowed"])

    def test_045_fixture_contains_only_synthetic_learner_ids(self) -> None:
        fixture_path = PROJECT_ROOT / "evaluation/rq3_real_c4/track_m_memory/historical_replay_cases_v1.json"
        fixture = json.loads(fixture_path.read_text(encoding="utf-8"))
        self.assertFalse(fixture["contains_real_student_pii"])
        for case in fixture["cases"]:
            self.assertTrue(str(case["student_id"]).startswith("synthetic_"))
            for write in case["writes"]:
                override = write.get("student_id_override")
                if override:
                    self.assertTrue(str(override).startswith("synthetic_"))

    def test_046_schema_reset_clears_disabled_setting(self) -> None:
        self.provider.disable_memory_for_learner("synthetic_a", event_at=EVENT_TIME)
        self.assertFalse(self.store.is_memory_enabled("synthetic_a"))
        self.provider.clear_experimental_learner_state("synthetic_a")
        self.assertTrue(self.store.is_memory_enabled("synthetic_a"))

    def test_047_no_match_envelope_still_has_valid_sha(self) -> None:
        envelope = self.provider.retrieve("synthetic_a", "What does Total_chars mean?", [])
        observed = envelope.pop("envelope_sha256")
        self.assertEqual(envelope["status"], "NO_MATCH")
        self.assertEqual(observed, sha256_object(envelope))

    def test_048_student_id_is_hashed_not_exposed_in_envelope(self) -> None:
        self.apply()
        envelope = self.provider.retrieve("synthetic_a", "What goal did I want to achieve?", [])
        self.assertNotIn("synthetic_a", json.dumps(envelope))
        self.assertEqual(len(envelope["student_scope_sha256"]), 64)

    def test_049_network_guard_preserves_socket_type_and_blocks_connect(self) -> None:
        import socket

        with deny_network() as guard:
            self.assertIsInstance(socket.socket, type)
            outbound = socket.socket()
            with self.assertRaises(NetworkAccessAttempt):
                outbound.connect(("192.0.2.1", 443))
            outbound.close()
        self.assertEqual(guard.attempts, 1)

    def test_050_fts_stopwords_alone_do_not_create_a_match(self) -> None:
        self.apply(memory_type="PREFERENCE", content="I prefer studying in the library.")
        lexical_only = C4LearnerMemoryProvider(self.store, semantic_backend=None, clock=lambda: QUERY_TIME)
        envelope = lexical_only.retrieve(
            "synthetic_a",
            "When is Total_chars shown in the dashboard?",
            [],
        )
        self.assertEqual(envelope["status"], "NO_MATCH")

    def test_051_strong_type_alignment_supports_low_content_paraphrase(self) -> None:
        result = self.apply(memory_type="ACTIVE_PLAN", content="I will reply to one debate post.")
        typed_provider = C4LearnerMemoryProvider(
            self.store,
            semantic_backend=StrongTypeLowContentBackend(),
            clock=lambda: QUERY_TIME,
        )
        envelope = typed_provider.retrieve(
            "synthetic_a",
            "What study action did I commit to do next?",
            [],
        )
        self.assertEqual(envelope["status"], "AVAILABLE")
        self.assertEqual(envelope["selected_memory_items"][0]["memory_id"], result.memory_id)

    def test_052_strict_candidate_does_not_coerce_non_string_fields(self) -> None:
        value = candidate("ADD", "GOAL", "I want to study.").as_dict()
        value["operation"] = 123
        with self.assertRaisesRegex(C4MemoryWriteError, "OPERATION_MUST_BE_STRING"):
            StructuredMemoryCandidate.from_mapping(value)

    def test_053_sensitive_identifier_is_rejected_without_external_flag(self) -> None:
        result = self.apply(
            memory_type="CONSTRAINT",
            content="My passport number is unrelated to studying.",
            unrelated_sensitive=False,
        )
        self.assertEqual(result.reason_code, "UNRELATED_SENSITIVE_INFORMATION")
        self.assertEqual(self.store.list_memories("synthetic_a"), [])

    def test_054_expired_identical_fact_can_be_reasserted(self) -> None:
        first = self.apply(
            content="I want to finish the Week 3 lecture.",
            event_at="2026-08-01T09:00:00+00:00",
            valid_to="2026-08-15T09:00:00+00:00",
        )
        second = self.apply(
            content="I want to finish the Week 3 lecture.",
            event_at="2026-08-20T09:00:00+00:00",
            turn="turn-2",
        )
        self.assertTrue(first.accepted)
        self.assertTrue(second.accepted)
        self.assertNotEqual(first.memory_id, second.memory_id)

    def test_055_expired_target_cannot_be_updated(self) -> None:
        old = self.apply(
            content="I want to finish the Week 3 lecture.",
            event_at="2026-08-01T09:00:00+00:00",
            valid_to="2026-08-15T09:00:00+00:00",
        )
        update = self.apply(
            operation="UPDATE",
            content="I want to finish the Week 4 lecture.",
            target=old.memory_id,
            event_at="2026-08-20T09:00:00+00:00",
            turn="turn-2",
        )
        self.assertEqual(update.reason_code, "TARGET_MEMORY_NOT_TEMPORALLY_VALID")

    def test_056_blank_learner_identity_fails_closed(self) -> None:
        with self.assertRaisesRegex(C4MemoryStoreError, "INVALID_STUDENT_ID"):
            self.apply(student_id="")

    def test_057_serialised_visible_history_is_excluded(self) -> None:
        self.apply(content="I want to review the W5 reading.")
        history = json.dumps([{"role": "user", "content": "I want to review the W5 reading."}])
        envelope = self.provider.retrieve("synthetic_a", "What was my goal?", history)
        self.assertEqual(envelope["status"], "NO_MATCH")
        self.assertEqual(envelope["retrieval"]["visible_history_excluded_count"], 1)


if __name__ == "__main__":
    unittest.main()
