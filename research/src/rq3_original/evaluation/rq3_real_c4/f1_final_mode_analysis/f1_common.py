"""Local, write-once utilities for the directly authorized F1 analysis."""
from __future__ import annotations

import csv
import hashlib
import io
import json
import os
from pathlib import Path
import subprocess
import sys
from datetime import datetime, timezone

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]
C4 = ROOT / "evaluation/rq3_real_c4"
F0 = C4 / "f0_final_blinded_evaluation_integration"
RI = C4 / "i1_route_integration/restricted_internal"
EXPECTED_ROOT = "/Users/liuming/Downloads/rq2_v2_parallel/rq3-real-c4-i1-route-integration"
EXPECTED_BRANCH = "research/rq3-real-c4-i1-route-integration"
STARTING_HEAD = "e938853783fae771903dd6301c668b7a8ad72b73"
SEED = 20260831
BOOTSTRAP_REPLICATES = 10000
MONTE_CARLO_ASSIGNMENTS = 100000
TIE_TOLERANCE = 1e-12
PRIMARY_OUTCOME = "OVERALL_APPLICABLE_MEAN"
REGISTRY = C4 / "track_d_dataset/c4_real_ablation_mode_registry_v1.json"
GENERIC = ROOT / "evaluation/rq3_v2/rq3_0b4_evaluation_protocol/rq3_statistical_analysis_contract_v1.json"
RECEIPT = HERE / "F1_PRE_UNBLINDING_ANALYSIS_RECEIPT_V1.json"
LEDGER = HERE / "F1_CONTROLLED_UNBLINDING_LEDGER.jsonl"
FINAL_RECEIPT = HERE / "C4_REAL_FINAL_RQ3_ANALYSIS_FREEZE_RECEIPT.json"
REVIEW_ZIP = Path("/Users/liuming/Downloads/RQ3_REAL_F1_FINAL_MODE_ANALYSIS_REVIEW_2026-09-03.zip")
RETAINED = [
    "evaluation/rq3_real_c4/j2d2_corrected_applicability_freeze/C4_REAL_INDEPENDENT_APPLICABILITY_DECISION_FREEZE.md",
    "evaluation/rq3_real_c4/j2d2_corrected_applicability_freeze/STATUS.md",
    "evaluation/rq3_real_c4/j2d2_corrected_applicability_freeze/build_j2d2_phase_a.py",
]
EXPECTED_HASHES = {
    "evaluation/rq3_real_c4/f0_final_blinded_evaluation_integration/C4_REAL_FINAL_BLINDED_EVALUATION_FREEZE_RECEIPT.json": "b5400029eac0d14f271f8238cf5706bff6b039f29d976a7fb94a8ecbe666d5ad",
    "evaluation/rq3_real_c4/f0_final_blinded_evaluation_integration/F0_BLINDED_EVALUATION_ENTRY_RECEIPT_V1.json": "f5bbf1a226806f566be9f4a88d9a4fee4254bb808f93e044b440669f3fa14bff",
    "evaluation/rq3_real_c4/f0_final_blinded_evaluation_integration/F0_CONTROLLED_ACCESS_LEDGER.jsonl": "f0a1bf333a92f5e70410396d75cc2fff5f8fba52521a72aec54b7454e9de5ddb",
    "evaluation/rq3_real_c4/f0_final_blinded_evaluation_integration/c4_real_corrected_judge_results_frozen_v1.jsonl": "a090dd943b12f34f800253c4b18745b494e1a8e4a965c0aa55000dbafc4ae808",
    "evaluation/rq3_real_c4/f0_final_blinded_evaluation_integration/c4_real_corrected_judge_results_frozen_v1.csv": "218794c4788aebef66f566924790dad7df01f307c06bb9ec333d00c98ead3607",
    "evaluation/rq3_real_c4/i1_route_integration/restricted_internal/c4_real_corrected_condition_result_projection_f0_v1.jsonl": "913d3ce45ccce9ead5ce6ed630c28d2d159a10fd1f78b02348fb83344bbf8e5d",
    "evaluation/rq3_real_c4/f0_final_blinded_evaluation_integration/c4_real_corrected_human_ratings_A_frozen_v1.csv": "da4e4e08f975d7439abedc4980f077fe57b9aacc4611db8f4cd09f3abf7deb43",
    "evaluation/rq3_real_c4/f0_final_blinded_evaluation_integration/c4_real_corrected_human_ratings_B_frozen_v1.csv": "98f485320dbcb46d9c9c705933bdc5e707246d2a527a50c8f5c9d381a2a8c418",
    "evaluation/rq3_real_c4/f0_final_blinded_evaluation_integration/c4_real_blinded_human_human_agreement_v1.json": "3e703eff3902461572e40a49c3b5056db4b9019335b976c47916d17049be4d39",
    "evaluation/rq3_real_c4/f0_final_blinded_evaluation_integration/c4_real_blinded_human_llm_agreement_v1.json": "3e543f679348d5bc55c83b7f8c23354e8bef7e49a5bce1cd12ddc73f1f498ac7",
    "evaluation/rq3_real_c4/track_d_dataset/c4_real_ablation_mode_registry_v1.json": "998884326cbb448360d517e9792b46598d9df5733628ceefadf444d5316c960c",
    "evaluation/rq3_real_c4/track_d_dataset/C4_REAL_DATASET_AND_ABLATION_METHOD.md": "af3dfc16647c1089b8c6e17444c9ff4e10805f763dd63e36dcfef0f56456f05e",
    "evaluation/rq3_real_c4/track_d_dataset/final_62_scenario_identity_v1.json": "17e9d3a34c2d080a855246fe05b7150c9e7c5b2a64b9fcc7e47c043e9ff82c9a",
    "evaluation/rq3_real_c4/track_d_dataset/original_25_subset_identity_v1.json": "ec527fa008056c0ba39acaa53029b4bb5d42f3d58a1e385d0299fcc9c063adc6",
    "evaluation/rq3_real_c4/track_d_dataset/memory_scenario_registry_v1.csv": "a058780f81a46997d545f364f44eb9acba0c564bfb684870c7ddc000343d1d5c",
    "evaluation/rq3_v2/rq3_0b4_evaluation_protocol/rq3_statistical_analysis_contract_v1.json": "cddf95489eb5142064ca78902555946a74e43b30e9195dc90d456c16fc18d8b0",
    "evaluation/rq3_real_c4/i1_route_integration/restricted_internal/c4_real_i1_blinding_hmac_key.bin": "199db23c86b0dd824edaff2d5b40da12761c9aa76bf2fb9d902952ab376481b5",
}
CONTRASTS = [
    ("C1_MINUS_C0", "C1_EVIDENCE", "C0_ORIGINAL", "PRIMARY_ADD_ONE"),
    ("C2_MINUS_C1", "C2_EVIDENCE_RAG", "C1_EVIDENCE", "PRIMARY_ADD_ONE"),
    ("C3_MINUS_C1", "C3_EVIDENCE_MEMORY", "C1_EVIDENCE", "PRIMARY_ADD_ONE"),
    ("C4_MINUS_C1", "C4_EVIDENCE_PLANNING", "C1_EVIDENCE", "PRIMARY_ADD_ONE"),
    ("C5_MINUS_C1", "C5_FULL_C4", "C1_EVIDENCE", "PRIMARY_ADD_ONE"),
    ("C5_MINUS_C5_MINUS_RAG", "C5_FULL_C4", "C5_MINUS_RAG", "TARGETED_REMOVE_ONE"),
    ("C5_MINUS_C5_MINUS_MEMORY", "C5_FULL_C4", "C5_MINUS_MEMORY", "TARGETED_REMOVE_ONE"),
    ("C5_MINUS_C5_MINUS_PLANNING", "C5_FULL_C4", "C5_MINUS_PLANNING", "TARGETED_REMOVE_ONE"),
]
CRITERIA = ["CLARITY", "PERSONALISATION", "ACTIONABILITY", "CONTEXT_AWARENESS",
            "MOTIVATION_AND_ENGAGEMENT", "RELIABILITY", "MULTI_PAGE_COHESIVENESS", "ERROR_HANDLING"]
