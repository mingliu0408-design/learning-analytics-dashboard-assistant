from __future__ import annotations

from collections import Counter
import hashlib
import json
import os
from pathlib import Path
import socket
import stat
import subprocess
import tempfile
from types import SimpleNamespace
import unittest
from unittest import mock
import zipfile

from evaluation.rq3_real_c4.i1_route_integration.build_generation_packages_v2 import (
    _package_rows,
    _read_unique_rows,
    run_package_tests,
    write_package_directory,
    write_zip,
)
from evaluation.rq3_real_c4.i1_route_integration.build_i1_r1_artifacts import (
    _opaque_id,
    _v2_substantive_item_from_v1,
)
from evaluation.rq3_real_c4.i1_route_integration.generation_execution_runner_v2 import (
    AUTHORIZATION_ENVIRONMENT_VALUE,
    PACKAGE_FILES,
    RunnerFailure,
    canonical_bytes,
    execute_package,
)
from evaluation.rq3_real_c4.i1_route_integration.generation_package_validator_v2 import (
    ALLOWED_FILES,
    validate,
    validate_zip,
)
from evaluation.rq3_real_c4.i1_route_integration.i1_r1_common import (
    AUDIT_PHRASES,
    GENERATION_CONFIGURATION_V2_SHA256,
    GENERATION_PROMPT_SHA256,
    GENERATION_SCHEMA_V2_SHA256,
    HERE,
    HMAC_KEY_COMMITMENT,
    NEW_PACKAGE_PATHS,
    OLD_PACKAGE_PATHS,
    OLD_PACKAGE_SHA256,
    RESTRICTED,
    ROOT,
    SCIENTIFIC_SHA256,
    V1_RESTRICTED_SHA256,
    V1_REQUEST_ARTIFACT_SHA256,
    V2_PROHIBITED_MESSAGE_KEYS,
    V2_PROHIBITED_TEXT,
    load_csv,
    load_jsonl,
    sha256_file,
)
from evaluation.rq3_real_c4.i1_route_integration.i1_common import SOURCE_PATHS


V1_MANIFEST = HERE / "c4_real_unique_generation_request_manifest_frozen_v1.jsonl"
V2_MANIFEST = HERE / "c4_real_unique_generation_request_manifest_frozen_v2.jsonl"
V1_REGISTRY = RESTRICTED / "c4_real_condition_generation_payload_registry_frozen_v1.jsonl"
V2_REGISTRY = RESTRICTED / "c4_real_condition_generation_payload_registry_frozen_v2.jsonl"
EXPECTED_OLD_MEMBERS = {
    "README.md",
    "BLINDED_REQUESTS.jsonl",
    "GENERATION_PROMPT.txt",
    "GENERATION_SCHEMA.json",
    "GENERATION_CONFIGURATION.json",
    "generation_runner.py",
    "validate_package.py",
    "test_package.py",
    "EXECUTION_CONTRACT.json",
    "PACKAGE_SOURCE_HASHES.json",
}
OUTPUT_FILES = {
    "GENERATION_PREFLIGHT_RECEIPT.json",
    "GENERATION_ATTEMPT_JOURNAL.jsonl",
    "GENERATION_TERMINAL_JOURNAL.jsonl",
    "GENERATION_ERROR_REGISTRY.jsonl",
    "GENERATION_EXECUTION_STATUS.json",
    "GENERATION_USAGE_AND_COST.json",
    "GENERATION_EXECUTION_REPORT.md",
}


def _user_message(payload: dict) -> dict:
    return json.loads(payload["messages"][1]["content"])


def _walk_keys(value: object, counts: Counter[str]) -> None:
    if isinstance(value, dict):
        for key, nested in value.items():
            counts[str(key)] += 1
            _walk_keys(nested, counts)
    elif isinstance(value, list):
        for nested in value:
            _walk_keys(nested, counts)


def _runtime_identity() -> dict:
    return {
        "python_version": "3.13.5",
        "python_path": "/opt/anaconda3/bin/python3",
        "openai_sdk_version": "1.109.1",
        "automatic_sdk_retries": 0,
        "api_key_presence_checked_only": True,
        "api_key_value_recorded": False,
    }


