"""Shared deterministic helpers for RQ3-REAL-C4 I1 artifacts."""

from __future__ import annotations

from collections import Counter, defaultdict
import csv
import hashlib
import json
from pathlib import Path
import subprocess
from typing import Any, Iterable, Mapping, Sequence

from evaluation.rq3_real_c4.i0_integration.assemble_frozen_routes import (
    METHOD_ID,
    successful_by_scenario,
)


HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]
I0 = HERE.parent / "i0_integration"
TRACK_D = HERE.parent / "track_d_dataset"
TRACK_R = HERE.parent / "track_r_rag"
ROUTE_ROOT = HERE.parent
DATASET_PATH = Path(
    "/Users/liuming/Downloads/duteaiapp_cfull_semantic_integrated_v1_副本3/"
    "evaluation/unified_benchmark_scenarios.jsonl"
)
COURSE_ROOT = Path(
    "/Users/liuming/Downloads/duteaiapp_cfull_semantic_integrated_v1_副本3"
)
MPNET_PATH = COURSE_ROOT / (
    "semantic_runtime/models/all-mpnet-base-v2/"
    "e8c3b32edf5434bc2275fc9bab85f82640a19130"
)

STARTING_HEAD = "246e6ff64003caa4787716e00f050a2451dfca01"
BRANCH = "research/rq3-real-c4-i1-route-integration"
COMMIT_MAPPING = (
    (
        "197c534580a74845e9f5f1c47e3c3201c42656a6",
        "701617f999d89071a3fadc9f233f4c870e9d9e46",
    ),
    (
        "cf7248dd7896349306804462b2ac42aaab9cc1c6",
        "4b3e01bc7787d6a24b0e2315ba15a8ab03c9b86c",
    ),
    (
        "08c7a79d4410136f3ce94885b47808c97e0c84d7",
        "5a7cc94b3c8411951782c14c06d230e89c289e33",
    ),
    (
        "b2c4c04ef3b43e1f377dbdbea9acb4fde8c36069",
        "97acae5add9a67449eaaa4aa2502ea18b11d64ef",
    ),
)

EXPECTED_HASHES = {
    "dataset": "2df88a153101b39872154ed1ef339d6639e3ea28fac7df0eb42dd8bc9d998ce4",
    "p3_route_input_manifest": "b042e454a9508fac4348ce7ba1f2595ca2882227098696589c5e4e214710e326",
    "clarification_decisions": "ffad60337a8a38198084d8a89fd30e6f93a96678ef19eca0ae2bbc0c70034d18",
    "memory_preconditioning_manifest": "60a958896eb42fedaead7d55182d50c4e3631bdfe6dc3dde37e34bdb69540aad",
    "rag_terminal": "5e8b2665347b0c2905522a45f05bbb553315914e1189035ca2bfebd1d412bad1",
    "memory_terminal": "0fd794e671a4f7d17247f5637ce358a634cb391ae2f79330471c69a8f1e44ef2",
    "planning_terminal": "7f6e64597fbc85d506c70f950115cfabd90adfa470fb24fe7038454def0adfb9",
    "router_binding": "893a0726570ae654d2815a96ab1987555f89fbfc00d6714ab609a979a13d20dd",
    "generation_schema_v1": "46b79822888d72c3c7c78677a7ca9c5daa8f7cf361174258193d8bad597ed0d2",
    "generation_prompt": "41748d1f3a69ce6623e607551a8473228c0724871e16e392ecd7872b4e550b21",
    "course_corpus": "daaba43aebeda730db2bd7aef4583729610242a1af44060615c3f4c235e67ede",
}

