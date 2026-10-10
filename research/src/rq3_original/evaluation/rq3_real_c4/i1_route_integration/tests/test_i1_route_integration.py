"""Artifact-level tests for the governed RQ3-REAL-C4 I1 integration."""

from __future__ import annotations

from collections import Counter, defaultdict
import csv
import hashlib
import json
import os
from pathlib import Path
import stat
import subprocess
import tempfile
import unittest
import zipfile

from evaluation.rq3_real_c4.i1_route_integration.build_i1_artifacts import (
    EXPECTED_ACTIVATION_COUNTS,
    EXPECTED_SIGNATURES,
    PROVIDER_PROHIBITED_KEYS,
    _provider_leakage_errors,
)
from evaluation.rq3_real_c4.i1_route_integration.generation_package_validator_v1 import (
    ALLOWED_FILES,
    validate as validate_generation_package,
)
from evaluation.rq3_real_c4.i1_route_integration.i1_common import (
    BRANCH,
    COMMIT_MAPPING,
    EXPECTED_HASHES,
    HERE,
    ROOT,
    SOURCE_PATHS,
    STARTING_HEAD,
    canonical_bytes,
    load_jsonl,
    sha256_file,
)
from evaluation.rq3_real_c4.i1_route_integration.judge_transport import (
    normalise_judge_transport_v2,
)
from evaluation.rq3_v2.rq3_0b4_evaluation_protocol.rq3_judge_response_parser import (
    parse_judge_response,
)


DOWNLOADS = Path("/Users/liuming/Downloads")
PACKAGE_NAMES = {
    shard: f"C4_REAL_GENERATION_SHARD_{shard}_EXECUTION_PACKAGE_R1_2026-09-01.zip"
    for shard in "ABC"
}
RESTRICTED = HERE / "restricted_internal"


def read_json(name: str) -> dict:
    return json.loads((HERE / name).read_text(encoding="utf-8"))


def read_csv(path: Path) -> list[dict[str, str]]:
    with path.open(encoding="utf-8", newline="") as handle:
        return list(csv.DictReader(handle))


def git(*args: str, check: bool = True) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["git", *args],
        cwd=ROOT,
        check=check,
        capture_output=True,
        text=True,
    )