SECONDARY = CRITERIA + ["EVIDENCE_FAITHFULNESS", "UNSUPPORTED_CLAIM_COUNT"]
PROHIBITED_ACTION_COUNTS = {x: 0 for x in ["provider_calls", "network_calls", "judge_executions",
    "response_generations", "human_rating_actions", "human_amendment_actions", "score_modifications",
    "applicability_modifications", "rag_executions", "memory_executions", "planning_executions",
    "evidence_synthesis_executions", "p3_executions", "streamlit_launches"]}


def offline_audit(event, args):
    if event in {"socket.connect", "socket.connect_ex", "socket.getaddrinfo", "socket.bind"}:
        raise RuntimeError("F1_NETWORK_OPERATION_FORBIDDEN")


sys.addaudithook(offline_audit)


def now():
    return datetime.now(timezone.utc).isoformat(timespec="microseconds")


def sha_bytes(data):
    return hashlib.sha256(data).hexdigest()


def sha(path):
    """Byte hashing only, without interpreting any source identities or values."""
    h = hashlib.sha256()
    with Path(path).open("rb") as f:
        for b in iter(lambda: f.read(1024 * 1024), b""):
            h.update(b)
    return h.hexdigest()


def canonical_bytes(obj):
    return json.dumps(obj, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()


def read_json(path):
    path = Path(path).resolve()
    if path.is_relative_to(RI):
        raise RuntimeError("RESTRICTED_IDENTITY_READ_REQUIRES_F1_GUARD")
    return json.loads(path.read_text())


def git(*args):
    return subprocess.check_output(["git", *args], cwd=ROOT, text=True).strip()


def fsync_dir(path):
    fd = os.open(Path(path), os.O_RDONLY)
    try:
        os.fsync(fd)
    finally:
        os.close(fd)


def write_once_bytes(path, content, mode=0o644):
    path = Path(path).resolve()
    if not (path.is_relative_to(HERE) or (path.parent == RI and path.name.startswith("c4_real_f1_"))):
        raise RuntimeError("F1_OUTPUT_OUTSIDE_AUTHORIZED_SCOPE")
    path.parent.mkdir(parents=True, exist_ok=True)
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, mode)
    with os.fdopen(fd, "wb") as f:
        os.fchmod(f.fileno(), mode)
        f.write(content)
        f.flush()
        os.fsync(f.fileno())
    fsync_dir(path.parent)
    return sha(path)


def write_json(path, obj, mode=0o644):
    return write_once_bytes(path, (json.dumps(obj, indent=2, sort_keys=True, ensure_ascii=False,
                                             allow_nan=False) + "\n").encode(), mode)


def write_jsonl(path, rows, mode=0o644):
    return write_once_bytes(path, b"".join(canonical_bytes(x) + b"\n" for x in rows), mode)


def csv_bytes(rows, fields=None):
    fields = fields or list(rows[0])
    out = io.StringIO(newline="")
    w = csv.DictWriter(out, fieldnames=fields, lineterminator="\n")
    w.writeheader()
    for row in rows:
        w.writerow({k: (json.dumps(v, sort_keys=True, separators=(",", ":"), allow_nan=False)
                          if isinstance(v, (dict, list)) else v) for k, v in row.items()})
    return out.getvalue().encode()


def write_csv(path, rows, fields=None, mode=0o644):
    return write_once_bytes(path, csv_bytes(rows, fields), mode)


def file_metadata(path, rows=None):
    result = {"filename": Path(path).name, "sha256": sha(path)}
    if rows is not None:
        result["row_count"] = rows
    return result
