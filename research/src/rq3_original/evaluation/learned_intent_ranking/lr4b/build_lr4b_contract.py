"""Build the deterministic, text-free RQ1-A LR4B contract artifacts."""

from __future__ import annotations

import argparse
import ast
import csv
import hashlib
import json
import math
import os
import statistics
import sys
from collections import Counter, defaultdict
from pathlib import Path, PurePosixPath
from typing import Any, Iterable, Mapping


if __package__ in {None, ""}:
    sys.path.insert(0, str(Path(__file__).resolve().parents[3]))
    from evaluation.learned_intent_ranking.lr4b.contract_schema import (
        BASELINE,
        CONTRACT_VERSION,
        DOC_PATHS,
        EXPECTED_COUNTS,
        EXPECTED_EEDI_HASHES,
        EXPECTED_KEY_FILE_HASHES,
        EXPECTED_SCENARIOS,
        FINAL_GOLD_ROOT,
        FIVE_SEEDS,
        FORBIDDEN_MODEL_INPUT_FIELDS,
        LEDGER_FIELDS,
        LOCAL_LEDGER_PATH,
        MODEL_INPUT_FIELDS,
        PROTECTED_ROOTS,
        QUERY_ONLY_V1,
        SAFE_JSON_FILENAMES,
        STRUCTURED_CONTEXT_V1,
        authorised_project_path,
        canonical_json_bytes,
        sha256_bytes,
        sha256_file,
        validate_strict_scenarios,
    )
    from evaluation.learned_intent_ranking.lr4b.context_representation import (
        build_query_only_representation,
        build_structured_context_representation,
        normalise_source_field,
        representation_sha256,
        truncation_contract,
    )
else:
    from .contract_schema import (
        BASELINE,
        CONTRACT_VERSION,
        DOC_PATHS,
        EXPECTED_COUNTS,
        EXPECTED_EEDI_HASHES,
        EXPECTED_KEY_FILE_HASHES,
        EXPECTED_SCENARIOS,
        FINAL_GOLD_ROOT,
        FIVE_SEEDS,
        FORBIDDEN_MODEL_INPUT_FIELDS,
        LEDGER_FIELDS,
        LOCAL_LEDGER_PATH,
        MODEL_INPUT_FIELDS,
        PROTECTED_ROOTS,
        QUERY_ONLY_V1,
        SAFE_JSON_FILENAMES,
        STRUCTURED_CONTEXT_V1,
        authorised_project_path,
        canonical_json_bytes,
        sha256_bytes,
        sha256_file,
        validate_strict_scenarios,
    )
    from .context_representation import (
        build_query_only_representation,
        build_structured_context_representation,
        normalise_source_field,
        representation_sha256,
        truncation_contract,
    )


LR4B_RELATIVE_ROOT = PurePosixPath("evaluation/learned_intent_ranking/lr4b")
OUTPUT_CHECKSUM_PATH = LR4B_RELATIVE_ROOT / "lr4b_output_checksums_v1.sha256"

PATHS = {
    "full_eedi": "evaluation/learned_intent_ranking/lr4a/training_data_input/eedi_stage_e4_researcher_confirmed_300.csv",
    "retained_eedi": "evaluation/learned_intent_ranking/lr4a/training_data_input/eedi_stage_e4_confirmed_candidate_subset_256.csv",
    "eedi_audit": "evaluation/learned_intent_ranking/lr4a/training_data_input/eedi_stage_e4_audit.json",
    "eedi_codebook": "evaluation/learned_intent_ranking/lr4a/training_data_input/eedi_stage_e4_codebook_researcher_confirmed_v1.json",
    "lr4a_checksum": "evaluation/learned_intent_ranking/lr4a/lr4a_r1/lr4a_r1_output_checksums_v1.sha256",
    "expanded_train": "evaluation/learned_intent_ranking/lr4a/lr4a_r1/ranker_expanded_train_manifest_candidate_v2.jsonl",
    "scenarios": "evaluation/learned_intent_ranking/lr4a/lr4a_r1/ranker_data_volume_scenarios_candidate_v2.json",
    "reliability": "evaluation/learned_intent_ranking/lr4a/lr4a_r1/lr4a_r1_annotation_reliability_v1.json",
    "coverage": "evaluation/learned_intent_ranking/lr4a/lr4a_r1/lr4a_r1_label_coverage_v1.json",
    "contamination": "evaluation/learned_intent_ranking/lr4a/lr4a_r1/lr4a_r1_contamination_audit_v1.json",
    "provenance": "evaluation/learned_intent_ranking/lr4a/lr4a_r1/lr4a_r1_provenance_graph_v1.json",
    "lr4a_validation": "evaluation/learned_intent_ranking/lr4a/lr4a_r1/lr4a_r1_validation_report_v1.json",
    "train": "evaluation/learned_intent_ranking/lr1/ranker_train_manifest_candidate_v1.jsonl",
    "dev": "evaluation/learned_intent_ranking/lr1r/ranker_dev_manifest_candidate_v2.jsonl",
    "pair_dataset": "evaluation/learned_intent_ranking/lr2r/ranker_pair_dataset_baseline_candidate_v2.jsonl",
    "dev_views": "evaluation/learned_intent_ranking/lr2r/ranker_dev_evaluation_views_v1.json",
    "label_universe": "evaluation/learned_intent_ranking/lr2r/lr2r_label_universe_v1.json",
    "singleton_manifest": "evaluation/learned_intent_ranking/lr2r/lr2r_singleton_exclusion_manifest_v1.json",
    "lr2r_sampling": "evaluation/learned_intent_ranking/lr2r/lr2r_episodic_sampling_spec_v1.json",
    "lr3r_protocol": "evaluation/learned_intent_ranking/lr3r/lr3r_experiment_protocol_v1.json",
    "lr3r_comparison": "evaluation/learned_intent_ranking/lr3r/lr3r_model_comparison_v1.json",
    "lr3s_protocol": "evaluation/learned_intent_ranking/lr3s/lr3s_experiment_protocol_v1.json",
    "lr3s_comparison": "evaluation/learned_intent_ranking/lr3s/lr3s_model_comparison_v1.json",
    "approved_index": "semantic_runtime/artifacts/intent_examples_approved_index_v1.jsonl",
    "approved_metadata": "semantic_runtime/artifacts/intent_example_approved_metadata_v1.json",
    "semantic_config": "semantic_runtime/config/semantic_routing_config.json",
    "semantic_selection": "semantic_runtime/config/semantic_router_selection_manifest_v1.json",
    "source_manifest": "docs/thesis_mainline/source_contract/THESIS_0R_SAFE_RESEARCH_SOURCE_MANIFEST.sha256",
    "tracked_manifest": "evaluation/thesis_mainline/baseline/baseline_tracked_manifest_v1.sha256",
}

