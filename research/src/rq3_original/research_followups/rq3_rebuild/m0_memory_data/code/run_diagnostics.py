"""Bounded, single-pass forced diagnostics of the frozen retriever on new fixtures."""
from __future__ import annotations
import argparse
from collections import Counter, defaultdict
import csv
import importlib.metadata
import json
from pathlib import Path
import platform
import subprocess
import sys
import tempfile
from common import OWNED, disable_network, sha, object_sha, write_json, utc
disable_network()
from fixture_validation import validate_fixtures, coverage
from state_harness import (setup_episode, backup_closed, target_read, availability,
    ReadOnlyStore, snapshot, REPO)
from utils.c4_memory.c4_memory_retriever import FrozenLocalMPNetBackend, MPNET_REVISION, MPNET_REQUIRED_HASHES

MODEL = Path("/Users/liuming/Downloads/duteaiapp_cfull_semantic_integrated_v1_副本3") / (
    "semantic_runtime/models/all-mpnet-base-v2/" + MPNET_REVISION)

def runtime_backend():
    receipt = {"execution_utc": utc(), "python_executable": sys.executable, "python_version": sys.version,
        "platform": platform.platform(), "model_path": str(MODEL), "device": "cpu",
        "path_authority": "Inherited utils/c4_rag/corpus.py CANONICAL_MPNET_ROOT; required hashes in frozen Memory contract",
        "network": "DISABLED_BY_ENVIRONMENT_AND_PROCESS_AUDIT_HOOK", "downloads": 0,
        "packages": {}, "snapshot_files": [], "model_open_events": []}
    for n in ("torch", "transformers", "sentence-transformers", "numpy", "tokenizers", "safetensors"):
        try: receipt["packages"][n] = importlib.metadata.version(n)
        except importlib.metadata.PackageNotFoundError: receipt["packages"][n] = "NOT_INSTALLED"
    if not MODEL.is_dir():
        receipt.update(status="NOT_RUN", reason="FROZEN_LOCAL_MODEL_ABSENT")
        return None, receipt
    for p in sorted(MODEL.rglob("*")):
        if p.is_file() and (p.name in MPNET_REQUIRED_HASHES or p.suffix in (".json", ".txt")):
            observed = sha(p)
            expected = MPNET_REQUIRED_HASHES.get(p.relative_to(MODEL).as_posix())
            receipt["snapshot_files"].append({"path": str(p), "bytes": p.stat().st_size, "sha256": observed,
                "frozen_expected_sha256": expected,
                "verification_scope": "FROZEN_CONTRACT" if expected else "OBSERVED_ANCILLARY_CONFIGURATION"})
    try:
        # Verify required files before optional native code starts.
        FrozenLocalMPNetBackend(MODEL, verify_hashes=True)
        backend = IsolatedBackend(MODEL, receipt)
        receipt.update(status="LOADED", backend_identity=dict(backend.identity),
                       actual_parameter_device=backend.ready["actual_parameter_device"])
        return backend, receipt
    except Exception as exc:
        receipt.update(status="NOT_RUN", reason=type(exc).__name__ + ": " + str(exc)[:500])
        return None, receipt


class IsolatedBackend:
    """Local stdio transport for the unchanged frozen encoder, not an external provider."""
    def __init__(self, model, receipt):
        self.receipt = receipt
        (OWNED / ".runtime").mkdir(exist_ok=True)
        self.stderr_file = tempfile.TemporaryFile(mode="w+t", dir=OWNED / ".runtime")
        self.process = subprocess.Popen([sys.executable, "-B", str(OWNED / "code/semantic_worker.py"), str(model)],
            stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=self.stderr_file, text=True, bufsize=1)
        self.ready = self.receive()
        self._identity = self.ready["identity"]
        receipt["model_open_events"] = self.ready["model_open_events"]

    def receive(self):
        line = self.process.stdout.readline()
        if not line:
            rc = self.process.wait()
            self.stderr_file.seek(0)
            self.receipt["worker_exit_code"] = rc
            self.receipt["worker_stderr"] = self.stderr_file.read()[-4000:]
            self.close()
            raise RuntimeError(f"ISOLATED_NATIVE_RUNTIME_EXIT:{rc}")
        value = json.loads(line)
        if "error" in value:
            self.close()
            raise RuntimeError(value["error"])
        return value

    @property
    def identity(self):
        return self._identity

    def encode(self, texts):
        self.process.stdin.write(json.dumps({"texts": list(texts)}) + "\n")
        self.process.stdin.flush()
        return self.receive()["vectors"]

    def close(self):
        if self.process.poll() is None:
            self.process.terminate()
            self.process.wait(timeout=10)
        for stream in (self.process.stdin, self.process.stdout, self.stderr_file):
            if stream and not stream.closed: stream.close()

