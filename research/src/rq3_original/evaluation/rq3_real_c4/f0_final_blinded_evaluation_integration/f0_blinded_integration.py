"""Offline canonical-result intake and predeclared blinded agreement only.

This module never opens a mode mapping or calls a Provider. It preserves raw
ratings and rationales. Historical nonselected attempts are projected to identity,
error, and token metadata without decoding their score/rationale values.
"""
from __future__ import annotations

import io
import json
import math
import re
import types
import zipfile
from collections import Counter, defaultdict
from pathlib import Path

import f0_controlled_access_guard as guard
from f0_common import (HERE, ROOT, BASE, PHASE_B, RESTRICTED, DOWNLOADS, CRITERIA, FIELDS,
                       VISIBLE_FIELDS, RETAIN, KEEP, KEEP_NA, TO_NA, AMEND, MODEL,
                       canonical, digest, csv_rows, jsonl_rows, require, embedded_request)

PROTOCOL = ROOT / "evaluation/rq3_v2/rq3_0b4_evaluation_protocol"
TOKEN_FIELDS = ("prompt_tokens", "completion_tokens", "total_tokens", "cached_input_tokens")
IDENTITY_FIELDS = ("logical_judge_request_id", "judge_result_blind_id", "provider_payload_sha256")
ATTEMPT_METADATA_FIELDS = ("event", "logical_order", *IDENTITY_FIELDS, "attempt_number", "request_started_at_utc",
                           "response_finished_at_utc", "returned_model", "finish_reason", "provider_response_id",
                           "failure_code", *TOKEN_FIELDS)
COMPLEX_VISIBLE_FIELDS = set(VISIBLE_FIELDS) - {"student_query", "current_lad_page", "candidate_response"}


class Sources:
    def __init__(self):
        self.entry = guard.verify_entry()
        self.cache = {}
        self.catalog = {r["path"]: r for r in json.loads(guard.CATALOG.read_bytes())["sources"]}

    def raw(self, path, use="source_structure_and_identity"):
        path = Path(path).resolve()
        if path not in self.cache:
            self.cache[path] = guard.read_source(path, use)
        return self.cache[path]

    def metadata(self, name):
        return json.loads(self.raw(PHASE_B / name))

    def metadata_rows(self, path):
        return [guard.project_json_object(line, ATTEMPT_METADATA_FIELDS, require_all=False)
                for line in self.raw(path, "historical_usage_accounting").splitlines() if line.strip()]

    def selected_line(self, path, number):
        lines = self.raw(path, "canonical_result_validation").splitlines()
        require(1 <= number <= len(lines), "SELECTED_SOURCE_LINE_OUT_OF_RANGE")
        return json.loads(lines[number - 1])

    def sha(self, path):
        return self.catalog[str(Path(path).resolve())]["sha256"]

    def parser(self):
        path = PHASE_B / "package_support/judge_result_parser_v3.py"
        module = types.ModuleType("f0_frozen_parser_v3")
        exec(compile(self.raw(path, "frozen_protocol_loading"), str(path), "exec"), module.__dict__)
        return module

    def agreement_functions(self):
        # The helper's only relative dependency is a pure constant builder.
        # Executing its unchanged source in a private package avoids repository
        # top-level import side effects while retaining every frozen formula.
        import sys
        package = types.ModuleType("f0_frozen_agreement_protocol")
        package.__path__ = []
        sys.modules[package.__name__] = package
        builder = types.ModuleType(package.__name__ + ".rq3_judge_request_builder")
        path = PROTOCOL / "rq3_judge_request_builder.py"
        exec(compile(self.raw(path, "frozen_protocol_loading"), str(path), "exec"), builder.__dict__)
        sys.modules[builder.__name__] = builder
        module = types.ModuleType(package.__name__ + ".rq3_human_agreement")
        module.__package__ = package.__name__
        path = PROTOCOL / "rq3_human_agreement.py"
        exec(compile(self.raw(path, "frozen_protocol_loading"), str(path), "exec"), module.__dict__)
        require(tuple(builder.PRIMARY_CRITERIA) == CRITERIA, "FROZEN_CRITERIA_DIFFER")
        return module


def visible_from_judge(blind):
    fields = {
        "student_query": blind["student_query"], "current_lad_page": blind["current_lad_page"],
        "visible_conversation_history": blind["visible_conversation_history"],
        "condition_visible_dashboard_evidence": blind["frozen_dashboard_evidence"],
        "condition_visible_course_evidence": blind["course_evidence_available_in_condition"],
        "condition_visible_learner_memory": blind["long_term_memory_available_in_condition"],
        "condition_visible_planning_support": blind["planning_support_available_in_condition"],
        "candidate_response": blind["candidate_response"],
        "applicability_flags": blind["frozen_applicability_map"]["criteria"],
    }
    return {k: canonical(v).decode() if k in COMPLEX_VISIBLE_FIELDS or k == "applicability_flags" else v for k, v in fields.items()}


def require_blinded_structure(value):
    forbidden = {"scenario_id", "scenario", "mode", "mode_id", "condition_id", "condition_name", "replay_record_id",
                 "experimental_condition", "route", "route_signature", "expected_winner", "writer_id", "family_id"}
    if isinstance(value, dict):
        require(not set(value).intersection(forbidden), "HIDDEN_IDENTITY_IN_TRACKED_RESULT")
        for item in value.values():
            require_blinded_structure(item)
    elif isinstance(value, list):
        for item in value:
            require_blinded_structure(item)


def validate_usage_row(row):
    for name in TOKEN_FIELDS:
        value = row.get(name)
        require(value is None or type(value) is int and value >= 0, "USAGE_TOKEN_DOMAIN_INVALID")
    if all(row.get(k) is not None for k in ("prompt_tokens", "completion_tokens", "total_tokens")):
        require(row["prompt_tokens"] + row["completion_tokens"] == row["total_tokens"], "USAGE_TOKEN_ARITHMETIC_INVALID")
    if row.get("cached_input_tokens") is not None and row.get("prompt_tokens") is not None:
        require(row["cached_input_tokens"] <= row["prompt_tokens"], "CACHED_TOKENS_EXCEED_INPUT")


def usage_totals(rows):
    for row in rows:
        validate_usage_row(row)
    return {"observations": len(rows),
            "known_token_totals": {name: sum(r[name] for r in rows if r.get(name) is not None) for name in TOKEN_FIELDS},
            "unknown_token_observations": {name: sum(r.get(name) is None for r in rows) for name in TOKEN_FIELDS}}