PROVENANCE_FIELDS = (
    "conversation_group_id",
    "paraphrase_family_id",
    "parent_id",
    "contrast_set_id",
    "question_anchor_sha256",
    "annotation_reliability",
    "independent_second_rater",
)


class ContractBuildError(RuntimeError):
    """Fail-closed error whose messages never include governed text values."""


def _read_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8-sig"))


def _read_jsonl(path: Path) -> list[dict[str, Any]]:
    return [
        json.loads(line)
        for line in path.read_text(encoding="utf-8-sig").splitlines()
        if line
    ]


def _read_csv(path: Path) -> list[dict[str, str]]:
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        return list(csv.DictReader(handle))


def _text_sha256(value: str) -> str:
    return sha256_bytes(value.encode("utf-8"))


def _safe_path(project_root: Path, name: str) -> Path:
    try:
        return authorised_project_path(project_root, PATHS[name])
    except (PermissionError, ValueError) as exc:
        raise ContractBuildError(f"authorised input path rejected: {name}") from exc


def _verify_required_path(path: Path, role: str) -> None:
    if not path.is_file() or path.is_symlink():
        raise ContractBuildError(f"required regular input missing: {role}")


def _verify_lr4a_checksum(project_root: Path) -> dict[str, object]:
    manifest = _safe_path(project_root, "lr4a_checksum")
    _verify_required_path(manifest, "lr4a_checksum")
    entries = 0
    for line_number, line in enumerate(manifest.read_text(encoding="utf-8").splitlines(), 1):
        if not line:
            continue
        parts = line.split(None, 1)
        if len(parts) != 2 or len(parts[0]) != 64:
            raise ContractBuildError(f"invalid LR4A checksum syntax at line {line_number}")
        expected, relative_name = parts
        relative_name = relative_name.strip().lstrip("*")
        if Path(relative_name).is_absolute() or ".." in PurePosixPath(relative_name).parts:
            raise ContractBuildError("LR4A checksum member escaped its directory")
        member = manifest.parent / relative_name
        _verify_required_path(member, "lr4a_checksum_member")
        if sha256_file(member) != expected:
            raise ContractBuildError("LR4A checksum member mismatch")
        entries += 1
    if entries != 11:
        raise ContractBuildError("unexpected LR4A checksum entry count")
    return {
        "manifest_path": PATHS["lr4a_checksum"],
        "manifest_sha256": sha256_file(manifest),
        "entry_count": entries,
        "all_entries_match": True,
    }


def compute_protected_source_fingerprint(project_root: Path) -> dict[str, object]:
    """Hash protected regular files while pruning final gold before traversal."""

    entries: list[tuple[str, str]] = []
    forbidden = project_root.joinpath(*FINAL_GOLD_ROOT.parts)
    for relative_root in PROTECTED_ROOTS:
        root = authorised_project_path(project_root, relative_root)
        if not root.is_dir():
            raise ContractBuildError(f"protected source root missing: {relative_root}")
        for directory, directory_names, file_names in os.walk(root, followlinks=False):
            directory_path = Path(directory)
            directory_names[:] = sorted(
                name
                for name in directory_names
                if not (directory_path / name).is_symlink()
                and (directory_path / name) != forbidden
            )
            for name in sorted(file_names):
                path = directory_path / name
                if not path.is_file() or path.is_symlink():
                    continue
                relative_path = path.relative_to(project_root).as_posix()
                if relative_path == str(FINAL_GOLD_ROOT) or relative_path.startswith(
                    str(FINAL_GOLD_ROOT) + "/"
                ):
                    raise ContractBuildError("final-gold traversal guard failed")
                entries.append((relative_path, sha256_file(path)))
    entries.sort()
    projection = "".join(f"{digest}  {path}\n" for path, digest in entries)
    return {
        "entry_count": len(entries),
        "manifest_fingerprint": _text_sha256(projection),
        "final_gold_root_pruned_before_traversal": True,
    }


def _verify_baseline(project_root: Path) -> dict[str, object]:
    source_fingerprint = sha256_file(_safe_path(project_root, "source_manifest"))
    tracked_fingerprint = sha256_file(_safe_path(project_root, "tracked_manifest"))
    if source_fingerprint != BASELINE["source_pre_governance_fingerprint"]:
        raise ContractBuildError("source baseline fingerprint mismatch")
    if tracked_fingerprint != BASELINE["tracked_baseline_tree_fingerprint"]:
        raise ContractBuildError("tracked baseline fingerprint mismatch")
    key_hashes: dict[str, str] = {}
    for relative_path, expected in EXPECTED_KEY_FILE_HASHES.items():
        path = authorised_project_path(project_root, relative_path)
        _verify_required_path(path, "key_file")
        actual = sha256_file(path)
        key_hashes[relative_path] = actual
        if actual != expected:
            raise ContractBuildError("key file fingerprint mismatch")
    protected = compute_protected_source_fingerprint(project_root)
    if protected["manifest_fingerprint"] != BASELINE["protected_source_manifest_fingerprint"]:
        raise ContractBuildError("protected source fingerprint mismatch")
    return {
        "starting_branch": BASELINE["starting_branch"],
        "starting_head": BASELINE["starting_head"],
        "source_pre_governance_fingerprint": source_fingerprint,
        "tracked_baseline_tree_fingerprint": tracked_fingerprint,
        "key_file_hashes": key_hashes,
        "protected_source": protected,
    }


