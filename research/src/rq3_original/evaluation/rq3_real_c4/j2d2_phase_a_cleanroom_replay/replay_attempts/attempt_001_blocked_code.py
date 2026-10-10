#!/usr/bin/env python3
"""Score-free, standard-library-only applicability replay.

Run a byte copy of this file inside <fresh clean-room>/inputs/. The input
directory contains exactly the five pinned inputs plus this code. Generated
outputs are exclusively created in the sibling outputs/ directory, within the
same clean-room root. No repository module, key, environment variable, network,
subprocess, outcome data, or prior Phase-A decision artifact is used.
"""

import collections
import csv
import hashlib
import io
import json
import os
from pathlib import Path
import sys


CODE_NAME = "phase_a_cleanroom_replay.py"
INPUT_SPECS = {
    "applicability_researcher_review_packet_completed.csv": (
        106896, "0f248db0e00609fd4630c759e36548c62b61de5935d19ff7706601eb528c78a1"),
    "applicability_researcher_attestation_completed.md": (
        2212, "f2f7522f1ceb21bfe5e49176610fa48e67a6badd94158d5cfad8054e93f09bcc"),
    "applicability_researcher_review_packet.csv": (
        95499, "5e36691b2929d18a14528a4c31bee34345712ace5c85d778ec6c917d29ee2962"),
    "opaque_review_id_mapping.csv": (
        6196, "de04ba913919447fddefafa1127b1480fb5c8614bf4cfce570f52b548f397c25"),
    "condition_applicability_v1.jsonl": (
        671548, "1f5b159b3d80506c32265624a8f4e5866af4dba996dd0f62abf53dff93f31084"),
}
PACKET_FIELDS = (
    "applicability_review_id", "student_query", "current_lad_page",
    "visible_conversation_history", "student_specific_context_available_or_relevant",
    "persistent_memory_relevance_information", "pre_response_material_lad_page_candidates",
    "personalisation_definition", "personalisation_na_rule", "actionability_definition",
    "actionability_na_rule", "motivation_and_engagement_definition",
    "motivation_and_engagement_na_rule", "multi_page_cohesiveness_definition",
    "multi_page_cohesiveness_na_rule", "researcher_personalisation_applicable",
    "researcher_actionability_applicable", "researcher_motivation_and_engagement_applicable",
    "researcher_material_lad_pages", "researcher_notes",
)
DECISION_FIELDS = {
    "PERSONALISATION": "researcher_personalisation_applicable",
    "ACTIONABILITY": "researcher_actionability_applicable",
    "MOTIVATION_AND_ENGAGEMENT": "researcher_motivation_and_engagement_applicable",
}
EDITABLE_FIELDS = frozenset(DECISION_FIELDS.values()) | {
    "researcher_material_lad_pages", "researcher_notes"}
MAPPING_FIELDS = ("applicability_review_id", "scenario_id", "semantic_input_sha256")
CRITERIA = (
    "CLARITY", "CONTEXT_AWARENESS", "PERSONALISATION", "ACTIONABILITY",
    "MOTIVATION_AND_ENGAGEMENT", "RELIABILITY", "MULTI_PAGE_COHESIVENESS",
    "ERROR_HANDLING",
)
RESEARCHER_CRITERIA = tuple(DECISION_FIELDS) + ("MULTI_PAGE_COHESIVENESS",)
PAGES = frozenset({"Overview", "Reflection", "Debate", "Lecture", "Resources"})
V1_FIELDS = frozenset({
    "schema_version", "scenario_id", "mode", "frozen_applicability_map",
    "source_metadata", "freeze_timing", "candidate_response_accessed", "gold_accessed"})
V1_MAP_FIELDS = frozenset({
    "schema_version", "criteria", "applicable_primary_count", "freeze_status",
    "applicability_sha256"})
V1_METADATA_FIELDS = frozenset({
    "ambiguity_relevant", "applicability_metadata_version", "boundary_handling_relevant",
    "conflict_relevant", "gold_planning_required", "insufficiency_relevant",
    "long_term_memory_relevant", "material_lad_pages", "missing_evidence_relevant",
    "request_requires_advice", "student_facing_support_appropriate",
    "student_specific_data_relevant"})
