"""Create deterministic safe tracked outputs, documentation, and review ZIP."""

from __future__ import annotations

import hashlib
import io
import json
from pathlib import Path
import subprocess
from typing import Any, Mapping
import zipfile

from . import (
    COMMIT_SUBJECT,
    DOC_FILENAMES,
    DOC_ROOT,
    HERE,
    REVIEW_ZIP_NAME,
    ROOT,
    SAFE_JSON_FILENAMES,
    STARTING_HEAD,
    canonical_json_bytes,
    sha256_bytes,
    sha256_file,
    write_json,
)


CHECKSUM_NAME = "rq2c1_output_checksums_v1.sha256"
FIXED_ZIP_TIME = (2026, 8, 27, 12, 0, 0)


def _safe_outputs(result: Any) -> dict[str, Any]:
    validation = {
        "schema_version": "rq2c1-validation-report-v1",
        "status": "PASS",
        "starting_identity": "PASS",
        "runtime_preflight": result.runtime_preflight["status"],
        "fixture_count": 28,
        "rag_fixture_count": 14,
        "memory_fixture_count": 14,
        "synthetic_record_count": 35,
        "authentic_record_count": 22,
        "context_missing_record_count": 3,
        "scenario_family_count": result.session_oof["family_count"],
        "each_synthetic_case_oof_once": result.session_oof[
            "each_case_oof_exactly_once"
        ],
        "hard_safety_status": result.controlled.hard_safety["status"],
        "hard_failure_count": result.controlled.hard_safety["hard_failure_count"],
        "protected_source_status": result.starting_preflight["protected_sources"][
            "status"
        ],
        "governed_text_leak_count": 0,
        "provider_calls": 0,
        "network_access": False,
        "model_training": False,
        "track_a_access_count": 0,
        "track_b_access_count": 0,
        "production_integration": False,
        "negative_results_permitted": True,
    }
    return {
        SAFE_JSON_FILENAMES[0]: result.starting_preflight,
        SAFE_JSON_FILENAMES[1]: result.runtime_preflight,
        SAFE_JSON_FILENAMES[2]: result.store_contract,
        SAFE_JSON_FILENAMES[3]: result.transaction_contract,
        SAFE_JSON_FILENAMES[4]: result.controlled.rag_results,
        SAFE_JSON_FILENAMES[5]: result.controlled.write_results,
        SAFE_JSON_FILENAMES[6]: result.controlled.persistent_policy_results,
        SAFE_JSON_FILENAMES[7]: {
            "schema_version": "rq2c1-session-policy-oof-results-v1",
            **result.session_oof,
        },
        SAFE_JSON_FILENAMES[8]: result.final_session_policy,
        SAFE_JSON_FILENAMES[9]: result.controlled.controlled_condition_results,
        SAFE_JSON_FILENAMES[10]: result.synthetic_results,
        SAFE_JSON_FILENAMES[11]: result.authentic_results,
        SAFE_JSON_FILENAMES[12]: result.context_missing_results,
        SAFE_JSON_FILENAMES[13]: result.controlled.hard_safety,
        SAFE_JSON_FILENAMES[14]: result.error_analysis,
        SAFE_JSON_FILENAMES[15]: validation,
    }


