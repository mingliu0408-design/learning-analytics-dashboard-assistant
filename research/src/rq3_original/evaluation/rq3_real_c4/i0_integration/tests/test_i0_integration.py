"""Governed identity, adapter, package, and zero-execution tests for I0."""

from __future__ import annotations

from dataclasses import replace
import csv
import hashlib
import json
from pathlib import Path
import re
import tempfile
import unittest
from unittest import mock
from zipfile import ZipFile

from evaluation.rq3_real_c4.i0_integration.build_i0_artifacts import (
    ALL_MODES,
    CANONICAL,
    EXPECTED,
    HERE,
    PACKAGE_SPECS,
    PERSISTENT_CASES,
    PRIMARY_MODES,
    RAG_COHORT,
    REPLAY,
    ROOT,
    sha_file,
)
from evaluation.rq3_real_c4.i0_integration.assemble_frozen_routes import assemble
from evaluation.rq3_real_c4.mock_providers import build_mock_dependencies
from utils.c4_real_adapters import (
    C4DeterministicOutputGuard,
    C4OutputGuardViolation,
    C4PersistentLearnerMemoryAdapter,
    C4ProviderCompatibleGenerator,
    C4RealEvidenceCompilerV1,
    C4RealEvidenceSynthesisAdapter,
    C4RecommendationPlannerAdapter,
    C4SelectedR0CourseRAGAdapter,
    PrecomputedP3RouteCache,
    ProviderExecutionNotAuthorised,
    semantic_input_sha256,
    validate_planner_evidence_consistency,
)
from utils.c4_real_contracts import (
    C4Mode,
    C4RealRequest,
    CompiledEvidence,
    ExecutionContext,
    GenerationResult,
    MemoryScope,
    ModuleActivation,
    P3CapabilityRoute,
    PrimarySemanticInput,
)
from utils.c4_real_factory import build_c4_real_dependencies
from utils.c4_real_service import C4RealService


def jsonl(path: Path) -> list[dict]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line]


def request_from_route(row: dict, mode: C4Mode) -> C4RealRequest:
    value = row["semantic_input"]
    return C4RealRequest(
        request_id=f"TEST::{row['scenario_id']}::{mode.value}",
        scenario_id=row["scenario_id"],
        mode=mode,
        current_query=value["current_query"],
        current_page=value["current_page"],
        dashboard_context=value["dashboard_context"],
        visible_conversation_history=tuple(value["visible_conversation_history"]),
        student_id=f"TEST-STUDENT::{row['scenario_id']}",
        session_id=f"TEST-SESSION::{row['scenario_id']}",
        state_reset_id=f"TEST-RESET::{row['scenario_id']}::{mode.value}",
        execution_context=ExecutionContext.EVALUATION,
    )


class DeterministicSemanticBackend:
    @property
    def identity(self):
        return {"backend": "I0_TEST_DETERMINISTIC", "network_allowed": False}

    def encode(self, texts):
        return [[1.0, 0.0] for _ in texts]


class IntegratedIdentityTests(unittest.TestCase):
    def test_governed_external_source_hashes(self) -> None:
        for raw, expected in EXPECTED.items():
            self.assertEqual(sha_file(Path(raw)), expected)

    def test_integration_source_manifest_hashes_every_listed_file(self) -> None:
        manifest = json.loads((HERE / "c4_real_integration_source_manifest_v1.json").read_text())
        for item in manifest["source_files"]:
            path = Path(item["path"])
            self.assertEqual(sha_file(path), item["sha256"], item["path"])
            self.assertEqual(path.stat().st_size, item["byte_count"], item["path"])

    def test_exact_dataset_identity_and_replay_counts(self) -> None:
        dataset = jsonl(CANONICAL / "evaluation/unified_benchmark_scenarios.jsonl")
        self.assertEqual(len(dataset), 62)
        self.assertEqual([row["scenario_id"] for row in dataset], [f"U{i:03d}" for i in range(1, 63)])
        counts = {}
        for row in dataset:
            counts[row["source_dataset"]] = counts.get(row["source_dataset"], 0) + 1
        self.assertEqual(counts, {"main_benchmark": 25, "memory_diagnostic": 12, "rag_diagnostic": 10, "handwritten_unified": 15})
        replay = jsonl(REPLAY)
        self.assertEqual(len(replay), 558)
        self.assertEqual(sum(row["analysis_tier"] == "PRIMARY" for row in replay), 372)
        self.assertEqual(sum(row["analysis_tier"] == "TARGETED_SECONDARY" for row in replay), 186)

    def test_exact_nine_modes(self) -> None:
        self.assertEqual(tuple(mode.value for mode in C4Mode), ALL_MODES)
        self.assertEqual(len(PRIMARY_MODES), 6)

    def test_final_analysis_denominators_are_frozen(self) -> None:
        cohorts = json.loads((HERE / "c4_real_final_analysis_cohorts_v1.json").read_text())
        self.assertEqual(cohorts["primary_six_mode_dataset"]["scenario_count"], 62)
        self.assertEqual(cohorts["authentic_subset"]["scenario_ids"], [f"U{i:03d}" for i in range(1, 26)])
        self.assertEqual(tuple(cohorts["rag_effect_subset"]["scenario_ids"]), RAG_COHORT)
        self.assertEqual(cohorts["long_term_memory_primary_effect_subset"]["scenario_ids"], list(PERSISTENT_CASES))
        self.assertFalse(cohorts["post_response_denominator_changes_permitted"])


class RouteContractTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.routes = jsonl(HERE / "c4_real_p3_route_input_manifest_v1.jsonl")

    def test_gate_population_and_four_field_boundary(self) -> None:
        self.assertEqual(len(self.routes), 62)
        self.assertEqual({row["status"] for row in self.routes}, {"READY_FOR_P3_ROUTE_EXECUTION"})
        for row in self.routes:
            self.assertEqual(
                set(row["semantic_input"]),
                {"current_query", "current_page", "dashboard_context", "visible_conversation_history"},
            )
            primary = PrimarySemanticInput(
                row["semantic_input"]["current_query"],
                row["semantic_input"]["current_page"],
                row["semantic_input"]["dashboard_context"],
                tuple(row["semantic_input"]["visible_conversation_history"]),
            )
            self.assertEqual(semantic_input_sha256(primary), row["semantic_input_sha256"])

    def test_c0_c1_zero_route_and_one_decision_shared(self) -> None:
        route = P3CapabilityRoute(True, True, True, decision_id="ONE", provider_identity="TEST")
        provider = PrecomputedP3RouteCache({self.routes[0]["semantic_input_sha256"]: route}, evaluation_mode=True)
        dependencies, _, _, log = build_mock_dependencies(route=route)
        service = C4RealService(replace(dependencies, p3_router=provider))
        for mode in C4Mode:
            result = service.execute(request_from_route(self.routes[0], mode))
            self.assertTrue(result.success)
        self.assertEqual(provider.request_count, 7)
        self.assertEqual(provider.cache_hit_count, 7)
        self.assertEqual(provider.live_decision_count, 0)
        self.assertEqual(log.calls.count("common_generator"), 9)

    def test_evaluation_cache_miss_fails_closed(self) -> None:
        provider = PrecomputedP3RouteCache({}, evaluation_mode=True)
        row = self.routes[0]
        with self.assertRaisesRegex(KeyError, "FROZEN_EVALUATION_ROUTE_MISSING"):
            provider.route(PrimarySemanticInput(
                row["semantic_input"]["current_query"], row["semantic_input"]["current_page"],
                row["semantic_input"]["dashboard_context"], tuple(row["semantic_input"]["visible_conversation_history"])
            ))

    def test_route_content_never_enters_generation_input(self) -> None:
        source = (ROOT / "utils/c4_real_adapters.py").read_text(encoding="utf-8")
        self.assertIn("del clarification, route, activation", source)
        row = self.routes[0]
        request = request_from_route(row, C4Mode.C5_FULL_C4)
        value = C4ProviderCompatibleGenerator._generation_input(request, CompiledEvidence({"safe": True}), None)
        self.assertNotIn("route", value)
        self.assertNotIn("mode", value)


class AdapterTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.routes = {row["scenario_id"]: row for row in jsonl(HERE / "c4_real_p3_route_input_manifest_v1.jsonl")}

    def test_evidence_synthesis_is_cached_and_explicitly_output_level(self) -> None:
        adapter = C4RealEvidenceSynthesisAdapter(dashboard_data=None)
        request = request_from_route(self.routes["U001"], C4Mode.C1_EVIDENCE)
        first = adapter.synthesise(request=request, primary_input=request.primary_input)
        second = adapter.synthesise(request=request, primary_input=request.primary_input)
        self.assertIs(first, second)
        self.assertEqual(first.status, "FROZEN_OUTPUT_LEVEL_PACK")
        self.assertEqual(adapter.actual_synthesiser_calls, 0)
        self.assertEqual(adapter.frozen_pack_reads, 1)
        empty_request = request_from_route(self.routes["U040"], C4Mode.C1_EVIDENCE)
        empty = adapter.synthesise(request=empty_request, primary_input=empty_request.primary_input)
        self.assertEqual(empty.status, "FROZEN_TYPED_EMPTY_OUTPUT_LEVEL_PACK")
        self.assertEqual(empty.items, ())

    def test_all_62_evidence_packs_compile_consistently_within_budget(self) -> None:
        adapter = C4RealEvidenceSynthesisAdapter(dashboard_data=None)
        compiler = C4RealEvidenceCompilerV1()
        dependencies, _, _, _ = build_mock_dependencies()
        for row in self.routes.values():
            request = request_from_route(row, C4Mode.C1_EVIDENCE)
            evidence = adapter.synthesise(request=request, primary_input=request.primary_input)
            kwargs = dict(
                request=request,
                clarification=dependencies.clarification_gate.evaluate(request.primary_input),
                route=None,
                activation=ModuleActivation(True, False, False, False),
                dashboard_evidence=evidence,
                course_rag=None,
                learner_memory=None,
            )
            first = compiler.compile(**kwargs)
            second = compiler.compile(**kwargs)
            self.assertEqual(first.compiled_evidence_sha256, second.compiled_evidence_sha256)
            self.assertLessEqual(first.deterministic_token_count, first.deterministic_token_budget)
            self.assertFalse(any(value.startswith("TOKEN_BUDGET_EXCLUDED") for value in first.limitations))

    def test_selected_r0_evidence_strength_and_no_result(self) -> None:
        adapter = C4SelectedR0CourseRAGAdapter()
        supported = adapter.retrieve(request=request_from_route(self.routes["U040"], C4Mode.C2_EVIDENCE_RAG), evidence=None)
        self.assertEqual(adapter.provider.implementation_id, "C4_RAG_R0_LEXICAL")
        self.assertTrue(supported.sources)
        self.assertTrue(all(source.evidence_strength for source in supported.sources))
        self.assertTrue(all(source.source_id and source.document_title for source in supported.sources))
        no_result = adapter.retrieve(request=request_from_route(self.routes["U046"], C4Mode.C2_EVIDENCE_RAG), evidence=None)
        self.assertEqual(no_result.result_status, "NO_RESULT")
        self.assertEqual(no_result.sources, ())

    def test_r1_runtime_selection_is_rejected(self) -> None:
        class WrongProvider:
            implementation_id = "C4_RAG_R1_LOCAL_MPNET"
        adapter = C4SelectedR0CourseRAGAdapter(provider=WrongProvider())
        with self.assertRaisesRegex(ValueError, "Only C4_RAG_R0_LEXICAL"):
            _ = adapter.provider

    def test_memory_precondition_persists_after_reopen_and_isolates_modes(self) -> None:
        records = {row["scenario_id"]: row for row in jsonl(HERE / "c4_real_memory_preconditioning_manifest_v1.jsonl")}
        with tempfile.TemporaryDirectory() as temporary:
            adapter = C4PersistentLearnerMemoryAdapter(temporary, evaluation_mode=True, semantic_backend=DeterministicSemanticBackend())
            request_a = request_from_route(self.routes["U033"], C4Mode.C3_EVIDENCE_MEMORY)
            request_b = request_from_route(self.routes["U033"], C4Mode.C5_FULL_C4)
            proof_a = adapter.precondition(request_a.memory_scope, records["U033"])
            proof_b = adapter.precondition(request_b.memory_scope, records["U033"])
            self.assertTrue(proof_a["store_reopened"])
            self.assertTrue(proof_a["active_memory_ids_after_reopen"])
            self.assertNotEqual(proof_a["namespace_sha256"], proof_b["namespace_sha256"])
            self.assertEqual(adapter.store_open_count, adapter.store_close_count)
            self.assertEqual(len(adapter.view(request_a.memory_scope)), 3)
            self.assertEqual(len(adapter.view(request_b.memory_scope)), 3)

    def test_exact_persistent_cases_and_blank_extensions_excluded(self) -> None:
        records = jsonl(HERE / "c4_real_memory_preconditioning_manifest_v1.jsonl")
        self.assertEqual([row["scenario_id"] for row in records], list(PERSISTENT_CASES))
        self.assertEqual([row["source_scenario_id"] for row in records], list(PERSISTENT_CASES.values()))
        with (HERE.parent / "track_d_dataset/memory_extension_writer_packet_v1.csv").open() as handle:
            packet = list(csv.DictReader(handle))
        self.assertEqual(len(packet), 6)
        self.assertTrue(all(row["inclusion_status"] == "NOT_IN_PRIMARY_DATASET_OR_REPLAY_MANIFEST" for row in packet))
        self.assertTrue(all(not row["student_writer_setup_text"].strip() for row in packet))
        self.assertTrue(all(not row["student_writer_update_text"].strip() for row in packet))
        self.assertTrue(all(not row["student_writer_target_text"].strip() for row in packet))

    def test_no_assistant_advice_is_a_learner_fact(self) -> None:
        records = jsonl(HERE / "c4_real_memory_preconditioning_manifest_v1.jsonl")
        for record in records:
            self.assertFalse(record["assistant_recommendation_as_learner_fact"])
            for write in record["writes"]:
                self.assertNotEqual(write["source_role"], "ASSISTANT")
                if write["source_role"] == "SYSTEM":
                    self.assertEqual(write["claim_basis"], "VERIFIED_SYSTEM_EVENT")
                    self.assertEqual(write["candidate"]["memory_type"], "ACTIVE_PLAN")

    def test_all_memory_preconditions_pass_across_all_modes(self) -> None:
        report = json.loads((HERE / "c4_real_memory_preconditioning_validation_v1.json").read_text())
        self.assertEqual(report["status"], "PASS_ALL_NINE_CASES_ALL_NINE_MODES")
        self.assertEqual(report["persistent_case_count"], 9)
        self.assertEqual(report["mode_count"], 9)
        self.assertEqual(report["isolated_scope_count"], 81)
        self.assertEqual(report["unique_namespace_count"], 81)
        self.assertEqual(report["write_attempt_count"], 180)
        self.assertEqual(report["accepted_write_count"], 180)
        self.assertEqual(report["rejected_write_count"], 0)
        self.assertEqual(report["provider_calls"], 0)

    def test_compiler_dedupes_strips_internal_values_and_stabilises_hash(self) -> None:
        compiler = C4RealEvidenceCompilerV1()
        request = request_from_route(self.routes["U001"], C4Mode.C1_EVIDENCE)
        evidence_adapter = C4RealEvidenceSynthesisAdapter(dashboard_data=None)
        evidence = evidence_adapter.synthesise(request=request, primary_input=request.primary_input)
        kwargs = dict(request=request, clarification=build_mock_dependencies()[0].clarification_gate.evaluate(request.primary_input), route=None,
                      activation=__import__('utils.c4_real_contracts', fromlist=['ModuleActivation']).ModuleActivation(True, False, False, False),
                      dashboard_evidence=evidence, course_rag=None, learner_memory=None)
        first = compiler.compile(**kwargs)
        second = compiler.compile(**kwargs)
        self.assertEqual(first.compiled_evidence_sha256, second.compiled_evidence_sha256)
        self.assertEqual(first.content, second.content)
        serialised = json.dumps(first.content)
        self.assertNotIn("embedding", serialised.lower())
        self.assertNotIn("database_path", serialised.lower())

    def test_planner_consistency_validator_rejects_created_provenance(self) -> None:
        compiled = CompiledEvidence({"selected_evidence": [{"evidence_id": "known", "source_kind": "DASHBOARD", "content": {}}]})
        errors = validate_planner_evidence_consistency({"source_provenance": [{"evidence_id": "invented", "source_kind": "DASHBOARD"}], "learner_constraints": []}, compiled)
        self.assertIn("PLANNER_PROVENANCE_OUTSIDE_COMPILED_EVIDENCE", errors)

    def test_output_guard_flags_without_rewriting(self) -> None:
        guard = C4DeterministicOutputGuard()
        request = request_from_route(self.routes["U046"], C4Mode.C2_EVIDENCE_RAG)
        compiled = CompiledEvidence(
            {
                "selected_evidence": [],
                "typed_absence": [
                    {"source_kind": "COURSE_RAG", "status": "NO_RESULT"},
                    {"source_kind": "LEARNER_MEMORY", "status": "NO_MATCH"},
                ],
            }
        )
        activation = ModuleActivation(True, True, False, False)
        with self.assertRaises(C4OutputGuardViolation):
            guard.apply(
                request=request,
                generated=GenerationResult("P3 router selected this mode.", "test", "strict"),
                activation=activation,
                compiled_evidence=compiled,
                planner_result=None,
            )
        with self.assertRaises(C4OutputGuardViolation):
            guard.apply(
                request=request,
                generated=GenerationResult("1. Do one thing.\n2. Then do another.", "test", "strict"),
                activation=activation,
                compiled_evidence=compiled,
                planner_result=None,
            )
        safe_text = "I do not have enough course evidence to answer that specific point."
        safe = guard.apply(
            request=request,
            generated=GenerationResult(safe_text, "test", "strict"),
            activation=activation,
            compiled_evidence=compiled,
            planner_result=None,
        )
        self.assertEqual(safe.text, safe_text)

    def test_factory_import_and_mock_binding_without_streamlit_launch(self) -> None:
        route = P3CapabilityRoute(True, True, True)
        provider = PrecomputedP3RouteCache({self.routes["U001"]["semantic_input_sha256"]: route}, evaluation_mode=True)
        dependencies, _, _, _ = build_mock_dependencies(route=route)
        with tempfile.TemporaryDirectory() as temporary:
            real = build_c4_real_dependencies(
                route_provider=provider,
                course_asset_root=CANONICAL,
                memory_database_path=Path(temporary) / "memory",
                generator=dependencies.generator,
                output_guard=dependencies.output_guard,
                semantic_memory_backend=DeterministicSemanticBackend(),
                evaluation_mode=True,
            )
        self.assertEqual(real.course_rag.identity, "C4_REAL_COURSE_RAG_ADAPTER_V1::C4_RAG_R0_LEXICAL")
        self.assertEqual(real.learner_memory.identity, "C4_REAL_PERSISTENT_MEMORY_ADAPTER_V1::C4_LEARNER_MEMORY_V1")