class SourceAndRouteTests(unittest.TestCase):
    def test_branch_start_and_four_integrations_are_in_exact_order(self) -> None:
        self.assertEqual(git("branch", "--show-current").stdout.strip(), BRANCH)
        history = git("rev-list", "--reverse", f"{STARTING_HEAD}..HEAD").stdout.splitlines()
        self.assertEqual(history[:4], [cherry for _, cherry in COMMIT_MAPPING])
        self.assertIn(len(history), {4, 5})
        for original, cherry in COMMIT_MAPPING:
            self.assertEqual(git("rev-parse", original).stdout.strip(), original)
            self.assertEqual(git("rev-parse", cherry).stdout.strip(), cherry)
        if len(history) == 5:
            subject = git("show", "-s", "--format=%s", history[4]).stdout.strip()
            self.assertEqual(
                subject,
                "RQ3-REAL-I1: integrate P3 routes and freeze C4 generation requests",
            )

    def test_frozen_source_hashes_and_terminal_populations(self) -> None:
        expected_yes = {"rag_terminal": 21, "memory_terminal": 19, "planning_terminal": 15}
        output_fields = {
            "rag_terminal": "rag_required",
            "memory_terminal": "memory_required",
            "planning_terminal": "planning_required",
        }
        for name, path in SOURCE_PATHS.items():
            self.assertEqual(sha256_file(path), EXPECTED_HASHES[name])
        for name, field in output_fields.items():
            rows = load_jsonl(SOURCE_PATHS[name])
            self.assertEqual(len(rows), 62)
            self.assertEqual(sum(bool(row["output"][field]) for row in rows), expected_yes[name])
            self.assertTrue(all(row["terminal_status"] == "VALID_OUTPUT" for row in rows))
            self.assertTrue(
                all(row["returned_model"] == "gpt-4o-mini-2024-07-18" for row in rows)
            )
            self.assertTrue(all(row["physical_attempts_for_logical_request"] == 1 for row in rows))

    def test_historical_rag_v1_is_preserved_and_v2_is_sole_scientific_source(self) -> None:
        historical = HERE.parent / "r1_rag_route_execution/execution_output_v1/route_terminal_results_v1.jsonl"
        self.assertTrue(historical.is_file())
        self.assertEqual(SOURCE_PATHS["rag_terminal"].parent.name, "execution_output_v2")
        manifest = read_json("c4_real_p3_route_source_manifest_v1.json")
        self.assertEqual(
            manifest["source_terminal_validation"]["rag_terminal"]["sha256"],
            EXPECTED_HASHES["rag_terminal"],
        )

    def test_exact_p3_composition_signatures_and_duplicate_consistency(self) -> None:
        rows = load_jsonl(HERE / "c4_real_p3_routes_frozen_v1.jsonl")
        manifest = read_json("c4_real_p3_route_source_manifest_v1.json")
        self.assertEqual(len(rows), 62)
        self.assertEqual(manifest["unique_semantic_input_count"], 60)
        self.assertEqual(manifest["signature_distribution"], EXPECTED_SIGNATURES)
        self.assertEqual(
            manifest["duplicate_semantic_input_groups"], [["U022", "U026", "U031"]]
        )
        duplicates = [row for row in rows if row["scenario_id"] in {"U022", "U026", "U031"}]
        self.assertEqual(
            {
                (row["rag_required"], row["memory_required"], row["planning_required"])
                for row in duplicates
            },
            {(False, False, True)},
        )
        self.assertEqual(len({row["semantic_input_sha256"] for row in duplicates}), 1)

    def test_exact_62_case_joins_and_no_b4_rag_memory_bits_enter_p3(self) -> None:
        route_ids = [row["scenario_id"] for row in load_jsonl(HERE / "c4_real_p3_routes_frozen_v1.jsonl")]
        input_rows = load_jsonl(SOURCE_PATHS["p3_route_input_manifest"])
        self.assertEqual(route_ids, [row["scenario_id"] for row in input_rows])
        expected_hash = {row["scenario_id"]: row["semantic_input_sha256"] for row in input_rows}
        for source_name in ("rag_terminal", "memory_terminal", "planning_terminal"):
            rows = load_jsonl(SOURCE_PATHS[source_name])
            self.assertEqual([row["scenario_id"] for row in rows], route_ids)
            self.assertTrue(
                all(row["semantic_input_sha256"] == expected_hash[row["scenario_id"]] for row in rows)
            )
        audit = read_json("c4_real_b4_unused_route_bits_source_audit_v1.json")
        self.assertFalse(audit["b4_rag_memory_bits_entered_p3"])
        self.assertTrue(all(not row["b4_rag_memory_entered_p3"] for row in audit["rows"]))


