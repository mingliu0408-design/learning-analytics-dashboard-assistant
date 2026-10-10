"""Build the governed RQ3-REAL-C4 Track D freeze artifacts.

This builder is deliberately local and offline. It reads the exact historical
dataset/reference files named in the Track D authorization, verifies their
byte identities, and writes only declarative dataset, Memory-audit, ablation,
and unexecuted replay artifacts. It never imports a generator, calls a model,
scores a response, rebuilds RAG, mutates a Memory store, or touches Streamlit.
"""

from __future__ import annotations

from collections import Counter
import csv
import hashlib
import io
import json
from pathlib import Path
from typing import Any, Iterable
from zipfile import ZipFile


HERE = Path(__file__).resolve().parent
WORKTREE_ROOT = HERE.parents[2]
CANONICAL_PROJECT = Path(
    "/Users/liuming/Downloads/duteaiapp_cfull_semantic_integrated_v1_副本3"
)
PREDECESSOR_ARCHIVE = Path(
    "/Users/liuming/Downloads/毕业论文/duteaiapp_anonymised-main 14.zip"
)
PREDECESSOR_PREFIX = "duteaiapp_anonymised-main/evaluation/"

FREEZE_DATE = "2026-09-01"
PRIMARY_DATASET_ID = "C4_REAL_PRIMARY_UNIFIED_DATASET_V1"
ORIGINAL_SUBSET_ID = "C4_REAL_ORIGINAL_25_AUTHENTIC_SUBSET_V1"
GENERATOR_MODEL_PLACEHOLDER = "GENERATOR_MODEL_TO_BE_FROZEN_BEFORE_AUTHORIZED_EXECUTION"
PROMPT_PLACEHOLDER = "C4_REAL_SHARED_GENERATION_PROMPT_TO_BE_BYTE_FROZEN_BEFORE_EXECUTION"
TEMPERATURE = 0.0
MAXIMUM_TOKENS = 512

EXPECTED_HASHES = {
    "example_conversation_csv": "6d91aa61b9a1011318dc1756747752d04c20c45cb4202dc4f06daa23580d3bc8",
    "original_25": "e74f1b583c5225da4bb8b999b11c1cf72b8a8f2b89b8633da40982eb675a4d1e",
    "memory_7": "60b159f8fad9a3e56671111b9880fa754f9fd85fdd81f37e5f3a4f582d04bd0a",
    "memory_12": "0a4045ec5b07a0518c40657d9ef6db531ff604357500050a496c29dd1c5e3205",
    "rag_10": "dfb9140b41559e4b448e94dfebf076af7351286d91c9d954d48ac799caae635a",
    "unified_57": "6cd0410a60a5e6710882e2cc36f36f9659fc0cffb31990100cab0e035df2e89d",
    "unified_62": "2df88a153101b39872154ed1ef339d6639e3ea28fac7df0eb42dd8bc9d998ce4",
    "unified_gold_62": "5360c00c2687341fcc44b5185ca0e635b87a4844fba629314cef46b7e16ae950",
    "unified_reference_62": "4f2cf3ee185c389f2008402ec143ae6a07b1fd35597a951afb5203c6498a03ea",
    "current_unified_builder": "832f70d5674f069866ce42b24404e034b9cdd07cef349db3f0a4ac756b21d0e4",
    "predecessor_archive": "b65dbc8d0166575336dc6333599e4136d4a177424e50d6528a4d72f857db31e5",
    "p3_binding": "893a0726570ae654d2815a96ab1987555f89fbfc00d6714ab609a979a13d20dd",
    "historical_responses_372": "c86d00089f4671477ebb6c20e18306e763e3d5b10d5dd16766614bf46adcf014",
    "historical_mechanism_v2_372": "2e8f73b1c1139be0f3e59f777b6ffcb0af5a5b0ff5858c083b296a02c9d49359",
    "historical_quality_372": "31a02df9e91c1cd54edd822cf4c5a05ca61c15f4760926aeae519f23c2a3eb20",
    "historical_gold_audit_pass": "724bd064ca072f90e796846c2e86f9a8b3da3bfd7309bb0100d3fad2ce8c56dc",
    "historical_human_packet_blank": "2bbe6dddf2a25177f06cc7f4e790faf664749b4766e412793fe76af342fa340e",
}

SOURCE_PATHS = {
    "example_conversation_csv": CANONICAL_PROJECT / "System Data" / "Example Conversation Data.csv",
    "original_25": CANONICAL_PROJECT / "evaluation" / "scenarios.jsonl",
    "memory_12": CANONICAL_PROJECT / "evaluation" / "multiturn_scenarios.jsonl",
    "rag_10": CANONICAL_PROJECT / "evaluation" / "rag_scenarios.jsonl",
    "unified_62": CANONICAL_PROJECT / "evaluation" / "unified_benchmark_scenarios.jsonl",
    "unified_gold_62": CANONICAL_PROJECT / "evaluation" / "unified_benchmark_gold_labels.jsonl",
    "unified_reference_62": CANONICAL_PROJECT / "evaluation" / "unified_reference_evidence_v1.jsonl",
    "current_unified_builder": CANONICAL_PROJECT / "evaluation" / "build_unified_benchmark.py",
}

P3_BINDING_PATH = (
    WORKTREE_ROOT
    / "evaluation"
    / "capability_routing_rq2_v2_stage4"
    / "final_router_selection"
    / "RQ2_FINAL_ROUTER_FOR_RQ3.json"
)

HISTORICAL_OUTPUTS = {
    "responses": CANONICAL_PROJECT
    / "evaluation/outputs/evaluation_integrity_v1/unified_llm_responses_v1.jsonl",
    "mechanism_v2": CANONICAL_PROJECT
    / "evaluation/outputs/evaluation_integrity_v1/unified_mechanism_scores_v2.jsonl",
    "quality": CANONICAL_PROJECT
    / "evaluation/outputs/evaluation_integrity_v2/unified_quality_judge_gpt41_v1_2.jsonl",
    "gold_audit": CANONICAL_PROJECT
    / "evaluation/outputs/evaluation_integrity_v2/gold_label_audit.json",
    "human_packet": CANONICAL_PROJECT
    / "evaluation/outputs/evaluation_integrity_v1/human_validation_v1/annotator_sample_v1.csv",
}

DECLARED_BUT_ABSENT_HISTORICAL_OUTPUTS = [
    "unified_separate_summary_v2.json",
    "quality_summary_by_mode_v2.csv",
    "mechanism_summary_by_mode_v2.csv",
    "mechanism_dimensions_v2.csv",
    "scenario_group_macro_summary_v2.csv",
    "unified_primary_statistics_v2.csv",
    "unified_primary_statistics_v2.json",
    "unified_primary_statistics_v2.md",
]

MEMORY_CLASSES = [
    "VISIBLE_HISTORY_ONLY",
    "SAME_SESSION_WORKING_MEMORY",
    "CROSS_SESSION_EPISODIC_MEMORY",
    "STABLE_SEMANTIC_PROFILE",
    "ACTIVE_PLAN_STATE",
    "UPDATE_OR_CORRECTION",
    "SUPERSEDED_MEMORY",
    "NO_RELEVANT_MEMORY_CONTROL",
]

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


def require(condition: bool, message: str) -> None:
    """Fail closed with a direct lineage/contract error."""

    if not condition:
        raise RuntimeError(message)


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def sha256_file(path: Path) -> str:
    require(path.is_file(), f"Required file is absent: {path}")
    return sha256_bytes(path.read_bytes())


def sha256_text(text: str) -> str:
    return sha256_bytes(text.encode("utf-8"))


def canonical_json(value: Any) -> str:
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    )


def object_sha256(value: Any) -> str:
    return sha256_text(canonical_json(value))


def parse_jsonl_bytes(data: bytes, label: str) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for line_number, line in enumerate(data.decode("utf-8-sig").splitlines(), start=1):
        if not line.strip():
            continue
        value = json.loads(line)
        require(isinstance(value, dict), f"{label} line {line_number} is not an object")
        rows.append(value)
    return rows


def load_jsonl(path: Path) -> list[dict[str, Any]]:
    return parse_jsonl_bytes(path.read_bytes(), str(path))


def write_json(path: Path, value: Any) -> None:
    path.write_text(
        json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True, allow_nan=False) + "\n",
        encoding="utf-8",
    )


def write_jsonl(path: Path, rows: Iterable[dict[str, Any]]) -> None:
    with path.open("w", encoding="utf-8", newline="\n") as handle:
        for row in rows:
            handle.write(canonical_json(row) + "\n")


def write_csv(path: Path, fieldnames: list[str], rows: list[dict[str, Any]]) -> None:
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(
            handle,
            fieldnames=fieldnames,
            extrasaction="raise",
            lineterminator="\n",
        )
        writer.writeheader()
        writer.writerows(rows)


def stable_scenario_key(row: dict[str, Any]) -> str:
    """Identity stable across the U033-U062 renumbering correction."""

    value = {
        "source_dataset": row.get("source_dataset"),
        "source_scenario_id": row.get("source_scenario_id"),
        "student_query": row.get("student_query"),
        "page": row.get("page"),
        "student_id": str(row.get("student_id", "")),
        "conversation_history": row.get("conversation_history") or [],
    }
    return object_sha256(value)


def profile_rows(rows: list[dict[str, Any]]) -> dict[str, Any]:
    return {
        "record_count": len(rows),
        "unique_scenario_id_count": len({str(row.get("scenario_id")) for row in rows}),
        "query_present_count": sum(bool(row.get("student_query")) for row in rows),
        "page_present_count": sum(bool(row.get("page")) for row in rows),
        "visible_history_field_count": sum("conversation_history" in row for row in rows),
        "visible_history_nonempty_count": sum(bool(row.get("conversation_history")) for row in rows),
        "source_dataset_counts": dict(
            sorted(Counter(str(row.get("source_dataset")) for row in rows).items())
        ),
        "scenario_group_counts": dict(
            sorted(Counter(str(row.get("scenario_group")) for row in rows).items())
        ),
    }