def intake_judges(source):
    parser = source.parser()
    registry = jsonl_rows(source.raw(PHASE_B / "c4_real_corrected_judge_request_registry_v1.jsonl"))
    require(len(registry) == 149, "CORRECTED_REQUEST_REGISTRY_COUNT")
    by_id = {r["logical_judge_request_id"]: r for r in registry}
    require(len(by_id) == len({r["judge_result_blind_id"] for r in registry}) == 149, "DUPLICATE_CORRECTED_IDENTITY")
    payload_rows = jsonl_rows(source.raw(RESTRICTED / "c4_real_corrected_judge_unique_payloads_r4_v1.jsonl"))
    payloads = {r["logical_judge_request_id"]: r for r in payload_rows}
    require(set(payloads) == set(by_id) and len(payload_rows) == 149, "CORRECTED_PAYLOAD_COVERAGE")
    full_payloads, blind_requests = {}, {}
    for identity, row in payloads.items():
        metadata = by_id[identity]
        require(all(row.get(k) == metadata[k] for k in (*IDENTITY_FIELDS, "eligibility_class", "shard_id", "logical_order")), "REGISTRY_PAYLOAD_IDENTITY_MISMATCH")
        full_payloads[identity] = canonical(row["provider_payload"])
        require(digest(full_payloads[identity]) == row["provider_payload_sha256"], "PROVIDER_PAYLOAD_HASH_MISMATCH")
        require(row["provider_payload"]["model"] == MODEL, "REQUESTED_MODEL_MISMATCH")
        blind = embedded_request(row["provider_payload"])
        require(blind["response_blind_id"] == row["judge_result_blind_id"], "EMBEDDED_RESULT_IDENTITY_MISMATCH")
        amap = parser.validate_applicability_map(blind["frozen_applicability_map"])
        require(amap["applicability_sha256"] == metadata["corrected_applicability_sha256"], "CORRECTED_APPLICABILITY_MISMATCH")
        blind_requests[identity] = blind
    require(len(set(full_payloads.values())) == len({r["provider_payload_sha256"] for r in registry}) == 149, "UNEQUAL_PAYLOAD_SHARING_OR_DUPLICATE_REQUEST")
    policy = json.loads((HERE / "C4_REAL_FINAL_JUDGE_SOURCE_ACCEPTANCE_POLICY_V1.json").read_bytes())
    eligibility = source.metadata("c4_real_judge_result_eligibility_after_applicability_v2.json")
    retained = [r for r in eligibility["existing_result_dispositions"] if r["corrected_primary_disposition"] == "RETAIN_UNCHANGED"]
    require(retained == policy["retained_existing_sources"], "FROZEN_RETAINED_SOURCES_RESELECTED")
    retained_ids = {r["logical_judge_request_id"] for r in retained}
    require(retained_ids == {r["logical_judge_request_id"] for r in registry if r["eligibility_class"] == RETAIN}, "RETAINED_IDENTITIES_DIFFER_FROM_PHASE_B")
    results, sources, selected_usage = [], [], []
    selected_source_keys = set()

    def accept(raw_attempt, identity, source_identity, terminal=None, retained_record=None):
        request = by_id[identity]
        require(raw_attempt["event"] == "ATTEMPT_RETURNED", "SELECTED_SOURCE_IS_NOT_A_RETURN")
        require(all(raw_attempt[k] == request[k] for k in IDENTITY_FIELDS), "SELECTED_REQUEST_RESULT_PAYLOAD_MISMATCH")
        require(raw_attempt["returned_model"] == MODEL and raw_attempt["finish_reason"] == "stop", "SELECTED_RETURNED_MODEL_OR_FINISH_MISMATCH")
        raw_hash = digest(raw_attempt["raw_response_content"].encode())
        semantic = parser.parse_judge_result(raw_attempt["raw_response_content"], blind_requests[identity]["frozen_applicability_map"], expected_judge_result_blind_id=request["judge_result_blind_id"])
        require_blinded_structure(semantic)
        if raw_attempt.get("parsed_semantic_result") is not None:
            require(semantic == raw_attempt["parsed_semantic_result"], "EXISTING_PARSED_SCORE_OR_RATIONALE_CHANGED")
        if retained_record is not None:
            require(raw_hash == retained_record["raw_output_sha256"], "RETAINED_RAW_OUTPUT_IDENTITY_MISMATCH")
            require(raw_attempt["attempt_number"] == retained_record["selected_attempt_number"], "RETAINED_ATTEMPT_CHANGED")
        else:
            require(raw_attempt.get("failure_code") is None, "CORRECTED_SELECTED_ATTEMPT_HAS_UNRESOLVED_ERROR")
        if terminal is not None:
            require(all(terminal[k] == raw_attempt[k] for k in (*IDENTITY_FIELDS, "returned_model", "provider_response_id")), "TERMINAL_RETURN_IDENTITY_MISMATCH")
            require(terminal["parsed_semantic_result"] == semantic, "TERMINAL_PARSED_RESULT_CHANGED")
            require(all(terminal.get(k) == raw_attempt.get(k) for k in TOKEN_FIELDS), "TERMINAL_USAGE_DIFFERS_FROM_RETURN")
        require(semantic["overall_applicable_mean"] == parser.recompute_overall_applicable_mean(semantic, blind_requests[identity]["frozen_applicability_map"]), "LOCAL_MEAN_MISMATCH")
        require(all(isinstance(v, str) and v.strip() for v in semantic["criterion_rationales"].values()), "EMPTY_JUDGE_RATIONALE")
        source_identity = {**source_identity, "raw_output_sha256": raw_hash,
                           "provider_response_id": raw_attempt["provider_response_id"],
                           "attempt_number": raw_attempt["attempt_number"]}
        key = (source_identity["attempt_journal_path"], source_identity["source_line"])
        require(key not in selected_source_keys, "CANONICAL_SOURCE_OVERLAP")
        selected_source_keys.add(key)
        record = {"schema_version": "c4-real-corrected-judge-result-frozen-v1", **{k: request[k] for k in IDENTITY_FIELDS},
                  "frozen_applicability_map": blind_requests[identity]["frozen_applicability_map"],
                  "parsed_semantic_result": semantic, "returned_model": raw_attempt["returned_model"],
                  "semantic_result_sha256": digest(canonical(semantic)), "source_identity": source_identity}
        require_blinded_structure(record)
        results.append(record)
        sources.append({"logical_judge_request_id": identity, "judge_result_blind_id": request["judge_result_blind_id"],
                        "provider_payload_sha256": request["provider_payload_sha256"],
                        "corrected_applicability_sha256": request["corrected_applicability_sha256"],
                        "semantic_result_sha256": record["semantic_result_sha256"],
                        "frozen_record_sha256": digest(canonical(record)), "source_identity": source_identity,
                        "parser_v3_valid": True, "score_transformation_performed": False})
        selected_usage.append({"source_identity": source_identity, **{name: raw_attempt.get(name) for name in TOKEN_FIELDS}})

    for retained_record in retained:
        identity = retained_record["logical_judge_request_id"]
        path = Path(retained_record["source_path"])
        row = source.selected_line(path, retained_record["source_line"])
        reference = retained_record["terminal_source_reference"]
        accept(row, identity, {"source_role": "retained", "attempt_journal_path": str(path.relative_to(ROOT)),
                              "attempt_journal_sha256": source.sha(path), "source_line": retained_record["source_line"],
                              "eligibility_registry_sha256": source.sha(PHASE_B / "c4_real_judge_result_eligibility_after_applicability_v2.json"),
                              "historical_terminal_reference_present": reference is not None,
                              "materialized_from_exact_phase_b_selected_attempt": True}, retained_record=retained_record)

    corrected_counts = Counter()
    corrected_source_audit = []
    for spec in policy["corrected_execution_sources"]:
        folder = ROOT / spec["execution_directory"]
        terminal_path = folder / "JUDGE_TERMINAL_JOURNAL.jsonl"
        terminal_raw = source.raw(terminal_path, "canonical_result_validation")
        require(digest(terminal_raw) == spec["terminal_journal_sha256"], "CORRECTED_TERMINAL_JOURNAL_CHANGED")
        terminals = jsonl_rows(terminal_raw)
        require(len(terminals) == spec["valid_results"], "CORRECTED_TERMINAL_COUNT_MISMATCH")
        values = [r["parsed_semantic_result"] for r in terminals]
        parsed_bytes = canonical(values) if spec["source_role"].startswith("A_") else b"".join(canonical(r) + b"\n" for r in values)
        require(digest(parsed_bytes) == spec["parsed_result_set_sha256"], "CORRECTED_PARSED_SET_IDENTITY_MISMATCH")
        attempt_path = folder / "JUDGE_ATTEMPT_JOURNAL.jsonl"
        metadata = source.metadata_rows(attempt_path)
        returned = [(n, r) for n, r in enumerate(metadata, 1) if r["event"] == "ATTEMPT_RETURNED"]
        starts = [r for r in metadata if r["event"] == "ATTEMPT_STARTED"]
        errors = [guard.project_json_object(line, ("error_category", "phase", "logical_judge_request_id"), require_all=False)
                  for line in source.raw(folder / "JUDGE_ERROR_REGISTRY.jsonl", "source_structure_and_identity").splitlines() if line.strip()]
        require(not any("RateLimit" in r.get("error_category", "") for r in errors), "CORRECTED_RATE_LIMIT_ERROR")
        require(len(returned) == len(terminals), "CORRECTED_RETURN_TERMINAL_COVERAGE_MISMATCH")
        role = spec["source_role"]
        if role == "A_historical":
            require(len(starts) == 39 and len(errors) == 1 and errors[0].get("error_category") == "KeyboardInterrupt", "HISTORICAL_A_INTERRUPTION_HISTORY_CHANGED")
            require([r["logical_order"] for r in terminals] == list(range(1, 39)), "HISTORICAL_A_ORDER_COVERAGE_CHANGED")
        else:
            require(len(starts) == len(terminals) and not errors, "CORRECTED_EXECUTION_UNRESOLVED_ERROR")
        for number, terminal in enumerate(terminals, 1):
            identity = terminal["logical_judge_request_id"]
            require(identity not in retained_ids, "CORRECTED_SOURCE_OVERLAPS_RETAINED")
            expected_shard = role[0]
            require(by_id[identity]["shard_id"] == expected_shard, "CORRECTED_SOURCE_SHARD_MISMATCH")
            if role == "A_order39":
                require(by_id[identity]["logical_order"] == 39 and folder.name == "execution_output_v2", "A_ORDER39_NOT_FROM_V2")
            else:
                require(terminal["logical_order"] == by_id[identity]["logical_order"], "CORRECTED_LOGICAL_ORDER_MISMATCH")
            matches = [(n, r) for n, r in returned if r["logical_judge_request_id"] == identity and r["provider_response_id"] == terminal["provider_response_id"]]
            require(len(matches) == 1, "CORRECTED_TERMINAL_HAS_NO_UNIQUE_RETURN")
            n, metadata_row = matches[0]
            accept(source.selected_line(attempt_path, n), identity,
                   {"source_role": role, "original_commit": spec["original_commit"],
                    "attempt_journal_path": str(attempt_path.relative_to(ROOT)), "attempt_journal_sha256": source.sha(attempt_path), "source_line": n,
                    "terminal_journal_path": str(terminal_path.relative_to(ROOT)), "terminal_journal_sha256": spec["terminal_journal_sha256"], "terminal_line": number}, terminal=terminal)
            corrected_counts[expected_shard] += 1
        corrected_source_audit.append({"source_role": role, "count": len(terminals), "terminal_journal_sha256": spec["terminal_journal_sha256"],
                                       "parsed_result_set_sha256": spec["parsed_result_set_sha256"], "integrity_status": "PASS", "rate_limit_errors": 0})
    require(corrected_counts == {"B": 38, "C": 39, "A": 39}, "CORRECTED_SHARD_TOTALS_MISMATCH")
    require(len(results) == len({r["logical_judge_request_id"] for r in results}) == len({r["judge_result_blind_id"] for r in results}) == 149, "FINAL_JUDGE_IDENTITY_COUNT_MISMATCH")
    require({r["logical_judge_request_id"] for r in results} == set(by_id), "FINAL_JUDGE_COVERAGE_MISMATCH")
    require(not set(policy["excluded_old_request_ids"]).intersection(r["logical_judge_request_id"] for r in results), "EXCLUDED_OLD_RESULT_SELECTED")
    by_result = {r["logical_judge_request_id"]: r for r in results}
    condition_rows = guard.read_projection(RESTRICTED / "c4_real_condition_to_corrected_judge_request_mapping_r4_v1.csv")
    require(len(condition_rows) == len({r["replay_record_id"] for r in condition_rows}) == 558, "CONDITION_MAPPING_COVERAGE_MISMATCH")
    condition_projection = []
    counts = Counter()
    for row in condition_rows:
        identity = row["corrected_logical_judge_request_id"]
        result, request = by_result[identity], by_id[identity]
        require(row["corrected_judge_result_blind_id"] == result["judge_result_blind_id"], "CONDITION_RESULT_ID_MISMATCH")
        require(row["corrected_provider_payload_sha256"] == digest(full_payloads[identity]), "CONDITION_UNEQUAL_PROVIDER_PAYLOAD")
        require(row["corrected_applicability_sha256"] == request["corrected_applicability_sha256"], "CONDITION_APPLICABILITY_MISMATCH")
        counts[identity] += 1
        condition_projection.append({"opaque_condition_id": row["replay_record_id"], "corrected_judge_request_id": identity,
                                     "corrected_judge_result_id": result["judge_result_blind_id"],
                                     "corrected_applicability_map_sha256": row["corrected_applicability_sha256"],
                                     "score_record": result["parsed_semantic_result"], "source_identity": result["source_identity"]})
    require(all(counts[r["logical_judge_request_id"]] == r["condition_mapping_count"] for r in registry), "CONDITION_SHARING_COUNTS_DIFFER_FROM_FROZEN_REGISTRY")
    return {"results": sorted(results, key=lambda r: r["logical_judge_request_id"]),
            "source_registry": sorted(sources, key=lambda r: r["logical_judge_request_id"]),
            "selected_usage": selected_usage, "by_id": by_result, "requests": by_id, "blind_requests": blind_requests,
            "condition_rows": condition_rows, "condition_projection": condition_projection,
            "corrected_source_audit": corrected_source_audit, "retained_sources": retained,
            "retained_without_historical_terminal": sum(r["terminal_source_reference"] is None for r in retained)}


