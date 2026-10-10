"""Deterministic builder, validator, and review-package gate for RQ2-C0."""

from __future__ import annotations

import ast
import hashlib
import json
from pathlib import Path
import re
import subprocess
from typing import Any, Iterable, Mapping
import zipfile

from evaluation.capability_routing_rq2b_v1.gold_preflight import load_and_validate_gold
from utils.c_full_retrieval_adapter import retrieve_course_evidence

from . import (
    COMMIT_SUBJECT,
    DOC_FILENAMES,
    DOC_ROOT,
    HERE,
    RESULT_BRANCH,
    ROOT,
    SAFE_OUTPUT_FILENAMES,
    STARTING_BRANCH,
    STARTING_HEAD,
    STARTING_PARENT,
    canonical_json_bytes,
    sha256_bytes,
    sha256_file,
    write_canonical_json,
)
from .clarification_audit import build_clarification_audit
from .condition_contract import condition_matrix, metric_contract, validate_condition_isolation
from .episodic_memory_semantics import semantics_contract
from .mechanism_evaluability import build_mechanism_evaluability
from .memory_use_gate_contract import selective_memory_contract
from .rag_gate_contract import dual_gated_rag_contract
from .reachability_audit import build_episodic_reachability_audit
from .rq2b_identity import (
    EXPECTED_GOLD_BUNDLE_SHA256,
    EXPECTED_REVIEW_ZIP_SHA256,
    build_rq2b_identity,
)
from .tool_gate_schema import schema_contract


CHECKSUM_RELATIVE = Path(
    "evaluation/capability_routing_rq2c0_v1/rq2c0_output_checksums_v1.sha256"
)
ALLOWED_CHANGED_PREFIXES = (
    ".gitignore",
    "docs/thesis_mainline/rq2/RQ2C0_",
    "evaluation/capability_routing_rq2c0_v1/",
)
REVIEW_EXTRA_MEMBERS = frozenset(
    {
        "review_metadata/git_state.txt",
        "review_metadata/diff_summary.txt",
        "review_metadata/gitignore_diff.txt",
        "review_metadata/review_checksums.sha256",
    }
)


class RQ2C0ValidationError(RuntimeError):
    pass


def _git(*args: str) -> str:
    return subprocess.check_output(
        ["git", *args], cwd=ROOT, text=True, stderr=subprocess.STDOUT
    ).strip()