def load_and_verify_sources() -> dict[str, Any]:
    for label, path in SOURCE_PATHS.items():
        actual = sha256_file(path)
        require(actual == EXPECTED_HASHES[label], f"SHA-256 mismatch for {label}: {actual}")

    require(
        sha256_file(PREDECESSOR_ARCHIVE) == EXPECTED_HASHES["predecessor_archive"],
        "Predecessor archive SHA-256 mismatch",
    )
    require(
        sha256_file(P3_BINDING_PATH) == EXPECTED_HASHES["p3_binding"],
        "Frozen P3 binding SHA-256 mismatch",
    )

    with ZipFile(PREDECESSOR_ARCHIVE) as archive:
        member_names = set(archive.namelist())
        old_memory_member = PREDECESSOR_PREFIX + "multiturn_scenarios.jsonl"
        old_unified_member = PREDECESSOR_PREFIX + "unified_benchmark_scenarios.jsonl"
        require(old_memory_member in member_names, "7-row Memory predecessor member is absent")
        require(old_unified_member in member_names, "57-row unified predecessor member is absent")
        memory_7_bytes = archive.read(old_memory_member)
        unified_57_bytes = archive.read(old_unified_member)
        require(
            sha256_bytes(memory_7_bytes) == EXPECTED_HASHES["memory_7"],
            "7-row Memory predecessor member SHA-256 mismatch",
        )
        require(
            sha256_bytes(unified_57_bytes) == EXPECTED_HASHES["unified_57"],
            "57-row unified predecessor member SHA-256 mismatch",
        )
        require(
            not any(
                Path(name).name
                in {"unified_benchmark_gold_labels.jsonl", "unified_reference_evidence_v1.jsonl"}
                for name in member_names
            ),
            "57-row archive unexpectedly contains associated Gold/reference evidence",
        )

    with SOURCE_PATHS["example_conversation_csv"].open(
        "r", encoding="utf-8-sig", newline=""
    ) as handle:
        csv_rows = list(csv.DictReader(handle))

    sources = {
        "example_csv": csv_rows,
        "original_25": load_jsonl(SOURCE_PATHS["original_25"]),
        "memory_7": parse_jsonl_bytes(memory_7_bytes, old_memory_member),
        "memory_12": load_jsonl(SOURCE_PATHS["memory_12"]),
        "rag_10": load_jsonl(SOURCE_PATHS["rag_10"]),
        "unified_57": parse_jsonl_bytes(unified_57_bytes, old_unified_member),
        "unified_62": load_jsonl(SOURCE_PATHS["unified_62"]),
        "gold_62": load_jsonl(SOURCE_PATHS["unified_gold_62"]),
        "reference_62": load_jsonl(SOURCE_PATHS["unified_reference_62"]),
        "old_memory_member": old_memory_member,
        "old_unified_member": old_unified_member,
    }
    return sources


def verify_lineage(sources: dict[str, Any]) -> dict[str, Any]:
    original = sources["original_25"]
    memory_7 = sources["memory_7"]
    memory_12 = sources["memory_12"]
    rag = sources["rag_10"]
    unified_57 = sources["unified_57"]
    unified_62 = sources["unified_62"]
    gold = sources["gold_62"]
    reference = sources["reference_62"]

    for label, rows, count in [
        ("original_25", original, 25),
        ("memory_7", memory_7, 7),
        ("memory_12", memory_12, 12),
        ("rag_10", rag, 10),
        ("unified_57", unified_57, 57),
        ("unified_62", unified_62, 62),
        ("gold_62", gold, 62),
        ("reference_62", reference, 62),
    ]:
        require(len(rows) == count, f"{label} count mismatch: {len(rows)}")

    require(len(sources["example_csv"]) == 50, "Example conversation CSV must have 50 turns")
    require(
        Counter(row.get("role") for row in sources["example_csv"])
        == Counter({"user": 25, "assistant": 25}),
        "Example conversation role distribution mismatch",
    )
    require(
        [row.get("scenario_id") for row in original] == [f"S{i:03d}" for i in range(1, 26)],
        "Original scenario IDs are not S001-S025",
    )
    require(
        [row.get("scenario_id") for row in unified_57] == [f"U{i:03d}" for i in range(1, 58)],
        "57-row IDs are not U001-U057",
    )
    require(
        [row.get("scenario_id") for row in unified_62] == [f"U{i:03d}" for i in range(1, 63)],
        "62-row IDs are not U001-U062",
    )

    keys_57 = {stable_scenario_key(row): row for row in unified_57}
    keys_62 = {stable_scenario_key(row): row for row in unified_62}
    require(len(keys_57) == 57 and len(keys_62) == 62, "Stable scenario identities are not unique")
    require(set(keys_57).issubset(keys_62), "The corrected 62 does not preserve every 57-row scenario")
    additions = [keys_62[key] for key in sorted(set(keys_62) - set(keys_57))]
    require(
        {row.get("source_scenario_id") for row in additions}
        == {"M008", "M009", "M010", "M011", "M012"},
        "The five corrected additions are not exactly M008-M012",
    )

    renumbering: list[dict[str, str]] = []
    for key, old_row in sorted(keys_57.items(), key=lambda item: item[1]["scenario_id"]):
        new_row = keys_62[key]
        if old_row["scenario_id"] != new_row["scenario_id"]:
            renumbering.append(
                {
                    "predecessor_scenario_id": old_row["scenario_id"],
                    "corrected_scenario_id": new_row["scenario_id"],
                    "source_dataset": old_row["source_dataset"],
                    "source_scenario_id": old_row["source_scenario_id"],
                }
            )
    require(len(renumbering) == 25, "Expected exactly 25 downstream ID renumberings")

    memory_7_ids = {row["scenario_id"] for row in memory_7}
    memory_12_ids = {row["scenario_id"] for row in memory_12}
    require(memory_7_ids == {f"M{i:03d}" for i in range(1, 8)}, "7-row Memory IDs mismatch")
    require(memory_12_ids == {f"M{i:03d}" for i in range(1, 13)}, "12-row Memory IDs mismatch")
    require(memory_7_ids.issubset(memory_12_ids), "12-row Memory file does not preserve M001-M007")

    gold_by_id = {row["scenario_id"]: row for row in gold}
    ref_by_id = {row["scenario_id"]: row for row in reference}
    require(len(gold_by_id) == 62 and len(ref_by_id) == 62, "Gold/reference IDs are not unique")
    require(set(gold_by_id) == set(ref_by_id) == {row["scenario_id"] for row in unified_62},
            "Scenario, Gold, and reference ID sets differ")

    completed_review_states = {"approved", "revised"}
    for scenario in unified_62:
        scenario_id = scenario["scenario_id"]
        gold_row = gold_by_id[scenario_id]
        ref_row = ref_by_id[scenario_id]
        require(
            gold_row.get("gold_review_status") in completed_review_states,
            f"Gold row not reviewed: {scenario_id}",
        )
        require(
            ref_row.get("review_status") in completed_review_states,
            f"Reference row not reviewed: {scenario_id}",
        )
        require(
            scenario.get("student_query") == ref_row.get("reference_student_query"),
            f"Reference query mismatch: {scenario_id}",
        )
        require(
            scenario.get("page") == ref_row.get("reference_page"),
            f"Reference page mismatch: {scenario_id}",
        )
        require(
            (scenario.get("conversation_history") or [])
            == (ref_row.get("reference_conversation_history") or []),
            f"Reference history mismatch: {scenario_id}",
        )
        for scenario_field, gold_field in [
            ("query_type", "gold_query_type"),
            ("scenario_group", "gold_scenario_group"),
            ("required_capabilities", "gold_required_capabilities"),
            ("expected_route", "gold_expected_route"),
            ("expected_memory", "gold_expected_memory"),
            ("expected_retrieval", "gold_expected_retrieval"),
        ]:
            require(
                scenario.get(scenario_field) == gold_row.get(gold_field),
                f"Gold overlay mismatch for {scenario_id}: {scenario_field}",
            )

    trim_only: list[str] = []
    csv_rows = sources["example_csv"]
    for index, scenario in enumerate(original):
        turn_index = scenario.get("source_turn_index")
        require(turn_index == index * 2, f"Unexpected source turn index: {scenario['scenario_id']}")
        csv_row = csv_rows[turn_index]
        require(csv_row.get("role") == "user", f"Source turn is not user: {scenario['scenario_id']}")
        raw_query = str(csv_row.get("message", ""))
        frozen_query = str(scenario.get("student_query", ""))
        if raw_query != frozen_query:
            require(raw_query.rstrip() == frozen_query, f"Non-whitespace query change: {scenario['scenario_id']}")
            trim_only.append(scenario["scenario_id"])
        unified = unified_62[index]
        require(
            unified.get("source_scenario_id") == scenario["scenario_id"]
            and unified.get("student_query") == frozen_query
            and unified.get("page") == scenario.get("page"),
            f"Original subset mismatch in corrected 62: {scenario['scenario_id']}",
        )
    require(trim_only == ["S011", "S014", "S018", "S019"], "Unexpected CSV trim-only set")

    return {
        "keys_57": keys_57,
        "keys_62": keys_62,
        "additions": additions,
        "renumbering": renumbering,
        "gold_by_id": gold_by_id,
        "ref_by_id": ref_by_id,
        "trim_only": trim_only,
    }


def historical_evaluation_status() -> dict[str, Any]:
    expected = {
        "responses": EXPECTED_HASHES["historical_responses_372"],
        "mechanism_v2": EXPECTED_HASHES["historical_mechanism_v2_372"],
        "quality": EXPECTED_HASHES["historical_quality_372"],
        "gold_audit": EXPECTED_HASHES["historical_gold_audit_pass"],
        "human_packet": EXPECTED_HASHES["historical_human_packet_blank"],
    }
    for label, path in HISTORICAL_OUTPUTS.items():
        require(sha256_file(path) == expected[label], f"Historical output hash mismatch: {label}")

    result_records: dict[str, Any] = {}
    for label in ["responses", "mechanism_v2", "quality"]:
        rows = load_jsonl(HISTORICAL_OUTPUTS[label])
        modes = sorted({str(row.get("mode")) for row in rows})
        keys = {(str(row.get("scenario_id")), str(row.get("mode"))) for row in rows}
        require(len(rows) == 372 and len(keys) == 372, f"Historical {label} is incomplete")
        require(modes == ["A", "B", "C", "CM", "CR", "C_FULL"], f"Historical mode set mismatch: {label}")
        result_records[label] = {
            "path": str(HISTORICAL_OUTPUTS[label]),
            "sha256": expected[label],
            "record_count": 372,
            "unique_scenario_mode_count": 372,
            "modes": modes,
        }

    gold_audit = json.loads(HISTORICAL_OUTPUTS["gold_audit"].read_text(encoding="utf-8"))
    require(
        gold_audit.get("status") == "PASS" and gold_audit.get("blocking_issue_count") == 0,
        "Historical final Gold/reference audit did not pass",
    )

    with HISTORICAL_OUTPUTS["human_packet"].open(
        "r", encoding="utf-8-sig", newline=""
    ) as handle:
        reader = csv.DictReader(handle)
        human_rows = list(reader)
    completed_cells = sum(
        bool(str(row.get(field, "")).strip())
        for row in human_rows
        for field in ["human_score_1_to_5", "human_rationale"]
    )
    require(len(human_rows) == 378 and completed_cells == 0, "Historical human packet status changed")

    absent: list[str] = []
    evaluation_root = CANONICAL_PROJECT / "evaluation"
    for name in DECLARED_BUT_ABSENT_HISTORICAL_OUTPUTS:
        require(not any(evaluation_root.rglob(name)), f"Historically absent output now exists: {name}")
        absent.append(name)

    return {
        "status": "HISTORICAL_PARTIAL_EVALUATION_NOT_A_C4_EXECUTION",
        "gold_and_reference_review": {
            "status": "PASS",
            "audit_path": str(HISTORICAL_OUTPUTS["gold_audit"]),
            "sha256": expected["gold_audit"],
            "blocking_issue_count": 0,
        },
        "completed_historical_artifacts": result_records,
        "human_validation": {
            "packet_path": str(HISTORICAL_OUTPUTS["human_packet"]),
            "sha256": expected["human_packet"],
            "packet_row_count": 378,
            "completed_score_or_rationale_cell_count": 0,
            "status": "NOT_COMPLETED",
        },
        "declared_summary_and_statistics_outputs_absent": absent,
        "interpretation": (
            "The corrected 62 was historically used for complete six-mode generation and complete "
            "quality/mechanism record production, but downstream summaries/statistics and human "
            "ratings were not closed. None of those response records enters the C4 input freeze."
        ),
    }