def validate_attestations(source):
    result = {}
    for rater in "AB":
        base_name = f"human_rater_attestation_{rater}_completed(1).md"
        amend_name = f"human_amendment_attestation_{rater}_completed(1).md"
        base = source.raw(DOWNLOADS / base_name, "human_base_and_amendment_intake").decode()
        amend = source.raw(DOWNLOADS / amend_name, "human_base_and_amendment_intake").decode()
        require("Independent rating completed: **YES**" in base, "BASE_INDEPENDENCE_ATTESTATION_ABSENT")
        require(bool(re.search(r"Reviewer signature:\s*[^\n]*" + rater, base)), "BASE_SIGNATURE_ABSENT")
        require("2026-09-02" in base and "2026-09-02" in amend, "ATTESTATION_COMPLETION_DATE_ABSENT")
        if rater == "A":
            require("Generative AI was used only to draft and format" in base and "not used to make, revise, validate, compare, or replace" in base, "A_BASE_AI_DISCLOSURE_CHANGED")
            require("**Signature:**" in amend and bool(re.search(r"\*\*Signature:\*\*[^\n]*A", amend)), "A_AMENDMENT_SIGNATURE_ABSENT")
            require("I made every substantive amendment rating and wrote every criterion-specific rationale myself" in amend, "A_SUBSTANTIVE_COMPLETION_DECLARATION_ABSENT")
            require("generative AI was used only to draft and format this administrative attestation" in amend and "After I had independently completed" in amend, "A_AMENDMENT_ADMINISTRATIVE_DISCLOSURE_ABSENT")
        else:
            require("did not view, consult, copy, or otherwise use the AI-generated reference template" in base, "B_BASE_TEMPLATE_DISCLOSURE_CHANGED")
            require("Reviewer signature: Reviewer B" in amend and "Packet status: COMPLETED_AND_SIGNED" in amend, "B_AMENDMENT_SIGNATURE_ABSENT")
            require("No generative AI or AI rating template was used to make, revise or validate an amendment rating or rationale: YES" in amend, "B_SUBSTANTIVE_INDEPENDENCE_DECLARATION_ABSENT")
            require("ChatGPT was used only after all six amendment ratings and criterion-specific rationales had been independently completed" in amend, "B_ADMINISTRATIVE_DISCLOSURE_ABSENT")
        result[rater] = {
            "base_attestation_sha256": source.sha(DOWNLOADS / base_name), "amendment_attestation_sha256": source.sha(DOWNLOADS / amend_name),
            "base_and_amendment_signed": True, "independence": "SELF_ATTESTED_INDEPENDENT_COMPLETION",
            "technical_independence_verification": "NOT_CLAIMED",
            "substantive_ratings_or_rationales_ai_assisted": False,
            "base_attestation_administrative_ai": "AI used only after completion to draft/format the attestation." if rater == "A" else "No administrative AI use is stated in the base attestation; no AI reference template use for ratings/rationales is declared.",
            "amendment_attestation_administrative_ai": "AI used only after all substantive amendment ratings and rationales were independently completed to draft/format the attestation; no substantive rating or rationale assistance.",
            "completed_source_files_modified": False,
        }
    return result


