"""Track R regression, safety, determinism, and frozen-artifact tests."""

from __future__ import annotations

import ast
import csv
import hashlib
import inspect
import json
from pathlib import Path
import socket
import subprocess
import unittest
from unittest import mock
import urllib.request

import numpy as np

from utils.c4_rag.corpus import (
    EXPECTED_SOURCE_HASHES,
    legacy_chunk_corpus_hash,
    load_legacy_chunks,
    sha256_file,
)
from utils.c4_rag.models import EvidenceStrength, SUBSTANTIVE_STRENGTHS
from utils.c4_rag.provider import C4CourseRAGProvider
from utils.c4_rag.retrievers import (
    C4RAGHybrid,
    C4RAGLegacyLexical,
    R0_ID,
    R1_ID,
)


ROOT = Path(__file__).resolve().parents[3]
OUTPUT = Path(__file__).resolve().parent


def _json(name: str) -> dict:
    return json.loads((OUTPUT / name).read_text(encoding="utf-8"))


class _DeterministicFakeEmbedder:
    identity = {
        "backend": "TEST_ONLY_DETERMINISTIC_FAKE",
        "dimension": 4,
        "external_embedding_api_calls": 0,
    }

    def encode(self, texts):
        rows = []
        for text in texts:
            digest = hashlib.sha256(str(text).encode("utf-8")).digest()
            value = np.array([digest[index] + 1 for index in range(4)], dtype="float32")
            rows.append(value / np.linalg.norm(value))
        return np.stack(rows) if rows else np.zeros((0, 4), dtype="float32")


class TrackRRAGTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.chunks = load_legacy_chunks()
        cls.registry = _json("course_source_registry_v1.json")
        cls.r0_identity = _json("c4_rag_r0_identity_v1.json")
        cls.r1_identity = _json("c4_rag_r1_identity_v1.json")
        cls.comparison = _json("retrieval_comparison_v1.json")
        cls.selected = _json("selected_c4_rag_frozen_v1.json")

    def test_01_all_registered_source_hashes(self) -> None:
        self.assertTrue(self.registry["authentic_text_bearing_course_corpus_available"])
        for record in self.registry["records"]:
            path = Path(record["exact_path"])
            self.assertTrue(path.is_file(), path)
            self.assertEqual(sha256_file(path), record["sha256"], path)
            self.assertEqual(record["parseability"], "PARSEABLE", path)

    def test_02_canonical_source_hash_binding(self) -> None:
        self.assertEqual(self.registry["expected_frozen_source_hashes"], EXPECTED_SOURCE_HASHES)
        self.assertEqual(self.registry["summary"]["unverified_candidate_count"], 0)

    def test_03_deterministic_unique_chunk_ids(self) -> None:
        ids = [chunk.chunk_id for chunk in self.chunks]
        self.assertEqual(len(ids), 624)
        self.assertEqual(len(ids), len(set(ids)))
        self.assertEqual(legacy_chunk_corpus_hash(self.chunks), self.r0_identity["chunk_corpus_hash"])
        self.assertEqual(self.r0_identity["chunk_corpus_hash"], self.r1_identity["chunk_corpus_hash"])

    def test_04_metadata_and_provenance_preserved(self) -> None:
        result = C4RAGLegacyLexical().retrieve(
            "What is W4's pre-recorded lecture about?",
            "Lecture",
            [],
            top_k=5,
            query_type="course_content_question",
        )
        self.assertTrue(result.selected_chunks)
        for item in result.selected_chunks:
            self.assertTrue(item.chunk_id)
            self.assertTrue(item.document_id)
            self.assertTrue(item.document_title)
            self.assertRegex(item.source_sha256, r"^[0-9a-f]{64}$")
            self.assertIsNotNone(item.section)

    def test_05_r0_legacy_file_is_immutable(self) -> None:
        path = ROOT / "utils/course_material_retriever.py"
        before = sha256_file(path)
        C4RAGLegacyLexical().retrieve(
            "What does Part A of the assessment ask me to do?",
            "Reflection",
            [],
            query_type="course_content_question",
        )
        self.assertEqual(sha256_file(path), before)
        self.assertEqual(before, self.r0_identity["legacy_code_hashes"]["utils/course_material_retriever.py"])
        self.assertFalse(self.r0_identity["behaviour"]["legacy_ranking_modified"])

    def test_06_lexical_dense_rrf_is_deterministic(self) -> None:
        retriever = C4RAGHybrid(
            chunks=self.chunks[:80], embedder=_DeterministicFakeEmbedder(), rrf_constant=60
        )
        first = retriever.retrieve(
            "What does Part A ask for in the reflection?", "Reflection", [], top_k=5
        )
        second = retriever.retrieve(
            "What does Part A ask for in the reflection?", "Reflection", [], top_k=5
        )
        self.assertEqual(first.chunk_ids, second.chunk_ids)
        self.assertEqual(
            [item.to_dict(include_text=False) for item in first.selected_chunks],
            [item.to_dict(include_text=False) for item in second.selected_chunks],
        )
        for item in first.selected_chunks:
            self.assertIsNotNone(item.lexical_score)
            self.assertIsNotNone(item.dense_score)
            self.assertIsNotNone(item.fusion_rank)

    def test_07_evidence_strength_constraints(self) -> None:
        for name in ("retrieval_results_r0_v1.csv", "retrieval_results_r1_v1.csv"):
            with (OUTPUT / name).open(encoding="utf-8", newline="") as handle:
                rows = list(csv.DictReader(handle))
            for row in rows:
                strengths = [EvidenceStrength(value) for value in json.loads(row["selected_evidence_strengths"])]
                for strength in strengths:
                    if strength not in SUBSTANTIVE_STRENGTHS:
                        self.assertIn(
                            strength,
                            {
                                EvidenceStrength.TITLE_AND_METADATA_ONLY,
                                EvidenceStrength.LINK_ONLY,
                                EvidenceStrength.WEAK_MATCH,
                            },
                        )

    def test_08_no_result_is_valid(self) -> None:
        result = C4RAGLegacyLexical().retrieve(
            "What does the course material say about laboratory coat sizes?",
            "Overview",
            [],
            query_type="course_content_question",
        )
        self.assertEqual(result.result_status.value, "NO_RESULT")
        self.assertEqual(result.chunk_ids, ())
        self.assertEqual(result.evidence_strength_classes, ("NO_RESULT",))

    def test_09_no_unrelated_dashboard_fallback(self) -> None:
        result = C4CourseRAGProvider(R0_ID).retrieve(
            "What does Part A of the assessment ask me to do?", "Reflection", [], top_k=5
        )
        self.assertTrue(result.selected_chunks)
        self.assertFalse(any("dashboard" in item.source_path.casefold() for item in result.selected_chunks))
        allowed = set(EXPECTED_SOURCE_HASHES.values())
        self.assertTrue(all(item.source_sha256 in allowed for item in result.selected_chunks))

    def test_10_provider_makes_no_network_or_generation_calls(self) -> None:
        provider = C4CourseRAGProvider(R0_ID)
        with mock.patch.object(socket, "create_connection", side_effect=AssertionError("network")), mock.patch.object(
            urllib.request, "urlopen", side_effect=AssertionError("network")
        ):
            result = provider.retrieve(
                "Which reference explains the analysis of individual reflection?",
                "Reflection",
                [],
            )
        self.assertTrue(result.selected_chunks)
        scoped_paths = [
            *sorted((ROOT / "utils/c4_rag").glob("*.py")),
            *sorted(OUTPUT.glob("*.py")),
        ]
        for path in scoped_paths:
            tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
            imported = []
            for node in ast.walk(tree):
                if isinstance(node, ast.Import):
                    imported.extend(alias.name.split(".")[0] for alias in node.names)
                elif isinstance(node, ast.ImportFrom) and node.module:
                    imported.append(node.module.split(".")[0])
            self.assertNotIn("openai", imported, path)

    def test_11_provider_interface_signature(self) -> None:
        parameters = inspect.signature(C4CourseRAGProvider.retrieve).parameters
        self.assertEqual(
            list(parameters),
            ["self", "student_query", "current_page", "visible_history", "student_id", "top_k"],
        )
        self.assertEqual(parameters["top_k"].default, 5)

    def test_12_real_r1_used_frozen_local_mpnet(self) -> None:
        dense = self.r1_identity["architecture"]["dense"]
        self.assertEqual(dense["repo_id"], "sentence-transformers/all-mpnet-base-v2")
        self.assertTrue(dense["local_files_only"])
        self.assertEqual(dense["external_embedding_api_calls"], 0)
        self.assertFalse(self.r1_identity["architecture"]["cross_encoder"])
        self.assertFalse(self.r1_identity["architecture"]["fine_tuning"])
        self.assertEqual(len(self.r1_identity["model_file_hashes"]), 4)

    def test_13_all_preexisting_scenario_groups_are_covered(self) -> None:
        provenance = self.comparison["evaluation_provenance"]
        self.assertEqual(provenance["raw_rag_scenarios_total"], 10)
        self.assertEqual(provenance["raw_rag_scenarios_covered"], 10)
        self.assertEqual(provenance["original_scenarios_total"], 25)
        self.assertEqual(provenance["original_course_evidence_applicable_ids"], ["S023", "S024"])
        self.assertEqual(provenance["unified_union_case_count"], 15)

    def test_14_predeclared_selection_freeze(self) -> None:
        self.assertEqual(self.selected["selected_implementation_id"], R0_ID)
        self.assertEqual(self.comparison["selected_implementation_id"], R0_ID)
        self.assertEqual(
            self.comparison["selection_trace"][0]["criterion"], "evidence_recall_at_5"
        )
        self.assertEqual(self.comparison["selection_trace"][0]["outcome"], f"SELECT_{R0_ID}")
        self.assertEqual(self.selected["write_count"], 1)
        self.assertFalse(self.selected["overwrite_permitted"])

    def test_15_zero_call_and_stop_boundary(self) -> None:
        for key in ("response_generation_calls", "provider_network_calls", "judge_calls"):
            self.assertEqual(self.selected[key], 0)
        self.assertFalse(self.selected["c4_integration_executed"])
        self.assertFalse(self.selected["rq3_outcome_scoring"])

    def test_16_changes_are_confined_to_authorised_paths(self) -> None:
        output = subprocess.run(
            ["git", "status", "--porcelain=v1", "--untracked-files=all"],
            cwd=ROOT,
            check=True,
            text=True,
            capture_output=True,
        ).stdout.splitlines()
        for line in output:
            path = line[3:]
            self.assertTrue(
                path.startswith("utils/c4_rag/")
                or path.startswith("evaluation/rq3_real_c4/track_r_rag/"),
                line,
            )


if __name__ == "__main__":
    unittest.main()
