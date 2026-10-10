"""Deterministic D0 safe outputs, documents, checksums, and review ZIP."""

from __future__ import annotations

import json
from pathlib import Path
import subprocess
from typing import Any
import zipfile

from . import (
    CHECKSUM_NAME,
    DOC_FILENAMES,
    DOC_ROOT,
    HERE,
    RESULT_BRANCH,
    REVIEW_ZIP_NAME,
    ROOT,
    SAFE_AUTHORITY_COPY_ROOT,
    SAFE_JSON_FILENAMES,
    SCHEMA_AUTHORITY_MEMBER_SHA256,
    SCHEMA_AUTHORITY_ZIP_SHA256,
    STARTING_HEAD,
    TRACK_B_ORDER_COMMITMENT,
    TRACK_B_SHA256,
    canonical_json_bytes,
    sha256_bytes,
    sha256_file,
    write_json,
)
from .blinded_packet_builder import blinding_contract_document
from .capability_review_schema import capability_review_schema_document
from .contamination_contract import contamination_contract_document
from .final_scope_contract import final_scope_contract_document
from .packet_generation_state_machine import state_machine_contract_document
from .run_rq2d0 import RQ2D0Result
from .statistical_contract import statistical_contract_document
from .track_b_schema_contract import schema_contract_document


FIXED_ZIP_TIME = (2026, 8, 27, 18, 0, 0)


def safe_outputs(result: RQ2D0Result) -> dict[str, Any]:
    preflight = {
        **result.preflight,
        "safe_schema_authority": {
            "status": result.safe_authority["status"],
            "package_sha256": result.safe_authority["package_sha256"],
            "member_count": result.safe_authority["member_count"],
            "byte_identical_copy_count": result.authority_copy["byte_identical_count"],
            "codex_raw_access": False,
            "repository_d0_raw_access": False,
        },
    }
    values = (
        result.safe_authority,
        schema_contract_document(),
        capability_review_schema_document(),
        blinding_contract_document(),
        contamination_contract_document(),
        state_machine_contract_document(),
        final_scope_contract_document(),
        statistical_contract_document(),
        result.synthetic_validation,
        preflight,
    )
    return dict(zip(SAFE_JSON_FILENAMES, values))


