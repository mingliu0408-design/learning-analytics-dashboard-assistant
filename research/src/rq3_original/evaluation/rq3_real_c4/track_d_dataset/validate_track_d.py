"""Read-only validator for the RQ3-REAL-C4 Track D freeze."""

from __future__ import annotations

from collections import Counter, defaultdict
import csv
import hashlib
import json
from pathlib import Path
from typing import Any


HERE = Path(__file__).resolve().parent

PRIMARY_DATASET_ID = "C4_REAL_PRIMARY_UNIFIED_DATASET_V1"
ORIGINAL_SUBSET_ID = "C4_REAL_ORIGINAL_25_AUTHENTIC_SUBSET_V1"
GENERATOR_PLACEHOLDER = "GENERATOR_MODEL_TO_BE_FROZEN_BEFORE_AUTHORIZED_EXECUTION"
PROMPT_PLACEHOLDER = "C4_REAL_SHARED_GENERATION_PROMPT_TO_BE_BYTE_FROZEN_BEFORE_EXECUTION"
P3_SHA256 = "893a0726570ae654d2815a96ab1987555f89fbfc00d6714ab609a979a13d20dd"

MODE_LOCKS = {
    "C0_ORIGINAL": (False, False, False, False),
    "C1_EVIDENCE": (True, False, False, False),
    "C2_EVIDENCE_RAG": (True, True, False, False),
    "C3_EVIDENCE_MEMORY": (True, False, True, False),
    "C4_EVIDENCE_PLANNING": (True, False, False, True),
    "C5_FULL_C4": (True, True, True, True),
    "C5_MINUS_RAG": (True, False, True, True),
    "C5_MINUS_MEMORY": (True, True, False, True),
    "C5_MINUS_PLANNING": (True, True, True, False),
}

PRIMARY_COMPARISONS = [
    ("C1_EVIDENCE", "C0_ORIGINAL"),
    ("C2_EVIDENCE_RAG", "C1_EVIDENCE"),
    ("C3_EVIDENCE_MEMORY", "C1_EVIDENCE"),
    ("C4_EVIDENCE_PLANNING", "C1_EVIDENCE"),
    ("C5_FULL_C4", "C1_EVIDENCE"),
]

REMOVE_ONE_COMPARISONS = [
    ("C5_FULL_C4", "C5_MINUS_RAG"),
    ("C5_FULL_C4", "C5_MINUS_MEMORY"),
    ("C5_FULL_C4", "C5_MINUS_PLANNING"),
]

MEMORY_CLASSES = {
    "VISIBLE_HISTORY_ONLY",
    "SAME_SESSION_WORKING_MEMORY",
    "CROSS_SESSION_EPISODIC_MEMORY",
    "STABLE_SEMANTIC_PROFILE",
    "ACTIVE_PLAN_STATE",
    "UPDATE_OR_CORRECTION",
    "SUPERSEDED_MEMORY",
    "NO_RELEVANT_MEMORY_CONTROL",
}

QUALITY_CRITERIA = [
    "CLARITY",
    "PERSONALISATION",
    "ACTIONABILITY",
    "CONTEXT_AWARENESS",
    "MOTIVATION_AND_ENGAGEMENT",
    "RELIABILITY",
    "MULTI_PAGE_COHESIVENESS",
    "ERROR_HANDLING",
]


def canonical_json(value: Any) -> str:
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    )


def object_sha256(value: Any) -> str:
    return hashlib.sha256(canonical_json(value).encode("utf-8")).hexdigest()