class FrozenProviderContractTests(unittest.TestCase):
    def test_generation_contract_and_disabled_transport(self) -> None:
        config = json.loads((HERE / "c4_real_generation_configuration_frozen_v1.json").read_text())
        self.assertEqual(config["model"], "gpt-4o-mini-2024-07-18")
        self.assertEqual(config["endpoint"], "OpenAI Chat Completions")
        self.assertEqual(config["temperature"], 0)
        self.assertEqual(config["max_output_tokens"], 512)
        self.assertEqual(config["automatic_sdk_retries"], 0)
        self.assertFalse(config["streaming"])
        self.assertEqual(config["tools"], "NONE")
        generator = C4ProviderCompatibleGenerator(transport=lambda payload: '{"answer_text":"x"}')
        with self.assertRaises(ProviderExecutionNotAuthorised):
            generator.generate(request=mock.Mock(), clarification=mock.Mock(), route=None,
                               activation=mock.Mock(), compiled_evidence=CompiledEvidence({}), planner_result=None)
        self.assertEqual(generator.transport_call_count, 0)

    def test_generation_prompt_excludes_experimental_and_gold_metadata(self) -> None:
        prompt = (HERE / "c4_real_generation_prompt_frozen_v1.txt").read_text().casefold()
        for term in ("mode id", "ablation", "expected capability", "human gold", "scenario group", "reference answer", "expected winner"):
            self.assertNotIn(term, prompt)
        schema = json.loads((HERE / "c4_real_generation_schema_v1.json").read_text())
        self.assertEqual(set(schema["properties"]), {"answer_text"})
        self.assertFalse(schema["additionalProperties"])

    def test_eight_criterion_judge_and_statistics_preserved(self) -> None:
        config = json.loads((HERE / "c4_real_judge_configuration_frozen_v1.json").read_text())
        self.assertEqual(config["model"], "gpt-4.1-2025-04-14")
        self.assertEqual(len(config["primary_criteria"]), 8)
        self.assertEqual(config["primary_outcome"], "OVERALL_APPLICABLE_MEAN")
        self.assertEqual(config["bootstrap_replicates"], 10000)
        self.assertEqual(config["multiplicity"], "HOLM_STEP_DOWN")
        schema = json.loads((HERE / "c4_real_judge_schema_v1.json").read_text())
        self.assertIn("evidence_faithfulness", schema["properties"])
        self.assertIn("unsupported_claim_count", schema["properties"])


