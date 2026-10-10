#!/usr/bin/env python3
"""Passive RQ3-B audit: frozen joins, corpus inventory, and text serialization only.

Never execute a router, research-data retrieval, encoder, generator, Judge, or
historical validator. No raw payloads, learner IDs, ratings, or answers are output.
Use --write once to create this audit's JSON/CSV. Without it, inspect in memory.
"""
from __future__ import annotations

import argparse
import ast
from collections import Counter, defaultdict
import copy
import csv
import hashlib
import io
import json
from pathlib import Path
import socket
import subprocess
import sys
from unittest.mock import patch
from zipfile import ZipFile

OUT = Path(__file__).resolve().parent
ROOT = OUT.parents[2]
BASE = "25373ba4bdd152634f0f8913ab38931cd17c1cde"
BRANCH = "research/rq3-explain-audit-b-pipeline"
C4 = ROOT / "evaluation/rq3_real_c4"
I0 = C4 / "i0_integration"
I1 = C4 / "i1_route_integration"
OLD = Path("/Users/liuming/Downloads/duteaiapp_cfull_semantic_integrated_v1_副本3")
HANDOFF = Path("/Users/liuming/Downloads/RQ3_REASSESSMENT_HANDOFF_2026-09-06.zip")
HANDOFF_PREFIX = "RQ3_REASSESSMENT_HANDOFF_2026-09-06/"
FULL = "C5_FULL_C4"


def canonical(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True,
                      separators=(",", ":"), allow_nan=False).encode()


def digest(value):
    return hashlib.sha256(value).hexdigest()


def unique_index(rows, key):
    indexed = {}
    for row in rows:
        identity = key(row)
        if identity in indexed:
            raise ValueError("DUPLICATE_SOURCE_IDENTITY")
        indexed[identity] = row
    return indexed


def csv_bytes(rows, fields, lineterminator="\r\n"):
    stream = io.StringIO(newline="")
    writer = csv.DictWriter(stream, fieldnames=fields, lineterminator=lineterminator)
    writer.writeheader()
    writer.writerows(rows)
    return stream.getvalue().encode()


class Sources:
    def __init__(self):
        self.entries = {}

    def read(self, path, expected=None):
        path = Path(path).resolve()
        data = path.read_bytes()
        entry = {"path": str(path), "bytes": len(data), "sha256": digest(data)}
        if expected is not None:
            entry.update(expected_sha256=expected, expected_hash_matches=digest(data) == expected)
        self.entries[str(path)] = {**self.entries.get(str(path), {}), **entry}
        return data

    def obj(self, path, expected=None):
        return json.loads(self.read(path, expected))

    def rows(self, path):
        return [json.loads(line) for line in self.read(path).decode().splitlines() if line.strip()]

    def table(self, path):
        return list(csv.DictReader(io.StringIO(self.read(path).decode("utf-8-sig"))))


class BlockNetwork(socket.socket):
    attempts = 0

    def connect(self, *args, **kwargs):
        type(self).attempts += 1
        raise RuntimeError("NETWORK_DISABLED_FOR_AUDIT")

    connect_ex = connect


def git(*args):
    return subprocess.check_output(["git", *args], cwd=ROOT).decode().strip()