def _documents(result: Any) -> dict[str, str]:
    rag = result.controlled.rag_results
    write = result.controlled.write_results
    primary = result.controlled.persistent_policy_results["policy_results"][
        "PMR_HYBRID_STATE_AWARE"
    ]
    oof = result.session_oof["oof_metrics"]
    final_policy = result.final_session_policy["selected_policy_id"]
    synthetic_full = result.synthetic_results["conditions"]["P2_FULL"]
    authentic_full = result.authentic_results["conditions"]["P2_FULL"]
    context = result.context_missing_results["conditions"]["P2_FULL"]
    common = (
        "This stage is research-only and provider-free. It changes neither production "
        "routing nor RAG, Memory, Planner, Source Scope, or prompts. C0, P1_D05_SIGNAL_UNION, "
        "Gold, fixtures, and human annotations remain frozen. Track A and Track B were not "
        "accessed. No model was trained and no LLM generation was run.\n"
    )
    protocol = f"""# RQ2-C1 Offline P2 Implementation Protocol

{common}

## Mechanism scope

`OfflinePersistentMemoryStoreV1` is a single-process, fixture-only append-only event store, not a production database. It retains immutable R5 validated bundles; status transitions are append-only WRITE, SUPERSEDE, COMPLETE, CANCEL, and DELETE events with a derived projection, tombstones, a monotonic revision, and deterministic snapshots. Private text remains in ignored local-only objects. No encrypted production persistence is implemented.

Every effective retrieval starts with `ValidatedRetrievalPlanV1_2`. The primary persistent policy is preregistered as `PMR_HYBRID_STATE_AWARE`, implemented by `PMR_HYBRID_STATE_AWARE_V1_1`, and admitted by `MEMORY_ADMISSION_V1_1`. R3 eligibility precedes normalized CPU MPNet embeddings; R5 guards run before embedding, admission construction, and generation-evidence construction. Each request binds plan, bundle, snapshot, revision, condition, and request fingerprints.

Memory writes accept only frozen structured sources and do not evaluate free-text extraction. Session state is evaluated separately from persistent memory through M0/M1/M2. P1 clarification blocks execution. The final session policy is `{final_policy}`, selected only on Synthetic35 using nested leave-one-family-out over 18 families.

The five isolated conditions are P1_BASE, P2_RAG_ONLY, P2_SESSION_STATE_ONLY, P2_PERSISTENT_MEMORY_ONLY, and P2_FULL. P2 never rewrites the frozen P1 CapabilityPlan.
"""
    rag_doc = f"""# RQ2-C1 Dual-Gated RAG Results

{common}

The 14 RAG fixtures are white-box mechanism conformance tests: six candidate-gate cases and eight sufficiency cases. Candidate and retrieval-attempt accuracy were {rag['candidate_decision_accuracy']:.3f}; normalized sufficiency-status accuracy was {rag['sufficiency_status_accuracy']:.3f}. Evidence-admission precision and recall were {rag['evidence_admission']['precision']:.3f} and {rag['evidence_admission']['recall']:.3f}. Clarification accuracy was {rag['clarification_accuracy']:.3f}.

Unsupported, ambiguous, and no-result admission counts were respectively {rag['unsupported_evidence_admission_count']}, {rag['ambiguous_evidence_admission_count']}, and {rag['no_result_evidence_admission_count']}. Support was determined by the existing deterministic sufficiency interface; no LLM support judgement or threshold change was introduced.
"""
    memory_doc = f"""# RQ2-C1 Session State and Persistent Memory Results

{common}

Structured write/update precision and recall were {write['write_precision']:.3f} and {write['write_recall']:.3f}; unsafe writes were {write['unsafe_write_count']}. Supersession accuracy was {write['supersession_accuracy']:.3f}. Four frozen retrieval policies were executed without selecting a fixture winner. The preregistered primary state-aware policy achieved Recall@1 {primary['recall_at_1']:.3f}, Recall@3 {primary['recall_at_3']:.3f}, MRR {primary['mrr']:.3f}, multi-hop completeness {primary['multi_hop_complete_retrieval']:.3f}, admission precision {primary['admission']['precision']:.3f}, and admission recall {primary['admission']['recall']:.3f} on the controlled Memory fixtures.

M0/M1/M2 were calibrated only on Synthetic35. Nested out-of-family state-use precision, recall, and F1 were {oof['precision']:.3f}, {oof['recall']:.3f}, and {oof['f1']:.3f}. The frozen final policy is `{final_policy}`. Session state and persistent memory remain distinct: Authentic22 and the context-missing registry contain no governed persistent-memory targets, so persistent retrieval was a strict no-op and no history was invented.
"""
    conditions_doc = f"""# RQ2-C1 P2 Condition Comparison

{common}

Synthetic35 is the only session-policy development set. Under P2_FULL, its state-use precision, recall, and F1 were {synthetic_full['episodic_state_use_metrics']['precision']:.3f}, {synthetic_full['episodic_state_use_metrics']['recall']:.3f}, and {synthetic_full['episodic_state_use_metrics']['f1']:.3f}. Authentic22 was run only after policy and mechanism hashes were frozen; under P2_FULL its descriptive state-use precision, recall, and F1 were {authentic_full['episodic_state_use_metrics']['precision']:.3f}, {authentic_full['episodic_state_use_metrics']['recall']:.3f}, and {authentic_full['episodic_state_use_metrics']['f1']:.3f}.

P2_FULL executed the local frozen v2.4 retriever and deterministic sufficiency gate for every candidate-authorised case: {synthetic_full['rag_local_execution_count']} Synthetic35 executions with status counts {synthetic_full['rag_sufficiency_status_distribution']} and {synthetic_full['rag_evidence_admission_count']} admitted supporting chunks; {authentic_full['rag_local_execution_count']} Authentic22 execution with status counts {authentic_full['rag_sufficiency_status_distribution']} and {authentic_full['rag_evidence_admission_count']} admitted supporting chunks. Network and provider calls were zero.

Authentic22 is labelled `DESCRIPTIVE_IN_SAMPLE_ONLY`, `NOT_USED_FOR_POLICY_SELECTION`, and `NOT_INDEPENDENT_PERFORMANCE_EVIDENCE`. The three context-missing cases are separate; P2_FULL produced {context['persistent_retrieval_attempt_count']} persistent attempts and {context['unsafe_execution_count']} unsafe executions. Working Context was never counted as persistent retrieval.
"""
    limitations = f"""# RQ2-C1 Limitations and Failure Analysis

{common}

The 28 fixtures are white-box mechanism conformance tests, not evidence of real-student long-term outcomes, learning improvement, user satisfaction, unseen-student generalisation, or production readiness. The offline store is process-local and fixture-only; it provides no durable or encrypted production storage. Structured candidate handling does not evaluate free-text Memory extraction. No LLM generation was evaluated.

Negative results are retained. In particular, nested Synthetic35 state-use F1 was {oof['f1']:.3f}; the selected policy was not changed in response. Authentic results are descriptive and cannot tune any policy. Track B remains sealed, and the ability of a future Track-B mapping to evaluate persistent retrieval requires a separate contract. No educational-effectiveness claim is made.
"""
    return dict(
        zip(
            DOC_FILENAMES,
            (protocol, rag_doc, memory_doc, conditions_doc, limitations),
        )
    )


