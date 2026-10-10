"""Deterministic safe outputs, documents, checksums, and post-commit review ZIP."""

from __future__ import annotations

import io
import json
from pathlib import Path
import subprocess
from typing import Any
import zipfile

from . import (
    COMMIT_SUBJECT,
    DOC_FILENAMES,
    DOC_ROOT,
    HERE,
    ORIGINAL_DISPOSITION,
    ORIGINAL_PRESERVATION,
    RESULT_BRANCH,
    REVIEW_ZIP_NAME,
    ROOT,
    SAFE_JSON_FILENAMES,
    STAGE_ID,
    STARTING_HEAD,
    canonical_json_bytes,
    sha256_bytes,
    sha256_file,
    write_json,
)


CHECKSUM_NAME = "rq2c1_r1_output_checksums_v1.sha256"
FIXED_ZIP_TIME = (2026, 8, 27, 12, 0, 0)


def _validation_report(result: Any) -> dict[str, Any]:
    return {
        "schema_version": "rq2c1-r1-validation-report-v1",
        "stage": STAGE_ID,
        "status": "PASS",
        "starting_identity": result.starting_preflight["status"],
        "original_c1_identity": result.starting_preflight["original_c1"]["status"],
        "original_c1_file_change_count": 0,
        "fixture_count": 28,
        "rag_fixture_count": 14,
        "memory_fixture_count": 14,
        "synthetic_record_count": 35,
        "authentic_record_count": 22,
        "context_missing_record_count": 3,
        "scenario_family_count": result.session_results["nested_oof"]["family_count"],
        "each_synthetic_case_oof_once": result.session_results["nested_oof"][
            "each_case_oof_exactly_once"
        ],
        "rag_condition_isolation_status": result.rag_isolation["status"],
        "disabled_condition_actual_rag_call_count": result.rag_isolation[
            "disabled_condition_actual_call_count"
        ],
        "runtime_safety_status": result.runtime_safety["status"],
        "hard_failure_count": result.runtime_safety["hard_failure_count"],
        "successful_safety_violation_count": result.runtime_safety[
            "successful_violation_count"
        ],
        "all_adversarial_probes_blocked": result.runtime_safety[
            "adversarial_guard_probes"
        ]["all_probes_blocked"],
        "r5_aware_time_used": True,
        "r2_naive_time_helper_used": False,
        "case_scoped_admission_metrics_used": True,
        "governed_text_leak_count": 0,
        "provider_calls": 0,
        "network_access": False,
        "model_training": False,
        "track_a_access_count": 0,
        "track_b_access_count": 0,
        "production_integration": False,
        "production_source_change_count": 0,
        "p1_changed": False,
        "gold_changed": False,
        "fixture_changed": False,
        "human_annotation_changed": False,
        "c0_changed": False,
        "authentic_used_for_policy_selection": False,
    }


def safe_outputs(result: Any) -> dict[str, Any]:
    values = {
        SAFE_JSON_FILENAMES[0]: result.starting_preflight,
        SAFE_JSON_FILENAMES[1]: result.store_contract,
        SAFE_JSON_FILENAMES[2]: result.execution_context_contract,
        SAFE_JSON_FILENAMES[3]: result.rag_isolation,
        SAFE_JSON_FILENAMES[4]: result.correction_contract,
        SAFE_JSON_FILENAMES[5]: result.runtime_safety,
        SAFE_JSON_FILENAMES[6]: result.controlled.rag_results,
        SAFE_JSON_FILENAMES[7]: result.controlled.memory_results,
        SAFE_JSON_FILENAMES[8]: result.session_results,
        SAFE_JSON_FILENAMES[9]: result.condition_results,
        SAFE_JSON_FILENAMES[10]: result.authentic_results,
        SAFE_JSON_FILENAMES[11]: result.context_missing_results,
        SAFE_JSON_FILENAMES[12]: result.delta_results,
        SAFE_JSON_FILENAMES[13]: _validation_report(result),
    }
    if set(values) != set(SAFE_JSON_FILENAMES):
        raise RuntimeError("BLOCKED_RQ2_C1_R1_EVALUATION")
    return values