def _response(
    content: str,
    *,
    model: str = "gpt-4o-mini-2024-07-18",
    prompt_tokens: int = 10,
    completion_tokens: int = 4,
    cached_tokens: int | None = 2,
) -> SimpleNamespace:
    details = (
        SimpleNamespace(cached_tokens=cached_tokens) if cached_tokens is not None else None
    )
    return SimpleNamespace(
        id="chatcmpl-mocked",
        model=model,
        system_fingerprint="fp_mocked",
        usage=SimpleNamespace(
            prompt_tokens=prompt_tokens,
            completion_tokens=completion_tokens,
            total_tokens=prompt_tokens + completion_tokens,
            prompt_tokens_details=details,
        ),
        choices=[
            SimpleNamespace(
                finish_reason="stop",
                message=SimpleNamespace(content=content, refusal=None),
            )
        ],
    )


class _SequencedCreate:
    def __init__(self, events: list[object]) -> None:
        self.events = list(events)
        self.payload_bytes: list[bytes] = []

    def __call__(self, **payload: object) -> object:
        self.payload_bytes.append(canonical_bytes(payload))
        if not self.events:
            raise AssertionError("mock provider received an unexpected call")
        event = self.events.pop(0)
        if isinstance(event, BaseException):
            raise event
        return event


class _FakeClient:
    def __init__(self, events: list[object]) -> None:
        self.create = _SequencedCreate(events)
        self.chat = SimpleNamespace(completions=SimpleNamespace(create=self.create))


class _Tick:
    def __init__(self) -> None:
        self.value = 10.0

    def __call__(self) -> float:
        self.value += 0.01
        return self.value


def _jsonl(path: Path) -> list[dict]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line]