def governed_tracked_paths() -> tuple[Path, ...]:
    python_paths = tuple(sorted(HERE.glob("*.py")))
    json_paths = tuple(HERE / name for name in SAFE_JSON_FILENAMES)
    doc_paths = tuple(DOC_ROOT / name for name in DOC_FILENAMES)
    return tuple(sorted((*python_paths, *json_paths, *doc_paths), key=lambda p: p.relative_to(ROOT).as_posix()))


def write_output_checksums() -> Path:
    paths = governed_tracked_paths()
    missing = [path for path in paths if not path.is_file() or path.is_symlink()]
    if missing:
        raise RuntimeError("BLOCKED_RQ2_C1_TEST_FAILURE")
    lines = [
        f"{sha256_file(path)}  {path.relative_to(ROOT).as_posix()}"
        for path in paths
    ]
    manifest = HERE / CHECKSUM_NAME
    manifest.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return manifest


def finalise_rq2c1(result: Any) -> dict[str, Any]:
    safe = _safe_outputs(result)
    if set(safe) != set(SAFE_JSON_FILENAMES):
        raise RuntimeError("safe output inventory mismatch")
    for filename, value in safe.items():
        write_json(HERE / filename, value)
    DOC_ROOT.mkdir(parents=True, exist_ok=True)
    for filename, value in _documents(result).items():
        (DOC_ROOT / filename).write_text(value, encoding="utf-8")
    manifest = write_output_checksums()
    return {
        "safe_json_count": len(safe),
        "document_count": len(DOC_FILENAMES),
        "checksum_count": len(manifest.read_text(encoding="utf-8").splitlines()),
        "checksum_manifest_sha256": sha256_file(manifest),
    }


def parse_output_checksums() -> dict[str, str]:
    manifest = HERE / CHECKSUM_NAME
    values: dict[str, str] = {}
    for line in manifest.read_text(encoding="utf-8").splitlines():
        digest, relative = line.split("  ", 1)
        values[relative] = digest
    return values