def intake_humans(source, judges):
    impact = source.metadata("c4_real_human_applicability_impact_v1.json")
    require(impact["corrected_unique_visible_items"] == 44 and impact["corrected_criterion_pair_count"] == 352, "HUMAN_IMPACT_UNIVERSE_MISMATCH")
    require(impact["old_item_split_count"] == impact["old_item_merge_count"] == 0, "HUMAN_ITEM_SPLIT_OR_MERGE_NOT_AUTHORIZED")
    pairs = {(r["corrected_rating_item_id"], r["criterion"]): r for r in impact["criterion_pair_classifications"]}
    require(len(pairs) == 352, "HUMAN_IMPACT_DUPLICATE_PAIR")
    expected_counts = {KEEP: 270, KEEP_NA: 69, TO_NA: 7, AMEND: 6}
    require(dict(Counter(r["classification"] for r in pairs.values())) == expected_counts, "HUMAN_TRANSITION_COUNTS_MISMATCH")
    mappings = guard.read_projection(RESTRICTED / "c4_real_corrected_human_item_to_condition_mapping_v2.jsonl")
    amendment_links = guard.read_projection(RESTRICTED / "c4_real_human_applicability_amendment_to_condition_mapping_r1.jsonl")
    require(len(mappings) == len({r["replay_record_id"] for r in mappings}) == 108, "HUMAN_CONDITION_MAP_COVERAGE_MISMATCH")
    old_to_corrected = defaultdict(set)
    corrected_to_judge = defaultdict(set)
    corrected_to_visible_hash = defaultdict(set)
    condition_by_id = {r["replay_record_id"]: r for r in judges["condition_rows"]}
    for row in mappings:
        old_to_corrected[row["original_rating_item_id"]].add(row["corrected_rating_item_id"])
        corrected_to_judge[row["corrected_rating_item_id"]].add(condition_by_id[row["replay_record_id"]]["corrected_logical_judge_request_id"])
        corrected_to_visible_hash[row["corrected_rating_item_id"]].add(row["corrected_visible_payload_sha256"])
    require(len(old_to_corrected) == len(corrected_to_judge) == 44 and all(len(v) == 1 for v in old_to_corrected.values()), "HUMAN_IDENTITY_SPLIT_OR_MERGE")
    require(all(len(v) == 1 for v in corrected_to_judge.values()), "HUMAN_ITEM_HAS_MULTIPLE_JUDGE_RESULTS_WITHOUT_SELECTION_AUTHORITY")
    require(all(len(v) == 1 for v in corrected_to_visible_hash.values()), "HUMAN_VISIBLE_HASH_AMBIGUOUS")
    old_to_corrected = {k: next(iter(v)) for k, v in old_to_corrected.items()}
    matched_judge = {k: next(iter(v)) for k, v in corrected_to_judge.items()}
    amendment_ids = defaultdict(set)
    amendment_by_id = {}
    for row in amendment_links:
        require(row["criterion"] == "ACTIONABILITY", "AMENDMENT_WRONG_CRITERION")
        require(old_to_corrected[row["original_rating_item_id"]] == row["corrected_rating_item_id"], "AMENDMENT_BASE_ITEM_ID_MISMATCH")
        require(condition_by_id[row["replay_record_id"]]["corrected_logical_judge_request_id"] == matched_judge[row["corrected_rating_item_id"]], "AMENDMENT_CONDITION_IDENTITY_MISMATCH")
        amendment_ids[(row["corrected_rating_item_id"], row["criterion"])].add(row["amendment_item_id"])
        projection = {k: row[k] for k in ("amendment_item_id", "corrected_rating_item_id", "criterion", "original_rating_item_id")}
        require(row["amendment_item_id"] not in amendment_by_id or amendment_by_id[row["amendment_item_id"]] == projection, "AMENDMENT_ITEM_ID_COLLISION")
        amendment_by_id[row["amendment_item_id"]] = projection
    require(len(amendment_links) == 18 and len(amendment_by_id) == 6 and all(len(v) == 1 for v in amendment_ids.values()), "AMENDMENT_ID_COVERAGE_MISMATCH")
    require(set(amendment_ids) == {key for key, pair in pairs.items() if pair["classification"] == AMEND}, "AMENDMENT_IDS_DIFFER_FROM_IMPACT_REGISTRY")
    manifest = source.metadata("c4_real_human_amendment_packet_manifest_v1.json")
    attestations = validate_attestations(source)
    base_inputs, amendment_inputs, output = {}, {}, {}
    source_audit, item_matches, intake_metadata = [], {}, {}
    for rater in "AB":
        base_name = f"human_rating_packet_{rater}_completed.csv"
        base = csv_rows(source.raw(DOWNLOADS / base_name, "human_base_and_amendment_intake"))
        blank = csv_rows(source.raw(BASE / f"r3d1_response_integration_r2/human_rating_packet_{rater}_R2.csv", "human_base_and_amendment_intake"))
        require(len(base) == len(blank) == 44, "HUMAN_BASE_ROW_COUNT")
        expected_fields = {"rating_item_id", *VISIBLE_FIELDS, "applicability_flags", *(f + suffix for f in FIELDS for suffix in ("_rating", "_rationale"))}
        require(all(set(r) == expected_fields for r in base + blank), "HUMAN_BASE_COLUMN_SET_CHANGED")
        require([r["rating_item_id"] for r in base] == [r["rating_item_id"] for r in blank], "HUMAN_BASE_ROW_ORDER_CHANGED")
        require(len({r["rating_item_id"] for r in base}) == 44 and {r["rating_item_id"] for r in base} == set(old_to_corrected), "HUMAN_BASE_ITEM_SET_MISMATCH")
        originals = {r["rating_item_id"]: r for r in blank}
        for row in base:
            original = originals[row["rating_item_id"]]
            require(all(row[k] == original[k] for k in ("rating_item_id", *VISIBLE_FIELDS, "applicability_flags")), "HUMAN_VISIBLE_SOURCE_FIELD_CHANGED")
            flags = json.loads(row["applicability_flags"])
            require(set(flags) == set(CRITERIA) and all(type(v) is bool for v in flags.values()), "HUMAN_BASE_FLAGS_INVALID")
            for criterion, field in zip(CRITERIA, FIELDS):
                value, rationale = row[field + "_rating"], row[field + "_rationale"]
                require(value in {"1", "2", "3", "4", "5"} if flags[criterion] else value == "NA", "HUMAN_BASE_SCORE_NA_INVALID")
                require(bool(rationale.strip()), "HUMAN_BASE_RATIONALE_EMPTY")
        amendment_name = "human_applicability_amendment_packet_A_completed (1).csv" if rater == "A" else "human_applicability_amendment_packet_B_completed(1).csv"
        completed = csv_rows(source.raw(DOWNLOADS / amendment_name, "human_base_and_amendment_intake"))
        package_meta = manifest["packages"][rater]
        package = source.raw(Path(package_meta["path"]), "human_base_and_amendment_intake")
        with zipfile.ZipFile(io.BytesIO(package)) as archive:
            require(archive.testzip() is None and set(archive.namelist()) == set(package_meta["members"]), "HUMAN_AMENDMENT_PACKAGE_INTEGRITY")
            for name, expected in package_meta["members"].items():
                require(digest(archive.read(name)) == expected, "HUMAN_AMENDMENT_MEMBER_HASH_MISMATCH")
            blank_amendments = csv_rows(archive.read(f"human_applicability_amendment_packet_{rater}.csv"))
        require(len(completed) == len(blank_amendments) == 6, "HUMAN_AMENDMENT_ROW_COUNT")
        require([r["amendment_item_id"] for r in completed] == [r["amendment_item_id"] for r in blank_amendments], "AMENDMENT_ROW_ORDER_CHANGED")
        require({r["amendment_item_id"] for r in completed} == set(amendment_by_id), "COMPLETED_AMENDMENT_IDS_MISMATCH")
        by_amendment_id = {r["amendment_item_id"]: r for r in completed}
        for row, old in zip(completed, blank_amendments):
            require(set(row) == set(old), "AMENDMENT_COLUMNS_CHANGED")
            require(all(row[k] == old[k] for k in row if k not in {"amendment_rating", "criterion_specific_rationale"}), "AMENDMENT_VISIBLE_SOURCE_FIELD_CHANGED")
            require(row["newly_applicable_criterion"] == "ACTIONABILITY" and row["corrected_applicability"] == "true", "AMENDMENT_APPLICABILITY_INVALID")
            require(row["amendment_rating"] in {"1", "2", "3", "4", "5"} and bool(row["criterion_specific_rationale"].strip()), "AMENDMENT_SCORE_OR_RATIONALE_INVALID")
        converted = []
        transition_counts, numeric, na = Counter(), 0, 0
        for row in base:
            old_id = row["rating_item_id"]
            identity = old_to_corrected[old_id]
            judge_id = matched_judge[identity]
            flags = {c: pairs[(identity, c)]["new_applicable"] for c in CRITERIA}
            old_flags = json.loads(row["applicability_flags"])
            visible = {k: row[k] for k in VISIBLE_FIELDS}
            visible["applicability_flags"] = canonical(flags).decode()
            visible_bytes = canonical(visible)
            require(digest(visible_bytes) == next(iter(corrected_to_visible_hash[identity])), "CORRECTED_HUMAN_VISIBLE_PAYLOAD_HASH_MISMATCH")
            judge_visible = visible_from_judge(judges["blind_requests"][judge_id])
            require(visible_bytes == canonical(judge_visible), "COMPLETE_HUMAN_JUDGE_VISIBLE_PAYLOAD_MISMATCH")
            match = {"corrected_rating_item_id": identity, "corrected_judge_request_id": judge_id,
                     "corrected_judge_result_id": judges["by_id"][judge_id]["judge_result_blind_id"],
                     "complete_corrected_visible_payload_sha256": digest(visible_bytes),
                     "complete_visible_payload_byte_identical": True}
            require(identity not in item_matches or item_matches[identity] == match, "HUMAN_RATER_VISIBLE_PAYLOAD_MISMATCH")
            item_matches[identity] = match
            scores, rationales, provenance = {}, {}, {}
            for criterion, field in zip(CRITERIA, FIELDS):
                pair = pairs[(identity, criterion)]
                require(pair["old_applicable"] == old_flags[criterion], "HUMAN_IMPACT_OLD_APPLICABILITY_MISMATCH")
                transition = pair["classification"]
                expected_transition = KEEP if old_flags[criterion] and flags[criterion] else KEEP_NA if not old_flags[criterion] and not flags[criterion] else TO_NA if old_flags[criterion] else AMEND
                require(transition == expected_transition, "HUMAN_TRANSITION_CLASSIFICATION_MISMATCH")
                transition_counts[transition] += 1
                original_value, original_rationale = row[field + "_rating"], row[field + "_rationale"]
                evidence = {"transition": transition, "base_source_sha256": source.sha(DOWNLOADS / base_name), "original_rating_item_id": old_id}
                if transition == KEEP:
                    value, rationale = int(original_value), original_rationale
                elif transition == KEEP_NA:
                    value, rationale = "NA", original_rationale
                elif transition == TO_NA:
                    value, rationale = "NA", None
                    source_audit.append({"rater": rater, "corrected_rating_item_id": identity, "criterion": criterion,
                                         "transition": transition, "original_rating_item_id": old_id,
                                         "raw_source_filename": base_name, "raw_source_sha256": source.sha(DOWNLOADS / base_name),
                                         "preserved_original_score": original_value, "preserved_original_rationale": original_rationale,
                                         "corrected_semantic_value": "NA", "source_modified": False})
                else:
                    amendment_id = next(iter(amendment_ids[(identity, criterion)]))
                    amendment = by_amendment_id[amendment_id]
                    require(all(amendment[k] == row[k] for k in VISIBLE_FIELDS), "AMENDMENT_FULL_VISIBLE_CONTEXT_MISMATCH")
                    value, rationale = int(amendment["amendment_rating"]), amendment["criterion_specific_rationale"]
                    evidence.update({"amendment_item_id": amendment_id, "amendment_source_sha256": source.sha(DOWNLOADS / amendment_name)})
                require(type(value) is int and 1 <= value <= 5 if flags[criterion] else value == "NA", "CORRECTED_HUMAN_SCORE_NA_MISMATCH")
                require(not flags[criterion] or isinstance(rationale, str) and bool(rationale.strip()), "CORRECTED_HUMAN_REQUIRED_RATIONALE_EMPTY")
                scores[field], rationales[field], provenance[field] = value, rationale, evidence
                numeric += type(value) is int
                na += value == "NA"
            record = {"schema_version": "c4-real-corrected-human-rating-frozen-v1", "rater": rater,
                      "corrected_rating_item_id": identity, "corrected_visible_payload_sha256": digest(visible_bytes),
                      "applicability_flags": flags, "criterion_scores": scores, "criterion_rationales": rationales,
                      "criterion_source_provenance": provenance}
            require_blinded_structure(record)
            converted.append(record)
        require(dict(transition_counts) == expected_counts and numeric == 276 and na == 76, "CORRECTED_HUMAN_PAIR_ACCOUNTING_MISMATCH")
        base_inputs[rater], amendment_inputs[rater], output[rater] = base, completed, converted
        intake_metadata[rater] = {"base_rows": 44, "amendment_rows": 6, "unique_corrected_items": 44,
                                  "total_item_criterion_pairs": 352, "transition_counts": dict(transition_counts),
                                  "corrected_numeric_pairs": numeric, "corrected_na_pairs": na,
                                  "visible_source_fields_unchanged": True, "only_authorized_amendment_fields_changed": True,
                                  "base_order_preserved": True, "amendment_order_preserved": True,
                                  "base_source_sha256": source.sha(DOWNLOADS / base_name), "amendment_source_sha256": source.sha(DOWNLOADS / amendment_name),
                                  "attestation": attestations[rater]}
    require({r["rating_item_id"] for r in base_inputs["A"]} == {r["rating_item_id"] for r in base_inputs["B"]}, "RATER_ITEM_SETS_DIFFER")
    require([r["rating_item_id"] for r in base_inputs["A"]] != [r["rating_item_id"] for r in base_inputs["B"]], "RATER_ORDERS_NOT_DIFFERENT")
    require([r["amendment_item_id"] for r in amendment_inputs["A"]] != [r["amendment_item_id"] for r in amendment_inputs["B"]], "AMENDMENT_ORDERS_NOT_DIFFERENT")
    require(len(item_matches) == 44 and len(source_audit) == 14, "HUMAN_MATCH_OR_SOURCE_AUDIT_COVERAGE")
    # The Phase-B semantic source is compared only on already frozen retention
    # fields; no obsolete value is promoted into a corrected applicable score.
    historical = jsonl_rows(source.raw(RESTRICTED / "c4_real_corrected_human_semantic_records_v2.jsonl", "human_base_and_amendment_intake"))
    require(len(historical) == 704, "HUMAN_PHASE_B_SEMANTIC_PAIR_COUNT")
    lookup = {(rater, r["corrected_rating_item_id"]): r for rater in "AB" for r in output[rater]}
    for old in historical:
        current = lookup[(old["rater"], old["corrected_rating_item_id"])]
        field = old["criterion"].lower()
        require(old["classification"] == current["criterion_source_provenance"][field]["transition"], "PHASE_B_SEMANTIC_CLASSIFICATION_CHANGED")
        if old["classification"] in (KEEP, KEEP_NA):
            value = current["criterion_scores"][field]
            require(str(value) == old["corrected_semantic_value"] and current["criterion_rationales"][field] == old["retained_source_rationale"], "FROZEN_BASE_VALUE_OR_RATIONALE_CHANGED")
        elif old["classification"] == TO_NA:
            require(old["corrected_semantic_value"] == "NA" and old["retained_source_rationale"] is None, "PHASE_B_TO_NA_SEMANTICS_CHANGED")
        else:
            require(old["corrected_semantic_value"] is None and old["retained_source_rationale"] is None, "PHASE_B_PENDING_AMENDMENT_NOT_EMPTY")
    return {"ratings": output, "intake_metadata": intake_metadata, "source_audit": source_audit,
            "item_matches": sorted(item_matches.values(), key=lambda r: r["corrected_rating_item_id"]),
            "amendment_ids": sorted(amendment_by_id), "same_item_set": True, "different_orders": True}


