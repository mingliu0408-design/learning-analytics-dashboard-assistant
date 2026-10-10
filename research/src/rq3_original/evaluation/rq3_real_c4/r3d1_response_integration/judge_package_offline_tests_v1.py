#!/usr/bin/env python3
"""Offline-only tests embedded in each C4 REAL Judge Shard Package."""

from __future__ import annotations

import json
from pathlib import Path
import tempfile
import unittest

from judge_execution_runner_v1 import RunnerError, execute_shard
from judge_result_parser_v1 import JudgeResultError, SCORE_FIELDS, parse_judge_result
from validate_package import validate_package_dir


PACKAGE_DIR = Path(__file__).resolve().parent


def first_request() -> tuple[dict, dict]:
    row = json.loads(
        next(
            line
            for line in (PACKAGE_DIR / "BLINDED_JUDGE_REQUESTS.jsonl")
            .read_text(encoding="utf-8")
            .splitlines()
            if line.strip()
        )
    )
    content = row["provider_payload"]["messages"][0]["content"]
    request = json.loads(
        content.split("BEGIN_BLIND_JUDGE_REQUEST_JSON\n", 1)[1].rsplit(
            "\nEND_BLIND_JUDGE_REQUEST_JSON", 1
        )[0]
    )
    return row, request


def valid_transport_result(request: dict) -> dict:
    scores: dict[str, str] = {}
    rationales: dict[str, str] = {}
    numeric: list[int] = []
    for criterion, field in SCORE_FIELDS.items():
        if request["frozen_applicability_map"]["criteria"][criterion]:
            scores[field] = "4"
            numeric.append(4)
        else:
            scores[field] = "NA"
        rationales[field] = "Offline parser fixture rationale."
    return {
        "response_blind_id": request["response_blind_id"],
        **scores,
        "evidence_faithfulness": "4",
        "unsupported_claim_count": "0",
        "overall_applicable_mean": str(sum(numeric) / len(numeric)),
        "criterion_rationales": rationales,
        "schema_version": "rq3-judge-response-v2-transport",
    }


class PackageOfflineTests(unittest.TestCase):
    def test_01_package_validator(self) -> None:
        self.assertEqual(validate_package_dir(PACKAGE_DIR)["status"], "PASS")

    def test_02_request_ids_and_configuration(self) -> None:
        row, request = first_request()
        self.assertTrue(row["logical_judge_request_id"].startswith("C4J1-"))
        self.assertEqual(row["judge_result_blind_id"], request["response_blind_id"])
        self.assertEqual(row["provider_payload"]["max_tokens"], 2048)

    def test_03_parser_recomputes_semantic_mean(self) -> None:
        row, request = first_request()
        parsed = parse_judge_result(
            valid_transport_result(request),
            request["frozen_applicability_map"],
            expected_judge_result_blind_id=row["judge_result_blind_id"],
        )
        self.assertEqual(parsed["schema_version"], "rq3-judge-response-v1")
        self.assertEqual(parsed["overall_applicable_mean"], 4.0)

    def test_04_duplicate_keys_and_applicability_fail_closed(self) -> None:
        _row, request = first_request()
        with self.assertRaises(JudgeResultError):
            parse_judge_result(
                '{"response_blind_id":"R3B-00000000000000000000",'
                '"response_blind_id":"R3B-11111111111111111111"}',
                request["frozen_applicability_map"],
            )
        invalid = valid_transport_result(request)
        for criterion, field in SCORE_FIELDS.items():
            if not request["frozen_applicability_map"]["criteria"][criterion]:
                invalid[field] = "3"
                break
        else:
            first_field = next(iter(SCORE_FIELDS.values()))
            invalid[first_field] = "NA"
        with self.assertRaises(JudgeResultError):
            parse_judge_result(invalid, request["frozen_applicability_map"])

    def test_05_runner_refuses_existing_output_without_network(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            with self.assertRaises(RunnerError):
                execute_shard(PACKAGE_DIR, Path(tmp), enforce_runtime=False)


if __name__ == "__main__":
    unittest.main(verbosity=2)