class MechanismReplayTests(unittest.TestCase):
    def test_exact_replay_and_module_activation_counts(self) -> None:
        summary = read_json("c4_real_mechanism_replay_summary_v1.json")
        self.assertEqual(summary["condition_count"], 558)
        self.assertEqual(summary["analysis_tier_counts"], {"PRIMARY": 372, "TARGETED_SECONDARY": 186})
        self.assertEqual(summary["scenario_count"], 62)
        self.assertEqual(summary["mode_count"], 9)
        self.assertEqual(summary["observed_module_counts"], EXPECTED_ACTIVATION_COUNTS)
        self.assertEqual(summary["independently_expected_module_counts"], EXPECTED_ACTIVATION_COUNTS)
        self.assertEqual(summary["c0_c1_zero_route_lookup_count"], 124)

    def test_c0_c1_never_look_up_p3_and_every_condition_is_unsent(self) -> None:
        rows = load_jsonl(HERE / "c4_real_condition_mechanism_records_frozen_v1.jsonl")
        self.assertEqual(len(rows), 558)
        for row in rows:
            self.assertFalse(row["generation_sent"])
            self.assertEqual(row["provider_call_count"], 0)
            self.assertEqual(row["generator_transport_call_count"], 0)
            self.assertEqual(row["judge_call_count"], 0)
            self.assertEqual(row["target_memory_write_count"], 0)
            if row["mode"] in {"C0_ORIGINAL", "C1_EVIDENCE"}:
                self.assertIsNone(row["frozen_route_identity"])
                self.assertNotIn("frozen_scenario_route_provider", row["modules_actually_called"])

    def test_memory_preconditioning_is_isolated_reopened_and_write_free_at_target(self) -> None:
        summary = read_json("c4_real_memory_preconditioning_summary_v1.json")
        self.assertEqual(summary["isolated_namespace_count"], 81)
        self.assertEqual(summary["unique_namespace_count"], 81)
        self.assertEqual(summary["accepted_setup_write_count"], 180)
        self.assertTrue(summary["all_stores_reopened"])
        self.assertEqual(summary["u031_setup_write_count"], 0)
        self.assertEqual(summary["u036_diagnostic_status"], "NO_MATCH")
        self.assertEqual(summary["target_session_write_proposals"], 0)
        self.assertEqual(summary["target_session_writes"], 0)
        receipts = load_jsonl(HERE / "c4_real_memory_preconditioning_receipts_v1.jsonl")
        self.assertEqual(len(receipts), 81)
        self.assertEqual(len({row["namespace_sha256"] for row in receipts}), 81)
        self.assertTrue(all(row["store_reopened"] for row in receipts))
        self.assertTrue(all(not row["raw_database_path_exposed"] for row in receipts))

    def test_selected_r0_rag_cache_and_evidence_counts(self) -> None:
        rag = read_json("c4_real_mechanism_replay_summary_v1.json")["rag"]
        self.assertEqual(rag["selected_implementation"], "C4_RAG_R0_LEXICAL")
        self.assertEqual(rag["activation_count"], 84)
        self.assertEqual(rag["lexical_retrieval_computation_count"], 21)
        self.assertEqual(rag["retrieval_cache_hit_count"], 63)
        self.assertEqual(rag["result_status_counts"], {"LIMITED_EVIDENCE": 12, "NO_RESULT": 36, "SUPPORTED": 36})
        self.assertEqual(rag["selected_source_count"], 240)
        self.assertEqual(
            rag["evidence_strength_counts"],
            {"BODY_EXCERPT": 60, "LINK_ONLY": 44, "SUMMARY_SUPPORT": 12, "TITLE_AND_METADATA_ONLY": 124},
        )

    def test_memory_results_and_planner_consistency(self) -> None:
        summary = read_json("c4_real_mechanism_replay_summary_v1.json")
        memory = summary["memory"]
        self.assertEqual(memory["target_condition_read_count"], 76)
        self.assertEqual(memory["status_counts"], {"AVAILABLE": 8, "NO_MATCH": 68})
        self.assertEqual(memory["selected_item_count"], 12)
        self.assertEqual(memory["selected_memory_type_counts"], {"ACTIVE_PLAN": 8, "GOAL": 4})
        self.assertEqual(memory["stale_or_superseded_selection_count"], 0)
        planner = summary["planner"]
        self.assertEqual(planner["activation_count"], 60)
        self.assertEqual(planner["status_counts"], {"INSUFFICIENT_EVIDENCE": 6, "USED": 54})
        self.assertEqual(planner["zero_step_plan_count"], 6)
        self.assertEqual(planner["evidence_provenance_inconsistency_count"], 0)
        self.assertEqual(planner["learner_constraint_inconsistency_count"], 0)

    def test_provider_safe_projection_and_all_payloads_have_zero_leakage(self) -> None:
        contract = read_json("c4_real_provider_evidence_projection_v1.json")
        self.assertEqual(contract["status"], "FROZEN_ALLOWLIST")
        self.assertEqual(set(contract["prohibited_fields"]), set(PROVIDER_PROHIBITED_KEYS))
        rows = load_jsonl(HERE / "c4_real_unique_generation_request_manifest_frozen_v1.jsonl")
        self.assertEqual(len(rows), 197)
        for row in rows:
            self.assertEqual(_provider_leakage_errors(row["provider_payload"]), [])
        audit = read_json("c4_real_provider_payload_privacy_and_leakage_audit_v1.json")
        self.assertEqual(audit["status"], "PASS_ZERO_LEAKS")
        self.assertEqual(audit["provider_payload_count"], 558)
        for key, value in audit.items():
            if key.endswith("occurrence_count"):
                self.assertEqual(value, 0)

    def test_pre_response_applicability_is_complete_and_mode_independent_for_need(self) -> None:
        rows = load_jsonl(HERE / "c4_real_condition_applicability_maps_frozen_v1.jsonl")
        self.assertEqual(len(rows), 558)
        by_scenario: dict[str, list[dict]] = defaultdict(list)
        for row in rows:
            self.assertFalse(row["candidate_response_accessed"])
            self.assertFalse(row["gold_accessed"])
            frozen = row["frozen_applicability_map"]
            self.assertGreaterEqual(frozen["applicable_primary_count"], 3)
            self.assertTrue(frozen["criteria"]["CLARITY"])
            self.assertTrue(frozen["criteria"]["CONTEXT_AWARENESS"])
            self.assertTrue(frozen["criteria"]["RELIABILITY"])
            by_scenario[row["scenario_id"]].append(row)
        for scenario_rows in by_scenario.values():
            self.assertEqual(
                len({row["frozen_applicability_map"]["criteria"]["PERSONALISATION"] for row in scenario_rows}),
                1,
            )
            self.assertEqual(
                len({row["frozen_applicability_map"]["criteria"]["ACTIONABILITY"] for row in scenario_rows}),
                1,
            )