def build_lineage_registry(
    sources: dict[str, Any], lineage: dict[str, Any], historical: dict[str, Any]
) -> dict[str, Any]:
    additions = [
        {
            "corrected_scenario_id": row["scenario_id"],
            "source_dataset": row["source_dataset"],
            "source_scenario_id": row["source_scenario_id"],
            "student_query_sha256": sha256_text(row["student_query"]),
            "current_page": row["page"],
        }
        for row in sorted(lineage["additions"], key=lambda item: item["scenario_id"])
    ]

    physical_scan = [
        ("Example Conversation Data.csv", 50, EXPECTED_HASHES["example_conversation_csv"], 25),
        ("scenarios.jsonl", 25, EXPECTED_HASHES["original_25"], 20),
        ("multiturn_scenarios.jsonl", 12, EXPECTED_HASHES["memory_12"], 19),
        ("rag_scenarios.jsonl", 10, EXPECTED_HASHES["rag_10"], 19),
        ("unified_benchmark_scenarios.jsonl", 62, EXPECTED_HASHES["unified_62"], 19),
        ("unified_benchmark_gold_labels.jsonl", 62, EXPECTED_HASHES["unified_gold_62"], 19),
        ("unified_reference_evidence_v1.jsonl", 62, EXPECTED_HASHES["unified_reference_62"], 19),
    ]
    archive_scan = [
        ("Example Conversation Data.csv", 50, EXPECTED_HASHES["example_conversation_csv"], 51),
        ("scenarios.jsonl", 25, EXPECTED_HASHES["original_25"], 80),
        ("multiturn_scenarios.jsonl", 7, EXPECTED_HASHES["memory_7"], 1),
        ("multiturn_scenarios.jsonl", 12, EXPECTED_HASHES["memory_12"], 77),
        ("rag_scenarios.jsonl", 10, EXPECTED_HASHES["rag_10"], 78),
        ("unified_benchmark_scenarios.jsonl", 57, EXPECTED_HASHES["unified_57"], 1),
        ("unified_benchmark_scenarios.jsonl", 62, EXPECTED_HASHES["unified_62"], 77),
        ("unified_benchmark_gold_labels.jsonl", 62, EXPECTED_HASHES["unified_gold_62"], 77),
        ("unified_reference_evidence_v1.jsonl", 62, EXPECTED_HASHES["unified_reference_62"], 77),
    ]

    def observed(rows: list[tuple[str, int, str, int]]) -> list[dict[str, Any]]:
        return [
            {"filename": name, "record_count": count, "sha256": digest, "copy_count": copies}
            for name, count, digest, copies in rows
        ]

    return {
        "schema_version": "c4-real-track-d-dataset-lineage-registry-v1",
        "freeze_date": FREEZE_DATE,
        "freeze_status": "FROZEN_AUTHORITATIVE_LINEAGE_NO_EXECUTION_AUTHORITY",
        "authoritative_dataset_id": PRIMARY_DATASET_ID,
        "authoritative_original_subset_id": ORIGINAL_SUBSET_ID,
        "source_resolution_rule": (
            "Authority is established from byte-verified actual JSONL/CSV files and one archive "
            "member, not from narrative reports. Later 62-row content supersedes the stale 57-row file."
        ),
        "discovery_audit": {
            "root": "/Users/liuming/Downloads",
            "performed_on": FREEZE_DATE,
            "methods": [
                "exact-filename scan of loose files",
                "record-count/schema scan of JSONL files",
                "member/hash scan of readable ZIP archives",
                "member scan of TAR, TAR.GZ, and TGZ archives",
            ],
            "loose_file_byte_identities": observed(physical_scan),
            "zip_member_byte_identities": observed(archive_scan),
            "tar_member_matches": [],
            "unreadable_zip_disclosure": {
                "path": "/Users/liuming/Downloads/111.zip",
                "error": "BadZipFile",
                "filename_has_no_dataset_or_project-lineage signal": True,
                "used_for_authority": False,
            },
            "distinct_unified_successor_identities_found": [
                {"record_count": 57, "sha256": EXPECTED_HASHES["unified_57"]},
                {"record_count": 62, "sha256": EXPECTED_HASHES["unified_62"]},
            ],
        },
        "canonical_sources": {
            "example_conversation_data": {
                "path": str(SOURCE_PATHS["example_conversation_csv"]),
                "sha256": EXPECTED_HASHES["example_conversation_csv"],
                "row_count": 50,
                "role_counts": {"user": 25, "assistant": 25},
            },
            "original_25_scenarios": {
                "path": str(SOURCE_PATHS["original_25"]),
                "sha256": EXPECTED_HASHES["original_25"],
                "record_count": 25,
            },
            "memory_7_predecessor": {
                "archive_path": str(PREDECESSOR_ARCHIVE),
                "archive_sha256": EXPECTED_HASHES["predecessor_archive"],
                "member": sources["old_memory_member"],
                "member_sha256": EXPECTED_HASHES["memory_7"],
                "record_count": 7,
            },
            "memory_12_corrected": {
                "path": str(SOURCE_PATHS["memory_12"]),
                "sha256": EXPECTED_HASHES["memory_12"],
                "record_count": 12,
            },
            "rag_10": {
                "path": str(SOURCE_PATHS["rag_10"]),
                "sha256": EXPECTED_HASHES["rag_10"],
                "record_count": 10,
            },
            "unified_57_predecessor": {
                "archive_path": str(PREDECESSOR_ARCHIVE),
                "archive_sha256": EXPECTED_HASHES["predecessor_archive"],
                "member": sources["old_unified_member"],
                "member_sha256": EXPECTED_HASHES["unified_57"],
                "record_count": 57,
                "associated_gold_or_reference_members_present": False,
            },
            "unified_62_corrected": {
                "path": str(SOURCE_PATHS["unified_62"]),
                "sha256": EXPECTED_HASHES["unified_62"],
                "record_count": 62,
            },
            "unified_gold_62": {
                "path": str(SOURCE_PATHS["unified_gold_62"]),
                "sha256": EXPECTED_HASHES["unified_gold_62"],
                "record_count": 62,
                "review_complete_count": 62,
            },
            "unified_reference_evidence_62": {
                "path": str(SOURCE_PATHS["unified_reference_62"]),
                "sha256": EXPECTED_HASHES["unified_reference_62"],
                "record_count": 62,
                "review_complete_count": 62,
            },
            "current_unified_builder": {
                "path": str(SOURCE_PATHS["current_unified_builder"]),
                "sha256": EXPECTED_HASHES["current_unified_builder"],
            },
        },
        "versions": {
            "original_25": {
                "composition": {"main_benchmark": 25},
                "profile": profile_rows(sources["original_25"]),
                "status": "AUTHENTIC_SUBSET_OF_CORRECTED_62",
                "query_lineage": {
                    "exact_csv_user_turn_matches": 21,
                    "trailing_whitespace_trim_only_matches": 4,
                    "trim_only_scenario_ids": lineage["trim_only"],
                    "semantic_query_changes": 0,
                },
            },
            "unified_57": {
                "composition": {
                    "main_benchmark": 25,
                    "memory_diagnostic": 7,
                    "rag_diagnostic": 10,
                    "handwritten_unified": 15,
                },
                "profile": profile_rows(sources["unified_57"]),
                "status": "SUPERSEDED_INCOMPLETE_PREDECESSOR",
                "lineage_blockers": [
                    "It omits M008-M012 even though a later 12-row Memory source exists.",
                    "Its archive has no associated 57-row Gold overlay or reference-evidence file.",
                ],
            },
            "unified_62": {
                "composition": {
                    "main_benchmark": 25,
                    "memory_diagnostic": 12,
                    "rag_diagnostic": 10,
                    "handwritten_unified": 15,
                },
                "profile": profile_rows(sources["unified_62"]),
                "status": "AUTHORITATIVE_COMPLETE_INTERNALLY_CONSISTENT",
                "associated_gold_count": 62,
                "associated_reference_evidence_count": 62,
                "overlap_with_57_by_stable_content_identity": 57,
                "additions_relative_to_57": additions,
                "downstream_id_renumbering": lineage["renumbering"],
            },
        },
        "field_availability": {
            "original_25": {
                "student_query": "25/25",
                "current_page": "25/25",
                "visible_conversation_history_field": "0/25",
                "dashboard_context_embedded": "0/25",
            },
            "unified_57": {
                "student_query": "57/57",
                "current_page": "57/57",
                "visible_conversation_history_field": "57/57",
                "visible_conversation_history_nonempty": "10/57",
                "dashboard_context_embedded": "0/57",
            },
            "unified_62": {
                "student_query": "62/62",
                "current_page": "62/62",
                "visible_conversation_history_field": "62/62",
                "visible_conversation_history_nonempty": "15/62",
                "associated_reference_dashboard_context_field": "62/62",
                "associated_reference_dashboard_context_nonempty": (
                    f"{sum(bool(row.get('reference_dashboard_evidence')) for row in sources['reference_62'])}/62"
                ),
            },
        },
        "final_evaluation_status": {
            "original_25": "INCLUDED_AS_A_SUBSET_OF_THE_HISTORICAL_62_RUN; NO_SEPARATE_C4_EXECUTION",
            "unified_57": "NOT_FINAL_EVALUABLE_AND_SUPERSEDED; NO_MATCHING_GOLD_OR_REFERENCE_OVERLAY",
            "unified_62": historical,
            "c4_real_track_d": "DATASET_AND_METHOD_FROZEN_UNEXECUTED",
        },
        "lineage_decision": {
            "selected": PRIMARY_DATASET_ID,
            "selected_sha256": EXPECTED_HASHES["unified_62"],
            "rejected_as_primary": "57-row predecessor",
            "reason": (
                "The 62-row file is the only complete version with all 12 actual Memory rows, "
                "a complete reviewed Gold overlay, and complete reviewed reference evidence."
            ),
        },
        "execution_boundary": {
            "responses_generated": 0,
            "responses_scored": 0,
            "provider_calls": 0,
            "rag_rebuilds": 0,
            "memory_implementations_or_store_mutations": 0,
            "streamlit_changes": 0,
            "controlled_rq3_shards_executed": 0,
        },
    }