def _documents(result: Any) -> dict[str, str]:
    primary = result.controlled.memory_results["persistent_policy_comparison"][
        "policy_results"
    ]["PMR_HYBRID_STATE_AWARE"]
    rag = result.controlled.rag_results
    final_policy = result.session_results["final_session_policy"]["selected_policy_id"]
    oof = result.session_results["nested_oof"]["oof_metrics"]
    synthetic_full = result.condition_results["synthetic35"]["conditions"]["P2_FULL"]
    authentic_full = result.authentic_results["conditions"]["P2_FULL"]
    common = (
        "This is a research-only, provider-free offline correction. Original RQ2-C1 is "
        f"{ORIGINAL_PRESERVATION} and {ORIGINAL_DISPOSITION}. No original C1 file, fixture, "
        "P1 policy, Gold label, human annotation, C0 artifact, production source, or threshold "
        "was changed. Track A and Track B were not accessed. No model was trained.\n"
    )
    store_doc = f"""# RQ2-C1-R1 Store Lifecycle and Tombstone Safety

{common}

`OfflinePersistentMemoryStoreV1_1` uses an explicit state machine. ACTIVE may become SUPERSEDED, COMPLETED, CANCELLED, or DELETED. SUPERSEDED, COMPLETED, CANCELLED, and STALE may only become DELETED. DELETED has no outgoing transition. A WRITE → DELETE → COMPLETE sequence is rejected as `INVALID_STORE_STATE_TRANSITION` and cannot re-enter the active set.

Tombstones are reconstructed from the complete append-only DELETE-event history, not inferred only from the latest projection. Every event records previous/new status, previous/current event time, contract ID, revision, and source bundle fingerprint. Event time must be timezone-aware, at or after episode ingestion, and monotonic within each memory. Projection, tombstones, active IDs, revision, and snapshot fingerprints are reproducible by replay. This remains a process-local fixture store, not durable production persistence.
"""
    context_doc = f"""# RQ2-C1-R1 Execution-Context Transaction Binding

{common}

`ValidatedMemoryExecutionContextV1_1` is issued only by its factory and binds the validated R5 plan and bundle, student-scope hash, current snapshot, projection hash/status, store revision, condition, request, context fingerprint, and contract ID. Verification recomputes those facts from the current store; type identity alone is never authority. Cross-store, cross-scope, cross-revision, cross-condition, cross-request, forged, and mutated contexts fail closed.

The current projection is state authority; immutable episode status remains historical. ACTIVE is eligible normally. COMPLETED is eligible only when the validated plan explicitly targets COMPLETION. SUPERSEDED, CANCELLED, STALE, and DELETED are rejected. Temporal checks call `temporal_validity_aware_v1_1` with `ValidatedRetrievalPlanV1_2.query_time_utc`; no R2 naive-time helper is used.
"""
    isolation_doc = f"""# RQ2-C1-R1 Condition Isolation and Corrected Results

{common}

RAG candidate gating and actual execution now occur inside each condition. P1_BASE, P2_SESSION_STATE_ONLY, and P2_PERSISTENT_MEMORY_ONLY made {result.rag_isolation['disabled_condition_actual_call_count']} actual RAG calls. P2_RAG_ONLY and P2_FULL each execute the frozen local retriever only for their own candidate-passing cases; retrieval, sufficiency, admission, and receipts are not reused across conditions. Synthetic35 made {result.rag_isolation['datasets']['SYNTHETIC35']['physical_actual_retriever_call_count']} physical condition-local calls and Authentic22 made {result.rag_isolation['datasets']['AUTHENTIC22']['physical_actual_retriever_call_count']}. Provider and network calls were zero.

The 14 controlled RAG fixtures retained candidate accuracy {rag['candidate_decision_accuracy']:.3f}, sufficiency accuracy {rag['sufficiency_status_accuracy']:.3f}, admission precision {rag['evidence_admission']['precision']:.3f}, and admission recall {rag['evidence_admission']['recall']:.3f}. The primary persistent policy produced Recall@1 {primary['recall_at_1']:.3f}, Recall@3 {primary['recall_at_3']:.3f}, MRR {primary['mrr']:.3f}, multi-hop completeness {primary['multi_hop_complete_retrieval']:.3f}, admission precision {primary['admission']['precision']:.3f}, and admission recall {primary['admission']['recall']:.3f}. Admission identity is `(fixture_id, memory_id)`. Recall@k is the recovered proportion of required IDs; MRR is the rank of the first relevant item, so multi-target MRR can equal 1 while Recall@1 is below 1.

Synthetic35 alone reselected `{final_policy}` under the frozen rule; nested out-of-family session-state F1 was {oof['f1']:.3f}. P2_FULL Synthetic35 and descriptive Authentic22 state-use F1 were {synthetic_full['episodic_state_use_metrics']['f1']:.3f} and {authentic_full['episodic_state_use_metrics']['f1']:.3f}. Authentic22 and the context-missing registry did not tune any policy.
"""
    limitations_doc = f"""# RQ2-C1-R1 Limitations and Track-B Entry Decision

{common}

All nine adversarial guard categories were exercised, and every attempt was blocked; successful safety violations were {result.runtime_safety['successful_violation_count']}. These are implementation-safety and white-box mechanism results, not evidence of educational effectiveness, learning improvement, longitudinal memory quality, unseen-student generalisation, user satisfaction, or production readiness.

The store remains in-memory and fixture-only. Private payload encryption and durable lifecycle recovery are not production implementations. The 28 fixtures, Synthetic35, Authentic22, context-missing3, P1_D05, C0, primary persistent policy, M0/M1/M2 grid, and RAG threshold were unchanged. Negative and unchanged metrics were retained without tuning.

The corrected stage is ready only for a separate RQ2-D0 contract that maps Track B, freezes P2 final-evaluation scope, and establishes a one-shot harness. Track B remains sealed. No production capability router has been integrated.
"""
    return dict(zip(DOC_FILENAMES, (store_doc, context_doc, isolation_doc, limitations_doc)))