SOURCE_PATHS = {
    "p3_route_input_manifest": I0 / "c4_real_p3_route_input_manifest_v1.jsonl",
    "clarification_decisions": I0 / "c4_real_clarification_decisions_frozen_v1.csv",
    "memory_preconditioning_manifest": I0 / "c4_real_memory_preconditioning_manifest_v1.jsonl",
    "rag_terminal": ROUTE_ROOT / "r1_rag_route_execution/execution_output_v2/route_terminal_results_v1.jsonl",
    "memory_terminal": ROUTE_ROOT / "r1_memory_route_execution/execution_output_v1/route_terminal_results_v1.jsonl",
    "planning_terminal": ROUTE_ROOT / "r1_b4_planning_route_execution/execution_output_v1/route_terminal_results_v1.jsonl",
    "router_binding": ROOT / "evaluation/capability_routing_rq2_v2_stage4/final_router_selection/RQ2_FINAL_ROUTER_FOR_RQ3.json",
    "generation_schema_v1": I0 / "c4_real_generation_schema_v1.json",
    "generation_prompt": I0 / "c4_real_generation_prompt_frozen_v1.txt",
}

TERMINAL_FIELDS = {
    "rag_terminal": "rag_required",
    "memory_terminal": "memory_required",
    "planning_terminal": "planning_required",
}


def canonical_bytes(value: Any) -> bytes:
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    ).encode("utf-8")


def canonical_sha256(value: Any) -> str:
    return hashlib.sha256(canonical_bytes(value)).hexdigest()


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def load_jsonl(path: Path) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        if not line.strip():
            continue
        value = json.loads(line)
        if not isinstance(value, dict):
            raise ValueError(f"{path}:{number} is not an object")
        rows.append(value)
    return rows


def write_json(path: Path, value: Any) -> None:
    path.write_text(
        json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def write_jsonl(path: Path, rows: Iterable[Mapping[str, Any]]) -> None:
    path.write_text(
        "".join(
            json.dumps(dict(row), ensure_ascii=False, sort_keys=True) + "\n"
            for row in rows
        ),
        encoding="utf-8",
    )


def write_csv(path: Path, fieldnames: Sequence[str], rows: Iterable[Mapping[str, Any]]) -> None:
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames, lineterminator="\n")
        writer.writeheader()
        for row in rows:
            writer.writerow({name: row.get(name, "") for name in fieldnames})


def _git(*args: str) -> str:
    return subprocess.check_output(["git", *args], cwd=ROOT, text=True).strip()


def _assert_ancestor(commit: str) -> None:
    result = subprocess.run(
        ["git", "merge-base", "--is-ancestor", commit, "HEAD"],
        cwd=ROOT,
        check=False,
    )
    if result.returncode != 0:
        raise ValueError(f"required integrated commit is not an ancestor: {commit}")