def response_identity_bridge(sources, frozen_payload_hashes):
    """Join only the non-answer R3 provenance registry, never raw responses."""
    registry = sources.rows(C4 / "r3d1_response_integration/c4_real_r3_response_source_registry_v1.jsonl")
    sources.read(C4 / "r3d1_response_integration/C4_REAL_R3_FINAL_RESPONSE_FREEZE_REPORT.md")
    bound = {r["provider_payload_sha256"] for r in registry}
    execution_sources = Counter(r["selected_execution_source"] for r in registry)
    identities = []
    for sub, name in [
        ("r3a_response_regeneration_shard_a", "generation_execution_source_manifest_v1.json"),
        ("r3b_response_regeneration_shard_b", "generation_execution_source_manifest_v1.json"),
        ("r3c_response_regeneration_shard_c", "generation_execution_source_manifest_v1.json"),
        ("r3c1_response_continuation", "continuation_execution_source_manifest_v1.json"),
    ]:
        manifest = sources.obj(C4 / sub / name)
        identity_key = "frozen_scientific_identity" if "frozen_scientific_identity" in manifest else "frozen_generation_identity"
        identities.append({"source": sub, "top_level_status": manifest.get("status"),
                           "identity_source_key": identity_key,
                           "generation_identity": manifest[identity_key]})
    return {"registry_rows": len(registry), "unique_payload_hashes": len(bound),
            "payload_set_equals_frozen_v3": bound == frozen_payload_hashes,
            "selected_source_counts": dict(execution_sources),
            "execution_manifest_identities": identities, "answer_bodies_read": False,
            "note": "Registry identity bridge; no new validation or scoring of response content."}


def native_setup_migration(sources, preconditions):
    data = sources.read(OLD / "evaluation/unified_benchmark_scenarios.jsonl",
                        "2df88a153101b39872154ed1ef339d6639e3ea28fac7df0eb42dd8bc9d998ce4")
    native = {r["scenario_id"]: r for r in map(json.loads, data.splitlines())}
    # Only these original query/history fields are used; no Gold or prediction field is used.
    return [{"scenario_id": sid, "original_history_turns": len(native[sid]["conversation_history"]),
             "setup_equals_original_history": p["earlier_session_setup"] == native[sid]["conversation_history"],
             "target_query_equals_original": p["target_query"] == native[sid]["student_query"],
             "target_visible_history_empty": p["target_session_visible_history"] == []}
            for sid, p in preconditions.items()]