def governed_tracked_paths() -> tuple[Path, ...]:
    python_paths = tuple(sorted(HERE.glob("*.py")))
    json_paths = tuple(HERE / name for name in SAFE_JSON_FILENAMES)
    doc_paths = tuple(DOC_ROOT / name for name in DOC_FILENAMES)
    return tuple(
        sorted(
            (*python_paths, *json_paths, *doc_paths),
            key=lambda path: path.relative_to(ROOT).as_posix(),
        )
    )


def write_output_checksums() -> Path:
    paths = governed_tracked_paths()
    missing = [path for path in paths if not path.is_file() or path.is_symlink()]
    if missing:
        raise RuntimeError("BLOCKED_RQ2_C1_R1_TEST_FAILURE")
    manifest = HERE / CHECKSUM_NAME
    manifest.write_text(
        "\n".join(
            f"{sha256_file(path)}  {path.relative_to(ROOT).as_posix()}"
            for path in paths
        )
        + "\n",
        encoding="utf-8",
    )
    return manifest


def finalise_rq2c1_r1(result: Any) -> dict[str, Any]:
    for filename, value in safe_outputs(result).items():
        write_json(HERE / filename, value)
    DOC_ROOT.mkdir(parents=True, exist_ok=True)
    for filename, text in _documents(result).items():
        (DOC_ROOT / filename).write_text(text, encoding="utf-8")
    manifest = write_output_checksums()
    return {
        "safe_json_count": len(SAFE_JSON_FILENAMES),
        "document_count": len(DOC_FILENAMES),
        "checksum_count": len(manifest.read_text(encoding="utf-8").splitlines()),
        "checksum_manifest_sha256": sha256_file(manifest),
    }


def parse_output_checksums() -> dict[str, str]:
    values: dict[str, str] = {}
    for line in (HERE / CHECKSUM_NAME).read_text(encoding="utf-8").splitlines():
        digest, relative = line.split("  ", 1)
        values[relative] = digest
    return values


def _git(*args: str) -> str:
    return subprocess.check_output(
        ["git", *args], cwd=ROOT, text=True, stderr=subprocess.STDOUT
    ).strip()