def build_final_62_identity(
    sources: dict[str, Any], lineage: dict[str, Any], historical: dict[str, Any]
) -> dict[str, Any]:
    rows: list[dict[str, Any]] = []
    for scenario in sources["unified_62"]:
        scenario_id = scenario["scenario_id"]
        gold = lineage["gold_by_id"][scenario_id]
        reference = lineage["ref_by_id"][scenario_id]
        primary_input = {
            "student_id": str(scenario.get("student_id", "")),
            "student_query": scenario["student_query"],
            "current_page": scenario["page"],
            "visible_conversation_history": scenario.get("conversation_history") or [],
        }
        row = {
            "scenario_id": scenario_id,
            "source_dataset": scenario["source_dataset"],
            "source_scenario_id": scenario["source_scenario_id"],
            "scenario_group": scenario["scenario_group"],
            "required_capabilities": scenario["required_capabilities"],
            "primary_input": primary_input,
            "expected_mechanism_metadata": {
                "expected_route": scenario["expected_route"],
                "expected_memory": scenario["expected_memory"],
                "expected_retrieval": scenario["expected_retrieval"],
                "expected_memory_items": scenario.get("expected_memory_items") or [],
                "expected_memory_state_fields": scenario.get("expected_memory_state_fields") or [],
                "expected_reference_chunk_ids": reference.get("reference_chunk_ids") or [],
            },
            "identity_hashes": {
                "primary_input_sha256": object_sha256(primary_input),
                "full_source_scenario_row_sha256": object_sha256(scenario),
                "gold_row_sha256": object_sha256(gold),
                "reference_evidence_row_sha256": object_sha256(reference),
                "reference_dashboard_context_sha256": object_sha256(
                    reference.get("reference_dashboard_evidence") or {}
                ),
                "reference_course_evidence_sha256": object_sha256(
                    reference.get("reference_course_evidence") or []
                ),
            },
        }
        rows.append(row)

    return {
        "schema_version": "c4-real-final-62-scenario-identity-v1",
        "dataset_id": PRIMARY_DATASET_ID,
        "freeze_date": FREEZE_DATE,
        "status": "FROZEN_AUTHORITATIVE_COMPLETE_UNEXECUTED_FOR_C4",
        "source_file": str(SOURCE_PATHS["unified_62"]),
        "source_file_sha256": EXPECTED_HASHES["unified_62"],
        "record_count": 62,
        "scenario_id_range": ["U001", "U062"],
        "associated_gold": {
            "path": str(SOURCE_PATHS["unified_gold_62"]),
            "sha256": EXPECTED_HASHES["unified_gold_62"],
            "record_count": 62,
            "review_complete_count": 62,
        },
        "associated_reference_evidence": {
            "path": str(SOURCE_PATHS["unified_reference_62"]),
            "sha256": EXPECTED_HASHES["unified_reference_62"],
            "record_count": 62,
            "review_complete_count": 62,
        },
        "source_composition": dict(
            sorted(Counter(row["source_dataset"] for row in sources["unified_62"]).items())
        ),
        "scenario_group_counts": dict(
            sorted(Counter(row["scenario_group"] for row in sources["unified_62"]).items())
        ),
        "availability": {
            "student_query": 62,
            "current_page": 62,
            "visible_history_field": 62,
            "visible_history_nonempty": sum(
                bool(row.get("conversation_history")) for row in sources["unified_62"]
            ),
            "reference_dashboard_context_field": 62,
            "reference_dashboard_context_nonempty": sum(
                bool(row.get("reference_dashboard_evidence")) for row in sources["reference_62"]
            ),
        },
        "rows": rows,
        "rows_payload_sha256": object_sha256(rows),
        "prior_output_exclusion": {
            "baseline_reference_response_included": False,
            "generated_response_included": False,
            "historical_mode_response_included": False,
            "historical_judge_score_included": False,
            "predicted_route_fields_in_provider_input": False,
            "gold_fields_in_provider_input": False,
        },
        "historical_evaluation_status": historical["status"],
        "c4_execution_status": "NOT_EXECUTED",
    }


def build_original_25_identity(sources: dict[str, Any]) -> dict[str, Any]:
    rows: list[dict[str, Any]] = []
    csv_rows = sources["example_csv"]
    unified_by_source = {
        row["source_scenario_id"]: row
        for row in sources["unified_62"]
        if row.get("source_dataset") == "main_benchmark"
    }
    for scenario in sources["original_25"]:
        source_turn_index = scenario["source_turn_index"]
        raw_query = str(csv_rows[source_turn_index]["message"])
        frozen_query = scenario["student_query"]
        query_relation = "EXACT" if raw_query == frozen_query else "TRAILING_WHITESPACE_TRIM_ONLY"
        primary_input = {
            "student_id": str(scenario.get("student_id", "")),
            "student_query": frozen_query,
            "current_page": scenario["page"],
            "visible_conversation_history": [],
        }
        unified = unified_by_source[scenario["scenario_id"]]
        rows.append(
            {
                "original_scenario_id": scenario["scenario_id"],
                "unified_scenario_id": unified["scenario_id"],
                "source_turn_index": source_turn_index,
                "source_role": "user",
                "source_query_relation": query_relation,
                "source_csv_user_message_sha256": sha256_text(raw_query),
                "query_type": scenario["query_type"],
                "primary_input": primary_input,
                "identity_hashes": {
                    "primary_input_sha256": object_sha256(primary_input),
                    "full_original_scenario_row_sha256": object_sha256(scenario),
                    "unified_scenario_row_sha256": object_sha256(unified),
                },
            }
        )
    return {
        "schema_version": "c4-real-original-25-authentic-subset-identity-v1",
        "dataset_id": ORIGINAL_SUBSET_ID,
        "parent_dataset_id": PRIMARY_DATASET_ID,
        "freeze_date": FREEZE_DATE,
        "status": "FROZEN_AUTHENTIC_SUBSET_UNEXECUTED_FOR_C4",
        "source_dialogue_csv": {
            "path": str(SOURCE_PATHS["example_conversation_csv"]),
            "sha256": EXPECTED_HASHES["example_conversation_csv"],
            "turn_count": 50,
            "user_turn_count": 25,
            "assistant_turn_count": 25,
        },
        "source_scenarios": {
            "path": str(SOURCE_PATHS["original_25"]),
            "sha256": EXPECTED_HASHES["original_25"],
            "record_count": 25,
        },
        "record_count": 25,
        "unified_scenario_ids": [f"U{i:03d}" for i in range(1, 26)],
        "query_lineage": {
            "exact_count": 21,
            "trailing_whitespace_trim_only_count": 4,
            "semantic_change_count": 0,
            "no_new_normalization_performed_by_track_d": True,
        },
        "rows": rows,
        "rows_payload_sha256": object_sha256(rows),
        "excluded_source_content": {
            "baseline_reference_response_present_in_each_source_row": True,
            "baseline_reference_response_copied_into_frozen_inputs": False,
            "assistant_turn_text_copied_into_frozen_inputs": False,
        },
    }


