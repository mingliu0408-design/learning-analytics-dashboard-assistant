"""Standard-library tests for the repaired RQ1-C0-R2 harness."""

from __future__ import annotations

import builtins
import csv
import hashlib
import io
import json
import subprocess
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

from . import (
    AUTHORITY_BRIDGE_PATH,
    AUTHORITY_BRIDGE_SHA256,
    AUTHORITY_CANDIDATE_SHA256,
    FINAL_RESULT_RELATIVE,
    LABEL_UNIVERSE,
    LOCAL_ARTIFACTS_RELATIVE,
    LOCK_FILE_NAME,
    REPRESENTATIVE_SEED,
    ROOT,
    STATISTICAL_CONTRACT_SHA256,
    STATISTICAL_MODULE_SHA256,
)
from . import run_rq1c_final as final_cli
from .authority_contract import (
    AuthorityContractError,
    build_authority_contract,
    canonical_json_bytes,
    validate_authority_contract,
    validate_requested_asset_name,
    verify_authority_bridge,
)
from .checkpoint_loader import verify_all_checkpoints
from .contamination_audit import (
    FinalEvaluationInvalid,
    audit_contamination,
    build_reference_identity_sets,
    require_contamination_clear,
)
from .final_input_schema import (
    CONTAMINATION_NORMALISATION,
    SOURCE_NORMALISATION,
    FinalInputError,
    build_synthetic_final_csv,
    deterministic_normalised_query,
    parse_final_csv_bytes,
    source_track_a_normalised_query,
)
from .final_metrics import compute_fixed16_metrics
from .final_model_runner import run_dev_parity
from .sealed_access import (
    FinalResultTarget,
    SealedAccessError,
    consume_one_shot_asset,
    persist_result_atomically,
    preflight_final_result_path,
    run_authorised_one_shot,
    validate_execution_authority,
)
from .validate_rq1c_harness import (
    governed_text_leak_scan,
    run_synthetic_validation,
    verify_ignore_policy,
    verify_protected_sources,
    verify_statistical_contract,
)
from evaluation.learned_intent_ranking.lr4b_r1 import statistical_decision_contract as stats


def _rewrite_csv(raw_bytes: bytes, mutate: object) -> bytes:
    reader = csv.DictReader(
        io.StringIO(raw_bytes.decode("utf-8-sig"), newline="")
    )
    rows = [dict(row) for row in reader]
    mutate(rows)  # type: ignore[operator]
    output = io.StringIO(newline="")
    writer = csv.DictWriter(output, fieldnames=reader.fieldnames, lineterminator="\r\n")
    writer.writeheader()
    writer.writerows(rows)
    return b"\xef\xbb\xbf" + output.getvalue().encode("utf-8")


class _Reader:
    def __init__(self, handle: object, calls: dict[str, int]) -> None:
        self.handle = handle
        self.calls = calls

    def __enter__(self) -> "_Reader":
        return self

    def __exit__(self, *args: object) -> None:
        self.handle.close()  # type: ignore[attr-defined]

    def read(self) -> bytes:
        self.calls["read"] += 1
        return self.handle.read()  # type: ignore[attr-defined,no-any-return]