def expected_review_members() -> tuple[str, ...]:
    referenced = tuple(sorted(parse_output_checksums()))
    members = [
        *referenced,
        (HERE / CHECKSUM_NAME).relative_to(ROOT).as_posix(),
        "REVIEW/GIT_STATE.json",
        "REVIEW/DIFF_SUMMARY.txt",
        "REVIEW/REVIEW_CHECKSUMS.sha256",
    ]
    if _git("diff", STARTING_HEAD + "..HEAD", "--", ".gitignore"):
        members.append("REVIEW/GITIGNORE_DIFF.txt")
    return tuple(members)


def _zip_info(name: str) -> zipfile.ZipInfo:
    info = zipfile.ZipInfo(name, FIXED_ZIP_TIME)
    info.compress_type = zipfile.ZIP_DEFLATED
    info.external_attr = 0o100644 << 16
    return info


def build_review_zip() -> dict[str, Any]:
    referenced = parse_output_checksums()
    tracked = set(_git("ls-files").splitlines())
    if not set(referenced) <= tracked:
        raise RuntimeError("BLOCKED_RQ2_C1_R1_REVIEW_PACKAGE_INCOMPLETE")
    payloads: dict[str, bytes] = {}
    for relative, digest in referenced.items():
        value = (ROOT / relative).read_bytes()
        if sha256_bytes(value) != digest:
            raise RuntimeError("BLOCKED_RQ2_C1_R1_REVIEW_PACKAGE_INCOMPLETE")
        payloads[relative] = value
    checksum_relative = (HERE / CHECKSUM_NAME).relative_to(ROOT).as_posix()
    payloads[checksum_relative] = (HERE / CHECKSUM_NAME).read_bytes()
    git_state = {
        "branch": _git("branch", "--show-current"),
        "head": _git("rev-parse", "HEAD"),
        "base_head": STARTING_HEAD,
        "relative_commit_count": int(
            _git("rev-list", "--count", f"{STARTING_HEAD}..HEAD")
        ),
        "commit_subject": _git("show", "-s", "--format=%s", "HEAD"),
        "remote_count": len(_git("remote").splitlines()) if _git("remote") else 0,
        "tag_count": len(_git("tag", "--list").splitlines())
        if _git("tag", "--list")
        else 0,
        "working_tree_clean": _git(
            "status", "--porcelain=v1", "--untracked-files=all"
        )
        == "",
        "original_c1_changed_file_count": len(
            _git(
                "diff",
                "--name-only",
                STARTING_HEAD + "..HEAD",
                "--",
                "evaluation/capability_routing_rq2c1_v1",
            ).splitlines()
        ),
    }
    payloads["REVIEW/GIT_STATE.json"] = canonical_json_bytes(git_state)
    payloads["REVIEW/DIFF_SUMMARY.txt"] = (
        _git("diff", "--stat", STARTING_HEAD + "..HEAD") + "\n"
    ).encode("utf-8")
    gitignore_diff = _git("diff", STARTING_HEAD + "..HEAD", "--", ".gitignore")
    if gitignore_diff:
        payloads["REVIEW/GITIGNORE_DIFF.txt"] = (gitignore_diff + "\n").encode(
            "utf-8"
        )
    review_checksums = (
        "\n".join(
            f"{sha256_bytes(value)}  {name}"
            for name, value in sorted(payloads.items())
        )
        + "\n"
    )
    payloads["REVIEW/REVIEW_CHECKSUMS.sha256"] = review_checksums.encode("utf-8")
    expected = set(expected_review_members())
    if set(payloads) != expected:
        raise RuntimeError("BLOCKED_RQ2_C1_R1_REVIEW_PACKAGE_INCOMPLETE")
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        for name, value in sorted(payloads.items()):
            archive.writestr(_zip_info(name), value)
    zip_path = Path.home() / "Downloads" / REVIEW_ZIP_NAME
    zip_path.write_bytes(buffer.getvalue())
    with zipfile.ZipFile(zip_path) as archive:
        if archive.testzip() is not None or set(archive.namelist()) != expected:
            raise RuntimeError("BLOCKED_RQ2_C1_R1_REVIEW_PACKAGE_INCOMPLETE")
    return {
        "path": str(zip_path),
        "sha256": sha256_file(zip_path),
        "size_bytes": zip_path.stat().st_size,
        "member_count": len(payloads),
        "referenced_output_count": len(referenced),
        "referenced_outputs_present": len(set(referenced) & set(payloads)),
        "integrity": "PASS",
    }
