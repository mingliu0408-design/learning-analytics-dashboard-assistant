"""Contract and reproducibility tests for RQ2-A-R2B."""

from __future__ import annotations

import ast
import copy
import hashlib
import json
from pathlib import Path
import subprocess
import unittest

from . import (
    AUTHENTIC_LABELS_RELATIVE,
    AUTHENTIC_REGISTRY_LABELS_RELATIVE,
    CANONICAL_ADJUDICATION_RELATIVE,
    CANONICAL_ADJUDICATION_SHA256,
    CAPABILITIES,
    COMBINED_BANK_RELATIVE,
    COMBINED_BANK_SHA256,
    EXPECTED_AUTHENTIC_DISTRIBUTION,
    EXPECTED_SYNTHETIC_DISTRIBUTION,
    LABEL_ONLY_FIELDS,
    LOCAL_AUTHENTIC_GOLD_RELATIVE,
    LOCAL_AUTHENTIC_REGISTRY_RELATIVE,
    LOCAL_COMBINED_GOLD_RELATIVE,
    LOCAL_SYNTHETIC_GOLD_RELATIVE,
    ROOT,
    RQ2A_R2A_HEAD,
    RQ2A_R2A_PARENT,
    RQ2A_R2A_REVIEW_ZIP_NAME,
    RQ2A_R2A_REVIEW_ZIP_SHA256,
    SOURCE_MAPPING_RELATIVE,
    SOURCE_MAPPING_SHA256,
    SYNTHETIC_LABELS_RELATIVE,
    reject_prohibited_track_path,
    sha256_file,
)
from .adjudication_canonicalisation import (
    canonicalise_adjudication_bytes,
    validate_canonical_adjudication,
)
from .adjudication_packet_identity import (
    rebuild_blank_packet_in_external_temp,
    validate_completed_against_blank,
    verify_adjudication_identity,
)
from .adjudicator_attestation import (
    adjudicator_independence_attestation,
    validate_adjudicator_independence_attestation,
)
from .coverage_validator import COVERAGE_THRESHOLDS, validate_synthetic_coverage
from .eligibility_amendment import (
    synthetic_clarification_eligibility_amendment,
    synthetic_clarification_exception_applies,
)
from .gold_policy_v1_1 import (
    AUTHENTIC_REGISTRY,
    SYNTHETIC_GOLD,
    authentic_destination,
    synthetic_destination,
)
from .post_gold_diagnostics import verify_frozen_gold_members
from .source_separated_gold_builder import (
    GoldBuilderError,
    LOCAL_OUTPUTS,
    _consensus_decision,
    build_source_separated_gold_bytes,
)
from .validate_rq2a_r2b import (
    AMENDMENT_RELATIVE,
    ATTESTATION_RELATIVE,
    CHECKSUM_RELATIVE,
    DIAGNOSTIC_RELATIVE,
    DOCUMENT_RELATIVES,
    EXPECTED_TEST_COVERAGE,
    GOLD_MANIFEST_RELATIVE,
    GOLD_SUMMARY_RELATIVE,
    OUTPUT_CHECKSUM_RELATIVES,
    POLICY_RELATIVE,
    PREFLIGHT_RELATIVE,
    PYTHON_FILES,
    assert_change_scope,
    assert_lineage,
    assert_python_ast_and_offline_surface,
    assert_r2a_artifacts,
    governed_text_leak_scan,
    validate_existing_outputs,
    validate_output_checksums,
)


def _json(relative: Path) -> dict:
    return json.loads((ROOT / relative).read_text(encoding="utf-8"))


def _jsonl(relative: Path) -> list[dict]:
    return [
        json.loads(line)
        for line in (ROOT / relative).read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]