def _make_runner_package(base: Path, request_count: int = 1) -> dict[str, Path]:
    source_rows = _read_unique_rows()[:request_count]
    rows = _package_rows(source_rows)
    package_root = base / "package"
    package_root.mkdir()
    manifest = package_root / "BLINDED_REQUESTS.jsonl"
    manifest.write_text(
        "".join(json.dumps(row, ensure_ascii=False, sort_keys=True) + "\n" for row in rows),
        encoding="utf-8",
    )
    package_id = "C4_REAL_GENERATION_SHARD_A_R2_20260901"
    contract = {
        "package_id": package_id,
        "shard": "A",
        "status": "PREPARED_NOT_AUTHORIZED",
        "request_count": request_count,
        "maximum_physical_attempts": request_count * 2,
    }
    (package_root / "EXECUTION_CONTRACT.json").write_text(
        json.dumps(contract, sort_keys=True) + "\n", encoding="utf-8"
    )
    runner_source = (HERE / "generation_execution_runner_v2.py").read_bytes()
    fixed_members = {
        "GENERATION_PROMPT.txt": SOURCE_PATHS["generation_prompt"].read_bytes(),
        "GENERATION_SCHEMA.json": (
            HERE / "c4_real_generation_schema_v2_provider_compatible.json"
        ).read_bytes(),
        "GENERATION_CONFIGURATION.json": (
            HERE / "c4_real_generation_configuration_frozen_v2.json"
        ).read_bytes(),
        "generation_execution_runner_v2.py": runner_source,
    }
    for name, content in fixed_members.items():
        (package_root / name).write_bytes(content)
    for name in PACKAGE_FILES - {
        "BLINDED_REQUESTS.jsonl",
        "EXECUTION_CONTRACT.json",
        "PACKAGE_SOURCE_HASHES.json",
        *fixed_members,
    }:
        (package_root / name).write_bytes((name + "\n").encode("utf-8"))
    manifest_hash = sha256_file(manifest)
    member_hashes = {
        name: sha256_file(package_root / name)
        for name in PACKAGE_FILES - {"PACKAGE_SOURCE_HASHES.json"}
    }
    (package_root / "PACKAGE_SOURCE_HASHES.json").write_text(
        json.dumps(
            {
                "package_id": package_id,
                "shard": "A",
                "blinded_manifest_sha256": manifest_hash,
                "member_sha256_excluding_self": member_hashes,
            },
            sort_keys=True,
        )
        + "\n",
        encoding="utf-8",
    )
    package_zip = base / "package.zip"
    with zipfile.ZipFile(package_zip, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        for name in sorted(PACKAGE_FILES):
            archive.write(package_root / name, arcname=name)
    authorization = {
        "schema_version": "c4-real-response-generation-authorization-r2",
        "authorization_id": "AUTH-MOCK-R2",
        "authorized_by": "offline-test-fixture",
        "authorized_at_utc": "2026-09-01T00:00:00Z",
        "package_id": package_id,
        "shard": "A",
        "request_count": request_count,
        "maximum_physical_attempts": request_count * 2,
        "package_sha256": sha256_file(package_zip),
        "blinded_manifest_sha256": manifest_hash,
        "status": "AUTHORIZED",
    }
    authorization_path = base / "authorization.json"
    authorization_path.write_text(json.dumps(authorization, sort_keys=True) + "\n", encoding="utf-8")
    return {
        "package_root": package_root,
        "manifest": manifest,
        "package_zip": package_zip,
        "authorization": authorization_path,
    }


def _execute_fixture(
    fixture: dict[str, Path],
    output: Path,
    client: _FakeClient,
    *,
    runtime_checker=_runtime_identity,
) -> int:
    tick = _Tick()
    with mock.patch.dict(
        os.environ,
        {"C4_REAL_RESPONSE_GENERATION_AUTHORIZATION": AUTHORIZATION_ENVIRONMENT_VALUE},
    ), mock.patch.object(socket, "socket", side_effect=AssertionError("real network forbidden")):
        return execute_package(
            fixture["manifest"],
            fixture["authorization"],
            fixture["package_zip"],
            output,
            package_root=fixture["package_root"],
            runtime_checker=runtime_checker,
            client_factory=lambda: client,
            sleeper=lambda _seconds: None,
            monotonic=tick,
            now=lambda: "2026-09-01T00:00:00Z",
        )


class FrozenScientificPreservationTests(unittest.TestCase):
    def test_all_scientific_and_v1_source_hashes_are_unchanged(self) -> None:
        for name, expected in SCIENTIFIC_SHA256.items():
            self.assertEqual(sha256_file(HERE / name), expected, name)
        for name, expected in V1_REQUEST_ARTIFACT_SHA256.items():
            self.assertEqual(sha256_file(HERE / name), expected, name)
        for name, expected in V1_RESTRICTED_SHA256.items():
            self.assertEqual(sha256_file(RESTRICTED / name), expected, name)
        self.assertEqual(sha256_file(SOURCE_PATHS["generation_prompt"]), GENERATION_PROMPT_SHA256)
        self.assertEqual(
            sha256_file(HERE / "c4_real_generation_schema_v2_provider_compatible.json"),
            GENERATION_SCHEMA_V2_SHA256,
        )
        self.assertEqual(
            sha256_file(HERE / "c4_real_generation_configuration_frozen_v2.json"),
            GENERATION_CONFIGURATION_V2_SHA256,
        )

    def test_condition_route_and_analysis_identities_are_unchanged(self) -> None:
        mechanisms = load_jsonl(HERE / "c4_real_condition_mechanism_records_frozen_v1.jsonl")
        registry = load_jsonl(V2_REGISTRY)
        self.assertEqual(len(mechanisms), 558)
        self.assertEqual(len(registry), 558)
        self.assertEqual(Counter(row["analysis_tier"] for row in mechanisms), {"PRIMARY": 372, "TARGETED_SECONDARY": 186})
        self.assertEqual(
            {(row["scenario_id"], row["mode"]) for row in mechanisms},
            {(row["scenario_id"], row["mode_id"]) for row in registry},
        )
        by_key = {(row["scenario_id"], row["mode"]): row for row in mechanisms}
        for row in registry:
            source = by_key[(row["scenario_id"], row["mode_id"])]
            self.assertEqual(row["route_signature"], source["route_signature"])
            self.assertEqual(row["activation_mask"], source["activation_mask"])
            self.assertEqual(row["compiled_evidence_sha256"], source["compiled_evidence_sha256"])
            self.assertEqual(row["planner_result_sha256"], source["planner_result_sha256"])

    def test_original_packages_are_hash_preserved_and_unexecuted(self) -> None:
        for shard in "ABC":
            path = OLD_PACKAGE_PATHS[shard]
            self.assertEqual(sha256_file(path), OLD_PACKAGE_SHA256[shard])
            with zipfile.ZipFile(path) as archive:
                self.assertEqual(set(archive.namelist()), EXPECTED_OLD_MEMBERS)
                self.assertFalse(
                    any(
                        token in name.upper()
                        for name in archive.namelist()
                        for token in ("RESPONSE", "ATTEMPT_JOURNAL", "TERMINAL_JOURNAL", "PREFLIGHT_RECEIPT")
                    )
                )

    def test_existing_hmac_key_and_v1_mappings_are_preserved(self) -> None:
        key_path = RESTRICTED / "c4_real_i1_blinding_hmac_key.bin"
        key = key_path.read_bytes()
        self.assertEqual(len(key), 32)
        self.assertEqual(stat.S_IMODE(key_path.stat().st_mode), 0o600)
        self.assertEqual(hashlib.sha256(key).hexdigest(), HMAC_KEY_COMMITMENT)
        ignored = subprocess.run(
            ["git", "check-ignore", key_path.relative_to(ROOT).as_posix()],
            cwd=ROOT,
            check=True,
            capture_output=True,
            text=True,
        ).stdout.strip()
        self.assertTrue(ignored)
        tracked = set(
            subprocess.run(
                ["git", "ls-files"],
                cwd=ROOT,
                check=True,
                capture_output=True,
                text=True,
            ).stdout.splitlines()
        )
        self.assertNotIn(key_path.relative_to(ROOT).as_posix(), tracked)


class PayloadRepairTests(unittest.TestCase):
    def test_independent_v1_hygiene_counts(self) -> None:
        rows = load_jsonl(V1_MANIFEST)
        self.assertEqual(len(rows), 197)
        phrase_payloads = Counter()
        phrase_occurrences = Counter()
        schema_labels = Counter()
        duplicate_payloads = 0
        extra_duplicates = Counter()
        duplicate_hashes: set[str] = set()
        for row in rows:
            user = _user_message(row["provider_payload"])
            serialized = json.dumps(user, ensure_ascii=False, sort_keys=True)
            for phrase in AUDIT_PHRASES:
                count = serialized.count(phrase)
                phrase_occurrences[phrase] += count
                phrase_payloads[phrase] += count > 0
            schema_labels[user["evidence"]["schema_version"]] += 1
            seen: dict[str, set[bytes]] = {"DASHBOARD": set(), "COURSE_RAG": set(), "LEARNER_MEMORY": set()}
            payload_has_duplicate = False
            for item in user["evidence"]["evidence"]:
                kind = item["source_kind"]
                encoded = canonical_bytes(item)
                if encoded in seen[kind]:
                    extra_duplicates[kind] += 1
                    duplicate_hashes.add(hashlib.sha256(encoded).hexdigest())
                    payload_has_duplicate = True
                else:
                    seen[kind].add(encoded)
            duplicate_payloads += payload_has_duplicate
        expected = {
            "Reviewed output-level Dashboard evidence": 116,
            "raw DataFrames were not available in I0": 116,
            "TRACK_M_RESEARCH_ONLY_NOT_C4_INTEGRATED": 37,
            "P3_GATE_NOT_EXECUTED_IN_TRACK_M": 37,
            "NO_ELIGIBLE_ACTIVE_MEMORY": 31,
            "Frozen legacy lexical scoring": 41,
            "FROZEN_OUTPUT_LEVEL_EVIDENCE_PACK": 116,
            "FROZEN_STRUCTURED_OUTPUT": 176,
            "FROZEN_TYPED_EMPTY_OUTPUT_LEVEL_PACK": 21,
        }
        self.assertEqual(dict(phrase_payloads), expected)
        self.assertEqual(dict(phrase_occurrences), expected)
        self.assertEqual(schema_labels, {"c4-real-provider-evidence-projection-v1": 197})
        self.assertEqual(duplicate_payloads, 20)
        self.assertEqual(extra_duplicates, {"COURSE_RAG": 32})
        self.assertEqual(len(duplicate_hashes), 9)

    def test_v2_projection_removes_internal_metadata_and_exact_duplicates(self) -> None:
        rows = load_jsonl(V2_MANIFEST)
        self.assertEqual(len(rows), 197)
        for row in rows:
            user = _user_message(row["provider_payload"])
            envelope = user["evidence"]
            self.assertEqual(set(envelope), {"evidence", "availability_notes"})
            self.assertIsNone(V2_PROHIBITED_TEXT.search(json.dumps(user, ensure_ascii=False)))
            key_counts: Counter[str] = Counter()
            _walk_keys(envelope, key_counts)
            self.assertFalse(V2_PROHIBITED_MESSAGE_KEYS & set(key_counts))
            by_kind: dict[str, set[bytes]] = {"DASHBOARD": set(), "COURSE_RAG": set(), "LEARNER_MEMORY": set()}
            for item in envelope["evidence"]:
                kind = {
                    "dashboard_activity": "DASHBOARD",
                    "current_page_context": "DASHBOARD",
                    "course_material": "COURSE_RAG",
                    "learner_memory": "LEARNER_MEMORY",
                }[item["source"]]
                encoded = canonical_bytes(item)
                self.assertNotIn(encoded, by_kind[kind])
                by_kind[kind].add(encoded)

    def test_typed_absence_and_module_off_semantics(self) -> None:
        rows = load_jsonl(V2_REGISTRY)
        counts = Counter()
        for row in rows:
            user = _user_message(row["provider_payload"])
            sources = {item["source"] for item in user["evidence"]["evidence"]}
            notes = set(user["evidence"]["availability_notes"])
            activated = row["activation_mask"]
            rag_note = "No sufficiently relevant course material was found for this request."
            memory_note = "No relevant earlier-session learner information was available for this request."
            if not activated["rag"]:
                self.assertNotIn("course_material", sources)
                self.assertNotIn(rag_note, notes)
                counts["rag_off"] += 1
            elif "course_material" not in sources:
                self.assertIn(rag_note, notes)
                counts["rag_no_result"] += 1
            if not activated["memory"]:
                self.assertNotIn("learner_memory", sources)
                self.assertNotIn(memory_note, notes)
                counts["memory_off"] += 1
            elif "learner_memory" not in sources:
                self.assertIn(memory_note, notes)
                counts["memory_no_match"] += 1
        self.assertEqual(
            counts,
            {"rag_off": 474, "rag_no_result": 36, "memory_off": 482, "memory_no_match": 68},
        )

    def test_substantive_evidence_query_history_and_planning_are_preserved(self) -> None:
        v1 = {(row["scenario_id"], row["mode_id"]): row for row in load_jsonl(V1_REGISTRY)}
        v2 = {(row["scenario_id"], row["mode_id"]): row for row in load_jsonl(V2_REGISTRY)}
        self.assertEqual(set(v1), set(v2))
        removed_by_kind = Counter()
        for key in v1:
            old_user = _user_message(v1[key]["provider_payload"])
            new_user = _user_message(v2[key]["provider_payload"])
            for field in ("current_query", "current_page", "visible_conversation_history", "planning_support"):
                self.assertEqual(old_user[field], new_user[field], (key, field))
            expected: dict[str, set[bytes]] = {"DASHBOARD": set(), "COURSE_RAG": set(), "LEARNER_MEMORY": set()}
            old_occurrences = Counter()
            for item in old_user["evidence"]["evidence"]:
                kind = item["source_kind"]
                expected[kind].add(canonical_bytes(_v2_substantive_item_from_v1(item)))
                old_occurrences[kind] += 1
            actual: dict[str, set[bytes]] = {"DASHBOARD": set(), "COURSE_RAG": set(), "LEARNER_MEMORY": set()}
            new_occurrences = Counter()
            for item in new_user["evidence"]["evidence"]:
                kind = {
                    "dashboard_activity": "DASHBOARD",
                    "current_page_context": "DASHBOARD",
                    "course_material": "COURSE_RAG",
                    "learner_memory": "LEARNER_MEMORY",
                }[item["source"]]
                actual[kind].add(canonical_bytes(item))
                new_occurrences[kind] += 1
            self.assertEqual(expected, actual, key)
            removed_by_kind.update(old_occurrences - new_occurrences)
        self.assertEqual(removed_by_kind, {"COURSE_RAG": 68})

    def test_v2_exact_request_deduplication_and_hmac_ids_are_deterministic(self) -> None:
        unique = load_jsonl(V2_MANIFEST)
        mapping = load_csv(RESTRICTED / "c4_real_condition_to_unique_request_mapping_frozen_v2.csv")
        self.assertEqual(len(unique), 197)
        self.assertEqual(len(mapping), 558)
        self.assertEqual(558 - len(unique), 361)
        key = (RESTRICTED / "c4_real_i1_blinding_hmac_key.bin").read_bytes()
        by_hash = {row["provider_payload_sha256"]: row for row in unique}
        for digest, row in by_hash.items():
            self.assertEqual(hashlib.sha256(canonical_bytes(row["provider_payload"])).hexdigest(), digest)
            self.assertEqual(row["logical_generation_request_id"], _opaque_id(key, "logical-request-v2", digest))
            self.assertEqual(row["response_blind_id"], _opaque_id(key, "response-blind-v2", digest))
        self.assertEqual({row["provider_payload_sha256_v2"] for row in mapping}, set(by_hash))
        scenario_shards: dict[str, set[str]] = {}
        for row in mapping:
            scenario_shards.setdefault(row["scenario_id"], set()).add(row["shard_id"])
        self.assertTrue(all(len(shards) == 1 for shards in scenario_shards.values()))


class PackageFreezeTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.temporary = tempfile.TemporaryDirectory()
        cls.root = Path(cls.temporary.name) / "package"
        cls.zip_path = Path(cls.temporary.name) / "package.zip"
        rows = _package_rows(row for row in _read_unique_rows() if row["shard_id"] == "A")
        write_package_directory(cls.root, "A", rows)
        write_zip(cls.root, cls.zip_path)

    @classmethod
    def tearDownClass(cls) -> None:
        cls.temporary.cleanup()

    def test_package_allowlist_hashes_hygiene_and_identity(self) -> None:
        report = validate(self.root)
        self.assertEqual(report["status"], "PASS")
        self.assertEqual(report["request_count"], 73)
        self.assertEqual(report["estimated_input_tokens"], 51821)
        self.assertEqual(report["exact_duplicate_provider_evidence_items"], 0)
        self.assertEqual(set(path.name for path in self.root.iterdir()), ALLOWED_FILES)
        self.assertEqual(validate_zip(self.zip_path)["status"], "PASS")

    def test_package_excludes_restricted_mappings_key_and_outputs(self) -> None:
        names = {path.name.casefold() for path in self.root.iterdir()}
        forbidden = ("mapping", "hmac", "sqlite", "response_journal", "judge")
        self.assertFalse(any(token in name for name in names for token in forbidden))
        source = json.loads((self.root / "PACKAGE_SOURCE_HASHES.json").read_text(encoding="utf-8"))
        self.assertFalse(source["restricted_mapping_included"])
        self.assertFalse(source["hmac_key_included"])
        self.assertFalse(source["existing_execution_results_included"])

    def test_embedded_offline_tests_and_runtime_identity(self) -> None:
        self.assertEqual(run_package_tests(self.root), 6)

    def test_all_final_packages_validate_if_published(self) -> None:
        existing = [path.exists() for path in NEW_PACKAGE_PATHS.values()]
        self.assertIn(sum(existing), (0, 3))
        for path in NEW_PACKAGE_PATHS.values():
            if path.exists():
                self.assertEqual(validate_zip(path)["status"], "PASS")


class RunnerV2Tests(unittest.TestCase):
    def test_strict_authorization_record_binding(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            base = Path(temporary)
            fixture = _make_runner_package(base)
            authorization = json.loads(fixture["authorization"].read_text(encoding="utf-8"))
            authorization["status"] = "READY"
            fixture["authorization"].write_text(json.dumps(authorization) + "\n", encoding="utf-8")
            output = base / "output"
            with mock.patch.dict(
                os.environ,
                {"C4_REAL_RESPONSE_GENERATION_AUTHORIZATION": AUTHORIZATION_ENVIRONMENT_VALUE},
            ):
                with self.assertRaisesRegex(ValueError, "status is not AUTHORIZED"):
                    execute_package(
                        fixture["manifest"],
                        fixture["authorization"],
                        fixture["package_zip"],
                        output,
                        package_root=fixture["package_root"],
                        runtime_checker=_runtime_identity,
                        client_factory=lambda: _FakeClient([]),
                    )
            self.assertFalse(output.exists())

    def test_output_directory_exclusivity_and_no_resume(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            base = Path(temporary)
            fixture = _make_runner_package(base)
            output = base / "output"
            client = _FakeClient([_response('{"answer_text":"mocked"}')])
            self.assertEqual(_execute_fixture(fixture, output, client), 0)
            with mock.patch.dict(
                os.environ,
                {"C4_REAL_RESPONSE_GENERATION_AUTHORIZATION": AUTHORIZATION_ENVIRONMENT_VALUE},
            ):
                with self.assertRaisesRegex(FileExistsError, "overwrite or automatic resume"):
                    execute_package(
                        fixture["manifest"],
                        fixture["authorization"],
                        fixture["package_zip"],
                        output,
                        package_root=fixture["package_root"],
                        runtime_checker=_runtime_identity,
                        client_factory=lambda: _FakeClient([]),
                    )
            self.assertEqual(len(client.create.payload_bytes), 1)

    def test_runtime_preflight_failure_is_durably_persisted(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            base = Path(temporary)
            fixture = _make_runner_package(base)
            output = base / "output"
            client = _FakeClient([])

            def fail_runtime() -> dict:
                raise RunnerFailure("RUNTIME_PREFLIGHT_ERROR", "runtime unavailable")

            self.assertEqual(_execute_fixture(fixture, output, client, runtime_checker=fail_runtime), 2)
            self.assertEqual({path.name for path in output.iterdir()}, OUTPUT_FILES)
            status = json.loads((output / "GENERATION_EXECUTION_STATUS.json").read_text())
            self.assertEqual(status["status"], "INCOMPLETE_FAIL_CLOSED")
            self.assertEqual(status["stop_reason"], "RUNTIME_PREFLIGHT_ERROR")
            self.assertEqual(len(client.create.payload_bytes), 0)

    def test_client_construction_failure_and_secret_redaction_are_persisted(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            base = Path(temporary)
            fixture = _make_runner_package(base)
            output = base / "output"
            tick = _Tick()
            synthetic_secret = "sk-" + "abcdefghijklmnop"

            def fail_client() -> object:
                raise ValueError(synthetic_secret + " at /Users/example/private-file")

            with mock.patch.dict(
                os.environ,
                {"C4_REAL_RESPONSE_GENERATION_AUTHORIZATION": AUTHORIZATION_ENVIRONMENT_VALUE},
            ):
                result = execute_package(
                    fixture["manifest"],
                    fixture["authorization"],
                    fixture["package_zip"],
                    output,
                    package_root=fixture["package_root"],
                    runtime_checker=_runtime_identity,
                    client_factory=fail_client,
                    sleeper=lambda _seconds: None,
                    monotonic=tick,
                    now=lambda: "2026-09-01T00:00:00Z",
                )
            self.assertEqual(result, 2)
            self.assertEqual({path.name for path in output.iterdir()}, OUTPUT_FILES)
            errors = (output / "GENERATION_ERROR_REGISTRY.jsonl").read_text()
            self.assertNotIn(synthetic_secret, errors)
            self.assertNotIn("/Users/example", errors)
            self.assertIn("[REDACTED_SECRET]", errors)
            self.assertIn("[REDACTED_LOCAL_PATH]", errors)

    def test_valid_one_attempt_completion_and_usage_arithmetic(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            base = Path(temporary)
            fixture = _make_runner_package(base)
            output = base / "output"
            client = _FakeClient([_response('{"answer_text":"mocked"}', prompt_tokens=12, completion_tokens=5)])
            self.assertEqual(_execute_fixture(fixture, output, client), 0)
            self.assertEqual({path.name for path in output.iterdir()}, OUTPUT_FILES)
            attempts = _jsonl(output / "GENERATION_ATTEMPT_JOURNAL.jsonl")
            terminal = _jsonl(output / "GENERATION_TERMINAL_JOURNAL.jsonl")
            usage = json.loads((output / "GENERATION_USAGE_AND_COST.json").read_text())
            self.assertEqual(len(attempts), 1)
            self.assertEqual(attempts[0]["strict_validation_status"], "VALID")
            self.assertEqual(terminal[0]["terminal_status"], "VALID_RESPONSE")
            self.assertEqual((usage["prompt_tokens"], usage["completion_tokens"], usage["total_tokens"]), (12, 5, 17))
            self.assertTrue(usage["usage_arithmetic_valid"])
            self.assertEqual(usage["cost_status"], "NOT_COMPUTED_NO_FROZEN_PRICING_AUTHORITY")

    def test_one_invalid_then_identical_valid_retry_retains_first_raw(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            base = Path(temporary)
            fixture = _make_runner_package(base)
            output = base / "output"
            first_raw = "not-json-first-mocked-output"
            client = _FakeClient([_response(first_raw), _response('{"answer_text":"mocked"}')])
            self.assertEqual(_execute_fixture(fixture, output, client), 0)
            attempts = _jsonl(output / "GENERATION_ATTEMPT_JOURNAL.jsonl")
            self.assertEqual(len(attempts), 2)
            self.assertEqual(attempts[0]["raw_response_content"], first_raw)
            self.assertEqual(attempts[0]["strict_validation_status"], "INVALID_JSON_OR_STRICT_SCHEMA")
            self.assertEqual(client.create.payload_bytes[0], client.create.payload_bytes[1])

    def test_first_nonretryable_error_stops_entire_shard(self) -> None:
        class AuthenticationErrorForTest(Exception):
            pass

        with tempfile.TemporaryDirectory() as temporary:
            base = Path(temporary)
            fixture = _make_runner_package(base, request_count=2)
            output = base / "output"
            client = _FakeClient([AuthenticationErrorForTest("invalid api key"), _response('{"answer_text":"must not run"}')])
            self.assertEqual(_execute_fixture(fixture, output, client), 2)
            self.assertEqual(len(client.create.payload_bytes), 1)
            status = json.loads((output / "GENERATION_EXECUTION_STATUS.json").read_text())
            self.assertEqual(status["stop_reason"], "AUTHENTICATION_ERROR")
            self.assertEqual(status["unattempted_logical_request_count"], 1)

    def test_second_invalid_output_stops_shard_and_retains_both_raw_outputs(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            base = Path(temporary)
            fixture = _make_runner_package(base, request_count=2)
            output = base / "output"
            client = _FakeClient([_response("invalid-one"), _response("invalid-two"), _response('{"answer_text":"must not run"}')])
            self.assertEqual(_execute_fixture(fixture, output, client), 2)
            self.assertEqual(len(client.create.payload_bytes), 2)
            attempts = _jsonl(output / "GENERATION_ATTEMPT_JOURNAL.jsonl")
            self.assertEqual([row["raw_response_content"] for row in attempts], ["invalid-one", "invalid-two"])
            terminal = _jsonl(output / "GENERATION_TERMINAL_JOURNAL.jsonl")
            self.assertEqual(terminal[0]["terminal_status"], "INCOMPLETE_AFTER_SECOND_INVALID_JSON_OR_SCHEMA")
            status = json.loads((output / "GENERATION_EXECUTION_STATUS.json").read_text())
            self.assertEqual(status["stop_reason"], "SECOND_INVALID_JSON_OR_SCHEMA")
            self.assertEqual(status["unattempted_logical_request_count"], 1)

    def test_returned_model_mismatch_is_retained_and_stops_shard(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            base = Path(temporary)
            fixture = _make_runner_package(base, request_count=2)
            output = base / "output"
            client = _FakeClient([_response('{"answer_text":"mocked"}', model="wrong-model"), _response('{"answer_text":"must not run"}')])
            self.assertEqual(_execute_fixture(fixture, output, client), 2)
            self.assertEqual(len(client.create.payload_bytes), 1)
            attempts = _jsonl(output / "GENERATION_ATTEMPT_JOURNAL.jsonl")
            self.assertEqual(attempts[0]["returned_model"], "wrong-model")
            self.assertEqual(attempts[0]["provider_response_id"], "chatcmpl-mocked")
            status = json.loads((output / "GENERATION_EXECUTION_STATUS.json").read_text())
            self.assertEqual(status["stop_reason"], "MODEL_MISMATCH")


if __name__ == "__main__":
    unittest.main()