def verify_sources() -> dict[str, Any]:
    if Path.cwd().resolve() != ROOT.resolve():
        raise ValueError("I1 builder must run from the repository root")
    if _git("branch", "--show-current") != BRANCH:
        raise ValueError("I1 branch mismatch")
    if _git("rev-parse", STARTING_HEAD) != STARTING_HEAD:
        raise ValueError("starting HEAD object is unavailable")
    for original, cherry in COMMIT_MAPPING:
        if _git("rev-parse", original) != original or _git("rev-parse", cherry) != cherry:
            raise ValueError("source or cherry-picked commit identity mismatch")
        _assert_ancestor(cherry)

    observed_hashes = {name: sha256_file(path) for name, path in SOURCE_PATHS.items()}
    observed_hashes["dataset"] = sha256_file(DATASET_PATH)
    for name, expected in EXPECTED_HASHES.items():
        if name == "course_corpus":
            continue
        if observed_hashes[name] != expected:
            raise ValueError(f"frozen source hash mismatch: {name}")
    if sum(1 for line in DATASET_PATH.read_bytes().splitlines() if line.strip()) != 62:
        raise ValueError("frozen dataset record count mismatch")

    selected_rag = json.loads((TRACK_R / "selected_c4_rag_frozen_v1.json").read_text(encoding="utf-8"))
    rag_identity = json.loads((TRACK_R / "c4_rag_r0_identity_v1.json").read_text(encoding="utf-8"))
    if selected_rag.get("selected_implementation_id") != "C4_RAG_R0_LEXICAL":
        raise ValueError("selected Course RAG identity mismatch")
    if rag_identity.get("implementation_id") != "C4_RAG_R0_LEXICAL":
        raise ValueError("R0 implementation identity mismatch")
    if rag_identity.get("chunk_count") != 624 or rag_identity.get("chunk_corpus_hash") != EXPECTED_HASHES["course_corpus"]:
        raise ValueError("R0 corpus identity mismatch")

    binding = json.loads(SOURCE_PATHS["router_binding"].read_text(encoding="utf-8"))
    if binding.get("selected_method_id") != METHOD_ID or binding.get("write_count") != 1:
        raise ValueError("final Router binding mismatch")

    route_inputs = load_jsonl(SOURCE_PATHS["p3_route_input_manifest"])
    if len(route_inputs) != 62 or any(row.get("status") != "READY_FOR_P3_ROUTE_EXECUTION" for row in route_inputs):
        raise ValueError("P3 input population mismatch")
    expected_ids = [row["scenario_id"] for row in route_inputs]
    if len(set(expected_ids)) != 62:
        raise ValueError("P3 input scenario IDs are not unique")

    terminals: dict[str, dict[str, dict[str, Any]]] = {}
    terminal_validations: dict[str, Any] = {}
    for name, field in TERMINAL_FIELDS.items():
        path = SOURCE_PATHS[name]
        rows = load_jsonl(path)
        if len(rows) != 62:
            raise ValueError(f"{name} terminal count mismatch")
        by_scenario = successful_by_scenario(path, field)
        if list(by_scenario) != expected_ids:
            raise ValueError(f"{name} logical scenario order mismatch")
        for logical_order, scenario_id in enumerate(expected_ids, 1):
            row = by_scenario[scenario_id]
            expected_hash = route_inputs[logical_order - 1]["semantic_input_sha256"]
            if row.get("logical_order") != logical_order:
                raise ValueError(f"{name} logical order mismatch")
            if row.get("semantic_input_sha256") != expected_hash:
                raise ValueError(f"{name} semantic-input hash mismatch")
            if row.get("returned_model") != "gpt-4o-mini-2024-07-18":
                raise ValueError(f"{name} returned-model mismatch")
            if row.get("physical_attempts_for_logical_request") != 1:
                raise ValueError(f"{name} retry/error mismatch")
            if row.get("terminal_status") != "VALID_OUTPUT":
                raise ValueError(f"{name} invalid terminal status")
        terminals[name] = by_scenario
        error_registry = path.parent / "route_error_registry_v1.jsonl"
        if any(line.strip() for line in error_registry.read_text(encoding="utf-8").splitlines()):
            raise ValueError(f"{name} error registry is not empty")
        terminal_validations[name] = {
            "sha256": observed_hashes[name],
            "valid_terminal_count": len(rows),
            "retry_count": 0,
            "error_count": 0,
            "returned_model": "gpt-4o-mini-2024-07-18",
            "yes_count": sum(row["output"][field] for row in rows),
            "no_count": sum(not row["output"][field] for row in rows),
        }
    expected_yes = {"rag_terminal": 21, "memory_terminal": 19, "planning_terminal": 15}
    for name, count in expected_yes.items():
        if terminal_validations[name]["yes_count"] != count:
            raise ValueError(f"{name} route distribution mismatch")

    replay = load_jsonl(TRACK_D / "c4_real_replay_manifest_unexecuted_v1.jsonl")
    if len(replay) != 558:
        raise ValueError("frozen replay count mismatch")
    tier_counts = Counter(str(row["analysis_tier"]) for row in replay)
    if tier_counts != Counter({"PRIMARY": 372, "TARGETED_SECONDARY": 186}):
        raise ValueError("frozen replay tier mismatch")
    scenario_modes = defaultdict(set)
    for row in replay:
        scenario_modes[row["scenario_id"]].add(row["mode_id"])
    if set(scenario_modes) != set(expected_ids) or any(len(modes) != 9 for modes in scenario_modes.values()):
        raise ValueError("frozen replay scenario/mode population mismatch")

    return {
        "observed_hashes": observed_hashes,
        "route_inputs": route_inputs,
        "terminals": terminals,
        "terminal_validations": terminal_validations,
        "replay": replay,
        "tier_counts": dict(sorted(tier_counts.items())),
        "course_rag": {
            "implementation_id": "C4_RAG_R0_LEXICAL",
            "chunk_count": 624,
            "corpus_sha256": EXPECTED_HASHES["course_corpus"],
        },
    }