def _documents(outputs: Mapping[str, Mapping[str, Any]]) -> dict[str, str]:
    identity = outputs["rq2b_result_identity_v1.json"]
    episodic = outputs["episodic_memory_reachability_audit_v1.json"]
    clarification = outputs["clarification_gate_reachability_audit_v1.json"]
    evaluability = outputs["p2_mechanism_evaluability_v1.json"]
    rag = outputs["dual_gated_rag_contract_v1.json"]
    memory = outputs["selective_episodic_state_use_contract_v1.json"]

    freeze_doc = f"""# RQ2-C0 RQ2-B Result Freeze and Entry Decision

## Frozen entry

RQ2-C0 preserves RQ2-B at approved commit `{STARTING_HEAD}`. The final P1 policy remains `P1_D05_SIGNAL_UNION`, is immutable, and was selected only on Synthetic35. Authentic22 remains descriptive only. RQ2-B metrics were verified by hash and were not recomputed or changed.

The retained RQ2-B interpretation is that P1 improved the synthetic family-grouped development comparison overall, while Episodic Memory recall was zero and Clarification precision was 0.272727. These failures motivate mechanism contracts; they do not authorise changing P1.

## B0 interpretation correction

B0 has no context resolver by design. Its numeric context accuracy remains in the RQ2-B record, but its mechanism interpretation is `CONTEXT_RESOLUTION_NOT_AVAILABLE_BY_DESIGN`, not a measured resolver capability.

## Entry decision

Gold bundle `{identity['gold_bundle_sha256']}` and all eight required local-ledger commitments matched. The mechanism-evaluability result is `{evaluability['result']}`; therefore the next implementation stage is blocked pending separate mechanism fixtures. No RQ2-B result, P1 policy, Gold, production source, threshold, or human annotation was changed.
"""

    reachability_doc = f"""# RQ2-C0 Episodic Memory Semantics and Reachability

## Terms

`WORKING_CONTEXT_AVAILABLE` means recent relevant turns or active structured state already entered ContextEnvelopeV1; it is not a predicted capability. `EPISODIC_STATE_USE_REQUIRED` means the answer depends on prior state. `EPISODIC_RETRIEVAL_REQUIRED` is narrower: the state is absent from the envelope and must be fetched from additional storage. `MISSING_CONTEXT_CLARIFICATION_REQUIRED` means dependable state is unavailable and execution must stop.

The current `episodic_memory` Gold label must not be equated with persistent retrieval.

## Frozen reachability audit

- Episodic Gold positives: {episodic['gold_episodic_positive_count']}.
- B0 TP/FP/FN: {episodic['confusion']['B0']['tp']}/{episodic['confusion']['B0']['fp']}/{episodic['confusion']['B0']['fn']}.
- B1 TP/FP/FN: {episodic['confusion']['B1']['tp']}/{episodic['confusion']['B1']['fp']}/{episodic['confusion']['B1']['fn']}.
- P1 TP/FP/FN: {episodic['confusion']['P1']['tp']}/{episodic['confusion']['P1']['fp']}/{episodic['confusion']['P1']['fn']}.
- Working-context-satisfied mechanism labels: {episodic['mechanism_classification_counts']['SATISFIED_BY_WORKING_CONTEXT']}.
- Additional episodic-retrieval targets: {episodic['mechanism_classification_counts']['REQUIRES_ADDITIONAL_EPISODIC_RETRIEVAL']}.
- Unresolved mechanism labels: {episodic['mechanism_classification_counts']['UNRESOLVED_MECHANISM_LABEL']}.

All eight P1 false negatives received one or more trace-derived explanations. Five were not resolved and failed the Legacy dependency predicate; three had pre-exclusivity episodic evidence suppressed by Clarification; all eight lacked semantic-map episodic support.

The frozen M0/M1/M2 family expands candidate reachability only through existing resolver state, real state objects, and existing Need Signals. Missing context alone never triggers Memory. No long-term vector store or cross-student search is introduced.
"""

    rag_doc = f"""# RQ2-C0 Dual-Gated RAG Contract

## Gate 1: retrieval candidacy

Retrieval may be attempted only when P1 requests `course_retrieval`, P1 does not request Clarification, and deterministic source restrictions authorise course material. Gold and C0 confidence are not triggers.

## Gate 2: evidence sufficiency

The recoverable interface is `{rag['gate_2_evidence_sufficiency']['existing_interface']['interface']}`. Existing statuses are normalised to SUPPORTED, AMBIGUOUS, UNSUPPORTED, NO_RESULT, or NOT_APPLICABLE. Only SUPPORTED evidence with at least one supporting chunk may enter generation. Other chunks are excluded from the prompt; an LLM may not decide support, and existing retrieval thresholds remain unchanged.

The current seven course-positive fixtures were runnable, but produced six SUPPORTED and one NOT_APPLICABLE outcomes. They contain no AMBIGUOUS, UNSUPPORTED, or NO_RESULT mechanism fixture, so they cannot evaluate the second gate's negative discrimination.

This is a contract-only freeze. RAG behaviour and production generation were not changed.
"""

    condition_doc = f"""# RQ2-C0 P2 Condition and Ablation Protocol

Future offline work must compare all four frozen conditions:

- `P1_BASE`: frozen P1; no new RAG or Memory gate.
- `P2_RAG_ONLY`: P1 plus dual-gated RAG; Memory unchanged.
- `P2_MEMORY_ONLY`: P1 plus selective state-use gate; RAG unchanged.
- `P2_FULL`: both mechanism gates.

All conditions retain the same C0, `P1_D05_SIGNAL_UNION`, Gold, case set, ContextEnvelopeV1, and production guards. Comparing only P1 with P2_FULL is prohibited because it cannot identify which mechanism caused a change.

Capability metrics remain Macro-F1, exact-set accuracy, required-capability recall, unnecessary-capability rate, and Jaccard. RAG metrics distinguish candidacy, attempts, sufficiency and unsupported admission. Memory metrics distinguish prior-state dependency, working-context satisfaction, additional retrieval, unnecessary state use, stale/superseded admission, and missing-context unsafe execution. Working context must never be reported as persistent-retrieval success.
"""

    missing = ", ".join(evaluability["missing_requirements"])
    evaluability_doc = f"""# RQ2-C0 Mechanism Evaluability and Limitations

## Result

`{evaluability['result']}`

Synthetic35 contains seven course-retrieval positives, eight episodic-state positives, and three Clarification positives. All eight episodic positives are satisfiable from visible Working Context; none supplies an explicit persistent-retrieval target. Three histories contain an old completed or replaced state, but the structured candidate representation exposes zero stale/superseded negative controls suitable for the frozen freshness gate.

Missing mechanism support: {missing}.

The current data can support selective prior-state-use analysis but cannot establish persistent Memory retrieval performance, long-term Memory performance, or the negative side of the RAG sufficiency gate. Separate fixtures must be human-governed; none was generated or labelled in RQ2-C0.

Authentic22 remains descriptive only, the context-missing registry remains a safety diagnostic, and Track B remains sealed. No model was trained, no provider or network was used, and no P2 or production capability router was implemented.
"""

    return {
        DOC_FILENAMES[0]: freeze_doc,
        DOC_FILENAMES[1]: reachability_doc,
        DOC_FILENAMES[2]: rag_doc,
        DOC_FILENAMES[3]: condition_doc,
        DOC_FILENAMES[4]: evaluability_doc,
    }