def inspect():
    if Path.cwd().resolve() != ROOT or git("branch", "--show-current") != BRANCH:
        raise RuntimeError("INCOMPATIBLE_WORKSPACE_STOP")
    # The completed audit commit may descend from BASE; historical paths must be unchanged.
    scope = OUT.relative_to(ROOT).as_posix()
    if git("diff", BASE, "--", ".", f":(exclude){scope}"):
        raise RuntimeError("HISTORICAL_TRACKED_CHANGE_STOP")
    sources = Sources()
    z = ZipFile(io.BytesIO(sources.read(HANDOFF)))
    package = json.loads(z.read(HANDOFF_PREFIX + "PACKAGE_MANIFEST.json"))
    members = []
    for row in package["files"]:
        data = z.read(HANDOFF_PREFIX + row["path"])
        members.append({"member": row["path"], "bytes": len(data), "sha256": digest(data),
                        "manifest_matches": len(data) == row["bytes"] and digest(data) == row["sha256"]})
    claims = json.loads(z.read(HANDOFF_PREFIX + "TRACE_AUDIT_PROVENANCE.json"))
    for row in claims["input_sources"]:
        candidate = I1 / row["filename"]
        if not candidate.exists():
            candidate = C4 / "track_d_dataset" / row["filename"]
        sources.read(candidate, row["sha256"])

    mechanism = sources.rows(I1 / "c4_real_condition_mechanism_records_frozen_v1.jsonl")
    by_condition = unique_index(mechanism, lambda r: (r["scenario_id"], r["mode"]))
    full = sorted((r for r in mechanism if r["mode"] == FULL), key=lambda r: r["scenario_id"])
    registry = sources.table(C4 / "track_d_dataset/memory_scenario_registry_v1.csv")
    cohort = unique_index([r for r in registry if r["persistent_replay_eligible"] == "YES"],
                          lambda r: r["unified_scenario_id"])
    fields = ["scenario_id", "route_signature", "rag_status", "memory_status", "planning_status",
              "persistent_replay_cohort", "memory_design_class", "memory_control_class"]
    table = []
    for row in full:
        reference = cohort.get(row["scenario_id"], {})
        table.append(dict(scenario_id=row["scenario_id"], route_signature=row["route_signature"],
                          rag_status=row["typed_statuses"]["rag"], memory_status=row["typed_statuses"]["memory"],
                          planning_status=row["typed_statuses"]["planning"],
                          persistent_replay_cohort="YES" if reference else "NO",
                          memory_design_class=reference.get("memory_class", ""),
                          memory_control_class=reference.get("control_status", "")))
    nine = [{**r, "student_query": cohort[r["scenario_id"]]["student_query"],
             "expected_retrieval_operation": cohort[r["scenario_id"]]["expected_target_retrieval_operation"]}
            for r in table if r["scenario_id"] in cohort]
    csv_reconciliation = {}
    for name, data in [("RQ3_62_SCENARIO_MODULE_AUDIT.csv", csv_bytes(table, fields)),
                       ("RQ3_MEMORY_NINE_CASE_AUDIT.csv", csv_bytes(nine, fields + ["student_query", "expected_retrieval_operation"]))]:
        csv_reconciliation[name] = {"independent_sha256": digest(data),
                                    "handoff_sha256": digest(z.read(HANDOFF_PREFIX + name)),
                                    "byte_identical": data == z.read(HANDOFF_PREFIX + name)}

    inputs = unique_index(sources.rows(I0 / "c4_real_p3_route_input_manifest_v1.jsonl"), lambda r: r["scenario_id"])
    duplicate_inputs = defaultdict(list)
    for r in inputs.values():
        h = digest(canonical(r["semantic_input"]))
        if h != r["semantic_input_sha256"]:
            raise ValueError("FROZEN_SEMANTIC_INPUT_HASH_MISMATCH")
        duplicate_inputs[h].append(r["scenario_id"])
    preconditions = unique_index(sources.rows(I0 / "c4_real_memory_preconditioning_manifest_v1.jsonl"), lambda r: r["scenario_id"])
    receipts = unique_index(sources.rows(I1 / "c4_real_memory_preconditioning_receipts_v1.jsonl"), lambda r: (r["scenario_id"], r["mode"]))
    memories = unique_index(sources.rows(I1 / "c4_real_condition_memory_results_frozen_v1.jsonl"), lambda r: (r["scenario_id"], r["mode"]))
    courses = unique_index(sources.rows(I1 / "c4_real_condition_rag_results_frozen_v1.jsonl"), lambda r: (r["scenario_id"], r["mode"]))
    dashboards = unique_index(sources.rows(I1 / "c4_real_condition_dashboard_evidence_frozen_v1.jsonl"), lambda r: (r["scenario_id"], r["mode"]))
    planners = unique_index(sources.rows(I1 / "c4_real_condition_planner_results_frozen_v1.jsonl"), lambda r: (r["scenario_id"], r["mode"]))
    compiled = unique_index(sources.rows(I1 / "c4_real_condition_compiled_evidence_frozen_v1.jsonl"), lambda r: (r["scenario_id"], r["mode"]))
    traces = sources.rows(I1 / "c4_real_condition_execution_traces_frozen_v1.jsonl")
    memory_cases = []
    for r in full:
        sid = r["scenario_id"]
        if sid not in cohort and r["route_signature"][1] != "1":
            continue
        p = preconditions.get(sid, {})
        receipt = receipts.get((sid, FULL), {})
        m = memories[(sid, FULL)]["result"] or {}
        memory_cases.append({"scenario_id": sid, "p3_memory_required": r["route_signature"][1] == "1",
                             "memory_status": r["typed_statuses"]["memory"],
                             "design_control": cohort.get(sid, {}).get("control_status", "OUTSIDE_PRECONDITIONED_COHORT"),
                             "setup_types": [w["candidate"]["memory_type"] for w in p.get("writes", [])],
                             "snapshot_active_count": receipt.get("active_after_reopen_count"),
                             "selected_types": [x["item_type"] for x in m.get("items", [])],
                             "target_history_length": len(inputs[sid]["semantic_input"]["visible_conversation_history"]),
                             "query_preserved": p.get("target_query") == inputs[sid]["semantic_input"]["current_query"] if p else None,
                             "limitation_codes": m.get("limitations", [])})

    # Pure serialization from saved compiler/projection records; no service/adapter instance.
    sys.path.insert(0, str(ROOT))
    from utils.c4_real_adapters import project_provider_evidence_v2_from_v1
    from evaluation.rq3_real_c4.g2d0_response_format_repair.c4_real_generation_request_renderer_v3 import render_generation_request_v3_with_audit
    v3 = sources.rows(I1 / "c4_real_unique_generation_request_manifest_frozen_v3.jsonl")
    v2 = sources.rows(I1 / "c4_real_unique_generation_request_manifest_frozen_v2.jsonl")
    frozen3 = {r["provider_payload_sha256"] for r in v3}
    frozen2 = {r["provider_payload_sha256"] for r in v2}
    for row in v3 + v2:
        if digest(canonical(row["provider_payload"])) != row["provider_payload_sha256"]:
            raise ValueError("FROZEN_PROVIDER_PAYLOAD_HASH_MISMATCH")
    prompt = sources.read(C4 / "g2d0_response_format_repair/c4_real_generation_prompt_frozen_v3.txt").decode()
    contexts, rendered, payload_hashes = {}, {}, {}
    exclusions, dropped, payload_missing, v2_missing = [], [], [], []
    notes, retained_types, token_counts = Counter(), Counter(), []
    for key, row in compiled.items():
        ce = row["compiled_evidence"]
        token_counts.append(ce["deterministic_token_count"])
        exclusions.extend({"scenario_id": key[0], "mode": key[1], "reason": x}
                          for x in ce["limitations"] if x.startswith("TOKEN_BUDGET_EXCLUDED:"))
        kept_ids = set(ce["evidence_ids"])
        for category, src, field, idfield in [("memory", memories, "items", "memory_id"), ("rag", courses, "sources", "source_id")]:
            for item in (src[key]["result"] or {}).get(field, []):
                if item[idfield] not in kept_ids:
                    dropped.append({"scenario_id": key[0], "mode": key[1], "source": category})
        si = inputs[key[0]]["semantic_input"]
        context = {k: si[k] for k in ("current_query", "current_page", "visible_conversation_history")}
        context.update(evidence=project_provider_evidence_v2_from_v1(row["provider_projection"]),
                       planning_support=row["provider_planning_projection"])
        contexts[key] = context
        rendered[key] = render_generation_request_v3_with_audit(context).text
        pp = copy.deepcopy(v3[0]["provider_payload"])
        pp["messages"] = [{"role": "system", "content": prompt}, {"role": "user", "content": rendered[key]}]
        payload_hashes[key] = digest(canonical(pp))
        if payload_hashes[key] not in frozen3:
            payload_missing.append({"scenario_id": key[0], "mode": key[1]})
        old_pp = copy.deepcopy(v2[0]["provider_payload"])
        old_pp["messages"][1]["content"] = canonical(context).decode()
        if digest(canonical(old_pp)) not in frozen2:
            v2_missing.append({"scenario_id": key[0], "mode": key[1]})
        notes.update(context["evidence"]["availability_notes"])
        retained_types.update(x["source"] for x in context["evidence"]["evidence"])
    baseline = {"same_reviewed_dashboard_input": 0, "same_provider_dashboard_content": 0,
                "same_final_v3_user_text": 0, "same_final_v3_payload": 0, "empty_dashboard_inputs": 0,
                "different_final_payload_ids": []}
    for r in full:
        sid = r["scenario_id"]; a = (sid, "C0_ORIGINAL"); b = (sid, "C1_EVIDENCE")
        raw = compiled[a]["compiled_evidence"]["content"]["legacy_raw_page_context"]
        ev = (dashboards[b]["result"] or {}).get("items", [])
        baseline["same_reviewed_dashboard_input"] += raw == (ev[0]["content"] if ev else {})
        baseline["empty_dashboard_inputs"] += not bool(raw)
        ca = [x.get("content") for x in contexts[a]["evidence"]["evidence"]]
        cb = [x.get("content") for x in contexts[b]["evidence"]["evidence"]]
        baseline["same_provider_dashboard_content"] += ca == cb
        baseline["same_final_v3_user_text"] += rendered[a] == rendered[b]
        equal = payload_hashes[a] == payload_hashes[b]
        baseline["same_final_v3_payload"] += equal
        if not equal:
            baseline["different_final_payload_ids"].append(sid)

    # Reconstruct only the fixed corpus inventory, without passing any query to a retriever.
    from utils.c4_rag.corpus import load_legacy_chunks, legacy_chunk_corpus_hash
    from utils.c4_rag.retrievers import _evidence_strength
    chunks = load_legacy_chunks()
    grouped_text = defaultdict(list)
    for chunk in chunks:
        grouped_text[digest(chunk.text.encode())].append(chunk.chunk_id)
    registry_r = sources.obj(C4 / "track_r_rag/course_source_registry_v1.json")
    corpus = {"chunk_count": len(chunks), "unique_chunk_ids": len({c.chunk_id for c in chunks}),
              "corpus_sha256": legacy_chunk_corpus_hash(chunks),
              "runtime_source_document_count": len({c.source_file for c in chunks}),
              "counts_by_source_type": dict(Counter(c.source_type for c in chunks)),
              "rule_assigned_strength_counts": dict(Counter(_evidence_strength(c).value for c in chunks)),
              "nonempty_metadata_counts": {k: sum(bool(getattr(c, k)) for c in chunks) for k in ["title", "week", "page", "task_type"]},
              "explicit_section_title_count": sum(bool(c.metadata.get("section_title")) for c in chunks),
              "max_chunk_text_characters": max(len(c.text) for c in chunks),
              "unique_text_sha256_count": len(grouped_text),
              "duplicate_text_groups": [v for v in grouped_text.values() if len(v) > 1],
              "registered_paths": len(registry_r["records"]),
              "registered_unique_file_hashes": len({r["sha256"] for r in registry_r["records"]})}
    stored_metrics = {}
    comparison = sources.obj(C4 / "track_r_rag/retrieval_comparison_v1.json")
    for name in ["r0", "r1"]:
        rows = sources.table(C4 / f"track_r_rag/retrieval_results_{name}_v1.csv")
        vals = [float(r["recall_at_5"]) for r in rows if r["recall_at_5"] != ""]
        stored_metrics[name] = {"case_count": len(rows), "stored_nonempty_recall_denominator": len(vals),
                                "mean_of_frozen_recall_at_5": sum(vals) / len(vals),
                                "stored_per_case_recall_at_5": {r["scenario_id"]: r["recall_at_5"] for r in rows},
                                "no_relevance_labels_recomputed": True}

    # Bind source files and code versions actually co-frozen with the I1 records.
    frozen_commit = git("rev-parse", "795ec13")
    code_comparison = []
    for rel in ["utils/c4_real_adapters.py", "utils/c4_real_service.py", "utils/c4_real_contracts.py",
                "utils/c4_real_trace.py", "utils/c4_memory/c4_memory_retriever.py", "utils/c4_memory/c4_memory_store.py",
                "utils/c4_memory/c4_memory_provider.py", "utils/c4_memory/c4_memory_writer.py",
                "utils/recommendation_planner.py", "evaluation/rq3_real_c4/i1_route_integration/build_i1_artifacts.py"]:
        data = sources.read(ROOT / rel)
        archived = subprocess.check_output(["git", "show", f"{frozen_commit}:{rel}"], cwd=ROOT)
        def defs(code):
            return {n.name: ast.dump(n, include_attributes=False) for n in ast.parse(code).body
                    if isinstance(n, (ast.ClassDef, ast.FunctionDef))}
        before, after = defs(archived), defs(data)
        code_comparison.append({"path": rel, "i1_commit": frozen_commit, "i1_sha256": digest(archived),
                                "current_sha256": digest(data), "byte_identical": archived == data,
                                "changed_existing_definitions": [k for k in before if before[k] != after.get(k)]})
    for name in ["c4_rag_r0_identity_v1.json", "c4_rag_r1_identity_v1.json"]:
        identity = sources.obj(C4 / "track_r_rag" / name)
        for group in ["adapter_code_hashes", "legacy_code_hashes", "source_hashes", "code_hashes"]:
            for rel, expected in identity.get(group, {}).items():
                candidate = ROOT / rel if rel.startswith(("utils/", "evaluation/rq3_real_c4/")) else OLD / rel
                sources.read(candidate, expected)
    for rel in ["utils/c4_real_factory.py", "utils/c4_real_streamlit.py", "utils/conversation_memory.py",
                "pages/1 - 👨🏼‍💻 Individual Feedback.py", "utils/c_full_service.py", "utils/c_full_retrieval_adapter.py",
                "evaluation/rq3_real_c4/i1_route_integration/i1_common.py",
                "evaluation/rq3_real_c4/g2d0_response_format_repair/c4_real_generation_request_renderer_v3.py",
                "evaluation/rq3_real_c4/g2d0_response_format_repair/generation_execution_runner_v3.py",
                "evaluation/capability_routing_rq2_v2_stage4/track_k0_specialists/memory_specialist_prompt_frozen_v1.txt",
                "evaluation/capability_routing_rq2_v2_stage4/final_router_selection/RQ2_FINAL_ROUTER_FOR_RQ3.json"]:
        sources.read(ROOT / rel)
    for rel in ["i1_route_integration/c4_real_i1_source_manifest_v1.json",
                "i1_route_integration/c4_real_p3_route_source_manifest_v1.json",
                "i1_route_integration/c4_real_generation_configuration_frozen_v3.json",
                "i1_route_integration/c4_real_generation_package_manifest_v3.json",
                "i1_route_integration/c4_real_i1_r1_scientific_preservation_manifest_v1.json",
                "track_d_dataset/C4_REAL_DATASET_AND_ABLATION_METHOD.md", "track_r_rag/REAL_C4_RAG_RESULTS.md",
                "track_m_memory/REAL_C4_MEMORY_RESULTS.md", "track_r_rag/selected_c4_rag_frozen_v1.json",
                "g2d0_response_format_repair/c4_real_generation_renderer_v2_v3_diff_audit.json",
                "r1_memory_route_execution/memory_route_execution_source_manifest_v1.json"]:
        sources.read(C4 / rel)
    route_source = sources.obj(C4 / "r1_memory_route_execution/memory_route_execution_source_manifest_v1.json")["authoritative_package"]
    route_zip = sources.read(route_source["path"], route_source["sha256"])
    with ZipFile(io.BytesIO(route_zip)) as rz:
        executed_prompt = rz.read("prompt.txt")
    prompt_binding = {"package_sha256_matches": digest(route_zip) == route_source["sha256"],
                      "prompt_sha256": digest(executed_prompt),
                      "manifest_matches": digest(executed_prompt) == route_source["member_sha256"]["prompt.txt"]}
    diagnostics = sources.rows(I1 / "c4_real_memory_preconditioning_selected_envelopes_v1.jsonl")
    result = {
        "status": "RETROSPECTIVE_OFFLINE_AUDIT", "base_head": BASE,
        "conditions": len(by_condition), "full_scenarios": len(full),
        "module_statuses_full": {k: dict(Counter(r["typed_statuses"][k] for r in full)) for k in ["rag", "memory", "planning"]},
        "module_statuses_all_conditions": {k: dict(Counter(r["typed_statuses"][k] for r in mechanism)) for k in ["rag", "memory", "planning"]},
        "full_rag_no_result_reasons": {key[0]: row["result"]["limitations"] for key, row in courses.items()
                                      if key[1] == FULL and row["status"] == "NO_RESULT"},
        "handoff_csv_reconciliation": csv_reconciliation,
        "duplicate_four_field_inputs": [sorted(v) for v in duplicate_inputs.values() if len(v) > 1],
        "memory_case_evidence": memory_cases,
        "native_setup_migration": native_setup_migration(sources, preconditions),
        "preconditioning_only_diagnostics": [{k: r[k] for k in ["scenario_id", "mode", "status", "selected_item_count", "limitations"]} for r in diagnostics],
        "executed_memory_prompt_binding": prompt_binding,
        "baseline": baseline,
        "compiler_and_renderer": {"token_budget_exclusions": exclusions, "retrieved_items_missing_compiler": dropped,
                                  "min_stored_tokens": min(token_counts), "max_stored_tokens": max(token_counts),
                                  "conditions_matching_frozen_v2_payloads": len(compiled) - len(v2_missing),
                                  "conditions_matching_frozen_v3_payloads": len(compiled) - len(payload_missing),
                                  "v2_unmatched_conditions": v2_missing, "v3_unmatched_conditions": payload_missing,
                                  "unique_reconstructed_v3_payload_hashes": len(set(payload_hashes.values())),
                                  "frozen_unique_v3_payload_hashes": len(frozen3),
                                  "availability_note_occurrences": dict(notes), "retained_source_occurrences": dict(retained_types)},
        "called_modules_in_frozen_traces": dict(Counter(x for r in traces for x in r["modules_actually_called"])),
        "corpus": corpus, "stored_retrieval_metrics_arithmetic": stored_metrics,
        "code_at_i1_freeze": code_comparison,
        "response_identity_bridge": response_identity_bridge(sources, frozen3),
        "network_attempts": BlockNetwork.attempts,
        "prohibited_model_modules_loaded": [m for m in ["torch", "transformers", "sentence_transformers", "openai"] if m in sys.modules],
        "research_retrieval_calls": 0, "embedding_calls": 0, "generation_calls": 0, "judge_calls": 0,
        "quality_or_relevance_scores_recomputed": 0,
    }
    manifest = {"audit_base_head": BASE, "i1_cofrozen_source_commit": frozen_commit,
                "authority": "User directed continuation; B selected from the matching existing workspace and branch. Handoff counts treated as claims.",
                "files": sorted(sources.entries.values(), key=lambda r: r["path"]), "handoff_members": members,
                "external_design_references": [
                    {"url": "https://www.sbert.net/examples/sentence_transformer/applications/retrieve_rerank/README.html", "role": "candidate design only", "accessed": "2026-09-06"},
                    {"url": "https://www.anthropic.com/engineering/contextual-retrieval", "role": "candidate design only", "accessed": "2026-09-06"},
                    {"url": "https://arxiv.org/abs/2410.10813", "role": "candidate design only", "accessed": "2026-09-06"}],
                "not_accessed": ["secrets", "private raw ratings or rationales", "restricted response mappings", "production Memory stores"],
                "no_copied_provider_payloads_or_answers": True}
    return result, manifest


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--write", action="store_true")
    args = parser.parse_args()
    with patch.object(socket, "socket", BlockNetwork):
        result, manifest = inspect()
    if args.write:
        targets = [OUT / "OFFLINE_AUDIT_RESULTS.json", OUT / "SOURCE_MANIFEST.json", OUT / "MEMORY_CASE_EVIDENCE.csv"]
        if any(p.exists() for p in targets):
            raise FileExistsError("AUDIT_OUTPUT_ALREADY_EXISTS_NO_OVERWRITE")
        for name, obj in zip(targets[:2], [result, manifest]):
            name.write_text(json.dumps(obj, ensure_ascii=False, indent=2, sort_keys=True) + "\n")
        rows = [{k: json.dumps(v, ensure_ascii=False) if isinstance(v, list) else v for k, v in r.items()}
                for r in result["memory_case_evidence"]]
        targets[2].write_bytes(csv_bytes(rows, list(rows[0]), lineterminator="\n"))
    print(json.dumps({k: result[k] for k in ["conditions", "full_scenarios", "baseline", "compiler_and_renderer", "corpus", "network_attempts", "prohibited_model_modules_loaded"]}, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