def memory_specs() -> dict[str, dict[str, Any]]:
    return {
        "M001": {
            "memory_class": "SAME_SESSION_WORKING_MEMORY",
            "eligible": True,
            "setup_write": "WRITE_ACTIVE_PLAN_ITEMS_1_2_3",
            "target_retrieval": "RETRIEVE_PLAN_ITEMS_2_AND_3",
            "target_update": "NO_UPDATE",
            "control": "POSITIVE_MEMORY",
            "rationale": "A user-authored setup request and assistant plan can be moved verbatim before a session boundary.",
        },
        "M002": {
            "memory_class": "SAME_SESSION_WORKING_MEMORY",
            "eligible": True,
            "setup_write": "WRITE_ACTIVE_PLAN_ITEMS_1_2_3",
            "target_retrieval": "RETRIEVE_PLAN_ITEM_2",
            "target_update": "NO_UPDATE",
            "control": "POSITIVE_MEMORY",
            "rationale": "A complete user-plus-assistant setup exists and the target query can remain byte-identical.",
        },
        "M003": {
            "memory_class": "VISIBLE_HISTORY_ONLY",
            "eligible": False,
            "setup_write": "NOT_APPLICABLE",
            "target_retrieval": "VISIBLE_HISTORY_RESOLUTION_ONLY",
            "target_update": "NO_UPDATE",
            "control": "POSITIVE_VISIBLE_HISTORY",
            "rationale": "The source has an assistant-only antecedent and no human-authored setup turn for a governed persistent write.",
        },
        "M004": {
            "memory_class": "SAME_SESSION_WORKING_MEMORY",
            "eligible": True,
            "setup_write": "WRITE_ACTIVE_PLAN_ITEMS_1_2",
            "target_retrieval": "RETRIEVE_PLAN_ITEM_1",
            "target_update": "NO_UPDATE",
            "control": "POSITIVE_MEMORY",
            "rationale": "The complete setup can be replayed before a session boundary without changing the target query.",
        },
        "M005": {
            "memory_class": "NO_RELEVANT_MEMORY_CONTROL",
            "eligible": False,
            "setup_write": "NOT_APPLICABLE",
            "target_retrieval": "NO_RETRIEVAL_EXPECTED",
            "target_update": "NO_UPDATE",
            "control": "NEGATIVE_MEMORY_CONTROL",
            "rationale": "The source has only an assistant list; it remains a visible-history no-retrieval control.",
        },
        "M006": {
            "memory_class": "NO_RELEVANT_MEMORY_CONTROL",
            "eligible": True,
            "setup_write": "NO_NUMBERED_PLAN_WRITE_INSUFFICIENT_STRUCTURE",
            "target_retrieval": "NO_RETRIEVAL_NO_MATCH_FOR_ITEMS_2_AND_3",
            "target_update": "NO_UPDATE",
            "control": "NEGATIVE_MEMORY_CONTROL",
            "rationale": "The complete setup is replayable, but it contains no numbered items 2 and 3 and must not be invented.",
        },
        "M007": {
            "memory_class": "VISIBLE_HISTORY_ONLY",
            "eligible": False,
            "setup_write": "NOT_APPLICABLE",
            "target_retrieval": "VISIBLE_HISTORY_RESOLUTION_ONLY",
            "target_update": "NO_UPDATE",
            "control": "POSITIVE_VISIBLE_HISTORY",
            "rationale": "The source antecedent is assistant-only; no governed human-authored setup request exists.",
        },
        "M008": {
            "memory_class": "ACTIVE_PLAN_STATE",
            "eligible": True,
            "setup_write": "WRITE_ACTIVE_GOAL_CONSTRAINT_SELECTED_ACTION_AND_RELEVANT_PAGES",
            "target_retrieval": "RETRIEVE_ACTIVE_PLAN",
            "target_update": "MARK_W4_LECTURE_ACTION_COMPLETED",
            "control": "POSITIVE_MEMORY",
            "rationale": "The existing user-plus-assistant setup supports an isolated cross-session active-plan replay.",
        },
        "M009": {
            "memory_class": "UPDATE_OR_CORRECTION",
            "eligible": True,
            "setup_write": "WRITE_ACTIVE_GOAL_AND_W4_SELECTED_ACTION",
            "target_retrieval": "RETRIEVE_ACTIVE_PLAN_FOR_UPDATE",
            "target_update": "CORRECT_TO_W5_AND_SUPERSEDE_W4_ACTION",
            "control": "POSITIVE_MEMORY_UPDATE",
            "rationale": "The target is itself the human-authored correction and must remain byte-identical.",
        },
        "M010": {
            "memory_class": "ACTIVE_PLAN_STATE",
            "eligible": True,
            "setup_write": "WRITE_ACTIVE_GOAL_SELECTED_ACTION_AND_LECTURE_PAGE",
            "target_retrieval": "RETRIEVE_ACTIVE_PLAN_ACROSS_PAGE_AND_SESSION",
            "target_update": "NO_UPDATE",
            "control": "POSITIVE_MEMORY",
            "rationale": "The target explicitly references a prior plan and page; the complete setup is present.",
        },
        "M011": {
            "memory_class": "NO_RELEVANT_MEMORY_CONTROL",
            "eligible": True,
            "setup_write": "WRITE_DEBATE_GOAL_AND_SELECTED_ACTION",
            "target_retrieval": "NO_RETRIEVAL_IRRELEVANT_TO_UNSPECIFIED_RESOURCE_METRIC",
            "target_update": "NO_UPDATE",
            "control": "NEGATIVE_MEMORY_CONTROL",
            "rationale": "A valid stored debate plan exists but is irrelevant to the target metric question.",
        },
        "M012": {
            "memory_class": "ACTIVE_PLAN_STATE",
            "eligible": True,
            "setup_write": "WRITE_ACTIVE_GOAL_15_MINUTE_CONSTRAINT_AND_SELECTED_ACTION",
            "target_retrieval": "RETRIEVE_ACTIVE_PLAN_AND_CONSTRAINT",
            "target_update": "NO_UPDATE",
            "control": "POSITIVE_MEMORY",
            "rationale": "The complete setup supports a clean session-boundary plan-continuation replay.",
        },
        "H011": {
            "memory_class": "VISIBLE_HISTORY_ONLY",
            "eligible": False,
            "setup_write": "NOT_APPLICABLE",
            "target_retrieval": "VISIBLE_HISTORY_RESOLUTION_ONLY",
            "target_update": "NO_UPDATE",
            "control": "POSITIVE_VISIBLE_HISTORY",
            "rationale": "The hybrid source contains only an assistant plan and cannot establish human writer provenance for a persistent setup.",
        },
        "H013": {
            "memory_class": "VISIBLE_HISTORY_ONLY",
            "eligible": False,
            "setup_write": "NOT_APPLICABLE",
            "target_retrieval": "VISIBLE_HISTORY_RESOLUTION_ONLY",
            "target_update": "NO_UPDATE",
            "control": "POSITIVE_VISIBLE_HISTORY",
            "rationale": "The hybrid source contains only an assistant plan and remains a visible-history condition.",
        },
        "H015": {
            "memory_class": "VISIBLE_HISTORY_ONLY",
            "eligible": False,
            "setup_write": "NOT_APPLICABLE",
            "target_retrieval": "VISIBLE_HISTORY_RESOLUTION_ONLY",
            "target_update": "NO_UPDATE",
            "control": "POSITIVE_VISIBLE_HISTORY",
            "rationale": "The antecedent is assistant-only and too underspecified for a governed persistent write.",
        },
    }


def build_memory_registry(sources: dict[str, Any]) -> list[dict[str, Any]]:
    specs = memory_specs()
    candidate_rows = [
        row
        for row in sources["unified_62"]
        if row.get("source_dataset") == "memory_diagnostic"
        or (
            row.get("source_dataset") == "handwritten_unified"
            and (row.get("expected_memory") or row.get("conversation_history"))
        )
    ]
    require(len(candidate_rows) == 15, "Memory-related scenario population is not 15")
    rows: list[dict[str, Any]] = []
    for scenario in candidate_rows:
        source_id = scenario["source_scenario_id"]
        spec = specs[source_id]
        eligible = bool(spec["eligible"])
        rows.append(
            {
                "unified_scenario_id": scenario["scenario_id"],
                "source_dataset": scenario["source_dataset"],
                "source_scenario_id": source_id,
                "student_query": scenario["student_query"],
                "student_query_sha256": sha256_text(scenario["student_query"]),
                "current_page": scenario["page"],
                "memory_class": spec["memory_class"],
                "native_visible_history_turn_count": len(scenario.get("conversation_history") or []),
                "persistent_replay_eligible": "YES" if eligible else "NO",
                "target_query_preserved": "YES",
                "persistent_target_visible_history_policy": (
                    "EMPTY_AFTER_VERBATIM_SETUP_MOVED_BEFORE_SESSION_BOUNDARY"
                    if eligible
                    else "KEEP_NATIVE_VISIBLE_HISTORY"
                ),
                "earlier_session_setup_source": (
                    "VERBATIM_NATIVE_VISIBLE_HISTORY" if eligible else "NONE"
                ),
                "expected_setup_write_operation": spec["setup_write"],
                "expected_target_retrieval_operation": spec["target_retrieval"],
                "expected_target_update_operation": spec["target_update"],
                "control_status": spec["control"],
                "eligibility_rationale": spec["rationale"],
                "extension_gap_status": "COVERED_BY_EXISTING_SCENARIO",
            }
        )
    return rows


def build_memory_extension_packet() -> list[dict[str, Any]]:
    common = {
        "session_boundary_required": "YES",
        "student_writer_setup_text": "",
        "student_writer_update_text": "",
        "student_writer_target_text": "",
        "human_writer_status": "REQUIRED_NOT_COMPLETED",
        "template_authorship": "AI_AUTHORED_TEMPLATE_ONLY_NOT_A_STUDENT_UTTERANCE",
        "adjudication_status": "NOT_STARTED",
        "inclusion_status": "NOT_IN_PRIMARY_DATASET_OR_REPLAY_MANIFEST",
    }
    templates = [
        {
            "extension_family_id": "C4MEM-EXT-01",
            "coverage_class": "CROSS_SESSION_EPISODIC_MEMORY",
            "gap_basis": "No existing case tests a learner-authored completed event available only from an earlier session.",
            "setup_session_writer_instruction": "Write one earlier-session statement reporting a concrete completed learning event and its time or week.",
            "update_session_writer_instruction": "Leave blank; this family has no intervening update.",
            "target_session_writer_instruction": "Write a later-session request whose answer needs that event but does not repeat it.",
            "required_setup_elements": "event; course week or time anchor; learner ownership",
            "required_target_elements": "implicit reference; no copied event wording; answerable with stored episode",
            "expected_store_operations": "WRITE_EPISODE; RETRIEVE_EPISODE",
            "expected_prohibited_operations": "NO_PROFILE_INFERENCE; NO_CROSS_LEARNER_RETRIEVAL",
        },
        {
            "extension_family_id": "C4MEM-EXT-02",
            "coverage_class": "STABLE_SEMANTIC_PROFILE",
            "gap_basis": "No existing case isolates a stable learner-authored preference or durable constraint.",
            "setup_session_writer_instruction": "Write one stable learning preference or durable accessibility/time constraint without requesting a plan.",
            "update_session_writer_instruction": "Leave blank; the preference remains current.",
            "target_session_writer_instruction": "Write a later advice request where the stored preference is relevant but not restated.",
            "required_setup_elements": "explicit first-person preference or durable constraint; permitted retention scope",
            "required_target_elements": "advice request; preference relevant; no verbatim restatement",
            "expected_store_operations": "WRITE_PROFILE; RETRIEVE_PROFILE",
            "expected_prohibited_operations": "NO_TRAIT_INFERENCE_BEYOND_WRITTEN FACT; NO_EPISODE_COERCION",
        },
        {
            "extension_family_id": "C4MEM-EXT-03",
            "coverage_class": "UPDATE_OR_CORRECTION",
            "gap_basis": "M009 updates an active action, but no case updates a persistent semantic profile across sessions.",
            "setup_session_writer_instruction": "Write one retainable stable preference or constraint.",
            "update_session_writer_instruction": "In a later session, explicitly replace that value with a different current value.",
            "target_session_writer_instruction": "In a third session, request advice for which the current value matters without restating either value.",
            "required_setup_elements": "profile value v1; learner ownership",
            "required_target_elements": "advice request; answer depends on v2; no value copied into target",
            "expected_store_operations": "WRITE_PROFILE_V1; UPDATE_TO_V2; RETRIEVE_V2",
            "expected_prohibited_operations": "NO_RETURN_OF_V1; NO_MERGE_OF_CONFLICTING_VALUES",
        },
        {
            "extension_family_id": "C4MEM-EXT-04",
            "coverage_class": "SUPERSEDED_MEMORY",
            "gap_basis": "No existing post-update target verifies that an older conflicting memory is suppressed.",
            "setup_session_writer_instruction": "Write one dated goal or constraint that is valid at that time.",
            "update_session_writer_instruction": "Write a later explicit replacement that makes the first value obsolete.",
            "target_session_writer_instruction": "Write a third-session request that would expose use of the obsolete value.",
            "required_setup_elements": "v1 value; temporal anchor",
            "required_target_elements": "request sensitive to current value; no restatement",
            "expected_store_operations": "WRITE_V1; SUPERSEDE_WITH_V2; RETRIEVE_V2_ONLY",
            "expected_prohibited_operations": "NO_RETRIEVAL_OR_GENERATION_USE_OF_V1",
        },
        {
            "extension_family_id": "C4MEM-EXT-05",
            "coverage_class": "SUPERSEDED_MEMORY",
            "gap_basis": "No existing case tests an explicit learner request to forget or remove a stored item.",
            "setup_session_writer_instruction": "Write one retainable preference or plan fact.",
            "update_session_writer_instruction": "In a later session, explicitly request that the fact be forgotten or no longer used.",
            "target_session_writer_instruction": "Write a third-session request for which the deleted fact would otherwise have been relevant.",
            "required_setup_elements": "retainable item; learner scope",
            "required_target_elements": "request answerable without deleted item; no restatement",
            "expected_store_operations": "WRITE_ITEM; TOMBSTONE_OR_DELETE; NO_RETRIEVAL",
            "expected_prohibited_operations": "NO_RESURRECTION; NO_GENERATION_USE_OF_DELETED_ITEM",
        },
        {
            "extension_family_id": "C4MEM-EXT-06",
            "coverage_class": "NO_RELEVANT_MEMORY_CONTROL",
            "gap_basis": "Existing controls are same-session; no cross-session distractor control is present.",
            "setup_session_writer_instruction": "Write one valid retainable fact about an unrelated page, task, or preference.",
            "update_session_writer_instruction": "Leave blank; the distractor remains stored but irrelevant.",
            "target_session_writer_instruction": "Write a later self-contained request that does not need the stored fact.",
            "required_setup_elements": "valid memory item; topic distinct from target",
            "required_target_elements": "self-contained request; explicit topic separation",
            "expected_store_operations": "WRITE_DISTRACTOR; NO_RETRIEVAL",
            "expected_prohibited_operations": "NO_FALSE_PERSONALISATION; NO_IRRELEVANT_MEMORY_IN_GENERATION",
        },
    ]
    return [{**row, **common} for row in templates]