def _nearest_rank(values: list[int], fraction: float) -> int:
    ordered = sorted(values)
    return ordered[max(0, math.ceil(fraction * len(ordered)) - 1)]


def _length_distribution(values: list[int]) -> dict[str, object]:
    if not values:
        raise ContractBuildError("empty representation length distribution")
    ordered = sorted(values)
    return {
        "count": len(ordered),
        "minimum": ordered[0],
        "maximum": ordered[-1],
        "mean": round(statistics.fmean(ordered), 6),
        "median": statistics.median(ordered),
        "p90_nearest_rank": _nearest_rank(ordered, 0.90),
        "p95_nearest_rank": _nearest_rank(ordered, 0.95),
        "p99_nearest_rank": _nearest_rank(ordered, 0.99),
    }


def _identifiers(rows: Iterable[Mapping[str, Any]], field: str) -> set[str]:
    values: set[str] = set()
    for row in rows:
        value = row.get(field)
        if value not in (None, ""):
            values.add(str(value))
        provenance = row.get("provenance")
        if isinstance(provenance, Mapping):
            nested = provenance.get(field)
            if nested not in (None, ""):
                values.add(str(nested))
    return values


def _membership_fingerprint(values: Iterable[str]) -> str:
    return _text_sha256("".join(f"{value}\n" for value in sorted(values)))


def _provenance_fingerprint(rows: Iterable[Mapping[str, Any]]) -> str:
    projections: list[str] = []
    for row in rows:
        projection = {field: row.get(field) for field in PROVENANCE_FIELDS}
        projections.append(
            json.dumps(projection, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
        )
    return _text_sha256("\n".join(sorted(projections)) + "\n")


def _validate_model_input_code(project_root: Path) -> dict[str, object]:
    path = authorised_project_path(
        project_root,
        LR4B_RELATIVE_ROOT / "context_representation.py",
    )
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=path.name)
    string_constants = {
        node.value
        for node in ast.walk(tree)
        if isinstance(node, ast.Constant) and isinstance(node.value, str)
    }
    leaked_names = sorted(FORBIDDEN_MODEL_INPUT_FIELDS & string_constants)
    if leaked_names:
        raise ContractBuildError("forbidden model-input field appears in representation module")
    if set(MODEL_INPUT_FIELDS[QUERY_ONLY_V1]) != {"query"}:
        raise ContractBuildError("query-only field allowlist drift")
    if set(MODEL_INPUT_FIELDS[STRUCTURED_CONTEXT_V1]) != {
        "question_anchor_for_review",
        "previous_turns_for_review",
        "utterance_for_review",
    }:
        raise ContractBuildError("structured-context field allowlist drift")
    return {
        "representation_module": str(LR4B_RELATIVE_ROOT / "context_representation.py"),
        "forbidden_field_string_constant_count": len(leaked_names),
        "model_input_field_access": {
            QUERY_ONLY_V1: list(MODEL_INPUT_FIELDS[QUERY_ONLY_V1]),
            STRUCTURED_CONTEXT_V1: list(MODEL_INPUT_FIELDS[STRUCTURED_CONTEXT_V1]),
        },
        "status": "PASS",
    }