def _preflight_report(
    identity: Mapping[str, Any],
    episodic: Mapping[str, Any],
    clarification: Mapping[str, Any],
    evaluability: Mapping[str, Any],
    rag: Mapping[str, Any],
) -> dict[str, Any]:
    return {
        "schema_version": "rq2c0-preflight-report-v1",
        "stage": "RQ2-C0",
        "status": "PASS_CONTRACT_FREEZE",
        "approved_starting_branch": STARTING_BRANCH,
        "approved_starting_head": STARTING_HEAD,
        "approved_starting_parent": STARTING_PARENT,
        "rq2b_review_zip_sha256": EXPECTED_REVIEW_ZIP_SHA256,
        "rq2b_output_checksum_count": identity["rq2b_output_checksum_count"],
        "rq2b_safe_result_count": len(identity["safe_result_sha256"]),
        "local_ledger_identity_count": identity["local_ledger_count"],
        "gold_bundle_sha256": EXPECTED_GOLD_BUNDLE_SHA256,
        "episodic_reachability_audit": episodic["status"],
        "clarification_reachability_audit": clarification["status"],
        "rag_sufficiency_interface": rag["gate_2_evidence_sufficiency"][
            "existing_interface"
        ]["status"],
        "mechanism_evaluability_result": evaluability["result"],
        "entry_decision": evaluability["entry_decision"],
        "rq2b_result_changed": False,
        "p1_policy_changed": False,
        "gold_changed": False,
        "human_annotation_changed": False,
        "p2_implemented": False,
        "production_behavior_changed": False,
        "model_training": False,
        "provider_calls": 0,
        "network_access": False,
        "track_a_access": False,
        "track_b_access": False,
    }