def text_sha256(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def load_json(name: str) -> dict[str, Any]:
    value = json.loads((HERE / name).read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise AssertionError(f"{name} is not a JSON object")
    return value


def load_jsonl(name: str) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for line_number, line in enumerate((HERE / name).read_text(encoding="utf-8").splitlines(), start=1):
        if not line.strip():
            continue
        value = json.loads(line)
        if not isinstance(value, dict):
            raise AssertionError(f"{name}:{line_number} is not an object")
        rows.append(value)
    return rows


def load_csv(name: str) -> list[dict[str, str]]:
    with (HERE / name).open("r", encoding="utf-8", newline="") as handle:
        return list(csv.DictReader(handle))


class Checks:
    def __init__(self) -> None:
        self.count = 0

    def check(self, condition: bool, message: str) -> None:
        self.count += 1
        if not condition:
            raise AssertionError(message)

    def equal(self, actual: Any, expected: Any, message: str) -> None:
        self.check(actual == expected, f"{message}: actual={actual!r}, expected={expected!r}")


def validate() -> int:
    c = Checks()
    required = {
        "dataset_lineage_registry_v1.json",
        "final_62_scenario_identity_v1.json",
        "original_25_subset_identity_v1.json",
        "memory_scenario_registry_v1.csv",
        "memory_extension_writer_packet_v1.csv",
        "c4_real_ablation_mode_registry_v1.json",
        "c4_real_replay_manifest_unexecuted_v1.jsonl",
        "C4_REAL_DATASET_AND_ABLATION_METHOD.md",
        "STATUS.md",
    }
    for name in sorted(required):
        c.check((HERE / name).is_file(), f"Missing required artifact: {name}")

    lineage = load_json("dataset_lineage_registry_v1.json")
    final_identity = load_json("final_62_scenario_identity_v1.json")
    original_identity = load_json("original_25_subset_identity_v1.json")
    memory = load_csv("memory_scenario_registry_v1.csv")
    extensions = load_csv("memory_extension_writer_packet_v1.csv")
    modes = load_json("c4_real_ablation_mode_registry_v1.json")
    replay = load_jsonl("c4_real_replay_manifest_unexecuted_v1.jsonl")

    c.equal(lineage["authoritative_dataset_id"], PRIMARY_DATASET_ID, "Lineage primary dataset ID")
    c.equal(lineage["authoritative_original_subset_id"], ORIGINAL_SUBSET_ID, "Lineage subset ID")
    c.equal(lineage["lineage_decision"]["selected"], PRIMARY_DATASET_ID, "Lineage selection")
    c.equal(
        lineage["lineage_decision"]["selected_sha256"],
        "2df88a153101b39872154ed1ef339d6639e3ea28fac7df0eb42dd8bc9d998ce4",
        "Primary source hash",
    )
    c.equal(
        lineage["versions"]["unified_62"]["overlap_with_57_by_stable_content_identity"],
        57,
        "57-to-62 overlap",
    )
    c.equal(len(lineage["versions"]["unified_62"]["additions_relative_to_57"]), 5, "Addition count")
    c.equal(
        {row["source_scenario_id"] for row in lineage["versions"]["unified_62"]["additions_relative_to_57"]},
        {"M008", "M009", "M010", "M011", "M012"},
        "Addition identities",
    )
    c.equal(
        len(lineage["versions"]["unified_62"]["downstream_id_renumbering"]), 25, "Renumbering count"
    )
    c.equal(
        lineage["final_evaluation_status"]["unified_62"]["status"],
        "HISTORICAL_PARTIAL_EVALUATION_NOT_A_C4_EXECUTION",
        "Historical status",
    )
    c.equal(
        lineage["final_evaluation_status"]["unified_62"]["human_validation"][
            "completed_score_or_rationale_cell_count"
        ],
        0,
        "Historical human packet must remain blank",
    )
    for value in lineage["execution_boundary"].values():
        c.equal(value, 0, "Track D lineage execution counter")

    c.equal(final_identity["dataset_id"], PRIMARY_DATASET_ID, "Final identity ID")
    c.equal(final_identity["record_count"], 62, "Final identity record count")
    c.equal(len(final_identity["rows"]), 62, "Final identity row count")
    c.equal(final_identity["rows_payload_sha256"], object_sha256(final_identity["rows"]), "Final row payload hash")
    final_by_id = {row["scenario_id"]: row for row in final_identity["rows"]}
    c.equal(len(final_by_id), 62, "Unique final identity IDs")
    c.equal(set(final_by_id), {f"U{i:03d}" for i in range(1, 63)}, "Final identity ID set")
    for row in final_identity["rows"]:
        primary = row["primary_input"]
        c.check(bool(primary["student_query"]), f"Empty query: {row['scenario_id']}")
        c.check(bool(primary["current_page"]), f"Empty page: {row['scenario_id']}")
        c.check(isinstance(primary["visible_conversation_history"], list), "History must be a list")
        c.equal(
            row["identity_hashes"]["primary_input_sha256"], object_sha256(primary), "Primary input hash"
        )
    c.equal(final_identity["prior_output_exclusion"]["generated_response_included"], False, "No generated response")
    c.equal(final_identity["prior_output_exclusion"]["historical_mode_response_included"], False, "No historical response")
    c.equal(final_identity["prior_output_exclusion"]["historical_judge_score_included"], False, "No judge score")

    c.equal(original_identity["dataset_id"], ORIGINAL_SUBSET_ID, "Original subset ID")
    c.equal(original_identity["parent_dataset_id"], PRIMARY_DATASET_ID, "Original subset parent")
    c.equal(original_identity["record_count"], 25, "Original subset count")
    c.equal(len(original_identity["rows"]), 25, "Original subset row count")
    c.equal(original_identity["rows_payload_sha256"], object_sha256(original_identity["rows"]), "Original payload hash")
    c.equal(original_identity["query_lineage"]["semantic_change_count"], 0, "No semantic query changes")
    c.equal(original_identity["query_lineage"]["trailing_whitespace_trim_only_count"], 4, "Trim-only count")
    c.equal(
        original_identity["excluded_source_content"]["baseline_reference_response_copied_into_frozen_inputs"],
        False,
        "Baseline responses excluded",
    )
    for row in original_identity["rows"]:
        unified = final_by_id[row["unified_scenario_id"]]
        c.equal(row["primary_input"], unified["primary_input"], "Original-to-unified primary input")
        c.check(row["unified_scenario_id"] <= "U025", "Original subset must map to U001-U025")

    c.equal(len(memory), 15, "Memory registry count")
    c.equal(len({row["unified_scenario_id"] for row in memory}), 15, "Memory registry unique IDs")
    c.check({row["memory_class"] for row in memory}.issubset(MEMORY_CLASSES), "Unknown Memory class")
    c.equal(sum(row["persistent_replay_eligible"] == "YES" for row in memory), 9, "Persistent replay count")
    c.equal(
        Counter(row["memory_class"] for row in memory),
        Counter(
            {
                "VISIBLE_HISTORY_ONLY": 5,
                "SAME_SESSION_WORKING_MEMORY": 3,
                "ACTIVE_PLAN_STATE": 3,
                "UPDATE_OR_CORRECTION": 1,
                "NO_RELEVANT_MEMORY_CONTROL": 3,
            }
        ),
        "Memory class distribution",
    )
    memory_by_id = {row["unified_scenario_id"]: row for row in memory}
    for row in memory:
        c.equal(row["target_query_preserved"], "YES", "Memory target query preservation")
        c.equal(row["student_query_sha256"], text_sha256(row["student_query"]), "Memory query hash")
        c.equal(row["student_query"], final_by_id[row["unified_scenario_id"]]["primary_input"]["student_query"],
                "Memory query identity")

    c.equal(len(extensions), 6, "Writer extension count")
    c.equal(len({row["extension_family_id"] for row in extensions}), 6, "Writer extension unique IDs")
    for row in extensions:
        c.equal(row["student_writer_setup_text"], "", "Blank setup writer cell")
        c.equal(row["student_writer_update_text"], "", "Blank update writer cell")
        c.equal(row["student_writer_target_text"], "", "Blank target writer cell")
        c.equal(row["human_writer_status"], "REQUIRED_NOT_COMPLETED", "Human writer status")
        c.equal(row["adjudication_status"], "NOT_STARTED", "Writer adjudication status")
        c.equal(
            row["inclusion_status"],
            "NOT_IN_PRIMARY_DATASET_OR_REPLAY_MANIFEST",
            "Writer inclusion boundary",
        )

    c.equal(modes["dataset_id"], PRIMARY_DATASET_ID, "Mode registry dataset")
    c.equal(modes["status"], "FROZEN_UNEXECUTED", "Mode registry status")
    c.equal(len(modes["modes"]), 9, "Mode count")
    mode_by_id = {mode["mode_id"]: mode for mode in modes["modes"]}
    c.equal(set(mode_by_id), set(MODE_LOCKS), "Mode ID set")
    for mode_id, expected in MODE_LOCKS.items():
        lock = mode_by_id[mode_id]["condition_lock"]
        actual = (lock["evidence_synthesis"], lock["rag"], lock["memory"], lock["planning"])
        c.equal(actual, expected, f"Condition lock for {mode_id}")
        c.check(bool(mode_by_id[mode_id]["p3_gating_rule"]), f"Missing P3 rule: {mode_id}")
        c.equal(mode_by_id[mode_id]["state_reset_rule_id"], "C4_REAL_PER_SCENARIO_MODE_ISOLATED_RESET_V1",
                "Mode reset rule")
    c.equal(sum(mode["analysis_tier"] == "PRIMARY" for mode in modes["modes"]), 6, "Primary mode count")
    c.equal(
        sum(mode["analysis_tier"] == "TARGETED_SECONDARY" for mode in modes["modes"]),
        3,
        "Targeted mode count",
    )
    c.equal(modes["p3_binding"]["sha256"], P3_SHA256, "P3 binding hash")
    c.equal(modes["p3_binding"]["write_count"], 1, "P3 binding write count")
    c.equal(modes["p3_binding"]["overwrite_permitted"], False, "P3 binding immutable")
    c.equal(modes["p3_binding"]["rq3_may_change_binding"], False, "RQ3 cannot change P3")
    c.equal(
        [(row["left"], row["right"]) for row in modes["frozen_comparisons"]["primary"]],
        PRIMARY_COMPARISONS,
        "Primary comparisons",
    )
    c.equal(
        [(row["left"], row["right"]) for row in modes["frozen_comparisons"]["targeted_remove_one"]],
        REMOVE_ONE_COMPARISONS,
        "Remove-one comparisons",
    )
    c.equal(
        modes["evaluation_contract"]["primary_response_quality_criteria"], QUALITY_CRITERIA, "Eight criteria"
    )
    c.equal(
        modes["evaluation_contract"]["primary_aggregate"]["name"],
        "OVERALL_APPLICABLE_MEAN",
        "Primary aggregate",
    )
    c.check("EVIDENCE_FAITHFULNESS" in modes["evaluation_contract"]["secondary_response_outcomes"],
            "Evidence Faithfulness missing")
    c.check("UNSUPPORTED_CLAIM_COUNT" in modes["evaluation_contract"]["secondary_response_outcomes"],
            "Unsupported Claim Count missing")
    c.check(bool(modes["evaluation_contract"]["retrieval_metrics"]), "Retrieval metrics missing")
    c.check(bool(modes["evaluation_contract"]["memory_metrics"]), "Memory metrics missing")
    c.check(bool(modes["evaluation_contract"]["planner_metrics"]), "Planner metrics missing")
    c.check(bool(modes["evaluation_contract"]["efficiency_metrics"]), "Efficiency metrics missing")

    c.equal(len(replay), 558, "Replay record count")
    c.equal(len({row["replay_record_id"] for row in replay}), 558, "Unique replay record IDs")
    c.equal(Counter(row["mode_id"] for row in replay), Counter({mode_id: 62 for mode_id in MODE_LOCKS}),
            "Records per mode")
    c.equal(Counter(row["scenario_id"] for row in replay), Counter({f"U{i:03d}": 9 for i in range(1, 63)}),
            "Records per scenario")

    provider_by_scenario: dict[str, list[str]] = defaultdict(list)
    forbidden_provider_keys = {
        "mode_id",
        "condition_name",
        "human_gold",
        "expected_route",
        "expected_memory",
        "expected_retrieval",
        "reference_chunk_ids",
        "historical_response",
        "historical_judge_score",
        "response",
        "generated_response",
        "assistant_response",
        "judge_score",
    }
    persistent_record_count = 0
    for row in replay:
        scenario_id = row["scenario_id"]
        mode_id = row["mode_id"]
        c.equal(row["execution_status"], "UNEXECUTED_NO_RESPONSE_NO_PROVIDER_CALL", "Replay status")
        c.equal(row["dataset_id"], PRIMARY_DATASET_ID, "Replay dataset")
        c.check(mode_id in MODE_LOCKS, f"Unknown replay mode: {mode_id}")
        record_without_hash = dict(row)
        recorded_hash = record_without_hash.pop("record_identity_sha256")
        c.equal(recorded_hash, object_sha256(record_without_hash), "Replay record identity hash")
        provider = row["provider_input"]
        provider_by_scenario[scenario_id].append(canonical_json(provider))
        c.check(not (set(provider) & forbidden_provider_keys), "Forbidden provider-input key")
        c.equal(provider["current_query"], final_by_id[scenario_id]["primary_input"]["student_query"],
                "Replay query identity")
        c.equal(provider["current_page"], final_by_id[scenario_id]["primary_input"]["current_page"],
                "Replay page identity")
        c.equal(provider["generator_model_placeholder"], GENERATOR_PLACEHOLDER, "Generator placeholder")
        c.equal(provider["shared_prompt_placeholder"], PROMPT_PLACEHOLDER, "Prompt placeholder")
        c.equal(provider["temperature"], 0.0, "Temperature")
        c.equal(provider["maximum_tokens"], 512, "Maximum tokens")
        lock = row["condition_lock"]
        c.equal(
            (lock["evidence_synthesis"], lock["rag"], lock["memory"], lock["planning"]),
            MODE_LOCKS[mode_id],
            "Replay condition lock",
        )
        c.equal(row["p3_gate"]["binding_sha256"], P3_SHA256, "Replay P3 hash")
        c.equal(row["p3_gate"]["human_gold_used_for_gating"], False, "Gold not used for gating")
        c.equal(row["evaluation_only_reference"]["excluded_from_provider_input"], True,
                "Evaluation reference separation")
        c.equal(row["state_reset"]["cross_record_reuse"], False, "No cross-record state")
        c.equal(row["state_reset"]["production_commit"], False, "No production commit")
        c.equal(row["memory_session_fixture"]["target_query"], provider["current_query"],
                "Memory target query identity")
        c.equal(row["memory_session_fixture"]["target_query_preserved_byte_for_byte"], True,
                "Memory target preserved flag")
        for value in row["track_d_actual_execution_counters"].values():
            c.equal(value, 0, "Replay execution counter")

        memory_row = memory_by_id.get(scenario_id)
        native_history = row["source_input_audit"]["native_visible_conversation_history"]
        c.equal(row["source_input_audit"]["native_visible_history_sha256"], object_sha256(native_history),
                "Native history hash")
        if memory_row and memory_row["persistent_replay_eligible"] == "YES":
            persistent_record_count += 1
            fixture = row["memory_session_fixture"]
            c.equal(fixture["persistent_replay_eligible"], True, "Persistent fixture eligibility")
            c.equal(fixture["earlier_session_setup_turns"], native_history, "Verbatim earlier-session setup")
            c.equal(provider["visible_conversation_history"], [], "Persistent target history reset")
            c.equal(fixture["session_boundary"]["required"], True, "Persistent session boundary")
            c.equal(
                row["source_input_audit"]["history_transform"],
                "MOVE_VERBATIM_NATIVE_HISTORY_TO_EARLIER_SESSION_SETUP",
                "Persistent history transform",
            )
        else:
            c.equal(row["memory_session_fixture"]["earlier_session_setup_turns"], [], "No setup for native replay")
            c.equal(provider["visible_conversation_history"], native_history, "Native visible history preserved")
            c.equal(row["source_input_audit"]["history_transform"], "NO_TRANSFORM", "No history transform")

    c.equal(persistent_record_count, 81, "Persistent replay manifest records")
    for scenario_id, provider_values in provider_by_scenario.items():
        c.equal(len(provider_values), 9, f"Provider-input mode count for {scenario_id}")
        c.equal(len(set(provider_values)), 1, f"Provider inputs differ across modes for {scenario_id}")

    method = (HERE / "C4_REAL_DATASET_AND_ABLATION_METHOD.md").read_text(encoding="utf-8")
    status = (HERE / "STATUS.md").read_text(encoding="utf-8")
    method_compact = " ".join(method.split())
    for phrase in [
        PRIMARY_DATASET_ID,
        ORIGINAL_SUBSET_ID,
        "558",
        "No P3 decision is produced in this freeze",
        "Hard stop",
    ]:
        c.check(phrase in method_compact, f"Method disclosure missing: {phrase}")
    for phrase in [
        "FROZEN_COMPLETE_UNEXECUTED",
        "Response generation: 0",
        "Provider/model calls: 0",
        "Controlled RQ3 shard executions: 0",
    ]:
        c.check(phrase in status, f"Status disclosure missing: {phrase}")

    return c.count


def main() -> None:
    count = validate()
    print(f"PASS: {count} read-only Track D validation checks")


if __name__ == "__main__":
    main()