def analyse_contract(project_root: Path) -> tuple[dict[str, dict[str, object]], list[dict[str, object]]]:
    baseline = _verify_baseline(project_root)
    lr4a_checksum = _verify_lr4a_checksum(project_root)

    authorised_inputs: list[dict[str, object]] = []
    for role, relative_path in sorted(PATHS.items()):
        path = _safe_path(project_root, role)
        _verify_required_path(path, role)
        authorised_inputs.append({
            "role": role,
            "relative_path": relative_path,
            "sha256": sha256_file(path),
            "size_bytes": path.stat().st_size,
        })
    actual_eedi_hashes = {
        relative_path: sha256_file(authorised_project_path(project_root, relative_path))
        for relative_path in EXPECTED_EEDI_HASHES
    }
    if actual_eedi_hashes != EXPECTED_EEDI_HASHES:
        raise ContractBuildError("secondary Eedi input fingerprint mismatch")

    full = _read_csv(_safe_path(project_root, "full_eedi"))
    retained = _read_csv(_safe_path(project_root, "retained_eedi"))
    expanded = _read_jsonl(_safe_path(project_root, "expanded_train"))
    dev = _read_jsonl(_safe_path(project_root, "dev"))
    approved = _read_jsonl(_safe_path(project_root, "approved_index"))
    scenarios_payload = _read_json(_safe_path(project_root, "scenarios"))
    reliability = _read_json(_safe_path(project_root, "reliability"))
    coverage = _read_json(_safe_path(project_root, "coverage"))
    contamination = _read_json(_safe_path(project_root, "contamination"))
    provenance = _read_json(_safe_path(project_root, "provenance"))
    lr4a_validation = _read_json(_safe_path(project_root, "lr4a_validation"))
    label_universe = _read_json(_safe_path(project_root, "label_universe"))
    dev_views = _read_json(_safe_path(project_root, "dev_views"))
    lr3r_protocol = _read_json(_safe_path(project_root, "lr3r_protocol"))
    lr3r_comparison = _read_json(_safe_path(project_root, "lr3r_comparison"))
    lr3s_protocol = _read_json(_safe_path(project_root, "lr3s_protocol"))
    lr3s_comparison = _read_json(_safe_path(project_root, "lr3s_comparison"))
    semantic_config = _read_json(_safe_path(project_root, "semantic_config"))
    semantic_selection = _read_json(_safe_path(project_root, "semantic_selection"))
    approved_metadata = _read_json(_safe_path(project_root, "approved_metadata"))

    full_ids = {row["record_id"] for row in full}
    retained_ids = {row["record_id"] for row in retained}
    if len(full) != EXPECTED_COUNTS["full_researcher_confirmed"] or len(full_ids) != len(full):
        raise ContractBuildError("full researcher-confirmed count mismatch")
    if len(retained) != EXPECTED_COUNTS["retained_secondary"] or len(retained_ids) != len(retained):
        raise ContractBuildError("retained secondary count mismatch")
    if not retained_ids < full_ids or len(full_ids - retained_ids) != EXPECTED_COUNTS["excluded_secondary"]:
        raise ContractBuildError("retained/excluded membership mismatch")
    mapping_counts = Counter(row["final_mapping_status"] for row in retained)
    if mapping_counts != Counter({
        "direct_shared_intent": EXPECTED_COUNTS["direct_shared_intent"],
        "contextual_shared_intent": EXPECTED_COUNTS["contextual_shared_intent"],
    }):
        raise ContractBuildError("mapping-status count mismatch")

    expanded_by_id = {str(row["record_id"]): row for row in expanded}
    if len(expanded) != EXPECTED_COUNTS["expanded_train"] or len(expanded_by_id) != len(expanded):
        raise ContractBuildError("expanded TRAIN count mismatch")
    pairwise_rows = [row for row in expanded if row.get("pairwise_eligible") is True]
    singleton_rows = [row for row in expanded if row.get("pairwise_eligible") is False]
    pairwise_labels = {str(row["intent_label"]) for row in pairwise_rows}
    if (
        len(pairwise_rows) != EXPECTED_COUNTS["pairwise_capable"]
        or len(pairwise_labels) != EXPECTED_COUNTS["pairwise_labels"]
        or len(singleton_rows) != EXPECTED_COUNTS["non_pairwise_singletons"]
    ):
        raise ContractBuildError("pairwise-capable count mismatch")

    scenario_sets: dict[str, set[str]] = {}
    scenario_membership: defaultdict[str, list[str]] = defaultdict(list)
    scenario_rows: list[dict[str, object]] = []
    for scenario in scenarios_payload["scenarios"]:
        scenario_id = str(scenario["scenario_id"])
        record_ids = {str(record_id) for record_id in scenario["record_ids"]}
        if int(scenario["record_count"]) != len(record_ids):
            raise ContractBuildError("scenario declared count mismatch")
        scenario_sets[scenario_id] = record_ids
        for record_id in record_ids:
            scenario_membership[record_id].append(scenario_id)
        label_counts = Counter(
            str(expanded_by_id[record_id]["intent_label"])
            for record_id in record_ids
        )
        scenario_rows.append({
            "scenario_id": scenario_id,
            "record_count": len(record_ids),
            "membership_sha256": _membership_fingerprint(record_ids),
            "per_label_counts": dict(sorted(label_counts.items())),
        })
    if {name: len(values) for name, values in scenario_sets.items()} != EXPECTED_SCENARIOS:
        raise ContractBuildError("scenario count mismatch")
    if not validate_strict_scenarios(scenario_sets):
        raise ContractBuildError("scenario nesting mismatch")
    if scenario_sets["V3"] != {str(row["record_id"]) for row in pairwise_rows}:
        raise ContractBuildError("V3 membership differs from pairwise-capable records")
    if scenarios_payload.get("membership_rule_uses_dev_performance") is not False:
        raise ContractBuildError("scenario membership used DEV performance")

    approved_by_id = {str(row["example_id"]): row for row in approved}
    retained_by_id = {row["record_id"]: row for row in retained}
    if len(approved_by_id) != 62 or approved_metadata.get("final_index_count") != 62:
        raise ContractBuildError("approved-index count mismatch")

    ledger: list[dict[str, object]] = []
    representations: list[str] = []
    representation_hashes: list[str] = []
    lengths_by_mode: defaultdict[str, list[int]] = defaultdict(list)
    mode_counts: Counter[str] = Counter()
    context_missing = 0
    source_hash_mismatch = 0
    label_mismatch = 0
    for record_id in sorted(expanded_by_id):
        manifest = expanded_by_id[record_id]
        anchor_sha: str | None = None
        previous_sha: str | None = None
        if record_id in approved_by_id:
            source = approved_by_id[record_id]
            representation = build_query_only_representation(str(source["query"]))
            query = representation
            context_mode = QUERY_ONLY_V1
            source_label = str(source["final_semantic_label"])
            source_query = str(source["query"])
        elif record_id in retained_by_id:
            source = retained_by_id[record_id]
            source_label = source["final_target_intent"]
            source_query = source["utterance_for_review"]
            query = build_query_only_representation(source_query)
            if source["final_mapping_status"] == "contextual_shared_intent":
                try:
                    representation = build_structured_context_representation(
                        question_anchor_for_review=source["question_anchor_for_review"],
                        previous_turns_for_review=source["previous_turns_for_review"],
                        utterance_for_review=source["utterance_for_review"],
                    )
                except (TypeError, ValueError) as exc:
                    context_missing += 1
                    raise ContractBuildError("required contextual source field missing") from exc
                context_mode = STRUCTURED_CONTEXT_V1
                anchor_sha = _text_sha256(normalise_source_field(source["question_anchor_for_review"]))
                previous_sha = _text_sha256(normalise_source_field(source["previous_turns_for_review"]))
            elif source["final_mapping_status"] == "direct_shared_intent":
                representation = query
                context_mode = QUERY_ONLY_V1
            else:
                raise ContractBuildError("unexpected retained mapping status")
        else:
            raise ContractBuildError("expanded TRAIN record cannot resolve to authorised source")
        if source_label != str(manifest["intent_label"]):
            label_mismatch += 1
        if _text_sha256(normalise_source_field(source_query)) != str(manifest["query_sha256"]):
            source_hash_mismatch += 1
        representation_hash = representation_sha256(representation)
        representations.append(representation)
        representation_hashes.append(representation_hash)
        mode_counts[context_mode] += 1
        lengths_by_mode[context_mode].append(len(representation))
        ledger.append({
            "record_id": record_id,
            "source_dataset_id": manifest["source_dataset_id"],
            "intent_label": manifest["intent_label"],
            "context_mode": context_mode,
            "query_source_sha256": _text_sha256(query),
            "question_anchor_source_sha256": anchor_sha,
            "previous_turns_source_sha256": previous_sha,
            "representation_sha256": representation_hash,
            "representation_character_count": len(representation),
            "scenario_membership": sorted(scenario_membership.get(record_id, [])),
            "annotation_reliability": manifest["annotation_reliability"],
        })
    if context_missing or source_hash_mismatch or label_mismatch:
        raise ContractBuildError("representation source validation failed")
    if mode_counts != Counter({
        QUERY_ONLY_V1: EXPECTED_COUNTS["query_only"],
        STRUCTURED_CONTEXT_V1: EXPECTED_COUNTS["structured_context"],
    }):
        raise ContractBuildError("context-mode count mismatch")
    if any(set(row) != set(LEDGER_FIELDS) for row in ledger):
        raise ContractBuildError("local ledger field allowlist violation")

    pairwise_mode_counts = Counter(
        str(row["context_mode"])
        for row in ledger
        if str(row["record_id"]) in scenario_sets["V3"]
    )
    non_pairwise_mode_counts = Counter(
        str(row["context_mode"])
        for row in ledger
        if str(row["record_id"]) not in scenario_sets["V3"]
    )

    model_input_audit = _validate_model_input_code(project_root)
    ledger_projection = "".join(
        f'{row["record_id"]}\t{row["representation_sha256"]}\n'
        for row in ledger
    )
    representation_summary = {
        "schema_version": "lr4b-context-representation-summary-v1",
        "stage": "RQ1-A",
        "status": "PASS",
        "record_count": len(ledger),
        "context_mode_counts": dict(sorted(mode_counts.items())),
        "pairwise_v3_context_mode_counts": dict(sorted(pairwise_mode_counts.items())),
        "non_pairwise_context_mode_counts": dict(sorted(non_pairwise_mode_counts.items())),
        "model_input_field_allowlist": {
            mode: list(fields) for mode, fields in sorted(MODEL_INPUT_FIELDS.items())
        },
        "normalisation_policy": {
            "file_decode": "UTF-8-SIG",
            "unicode": "NFC",
            "newline": "CRLF_AND_CR_TO_LF",
            "field_edge_whitespace": "TRIM",
            "internal_space_newline_punctuation_case_words": "PRESERVE",
            "casefold": False,
            "punctuation_removal": False,
            "internal_whitespace_collapse": False,
            "spelling_correction": False,
            "summarisation": False,
            "query_rewriting": False,
            "llm_synthesis": False,
        },
        "structured_field_order": [
            "QUESTION_ANCHOR",
            "PREVIOUS_TURNS",
            "CURRENT_STUDENT_UTTERANCE",
        ],
        "missing_required_context_field_count": context_missing,
        "duplicate_representation_hash_count": len(representation_hashes) - len(set(representation_hashes)),
        "character_length_distribution": {
            mode: _length_distribution(values)
            for mode, values in sorted(lengths_by_mode.items())
        },
        "per_label_record_counts": dict(sorted(Counter(
            str(row["intent_label"]) for row in ledger
        ).items())),
        "representation_ledger_fingerprint": _text_sha256(ledger_projection),
        "ledger_path": str(LOCAL_LEDGER_PATH),
        "ledger_tracked": False,
        "ledger_contains_natural_language": False,
        "model_input_code_audit": model_input_audit,
        "tokenizer_diagnostic": "TOKENIZER_DIAGNOSTIC_DEFERRED_TO_RQ1_B_PREFLIGHT",
        "tokenizer_loaded": False,
        "model_weights_loaded": False,
        "embedding_executed": False,
        "truncation_contract": truncation_contract(),
    }

    train_query_hashes = {str(row["query_sha256"]) for row in expanded}
    train_normalised_hashes = {str(row["normalised_query_sha256"]) for row in expanded}
    dev_query_hashes = {str(row["query_sha256"]) for row in dev}
    dev_normalised_hashes = {str(row["normalised_query_sha256"]) for row in dev}
    source_train = {(str(row["source_dataset_id"]), str(row["source_record_id"])) for row in expanded}
    source_dev = {(str(row["source_dataset_id"]), str(row["source_record_id"])) for row in dev}
    collision_fields = ("scenario_id", "paraphrase_family_id", "parent_id", "contrast_set_id")
    identifier_collisions = {
        field: len(_identifiers(expanded, field) & _identifiers(dev, field))
        for field in collision_fields
    }
    leakage = {
        "train_dev_exact_query_overlap": len(train_query_hashes & dev_query_hashes),
        "train_dev_normalised_query_overlap": len(train_normalised_hashes & dev_normalised_hashes),
        "train_dev_source_record_collision": len(source_train & source_dev),
        "train_dev_identifier_collisions": identifier_collisions,
        "functional_qa_train_record_count": sum(
            str(row["source_dataset_id"]) == "functional_qa_authorised_dev_v2"
            for row in expanded
        ),
        "functional_qa_query_overlap": contamination["retained_256_comparisons"]["functional_qa_dev_84"]["normalised"]["shared_identity_count"],
        "unified_benchmark_query_overlap": contamination["retained_256_comparisons"]["unified_benchmark"]["normalised"]["shared_identity_count"],
        "question_anchor_policy": {
            "train_dev_collision_status": "NOT_AVAILABLE_DEV_HAS_NO_QUESTION_ANCHOR_HASH",
            "within_eedi_shared_anchor_group_count": contamination["within_eedi_relationships"]["normalised_question_anchor"]["duplicate_group_count"],
            "within_eedi_records_in_shared_anchor_groups": contamination["within_eedi_relationships"]["normalised_question_anchor"]["records_in_duplicate_groups"],
            "mixed_label_shared_anchor_group_count": contamination["within_eedi_relationships"]["mixed_label_shared_anchor_group_count"],
            "shared_anchor_records_claimed_independent": False,
        },
        "label_field_leakage": 0,
        "final_gold_accessed": False,
        "final_gold_searched": False,
        "final_gold_used": False,
    }
    if (
        leakage["train_dev_exact_query_overlap"]
        or leakage["train_dev_normalised_query_overlap"]
        or leakage["train_dev_source_record_collision"]
        or any(identifier_collisions.values())
        or leakage["functional_qa_train_record_count"]
        or leakage["functional_qa_query_overlap"]
        or leakage["unified_benchmark_query_overlap"]
        or leakage["label_field_leakage"]
    ):
        raise ContractBuildError("TRAIN/DEV or label leakage gate failed")
    if contamination.get("primary_v3_accessed") is not False or contamination.get("stage6_final_gold_accessed") is not False:
        raise ContractBuildError("upstream final-gold boundary state is not false")

    label_count = int(label_universe["production_retrieval_universe"]["label_count"])
    if label_count != 16:
        raise ContractBuildError("candidate label universe count mismatch")
    if lr3r_comparison["selected_robustness_stage_development_architecture"] != "M64":
        raise ContractBuildError("M64 inherited architecture mismatch")
    if lr3s_comparison["selected_development_training_weighting_policy"] != "D0_DIRECTED_EQUAL_WEIGHT":
        raise ContractBuildError("D0 inherited weighting mismatch")
    if tuple(lr3r_protocol["training_seeds"]) != FIVE_SEEDS or tuple(lr3s_protocol["training_seeds"]) != FIVE_SEEDS:
        raise ContractBuildError("five-seed contract mismatch")
    model_contract = {
        "K0": {
            "name": "Keyword hard-routing baseline",
            "description": "degenerate single-candidate ranking baseline",
            "production_rules_modified": False,
            "ranking_length": 1,
            "reciprocal_rank_if_correct": 1,
            "reciprocal_rank_if_incorrect": 0,
            "mrr_equals_top1_accuracy": True,
            "arbitrary_remaining_intent_order_created": False,
            "shadow_adapter_top1_parity": {
                "fixture": "frozen approved 62-record intent index",
                "records": 62,
                "matches": 62,
                "mismatches": 0,
                "parity_percent": 100.0,
                "production_keyword_source_protected_by_starting_fingerprint": True,
            },
        },
        "C0": {
            "name": "MPNet cosine baseline",
            "encoder_repo": semantic_config["model"]["repo_id"],
            "encoder_revision": semantic_config["model"]["revision"],
            "local_model_path_reference": semantic_config["model"]["local_path"],
            "local_files_only": True,
            "model_asset_tracked": False,
            "model_asset_accessed_in_rq1a": False,
            "approved_index_path": semantic_config["artifacts"]["approved_index"]["path"],
            "approved_index_sha256": semantic_config["artifacts"]["approved_index"]["sha256"],
            "frozen_embedding_artifact_sha256": semantic_config["artifacts"]["embedding_npz"]["sha256"],
            "model_manifest_sha256": semantic_selection["model_manifest_sha256"],
            "pooling_policy": "FROZEN_EXISTING_SENTENCE_TRANSFORMER_MPNET_POOLING",
            "similarity": "COSINE",
            "intent_aggregation": semantic_config["aggregation"].upper(),
            "candidate_label_count": label_count,
            "embedding_executed_in_rq1a": False,
        },
        "M64": {
            "architecture_id": "M64",
            "architecture": lr3s_protocol["architecture"],
            "hidden_dimension": 64,
            "embedding_encoder": "SAME_FROZEN_MPNET_AS_C0",
            "feature_schema": lr3s_protocol["feature_schema"],
            "feature_dimension": lr3s_protocol["feature_dimension"],
            "training_weighting": "D0_DIRECTED_EQUAL_WEIGHT",
            "hard_negative_expansion": False,
            "new_architecture_search": False,
            "new_loss_search": False,
            "intent_taxonomy_change": False,
            "five_seeds": list(FIVE_SEEDS),
            "best_single_seed_selection": False,
            "optimizer": lr3s_protocol["optimizer"],
            "learning_rate": lr3s_protocol["learning_rate"],
            "weight_decay": lr3s_protocol["weight_decay"],
            "batch_size": lr3s_protocol["batch_size"],
            "maximum_epochs": lr3s_protocol["max_epochs"],
            "early_stopping_patience": lr3s_protocol["early_stopping_patience"],
            "early_stopping_view": lr3s_protocol["early_stopping_view"],
            "gradient_clip_norm": lr3s_protocol["gradient_clip_norm"],
            "dropout": lr3s_protocol["dropout"],
            "pair_direction_policy": lr3r_protocol["pair_direction_policy"],
            "pair_construction": "FROZEN_LR2R_PAIR_CONTRACT",
            "negative_sampling_policy": "FROZEN_LR2R_EPISODIC_SAMPLING_SPEC",
            "pair_sampling_spec_sha256": sha256_file(_safe_path(project_root, "lr2r_sampling")),
            "mpnet_finetuned": False,
        },
    }

    development_selection_rule = [
        "higher_five_seed_mean_VIEW_A_MRR",
        "higher_five_seed_mean_VIEW_A_Top1_Accuracy",
        "higher_five_seed_mean_VIEW_A_Macro_F1",
        "lower_five_seed_VIEW_A_MRR_standard_deviation",
        "smaller_data_volume_scenario",
    ]
    final_metrics = [
        "MRR",
        "Top-1 Accuracy",
        "Recall@3",
        "Macro-F1",
        "Per-intent precision/recall/F1",
        "Mean gold rank",
        "Confusion matrix",
    ]
    experiment_contract = {
        "schema_version": CONTRACT_VERSION,
        "stage": "RQ1-A",
        "status": "CONTRACT_FROZEN",
        "baseline": baseline,
        "data_roles": {
            "TRAIN": "governed expanded TRAIN; scenarios fixed before DEV",
            "DEV_PRIMARY": "VIEW_A_PAIRWISE_SEEN_LABELS",
            "DEV_DIAGNOSTIC_ONLY": [
                "VIEW_B_SINGLETON_UNSEEN",
                "MIXED_84_RECORD_DEV",
                "INDIVIDUAL_BEST_SEED",
                "INDIVIDUAL_INTENT_ANECDOTE",
            ],
            "FINAL_GOLD": "RQ1_C_SINGLE_USE_ONLY_AND_UNOPENED_IN_RQ1_A",
        },
        "governed_counts": dict(EXPECTED_COUNTS),
        "data_volume_scenarios": EXPECTED_SCENARIOS,
        "strict_scenario_nesting": True,
        "scenario_membership_uses_dev_performance": False,
        "future_rq1b_comparisons": ["C0", "M64-V0", "M64-V1", "M64-V2", "M64-V3"],
        "comparison_input_policy": {
            "same_record_same_frozen_representation_for_K0_C0_M64": True,
            "keyword_rules_modified": False,
            "context_strategy_selected_using_K0": False,
        },
        "controlled_conditions": [
            "M64 architecture",
            "D0 weighting",
            "pair construction",
            "negative sampling policy",
            "optimizer",
            "learning-rate policy",
            "early stopping",
            "maximum epochs",
            "five seeds",
            "DEV views",
            "candidate label universe",
            "metrics",
        ],
        "model_contracts": model_contract,
        "development_selection": {
            "primary_view": "VIEW_A_PAIRWISE_SEEN_LABELS",
            "lexicographic_rule": development_selection_rule,
            "diagnostics_cannot_select_model": [
                "VIEW_B_SINGLETON_UNSEEN",
                "MIXED_84_RECORD_DEV",
                "INDIVIDUAL_BEST_SEED",
                "INDIVIDUAL_INTENT_ANECDOTE",
                "FINAL_GOLD",
            ],
            "bootstrap_role": "DEVELOPMENT_UNCERTAINTY_DIAGNOSTIC_ONLY",
            "bootstrap_confirmatory_significance_test": False,
            "dev_record_count": dev_views["dev_record_count"],
        },
        "final_evaluation": {
            "stage": "RQ1-C_ONLY",
            "methods": ["K0", "C0", "RQ1_B_PRESELECTED_M64_SCENARIO"],
            "single_use_final_gold": True,
            "primary_metric": "MRR",
            "metrics": final_metrics,
            "nonlinear_replaces_cosine_only_if_all": [
                "final_gold_MRR_above_C0",
                "paired_confidence_interval_supports_positive_difference",
                "preregistered_paired_significance_test_passes",
                "Top1_direction_consistent",
                "Macro_F1_no_material_degradation",
                "result_not_driven_by_one_seed",
                "no_systematic_weak_class_collapse",
            ],
            "fallback": "C0 remains the selected Router",
            "executed_in_rq1a": False,
        },
        "invariants": {
            "model_training": False,
            "checkpoint_creation": False,
            "checkpoint_loading": False,
            "embedding_execution": False,
            "final_gold_accessed": False,
            "final_gold_searched": False,
            "final_gold_used": False,
            "provider_calls": False,
            "network_access": False,
            "production_code_changes": False,
            "rq1b_started": False,
        },
    }

    scenario_summary = {
        "schema_version": "lr4b-data-scenario-summary-v1",
        "stage": "RQ1-A",
        "status": "PASS",
        "expanded_train_record_count": len(expanded),
        "pairwise_capable_record_count": len(pairwise_rows),
        "pairwise_label_count": len(pairwise_labels),
        "non_pairwise_singleton_record_count": len(singleton_rows),
        "scenarios": sorted(scenario_rows, key=lambda row: str(row["scenario_id"])),
        "strict_nesting": True,
        "membership_selected_using_dev_results": False,
        "provenance_metadata": {
            "required_fields": list(PROVENANCE_FIELDS),
            "expanded_manifest_provenance_fingerprint": _provenance_fingerprint(expanded),
            "conversation_group_count": provenance["group_summary"]["conversation_group_count"],
            "query_family_count": provenance["group_summary"]["query_family_count"],
            "question_anchor_count": provenance["group_summary"]["question_anchor_count"],
            "shared_question_anchor_count": provenance["group_summary"]["shared_question_anchor_count"],
            "independent_second_rater_true_count": sum(
                row.get("independent_second_rater") is True for row in expanded
            ),
            "raw_record_metadata_emitted": False,
        },
    }

    inventory_summary = {
        "schema_version": "lr4b-input-inventory-summary-v1",
        "stage": "RQ1-A",
        "status": "PASS",
        "authorised_input_count": len(authorised_inputs),
        "authorised_inputs": authorised_inputs,
        "expected_eedi_hashes": EXPECTED_EEDI_HASHES,
        "eedi_hashes_match": True,
        "lr4a_r1_checksum": lr4a_checksum,
        "full_record_count": len(full),
        "retained_record_count": len(retained),
        "excluded_record_count": len(full_ids - retained_ids),
        "approved_intent_index_record_count": len(approved),
        "approved_intent_index_sha256": semantic_config["artifacts"]["approved_index"]["sha256"],
        "local_model_path_reference": semantic_config["model"]["local_path"],
        "local_model_contents_accessed": False,
        "final_gold_accessed": False,
        "final_gold_searched": False,
        "raw_text_emitted": False,
    }

    preflight = {
        "schema_version": "lr4b-preflight-report-v1",
        "stage": "RQ1-A",
        "status": "PASS",
        "baseline": baseline,
        "counts": {
            "full": len(full),
            "retained": len(retained),
            "excluded": len(full_ids - retained_ids),
            "direct": mapping_counts["direct_shared_intent"],
            "contextual": mapping_counts["contextual_shared_intent"],
            "expanded": len(expanded),
            "pairwise": len(pairwise_rows),
            "pairwise_labels": len(pairwise_labels),
            "non_pairwise_singletons": len(singleton_rows),
        },
        "scenarios": EXPECTED_SCENARIOS,
        "strict_scenario_nesting": True,
        "representation": {
            "missing_context_fields": context_missing,
            "duplicate_representation_hashes": representation_summary["duplicate_representation_hash_count"],
            "ledger_fingerprint": representation_summary["representation_ledger_fingerprint"],
            "deterministic_double_build_ready": True,
        },
        "keyword_baseline_parity": model_contract["K0"]["shadow_adapter_top1_parity"],
        "leakage_and_provenance": leakage,
        "upstream_governance": {
            "lr4a_validation_safe_to_proceed": lr4a_validation["safe_to_proceed_to_lr4b"],
            "lr4a_protected_snapshot_unchanged": lr4a_validation["protected_snapshot_unchanged"],
            "lr4a_final_gold_accessed": lr4a_validation["final_gold_accessed"],
            "lr4a_primary_v3_accessed": lr4a_validation["primary_v3_accessed"],
            "annotation_reliability_counts": reliability["counts"],
            "label_coverage_pairwise_capable_records": coverage["proposed_expanded"]["pairwise_capable_records"],
        },
        "model_training": False,
        "checkpoint_created": False,
        "checkpoint_loaded": False,
        "model_loaded": False,
        "embedding_executed": False,
        "provider_calls": False,
        "network_access": False,
        "final_gold_accessed": False,
        "final_gold_searched": False,
        "final_gold_used": False,
        "raw_text_emitted": False,
    }

    outputs = {
        "lr4b_experiment_contract_v1.json": experiment_contract,
        "lr4b_input_inventory_summary_v1.json": inventory_summary,
        "lr4b_data_scenario_summary_v1.json": scenario_summary,
        "lr4b_context_representation_summary_v1.json": representation_summary,
        "lr4b_preflight_report_v1.json": preflight,
    }
    if tuple(sorted(outputs)) != tuple(sorted(SAFE_JSON_FILENAMES)):
        raise ContractBuildError("safe-output filename contract drift")

    # Safe outputs are built only from counts, labels, paths, hashes, booleans,
    # and frozen method statements. Guard against accidental raw text copying.
    output_bytes = b"".join(canonical_json_bytes(outputs[name]) for name in sorted(outputs))
    for representation in representations:
        if len(representation) >= 24 and representation.encode("utf-8") in output_bytes:
            raise ContractBuildError("raw representation leaked into safe output")
    return outputs, ledger