def _documents(result: RQ2D0Result) -> dict[str, str]:
    schema = schema_contract_document()
    columns = schema["header_contract"]["exact_column_order"]
    column_lines = "\n".join(f"{index}. `{name}`" for index, name in enumerate(columns, 1))
    common = (
        "This is a contract-only, provider-free RQ2-D0 freeze. Codex and the D0 "
        "repository pipeline did not determine whether raw Track B exists and did not "
        "list, stat, resolve, hash, open, read, or parse it. The safe package records "
        "that a separate out-of-band authority builder accessed the hash-matched asset "
        "only to extract schema metadata; that builder must not review, adjudicate, tune, "
        "or evaluate Track B. No Capability labels or real review packets were created.\n"
    )
    authority_doc = f"""# RQ2-D0 Track B Authority and Schema

{common}

The sole effective schema sources are the byte-identical governed copies of `TRACK_B_SCHEMA_AUTHORITY_V1.json` and `TRACK_B_BLANK_SCHEMA_TEMPLATE_V1.csv`. The safe package SHA-256 is `{SCHEMA_AUTHORITY_ZIP_SHA256}`. It contains six exact members and no raw row, query, history, prior rationale, model prediction, Track A asset, or student record.

The raw identity is safe metadata only: filename `primary_v3_hybrid_context_human_review_researcher_final_v1.csv`, SHA-256 `{TRACK_B_SHA256}`, size 65,095 bytes, 48 records, and 47 columns. Encoding is UTF-8 with BOM `EFBBBF`; every physical line and the final line use CRLF. There is no raw `index` column. Blank optional values are zero-length CSV fields, not textual null tokens.

Physical order is authoritative: `PV3-B-0001` through `PV3-B-0048`; the ordered-ID commitment is `{TRACK_B_ORDER_COMMITMENT}`. D1 must recompute this before any reorder. `scenario_family_id` has 48 one-record groups and is not a repeated cluster unit. `contrast_set_id` has 24 two-record groups. No session-ID field exists.

## Exact governed 47-column order

{column_lines}

`human_revised_query` overrides `current_query` only when nonblank (current count 0). `human_revised_history` overrides `conversation_history` only when nonblank (current count 1). The expected-field overlay is hidden and post-Gold legacy-diagnostic only.
"""
    mapping_doc = f"""# RQ2-D0 Track B Capability Mapping Protocol

{common}

All 48 cases require two different human reviewers working independently and in different fixed random orders. They cannot use AI, view each other's decisions, view existing Intent labels, model outputs, source/guard/policy metadata, or automatic proposals. A third human adjudicator resolves every disagreement only after both packets are frozen.

Packets expose only an opaque review ID, effective current query, current page, effective two-turn conversation history, Capability definitions, and blank v1.3 human fields. Existing Track B Intent annotations are descriptive legacy annotations, not Capability Gold. The deterministic Intent-to-Capability map cannot form Gold. An Intent-versus-Capability diagnostic is allowed only after final Capability Gold is frozen.
"""
    scope_doc = f"""# RQ2-D0 RQ2 Final Evaluation Scope

{common}

Primary Track B Capability predictors are B0 original-query C0 Top-1 hard routing without context resolution, B1 current production context resolution plus C0 Top-1 hard routing, and frozen `P1_D05_SIGNAL_UNION`. Primary comparisons are P1−B1, B1−B0, and P1−B0; six-Capability Macro-F1 is primary. Track B cannot select a policy or threshold and cannot modify C0, P1, P2, Gold, or production behaviour.

P2 is a secondary execution diagnostic and does not rewrite the P1 CapabilityPlan. The schema supports post-Gold RAG trigger/attempt and session-state use diagnostics, but not chunk-level evidence-sufficiency accuracy. It contains no governed persistent store, expected persistent IDs, lifecycle targets, or stale/superseded/deleted targets, so Track B persistent retrieval is not evaluable. Persistent-only is `NOT_APPLICABLE_NO_GOVERNED_PERSISTENT_TARGET`; P2 full means RAG plus session state with a strict persistent no-op. Persistent retrieval claims remain confined to the controlled 28 fixtures.
"""
    runbook_doc = f"""# RQ2-D0 One-Shot Packet Generation Runbook

{common}

D1 is a distinct one-shot process. It must write an `ARMED` lock before source access, open and read the raw asset exactly once, validate the in-memory SHA/schema/order/contamination contract, atomically persist and reverify the canonical local case bank, then atomically persist and reverify the two blinded packets and manifest before writing `COMPLETED`.

The only legal state order is `ARMED → OPENED → CASE_BANK_PERSISTED → REVIEW_PACKETS_PERSISTED → COMPLETED`. Retry is never permitted, failure locks are preserved, and no post-COMPLETED write is allowed. This D0 stage exercised that lifecycle twice on wholly synthetic 48-record fixtures, including failure-lock and retry guards. It created no real Track B lock, case bank, packet, or label.
"""
    statistics_doc = f"""# RQ2-D0 Statistical and Contamination Contract

{common}

The primary paired comparison is P1 versus B1; B1 versus B0 and P1 versus B0 are secondary. The paired bootstrap uses 24 governed `contrast_set_id` clusters, 50,000 resamples, seed 20260828, and a 95% percentile interval. The paired sign-flip is also contrast-set-clustered, with 100,000 Monte Carlo draws and seed 20260829. This choice is frozen before D1; no session ID exists. Reports include four registered deltas, confidence intervals, p-values, and per-case utility wins/ties/losses. Negative findings remain valid and do not trigger tuning.

D1 contamination audit runs in memory after the single raw read and before packet persistence. It checks exact and normalised query overlap, query-plus-history overlap, record/source-ID collision, and governed grouping collisions against RQ1 TRAIN/DEV, frozen C0 candidates, Track A safe identities, Authentic22, Synthetic35, context-missing3, and mechanism Fixture28. Conflicting duplicates, duplicate IDs, and forbidden TRAIN/final collisions invalidate the evaluation. Same-label duplicates and clusters are retained with sensitivity reporting rather than post-hoc removal.
"""
    return dict(
        zip(
            DOC_FILENAMES,
            (authority_doc, mapping_doc, scope_doc, runbook_doc, statistics_doc),
        )
    )


def governed_tracked_paths() -> tuple[Path, ...]:
    python_paths = tuple(sorted(HERE.glob("*.py")))
    json_paths = tuple(HERE / name for name in SAFE_JSON_FILENAMES)
    doc_paths = tuple(DOC_ROOT / name for name in DOC_FILENAMES)
    authority_paths = tuple(
        SAFE_AUTHORITY_COPY_ROOT / name for name in sorted(SCHEMA_AUTHORITY_MEMBER_SHA256)
    )
    return tuple(
        sorted(
            (*python_paths, *json_paths, *doc_paths, *authority_paths),
            key=lambda path: path.relative_to(ROOT).as_posix(),
        )
    )


def write_output_checksums() -> Path:
    paths = governed_tracked_paths()
    if any(not path.is_file() or path.is_symlink() for path in paths):
        raise RuntimeError("BLOCKED_RQ2_D0_TEST_FAILURE")
    manifest = HERE / CHECKSUM_NAME
    manifest.write_text(
        "\n".join(
            f"{sha256_file(path)}  {path.relative_to(ROOT).as_posix()}" for path in paths
        )
        + "\n",
        encoding="utf-8",
    )
    return manifest