def calculate_pair_metrics(left, right, helper, *, human_llm, pooled):
    require(len(left) == len(right), "AGREEMENT_PAIR_LENGTH_MISMATCH")
    if not left:
        return {"n": 0, "status": "NOT_ESTIMABLE_NO_JOINTLY_APPLICABLE_PAIRS"}
    require(all(type(v) is int and 1 <= v <= 5 for v in left + right), "AGREEMENT_INPUT_DOMAIN_MISMATCH")
    n = len(left)
    exact = sum(a == b for a, b in zip(left, right))
    within = sum(abs(a - b) <= 1 for a, b in zip(left, right))
    metrics = {"n": n, "quadratic_weighted_kappa": helper.quadratic_weighted_kappa(left, right),
               "spearman_correlation": helper.spearman_correlation(left, right),
               "exact_agreement": exact / n, "within_one_point_agreement": within / n,
               "exact_agreement_numerator": exact, "within_one_point_numerator": within,
               "disagreement_count": n - exact, "disagreement_over_one_point_count": n - within}
    if human_llm:
        metrics["mean_absolute_score_difference"] = sum(abs(b - a) for a, b in zip(left, right)) / n
        if not pooled:
            metrics["criterion_level_bias_source_b_minus_source_a"] = sum(b - a for a, b in zip(left, right)) / n
    statuses = {}
    for name in ("quadratic_weighted_kappa", "spearman_correlation"):
        if metrics[name] is None:
            statuses[name] = "NOT_ESTIMABLE_ZERO_EXPECTED_DISAGREEMENT" if name == "quadratic_weighted_kappa" else "NOT_ESTIMABLE_ZERO_VARIANCE"
    if statuses:
        metrics["undefined_metric_statuses"] = statuses
    return metrics