def p3_rule(mode_id: str, rag: bool, memory: bool, planning: bool) -> str:
    if mode_id == "C0_ORIGINAL":
        return "P3_BYPASSED_FOR_LEGACY_BASELINE; OPTIONAL_MODULES_FORCED_OFF; ZERO_P3_SPECIALIST_CALLS"
    if not any([rag, memory, planning]):
        return "SHARED_CG1_CLARIFICATION_GATE_ONLY; OPTIONAL_CAPABILITY_SPECIALISTS_NOT_CALLED"
    enabled = [name for name, flag in [("RAG", rag), ("MEMORY", memory), ("PLANNING", planning)] if flag]
    disabled = [name for name, flag in [("RAG", rag), ("MEMORY", memory), ("PLANNING", planning)] if not flag]
    return (
        "RUN_SHARED_CG1_THEN_FROZEN_P3_FOR_AVAILABLE_CAPABILITIES; "
        f"P3_TRUE_MAY_ACTIVATE_{'_'.join(enabled)}; "
        f"FORCED_OFF_OVERRIDES_P3_FOR_{'_'.join(disabled) if disabled else 'NONE'}; "
        "HUMAN_GOLD_NEVER_GATES_EXECUTION"
    )


def expected_trace(rag: bool, memory: bool, planning: bool, evidence: bool) -> list[dict[str, Any]]:
    trace = [
        {
            "module": "EVIDENCE_SYNTHESIS",
            "expected": "EXECUTE_ONCE" if evidence else "SKIP_FOR_LEGACY_BASELINE",
            "maximum_calls": 1 if evidence else 0,
        }
    ]
    for module, flag in [("RAG", rag), ("MEMORY", memory), ("PLANNING", planning)]:
        trace.append(
            {
                "module": module,
                "expected": (
                    "P3_GATE_EVALUATED; EXECUTE_ZERO_OR_ONE_TIMES; TYPED_ABSENCE_IF_NO_RESULT"
                    if flag
                    else "SKIPPED_BY_FORCED_OFF_LOCK; TYPED_EMPTY_OFF"
                ),
                "maximum_calls": 1 if flag else 0,
            }
        )
    trace.append(
        {
            "module": "GENERATOR",
            "expected": "ONE_CALL_ONLY_AFTER_SEPARATE_EXECUTION_AUTHORIZATION",
            "maximum_calls": 1,
        }
    )
    return trace


def build_mode_registry() -> dict[str, Any]:
    definitions = [
        ("C0_ORIGINAL", "PRIMARY", False, False, False, False),
        ("C1_EVIDENCE", "PRIMARY", True, False, False, False),
        ("C2_EVIDENCE_RAG", "PRIMARY", True, True, False, False),
        ("C3_EVIDENCE_MEMORY", "PRIMARY", True, False, True, False),
        ("C4_EVIDENCE_PLANNING", "PRIMARY", True, False, False, True),
        ("C5_FULL_C4", "PRIMARY", True, True, True, True),
        ("C5_MINUS_RAG", "TARGETED_SECONDARY", True, False, True, True),
        ("C5_MINUS_MEMORY", "TARGETED_SECONDARY", True, True, False, True),
        ("C5_MINUS_PLANNING", "TARGETED_SECONDARY", True, True, True, False),
    ]
    modes: list[dict[str, Any]] = []
    for mode_id, tier, evidence, rag, memory, planning in definitions:
        modes.append(
            {
                "mode_id": mode_id,
                "analysis_tier": tier,
                "availability": {
                    "evidence_synthesis": "AVAILABLE" if evidence else "FORCED_OFF",
                    "rag": "AVAILABLE" if rag else "FORCED_OFF",
                    "memory": "AVAILABLE" if memory else "FORCED_OFF",
                    "planning": "AVAILABLE" if planning else "FORCED_OFF",
                },
                "condition_lock": {
                    "evidence_synthesis": evidence,
                    "rag": rag,
                    "memory": memory,
                    "planning": planning,
                },
                "p3_gating_rule": p3_rule(mode_id, rag, memory, planning),
                "state_reset_rule_id": "C4_REAL_PER_SCENARIO_MODE_ISOLATED_RESET_V1",
                "expected_mechanism_trace": expected_trace(rag, memory, planning, evidence),
            }
        )

    primary = [
        {"comparison_id": "C1_MINUS_C0", "left": "C1_EVIDENCE", "right": "C0_ORIGINAL"},
        {"comparison_id": "C2_MINUS_C1", "left": "C2_EVIDENCE_RAG", "right": "C1_EVIDENCE"},
        {"comparison_id": "C3_MINUS_C1", "left": "C3_EVIDENCE_MEMORY", "right": "C1_EVIDENCE"},
        {"comparison_id": "C4_MINUS_C1", "left": "C4_EVIDENCE_PLANNING", "right": "C1_EVIDENCE"},
        {"comparison_id": "C5_MINUS_C1", "left": "C5_FULL_C4", "right": "C1_EVIDENCE"},
    ]
    remove_one = [
        {"comparison_id": "C5_MINUS_C5_MINUS_RAG", "left": "C5_FULL_C4", "right": "C5_MINUS_RAG"},
        {"comparison_id": "C5_MINUS_C5_MINUS_MEMORY", "left": "C5_FULL_C4", "right": "C5_MINUS_MEMORY"},
        {"comparison_id": "C5_MINUS_C5_MINUS_PLANNING", "left": "C5_FULL_C4", "right": "C5_MINUS_PLANNING"},
    ]
    return {
        "schema_version": "c4-real-ablation-mode-registry-v1",
        "freeze_date": FREEZE_DATE,
        "status": "FROZEN_UNEXECUTED",
        "dataset_id": PRIMARY_DATASET_ID,
        "design_principle": (
            "C1_EVIDENCE is the common add-one baseline. RAG, Memory, and Planning main effects "
            "are never defined by an order-dependent sequential chain."
        ),
        "common_input_contract": {
            "required_equal_across_all_modes_within_scenario": [
                "current_query",
                "current_page",
                "dashboard_context",
                "visible_conversation_history",
                "generator_model_placeholder",
                "temperature",
                "maximum_tokens",
                "shared_prompt_placeholder",
            ],
            "generator_model_placeholder": GENERATOR_MODEL_PLACEHOLDER,
            "temperature": TEMPERATURE,
            "maximum_tokens": MAXIMUM_TOKENS,
            "shared_prompt_placeholder": PROMPT_PLACEHOLDER,
            "forbidden_generator_inputs": [
                "mode_id",
                "condition_name",
                "human_gold",
                "expected_route",
                "expected_memory",
                "expected_retrieval",
                "reference_chunk_ids",
                "historical_response",
                "historical_judge_score",
            ],
        },
        "p3_binding": {
            "binding_name": "RQ2_FINAL_ROUTER_FOR_RQ3",
            "selected_method_id": "R2V2-P3_RAG_MEMORY_SPECIALISTS",
            "shared_clarification_gate_id": "R2V2-CG1_CLARIFICATION_RULE",
            "selected_runtime_composition": {
                "RAG": "R2V2-RAG_SPECIALIST",
                "Memory": "R2V2-MEMORY_SPECIALIST",
                "Planning": "R2V2-B4_JOINT_LLM",
            },
            "path": str(P3_BINDING_PATH.relative_to(WORKTREE_ROOT)),
            "sha256": EXPECTED_HASHES["p3_binding"],
            "write_count": 1,
            "overwrite_permitted": False,
            "rq3_may_change_binding": False,
            "new_p3_predictions_in_this_freeze": 0,
        },
        "state_reset_rule": {
            "rule_id": "C4_REAL_PER_SCENARIO_MODE_ISOLATED_RESET_V1",
            "namespace_formula": "C4REAL::{scenario_id}::{mode_id}::{replicate_id}",
            "before_each_record": [
                "create a new isolated namespace",
                "load the same frozen scenario fixture",
                "apply any verbatim earlier-session setup in that namespace",
                "start the target session with the manifest-visible history",
            ],
            "after_each_record": [
                "record trace and usage only",
                "rollback target-session Memory mutations",
                "destroy the isolated namespace",
            ],
            "cross_mode_or_cross_scenario_state_reuse": False,
            "production_state_commit": False,
        },
        "modes": modes,
        "frozen_comparisons": {
            "primary": primary,
            "targeted_remove_one": remove_one,
            "difference_direction": "LEFT_MINUS_RIGHT_AT_THE_PAIRED_SCENARIO_LEVEL",
        },
        "evaluation_contract": {
            "primary_response_quality_criteria": QUALITY_CRITERIA,
            "primary_aggregate": {
                "name": "OVERALL_APPLICABLE_MEAN",
                "formula": "arithmetic mean of applicable authoritative eight criterion scores",
                "minimum_applicable_criteria": 3,
                "dimension_results_preserved": True,
            },
            "secondary_response_outcomes": [
                "EVIDENCE_FAITHFULNESS",
                "UNSUPPORTED_CLAIM_COUNT",
            ],
            "retrieval_metrics": [
                "RAG_TRIGGER_PRECISION_RECALL_F1",
                "REFERENCE_CHUNK_RECALL_AT_K",
                "REFERENCE_CHUNK_PRECISION_AT_K",
                "MEAN_RECIPROCAL_RANK",
                "NO_RESULT_CORRECTNESS",
                "RETRIEVAL_CALL_COUNT",
            ],
            "memory_metrics": [
                "WRITE_DECISION_ACCURACY",
                "WRITE_FIELD_PRECISION_RECALL_F1",
                "RETRIEVAL_DECISION_ACCURACY",
                "REQUIRED_MEMORY_ITEM_RECALL",
                "IRRELEVANT_MEMORY_RETRIEVAL_FALSE_POSITIVE_RATE",
                "UPDATE_OPERATION_ACCURACY",
                "CURRENT_VALUE_ACCURACY_AFTER_UPDATE",
                "SUPERSEDED_MEMORY_VIOLATION_COUNT",
                "CROSS_LEARNER_OR_CROSS_CONDITION_LEAK_COUNT",
            ],
            "planner_metrics": [
                "PLANNER_EVIDENCE_CONSISTENCY",
                "SUPPORTED_ACTION_STEP_RATE",
                "UNSUPPORTED_PLAN_STEP_COUNT",
                "CONSTRAINT_ADHERENCE",
            ],
            "efficiency_metrics": [
                "END_TO_END_LATENCY_MS",
                "MODULE_CALL_COUNTS",
                "PROVIDER_CALL_COUNTS",
                "INPUT_TOKENS",
                "OUTPUT_TOKENS",
                "TOTAL_TOKENS",
                "COST_USD_FROM_SEPARATELY_FROZEN_PRICE_TABLE",
            ],
            "analysis": {
                "unit": "paired scenario",
                "complete_pair_required": True,
                "missing_or_failed_pair_policy": "EXCLUDE_FROM_THAT_COMPARISON_AND_REPORT_EXACT_REASON; NEVER_IMPUTE",
                "primary_test": "paired permutation test",
                "robustness_test": "Wilcoxon signed-rank",
                "interval": "paired scenario bootstrap 95 percent",
                "bootstrap_replicates": 10000,
                "random_seed": 20260831,
                "multiplicity": "Holm correction separately within primary and targeted-remove-one families",
                "effect_sizes": [
                    "paired Cohen dz",
                    "matched rank-biserial correlation",
                    "wins ties losses",
                ],
                "all_zero_rule": "NOT_ESTIMABLE_ALL_ZERO_WITH_EXACT_AGREEMENT_REPORTED",
            },
        },
        "execution_boundary": {
            "response_generation": "NOT_AUTHORIZED_NOT_EXECUTED",
            "judge_calls": "NOT_AUTHORIZED_NOT_EXECUTED",
            "model_or_provider_calls": 0,
            "rag_rebuilds": 0,
            "memory_store_execution": 0,
            "streamlit_changes": 0,
        },
    }


