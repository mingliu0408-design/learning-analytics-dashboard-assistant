#!/usr/bin/env python3
"""Offline verification for the RQ3-REAL-C4-J2D0 repair and freeze."""

from __future__ import annotations

from contextlib import contextmanager
import hashlib
import json
import os
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from zipfile import ZipFile

from judge_execution_runner_v3 import (
    AUTHORIZATION_ENVIRONMENT_VALUE,
    AUTHORIZATION_ENVIRONMENT_VARIABLE,
    AUTHORIZATION_SCHEMA_VERSION,
    REQUEST_TIMEOUT_SECONDS,
    RunnerError,
    execute_package,
)
from judge_package_validator_v3 import (
    ALLOWED_FILES,
    canonical_json_bytes,
    sha256_bytes,
    sha256_file,
    validate_package_zip,
)
from judge_result_parser_v3 import (
    JudgeResultError,
    PRIMARY_CRITERIA,
    SCORE_FIELDS,
    TRANSPORT_SCHEMA_VERSION,
    parse_judge_result,
)


HERE = Path(__file__).resolve().parent
REPO = HERE.parents[2]
DOWNLOADS = Path("/Users/liuming/Downloads")
SHARDS = {
    "A": {
        "source": DOWNLOADS / "C4_REAL_JUDGE_SHARD_A_EXECUTION_PACKAGE_R2_2026-09-02.zip",
        "source_sha": "7e57d62a56feb2776398fd2b719a009e3eed64c8ebb6b48fc63666eaed300ff7",
        "continuation": DOWNLOADS / "C4_REAL_JUDGE_SHARD_A_CONTINUATION_EXECUTION_PACKAGE_R3_2026-09-02.zip",
        "orders": list(range(2, 50)),
        "canonical": 1,
    },
    "B": {
        "source": DOWNLOADS / "C4_REAL_JUDGE_SHARD_B_EXECUTION_PACKAGE_R2_2026-09-02.zip",
        "source_sha": "decc499163089e467ae6ec0e5d4f4e46a410f3670a99b17cf0c6396031ffb68b",
        "continuation": DOWNLOADS / "C4_REAL_JUDGE_SHARD_B_CONTINUATION_EXECUTION_PACKAGE_R3_2026-09-02.zip",
        "orders": list(range(39, 50)),
        "canonical": 38,
    },
    "C": {
        "source": DOWNLOADS / "C4_REAL_JUDGE_SHARD_C_EXECUTION_PACKAGE_R2_2026-09-02.zip",
        "source_sha": "7f7863a5dd399ae62136bd5bf7541f6d5fc7347eafb275d22b435b25821639cd",
        "continuation": DOWNLOADS / "C4_REAL_JUDGE_SHARD_C_CONTINUATION_EXECUTION_PACKAGE_R3_2026-09-02.zip",
        "orders": list(range(32, 50)),
        "canonical": 31,
    },
}


def read_json(name: str) -> dict:
    return json.loads((HERE / name).read_text("utf-8"))


def read_jsonl(path: Path) -> list[dict]:
    return [json.loads(line) for line in path.read_text("utf-8").splitlines() if line]


def zip_rows(path: Path) -> list[dict]:
    with ZipFile(path) as archive:
        return [
            json.loads(line)
            for line in archive.read("BLINDED_JUDGE_REQUESTS.jsonl").splitlines()
            if line
        ]


def source_rows(path: Path) -> list[dict]:
    with ZipFile(path) as archive:
        return [
            json.loads(line)
            for line in archive.read("BLINDED_JUDGE_REQUESTS.jsonl").splitlines()
            if line
        ]


def applicability(count: int = 5) -> dict:
    criteria = {
        criterion: index < count for index, criterion in enumerate(PRIMARY_CRITERIA)
    }
    return {
        "schema_version": "rq3-dimension-applicability-map-v1",
        "freeze_status": "FROZEN_BEFORE_CANDIDATE_SCORING",
        "criteria": criteria,
        "applicable_primary_count": count,
        "applicability_sha256": sha256_bytes(canonical_json_bytes(criteria)),
    }


def valid_result(app: dict) -> dict:
    scores = {
        SCORE_FIELDS[criterion]: "4" if app["criteria"][criterion] else "NA"
        for criterion in PRIMARY_CRITERIA
    }
    return {
        **scores,
        "evidence_faithfulness": "4",
        "unsupported_claim_count": "0",
        "criterion_rationales": {
            field: "non-empty rationale" for field in SCORE_FIELDS.values()
        },
        "schema_version": TRANSPORT_SCHEMA_VERSION,
    }