class RQ2AR2BTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.canonical_path = ROOT / CANONICAL_ADJUDICATION_RELATIVE
        cls.build = build_source_separated_gold_bytes(cls.canonical_path, ROOT)
        cls.authentic = _jsonl(AUTHENTIC_LABELS_RELATIVE)
        cls.synthetic = _jsonl(SYNTHETIC_LABELS_RELATIVE)
        cls.registry = _jsonl(AUTHENTIC_REGISTRY_LABELS_RELATIVE)
        cls.manifest = _json(GOLD_MANIFEST_RELATIVE)

    def test_01_starting_lineage_review_zip_and_checksums(self) -> None:
        self.assertEqual(
            subprocess.run(
                ["git", "rev-parse", f"{RQ2A_R2A_HEAD}^"],
                cwd=ROOT,
                capture_output=True,
                check=True,
            ).stdout.decode().strip(),
            RQ2A_R2A_PARENT,
        )
        self.assertIn(assert_lineage()["relative_commit_count"], {0, 1})
        zip_path = Path.home() / "Downloads" / RQ2A_R2A_REVIEW_ZIP_NAME
        self.assertEqual(sha256_file(zip_path), RQ2A_R2A_REVIEW_ZIP_SHA256)
        self.assertEqual(assert_r2a_artifacts()["output_checksum_count"], 19)

    def test_02_completed_identity_blank_rebuild_and_fixed_fields(self) -> None:
        completed, identity = verify_adjudication_identity(ROOT)
        blank = rebuild_blank_packet_in_external_temp(ROOT)
        repeated = rebuild_blank_packet_in_external_temp(ROOT)
        self.assertEqual(blank, repeated)
        self.assertEqual(
            hashlib.sha256(blank).hexdigest(),
            "acb0f6111f51e38539e187c2899f4bd4853c69fd52cf104a2dcaebf1395afbf1",
        )
        audit = validate_completed_against_blank(completed, blank)
        self.assertEqual(identity["fixed_field_mutation_count"], 0)
        self.assertEqual(identity["reviewer_field_mutation_count"], 0)
        self.assertTrue(audit["human_adjudication_completed"])
        self.assertEqual(audit["precanonical_date_count"], 5)
        self.assertEqual(audit["uppercase_immutable_boolean_count"], 10)

    def test_03_exact_canonicalisation_and_schema(self) -> None:
        completed, _ = verify_adjudication_identity(ROOT)
        source = completed.read_bytes()
        canonical = canonicalise_adjudication_bytes(source)
        self.assertEqual(canonical, self.canonical_path.read_bytes())
        self.assertEqual(hashlib.sha256(canonical).hexdigest(), CANONICAL_ADJUDICATION_SHA256)
        self.assertEqual(source.count(b"2026/8/26"), 5)
        self.assertEqual(source.count(b"FALSE"), 10)
        schema = validate_canonical_adjudication(self.canonical_path)
        self.assertEqual(schema["status"], "PASS")
        self.assertEqual(schema["authentic_missing_context_case_count"], 3)
        self.assertFalse(schema["query_rewrite_performed"])
        self.assertFalse(schema["assistant_context_attached"])

    def test_04_third_human_and_no_ai_attestation(self) -> None:
        value = _json(ATTESTATION_RELATIVE)
        validate_adjudicator_independence_attestation(value)
        self.assertEqual(value, adjudicator_independence_attestation())
        self.assertTrue(value["adjudicator_is_third_human"])
        self.assertFalse(value["adjudicator_is_reviewer_a"])
        self.assertFalse(value["adjudicator_is_reviewer_b"])
        self.assertFalse(value["used_chatgpt"])
        self.assertFalse(value["used_codex"])
        self.assertFalse(value["used_other_ai"])

    def test_05_amendment_authority_and_synthetic_only_exception(self) -> None:
        amendment = _json(AMENDMENT_RELATIVE)
        self.assertEqual(amendment, synthetic_clarification_eligibility_amendment())
        self.assertEqual(amendment["authority_basis"], "USER_EXPLICIT_AUTHORISATION")
        exception = dict(amendment["synthetic_exception_required_conditions"])
        self.assertTrue(synthetic_clarification_exception_applies(exception))
        self.assertEqual(synthetic_destination(exception), SYNTHETIC_GOLD)
        authentic = {**exception, "source_role": "authentic"}
        self.assertFalse(synthetic_clarification_exception_applies(authentic))
        self.assertEqual(authentic_destination(authentic), AUTHENTIC_REGISTRY)
        self.assertFalse(amendment["human_annotation_changed"])
        self.assertFalse(amendment["coverage_threshold_changed"])
        self.assertFalse(amendment["capability_definition_changed"])

    def test_06_gold_input_hashes(self) -> None:
        self.assertEqual(sha256_file(ROOT / SOURCE_MAPPING_RELATIVE), SOURCE_MAPPING_SHA256)
        self.assertEqual(sha256_file(ROOT / COMBINED_BANK_RELATIVE), COMBINED_BANK_SHA256)
        preflight = _json(PREFLIGHT_RELATIVE)
        self.assertEqual(preflight["source_mapping_sha256"], SOURCE_MAPPING_SHA256)
        self.assertEqual(preflight["combined_bank_sha256"], COMBINED_BANK_SHA256)

    def test_07_human_precedence_and_unresolved_disagreement_rejection(self) -> None:
        self.assertEqual(self.build["composition"]["consensus_cases"], 55)
        self.assertEqual(self.build["composition"]["adjudicated_cases"], 5)
        rows_a = self.build["all_decisions"]
        self.assertEqual(
            sum(row["gold_decision_source"] == "HUMAN_ADJUDICATION" for row in rows_a),
            5,
        )
        sample_a = {
            field: "NO"
            for field in (
                "case_validity",
                "context_link_valid",
                "context_sufficient",
                "capability_unambiguous",
                "context_resolution_required",
                *CAPABILITIES,
                "forbidden_capabilities",
            )
        }
        sample_b = copy.deepcopy(sample_a)
        sample_b["dashboard_evidence"] = "YES"
        with self.assertRaises(GoldBuilderError):
            _consensus_decision(sample_a, sample_b)

    def test_08_gold_composition(self) -> None:
        self.assertEqual(
            self.build["composition"],
            {
                "total_reviewed_cases": 60,
                "authentic_total": 25,
                "authentic_gold": 22,
                "authentic_context_missing_registry": 3,
                "synthetic_total": 35,
                "synthetic_gold": 35,
                "synthetic_excluded": 0,
                "combined_gold": 57,
                "consensus_cases": 55,
                "adjudicated_cases": 5,
                "included_adjudicated_gold_cases": 2,
                "adjudicated_authentic_registry_cases": 3,
            },
        )
        self.assertEqual((len(self.authentic), len(self.synthetic), len(self.registry)), (22, 35, 3))
        self.assertEqual(len(_jsonl(LOCAL_COMBINED_GOLD_RELATIVE)), 57)

    def test_09_capability_distributions(self) -> None:
        for key, expected in EXPECTED_AUTHENTIC_DISTRIBUTION.items():
            self.assertEqual(self.build["authentic_distribution"][key], expected)
        self.assertEqual(self.build["synthetic_distribution"], EXPECTED_SYNTHETIC_DISTRIBUTION)
        self.assertEqual(self.build["synthetic_distribution"]["synthetic_clarification_exception_cases"], 3)
        self.assertEqual(self.build["synthetic_distribution"]["multi_capability_cases"], 9)

    def test_10_all_coverage_gates_pass_and_thresholds_unchanged(self) -> None:
        coverage = validate_synthetic_coverage(self.synthetic)
        self.assertEqual(coverage, _json(Path("evaluation/capability_routing_v1_r2b/synthetic_coverage_validation_v1.json")))
        self.assertTrue(all(gate["status"] == "PASS" for gate in coverage["gates"].values()))
        self.assertEqual(COVERAGE_THRESHOLDS["included_synthetic_cases"], 20)
        self.assertEqual(COVERAGE_THRESHOLDS["context_resolution_required_positives"], 4)
        self.assertEqual(COVERAGE_THRESHOLDS["multi_capability_cases"], 4)

    def test_11_gold_freeze_precedes_unblinding_and_bundle_verifies(self) -> None:
        self.assertEqual(self.manifest["status"], "HUMAN_GOLD_FROZEN")
        self.assertTrue(self.manifest["gold_frozen_before_unblinding"])
        self.assertFalse(self.manifest["hidden_proposal_accessed"])
        self.assertFalse(self.manifest["model_output_accessed"])
        before = verify_frozen_gold_members(ROOT, self.manifest["gold_members"])
        after = verify_frozen_gold_members(ROOT, self.manifest["gold_members"])
        self.assertEqual(before, after)

    def test_12_diagnostic_order_source_separation_and_nonblocking_absence(self) -> None:
        diagnostic = _json(DIAGNOSTIC_RELATIVE)
        self.assertTrue(diagnostic["gold_hashes_verified_before_unblinding"])
        self.assertTrue(diagnostic["gold_hashes_unchanged_after_diagnostic"])
        self.assertFalse(diagnostic["proposal_used_to_form_gold"])
        self.assertFalse(diagnostic["threshold_tuning_performed"])
        self.assertEqual(diagnostic["overall_included_count"], 57)
        self.assertEqual(diagnostic["authentic_included_count"], 22)
        self.assertEqual(diagnostic["synthetic_included_count"], 35)
        self.assertEqual(diagnostic["authentic_context_missing_count"], 3)
        self.assertIn(diagnostic["status"], {"PASS", "NOT_AVAILABLE_COMPLETE_PROPOSAL_LEDGER"})

    def test_13_local_full_text_gold_is_ignored_and_untracked(self) -> None:
        for relative in LOCAL_OUTPUTS:
            self.assertEqual(
                subprocess.run(
                    ["git", "check-ignore", "-q", "--", relative.as_posix()],
                    cwd=ROOT,
                    check=False,
                ).returncode,
                0,
            )
            self.assertNotIn(relative.as_posix(), subprocess.run(
                ["git", "ls-files"], cwd=ROOT, capture_output=True, check=True
            ).stdout.decode().splitlines())

    def test_14_tracked_gold_exact_safe_field_allowlist(self) -> None:
        for rows in (self.authentic, self.synthetic, self.registry):
            self.assertTrue(
                all(set(row) == set(LABEL_ONLY_FIELDS) for row in rows)
            )
            text = json.dumps(rows, ensure_ascii=False).lower()
            for prohibited in (
                "current_query",
                "current_page",
                "conversation_history",
                "rationale",
                "reviewer_id",
                "adjudicator_id",
                "canonical_case_id",
                "hidden_proposal",
                "c0_score",
                "legacy_output",
            ):
                self.assertNotIn(prohibited, text)
            self.assertNotIn("/users/", text)

    def test_15_no_model_output_forms_gold(self) -> None:
        for key in (
            "hidden_proposal_used_to_form_gold",
            "legacy_output_used_to_form_gold",
            "c0_used_to_form_gold",
            "intent_prediction_used_to_form_gold",
        ):
            self.assertFalse(self.manifest[key])

    def test_16_track_boundaries(self) -> None:
        with self.assertRaises(Exception):
            reject_prohibited_track_path("evaluation/track_a/example.jsonl")
        with self.assertRaises(Exception):
            reject_prohibited_track_path("evaluation/track_b/example.jsonl")

    def test_17_no_production_change_and_staged_allowlist(self) -> None:
        assert_change_scope()
        changed = subprocess.run(
            ["git", "diff", "--name-only", RQ2A_R2A_HEAD],
            cwd=ROOT,
            capture_output=True,
            check=True,
        ).stdout.decode().splitlines()
        self.assertTrue(all(
            name == ".gitignore"
            or name.startswith("evaluation/capability_routing_v1_r2b/")
            or name.startswith("docs/thesis_mainline/rq2/RQ2A_R2B_")
            for name in changed
        ))

    def test_18_python_ast_and_no_provider_network_surface(self) -> None:
        assert_python_ast_and_offline_surface()
        for name in PYTHON_FILES:
            ast.parse((ROOT / "evaluation/capability_routing_v1_r2b" / name).read_text(encoding="utf-8"))

    def test_19_double_build_byte_identical_and_persisted(self) -> None:
        second = build_source_separated_gold_bytes(self.canonical_path, ROOT)
        self.assertEqual(self.build["output_bytes"], second["output_bytes"])
        for relative, value in second["output_bytes"].items():
            self.assertEqual((ROOT / relative).read_bytes(), value)

    def test_20_output_checksums_and_validator(self) -> None:
        self.assertEqual(validate_output_checksums(), len(OUTPUT_CHECKSUM_RELATIVES))
        self.assertEqual(validate_existing_outputs()["status"], "PASS")
        self.assertTrue((ROOT / CHECKSUM_RELATIVE).is_file())

    def test_21_governed_text_leak_scan(self) -> None:
        result = governed_text_leak_scan(OUTPUT_CHECKSUM_RELATIVES)
        self.assertEqual(result["status"], "PASS")
        self.assertEqual(result["leak_count"], 0)

    def test_22_safe_outputs_and_limitations(self) -> None:
        summary = _json(GOLD_SUMMARY_RELATIVE)
        self.assertEqual(summary["authentic_limitations"]["episodic_memory_positive_count"], 0)
        self.assertEqual(summary["authentic_limitations"]["clarification_positive_count"], 0)
        self.assertFalse(summary["synthetic_limitations"]["final_evaluation_eligible"])
        self.assertEqual(summary["track_b_status"], "SEALED_FUTURE_INDEPENDENT_CONTEXTUAL_FINAL_HELDOUT")
        preflight = _json(PREFLIGHT_RELATIVE)
        self.assertEqual(preflight["expected_test_coverage"], list(EXPECTED_TEST_COVERAGE))
        self.assertFalse(preflight["track_a_accessed"])
        self.assertFalse(preflight["track_b_accessed"])
        self.assertFalse(preflight["b0_implemented"])
        self.assertFalse(preflight["p1_implemented"])
        self.assertFalse(preflight["p2_implemented"])

    def test_23_review_documents_present(self) -> None:
        self.assertTrue(all((ROOT / relative).is_file() for relative in DOCUMENT_RELATIVES))
        self.assertTrue((ROOT / POLICY_RELATIVE).is_file())


if __name__ == "__main__":
    unittest.main()