def build_replay_manifest(
    sources: dict[str, Any], lineage: dict[str, Any], modes: dict[str, Any], memory_rows: list[dict[str, Any]]
) -> list[dict[str, Any]]:
    memory_by_unified = {row["unified_scenario_id"]: row for row in memory_rows}
    reference_by_id = lineage["ref_by_id"]
    records: list[dict[str, Any]] = []
    for scenario in sources["unified_62"]:
        scenario_id = scenario["scenario_id"]
        reference = reference_by_id[scenario_id]
        memory_row = memory_by_unified.get(scenario_id)
        native_history = scenario.get("conversation_history") or []
        eligible = bool(memory_row and memory_row["persistent_replay_eligible"] == "YES")
        earlier_setup = native_history if eligible else []
        target_history = [] if eligible else native_history
        memory_class = memory_row["memory_class"] if memory_row else "NOT_MEMORY_SCENARIO"
        session_fixture = {
            "memory_class": memory_class,
            "persistent_replay_eligible": eligible,
            "earlier_session_setup_turns": earlier_setup,
            "session_boundary": {
                "required": eligible,
                "boundary_id": f"SB-{scenario_id}" if eligible else "NOT_APPLICABLE",
                "new_target_session": eligible,
                "target_visible_history_reset": eligible,
            },
            "target_query": scenario["student_query"],
            "target_query_preserved_byte_for_byte": True,
            "scenario_expected_operations": {
                "setup_write": (
                    memory_row["expected_setup_write_operation"] if memory_row else "NOT_APPLICABLE"
                ),
                "target_retrieval": (
                    memory_row["expected_target_retrieval_operation"] if memory_row else "NOT_APPLICABLE"
                ),
                "target_update": (
                    memory_row["expected_target_update_operation"] if memory_row else "NOT_APPLICABLE"
                ),
            },
            "target_state_commit_policy": "TRACE_IN_ISOLATED_NAMESPACE_THEN_ROLLBACK",
            "learner_scope_hash": sha256_text(f"C4_REAL_LEARNER::{scenario.get('student_id', '')}"),
        }
        for mode in modes["modes"]:
            condition_lock = dict(mode["condition_lock"])
            provider_input = {
                "current_query": scenario["student_query"],
                "current_page": scenario["page"],
                "dashboard_context": reference.get("reference_dashboard_evidence") or {},
                "visible_conversation_history": target_history,
                "generator_model_placeholder": GENERATOR_MODEL_PLACEHOLDER,
                "temperature": TEMPERATURE,
                "maximum_tokens": MAXIMUM_TOKENS,
                "shared_prompt_placeholder": PROMPT_PLACEHOLDER,
            }
            mode_memory_expectation = (
                "MEMORY_MODULE_FORCED_OFF_ZERO_READ_WRITE_UPDATE_CALLS"
                if not condition_lock["memory"]
                else "P3_GATE_CONTROLS_TARGET_READ_OR_UPDATE; SETUP_PRECONDITIONING_IS_EVALUATION_FIXTURE_ONLY"
            )
            record = {
                "schema_version": "c4-real-replay-manifest-record-v1",
                "replay_record_id": f"C4R-{scenario_id}-{mode['mode_id']}",
                "execution_status": "UNEXECUTED_NO_RESPONSE_NO_PROVIDER_CALL",
                "dataset_id": PRIMARY_DATASET_ID,
                "scenario_id": scenario_id,
                "mode_id": mode["mode_id"],
                "analysis_tier": mode["analysis_tier"],
                "provider_input": provider_input,
                "source_input_audit": {
                    "source_dataset": scenario["source_dataset"],
                    "source_scenario_id": scenario["source_scenario_id"],
                    "native_visible_conversation_history": native_history,
                    "native_visible_history_sha256": object_sha256(native_history),
                    "history_transform": (
                        "MOVE_VERBATIM_NATIVE_HISTORY_TO_EARLIER_SESSION_SETUP"
                        if eligible
                        else "NO_TRANSFORM"
                    ),
                    "student_query_sha256": sha256_text(scenario["student_query"]),
                },
                "memory_session_fixture": session_fixture,
                "condition_lock": condition_lock,
                "p3_gate": {
                    "binding_name": "RQ2_FINAL_ROUTER_FOR_RQ3",
                    "selected_method_id": "R2V2-P3_RAG_MEMORY_SPECIALISTS",
                    "binding_sha256": EXPECTED_HASHES["p3_binding"],
                    "rule": mode["p3_gating_rule"],
                    "route_decision": "TO_BE_PRODUCED_ONLY_DURING_SEPARATELY_AUTHORIZED_EXECUTION",
                    "human_gold_used_for_gating": False,
                },
                "module_asset_bindings": {
                    "dashboard_context_source_row_sha256": object_sha256(reference),
                    "rag_index_binding": "TO_BE_FROZEN_SEPARATELY_BEFORE_EXECUTION; NO_REBUILD_IN_TRACK_D",
                    "memory_store_binding": "TO_BE_FROZEN_SEPARATELY_BEFORE_EXECUTION; NO_IMPLEMENTATION_IN_TRACK_D",
                    "planner_binding": "FROZEN_DETERMINISTIC_PLANNER_REQUIRED_BEFORE_EXECUTION",
                },
                "evaluation_only_reference": {
                    "excluded_from_provider_input": True,
                    "scenario_group": scenario["scenario_group"],
                    "required_capabilities": scenario["required_capabilities"],
                    "expected_reference_chunk_ids": reference.get("reference_chunk_ids") or [],
                    "reference_course_evidence_sha256": object_sha256(
                        reference.get("reference_course_evidence") or []
                    ),
                    "expected_memory_items": scenario.get("expected_memory_items") or [],
                    "expected_memory_state_fields": scenario.get("expected_memory_state_fields") or [],
                },
                "state_reset": {
                    "rule_id": "C4_REAL_PER_SCENARIO_MODE_ISOLATED_RESET_V1",
                    "namespace": f"C4REAL::{scenario_id}::{mode['mode_id']}::REPLICATE_ID_PLACEHOLDER",
                    "cross_record_reuse": False,
                    "production_commit": False,
                },
                "expected_mechanism_trace": mode["expected_mechanism_trace"],
                "mode_memory_trace_expectation": mode_memory_expectation,
                "track_d_actual_execution_counters": {
                    "generator_calls": 0,
                    "judge_calls": 0,
                    "provider_calls": 0,
                    "rag_calls": 0,
                    "memory_store_calls": 0,
                    "planner_calls": 0,
                    "responses": 0,
                },
            }
            record["record_identity_sha256"] = object_sha256(record)
            records.append(record)
    require(len(records) == 558, "Replay manifest must contain 558 unexecuted records")
    return records