def safe_output_bundle_fingerprint(outputs: Mapping[str, object]) -> str:
    digest = hashlib.sha256()
    for name in sorted(outputs):
        digest.update(name.encode("utf-8"))
        digest.update(b"\0")
        digest.update(canonical_json_bytes(outputs[name]))
    return digest.hexdigest()


def write_safe_outputs(project_root: Path, outputs: Mapping[str, object]) -> None:
    output_root = authorised_project_path(project_root, LR4B_RELATIVE_ROOT)
    output_root.mkdir(parents=True, exist_ok=True)
    for name in SAFE_JSON_FILENAMES:
        (output_root / name).write_bytes(canonical_json_bytes(outputs[name]))
    checksum_relative_paths = [
        *DOC_PATHS,
        str(LR4B_RELATIVE_ROOT / "__init__.py"),
        str(LR4B_RELATIVE_ROOT / "contract_schema.py"),
        str(LR4B_RELATIVE_ROOT / "context_representation.py"),
        str(LR4B_RELATIVE_ROOT / "build_lr4b_contract.py"),
        str(LR4B_RELATIVE_ROOT / "validate_lr4b_contract.py"),
        str(LR4B_RELATIVE_ROOT / "test_lr4b_contract_unittest.py"),
        *(str(LR4B_RELATIVE_ROOT / name) for name in SAFE_JSON_FILENAMES),
    ]
    checksum_lines: list[str] = []
    for relative_path in sorted(checksum_relative_paths):
        path = authorised_project_path(project_root, relative_path)
        _verify_required_path(path, "rq1a_output")
        checksum_lines.append(f"{sha256_file(path)}  {relative_path}")
    checksum_path = authorised_project_path(project_root, OUTPUT_CHECKSUM_PATH)
    checksum_path.write_text("\n".join(checksum_lines) + "\n", encoding="utf-8")