OUTPUT_NAMES = (
    "scenario_decisions_v2.jsonl", "scenario_decisions_v2.csv",
    "condition_applicability_v2.jsonl", "condition_applicability_v2.csv",
    "applicability_v1_v2_diff.json", "applicability_distributions.json",
    "source_validation.json", "mapping_metadata.json", "cleanroom_access_audit.json",
)
EXPECTED_DISTRIBUTIONS = {
    "PERSONALISATION": {"YES": 37, "NO": 25},
    "ACTIONABILITY": {"YES": 28, "NO": 34},
    "MOTIVATION_AND_ENGAGEMENT": {"YES": 40, "NO": 22},
    "MATERIAL_LAD_PAGES": {"0": 1, "1": 55, "2": 6},
    "MULTI_PAGE_COHESIVENESS": {"applicable": 6, "not_applicable": 56},
}
EXPECTED_CHANGES = {
    "scenarios_with_one_or_more_change": 39,
    "PERSONALISATION_true_to_false": 15,
    "ACTIONABILITY_false_to_true": 13,
    "MOTIVATION_AND_ENGAGEMENT_true_to_false": 22,
    "MULTI_PAGE_COHESIVENESS_true_to_false": 7,
    "opposite_direction_changes": 0,
    "changed_condition_maps": 351,
    "unchanged_condition_maps": 207,
    "error_handling_preserved": 558,
}


class ReplayFailure(Exception):
    """Fail closed without disclosing any restricted row identifiers."""


def require(condition, message):
    if not condition:
        raise ReplayFailure(message)


def sha256(data):
    return hashlib.sha256(data).hexdigest()


def json_bytes(value):
    return (json.dumps(value, ensure_ascii=False, sort_keys=True, indent=2,
                       allow_nan=False) + "\n").encode("utf-8")


def jsonl_bytes(rows):
    return b"".join((json.dumps(row, ensure_ascii=False, sort_keys=True,
                               separators=(",", ":"), allow_nan=False) + "\n").encode("utf-8")
                    for row in rows)


def csv_bytes(fields, rows):
    stream = io.StringIO(newline="")
    writer = csv.DictWriter(stream, fieldnames=fields, lineterminator="\n",
                            extrasaction="raise")
    writer.writeheader()
    writer.writerows(rows)
    return stream.getvalue().encode("utf-8")


def exact_keys(value, fields, label):
    require(type(value) is dict and set(value) == set(fields), label + ": unknown or missing field")


def hash_text(value):
    return (type(value) is str and len(value) == 64
            and all(c in "0123456789abcdef" for c in value))


def identity_text(value):
    return (type(value) is str and bool(value) and value == value.strip()
            and all(c.isascii() and (c.isalnum() or c in "_-.:") for c in value))


def parse_csv(data, fields):
    reader = csv.DictReader(io.StringIO(data.decode("utf-8-sig"), newline=""), strict=True)
    require(tuple(reader.fieldnames or ()) == tuple(fields), "CSV schema mismatch")
    rows = list(reader)
    for row in rows:
        exact_keys(row, fields, "CSV row")
        require(all(type(v) is str for v in row.values()), "CSV missing value or excess column")
    return rows


def unique_rows(rows, key, count):
    require(len(rows) == count, "Unexpected row count")
    require(all(identity_text(r[key]) for r in rows), "Invalid opaque or scenario identity")
    result = {r[key]: r for r in rows}
    require(len(result) == count, "Duplicate identity")
    return result


def parse_pages(value, allow_empty):
    require(type(value) is str, "Material page field must be text")
    if value == "" and allow_empty:
        return []
    pages = value.split("|")
    require(bool(pages) and len(set(pages)) == len(pages), "Duplicate material page")
    require(set(pages) <= PAGES, "Unknown material page")
    return sorted(pages)