def evaluate_case(runtime, expected, workdir, backend):
    databases, aliases, receipts = setup_episode(runtime, Path(workdir) / "preconditioned")
    all_ids = set()
    for course, database in databases.items():
        with ReadOnlyStore(database, clock=lambda: runtime["target"]["as_of"]) as store:
            all_ids.update(r["memory_id"] for r in snapshot(store)["memories"])
    # Evaluation-only setup assertions do not provide IDs to target_read.
    assert {aliases[f] for f in expected["expected_stored_fact_ids"]} == all_ids
    rejected = {r["fact_id"]: r["outcome"]["reason_code"] for r in receipts
                if r["event"] == "SETUP_WRITE_POLICY" and not r["outcome"]["accepted"]}
    assert rejected == expected["expected_write_rejections"]
    original = databases[runtime["target"]["course_id"]]
    observed = availability(original, runtime["target"], aliases)
    assert set(observed["active_authorized_fact_ids"]) == set(expected["expected_active_authorized_fact_ids"])
    receipts.append({"event": "EVALUATION_ONLY_SETUP_ASSERTION", "execution_utc": utc(),
        "exact_stored_id_check": True, "active_authorized_id_check": True,
        "assertion_inputs_never_passed_to_retrieval": True})
    traces, rows = [], []
    for gate in ("FORCED_ENGINEERING_DIAGNOSTIC", "GATE_OFF_STUB"):
        clone_dir = Path(workdir) / gate
        clone_dir.mkdir()
        clones = {}
        for course, database in databases.items():
            clone = clone_dir / database.name
            backup_closed(database, clone)
            clones[course] = clone
            with ReadOnlyStore(database, clock=lambda: runtime["target"]["as_of"]) as s, \
                 ReadOnlyStore(clone, clock=lambda: runtime["target"]["as_of"]) as c:
                assert snapshot(s) == snapshot(c)
            receipts.append({"event": "CONDITION_BACKUP_CLONE", "execution_utc": utc(),
                "condition": gate, "course_id": course, "clone_method": "SQLITE_CONNECTION_BACKUP",
                "source_closed_before_clone": True, "same_state": True, "same_learner_ids": True,
                "source_db_sha256": sha(database), "clone_db_sha256": sha(clone)})
        target_clone = clones[runtime["target"]["course_id"]]
        db_before = sha(target_clone)
        read = target_read(target_clone, runtime["target"], backend, gate=gate)
        assert sha(target_clone) == db_before
        inverse = {v: k for k, v in aliases.items()}
        selected = read["envelope"]["selected_memory_items"]
        retrieved = [inverse.get(s["memory_id"], "UNKNOWN_NATIVE_ID:" + s["memory_id"]) for s in selected]
        status, missing = coverage(expected["required_memory_fact_ids"], retrieved,
            ran=gate != "GATE_OFF_STUB", clarification=expected["clarification_required"])
        unauthorized = sorted(set(retrieved) - set(observed["active_authorized_fact_ids"]))
        wrong_learner = [s["memory_id"] for s in selected if any(r["memory_id"] == s["memory_id"] and
            r["student_id"] != runtime["target"]["learner_id"] for r in observed["records"])]
        assert not unauthorized and not wrong_learner
        assert gate != "GATE_OFF_STUB" or read["retriever_calls"] == 0
        nonselected = sorted(set(observed["active_authorized_fact_ids"]) - set(retrieved))
        public = read["public_retrieval_diagnostics"]
        row = {"case_id": runtime["case_id"], "family_id": runtime["family_id"], "condition": gate,
            "flags": "|".join(runtime["flags"]), "coverage_category": expected["coverage_category"],
            "persistent_need": expected["persistent_retrieval_needed"], "source_class": expected["source_class"],
            "setup_row_count_all_courses": len(all_ids), "setup_row_count_target_course": observed["stored_row_count"],
            "other_course_rows_excluded_by_partition": len(all_ids) - observed["stored_row_count"],
            "setup_write_policy_rejections": rejected, "active_sql_count": observed["active_sql_count"],
            "active_authorized_count": observed["active_authorized_count"],
            "setup_expected_id_check": "VERIFIED_EVALUATION_ONLY",
            "provider_entered": read["provider_entered"], "retriever_calls": read["retriever_calls"],
            "semantic_mode": "FROZEN_LOCAL_MPNET_HYBRID" if backend is not None else "LEXICAL_ONLY_SEMANTIC_NOT_RUN",
            "semantic_executed": (public != "NOT_ENTERED" and public["semantic_backend"].get("implementation") is not None
                and not any(x.startswith("SEMANTIC_BACKEND_UNAVAILABLE") for x in public["limitations"])
                and public["active_candidate_count"] > public["visible_history_excluded_count"]),
            "status": read["envelope"]["status"], "execution_success": True, "coverage_status": status,
            "expected_fact_ids": expected["required_memory_fact_ids"], "retrieved_fact_ids": retrieved,
            "missing_fact_ids": missing, "missing_constraints": [c for c in expected["expected_constraints"] if c["fact_id"] in missing],
            "selected_types": [s["memory_type"] for s in selected],
            "selected_scores": {inverse[s["memory_id"]]: s["relevance_components"] for s in selected},
            "active_candidate_ids_before_relevance": observed["active_authorized_fact_ids"],
            "nonselected_fact_ids": nonselected, "nonselected_candidate_scores": read["nonselected_scores"],
            "exclusions_before_relevance": observed["exclusions"],
            "visible_history_excluded_count": public["visible_history_excluded_count"] if public != "NOT_ENTERED" else "NOT_ENTERED",
            "conflict_excluded_count": public["conflict_excluded_count"] if public != "NOT_ENTERED" else "NOT_ENTERED",
            "wrong_learner_fact_ids": wrong_learner, "stale_or_unauthorized_fact_ids": unauthorized,
            "clarification_required": expected["clarification_required"],
            "retrieved_facts_not_required_by_sidecar": sorted(set(retrieved) - set(expected["required_memory_fact_ids"])),
            "limitations": read["envelope"]["limitations"], "target_state_writes": read["target_state_writes"],
            "compiler_retention": "NOT_RUN", "planner_consumption": "NOT_RUN", "final_utility": "NOT_RUN"}
        rows.append(row)
        traces.append({"case_id": runtime["case_id"], "target_runtime_sha256": object_sha(runtime["target"]),
            "read": read, "evaluation_only_observation": {k: v for k, v in observed.items() if k != "records"}})
    for r in receipts: r["case_id"] = runtime["case_id"]
    return rows, receipts, traces

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--storage-only", action="store_true", help="Explicitly labelled lexical mechanics, never full hybrid success")
    args = parser.parse_args()
    args.output.resolve().relative_to(OWNED)
    args.output.mkdir(parents=True, exist_ok=False)
    runtime, evaluation = validate_fixtures()
    begin = utc()
    backend, identity = (None, {"status": "NOT_RUN", "reason": "EXPLICIT_STORAGE_ONLY"}) if args.storage_only else runtime_backend()
    write_json(args.output / "RUNTIME_IDENTITY.json", identity)
    temp_root = OWNED / ".runtime"
    temp_root.mkdir(exist_ok=True)
    rows, receipts, traces = [], [], []
    for r in runtime:
        with tempfile.TemporaryDirectory(prefix=r["case_id"] + "-", dir=temp_root) as td:
            rr, re, tr = evaluate_case(r, evaluation[r["case_id"]], td, backend)
            rows.extend(rr); receipts.extend(re); traces.extend(tr)
        print(r["case_id"], rr[0]["status"], rr[0]["coverage_status"], flush=True)
    failures = [r for r in rows if any(s.startswith("SEMANTIC_BACKEND_UNAVAILABLE") for s in r["limitations"])]
    for f in identity.get("snapshot_files", []):
        f["unchanged_after_diagnostics"] = sha(f["path"]) == f["sha256"]
        assert f["unchanged_after_diagnostics"]
    if backend is not None:
        identity["backend_identity"] = dict(backend.identity)
        identity["status"] = "EXECUTED" if not failures else "PARTIAL_RUNTIME_ERRORS"
        backend.close()
    identity["loaded_model_hashes"] = dict(backend.identity)["verified_file_sha256"] if backend else "UNKNOWN_MODEL_LOAD_DID_NOT_COMPLETE"
    identity["semantic_target_count"] = sum(r["semantic_executed"] for r in rows)
    identity["open_observation_limit"] = "Python audit open events are returned only after worker readiness; native tokenizer/mmap reads may not emit Python events. Listed snapshot files hashed before and after diagnostics; hash verification is not successful model loading."
    write_json(args.output / "RUNTIME_IDENTITY.json", identity)
    with (args.output / "MEMORY_FIXTURE_DIAGNOSTIC.csv").open("w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0]))
        w.writeheader()
        for row in rows:
            w.writerow({k: json.dumps(v, ensure_ascii=False) if isinstance(v, (list, dict)) else v for k, v in row.items()})
    for name, values in (("MEMORY_SETUP_AND_REOPEN_RECEIPTS.jsonl", receipts), ("MEMORY_TARGET_TRACES.jsonl", traces)):
        with (args.output / name).open("w") as f:
            for value in values: f.write(json.dumps(value, ensure_ascii=False) + "\n")
    forced = [r for r in rows if r["condition"] == "FORCED_ENGINEERING_DIAGNOSTIC"]
    groups = {}
    for field in ("source_class", "setup_row_count_all_courses"):
        groups[field] = {}
        for row in forced:
            key = row[field] if field == "source_class" else ("RECORD_PRESENT" if row[field] else "RECORD_ABSENT")
            counter = groups[field].setdefault(str(key), Counter())
            counter["families"] += 1; counter["status_" + row["status"]] += 1
            counter["coverage_" + row["coverage_status"]] += 1
    summary = {"execution_start_utc": begin, "execution_end_utc": utc(), "families": len(runtime),
        "target_reads": len(rows), "execution_success_count": sum(r["execution_success"] for r in rows),
        "forced_coverage_counts": dict(Counter(r["coverage_status"] for r in forced)),
        "forced_status_counts": dict(Counter(r["status"] for r in forced)), "source_groups": groups,
        "receipt_count": len(receipts), "reopen_count": sum(r["event"] == "CLOSED_AND_REOPENED_READ_ONLY" for r in receipts),
        "clone_count": sum(r["event"] == "CONDITION_BACKUP_CLONE" for r in receipts),
        "setup_accepted_operations": sum(r["event"] == "SETUP_WRITE_POLICY" and r["outcome"]["accepted"] for r in receipts),
        "setup_rejected_operations": sum(r["event"] == "SETUP_WRITE_POLICY" and not r["outcome"]["accepted"] for r in receipts),
        "target_state_writes": 0, "provider_calls_external": 0, "llm_calls": 0, "judge_calls": 0,
        "p3_invocations": 0, "semantic_runtime_status": identity["status"], "semantic_runtime_error_rows": len(failures),
        "statistical_tests": "NOT_RUN", "quality_score": "NOT_RUN", "databases": "FRESH_SYNTHETIC_TEMPORARIES_REMOVED_AFTER_RECEIPTS"}
    write_json(args.output / "DIAGNOSTIC_SUMMARY.json", summary)

if __name__ == "__main__": main()