def finalise_rq2d0(result: RQ2D0Result) -> dict[str, Any]:
    for filename, value in safe_outputs(result).items():
        write_json(HERE / filename, value)
    DOC_ROOT.mkdir(parents=True, exist_ok=True)
    for filename, text in _documents(result).items():
        (DOC_ROOT / filename).write_text(text, encoding="utf-8")
    manifest = write_output_checksums()
    return {
        "status": "PASS",
        "safe_json_count": len(SAFE_JSON_FILENAMES),
        "document_count": len(DOC_FILENAMES),
        "safe_authority_copy_count": len(SCHEMA_AUTHORITY_MEMBER_SHA256),
        "checksum_count": len(manifest.read_text(encoding="utf-8").splitlines()),
        "checksum_manifest_sha256": sha256_file(manifest),
    }


def parse_output_checksums() -> dict[str, str]:
    values: dict[str, str] = {}
    for line in (HERE / CHECKSUM_NAME).read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        digest, relative = line.split(None, 1)
        values[relative.strip().lstrip("*")] = digest
    return values


def _git(*args: str) -> str:
    return subprocess.check_output(
        ["git", *args], cwd=ROOT, text=True, stderr=subprocess.STDOUT
    ).strip()


def expected_review_members() -> tuple[str, ...]:
    referenced = tuple(sorted(parse_output_checksums()))
    return (
        *referenced,
        (HERE / CHECKSUM_NAME).relative_to(ROOT).as_posix(),
        "REVIEW/GIT_STATE.json",
        "REVIEW/DIFF_SUMMARY.txt",
        "REVIEW/REVIEW_CHECKSUMS.sha256",
    )


def _zip_info(name: str) -> zipfile.ZipInfo:
    info = zipfile.ZipInfo(name, FIXED_ZIP_TIME)
    info.compress_type = zipfile.ZIP_DEFLATED
    info.external_attr = 0o100644 << 16
    return info


def build_review_zip() -> dict[str, Any]:
    referenced = parse_output_checksums()
    tracked = set(_git("ls-files").splitlines())
    if not set(referenced) <= tracked:
        raise RuntimeError("BLOCKED_RQ2_D0_REVIEW_PACKAGE_INCOMPLETE")
    payloads: dict[str, bytes] = {}
    for relative, digest in referenced.items():
        value = (ROOT / relative).read_bytes()
        if sha256_bytes(value) != digest:
            raise RuntimeError("BLOCKED_RQ2_D0_REVIEW_PACKAGE_INCOMPLETE")
        payloads[relative] = value
    checksum_relative = (HERE / CHECKSUM_NAME).relative_to(ROOT).as_posix()
    payloads[checksum_relative] = (HERE / CHECKSUM_NAME).read_bytes()
    git_state = {
        "branch": _git("branch", "--show-current"),
        "head": _git("rev-parse", "HEAD"),
        "base_head": STARTING_HEAD,
        "relative_commit_count": int(_git("rev-list", "--count", f"{STARTING_HEAD}..HEAD")),
        "remote_count": len(_git("remote").splitlines()) if _git("remote") else 0,
        "tag_count": len(_git("tag", "--list").splitlines()) if _git("tag", "--list") else 0,
        "worktree_clean": not bool(_git("status", "--porcelain=v1", "--untracked-files=all")),
    }
    if (
        git_state["branch"] != RESULT_BRANCH
        or git_state["relative_commit_count"] != 1
        or git_state["remote_count"]
        or git_state["tag_count"]
        or not git_state["worktree_clean"]
    ):
        raise RuntimeError("BLOCKED_RQ2_D0_GIT_FAILURE")
    payloads["REVIEW/GIT_STATE.json"] = canonical_json_bytes(git_state)
    payloads["REVIEW/DIFF_SUMMARY.txt"] = (
        _git("diff", "--stat", STARTING_HEAD + "..HEAD") + "\n"
    ).encode("utf-8")
    review_checksums = "\n".join(
        f"{sha256_bytes(value)}  {name}" for name, value in sorted(payloads.items())
    ) + "\n"
    payloads["REVIEW/REVIEW_CHECKSUMS.sha256"] = review_checksums.encode("ascii")
    destination = Path.home() / "Downloads" / REVIEW_ZIP_NAME
    if destination.exists():
        raise RuntimeError("BLOCKED_RQ2_D0_REVIEW_PACKAGE_INCOMPLETE")
    with zipfile.ZipFile(destination, "x") as archive:
        for name, value in sorted(payloads.items()):
            archive.writestr(_zip_info(name), value)
    return {
        "status": "PASS",
        "path": str(destination),
        "sha256": sha256_file(destination),
        "size_bytes": destination.stat().st_size,
        "member_count": len(payloads),
        "referenced_output_count": len(referenced),
    }