class MockClock:
    def __init__(self) -> None:
        self.value = 0.0

    def monotonic(self) -> float:
        return self.value

    def sleep(self, seconds: float) -> None:
        self.value += seconds


class TimeoutClient:
    max_retries = 0
    timeout = SimpleNamespace(connect=120.0, read=120.0, write=120.0, pool=120.0)

    def __init__(self) -> None:
        self.calls = 0
        self.chat = SimpleNamespace(completions=self)

    def create(self, **_payload: object) -> None:
        self.calls += 1
        raise TimeoutError("mock only")

    def close(self) -> None:
        return None


@contextmanager
def auth_gate():
    prior = os.environ.get(AUTHORIZATION_ENVIRONMENT_VARIABLE)
    os.environ[AUTHORIZATION_ENVIRONMENT_VARIABLE] = AUTHORIZATION_ENVIRONMENT_VALUE
    try:
        yield
    finally:
        if prior is None:
            os.environ.pop(AUTHORIZATION_ENVIRONMENT_VARIABLE, None)
        else:
            os.environ[AUTHORIZATION_ENVIRONMENT_VARIABLE] = prior


class J2D0Tests(unittest.TestCase):
    def test_01_commit_integration_order_and_mapping(self) -> None:
        value = read_json("c4_real_judge_commit_integration_mapping_v1.json")
        self.assertEqual(value["status"], "PASS_INTEGRATED_IN_EXACT_ORDER")
        self.assertEqual(
            [row["original_commit"] for row in value["integrations"]],
            [
                "9c18da0ba418161b0976fbfd4cbaf7e86368b84c",
                "936aef8c9e8796262887b7f9ab4a8358d128481d",
                "02b9b1572065e780592bf6326acb6fd002a98288",
            ],
        )
        self.assertTrue(all(row["tree_content_preserved"] for row in value["integrations"]))

    def test_02_original_package_hashes_unchanged(self) -> None:
        for info in SHARDS.values():
            self.assertEqual(sha256_file(info["source"]), info["source_sha"])

    def test_03_all_integrated_files_match_source_commits(self) -> None:
        value = read_json("C4_REAL_JUDGE_EXISTING_OUTPUT_PRESERVATION_MANIFEST_V1.json")
        self.assertTrue(value["all_original_execution_artifacts_unchanged"])
        for shard in value["integrated_execution_evidence"].values():
            self.assertTrue(shard["unchanged"])
            self.assertTrue(all(row["unchanged"] for row in shard["files"].values()))

    def test_04_required_execution_hashes_match(self) -> None:
        preservation = read_json("C4_REAL_JUDGE_EXISTING_OUTPUT_PRESERVATION_MANIFEST_V1.json")
        required = {
            "A": (
                "53fc0cd24e492ef8f585b6789c64f2e5fa0a13486298910c6e3224eaf36f0bf6",
                "e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855",
            ),
            "B": (None, "ec90b7e4994f0ace2dcbfed2965066e790fe720affc7d155cc374c88148c5a44"),
            "C": (None, "8d5af59458e65a90b38c363204fd71dea6ee30dad00fd245929e7b26aa151a28"),
        }
        for shard, (attempt_hash, terminal_hash) in required.items():
            files = preservation["integrated_execution_evidence"][shard]["files"]
            attempt = next(v for k, v in files.items() if k.endswith("JUDGE_ATTEMPT_JOURNAL.jsonl"))
            terminal = next(v for k, v in files.items() if k.endswith("JUDGE_TERMINAL_JOURNAL.jsonl"))
            if attempt_hash:
                self.assertEqual(attempt["after_sha256"], attempt_hash)
            self.assertEqual(terminal["after_sha256"], terminal_hash)

    def test_05_returned_output_counts(self) -> None:
        summary = read_json("c4_real_existing_judge_attempt_reclassification_summary_v3.json")
        self.assertEqual(summary["provider_returned_outputs"], {"A": 2, "B": 38, "C": 31, "total": 71})

    def test_06_shard_a_v2_failure_reproduced(self) -> None:
        rows = read_jsonl(HERE / "c4_real_existing_judge_attempt_reclassification_v3.jsonl")
        a = [row for row in rows if row["shard"] == "A"]
        self.assertEqual(len(a), 2)
        self.assertTrue(all(row["parser_v2_status"] == "STRICT_SCHEMA_VALIDATION_FAILED" for row in a))

    def test_07_shard_a_rationale_lengths_observed(self) -> None:
        rows = read_jsonl(HERE / "c4_real_existing_judge_attempt_reclassification_v3.jsonl")
        a = [row for row in rows if row["shard"] == "A"]
        self.assertEqual([row["rationale_lengths"]["actionability"] for row in a], [643, 514])
        for row in a:
            self.assertEqual(
                [name for name, length in row["rationale_lengths"].items() if length > 500],
                ["actionability"],
            )

    def test_08_all_returned_outputs_pass_v3(self) -> None:
        rows = read_jsonl(HERE / "c4_real_existing_judge_attempt_reclassification_v3.jsonl")
        self.assertEqual(len(rows), 71)
        self.assertTrue(all(row["parser_v3_status"] == "VALID" for row in rows))

    def test_09_v2_valid_results_semantically_unchanged(self) -> None:
        summary = read_json("c4_real_existing_judge_attempt_reclassification_summary_v3.json")
        self.assertEqual(summary["parser_v2"], {"valid": 69, "invalid": 2})
        self.assertTrue(summary["all_previously_valid_parser_v2_results_semantically_unchanged"])

    def test_10_canonical_rule_is_exact(self) -> None:
        value = read_json("C4_REAL_JUDGE_CANONICAL_ATTEMPT_SELECTION_RULE_V1.json")
        self.assertEqual(value["rule"], "EARLIEST_VALID_ATTEMPT_UNDER_JUDGE_PARSER_V3")
        self.assertFalse(value["score_based_selection"])
        self.assertFalse(value["condition_or_mode_based_selection"])

    def test_11_canonical_result_counts(self) -> None:
        rows = read_jsonl(HERE / "c4_real_existing_canonical_judge_results_v1.jsonl")
        self.assertEqual(len(rows), 70)
        self.assertEqual({s: sum(row["shard"] == s for row in rows) for s in SHARDS}, {"A": 1, "B": 38, "C": 31})

    def test_12_shard_a_attempt_one_selected(self) -> None:
        rows = read_jsonl(HERE / "c4_real_existing_canonical_judge_results_v1.jsonl")
        selected = next(row for row in rows if row["shard"] == "A")
        self.assertEqual(selected["logical_order"], 1)
        self.assertEqual(selected["selected_attempt_number"], 1)

    def test_13_shard_a_attempt_two_label(self) -> None:
        rows = read_jsonl(HERE / "c4_real_existing_judge_attempt_reclassification_v3.jsonl")
        row = next(row for row in rows if row["shard"] == "A" and row["attempt_number"] == 2)
        self.assertEqual(row["canonical_selection_status"], "NOT_SELECTED_REDUNDANT_RETRY_AFTER_PARSER_V2_FALSE_REJECTION")

    def test_14_reclassification_has_no_unblinding_fields(self) -> None:
        rows = read_jsonl(HERE / "c4_real_existing_judge_attempt_reclassification_v3.jsonl")
        forbidden = {"scenario", "family", "mode", "condition", "expected_winner"}
        self.assertTrue(all(not (set(row) & forbidden) for row in rows))

    def test_15_b_timeout_audit(self) -> None:
        text = (HERE / "C4_REAL_JUDGE_TIMEOUT_AUDIT.md").read_text()
        self.assertIn("2026-09-02T13:06:50.813689Z", text)
        self.assertIn("2026-09-02T13:07:00.824768Z", text)
        self.assertIn("10.011079", text)

    def test_16_c_timeout_audit(self) -> None:
        text = (HERE / "C4_REAL_JUDGE_TIMEOUT_AUDIT.md").read_text()
        self.assertIn("2026-09-02T13:06:47.474174Z", text)
        self.assertIn("2026-09-02T13:06:57.484653Z", text)
        self.assertIn("10.010479", text)

    def test_17_timeout_audit_is_causally_bounded(self) -> None:
        text = (HERE / "C4_REAL_JUDGE_TIMEOUT_AUDIT.md").read_text()
        self.assertIn("does not explicitly freeze a request timeout", text)
        self.assertIn("do not prove which environment or client default", text)

    def test_18_runner_v3_freezes_timeout_and_retries(self) -> None:
        text = (HERE / "judge_execution_runner_v3.py").read_text()
        self.assertIn("OpenAI(max_retries=0, timeout=REQUEST_TIMEOUT_SECONDS)", text)
        self.assertEqual(REQUEST_TIMEOUT_SECONDS, 120.0)

    def test_19_exact_runtime_client_preflight(self) -> None:
        value = read_json("C4_REAL_JUDGE_RUNNER_V3_OFFLINE_PREFLIGHT_RECEIPT.json")
        self.assertEqual(value["status"], "PASS_CLIENT_ACCEPTED_AND_PRESERVED_EXPLICIT_TIMEOUT")
        self.assertEqual(value["request_timeout_seconds"], 120.0)
        self.assertEqual(value["client_max_retries"], 0)
        self.assertEqual(set(value["timeout_components_seconds"].values()), {120.0})
        self.assertEqual(value["provider_calls"], 0)

    def test_20_parser_long_rationale_is_not_changed(self) -> None:
        app = applicability()
        result = valid_result(app)
        result["criterion_rationales"]["actionability"] = "x" * 643
        parsed = parse_judge_result(result, app, expected_judge_result_blind_id="R3B-00000000000000000000")
        self.assertEqual(parsed["criterion_rationales"]["actionability"], "x" * 643)

    def test_21_parser_empty_rationale_rejected(self) -> None:
        app = applicability()
        result = valid_result(app)
        result["criterion_rationales"]["actionability"] = " \t"
        with self.assertRaises(JudgeResultError):
            parse_judge_result(result, app, expected_judge_result_blind_id="R3B-00000000000000000000")

    def test_22_duplicate_json_key_rejected(self) -> None:
        with self.assertRaisesRegex(JudgeResultError, "duplicate JSON key"):
            parse_judge_result('{"clarity":"1","clarity":"2"}', applicability(), expected_judge_result_blind_id="R3B-00000000000000000000")

    def test_23_applicability_contract_unchanged(self) -> None:
        app = applicability()
        result = valid_result(app)
        result["clarity"] = "NA"
        with self.assertRaisesRegex(JudgeResultError, "APPLICABILITY_CONTRACT"):
            parse_judge_result(result, app, expected_judge_result_blind_id="R3B-00000000000000000000")

    def test_24_local_mean_remains_exact(self) -> None:
        app = applicability(6)
        result = valid_result(app)
        result["clarity"] = "2"
        parsed = parse_judge_result(result, app, expected_judge_result_blind_id="R3B-00000000000000000000")
        self.assertEqual(parsed["overall_applicable_mean"], 22 / 6)

    def test_25_remaining_order_ranges(self) -> None:
        for shard, info in SHARDS.items():
            name = f"c4_real_judge_shard_{shard.lower()}_remaining_manifest_v1.jsonl"
            rows = read_jsonl(HERE / name)
            self.assertEqual([row["original_logical_order"] for row in rows], info["orders"])

    def test_26_completed_and_remaining_are_disjoint(self) -> None:
        audit = read_json("c4_real_judge_continuation_source_identity_audit_v1.json")
        self.assertTrue(audit["completed_and_remaining_sets_disjoint"])
        self.assertEqual(audit["existing_canonical_request_count"], 70)
        self.assertEqual(audit["remaining_request_count"], 77)

    def test_27_union_is_exact_147_request_universe(self) -> None:
        audit = read_json("c4_real_judge_continuation_source_identity_audit_v1.json")
        self.assertTrue(audit["existing_and_remaining_union_equals_exact_147_request_universe"])
        self.assertEqual(audit["exact_judge_universe_request_count"], 147)

    def test_28_provider_payloads_are_byte_identical(self) -> None:
        for shard, info in SHARDS.items():
            source = source_rows(info["source"])
            remaining = zip_rows(info["continuation"])
            for row in remaining:
                original = source[row["original_logical_order"] - 1]
                self.assertEqual(canonical_json_bytes(row["provider_payload"]), canonical_json_bytes(original["provider_payload"]))
                self.assertEqual(row["provider_payload_sha256"], original["provider_payload_sha256"])

    def test_29_no_new_judge_ids(self) -> None:
        audit = read_json("c4_real_judge_continuation_source_identity_audit_v1.json")
        self.assertEqual(audit["new_judge_ids_issued"], 0)
        self.assertFalse(audit["requests_rebuilt_from_condition_records"])

    def test_30_package_allowlists_and_counts(self) -> None:
        for shard, info in SHARDS.items():
            validation = validate_package_zip(info["continuation"])
            self.assertEqual(validation["status"], "PASS")
            self.assertEqual(validation["request_count"], len(info["orders"]))
            with ZipFile(info["continuation"]) as archive:
                self.assertEqual(set(archive.namelist()), ALLOWED_FILES)

    def test_31_prompt_and_schema_bytes_preserved(self) -> None:
        for info in SHARDS.values():
            with ZipFile(info["source"]) as source, ZipFile(info["continuation"]) as continuation:
                self.assertEqual(source.read("JUDGE_PROMPT.txt"), continuation.read("JUDGE_PROMPT.txt"))
                self.assertEqual(source.read("JUDGE_SCHEMA.json"), continuation.read("JUDGE_SCHEMA.json"))

    def test_32_package_timeout_and_attempt_caps(self) -> None:
        expected_caps = {"A": 96, "B": 22, "C": 36}
        for shard, info in SHARDS.items():
            with ZipFile(info["continuation"]) as archive:
                config = json.loads(archive.read("JUDGE_CONFIGURATION.json"))
                contract = json.loads(archive.read("EXECUTION_CONTRACT.json"))
            self.assertEqual(config["request_timeout_seconds"], 120.0)
            self.assertEqual(config["maximum_physical_attempts"], expected_caps[shard])
            self.assertEqual(contract["maximum_physical_attempts"], expected_caps[shard])
            self.assertTrue(contract["timeout_is_non_retryable"])

    def test_33_exact_authorization_binding(self) -> None:
        for info in SHARDS.values():
            with ZipFile(info["continuation"]) as archive:
                contract = json.loads(archive.read("EXECUTION_CONTRACT.json"))
            self.assertEqual(contract["authorization_environment_variable"], "C4_REAL_JUDGE_EXECUTION_AUTHORIZATION")
            self.assertEqual(contract["authorization_environment_value"], "AUTHORIZED_C4_REAL_JUDGE_CONTINUATION_R3")

    def test_34_timeout_is_nonretryable_under_mock_transport(self) -> None:
        package = SHARDS["B"]["continuation"]
        validation = validate_package_zip(package)
        with tempfile.TemporaryDirectory(prefix="j2d0-timeout-") as directory:
            root = Path(directory)
            auth = root / "auth.json"
            auth.write_text(json.dumps({
                "schema_version": AUTHORIZATION_SCHEMA_VERSION,
                "authorization_id": "MOCK-J2D0",
                "authorized_by": "offline-test",
                "authorized_at_utc": "2026-09-02T00:00:00Z",
                "package_id": validation["package_id"],
                "shard_id": validation["shard_id"],
                "request_count": validation["request_count"],
                "maximum_physical_attempts": validation["maximum_physical_attempts"],
                "package_zip_sha256": sha256_file(package),
                "blinded_judge_manifest_sha256": validation["blinded_judge_manifest_sha256"],
                "status": "AUTHORIZED",
            }), encoding="utf-8")
            client = TimeoutClient()
            clock = MockClock()
            with auth_gate(), self.assertRaises(RunnerError):
                execute_package(
                    package,
                    auth,
                    root / "output",
                    runtime_probe=lambda: {"mocked_transport": True},
                    client_factory=lambda: client,
                    monotonic=clock.monotonic,
                    sleeper=clock.sleep,
                    utc_now=lambda: "2026-09-02T00:00:00Z",
                )
            self.assertEqual(client.calls, 1)

    def test_35_no_sensitive_or_result_artifacts_in_packages(self) -> None:
        forbidden = (b"restricted_internal/", b"c4_real_i1_blinding_hmac_key.bin", b"expected_winner")
        for info in SHARDS.values():
            with ZipFile(info["continuation"]) as archive:
                names = set(archive.namelist())
                self.assertFalse(any("JUDGE_TERMINAL_JOURNAL" in name for name in names))
                for name in (
                    "README.md",
                    "BLINDED_JUDGE_REQUESTS.jsonl",
                    "JUDGE_CONFIGURATION.json",
                    "EXECUTION_CONTRACT.json",
                    "PACKAGE_SOURCE_HASHES.json",
                ):
                    data = archive.read(name)
                    self.assertTrue(all(token not in data for token in forbidden))

    def test_36_human_rating_intake_remains_unperformed(self) -> None:
        text = (HERE / "C4_REAL_HUMAN_RATING_INTAKE_READINESS.md").read_text()
        self.assertIn("NOT_FULLY_FROZEN_NO_INTAKE_PERFORMED", text)
        self.assertIn("No Human agreement calculation was performed", text)

    def test_37_ready_status_does_not_authorize_execution(self) -> None:
        text = (HERE / "STATUS.md").read_text()
        self.assertIn("READY_FOR_SEQUENTIAL_C4_REAL_JUDGE_CONTINUATION_EXECUTION_R3", text)
        self.assertIn("No continuation Package has been executed", text)

    def test_38_zero_call_boundaries_recorded(self) -> None:
        report = (HERE / "C4_REAL_J2D0_EXECUTION_REPORT.md").read_text()
        manifest = read_json("c4_real_judge_continuation_package_manifest_v1.json")
        self.assertIn("zero Provider/network calls", report)
        self.assertEqual(manifest["provider_calls"], 0)
        self.assertTrue(all(row["provider_calls"] == 0 for row in manifest["packages"].values()))


if __name__ == "__main__":
    unittest.main(verbosity=2)