def pair_agreement(left, right, helper, *, human_llm):
    require(set(left) == set(right), "AGREEMENT_UNIQUE_ITEM_SET_MISMATCH")
    pooled_left, pooled_right, per_criterion = [], [], {}
    for field in FIELDS:
        values_left, values_right = [], []
        for identity in sorted(left):
            a, b = left[identity][field], right[identity][field]
            if a == b == "NA":
                continue
            require(a != "NA" and b != "NA", "AGREEMENT_APPLICABILITY_MISMATCH")
            values_left.append(a)
            values_right.append(b)
        per_criterion[field] = calculate_pair_metrics(values_left, values_right, helper, human_llm=human_llm, pooled=False)
        pooled_left.extend(values_left)
        pooled_right.extend(values_right)
    return {"per_criterion": per_criterion, "pooled": calculate_pair_metrics(pooled_left, pooled_right, helper, human_llm=human_llm, pooled=True),
            "pooling_rule": "Concatenate each jointly applicable criterion-item pair once per named source pairing; exclude NA."}


def blinded_agreement(source, humans, judges):
    helper = source.agreement_functions()
    human = {rater: {r["corrected_rating_item_id"]: r["criterion_scores"] for r in humans["ratings"][rater]} for rater in "AB"}
    judge = {m["corrected_rating_item_id"]: {f: judges["by_id"][m["corrected_judge_request_id"]]["parsed_semantic_result"][f] for f in FIELDS} for m in humans["item_matches"]}
    require(len(judge) == len(human["A"]) == len(human["B"]) == 44, "AGREEMENT_NOT_44_UNIQUE_ITEMS")
    hh = pair_agreement(human["A"], human["B"], helper, human_llm=False)
    hh.update({"schema_version": "c4-real-blinded-human-human-agreement-v1", "unique_items": 44,
               "human_raters": 2, "condition_level_duplicates_counted_as_observations": 0,
               "not_computed": {"mean_absolute_score_difference": "NOT_COMPUTED_PROTOCOL_UNDERSPECIFIED",
                                "human_human_bias": "NOT_COMPUTED_PROTOCOL_UNDERSPECIFIED"},
               "score_rewriting_performed": False, "mode_identity_accessed": False})
    hl = {"schema_version": "c4-real-blinded-human-llm-agreement-v1", "unique_items": 44, "human_raters": 2,
          "human_a_vs_llm_judge": pair_agreement(human["A"], judge, helper, human_llm=True),
          "human_b_vs_llm_judge": pair_agreement(human["B"], judge, helper, human_llm=True),
          "condition_level_duplicates_counted_as_observations": 0,
          "not_computed": {"pooled_bias": "NOT_COMPUTED_PROTOCOL_UNDERSPECIFIED"},
          "complete_visible_payload_identity_verified": True, "score_rewriting_performed": False, "mode_identity_accessed": False}
    pooled_humans = {(rater, item): scores for rater in "AB" for item, scores in human[rater].items()}
    pooled_judges = {(rater, item): scores for rater in "AB" for item, scores in judge.items()}
    hl["pooled_human_observations_vs_llm_judge"] = pair_agreement(pooled_humans, pooled_judges, helper, human_llm=True)
    require(hh["pooled"]["n"] == hl["human_a_vs_llm_judge"]["pooled"]["n"] == hl["human_b_vs_llm_judge"]["pooled"]["n"] == 276, "AGREEMENT_APPLICABLE_DENOMINATOR_MISMATCH")
    require(hl["pooled_human_observations_vs_llm_judge"]["pooled"]["n"] == 552, "POOLED_HUMAN_OBSERVATIONS_MISMATCH")
    return hh, hl