def build_all() -> dict[str, Any]:
    identity = build_rq2b_identity()
    episodic = build_episodic_reachability_audit(write_local=True)
    clarification = build_clarification_audit(write_local=True)
    rag = dual_gated_rag_contract()
    evaluability = build_mechanism_evaluability(write_local=True)
    outputs: dict[str, dict[str, Any]] = {
        "rq2b_result_identity_v1.json": identity,
        "b0_context_metric_interpretation_v1.json": {
            "schema_version": "b0-context-metric-interpretation-v1",
            "stage": "RQ2-C0",
            "status": "FROZEN",
            "b0_context_resolver_implemented": False,
            "b0_context_resolution_prediction": "ALWAYS_FALSE",
            "b0_numeric_context_accuracy_retained": True,
            "mechanism_interpretation": "CONTEXT_RESOLUTION_NOT_AVAILABLE_BY_DESIGN",
            "rq2b_numeric_result_deleted": False,
            "rq2b_numeric_result_overwritten": False,
        },
        "episodic_memory_reachability_audit_v1.json": episodic,
        "episodic_memory_semantics_contract_v1.json": semantics_contract(),
        "clarification_gate_reachability_audit_v1.json": clarification,
        "tool_gate_schema_v1.json": schema_contract(),
        "dual_gated_rag_contract_v1.json": rag,
        "selective_episodic_state_use_contract_v1.json": selective_memory_contract(),
        "p2_condition_contract_v1.json": condition_matrix(),
        "p2_metric_contract_v1.json": metric_contract(),
        "p2_mechanism_evaluability_v1.json": evaluability,
    }
    outputs["rq2c0_preflight_report_v1.json"] = _preflight_report(
        identity, episodic, clarification, evaluability, rag
    )
    if set(outputs) != set(SAFE_OUTPUT_FILENAMES):
        raise RQ2C0ValidationError("RQ2-C0 safe output set mismatch")
    for name, value in outputs.items():
        write_canonical_json(HERE / name, value)
    for name, text in _documents(outputs).items():
        path = DOC_ROOT / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")
    targets = _tracked_checksum_targets()
    manifest = "\n".join(
        f"{sha256_file(path)}  {path.relative_to(ROOT).as_posix()}" for path in targets
    ) + "\n"
    (ROOT / CHECKSUM_RELATIVE).write_text(manifest, encoding="utf-8")
    commitments = {
        path.relative_to(ROOT).as_posix(): sha256_file(path) for path in targets
    }
    return {
        "status": "PASS_CONTRACT_FREEZE",
        "entry_decision": evaluability["entry_decision"],
        "selected_p1_policy": identity["p1_final_policy"],
        "safe_output_count": len(outputs),
        "checksum_reference_count": len(targets),
        "build_commitment_sha256": sha256_bytes(canonical_json_bytes(commitments)),
    }


def _tracked_checksum_targets() -> list[Path]:
    python_files = sorted(HERE.glob("*.py"))
    json_files = [HERE / name for name in SAFE_OUTPUT_FILENAMES]
    docs = [DOC_ROOT / name for name in DOC_FILENAMES]
    targets = [*python_files, *json_files, *docs]
    if len(targets) != len(set(targets)) or any(not path.is_file() for path in targets):
        raise RQ2C0ValidationError("RQ2-C0 checksum target set is incomplete")
    return sorted(targets, key=lambda path: path.relative_to(ROOT).as_posix())


def parse_output_checksums() -> dict[str, str]:
    path = ROOT / CHECKSUM_RELATIVE
    if not path.is_file() or path.is_symlink():
        raise RQ2C0ValidationError("BLOCKED_RQ2_C0_TEST_FAILURE")
    result: dict[str, str] = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        try:
            digest, relative = line.split("  ", 1)
        except ValueError as exc:
            raise RQ2C0ValidationError("invalid checksum line") from exc
        if (
            not re.fullmatch(r"[0-9a-f]{64}", digest)
            or relative in result
            or Path(relative).is_absolute()
            or ".." in Path(relative).parts
        ):
            raise RQ2C0ValidationError("invalid checksum member")
        result[relative] = digest
    return result


def validate_output_checksums() -> dict[str, Any]:
    members = parse_output_checksums()
    failures = [
        relative
        for relative, expected in members.items()
        if not (ROOT / relative).is_file()
        or (ROOT / relative).is_symlink()
        or sha256_file(ROOT / relative) != expected
    ]
    if failures:
        raise RQ2C0ValidationError(
            "BLOCKED_RQ2_C0_TEST_FAILURE: output checksums " + ",".join(failures)
        )
    return {"status": "PASS", "referenced_tracked_output_path_count": len(members)}


def validate_python_ast() -> dict[str, Any]:
    files = sorted(HERE.glob("*.py"))
    for path in files:
        ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    if len(files) != 12:
        raise RQ2C0ValidationError("BLOCKED_RQ2_C0_TEST_FAILURE: python file count")
    return {"status": "PASS", "python_file_count": len(files)}