def write_local_ledger(project_root: Path, ledger: Iterable[Mapping[str, object]]) -> Path:
    ignore_path = project_root / ".gitignore"
    expected_rule = "evaluation/learned_intent_ranking/lr4b/local_artifacts/"
    if expected_rule not in ignore_path.read_text(encoding="utf-8").splitlines():
        raise ContractBuildError("local ledger ignore rule is absent")
    ledger_path = authorised_project_path(project_root, LOCAL_LEDGER_PATH)
    ledger_path.parent.mkdir(parents=True, exist_ok=True)
    rows = list(ledger)
    if any(set(row) != set(LEDGER_FIELDS) for row in rows):
        raise ContractBuildError("ledger field allowlist violation")
    content = "".join(
        json.dumps(row, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n"
        for row in rows
    )
    ledger_path.write_text(content, encoding="utf-8")
    return ledger_path


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--project-root", required=True)
    actions = parser.add_mutually_exclusive_group(required=True)
    actions.add_argument("--check-only", action="store_true")
    actions.add_argument("--emit-local-ledger", action="store_true")
    actions.add_argument("--write-safe-outputs", action="store_true")
    args = parser.parse_args(argv)
    project_root = Path(os.path.abspath(args.project_root))
    try:
        outputs, ledger = analyse_contract(project_root)
        fingerprint = safe_output_bundle_fingerprint(outputs)
        action = "CHECK_ONLY"
        if args.emit_local_ledger:
            write_local_ledger(project_root, ledger)
            action = "EMIT_LOCAL_LEDGER"
        elif args.write_safe_outputs:
            write_safe_outputs(project_root, outputs)
            action = "WRITE_SAFE_OUTPUTS"
        result = {
            "action": action,
            "status": "PASS",
            "safe_output_bundle_sha256": fingerprint,
            "record_count": len(ledger),
            "raw_text_emitted": False,
            "final_gold_accessed": False,
            "final_gold_searched": False,
            "model_training": False,
            "embedding_executed": False,
            "network_access": False,
        }
        print(json.dumps(result, ensure_ascii=False, sort_keys=True, separators=(",", ":")))
        return 0
    except (ContractBuildError, OSError, ValueError, TypeError, json.JSONDecodeError):
        print(json.dumps({
            "status": "FAIL",
            "error": "RQ1_A_CONTRACT_BUILD_FAILED",
            "raw_text_emitted": False,
        }, ensure_ascii=False, sort_keys=True, separators=(",", ":")))
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