def freeze_researcher_decisions(blank_rows, completed_rows, mapping_rows):
    """Accept no V1 record or response data; identity joins use opaque IDs only."""
    for row in blank_rows + completed_rows:
        exact_keys(row, PACKET_FIELDS, "Packet")
    for row in mapping_rows:
        exact_keys(row, MAPPING_FIELDS, "Opaque mapping")
        require(hash_text(row["semantic_input_sha256"]), "Invalid semantic identity hash")
    blank = unique_rows(blank_rows, "applicability_review_id", 62)
    completed = unique_rows(completed_rows, "applicability_review_id", 62)
    mapping = unique_rows(mapping_rows, "applicability_review_id", 62)
    unique_rows(mapping_rows, "scenario_id", 62)
    require(set(blank) == set(completed) == set(mapping), "Opaque mapping incomplete")
    notes = set()
    frozen = []
    for review_id in sorted(blank):
        before, after = blank[review_id], completed[review_id]
        require(all(before[f] == "" for f in EDITABLE_FIELDS), "Blank packet is not blank")
        require(all(before[f] == after[f] for f in PACKET_FIELDS if f not in EDITABLE_FIELDS),
                "Unauthorized source-field modification")
        note = after["researcher_notes"].strip()
        require(bool(note) and note not in notes, "Missing or non-distinct researcher note")
        notes.add(note)
        criteria = {}
        for criterion, field in DECISION_FIELDS.items():
            require(after[field] in {"YES", "NO"}, "Decision must be YES or NO")
            criteria[criterion] = after[field] == "YES"
        candidates = parse_pages(before["pre_response_material_lad_page_candidates"], False)
        material = parse_pages(after["researcher_material_lad_pages"], True)
        require(set(material) <= set(candidates), "Material page was not a supplied candidate")
        criteria["MULTI_PAGE_COHESIVENESS"] = len(material) >= 2
        frozen.append({"scenario_id": mapping[review_id]["scenario_id"],
                       "criteria": criteria, "material_lad_pages": material})
    return sorted(frozen, key=lambda row: row["scenario_id"])


def reject_duplicate_json_keys(pairs):
    result = {}
    for key, value in pairs:
        require(key not in result, "Duplicate JSON field")
        result[key] = value
    return result


def parse_v1(data):
    lines = data.decode("utf-8").splitlines()
    require(len(lines) == 558 and all(lines), "V1 condition row count mismatch")
    rows = [json.loads(line, object_pairs_hook=reject_duplicate_json_keys) for line in lines]
    for row in rows:
        exact_keys(row, V1_FIELDS, "V1 record")
        require(identity_text(row["scenario_id"]) and identity_text(row["mode"]),
                "Invalid V1 condition identity")
        require(row["candidate_response_accessed"] is False and row["gold_accessed"] is False,
                "V1 negative-access marker mismatch")
        require(all(type(row[k]) is str and row[k] for k in ("schema_version", "freeze_timing")),
                "Invalid V1 administrative field")
        frozen = row["frozen_applicability_map"]
        exact_keys(frozen, V1_MAP_FIELDS, "V1 applicability map")
        exact_keys(frozen["criteria"], CRITERIA, "V1 criteria")
        require(all(type(v) is bool for v in frozen["criteria"].values()), "Non-boolean V1 applicability")
        require(type(frozen["applicable_primary_count"]) is int, "Invalid applicability count")
        require(hash_text(frozen["applicability_sha256"]), "Invalid V1 applicability hash")
        require(all(type(frozen[k]) is str and frozen[k] for k in ("schema_version", "freeze_status")),
                "Invalid V1 map metadata")
        meta = row["source_metadata"]
        exact_keys(meta, V1_METADATA_FIELDS, "V1 source metadata")
        require(type(meta["applicability_metadata_version"]) is str, "Invalid metadata version")
        require(type(meta["material_lad_pages"]) is list
                and all(type(page) is str and bool(page) for page in meta["material_lad_pages"]),
                "Invalid metadata page type")
        require(all(type(v) is bool for k, v in meta.items()
                    if k not in {"material_lad_pages", "applicability_metadata_version"}),
                "Invalid metadata boolean")
    return rows


def condition_identities(v1):
    """Only these three fields can enter the expansion step."""
    return [{"scenario_id": row["scenario_id"], "mode": row["mode"],
             "ERROR_HANDLING": row["frozen_applicability_map"]["criteria"]["ERROR_HANDLING"]}
            for row in v1]