class TransportAndDeduplicationTests(unittest.TestCase):
    def test_generation_v1_v2_semantic_equivalence_and_frozen_config(self) -> None:
        v1 = json.loads(SOURCE_PATHS["generation_schema_v1"].read_text(encoding="utf-8"))
        v2 = read_json("c4_real_generation_schema_v2_provider_compatible.json")
        self.assertEqual(sha256_file(SOURCE_PATHS["generation_schema_v1"]), EXPECTED_HASHES["generation_schema_v1"])
        self.assertEqual(sha256_file(SOURCE_PATHS["generation_prompt"]), EXPECTED_HASHES["generation_prompt"])
        self.assertEqual(v1["type"], v2["type"])
        self.assertEqual(set(v1["properties"]), {"answer_text"})
        self.assertEqual(set(v2["properties"]), {"answer_text"})
        self.assertEqual(v1["required"], v2["required"])
        self.assertFalse(v1["additionalProperties"])
        self.assertFalse(v2["additionalProperties"])
        config = read_json("c4_real_generation_configuration_frozen_v2.json")
        self.assertEqual(config["model"], "gpt-4o-mini-2024-07-18")
        self.assertEqual(config["temperature"], 0)
        self.assertEqual(config["max_output_tokens"], 512)
        self.assertFalse(config["generation_execution_authorised"])

    def test_judge_v2_transport_normalises_to_unchanged_v1_semantics(self) -> None:
        applicability = load_jsonl(HERE / "c4_real_condition_applicability_maps_frozen_v1.jsonl")[0][
            "frozen_applicability_map"
        ]
        criteria = applicability["criteria"]
        fields = {
            "CLARITY": "clarity",
            "PERSONALISATION": "personalisation",
            "ACTIONABILITY": "actionability",
            "CONTEXT_AWARENESS": "context_awareness",
            "MOTIVATION_AND_ENGAGEMENT": "motivation_and_engagement",
            "RELIABILITY": "reliability",
            "MULTI_PAGE_COHESIVENESS": "multi_page_cohesiveness",
            "ERROR_HANDLING": "error_handling",
        }
        v2 = {
            "response_blind_id": "R3B-0123456789ABCDEF0123",
            **{field: "4" if criteria[name] else "NA" for name, field in fields.items()},
            "evidence_faithfulness": "5",
            "unsupported_claim_count": "0",
            "overall_applicable_mean": "4.0",
            "criterion_rationales": {field: "Transport-equivalence test." for field in fields.values()},
            "schema_version": "rq3-judge-response-v2-transport",
        }
        normalised = normalise_judge_transport_v2(
            v2,
            applicability,
            expected_response_blind_id=v2["response_blind_id"],
        )
        v1 = dict(v2)
        for name, field in fields.items():
            if criteria[name]:
                v1[field] = 4
        v1["evidence_faithfulness"] = 5
        v1["unsupported_claim_count"] = 0
        v1["overall_applicable_mean"] = 4.0
        v1["schema_version"] = "rq3-judge-response-v1"
        self.assertEqual(normalised, parse_judge_response(v1, applicability))
        config = read_json("c4_real_judge_configuration_frozen_v2.json")
        self.assertEqual(config["model"], "gpt-4.1-2025-04-14")
        self.assertEqual(config["temperature"], 0)
        self.assertFalse(config["judge_manifest_created"])
        self.assertEqual(config["judge_calls"], 0)

    def test_exact_deduplication_and_all_558_condition_mappings(self) -> None:
        registry = load_jsonl(
            RESTRICTED / "c4_real_condition_generation_payload_registry_frozen_v1.jsonl"
        )
        mappings = read_csv(
            RESTRICTED / "c4_real_condition_to_unique_request_mapping_frozen_v1.csv"
        )
        unique = load_jsonl(HERE / "c4_real_unique_generation_request_manifest_frozen_v1.jsonl")
        self.assertEqual(len(registry), 558)
        self.assertEqual(len(mappings), 558)
        exact = {hashlib.sha256(canonical_bytes(row["provider_payload"])).hexdigest() for row in registry}
        self.assertEqual(len(exact), len(unique))
        self.assertEqual(exact, {row["provider_payload_sha256"] for row in unique})
        summary = read_json("c4_real_generation_request_deduplication_summary_v1.json")
        self.assertEqual(summary["condition_mapping_count"], 558)
        self.assertEqual(summary["unique_request_count"], len(unique))
        self.assertEqual(summary["duplicate_mapping_count"], 558 - len(unique))
        self.assertFalse(summary["unique_count_hard_coded"])

    def test_blind_ids_key_commitment_and_restricted_mapping_integrity(self) -> None:
        key_path = RESTRICTED / "c4_real_i1_blinding_hmac_key.bin"
        key = key_path.read_bytes()
        metadata = read_json("c4_real_restricted_mapping_metadata_v1.json")
        self.assertEqual(len(key), 32)
        self.assertEqual(stat.S_IMODE(key_path.stat().st_mode), 0o600)
        self.assertEqual(hashlib.sha256(key).hexdigest(), metadata["hmac_key_sha256_commitment"])
        relative_key = key_path.relative_to(ROOT).as_posix()
        self.assertEqual(git("check-ignore", relative_key, check=False).returncode, 0)
        self.assertNotEqual(
            git("ls-files", "--error-unmatch", relative_key, check=False).returncode,
            0,
        )
        unique = load_jsonl(HERE / "c4_real_unique_generation_request_manifest_frozen_v1.jsonl")
        self.assertTrue(all(row["logical_generation_request_id"].startswith("C4G-") for row in unique))
        self.assertTrue(all(row["response_blind_id"].startswith("R3B-") for row in unique))
        for name, record in metadata["mapping_files"].items():
            path = RESTRICTED / name
            self.assertEqual(sha256_file(path), record["sha256"])
            count = len(load_jsonl(path)) if path.suffix == ".jsonl" else len(read_csv(path))
            self.assertEqual(count, record["row_count"])

    def test_scenario_atomic_shards_and_exact_package_balance(self) -> None:
        mappings = read_csv(
            RESTRICTED / "c4_real_condition_to_unique_request_mapping_frozen_v1.csv"
        )
        by_scenario: dict[str, set[str]] = defaultdict(set)
        by_request: dict[str, set[str]] = defaultdict(set)
        for row in mappings:
            by_scenario[row["scenario_id"]].add(row["shard_id"])
            by_request[row["logical_generation_request_id"]].add(row["shard_id"])
        self.assertTrue(all(len(shards) == 1 for shards in by_scenario.values()))
        self.assertTrue(all(len(shards) == 1 for shards in by_request.values()))
        summary = read_json("c4_real_generation_shard_summary_v1.json")
        self.assertTrue(summary["scenario_atomic"])
        self.assertEqual(summary["seed"], 20260901)
        self.assertEqual(
            {row["shard_id"]: row["unique_request_count"] for row in summary["shards"]},
            {"A": 68, "B": 62, "C": 67},
        )
        self.assertEqual(
            {row["shard_id"]: row["estimated_input_tokens"] for row in summary["shards"]},
            {"A": 57479, "B": 57407, "C": 57498},
        )