def validate_safe_outputs() -> dict[str, Any]:
    values = {
        name: json.loads((HERE / name).read_text(encoding="utf-8"))
        for name in SAFE_OUTPUT_FILENAMES
    }
    if any(not isinstance(value, dict) for value in values.values()):
        raise RQ2C0ValidationError("BLOCKED_RQ2_C0_TEST_FAILURE")
    if values["rq2b_result_identity_v1.json"].get("p1_final_policy") != "P1_D05_SIGNAL_UNION":
        raise RQ2C0ValidationError("BLOCKED_RQ2_C0_STARTING_STATE_MISMATCH")
    if values["episodic_memory_reachability_audit_v1.json"].get(
        "all_false_negatives_assigned_reason"
    ) is not True:
        raise RQ2C0ValidationError("BLOCKED_RQ2_C0_EPISODIC_REACHABILITY_AUDIT")
    if values["clarification_gate_reachability_audit_v1.json"].get("synthetic_fp") != 8:
        raise RQ2C0ValidationError("BLOCKED_RQ2_C0_CLARIFICATION_AUDIT_MISMATCH")
    if not validate_condition_isolation(values["p2_condition_contract_v1.json"]):
        raise RQ2C0ValidationError("BLOCKED_RQ2_C0_TEST_FAILURE")
    return {"status": "PASS", "safe_output_count": len(values)}


def _governed_strings() -> list[str]:
    gold = load_and_validate_gold(ROOT)
    strings: set[str] = set()
    for item in (
        *gold.synthetic_gold,
        *gold.authentic_gold,
        *gold.authentic_context_missing_registry,
    ):
        strings.add(item.router_input.current_query)
        for turn in item.router_input.conversation_history:
            content = str(turn.get("content") or "").strip()
            if content:
                strings.add(content)
    for item in gold.synthetic_gold:
        if not item.labels.course_retrieval:
            continue
        result = retrieve_course_evidence(
            item.router_input.current_query,
            backend="v2_4",
            top_k=5,
            context={"retrieval_needed": True, "allow_v1_fallback": False},
        )
        for chunk in result.audit.get("retrieved_chunks") or []:
            text = str(chunk.get("text") or "").strip()
            if len(text) >= 16:
                strings.add(text)
    return sorted(value for value in strings if len(value.strip()) >= 8)


def governed_text_leak_scan() -> dict[str, Any]:
    paths = [ROOT / relative for relative in parse_output_checksums()]
    governed = _governed_strings()
    leaks: list[str] = []
    for path in paths:
        text = path.read_text(encoding="utf-8")
        if ("/" + "Users/") in text or re.search(r"(?:^|\s)/(?:private|var|tmp)/", text):
            leaks.append(f"absolute_path:{path.name}")
        if any(value in text for value in governed):
            leaks.append(f"governed_text:{path.name}")
    if leaks:
        raise RQ2C0ValidationError(
            "BLOCKED_RQ2_C0_TEST_FAILURE: governed text " + ",".join(leaks)
        )
    return {
        "status": "PASS",
        "governed_string_count": len(governed),
        "scanned_tracked_file_count": len(paths),
        "leak_count": 0,
    }


def _changed_paths() -> list[str]:
    tracked = set(
        line for line in _git("diff", "--name-only", STARTING_HEAD, "--").splitlines() if line
    )
    untracked = set(
        line
        for line in _git("ls-files", "--others", "--exclude-standard").splitlines()
        if line
    )
    return sorted(tracked | untracked)


def protected_source_comparison() -> dict[str, Any]:
    changed = _changed_paths()
    forbidden = [
        path
        for path in changed
        if not any(path == prefix or path.startswith(prefix) for prefix in ALLOWED_CHANGED_PREFIXES)
    ]
    if forbidden:
        raise RQ2C0ValidationError(
            "BLOCKED_RQ2_C0_PROTECTED_SOURCE_MUTATED: " + ",".join(forbidden)
        )
    return {
        "status": "PASS",
        "changed_path_count": len(changed),
        "protected_existing_file_change_count": 0,
    }