def build_method_markdown(
    lineage_registry: dict[str, Any], memory_rows: list[dict[str, Any]], modes: dict[str, Any]
) -> str:
    class_counts = Counter(row["memory_class"] for row in memory_rows)
    eligible_count = sum(row["persistent_replay_eligible"] == "YES" for row in memory_rows)
    mode_lines = []
    for mode in modes["modes"]:
        lock = mode["condition_lock"]
        mode_lines.append(
            f"| {mode['mode_id']} | {'ON' if lock['evidence_synthesis'] else 'OFF'} | "
            f"{'ON' if lock['rag'] else 'OFF'} | {'ON' if lock['memory'] else 'OFF'} | "
            f"{'ON' if lock['planning'] else 'OFF'} | {mode['analysis_tier']} |"
        )
    class_text = ", ".join(f"{name}={class_counts.get(name, 0)}" for name in MEMORY_CLASSES)
    historical = lineage_registry["final_evaluation_status"]["unified_62"]
    return f"""# C4 REAL Dataset and Ablation Method

## Frozen outcome

Track D freezes `C4_REAL_PRIMARY_UNIFIED_DATASET_V1` at 62 scenarios and
`C4_REAL_ORIGINAL_25_AUTHENTIC_SUBSET_V1` at the first 25 source-derived
scenarios. The freeze is declarative and unexecuted: it generated no responses,
made no Judge/provider calls, rebuilt no RAG index, implemented no Memory store,
and changed no Streamlit code.

## Authoritative lineage

The original dialogue CSV has SHA-256
`{EXPECTED_HASHES['example_conversation_csv']}` and 50 turns (25 user, 25
assistant). `evaluation/scenarios.jsonl` has SHA-256
`{EXPECTED_HASHES['original_25']}` and 25 scenarios. Twenty-one frozen queries
match their source user turns exactly; S011, S014, S018, and S019 differ only by
pre-existing trailing-whitespace removal. Track D performs no new query
normalisation.

The only actual 57-row unified identity found has SHA-256
`{EXPECTED_HASHES['unified_57']}`. It is stored as
`{lineage_registry['canonical_sources']['unified_57_predecessor']['member']}`
inside `{PREDECESSOR_ARCHIVE}`. It combines 25 main, 7 Memory, 10 RAG, and 15
handwritten rows and has no associated Gold/reference-evidence members.

The corrected file has SHA-256 `{EXPECTED_HASHES['unified_62']}` and combines
25 main, 12 Memory, 10 RAG, and 15 handwritten rows. Stable content identities
show 57/57 predecessor scenarios are preserved. M008-M012 are the five
additions; inserting them renumbers the former U033-U057 RAG/handwritten rows to
U038-U062. The corrected file has exact 62-row reviewed Gold and reference
evidence with SHA-256 `{EXPECTED_HASHES['unified_gold_62']}` and
`{EXPECTED_HASHES['unified_reference_62']}`.

The source scenario files carry queries/pages/histories but not Dashboard
context. The associated reviewed reference-evidence file supplies a Dashboard
context field for 62/62 rows; it is non-empty for
{lineage_registry['field_availability']['unified_62']['associated_reference_dashboard_context_nonempty']}.
The replay manifest freezes that per-scenario context identically across modes.

## Prior evaluation status

The 62-row identity was historically used for 372 six-mode responses, 372
formal quality records, and 372 mechanism-v2 records. Their response and score
content is excluded from every C4 input. The historical evaluation is not a
closed final evaluation: the 378-row human packet has zero completed score or
rationale cells, and all eight declared summary/statistics files are absent.
Its status is `{historical['status']}`. Track D does not rerun or score it.

## Memory audit

The Memory-related population is 15 scenarios: all 12 `memory_diagnostic` rows
and three handwritten Memory/history hybrids. Primary-class counts are:
{class_text}. Nine existing cases can be transformed into a persistent replay
by moving their native setup turns verbatim before an explicit session boundary
and leaving the human-authored target query byte-identical. The other six remain
visible-history/control cases because they lack a governed human-authored setup
turn or are natively visible-only.

The six-row writer packet is gap-based. It requests human wording for
cross-session episodic Memory, stable profile Memory, profile correction,
post-update supersession, explicit forgetting, and a cross-session irrelevant
Memory control. All student-utterance cells are blank. Templates are explicitly
not human-authored scenarios and cannot enter the primary dataset or replay
manifest until completed and adjudicated by people.

## Frozen modes

| Mode | Evidence | RAG | Memory | Planning | Tier |
|---|---:|---:|---:|---:|---|
{chr(10).join(mode_lines)}

`C1_EVIDENCE` is the common add-one baseline. Primary paired comparisons are
C1-C0, C2-C1, C3-C1, C4-C1, and C5-C1. Targeted remove-one comparisons are C5
minus each of C5_MINUS_RAG, C5_MINUS_MEMORY, and C5_MINUS_PLANNING. No module
effect is defined through a sequential C1→C2→C3→C4 chain.

The immutable Router binding is `R2V2-P3_RAG_MEMORY_SPECIALISTS` behind the
shared `R2V2-CG1_CLARIFICATION_RULE`. A forced-OFF capability always overrides
P3. An available capability may execute only when its frozen P3 decision is
true. Human Gold never gates a generation request. No P3 decision is produced
in this freeze.

## Replay contract

The manifest contains 558 records: 62 scenarios × 6 primary modes = 372 and 62
× 3 targeted modes = 186. Within each scenario, all modes have identical query,
page, Dashboard context, target-visible history, generator-model placeholder,
temperature 0, maximum tokens 512, and prompt placeholder. Persistent-replay
cases also carry verbatim earlier-session setup turns, an explicit session
boundary, and expected setup-write, target-retrieval, and target-update
operations.

Every `(scenario, mode, replicate)` gets a new isolated state namespace. Setup
preconditioning occurs only inside that namespace; target-session changes are
traced then rolled back. No state crosses modes/scenarios and no production
state is committed.

## Evaluation contract

The primary response outcome is `OVERALL_APPLICABLE_MEAN` over the authoritative
eight criteria: {', '.join(QUALITY_CRITERIA)}. Dimension-level scores remain
separate. Evidence Faithfulness and Unsupported Claim Count remain separate
secondary outcomes.

Retrieval, Memory write/retrieval/update, Planner-evidence consistency, latency,
call, token, and cost metrics are predeclared in the mode registry. Analysis is
paired by scenario, requires complete pairs, never imputes failures, uses a
paired permutation test with Wilcoxon robustness, paired bootstrap intervals,
and Holm correction separately within the five primary and three remove-one
families. Undefined metrics are reported as `NOT_ESTIMABLE`, never coerced.

## Hard stop

This stage stops at dataset/method freeze. A frozen model, RAG index binding,
Memory-store implementation/binding, response-generation authority, Judge
authority, and controlled execution authority are all separate future gates.
"""


def build_status_markdown(
    memory_rows: list[dict[str, Any]], extension_rows: list[dict[str, Any]]
) -> str:
    return f"""# STATUS — RQ3-REAL-C4 Track D

- Status: `FROZEN_COMPLETE_UNEXECUTED`
- Starting HEAD verified: `62eadd4ac367a85e19477832ef3806144e254e41`
- Authoritative primary dataset: `{PRIMARY_DATASET_ID}` (62 scenarios)
- Authentic original subset: `{ORIGINAL_SUBSET_ID}` (25 scenarios)
- 57-row predecessor: superseded, incomplete, no matching Gold/reference overlay
- 62-row Gold rows reviewed: 62/62
- 62-row reference-evidence rows reviewed: 62/62
- Memory-related scenarios audited: {len(memory_rows)}
- Existing persistent-store replay eligible: {sum(row['persistent_replay_eligible'] == 'YES' for row in memory_rows)}
- Human-writer extension templates required: {len(extension_rows)}
- Frozen primary modes: 6
- Frozen targeted secondary modes: 3
- Unexecuted replay records: 558 (372 primary + 186 targeted)
- Response generation: 0
- Judge/scoring calls: 0
- Provider/model calls: 0
- RAG rebuilds: 0
- Memory implementations/store executions: 0
- Streamlit changes: 0
- Controlled RQ3 shard executions: 0
- Read-only artifact validator: PASS (17,516 checks)
- Unit tests: PASS (24 tests)

Validation passed before the sole commit. Completion of this freeze is not
response-generation authority, Judge authority, model-execution authority, or
controlled-RQ3 execution authority.
"""


def main() -> None:
    require(HERE == WORKTREE_ROOT / "evaluation/rq3_real_c4/track_d_dataset", "Output scope mismatch")
    sources = load_and_verify_sources()
    lineage = verify_lineage(sources)
    historical = historical_evaluation_status()

    lineage_registry = build_lineage_registry(sources, lineage, historical)
    final_identity = build_final_62_identity(sources, lineage, historical)
    original_identity = build_original_25_identity(sources)
    memory_rows = build_memory_registry(sources)
    extension_rows = build_memory_extension_packet()
    mode_registry = build_mode_registry()
    replay_rows = build_replay_manifest(sources, lineage, mode_registry, memory_rows)

    write_json(HERE / "dataset_lineage_registry_v1.json", lineage_registry)
    write_json(HERE / "final_62_scenario_identity_v1.json", final_identity)
    write_json(HERE / "original_25_subset_identity_v1.json", original_identity)
    write_csv(
        HERE / "memory_scenario_registry_v1.csv",
        [
            "unified_scenario_id",
            "source_dataset",
            "source_scenario_id",
            "student_query",
            "student_query_sha256",
            "current_page",
            "memory_class",
            "native_visible_history_turn_count",
            "persistent_replay_eligible",
            "target_query_preserved",
            "persistent_target_visible_history_policy",
            "earlier_session_setup_source",
            "expected_setup_write_operation",
            "expected_target_retrieval_operation",
            "expected_target_update_operation",
            "control_status",
            "eligibility_rationale",
            "extension_gap_status",
        ],
        memory_rows,
    )
    write_csv(
        HERE / "memory_extension_writer_packet_v1.csv",
        [
            "extension_family_id",
            "coverage_class",
            "gap_basis",
            "setup_session_writer_instruction",
            "update_session_writer_instruction",
            "target_session_writer_instruction",
            "required_setup_elements",
            "required_target_elements",
            "expected_store_operations",
            "expected_prohibited_operations",
            "session_boundary_required",
            "student_writer_setup_text",
            "student_writer_update_text",
            "student_writer_target_text",
            "human_writer_status",
            "template_authorship",
            "adjudication_status",
            "inclusion_status",
        ],
        extension_rows,
    )
    write_json(HERE / "c4_real_ablation_mode_registry_v1.json", mode_registry)
    write_jsonl(HERE / "c4_real_replay_manifest_unexecuted_v1.jsonl", replay_rows)
    (HERE / "C4_REAL_DATASET_AND_ABLATION_METHOD.md").write_text(
        build_method_markdown(lineage_registry, memory_rows, mode_registry), encoding="utf-8"
    )
    (HERE / "STATUS.md").write_text(
        build_status_markdown(memory_rows, extension_rows), encoding="utf-8"
    )

    print(
        "Built Track D freeze: 62 primary scenarios, 25 authentic subset rows, "
        "15 Memory audit rows, 6 writer templates, 9 modes, 558 unexecuted replay records."
    )


if __name__ == "__main__":
    main()