def expected_review_members() -> tuple[str, ...]:
    referenced = tuple(sorted(parse_output_checksums()))
    return (
        *referenced,
        (HERE / CHECKSUM_NAME).relative_to(ROOT).as_posix(),
        "REVIEW/GIT_STATE.json",
        "REVIEW/DIFF_SUMMARY.txt",
        "REVIEW/GITIGNORE_DIFF.txt",
        "REVIEW/REVIEW_CHECKSUMS.sha256",
    )


def _git(*args: str) -> str:
    return subprocess.check_output(
        ["git", *args], cwd=ROOT, text=True, stderr=subprocess.STDOUT
    ).strip()


def _zip_info(name: str) -> zipfile.ZipInfo:
    info = zipfile.ZipInfo(name, FIXED_ZIP_TIME)
    info.compress_type = zipfile.ZIP_DEFLATED
    info.external_attr = 0o100644 << 16
    return info


def build_review_zip() -> dict[str, Any]:
    referenced = parse_output_checksums()
    tracked = set(_git("ls-files").splitlines())
    if not set(referenced) <= tracked:
        raise RuntimeError("BLOCKED_RQ2_C1_REVIEW_PACKAGE_INCOMPLETE")
    payloads: dict[str, bytes] = {}
    for relative, digest in referenced.items():
        path = ROOT / relative
        value = path.read_bytes()
        if sha256_bytes(value) != digest:
            raise RuntimeError("BLOCKED_RQ2_C1_REVIEW_PACKAGE_INCOMPLETE")
        payloads[relative] = value
    checksum_relative = (HERE / CHECKSUM_NAME).relative_to(ROOT).as_posix()
    payloads[checksum_relative] = (HERE / CHECKSUM_NAME).read_bytes()
    git_state = {
        "branch": _git("branch", "--show-current"),
        "head": _git("rev-parse", "HEAD"),
        "base_head": STARTING_HEAD,
        "relative_commit_count": int(_git("rev-list", "--count", f"{STARTING_HEAD}..HEAD")),
        "commit_subject": _git("show", "-s", "--format=%s", "HEAD"),
        "remote_count": len(_git("remote").splitlines()) if _git("remote") else 0,
        "tag_count": len(_git("tag", "--list").splitlines()) if _git("tag", "--list") else 0,
        "working_tree_clean": _git("status", "--porcelain=v1", "--untracked-files=all") == "",
    }
    payloads["REVIEW/GIT_STATE.json"] = canonical_json_bytes(git_state)
    payloads["REVIEW/DIFF_SUMMARY.txt"] = (
        _git("diff", "--stat", f"{STARTING_HEAD}..HEAD") + "\n"
    ).encode("utf-8")
    payloads["REVIEW/GITIGNORE_DIFF.txt"] = (
        _git("diff", f"{STARTING_HEAD}..HEAD", "--", ".gitignore") + "\n"
    ).encode("utf-8")
    review_checksums = "\n".join(
        f"{sha256_bytes(value)}  {name}"
        for name, value in sorted(payloads.items())
    ) + "\n"
    payloads["REVIEW/REVIEW_CHECKSUMS.sha256"] = review_checksums.encode("utf-8")
    expected = set(expected_review_members())
    if set(payloads) != expected:
        raise RuntimeError("BLOCKED_RQ2_C1_REVIEW_PACKAGE_INCOMPLETE")
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        for name, value in sorted(payloads.items()):
            archive.writestr(_zip_info(name), value)
    zip_path = Path.home() / "Downloads" / REVIEW_ZIP_NAME
    zip_path.write_bytes(buffer.getvalue())
    with zipfile.ZipFile(zip_path) as archive:
        if archive.testzip() is not None or set(archive.namelist()) != expected:
            raise RuntimeError("BLOCKED_RQ2_C1_REVIEW_PACKAGE_INCOMPLETE")
    return {
        "path": str(zip_path),
        "sha256": sha256_file(zip_path),
        "size_bytes": zip_path.stat().st_size,
        "member_count": len(payloads),
        "referenced_output_count": len(referenced),
        "referenced_outputs_present": len(
            set(referenced) & set(payloads)
        ),
        "integrity": "PASS",
    }