class PackageAndBoundaryTests(unittest.TestCase):
    def test_three_generation_packages_have_exact_allowlists_and_validate(self) -> None:
        manifest = read_json("c4_real_generation_package_manifest_v1.json")
        self.assertEqual(manifest["package_count"], 3)
        self.assertEqual(manifest["unique_request_count"], 197)
        self.assertEqual(manifest["logical_call_count"], 197)
        self.assertEqual(manifest["maximum_physical_attempt_count"], 394)
        for package in manifest["packages"]:
            path = Path(package["path"])
            self.assertEqual(path, DOWNLOADS / PACKAGE_NAMES[package["shard"]])
            self.assertEqual(sha256_file(path), package["sha256"])
            with zipfile.ZipFile(path) as archive:
                self.assertEqual(set(archive.namelist()), ALLOWED_FILES)
                with tempfile.TemporaryDirectory() as temporary:
                    archive.extractall(temporary)
                    report = validate_generation_package(Path(temporary))
            self.assertEqual(report["status"], "PASS")
            self.assertEqual(report["request_count"], package["request_count"])

    def test_future_runtime_preflight_identity(self) -> None:
        completed = subprocess.run(
            [
                "/opt/anaconda3/bin/python3",
                "-c",
                "import openai,sys; print('.'.join(map(str,sys.version_info[:3]))); print(openai.__version__)",
            ],
            check=True,
            capture_output=True,
            text=True,
        )
        self.assertEqual(completed.stdout.splitlines(), ["3.13.5", "1.109.1"])

    def test_zero_external_generation_judge_scoring_and_streamlit_execution(self) -> None:
        mechanism = read_json("c4_real_mechanism_replay_summary_v1.json")
        self.assertEqual(mechanism["outbound_network_attempt_count"], 0)
        for field in (
            "provider_call_count",
            "response_generation_count",
            "judge_call_count",
            "route_accuracy_score_count",
            "response_quality_score_count",
            "streamlit_launch_count",
        ):
            self.assertEqual(mechanism[field], 0)
        status = read_json("c4_real_i1_status_v1.json")
        self.assertEqual(
            status["RQ3_REAL_I1_STATUS"],
            "READY_FOR_PARALLEL_C4_REAL_RESPONSE_GENERATION_AUTHORIZATION",
        )
        self.assertTrue(status["generation_packages_preparation_complete"])
        self.assertFalse(status["response_generation_authorised"])
        self.assertFalse(status["response_generation_executed"])
        self.assertFalse(status["judge_executed"])
        self.assertFalse(status["scoring_executed"])
        self.assertFalse(status["streamlit_launched"])
        self.assertEqual(status["external_provider_calls"], 0)

    def test_no_database_key_or_restricted_mapping_is_tracked_or_packaged(self) -> None:
        tracked = git("ls-files").stdout.splitlines()
        self.assertFalse(any(name.endswith((".sqlite", ".sqlite3", ".db")) for name in tracked))
        restricted_tracked = [
            name
            for name in tracked
            if "/restricted_internal/" in name and not name.endswith("/.gitignore")
        ]
        self.assertEqual(restricted_tracked, [])
        key = (RESTRICTED / "c4_real_i1_blinding_hmac_key.bin").read_bytes()
        for name in PACKAGE_NAMES.values():
            package = DOWNLOADS / name
            self.assertNotIn(key, package.read_bytes())
            with zipfile.ZipFile(package) as archive:
                self.assertFalse(any("restricted" in item.casefold() for item in archive.namelist()))


if __name__ == "__main__":
    unittest.main(verbosity=2)