def expand_conditions(scenarios, identities):
    decisions = {row["scenario_id"]: row for row in scenarios}
    require(len(decisions) == 62 and len(identities) == 558, "Expansion cardinality mismatch")
    seen = set()
    membership = collections.defaultdict(set)
    result = []
    for row in identities:
        exact_keys(row, {"scenario_id", "mode", "ERROR_HANDLING"}, "Condition identity projection")
        require(type(row["ERROR_HANDLING"]) is bool, "ERROR_HANDLING must be boolean")
        key = (row["scenario_id"], row["mode"])
        require(key not in seen and key[0] in decisions, "Duplicate or unknown condition identity")
        seen.add(key)
        membership[key[0]].add(key[1])
        decision = decisions[key[0]]
        criteria = {"CLARITY": True, "CONTEXT_AWARENESS": True, "RELIABILITY": True,
                    **decision["criteria"], "ERROR_HANDLING": row["ERROR_HANDLING"]}
        exact_keys(criteria, CRITERIA, "V2 condition criteria")
        result.append({"scenario_id": key[0], "mode": key[1], "criteria": criteria,
                       "material_lad_pages": list(decision["material_lad_pages"])})
    require(set(membership) == set(decisions), "Scenario membership mismatch")
    require(all(len(values) == 9 for values in membership.values()), "Expected nine conditions per scenario")
    require(len({tuple(sorted(values)) for values in membership.values()}) == 1,
            "Condition identity sets differ")
    return sorted(result, key=lambda row: (row["scenario_id"], row["mode"]))


def distributions(scenarios):
    result = {criterion: {"YES": sum(row["criteria"][criterion] for row in scenarios),
                          "NO": sum(not row["criteria"][criterion] for row in scenarios)}
              for criterion in DECISION_FIELDS}
    result["MATERIAL_LAD_PAGES"] = dict(sorted(collections.Counter(
        str(len(row["material_lad_pages"])) for row in scenarios).items()))
    result["MULTI_PAGE_COHESIVENESS"] = {
        "applicable": sum(row["criteria"]["MULTI_PAGE_COHESIVENESS"] for row in scenarios),
        "not_applicable": sum(not row["criteria"]["MULTI_PAGE_COHESIVENESS"] for row in scenarios)}
    require(result == EXPECTED_DISTRIBUTIONS, "Researcher decision aggregate mismatch")
    return result


def mechanical_diff(v1, v2):
    """Called only after independent researcher decisions and V2 expansion exist."""
    before = {(r["scenario_id"], r["mode"]): r["frozen_applicability_map"]["criteria"] for r in v1}
    after = {(r["scenario_id"], r["mode"]): r["criteria"] for r in v2}
    require(len(before) == len(after) == 558 and set(before) == set(after), "Diff identities differ")
    scenario_changes = collections.defaultdict(set)
    changed_conditions = []
    preserved = 0
    for key in sorted(before):
        old, new = before[key], after[key]
        preserved += old["ERROR_HANDLING"] == new["ERROR_HANDLING"]
        changed = [c for c in CRITERIA if old[c] != new[c]]
        require(set(changed) <= set(RESEARCHER_CRITERIA), "Unexpected non-researcher criterion change")
        if changed:
            changed_conditions.append({"scenario_id": key[0], "mode": key[1],
                                       "changed_criteria": sorted(changed)})
        for criterion in changed:
            scenario_changes[key[0]].add((criterion, old[criterion], new[criterion]))
    directions = collections.Counter(change for values in scenario_changes.values() for change in values)
    intended = {("PERSONALISATION", True, False), ("ACTIONABILITY", False, True),
                ("MOTIVATION_AND_ENGAGEMENT", True, False), ("MULTI_PAGE_COHESIVENESS", True, False)}
    summary = {
        "scenarios_with_one_or_more_change": len(scenario_changes),
        "PERSONALISATION_true_to_false": directions[("PERSONALISATION", True, False)],
        "ACTIONABILITY_false_to_true": directions[("ACTIONABILITY", False, True)],
        "MOTIVATION_AND_ENGAGEMENT_true_to_false": directions[("MOTIVATION_AND_ENGAGEMENT", True, False)],
        "MULTI_PAGE_COHESIVENESS_true_to_false": directions[("MULTI_PAGE_COHESIVENESS", True, False)],
        "opposite_direction_changes": sum(n for d, n in directions.items() if d not in intended),
        "changed_condition_maps": len(changed_conditions),
        "unchanged_condition_maps": 558 - len(changed_conditions),
        "error_handling_preserved": preserved,
    }
    require(summary == EXPECTED_CHANGES, "V1/V2 aggregate mismatch")
    return {"summary": summary, "changed_conditions": changed_conditions,
            "scenario_changes": [{"scenario_id": sid, "changes": [
                {"criterion": criterion, "v1": old, "v2": new}
                for criterion, old, new in sorted(values)]}
                for sid, values in sorted(scenario_changes.items())],
            "old_applicability_used_for_decision_making": False}