def historical_usage(source, judges):
    attempt_paths = sorted(Path(path) for path, record in source.catalog.items() if record["source_role"] == "judge_attempt_journal")
    all_returned, unknown, api_errors, per_execution = [], [], [], []
    selected_keys = {(r["source_identity"]["attempt_journal_path"], r["source_identity"]["source_line"]) for r in judges["selected_usage"]}
    selected_returns_seen = set()
    excluded_returned = []
    total_started = 0
    for path in attempt_paths:
        metadata = source.metadata_rows(path)
        key = lambda row: (row["logical_judge_request_id"], row["attempt_number"])
        starts = {key(row): row for row in metadata if row["event"] == "ATTEMPT_STARTED"}
        returned = {key(row): (number, row) for number, row in enumerate(metadata, 1) if row["event"] == "ATTEMPT_RETURNED"}
        require(len(starts) == sum(row["event"] == "ATTEMPT_STARTED" for row in metadata), "HISTORICAL_ATTEMPT_IDENTITY_DUPLICATE")
        require(len(returned) == sum(row["event"] == "ATTEMPT_RETURNED" for row in metadata), "HISTORICAL_RETURN_IDENTITY_DUPLICATE")
        require(set(returned) <= set(starts), "HISTORICAL_RETURN_WITHOUT_START")
        total_started += len(starts)
        returned_values = [row for number, row in returned.values()]
        all_returned.extend(returned_values)
        for number, row in returned.values():
            source_key = (str(path.relative_to(ROOT)), number)
            if source_key in selected_keys:
                selected_returns_seen.add(source_key)
            else:
                excluded_returned.append(row)
        error_path = path.parent / "JUDGE_ERROR_REGISTRY.jsonl"
        errors = [guard.project_json_object(line, ("error_category", "phase", "logical_judge_request_id", "attempt_number"), require_all=False)
                  for line in source.raw(error_path, "historical_usage_accounting").splitlines() if line.strip()]
        missing = set(starts) - set(returned)
        for attempt_key in sorted(missing):
            start = starts[attempt_key]
            matching_errors = [r for r in errors if r.get("logical_judge_request_id") in (None, start["logical_judge_request_id"]) and r.get("phase") == "PROVIDER_CALL"]
            categories = sorted({r["error_category"] for r in matching_errors})
            record = {"attempt_journal_path": str(path.relative_to(ROOT)), "attempt_journal_sha256": source.sha(path),
                      "logical_judge_request_id": start["logical_judge_request_id"], "attempt_number": start["attempt_number"],
                      "provider_payload_sha256": start["provider_payload_sha256"], "error_categories": categories,
                      "judge_result": False, "known_token_usage": None, "provider_billing": "UNOBSERVED"}
            if categories == ["RateLimitError"]:
                record["outcome_status"] = "RECORDED_API_REJECTION_NO_JUDGE_RESULT"
                record["error_subtype"] = "NOT_INFERRED_FROM_DURABLE_CATEGORY"
                api_errors.append(record)
            else:
                record["outcome_status"] = "UNKNOWN_PROVIDER_COMPLETION_AND_BILLING"
                unknown.append(record)
        per_execution.append({"execution_directory": str(path.parent.relative_to(ROOT)), "physical_attempts_started": len(starts),
                              "returned_output_count": len(returned), "unreturned_attempt_count": len(missing),
                              "known_returned_usage": usage_totals(returned_values), "error_categories": dict(Counter(r.get("error_category", "UNKNOWN") for r in errors))})
    require(selected_returns_seen == selected_keys and len(selected_keys) == 149, "CANONICAL_USAGE_SOURCE_COVERAGE_MISMATCH")
    require(any("j4a_corrected_judge_shard_a/execution_output_v1" in r["attempt_journal_path"] and "KeyboardInterrupt" in r["error_categories"] for r in unknown), "INTERRUPTED_A_UNKNOWN_OUTCOME_NOT_DISCLOSED")
    return {"schema_version": "F0_JUDGE_USAGE_ACCOUNTING_V1", "canonical_corrected_results": usage_totals(judges["selected_usage"]),
            "all_historical_returned_outputs": usage_totals(all_returned), "noncanonical_returned_outputs": usage_totals(excluded_returned),
            "physical_attempts_started": total_started, "all_returned_output_count": len(all_returned),
            "unknown_provider_outcome_attempts": unknown, "recorded_api_rejections_without_result": api_errors,
            "per_execution": per_execution, "usage_multiplier_from_condition_mappings": 1,
            "condition_mapping_count": 558, "canonical_result_count": 149,
            "historical_usage_scope": "All eleven frozen execution histories, including invalid returned outputs, excluded old results, and redundant returned attempts; each physical return counted once.",
            "unknown_usage_imputed": False, "provider_billed_cost": None,
            "cost_status": "NOT_COMPUTED_NO_FROZEN_PRICE_SCHEDULE_AND_UNOBSERVED_BILLING_OUTCOMES",
            "known_token_totals_are_incomplete_for_unknown_outcomes": True,
            "new_provider_calls": 0}


def collect():
    source = Sources()
    judges = intake_judges(source)
    humans = intake_humans(source, judges)
    hh, hl = blinded_agreement(source, humans, judges)
    usage = historical_usage(source, judges)
    require(not guard.NETWORK_DENIALS, "UNEXPECTED_NETWORK_OR_SUBPROCESS_ATTEMPT")
    return {"judges": judges, "humans": humans, "human_human": hh, "human_llm": hl, "usage": usage}


if __name__ == "__main__":
    guard.install_offline_guard()
    data = collect()
    print(json.dumps({"status": "OFFLINE_BLINDED_INTAKE_VALIDATED", "judge_results": len(data["judges"]["results"]),
                      "condition_mappings": len(data["judges"]["condition_projection"]),
                      "human_items_per_rater": {r: len(data["humans"]["ratings"][r]) for r in "AB"},
                      "human_numeric_pairs": {r: data["humans"]["intake_metadata"][r]["corrected_numeric_pairs"] for r in "AB"},
                      "mode_identity_accesses": 0, "provider_calls": 0}))