class RQ1C0R2HarnessTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.bridge, cls.candidate = verify_authority_bridge(AUTHORITY_BRIDGE_PATH)
        cls.contract = build_authority_contract(cls.bridge, cls.candidate)
        cls.synthetic_bytes = build_synthetic_final_csv()
        cls.records, cls.schema = parse_final_csv_bytes(
            cls.synthetic_bytes, cls.contract
        )
        cls.references = build_reference_identity_sets(ROOT)
        cls.synthetic_report = run_synthetic_validation(cls.contract)
        cls.dev_report = run_dev_parity(ROOT)

    def test_01_authority_bridge_identity_and_members_are_exact(self) -> None:
        self.assertEqual(self.bridge["zip_sha256"], AUTHORITY_BRIDGE_SHA256)
        self.assertEqual(
            self.bridge["candidate_manifest_sha256"], AUTHORITY_CANDIDATE_SHA256
        )
        self.assertEqual(self.bridge["member_count"], 3)
        self.assertEqual(self.bridge["status"], "PASS")

    def test_02_authority_contract_remains_safe_and_authorised(self) -> None:
        validate_authority_contract(self.contract)
        self.assertFalse(self.contract["contains_raw_final_gold"])
        self.assertFalse(self.contract["raw_asset_opened"])
        self.assertFalse(self.contract["raw_asset_statted"])
        self.assertFalse(self.contract["raw_asset_hashed"])

    def test_03_track_b_is_still_rejected_from_rq1(self) -> None:
        with self.assertRaises(AuthorityContractError):
            validate_requested_asset_name(
                "primary_v3_hybrid_context_human_review_researcher_final_v1.csv"
            )
        self.assertTrue(self.contract["track_b"]["track_b_excluded_from_rq1"])

    def test_04_source_normalisation_preserves_comma(self) -> None:
        self.assertEqual(source_track_a_normalised_query("  Hello, World  "), "hello, world")

    def test_05_source_normalisation_preserves_question_mark(self) -> None:
        self.assertEqual(source_track_a_normalised_query("Ready?"), "ready?")

    def test_06_source_normalisation_preserves_apostrophe(self) -> None:
        self.assertEqual(source_track_a_normalised_query("Student's"), "student's")

    def test_07_source_normalisation_preserves_full_stop(self) -> None:
        self.assertEqual(source_track_a_normalised_query("Done."), "done.")

    def test_08_source_normalisation_preserves_ascii_hyphen(self) -> None:
        self.assertEqual(source_track_a_normalised_query("Case-Fold"), "case-fold")

    def test_09_source_normalisation_maps_em_dash_only(self) -> None:
        self.assertEqual(source_track_a_normalised_query("Case\u2014Fold"), "case-fold")

    def test_10_source_and_contamination_normalisers_are_distinct(self) -> None:
        value = "  Student's,  Case?  "
        self.assertNotEqual(
            source_track_a_normalised_query(value),
            deterministic_normalised_query(value),
        )
        self.assertEqual(deterministic_normalised_query(value), "students case")
        self.assertEqual(
            SOURCE_NORMALISATION,
            "NFC_STRIP_CASEFOLD_EM_DASH_TO_ASCII_HYPHEN_PRESERVE_OTHER_PUNCTUATION",
        )
        self.assertEqual(
            CONTAMINATION_NORMALISATION,
            "NFKC_CASEFOLD_REMOVE_UNICODE_PUNCTUATION_COLLAPSE_WHITESPACE",
        )

    def test_11_source_normalisation_preserves_internal_whitespace(self) -> None:
        self.assertEqual(source_track_a_normalised_query("A   B"), "a   b")

    def test_12_synthetic_schema_distribution_and_canonical_none_are_exact(self) -> None:
        self.assertEqual(len(self.records), 128)
        self.assertEqual(self.schema["distribution"]["label_count"], 16)
        self.assertEqual(self.schema["distribution"]["per_label_count"], 8)
        self.assertEqual(self.schema["distribution"]["page_context"]["NONE"], 104)
        self.assertEqual(self.schema["distribution"]["contrast_role"]["NONE"], 64)
        self.assertTrue(all(row["current_page"] == "NONE" for row in self.records[:104]))
        self.assertTrue(all(row["contrast_role"] == "NONE" for row in self.records[64:]))

    def test_13_synthetic_raw_fixture_uses_blank_conventions(self) -> None:
        rows = list(
            csv.DictReader(
                io.StringIO(self.synthetic_bytes.decode("utf-8-sig"), newline="")
            )
        )
        self.assertEqual(
            sum(row["human_final_page_context"] == "" for row in rows), 104
        )
        self.assertEqual(sum(row["contrast_role"] == "" for row in rows), 64)
        self.assertNotIn("NONE", {row["contrast_role"] for row in rows})

    def test_14_synthetic_fixture_preserves_punctuation_normalisation(self) -> None:
        rows = list(
            csv.DictReader(
                io.StringIO(self.synthetic_bytes.decode("utf-8-sig"), newline="")
            )
        )
        for row in rows[:6]:
            self.assertEqual(
                row["normalised_query"],
                source_track_a_normalised_query(row["query"]),
            )
        values = [row["normalised_query"] for row in rows[:6]]
        for punctuation, value in zip((",", "?", "'", ".", "-", "-"), values, strict=True):
            self.assertIn(punctuation, value)
        self.assertNotIn("\u2014", values[5])

    def test_15_invalid_query_only_and_current_page_combinations_fail(self) -> None:
        query_only_nonblank = _rewrite_csv(
            self.synthetic_bytes,
            lambda rows: rows[0].__setitem__("human_final_page_context", "Overview"),
        )
        with self.assertRaises(FinalInputError):
            parse_final_csv_bytes(query_only_nonblank, self.contract)
        current_page_blank = _rewrite_csv(
            self.synthetic_bytes,
            lambda rows: rows[104].__setitem__("human_final_page_context", ""),
        )
        with self.assertRaises(FinalInputError):
            parse_final_csv_bytes(current_page_blank, self.contract)

    def test_16_invalid_blank_contrast_combinations_fail(self) -> None:
        blank_role_with_set = _rewrite_csv(
            self.synthetic_bytes,
            lambda rows: (
                rows[64].__setitem__("contrast_role", ""),
                rows[64].__setitem__("contrast_set_id", "SYN-CS-X"),
            ),
        )
        with self.assertRaises(FinalInputError):
            parse_final_csv_bytes(blank_role_with_set, self.contract)
        role_without_set = _rewrite_csv(
            self.synthetic_bytes,
            lambda rows: rows[0].__setitem__("contrast_set_id", ""),
        )
        with self.assertRaises(FinalInputError):
            parse_final_csv_bytes(role_without_set, self.contract)

    def test_17_literal_none_is_not_a_raw_blank_substitute(self) -> None:
        literal_none = _rewrite_csv(
            self.synthetic_bytes,
            lambda rows: (
                rows[64].__setitem__("contrast_role", "NONE"),
                rows[64].__setitem__("human_final_page_context", "NONE"),
            ),
        )
        with self.assertRaises(FinalInputError):
            parse_final_csv_bytes(literal_none, self.contract)

    def test_18_bom_and_crlf_remain_required(self) -> None:
        with self.assertRaises(FinalInputError):
            parse_final_csv_bytes(self.synthetic_bytes[3:], self.contract)
        with self.assertRaises(FinalInputError):
            parse_final_csv_bytes(
                self.synthetic_bytes.replace(b"\r\n", b"\n"), self.contract
            )

    def test_19_clean_synthetic_contamination_audit_passes(self) -> None:
        report = audit_contamination(self.records, self.references)
        require_contamination_clear(report)
        self.assertEqual(report["hard_failure_count"], 0)

    def test_20_overlap_is_fail_closed(self) -> None:
        copied = {
            role: {
                "exact_query_hashes": set(value["exact_query_hashes"]),
                "normalised_query_hashes": set(value["normalised_query_hashes"]),
                "family_ids": set(value["family_ids"]),
            }
            for role, value in self.references.items()
        }
        copied["DEV"]["exact_query_hashes"].add(
            hashlib.sha256(self.records[0]["query"].encode("utf-8")).hexdigest()
        )
        with self.assertRaises(FinalEvaluationInvalid):
            require_contamination_clear(audit_contamination(self.records, copied))

    def test_21_fixed_16_label_metrics_include_every_label(self) -> None:
        predictions = [
            {
                "record_id": row["record_id"],
                "gold_label": row["gold_label"],
                "ranking": (row["gold_label"],),
                "top1_label": row["gold_label"],
                "gold_rank": 1,
            }
            for row in self.records
        ]
        metrics = compute_fixed16_metrics(predictions)
        self.assertEqual(tuple(metrics["per_label"]), LABEL_UNIVERSE)
        self.assertEqual(metrics["macro_f1"], 1.0)

    def test_22_atomic_result_is_persisted_before_completed(self) -> None:
        calls = {"open": 0, "read": 0}
        states: list[str] = []
        with tempfile.TemporaryDirectory(prefix="rq1c-r2-persist-", dir="/private/tmp") as value:
            root = Path(value)
            asset = root / "fixture.csv"
            asset.write_bytes(self.synthetic_bytes)
            lock_path = root / "lock.json"
            target = FinalResultTarget(
                path=root / "result.json",
                temporary_path=root / ".result.json.tmp",
                relative_path="synthetic/result.json",
            )

            def opener(path: str, mode: str) -> _Reader:
                calls["open"] += 1
                return _Reader(builtins.open(path, mode), calls)

            from . import sealed_access as sealed_module
            original_write = sealed_module._write_lock_state

            def record_state(path: Path, payload: object) -> None:
                states.append(str(payload["state"]))  # type: ignore[index]
                original_write(path, payload)  # type: ignore[arg-type]

            with mock.patch.object(sealed_module, "_write_lock_state", side_effect=record_state):
                lock, result = consume_one_shot_asset(
                    asset_path=asset,
                    lock_path=lock_path,
                    expected_sha256=hashlib.sha256(self.synthetic_bytes).hexdigest(),
                    expected_size=len(self.synthetic_bytes),
                    expected_head="1" * 40,
                    parser=lambda value: parse_final_csv_bytes(value, self.contract)[0],
                    evaluator=lambda rows: {"status": "PASS", "count": len(rows)},
                    result_persister=lambda output: persist_result_atomically(
                        output, target
                    ),
                    opener=opener,
                )
            self.assertEqual(states, ["OPENED", "RESULT_PERSISTED", "COMPLETED"])
            self.assertTrue(target.path.is_file())
            self.assertEqual(lock["state"], "COMPLETED")
            self.assertTrue(lock["persisted"])
            self.assertEqual(lock["result_size_bytes"], target.path.stat().st_size)
            self.assertEqual(
                lock["result_sha256"], hashlib.sha256(target.path.read_bytes()).hexdigest()
            )
            self.assertEqual(result["count"], 128)
            self.assertEqual(calls, {"open": 1, "read": 1})

    def test_23_persistence_failure_preserves_noncompleted_lock(self) -> None:
        with tempfile.TemporaryDirectory(prefix="rq1c-r2-persist-fail-", dir="/private/tmp") as value:
            root = Path(value)
            asset = root / "fixture.csv"
            asset.write_bytes(self.synthetic_bytes)
            lock_path = root / "lock.json"
            with self.assertRaises(OSError):
                consume_one_shot_asset(
                    asset_path=asset,
                    lock_path=lock_path,
                    expected_sha256=hashlib.sha256(self.synthetic_bytes).hexdigest(),
                    expected_size=len(self.synthetic_bytes),
                    expected_head="2" * 40,
                    parser=lambda value: value,
                    evaluator=lambda value: {"status": "PASS"},
                    result_persister=lambda output: (_ for _ in ()).throw(
                        OSError("synthetic persistence failure")
                    ),
                )
            lock = json.loads(lock_path.read_text(encoding="utf-8"))
            self.assertEqual(lock["state"], "FAILED_RESULT_PERSISTENCE")
            self.assertFalse(lock["persisted"])
            self.assertFalse(lock["retry_permitted"])
            self.assertNotEqual(lock["state"], "COMPLETED")

    def test_24_existing_lock_refuses_retry_before_open(self) -> None:
        calls = {"open": 0, "read": 0}
        with tempfile.TemporaryDirectory(prefix="rq1c-r2-lock-refusal-", dir="/private/tmp") as value:
            root = Path(value)
            asset = root / "fixture.csv"
            asset.write_bytes(self.synthetic_bytes)
            lock_path = root / "lock.json"
            lock_path.write_text("{}", encoding="utf-8")

            def opener(path: str, mode: str) -> _Reader:
                calls["open"] += 1
                return _Reader(builtins.open(path, mode), calls)

            with self.assertRaises(SealedAccessError):
                consume_one_shot_asset(
                    asset_path=asset,
                    lock_path=lock_path,
                    expected_sha256=hashlib.sha256(self.synthetic_bytes).hexdigest(),
                    expected_size=len(self.synthetic_bytes),
                    expected_head="3" * 40,
                    parser=lambda value: value,
                    evaluator=lambda value: {"status": "UNREACHABLE"},
                    result_persister=lambda output: {},
                    opener=opener,
                )
            self.assertEqual(calls, {"open": 0, "read": 0})

    def test_25_prearm_dependency_failure_occurs_before_lock_and_open(self) -> None:
        calls = {"open": 0}
        with tempfile.TemporaryDirectory(prefix="rq1c-r2-prearm-fail-", dir="/private/tmp") as value:
            root = Path(value)

            def opener(*args: object, **kwargs: object) -> object:
                calls["open"] += 1
                raise AssertionError("raw opener must be unreachable")

            def fail_prearm(path: Path, head: str) -> object:
                raise RuntimeError("synthetic pre-arm dependency failure")

            with self.assertRaisesRegex(RuntimeError, "pre-arm dependency"):
                run_authorised_one_shot(
                    execute_final=True,
                    expected_harness_head="4" * 40,
                    authority_contract_argument=(
                        "evaluation/learned_intent_ranking/rq1c/"
                        "rq1c_final_gold_authority_contract_v1.json"
                    ),
                    environment={"RQ1C_FINAL_ACCESS_AUTHORISED": "YES"},
                    evaluator=lambda rows, bundle: {"status": "UNREACHABLE"},
                    root=root,
                    runtime_preparer=fail_prearm,  # type: ignore[arg-type]
                    opener=opener,  # type: ignore[arg-type]
                )
            lock_path = root.joinpath(*LOCAL_ARTIFACTS_RELATIVE.parts) / LOCK_FILE_NAME
            self.assertFalse(lock_path.exists())
            self.assertEqual(calls["open"], 0)

    def test_26_preexisting_result_refuses_before_lock_and_open(self) -> None:
        calls = {"open": 0}
        with tempfile.TemporaryDirectory(prefix="rq1c-r2-result-refusal-", dir="/private/tmp") as value:
            root = Path(value)
            target = root.joinpath(*FINAL_RESULT_RELATIVE.parts)
            target.parent.mkdir(parents=True)
            target.write_text("pre-existing", encoding="utf-8")
            bundle = SimpleNamespace(
                authority_contract=self.contract,
                reference_identity_sets=self.references,
            )

            def opener(*args: object, **kwargs: object) -> object:
                calls["open"] += 1
                raise AssertionError("raw opener must be unreachable")

            completed = subprocess.CompletedProcess(
                args=["git", "check-ignore"], returncode=0, stdout=b"", stderr=b""
            )
            from . import sealed_access as sealed_module
            with mock.patch.object(sealed_module, "_git", return_value=completed):
                with self.assertRaisesRegex(
                    SealedAccessError,
                    "BLOCKED_RQ1_C0_R2_RESULT_PATH_ALREADY_EXISTS",
                ):
                    run_authorised_one_shot(
                        execute_final=True,
                        expected_harness_head="5" * 40,
                        authority_contract_argument=(
                            "evaluation/learned_intent_ranking/rq1c/"
                            "rq1c_final_gold_authority_contract_v1.json"
                        ),
                        environment={"RQ1C_FINAL_ACCESS_AUTHORISED": "YES"},
                        evaluator=lambda rows, runtime: {"status": "UNREACHABLE"},
                        root=root,
                        runtime_preparer=lambda path, head: bundle,  # type: ignore[arg-type]
                        opener=opener,  # type: ignore[arg-type]
                    )
            lock_path = root.joinpath(*LOCAL_ARTIFACTS_RELATIVE.parts) / LOCK_FILE_NAME
            self.assertFalse(lock_path.exists())
            self.assertEqual(calls["open"], 0)

    def test_27_output_preflight_and_atomic_write_are_local_only(self) -> None:
        with tempfile.TemporaryDirectory(prefix="rq1c-r2-output-preflight-", dir="/private/tmp") as value:
            root = Path(value)
            completed = subprocess.CompletedProcess(
                args=["git", "check-ignore"], returncode=0, stdout=b"", stderr=b""
            )
            from . import sealed_access as sealed_module
            with mock.patch.object(sealed_module, "_git", return_value=completed):
                target = preflight_final_result_path(root)
            self.assertFalse(target.path.exists())
            self.assertFalse(target.temporary_path.exists())
            metadata = persist_result_atomically({"status": "PASS"}, target)
            self.assertTrue(metadata["persisted"])
            self.assertEqual(metadata["result_relative_path"], FINAL_RESULT_RELATIVE.as_posix())

    def test_28_cli_performs_no_postcompleted_result_write(self) -> None:
        lock = {
            "state": "COMPLETED",
            "result_relative_path": FINAL_RESULT_RELATIVE.as_posix(),
            "result_sha256": "a" * 64,
        }
        output = io.StringIO()
        with mock.patch.object(
            final_cli, "run_authorised_one_shot", return_value=(lock, {"ignored": True})
        ), mock.patch.object(
            Path,
            "write_bytes",
            side_effect=AssertionError("CLI must not write after COMPLETED"),
        ), redirect_stdout(output):
            code = final_cli.main(
                [
                    "--execute-final",
                    "--expected-harness-head",
                    "6" * 40,
                    "--authority-contract",
                    "evaluation/learned_intent_ranking/rq1c/"
                    "rq1c_final_gold_authority_contract_v1.json",
                ]
            )
        payload = json.loads(output.getvalue())
        self.assertEqual(code, 0)
        self.assertEqual(payload["status"], "COMPLETED")
        self.assertEqual(payload["result_sha256"], "a" * 64)

    def test_29_triple_authority_refuses_missing_environment(self) -> None:
        with self.assertRaises(SealedAccessError):
            validate_execution_authority(
                execute_final=True,
                expected_harness_head="7" * 40,
                authority_contract_argument=(
                    "evaluation/learned_intent_ranking/rq1c/"
                    "rq1c_final_gold_authority_contract_v1.json"
                ),
                environment={},
                root=ROOT,
            )

    def test_30_checkpoint_preflight_verifies_all_five(self) -> None:
        report = verify_all_checkpoints(ROOT)
        self.assertEqual(report["checkpoint_count"], 5)
        self.assertEqual(report["representative_seed"], REPRESENTATIVE_SEED)
        self.assertTrue(report["all_checkpoints_verified"])

    def test_31_k0_c0_and_all_m64_dev_parity_remain_exact(self) -> None:
        self.assertEqual(self.dev_report["k0"]["semantic_loader_call_count"], 0)
        self.assertEqual(self.dev_report["c0"]["ranking_identity_match_count"], 84)
        self.assertTrue(self.dev_report["c0"]["metrics_exact_match"])
        for row in self.dev_report["m64_v0"]["seeds"]:
            self.assertEqual(row["ranking_identity_match_count"], 84)
            self.assertTrue(row["metrics_exact_match"])
        self.assertEqual(
            self.dev_report["m64_v0"]["representative_seed"], REPRESENTATIVE_SEED
        )

    def test_32_statistical_contract_hashes_are_unchanged(self) -> None:
        report = verify_statistical_contract(ROOT)
        self.assertEqual(
            report["statistical_contract_json"]["sha256"],
            STATISTICAL_CONTRACT_SHA256,
        )
        self.assertEqual(
            report["statistical_contract_module"]["sha256"],
            STATISTICAL_MODULE_SHA256,
        )

    def test_33_protected_sources_and_ignore_policy_pass(self) -> None:
        self.assertTrue(verify_protected_sources(ROOT)["protected_sources_unchanged"])
        self.assertTrue(verify_ignore_policy()["all_ignored"])

    def test_34_synthetic_double_build_is_byte_identical(self) -> None:
        first = run_synthetic_validation(self.contract)
        second = run_synthetic_validation(self.contract)
        self.assertEqual(canonical_json_bytes(first), canonical_json_bytes(second))

    def test_35_no_network_provider_real_final_or_real_lock(self) -> None:
        self.assertFalse(self.synthetic_report["network_access"])
        self.assertEqual(self.synthetic_report["provider_calls"], 0)
        self.assertFalse(self.synthetic_report["real_final_asset_used"])
        self.assertFalse(self.synthetic_report["real_lock_created"])
        lock_path = ROOT.joinpath(*LOCAL_ARTIFACTS_RELATIVE.parts) / LOCK_FILE_NAME
        self.assertFalse(lock_path.exists())

    def test_36_any_failed_required_gate_keeps_c0(self) -> None:
        decision = stats.final_selection_gate(
            primary_mrr_significance=True,
            top1_direction=True,
            macro_f1_tolerance=False,
            weak_class=True,
            seed_robustness=True,
            no_final_gold_tuning=True,
            no_taxonomy_change=True,
        )
        self.assertEqual(decision, "C0_REMAINS_SELECTED")

    def test_37_governed_text_scan_stays_clear(self) -> None:
        self.assertEqual(governed_text_leak_scan()["match_count"], 0)


if __name__ == "__main__":
    unittest.main()