def staged_allowlist() -> dict[str, Any]:
    staged = [
        line for line in _git("diff", "--cached", "--name-only").splitlines() if line
    ]
    forbidden = [
        path
        for path in staged
        if "/local_artifacts/" in path
        or not any(path == prefix or path.startswith(prefix) for prefix in ALLOWED_CHANGED_PREFIXES)
    ]
    if forbidden:
        raise RQ2C0ValidationError(
            "BLOCKED_RQ2_C0_GIT_FAILURE: staged allowlist " + ",".join(forbidden)
        )
    return {"status": "PASS", "staged_path_count": len(staged)}


def assert_partition_access_allowed(partition: str) -> None:
    if str(partition).upper() in {"TRACK_A", "TRACK_B"}:
        raise PermissionError("sealed evaluation partition")


def validate_local_artifact_ignore() -> dict[str, Any]:
    path = "evaluation/capability_routing_rq2c0_v1/local_artifacts/probe.json"
    result = subprocess.run(
        ["git", "check-ignore", "-q", path], cwd=ROOT, check=False
    )
    if result.returncode != 0:
        raise RQ2C0ValidationError("BLOCKED_RQ2_C0_GIT_FAILURE")
    tracked = _git("ls-files", "evaluation/capability_routing_rq2c0_v1/local_artifacts")
    if tracked:
        raise RQ2C0ValidationError("BLOCKED_RQ2_C0_GIT_FAILURE")
    return {"status": "PASS", "tracked_local_artifact_count": 0}


def validate_all() -> dict[str, Any]:
    if _git("branch", "--show-current") != RESULT_BRANCH:
        raise RQ2C0ValidationError("BLOCKED_RQ2_C0_GIT_FAILURE")
    if subprocess.run(
        ["git", "merge-base", "--is-ancestor", STARTING_HEAD, "HEAD"],
        cwd=ROOT,
        check=False,
    ).returncode != 0:
        raise RQ2C0ValidationError("BLOCKED_RQ2_C0_STARTING_STATE_MISMATCH")
    reports = {
        "python_ast": validate_python_ast(),
        "safe_outputs": validate_safe_outputs(),
        "output_checksums": validate_output_checksums(),
        "governed_text_leak_scan": governed_text_leak_scan(),
        "protected_sources": protected_source_comparison(),
        "staged_allowlist": staged_allowlist(),
        "local_artifacts": validate_local_artifact_ignore(),
    }
    return {
        "status": "PASS_CONTRACT_FREEZE",
        "entry_decision": json.loads(
            (HERE / "p2_mechanism_evaluability_v1.json").read_text(encoding="utf-8")
        )["entry_decision"],
        "reports": reports,
    }


def expected_review_members() -> set[str]:
    return {
        *parse_output_checksums(),
        CHECKSUM_RELATIVE.as_posix(),
        *REVIEW_EXTRA_MEMBERS,
    }


def _zip_info(name: str) -> zipfile.ZipInfo:
    info = zipfile.ZipInfo(name, date_time=(2026, 8, 26, 12, 0, 0))
    info.compress_type = zipfile.ZIP_DEFLATED
    info.external_attr = 0o100644 << 16
    return info


def validate_review_zip(zip_path: Path) -> dict[str, Any]:
    allowed = expected_review_members()
    with zipfile.ZipFile(zip_path) as archive:
        bad = archive.testzip()
        members = [item.filename for item in archive.infolist() if not item.is_dir()]
        if bad is not None or len(members) != len(set(members)) or set(members) != allowed:
            raise RQ2C0ValidationError("BLOCKED_RQ2_C0_TEST_FAILURE: review package")
        for relative, expected in parse_output_checksums().items():
            if hashlib.sha256(archive.read(relative)).hexdigest() != expected:
                raise RQ2C0ValidationError("BLOCKED_RQ2_C0_TEST_FAILURE: review checksum")
    return {
        "status": "PASS",
        "zip_integrity": "PASS",
        "zip_member_count": len(members),
        "referenced_output_member_count": len(parse_output_checksums()),
        "referenced_outputs_present": True,
    }