def write_once(path, data):
    with open(path, "xb") as stream:
        stream.write(data)


class FileBoundary:
    """Deny data access outside the isolated root, extra inputs and networking."""

    def __init__(self, root):
        self.root = root
        self.inputs = root / "inputs"
        self.outputs = root / "outputs"
        self.readable = {str(self.inputs / name) for name in (*INPUT_SPECS, CODE_NAME)}
        self.writable = {str(self.outputs / name) for name in OUTPUT_NAMES}
        self.reads = set()
        self.writes = set()
        self.denied = 0

    def deny(self):
        self.denied += 1
        raise ReplayFailure("Clean-room access boundary denied an operation")

    def audit(self, event, args):
        if event == "open":
            raw, mode, flags = args
            if not isinstance(raw, (str, bytes, os.PathLike)):
                self.deny()
            name = os.path.abspath(os.fsdecode(raw))
            writing = flags & (os.O_WRONLY | os.O_RDWR | os.O_CREAT | os.O_TRUNC | os.O_APPEND)
            if writing:
                if name not in self.writable or not flags & os.O_EXCL:
                    self.deny()
                self.writes.add(Path(name).name)
            else:
                if name not in self.readable:
                    self.deny()
                self.reads.add(Path(name).name)
        elif event in {"os.listdir", "os.scandir", "os.mkdir"}:
            name = os.path.abspath(os.fsdecode(args[0]))
            allowed = {str(self.root), str(self.inputs), str(self.outputs)}
            if name not in allowed or (event == "os.mkdir" and name != str(self.outputs)):
                self.deny()
        elif (event.startswith(("socket.", "subprocess.", "ctypes."))
              or event in {"os.system", "os.posix_spawn", "os.spawn", "os.exec", "import"}):
            self.deny()