class RoutePackageTests(unittest.TestCase):
    def test_future_local_merger_uses_declared_bits_and_no_gold(self) -> None:
        routes = jsonl(HERE / "c4_real_p3_route_input_manifest_v1.jsonl")
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            paths = {name: root / f"{name}.jsonl" for name in ("rag", "memory", "b4")}
            fields = {"rag": "rag_required", "memory": "memory_required", "b4": "planning_required"}
            for name, path in paths.items():
                with path.open("w", encoding="utf-8") as handle:
                    for row in routes:
                        event = {
                            "event": "TERMINAL_SUCCESS",
                            "scenario_id": row["scenario_id"],
                            "semantic_input_sha256": row["semantic_input_sha256"],
                            "output": {fields[name]: True},
                        }
                        handle.write(json.dumps(event, sort_keys=True) + "\n")
            output = root / "routes.json"
            summary = assemble(rag_terminal=paths["rag"], memory_terminal=paths["memory"], b4_terminal=paths["b4"], output=output)
            payload = json.loads(output.read_text())
            self.assertEqual(summary["scenario_count"], 62)
            self.assertEqual(summary["unique_semantic_input_count"], 60)
            self.assertFalse(payload["gold_used"])
            self.assertEqual(payload["provider_calls_by_merger"], 0)

    def test_three_package_allowlists_hashes_and_request_safety(self) -> None:
        plan = json.loads((HERE / "c4_real_route_execution_plan_v1.json").read_text())
        self.assertEqual(plan["logical_call_population"], 62)
        self.assertEqual(plan["per_package_physical_attempt_ceiling"], 124)
        self.assertEqual(len(plan["packages"]), 3)
        for package in plan["packages"]:
            path = Path(package["path"])
            self.assertEqual(sha_file(path), package["sha256"])
            with ZipFile(path) as archive:
                names = sorted(archive.namelist())
                manifest = json.loads(archive.read("PACKAGE_MANIFEST.json"))
                self.assertEqual(names, manifest["strict_allowlist"])
                self.assertFalse(manifest["contains_gold"])
                self.assertFalse(manifest["contains_evaluation_expected_capabilities"])
                self.assertFalse(manifest["contains_reference_evidence"])
                self.assertFalse(manifest["contains_mode_labels"])
                for name, expected in manifest["member_sha256_excluding_self"].items():
                    self.assertEqual(hashlib.sha256(archive.read(name)).hexdigest(), expected)
                requests = [json.loads(line) for line in archive.read("requests.jsonl").decode().splitlines()]
                self.assertEqual(len(requests), 62)
                for row in requests:
                    self.assertEqual(set(row), {"schema_version", "scenario_id", "semantic_input_sha256", "status", "semantic_input"})
                    self.assertEqual(set(row["semantic_input"]), {"current_query", "current_page", "dashboard_context", "visible_conversation_history"})

    def test_packages_contain_zero_secrets_and_empty_journals(self) -> None:
        plan = json.loads((HERE / "c4_real_route_execution_plan_v1.json").read_text())
        secret = re.compile(rb"(?:sk-[A-Za-z0-9_-]{16,}|OPENAI_API_KEY\s*[=:]\s*['\"]?[A-Za-z0-9_-]{16,})")
        for package in plan["packages"]:
            with ZipFile(package["path"]) as archive:
                self.assertEqual(archive.read("ATTEMPT_JOURNAL.jsonl"), b"")
                self.assertEqual(archive.read("TERMINAL_JOURNAL.jsonl"), b"")
                self.assertIsNone(secret.search(b"\n".join(archive.read(name) for name in archive.namelist())))

    def test_zero_execution_reports(self) -> None:
        build = json.loads((HERE / "c4_real_i0_build_report_v1.json").read_text())
        dry = json.loads((HERE / "c4_real_system_dry_run_v1.json").read_text())
        source = json.loads((HERE / "c4_real_integration_source_manifest_v1.json").read_text())
        self.assertEqual(build["provider_calls"], 0)
        self.assertEqual(dry["provider_calls"], 0)
        self.assertEqual(dry["p3_provider_calls"], 0)
        self.assertEqual(dry["generator"]["calls_producing_text"], 0)
        self.assertEqual(dry["judge_calls"], 0)
        self.assertEqual(dry["streamlit_launches"], 0)
        self.assertEqual(dry["network_attempts"], 0)
        self.assertEqual(source["actual_execution_counters"], {"provider_calls": 0, "p3_calls": 0, "generation_calls": 0, "judge_calls": 0, "streamlit_launches": 0})


if __name__ == "__main__":
    unittest.main(verbosity=2)