def assemble_p3(source: Mapping[str, Any]) -> dict[str, Any]:
    route_inputs = source["route_inputs"]
    terminals = source["terminals"]
    source_hashes = source["observed_hashes"]
    routes: list[dict[str, Any]] = []
    by_semantic: dict[str, dict[str, Any]] = {}
    b4_rows: list[dict[str, Any]] = []
    for row in route_inputs:
        scenario_id = row["scenario_id"]
        semantic_hash = row["semantic_input_sha256"]
        rag_row = terminals["rag_terminal"][scenario_id]
        memory_row = terminals["memory_terminal"][scenario_id]
        planning_row = terminals["planning_terminal"][scenario_id]
        bits = {
            "rag_required": rag_row["output"]["rag_required"],
            "memory_required": memory_row["output"]["memory_required"],
            "planning_required": planning_row["output"]["planning_required"],
        }
        decision_id = "C4-P3-" + canonical_sha256(
            {"semantic_input_sha256": semantic_hash, **bits}
        )[:24]
        component_hashes = {
            "rag_terminal_file_sha256": source_hashes["rag_terminal"],
            "rag_terminal_record_sha256": canonical_sha256(rag_row),
            "memory_terminal_file_sha256": source_hashes["memory_terminal"],
            "memory_terminal_record_sha256": canonical_sha256(memory_row),
            "planning_terminal_file_sha256": source_hashes["planning_terminal"],
            "planning_terminal_record_sha256": canonical_sha256(planning_row),
        }
        route = {
            "scenario_id": scenario_id,
            "semantic_input_sha256": semantic_hash,
            **bits,
            "method_id": METHOD_ID,
            "decision_id": decision_id,
            "source_component_hashes": component_hashes,
        }
        prior = by_semantic.setdefault(semantic_hash, route)
        if any(prior[key] != route[key] for key in bits):
            raise ValueError("duplicate semantic input received inconsistent P3 routes")
        routes.append(route)
        b4_rows.append(
            {
                "scenario_id": scenario_id,
                "semantic_input_sha256": semantic_hash,
                "b4_rag_required_descriptive_only": planning_row["output"]["rag_required"],
                "b4_memory_required_descriptive_only": planning_row["output"]["memory_required"],
                "b4_planning_required_selected": planning_row["output"]["planning_required"],
                "p3_rag_source": "RAG_SPECIALIST_ONLY",
                "p3_memory_source": "MEMORY_SPECIALIST_ONLY",
                "b4_rag_memory_entered_p3": False,
            }
        )

    signatures = Counter(
        f"{int(row['rag_required'])}{int(row['memory_required'])}{int(row['planning_required'])}"
        for row in routes
    )
    expected_signatures = Counter(
        {"000": 25, "001": 8, "010": 7, "011": 1, "100": 7, "101": 3, "110": 8, "111": 3}
    )
    if signatures != expected_signatures:
        raise ValueError("P3 signature distribution mismatch")
    if len(routes) != 62 or len(by_semantic) != 60:
        raise ValueError("P3 route/cache population mismatch")
    duplicates = defaultdict(list)
    for row in routes:
        duplicates[row["semantic_input_sha256"]].append(row["scenario_id"])
    duplicate_groups = [sorted(ids) for ids in duplicates.values() if len(ids) > 1]
    if duplicate_groups != [["U022", "U026", "U031"]]:
        raise ValueError("P3 duplicate semantic-input group mismatch")
    duplicate_route = next(row for row in routes if row["scenario_id"] == "U022")
    if (
        duplicate_route["rag_required"],
        duplicate_route["memory_required"],
        duplicate_route["planning_required"],
    ) != (False, False, True):
        raise ValueError("duplicate semantic-input route mismatch")

    write_jsonl(HERE / "c4_real_p3_routes_frozen_v1.jsonl", routes)
    csv_rows = []
    for row in routes:
        csv_rows.append(
            {
                **{key: row[key] for key in (
                    "scenario_id", "semantic_input_sha256", "rag_required",
                    "memory_required", "planning_required", "method_id", "decision_id"
                )},
                **row["source_component_hashes"],
            }
        )
    write_csv(
        HERE / "c4_real_p3_routes_frozen_v1.csv",
        list(csv_rows[0]),
        csv_rows,
    )
    cache = {
        "schema_version": "c4-real-precomputed-p3-route-cache-frozen-v1",
        "method_id": METHOD_ID,
        "scenario_count": len(routes),
        "unique_semantic_input_count": len(by_semantic),
        "scenario_routes": routes,
        "route_cache": {
            semantic_hash: {
                "rag_required": row["rag_required"],
                "memory_required": row["memory_required"],
                "planning_required": row["planning_required"],
                "method_id": METHOD_ID,
                "decision_id": row["decision_id"],
                "provider_identity": "FROZEN_PARALLEL_ROUTE_JOURNALS",
            }
            for semantic_hash, row in sorted(by_semantic.items())
        },
        "gold_used": False,
        "route_accuracy_scored": False,
        "provider_calls_by_merger": 0,
    }
    write_json(HERE / "c4_real_precomputed_p3_route_cache_frozen_v1.json", cache)
    b4_audit = {
        "schema_version": "c4-real-b4-unused-route-bits-source-audit-v1",
        "status": "DESCRIPTIVE_ONLY_NOT_P3_INPUT",
        "scenario_count": len(b4_rows),
        "b4_rag_yes_count": sum(row["b4_rag_required_descriptive_only"] for row in b4_rows),
        "b4_memory_yes_count": sum(row["b4_memory_required_descriptive_only"] for row in b4_rows),
        "b4_planning_yes_count": sum(row["b4_planning_required_selected"] for row in b4_rows),
        "b4_rag_memory_bits_entered_p3": False,
        "rows": b4_rows,
    }
    write_json(HERE / "c4_real_b4_unused_route_bits_source_audit_v1.json", b4_audit)

    route_manifest = {
        "schema_version": "c4-real-p3-route-source-manifest-v1",
        "status": "PASS_FROZEN_P3_ASSEMBLED_UNSCORED",
        "method_id": METHOD_ID,
        "starting_head": STARTING_HEAD,
        "commit_mapping": [
            {"original_commit": original, "cherry_picked_commit": cherry, "order": index}
            for index, (original, cherry) in enumerate(COMMIT_MAPPING, 1)
        ],
        "source_terminal_validation": source["terminal_validations"],
        "route_input_manifest_sha256": source_hashes["p3_route_input_manifest"],
        "router_binding_sha256": source_hashes["router_binding"],
        "scenario_count": len(routes),
        "unique_semantic_input_count": len(by_semantic),
        "signature_distribution": dict(sorted(signatures.items())),
        "component_yes_counts": {
            "rag": sum(row["rag_required"] for row in routes),
            "memory": sum(row["memory_required"] for row in routes),
            "planning": sum(row["planning_required"] for row in routes),
            "any_optional": sum(
                row["rag_required"] or row["memory_required"] or row["planning_required"]
                for row in routes
            ),
            "all_optional_no": sum(
                not (row["rag_required"] or row["memory_required"] or row["planning_required"])
                for row in routes
            ),
        },
        "duplicate_semantic_input_groups": duplicate_groups,
        "duplicate_route": {"rag_required": False, "memory_required": False, "planning_required": True},
        "gold_used": False,
        "accuracy_metrics_computed": False,
    }
    write_json(HERE / "c4_real_p3_route_source_manifest_v1.json", route_manifest)
    return {
        "routes": routes,
        "cache": cache,
        "manifest": route_manifest,
        "signature_distribution": dict(sorted(signatures.items())),
    }