def run():
    code_path = Path(__file__).resolve()
    input_dir, root = code_path.parent, code_path.parent.parent
    require(input_dir.name == "inputs" and root.name.startswith("rq3_j2d2_r0_cleanroom_"),
            "Run only the copied code inside a fresh physical clean-room")
    boundary = FileBoundary(root)
    sys.addaudithook(boundary.audit)
    require(set(os.listdir(root)) == {"inputs"}, "Clean-room root is not fresh")
    require(set(os.listdir(input_dir)) == set(INPUT_SPECS) | {CODE_NAME}, "Input allowlist mismatch")
    require(all((input_dir / name).is_file() and not (input_dir / name).is_symlink()
                for name in (*INPUT_SPECS, CODE_NAME)), "Non-regular clean-room input")
    data = {}
    for name, (size, digest) in INPUT_SPECS.items():
        data[name] = (input_dir / name).read_bytes()
        require(len(data[name]) == size and sha256(data[name]) == digest, "Pinned source hash mismatch")
    code_hash = sha256(code_path.read_bytes())
    blank = parse_csv(data["applicability_researcher_review_packet.csv"], PACKET_FIELDS)
    completed = parse_csv(data["applicability_researcher_review_packet_completed.csv"], PACKET_FIELDS)
    mapping = parse_csv(data["opaque_review_id_mapping.csv"], MAPPING_FIELDS)
    scenarios = freeze_researcher_decisions(blank, completed, mapping)
    decision_distribution = distributions(scenarios)
    # V1 flags cannot influence the preceding independent freeze.
    v1 = parse_v1(data["condition_applicability_v1.jsonl"])
    conditions = expand_conditions(scenarios, condition_identities(v1))
    diff = mechanical_diff(v1, conditions)
    scenario_fields = ("scenario_id", *RESEARCHER_CRITERIA, "MATERIAL_LAD_PAGES")
    scenario_csv = [{"scenario_id": row["scenario_id"],
                     **{c: str(row["criteria"][c]).lower() for c in RESEARCHER_CRITERIA},
                     "MATERIAL_LAD_PAGES": "|".join(row["material_lad_pages"])} for row in scenarios]
    condition_fields = ("scenario_id", "mode", *CRITERIA, "MATERIAL_LAD_PAGES")
    condition_csv = [{"scenario_id": row["scenario_id"], "mode": row["mode"],
                     **{c: str(row["criteria"][c]).lower() for c in CRITERIA},
                     "MATERIAL_LAD_PAGES": "|".join(row["material_lad_pages"])} for row in conditions]
    payloads = {
        "scenario_decisions_v2.jsonl": jsonl_bytes(scenarios),
        "scenario_decisions_v2.csv": csv_bytes(scenario_fields, scenario_csv),
        "condition_applicability_v2.jsonl": jsonl_bytes(conditions),
        "condition_applicability_v2.csv": csv_bytes(condition_fields, condition_csv),
        "applicability_v1_v2_diff.json": json_bytes(diff),
        "applicability_distributions.json": json_bytes(decision_distribution),
        "source_validation.json": json_bytes({
            "blank_rows": 62, "completed_rows": 62, "unique_opaque_review_ids": 62,
            "unauthorized_source_field_changes": 0, "nonempty_distinct_notes": 62,
            "material_page_selections_valid": True, "attestation_hash_valid": True,
            "schema_validation": "exact fields, including nested V1 records; no unknown fields",
            "source_hashes": {name: {"bytes": len(value), "sha256": sha256(value)}
                              for name, value in sorted(data.items())},
            "candidate_response_accessed_marker": "false boolean only; no response content",
            "score_bearing_inputs": 0, "candidate_response_inputs": 0, "human_rating_inputs": 0}),
        "mapping_metadata.json": json_bytes({
            "opaque_mapping_sha256": INPUT_SPECS["opaque_review_id_mapping.csv"][1],
            "mapping_rows": 62, "unique_review_ids": 62, "unique_scenarios": 62,
            "condition_records": 558, "conditions_per_scenario": 9,
            "semantic_identity_hash_format_valid": True,
            "join_method": "opaque_review_id_only", "query_text_matching": False,
            "hmac_key_accessed": False, "restricted_pairs_exported": False}),
    }
    boundary.outputs.mkdir(mode=0o700)
    for name in OUTPUT_NAMES:
        if name == "cleanroom_access_audit.json":
            require(boundary.reads == set(INPUT_SPECS) | {CODE_NAME}, "Unexpected input reads")
            require(boundary.writes == set(OUTPUT_NAMES) - {name}, "Unexpected output writes")
            payloads[name] = json_bytes({
                "read_files": sorted(boundary.reads), "code_sha256": code_hash,
                "completed_output_writes_before_this_audit": sorted(boundary.writes),
                "this_audit_write_mode": "exclusive creation",
                "unexpected_accesses": boundary.denied,
                "network_calls": 0, "provider_calls": 0, "subprocess_calls": 0,
                "environment_variable_reads": 0, "repository_module_imports": 0,
                "score_bearing_inputs": 0, "candidate_response_inputs": 0, "human_rating_inputs": 0,
                "old_applicability_decision_inputs": 0, "phase_b_started": False,
                "stage_order": ["source_validation", "independent_researcher_freeze",
                                "condition_identity_and_error_handling_expansion", "mechanical_v1_v2_diff"],
                "boundary": "Reads limited to six allowlisted files; writes limited to nine new outputs inside the isolated root."})
        write_once(boundary.outputs / name, payloads[name])
    require(boundary.writes == set(OUTPUT_NAMES) and boundary.denied == 0, "Final access audit failed")
    print(json.dumps({"status": "CLEANROOM_REPLAY_COMPLETE", "scenario_count": len(scenarios),
                      "condition_count": len(conditions), "code_sha256": code_hash,
                      "output_hashes": {name: sha256(value) for name, value in sorted(payloads.items())},
                      "distributions": decision_distribution, "changes": diff["summary"]}, sort_keys=True))


if __name__ == "__main__":
    try:
        run()
    except (ReplayFailure, OSError, UnicodeError, ValueError, KeyError, TypeError, csv.Error) as error:
        # Do not print input rows, restricted identifiers, or source contents.
        print(json.dumps({"status": "FAIL_CLOSED", "error_type": type(error).__name__}), file=sys.stderr)
        raise SystemExit(1)