def build_review_zip(zip_path: Path) -> dict[str, Any]:
    if zip_path.exists():
        raise RQ2C0ValidationError("review ZIP target already exists")
    if _git("branch", "--show-current") != RESULT_BRANCH:
        raise RQ2C0ValidationError("BLOCKED_RQ2_C0_GIT_FAILURE")
    if _git("status", "--porcelain=v1", "--untracked-files=all"):
        raise RQ2C0ValidationError("BLOCKED_RQ2_C0_GIT_FAILURE: worktree not clean")
    if _git("remote") or _git("tag", "--list"):
        raise RQ2C0ValidationError("BLOCKED_RQ2_C0_GIT_FAILURE")
    if int(_git("rev-list", "--count", f"{STARTING_HEAD}..HEAD")) != 1:
        raise RQ2C0ValidationError("BLOCKED_RQ2_C0_GIT_FAILURE")

    payloads = {
        relative: (ROOT / relative).read_bytes() for relative in parse_output_checksums()
    }
    payloads[CHECKSUM_RELATIVE.as_posix()] = (ROOT / CHECKSUM_RELATIVE).read_bytes()
    git_state = "\n".join(
        (
            f"branch: {_git('branch', '--show-current')}",
            f"head: {_git('rev-parse', 'HEAD')}",
            f"parent: {_git('rev-parse', 'HEAD^')}",
            f"starting_head: {STARTING_HEAD}",
            f"relative_commits: {_git('rev-list', '--count', f'{STARTING_HEAD}..HEAD')}",
            "remote_count: 0",
            "tag_count: 0",
            "working_tree: clean",
            "index: clean",
            f"commit_subject: {_git('show', '-s', '--format=%s', 'HEAD')}",
        )
    ) + "\n"
    payloads["review_metadata/git_state.txt"] = git_state.encode("utf-8")
    payloads["review_metadata/diff_summary.txt"] = (
        _git("diff", "--stat", STARTING_HEAD, "HEAD")
        + "\n\n"
        + _git("diff", "--name-status", STARTING_HEAD, "HEAD")
        + "\n"
    ).encode("utf-8")
    payloads["review_metadata/gitignore_diff.txt"] = (
        _git("diff", STARTING_HEAD, "HEAD", "--", ".gitignore") + "\n"
    ).encode("utf-8")
    review_checksums = "\n".join(
        f"{hashlib.sha256(payloads[name]).hexdigest()}  {name}"
        for name in sorted(payloads)
    ) + "\n"
    payloads["review_metadata/review_checksums.sha256"] = review_checksums.encode(
        "utf-8"
    )
    governed = _governed_strings()
    for name, payload in payloads.items():
        if name.endswith((".py", ".json", ".md", ".txt", ".sha256")):
            text = payload.decode("utf-8")
            if ("/" + "Users/") in text or any(value in text for value in governed):
                raise RQ2C0ValidationError("BLOCKED_RQ2_C0_TEST_FAILURE: ZIP leak")
    zip_path.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(zip_path, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        for name in sorted(payloads):
            archive.writestr(_zip_info(name), payloads[name])
    verification = validate_review_zip(zip_path)
    with zipfile.ZipFile(zip_path) as archive:
        lines = archive.read("review_metadata/review_checksums.sha256").decode(
            "utf-8"
        ).splitlines()
        for line in lines:
            expected, name = line.split("  ", 1)
            if hashlib.sha256(archive.read(name)).hexdigest() != expected:
                raise RQ2C0ValidationError("BLOCKED_RQ2_C0_TEST_FAILURE: ZIP checksum")
    return {
        **verification,
        "review_checksum_entries": len(lines),
        "governed_text_leak_scan": "PASS",
        "sha256": sha256_file(zip_path),
        "size_bytes": zip_path.stat().st_size,
        "path": str(zip_path),
    }


def main() -> int:
    if not all((HERE / name).is_file() for name in SAFE_OUTPUT_FILENAMES):
        build_all()
    print(json.dumps(validate_all(), sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
