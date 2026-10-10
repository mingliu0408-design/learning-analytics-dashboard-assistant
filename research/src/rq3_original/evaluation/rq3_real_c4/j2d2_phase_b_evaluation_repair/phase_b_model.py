"""Offline applicability repair. No outcome aggregation or network operations."""

from __future__ import annotations

import copy
import hmac
import json
import math
import re
import types
from collections import Counter, defaultdict

from phase_b_sources import canonical, digest, jsonl_rows, require

RETAIN = "RETAIN_EXISTING_RESULT_UNCHANGED_APPLICABILITY"
REJUDGE = "REJUDGE_EXISTING_RESULT_CHANGED_APPLICABILITY"
NEW = "JUDGE_PREVIOUSLY_UNATTEMPTED"
FAILED = "JUDGE_PREVIOUSLY_FAILED_NO_VALID_RESULT"
KEEP = "UNCHANGED_APPLICABLE_KEEP_EXISTING_RATING"
KEEP_NA = "UNCHANGED_NOT_APPLICABLE_KEEP_NA"
TO_NA = "OLD_APPLICABLE_NEW_NOT_APPLICABLE_EXCLUDE_OLD_AND_SET_NA"
AMEND = "OLD_NOT_APPLICABLE_NEW_APPLICABLE_REQUIRES_BLIND_AMENDMENT"
CRITERIA = ("CLARITY", "PERSONALISATION", "ACTIONABILITY", "CONTEXT_AWARENESS",
            "MOTIVATION_AND_ENGAGEMENT", "RELIABILITY", "MULTI_PAGE_COHESIVENESS", "ERROR_HANDLING")
JUDGE_DOMAIN = "C4_REAL_JUDGE_APPLICABILITY_V2_R4"
HUMAN_DOMAIN = "C4_REAL_HUMAN_APPLICABILITY_AMENDMENT_R1"
SEED = 20260902
BEGIN = "BEGIN_BLIND_JUDGE_REQUEST_JSON\n"
END = "\nEND_BLIND_JUDGE_REQUEST_JSON"
VISIBLE_FIELDS = ("student_query", "current_lad_page", "visible_conversation_history",
                  "condition_visible_dashboard_evidence", "condition_visible_course_evidence",
                  "condition_visible_learner_memory", "condition_visible_planning_support", "candidate_response")


def opaque(key: bytes, domain: str, purpose: str, payload: bytes, prefix: str, length: int):
    message = domain.encode() + b"\0" + purpose.encode() + b"\0" + payload
    return prefix + hmac.new(key, message, "sha256").hexdigest()[:length].upper()


def embedded(payload):
    text = payload["messages"][0]["content"]
    require(text.count(BEGIN) == text.count(END) == 1, "Embedded request boundary mismatch")
    raw = text.split(BEGIN, 1)[1].rsplit(END, 1)[0]
    value = json.loads(raw)
    require(canonical(value).decode() == raw, "Original embedded JSON bytes are not the frozen canonical encoding")
    return value


def replace_embedded(payload, **fields):
    """Change only designated JSON values, preserving all other content bytes."""
    result = copy.deepcopy(payload)
    original = embedded(payload)
    changed = {**original, **copy.deepcopy(fields)}
    original_text = canonical(original).decode()
    text = payload["messages"][0]["content"]
    prefix, rest = text.split(BEGIN, 1)
    body, suffix = rest.rsplit(END, 1)
    require(body == original_text, "Embedded JSON boundary changed")
    result["messages"][0]["content"] = prefix + BEGIN + canonical(changed).decode() + END + suffix
    require({k: v for k, v in embedded(result).items() if k not in fields} ==
            {k: v for k, v in original.items() if k not in fields}, "Substantive payload changed")
    return result


def estimated_tokens(payload):
    size = sum(len(canonical(message)) for message in payload["messages"])
    return math.ceil((size + len(canonical(payload["response_format"])) + 16) / 4)


def parser_without_aggregation(source: bytes):
    """Use exact V3 validation with its aggregate callback replaced by checks.

    The frozen parser file is never modified. This private in-memory module
    preserves every score-domain/NA rejection in the original aggregate helper,
    but neither adds nor divides scores. Its transient None aggregate is never
    serialized as a repaired result, and no historical result is rewritten.
    """
    require(digest(source) == "7d54f39fd3b4452e11151d736aaac616c661c2c7cc9ca725573191d4d2f9e4fb", "Parser V3 source changed")
    module = types.ModuleType("phase_b_private_parser_v3_validity_only")
    exec(compile(source, "<manifest-bound-judge-parser-v3>", "exec"), module.__dict__)

    def validate_scores_without_mean(scores, applicability_map):
        applicability = module.validate_applicability_map(applicability_map)
        for criterion in module.PRIMARY_CRITERIA:
            value = scores.get(module.SCORE_FIELDS[criterion])
            if applicability["criteria"][criterion]:
                if type(value) is not int or not 1 <= value <= 5:
                    raise module.JudgeResultError("APPLICABILITY_CONTRACT_VIOLATION: applicable score domain")
            elif value != "NA":
                raise module.JudgeResultError("APPLICABILITY_CONTRACT_VIOLATION: nonapplicable criterion must be NA")
        return None

    module.recompute_overall_applicable_mean = validate_scores_without_mean
    return module


def historical_judge_eligibility(data):
    requests = {r["logical_judge_request_id"]: r for r in data["requests"]}
    require(len(requests) == len(data["requests"]), "Duplicate original request ID")
    original_orders = {}
    for shard, members in data["old_packages"].items():
        rows = jsonl_rows(members["BLINDED_JUDGE_REQUESTS.jsonl"])
        require(len(rows) == 49, "Original shard request count mismatch")
        for position, row in enumerate(rows, 1):
            original = requests[row["logical_judge_request_id"]]
            require(canonical(row["provider_payload"]) == canonical(original["provider_payload"]), "Original package/manifest payload mismatch")
            require(row["judge_result_blind_id"] == original["judge_result_blind_id"], "Original result ID mismatch")
            require(embedded(row["provider_payload"])["response_blind_id"] == row["judge_result_blind_id"], "Original embedded result identity mismatch")
            require(digest(canonical(row["provider_payload"])) == row["provider_payload_sha256"] == original["provider_payload_sha256"], "Original payload commitment mismatch")
            original_orders[row["logical_judge_request_id"]] = (shard, position)
    parser = parser_without_aggregation(data["support"]["judge_result_parser_v3.py"])
    candidates = defaultdict(list)
    attempted = set()
    invalid = []
    terminal_records = {}
    history_counts = []
    for source in data["execution_sources"]:
        attempts = jsonl_rows(source["files"]["JUDGE_ATTEMPT_JOURNAL.jsonl"])
        terminals = jsonl_rows(source["files"]["JUDGE_TERMINAL_JOURNAL.jsonl"])
        attempts_path = str(source["directory"] / source["output_folder"] / "JUDGE_ATTEMPT_JOURNAL.jsonl")
        terminals_path = str(source["directory"] / source["output_folder"] / "JUDGE_TERMINAL_JOURNAL.jsonl")
        for number, row in enumerate(attempts, 1):
            logical_id = row["logical_judge_request_id"]
            original = requests[logical_id]
            require(row["judge_result_blind_id"] == original["judge_result_blind_id"], "Attempt result ID mismatch")
            require(row["provider_payload_sha256"] == original["provider_payload_sha256"], "Attempt payload mismatch")
            require((source["shard"], row["logical_order"]) == original_orders[logical_id], "Attempt original order mismatch")
            attempted.add(logical_id)
            if row["event"] != "ATTEMPT_RETURNED":
                continue
            require(source["scientific"], "Billing-only history unexpectedly contains a returned scientific output")
            try:
                require(row["returned_model"] == "gpt-4.1-2025-04-14" and row["finish_reason"] == "stop", "Returned model/finish reason mismatch")
                semantic = parser.parse_judge_result(row["raw_response_content"], embedded(original["provider_payload"])["frozen_applicability_map"],
                                                     expected_judge_result_blind_id=original["judge_result_blind_id"])
                require(semantic["overall_applicable_mean"] is None, "Aggregate computation was not disabled")
            except parser.JudgeResultError as exc:
                invalid.append({"logical_judge_request_id": logical_id, "attempt_number": row["attempt_number"],
                                "source_path": attempts_path, "source_line": number,
                                "failure_code": parser.retryable_failure_code(exc),
                                "raw_output_sha256": digest(row["raw_response_content"].encode())})
                continue
            if row.get("parsed_semantic_result") is not None:
                existing = row["parsed_semantic_result"]
                require({k: v for k, v in existing.items() if k != "overall_applicable_mean"} ==
                        {k: v for k, v in semantic.items() if k != "overall_applicable_mean"}, "Existing parsed values differ from V3 validity parse")
            candidates[logical_id].append({
                "logical_judge_request_id": logical_id, "judge_result_blind_id": row["judge_result_blind_id"],
                "provider_payload_sha256": row["provider_payload_sha256"], "original_shard": source["shard"],
                "original_logical_order": row["logical_order"], "selected_attempt_number": row["attempt_number"],
                "source_rank": source["source_rank"], "source_path": attempts_path, "source_line": number,
                "raw_output_sha256": digest(row["raw_response_content"].encode()), "parser_v3_passed": True,
                "score_aggregate_computed": False, "score_values_or_rationales_in_record": False,
            })
        for number, row in enumerate(terminals, 1):
            logical_id = row["logical_judge_request_id"]
            original = requests[logical_id]
            require(source["scientific"] and logical_id in candidates, "Terminal lacks a valid raw V3 source")
            require(row["judge_result_blind_id"] == original["judge_result_blind_id"], "Terminal result ID mismatch")
            require(row["provider_payload_sha256"] == original["provider_payload_sha256"], "Terminal payload mismatch")
            require(row["parsed_semantic_result"]["response_blind_id"] == original["judge_result_blind_id"], "Parsed semantic ID mismatch")
            terminal_records[logical_id] = {"path": terminals_path, "line": number,
                                            "existing_parsed_result_sha256": digest(canonical(row["parsed_semantic_result"]))}
        if source["directory"].name == "j3b_judge_continuation_b" and source["output_folder"] == "execution_output_v2":
            require(digest(source["files"]["JUDGE_TERMINAL_JOURNAL.jsonl"]) == "c7cdcb0124aaa1a1f2137f2e17dac48c075cc1c888fbe92305bcf6f90642a268", "B V2 terminal commitment mismatch")
            projection = [{k: r[k] for k in ("logical_order", "logical_judge_request_id", "judge_result_blind_id", "parsed_semantic_result")}
                          for r in sorted(terminals, key=lambda row: row["logical_order"])]
            require(digest(canonical(projection)) == "b51928e34e693464cf3dc421404108fb2ea160f2b2bff723054c704f50c9865b", "B V2 result-set commitment mismatch")
        if source["directory"].name == "j3c_judge_continuation_c" and source["output_folder"] == "execution_output_v2":
            require(digest(source["files"]["JUDGE_TERMINAL_JOURNAL.jsonl"]) == "03560d2a8d5a9c2a39d15442eb6c2648376ffa125e375db1cd389fa7798a6de6", "C V2 terminal commitment mismatch")
            projection = b"".join(canonical(r["parsed_semantic_result"]) + b"\n" for r in sorted(terminals, key=lambda row: row["logical_order"]))
            require(digest(projection) == "9f2615b5913e6fa32be3b942446440b60301c3191d3ba6db9b58224dc0e946ff", "C V2 result-set commitment mismatch")
            require([r["logical_order"] for r in terminals] == list(range(32, 40)), "C V2 valid order set differs")
        history_counts.append({"directory": str(source["directory"]), "output_folder": source["output_folder"],
                               "scientific_result_source": source["scientific"], "attempt_journal_records": len(attempts),
                               "terminal_records": len(terminals), "files_preserved": len(source["files"])})
    canonical_results = {}
    for logical_id, valid in candidates.items():
        selected = min(valid, key=lambda item: (item["source_rank"], item["selected_attempt_number"]))
        selected = {**selected, "terminal_source_reference": terminal_records.get(logical_id),
                    "selection_rule": "EARLIEST_VALID_ATTEMPT_UNDER_JUDGE_PARSER_V3"}
        canonical_results[logical_id] = selected
    counts = Counter(r["original_shard"] for r in canonical_results.values())
    require(counts == {"A": 1, "B": 49, "C": 39}, "Current canonical Judge universe differs from authorized 1/49/39")
    require(data["selection_rule"]["rule"] == "EARLIEST_VALID_ATTEMPT_UNDER_JUDGE_PARSER_V3", "Historical selection authority differs")
    require(data["j2d0_reclassification_summary"]["canonical_results"] == {"A": 1, "B": 38, "C": 31, "total": 70}, "Historical J2D0 reclassification summary differs")
    c40 = next(identity for identity, location in original_orders.items() if location == ("C", 40))
    require(c40 not in canonical_results and c40 in attempted, "C order 40 no-valid-result invariant failed")
    require(len([r for r in invalid if r["logical_judge_request_id"] == c40]) == 2, "C order 40 must preserve two invalid outputs")
    require(all(identity not in attempted for identity, (shard, order) in original_orders.items()
                if (shard == "A" and order >= 2) or (shard == "C" and order >= 41)), "Previously unattempted A/C population changed")
    return {"canonical": canonical_results, "attempted": attempted, "original_orders": original_orders,
            "invalid": invalid, "c_order_40_id": c40, "history_counts": history_counts,
            "canonical_counts": dict(counts)}


def repair_judge(data, history):
    requests = {r["logical_judge_request_id"]: r for r in data["requests"]}
    maps = {(r["scenario_id"], r["mode"]): r for r in data["maps_v2"]}
    responses = {(r["scenario_id"], r["mode_id"]): r for r in data["responses"]}
    require(len(maps) == len(responses) == len(data["judge_mappings"]) == 558, "Condition population must be 558")
    require(set(maps) == set(responses) == {(r["scenario_id"], r["mode_id"]) for r in data["judge_mappings"]}, "Condition identity sets differ")
    by_complete_bytes = {}
    mappings = []
    provisional_bytes = set()
    old_ids = set(requests)
    old_result_ids = {r["judge_result_blind_id"] for r in requests.values()}
    for mapping in data["judge_mappings"]:
        pair = (mapping["scenario_id"], mapping["mode_id"])
        old = requests[mapping["judge_logical_request_id"]]
        before = embedded(old["provider_payload"])
        response = responses[pair]
        require(before["candidate_response"] == response["answer_text"], "Candidate response differs from frozen condition response")
        require(before["current_lad_page"] == response["current_page"], "Current page differs from frozen response context")
        require(canonical(before["frozen_applicability_map"]) == canonical(response["frozen_applicability_map"]), "Original applicability join differs")
        require(mapping["judge_result_blind_id"] == old["judge_result_blind_id"], "Original condition Judge ID join differs")
        new_map = maps[pair]["frozen_applicability_map"]
        changed = canonical(before["frozen_applicability_map"]) != canonical(new_map)
        require(changed == maps[pair]["applicability_changed_from_v1"], "Frozen V2 change flag mismatch")
        corrected = replace_embedded(old["provider_payload"], frozen_applicability_map=new_map)
        provisional_bytes.add(canonical(corrected))
        valid = old["logical_judge_request_id"] in history["canonical"]
        if valid and not changed:
            eligibility = RETAIN
            logical_id, result_id = old["logical_judge_request_id"], old["judge_result_blind_id"]
            require(canonical(corrected) == canonical(old["provider_payload"]), "Retained payload differs bytewise")
        else:
            eligibility = REJUDGE if valid else FAILED if old["logical_judge_request_id"] in history["attempted"] else NEW
            # Opaque IDs cannot hash themselves. A fixed opaque placeholder is
            # used solely for ID assignment; deduplication below uses FINAL bytes.
            neutral = replace_embedded(corrected, response_blind_id="R3B-" + "0" * 20)
            identity_basis = canonical(neutral)
            logical_id = opaque(data["key"], JUDGE_DOMAIN, "logical-request-id", identity_basis, "C4J4-", 24)
            result_id = opaque(data["key"], JUDGE_DOMAIN, "result-blind-id", identity_basis, "R3B-", 20)
            require(logical_id not in old_ids and result_id not in old_result_ids, "New corrected request reused a historical identity")
            corrected = replace_embedded(corrected, response_blind_id=result_id)
        final_bytes = canonical(corrected)
        final_hash = digest(final_bytes)
        require({k: v for k, v in embedded(corrected).items() if k not in {"frozen_applicability_map", "response_blind_id"}} ==
                {k: v for k, v in before.items() if k not in {"frozen_applicability_map", "response_blind_id"}}, "Substantive evidence/response changed")
        record = by_complete_bytes.setdefault(final_bytes, {
            "logical_judge_request_id": logical_id, "judge_result_blind_id": result_id,
            "provider_payload_sha256": final_hash, "provider_payload": corrected,
            "estimated_input_tokens": estimated_tokens(corrected), "member_mappings": [],
        })
        require(record["logical_judge_request_id"] == logical_id and record["judge_result_blind_id"] == result_id, "Deterministic corrected ID instability")
        corrected_mapping = {
            "replay_record_id": mapping["replay_record_id"], "scenario_id": pair[0], "mode_id": pair[1],
            "original_logical_judge_request_id": old["logical_judge_request_id"], "original_judge_result_blind_id": old["judge_result_blind_id"],
            "original_provider_payload_sha256": old["provider_payload_sha256"],
            "corrected_logical_judge_request_id": logical_id, "corrected_judge_result_blind_id": result_id,
            "corrected_provider_payload_sha256": final_hash, "original_applicability_sha256": before["frozen_applicability_map"]["applicability_sha256"],
            "corrected_applicability_sha256": new_map["applicability_sha256"], "applicability_changed": changed,
            "changed_criteria": maps[pair]["changed_criteria_from_v1"], "eligibility_class": eligibility,
        }
        record["member_mappings"].append(corrected_mapping)
        mappings.append(corrected_mapping)
    records = list(by_complete_bytes.values())
    require(len({r["provider_payload_sha256"] for r in records}) == len(records), "SHA-256 collision between unequal complete payloads")
    require(len({r["logical_judge_request_id"] for r in records}) == len(records), "Corrected logical ID collision")
    require(len({r["judge_result_blind_id"] for r in records}) == len(records), "Corrected result ID collision")
    for record in records:
        member_classes = {m["eligibility_class"] for m in record["member_mappings"]}
        require(not (RETAIN in member_classes and len(member_classes) > 1), "Retained result merged with a changed/new request")
        classification = next(c for c in (RETAIN, REJUDGE, FAILED, NEW) if c in member_classes)
        record["eligibility_class"] = classification
        for mapping in record["member_mappings"]:
            mapping["eligibility_class"] = classification
        record["original_request_ids"] = sorted({m["original_logical_judge_request_id"] for m in record["member_mappings"]})
        record["changed_criteria"] = sorted({c for m in record["member_mappings"] for c in m["changed_criteria"]})
    require(all(m["eligibility_class"] == FAILED for m in mappings if m["original_logical_judge_request_id"] == history["c_order_40_id"]), "C order 40 classification changed")
    counts = {c: sum(r["eligibility_class"] == c for r in records) for c in (RETAIN, REJUDGE, NEW, FAILED)}
    retained_old = {oid for r in records if r["eligibility_class"] == RETAIN for oid in r["original_request_ids"]}
    excluded_old = set(history["canonical"]) - retained_old
    require(len(retained_old) + len(excluded_old) == 89, "Canonical old result disposition is incomplete")
    return {"records": records, "condition_mappings": mappings, "counts": counts,
            "unique_count": len(records), "provisional_map_only_unique_count": len(provisional_bytes),
            "retained_old_ids": retained_old, "excluded_old_ids": excluded_old,
            "execution_count": len(records) - counts[RETAIN]}


def assign_shards(judge):
    """Scenario/family connected components; deterministic load balancing."""
    scenarios = sorted({m["scenario_id"] for m in judge["condition_mappings"]})
    parents = {scenario: scenario for scenario in scenarios}
    def root(value):
        while parents[value] != value:
            value = parents[value]
        return value
    for record in judge["records"]:
        linked = sorted({m["scenario_id"] for m in record["member_mappings"]})
        for scenario in linked[1:]:
            parents[root(scenario)] = root(linked[0])
    components = {}
    for record in judge["records"]:
        if record["eligibility_class"] == RETAIN:
            record["shard_id"] = None
            continue
        component_id = root(record["member_mappings"][0]["scenario_id"])
        component = components.setdefault(component_id, {"records": [], "tokens": 0, "pages": set(), "changes": set(), "scenarios": set()})
        component["records"].append(record)
        component["tokens"] += record["estimated_input_tokens"]
        component["pages"].add(embedded(record["provider_payload"])["current_lad_page"])
        component["changes"].update(record["changed_criteria"] or ["UNCHANGED_APPLICABILITY"])
        component["scenarios"].update(m["scenario_id"] for m in record["member_mappings"])
    tie = lambda *parts: digest(canonical([SEED, *parts]))
    order = sorted(components, key=lambda cid: (-components[cid]["tokens"], -len(components[cid]["records"]), tie(cid)))
    assignment = {}
    all_pages = set().union(*(c["pages"] for c in components.values()))
    all_changes = set().union(*(c["changes"] for c in components.values()))
    def states(current):
        result = {s: {"tokens": 0, "count": 0, "pages": set(), "changes": set(), "scenarios": set()} for s in "ABC"}
        for cid, shard in current.items():
            state, component = result[shard], components[cid]
            state["tokens"] += component["tokens"]
            state["count"] += len(component["records"])
            for field in ("pages", "changes", "scenarios"):
                state[field].update(component[field])
        return result
    def objective(current):
        state = states(current)
        tokens = [state[s]["tokens"] for s in "ABC"]
        counts = [state[s]["count"] for s in "ABC"]
        return (sum((3 * t - sum(tokens)) ** 2 for t in tokens),
                sum((3 * n - sum(counts)) ** 2 for n in counts),
                sum(len(all_pages - state[s]["pages"]) for s in "ABC"),
                sum(len(all_changes - state[s]["changes"]) for s in "ABC"))
    for cid in order:
        chosen = min("ABC", key=lambda shard: (objective({**assignment, cid: shard}), tie("initial", cid, shard)))
        assignment[cid] = chosen
    improvements = 0
    while True:
        baseline = objective(assignment)
        best = None
        for i, first in enumerate(order):
            for shard in "ABC":
                if shard == assignment[first]:
                    continue
                candidate = {**assignment, first: shard}
                score = objective(candidate)
                if score < baseline:
                    item = (score, tie("move", first, shard), candidate)
                    if best is None or item[:2] < best[:2]: best = item
            for second in order[i + 1:]:
                if assignment[first] == assignment[second]: continue
                candidate = {**assignment, first: assignment[second], second: assignment[first]}
                score = objective(candidate)
                if score < baseline:
                    item = (score, tie("swap", first, second), candidate)
                    if best is None or item[:2] < best[:2]: best = item
        if best is None: break
        assignment = best[2]
        improvements += 1
    for cid, shard in assignment.items():
        for record in components[cid]["records"]:
            record["shard_id"] = shard
    state = states(assignment)
    for shard in "ABC":
        rows = sorted((r for r in judge["records"] if r["shard_id"] == shard), key=lambda row: tie("request-order", row["logical_judge_request_id"]))
        require(bool(rows), "Empty corrected execution shard")
        for position, record in enumerate(rows, 1): record["logical_order"] = position
    summary = {s: {"request_count": state[s]["count"], "estimated_input_tokens": state[s]["tokens"],
                   "scenario_family_count": len(state[s]["scenarios"]), "page_coverage": sorted(state[s]["pages"]),
                   "applicability_change_coverage": sorted(state[s]["changes"]),
                   "maximum_physical_attempts": state[s]["count"] * 2} for s in "ABC"}
    return {"seed": SEED, "shards": summary, "local_improvements": improvements,
            "objective_order": ["estimated_input_token_squared_imbalance", "request_count_squared_imbalance", "missing_page_coverage", "missing_applicability_change_coverage", "seeded_hash_tie_break"],
            "scenario_family_unit": "Existing frozen R3D1 scenario_id family unit; shared-request components remain atomic",
            "scenario_family_atomic": True, "outcome_values_used": False}


def validate_human_base(data):
    results = {}
    expected_fields = {"rating_item_id", *VISIBLE_FIELDS, "applicability_flags",
                       *(c.lower() + ending for c in CRITERIA for ending in ("_rating", "_rationale"))}
    for rater in "AB":
        rows, blank = data["human"][rater], data["blank_human"][rater]
        require(len(rows) == len(blank) == 44, "Human intake row count differs")
        require(all(set(r) == expected_fields for r in rows + blank), "Human source field set differs")
        require([r["rating_item_id"] for r in rows] == [r["rating_item_id"] for r in blank], "Human deterministic source order changed")
        require(len({r["rating_item_id"] for r in rows}) == 44, "Duplicate Human item ID")
        originals = {r["rating_item_id"]: r for r in blank}
        for row in rows:
            original = originals[row["rating_item_id"]]
            require(all(row[f] == original[f] for f in ("rating_item_id", *VISIBLE_FIELDS, "applicability_flags")), "Human visible source field changed")
            flags = json.loads(row["applicability_flags"])
            require(set(flags) == set(CRITERIA) and all(type(v) is bool for v in flags.values()), "Human V1 flags malformed")
            for criterion in CRITERIA:
                value = row[criterion.lower() + "_rating"]
                require(value in {"1", "2", "3", "4", "5"} if flags[criterion] else value == "NA", "Human score/NA violates V1")
                require(bool(row[criterion.lower() + "_rationale"].strip()), "Human rationale incomplete")
        attestation = data["attestations"][rater]
        require("Independent rating completed: **YES**" in attestation, "Human independence attestation missing")
        require(bool(re.search(r"Reviewer signature:\s*[^\n]*[AB][^\n]*", attestation)), "Human attestation signature missing")
        require("2026-09-02" in attestation, "Human attestation completion date missing")
        results[rater] = {"rows": 44, "unique_items": 44, "required_criterion_pairs_complete": 44 * len(CRITERIA),
                          "visible_source_fields_unchanged": True, "score_and_na_valid_under_v1": True,
                          "all_required_rationales_present": True, "attestation_present_and_signed": True,
                          "independence_status": "SELF_ATTESTED_INDEPENDENT_COMPLETION", "technical_independence_verification": "NOT_CLAIMED"}
    require({r["rating_item_id"] for r in data["human"]["A"]} == {r["rating_item_id"] for r in data["human"]["B"]}, "Human item sets differ")
    require([r["rating_item_id"] for r in data["human"]["A"]] != [r["rating_item_id"] for r in data["human"]["B"]], "Human A/B deterministic orders must differ")
    require("Generative AI was used only to draft and format" in data["attestations"]["A"] and
            "not used to make, revise, validate, compare, or replace" in data["attestations"]["A"], "Rater A AI-use declaration differs")
    require("did not view, consult, copy, or otherwise use the AI-generated reference template" in data["attestations"]["B"], "Rater B template-use declaration differs")
    results["A"]["ai_use_declaration"] = "Rater A independently completed all 44 ratings and required rationales. Generative AI was used only to draft and format the later attestation wording, not to make, revise, validate, compare or replace any rating or rationale."
    results["B"]["ai_use_declaration"] = "Rater B independently completed all assigned ratings and required rationales and declared no viewing, consultation, copying or other use of the AI-generated reference template for ratings or rationales."
    return {"status": "PASS_COMPLETED_HUMAN_BASE_INTAKE", "raters": results, "same_opaque_item_set": True,
            "different_deterministic_orders": True, "raw_sources_modified": False,
            "agreement_computations": 0, "score_aggregates_computed": 0}


def human_transition(old: bool, new: bool):
    return KEEP if old and new else KEEP_NA if not old and not new else TO_NA if old else AMEND


def repair_human(data):
    maps = {(r["scenario_id"], r["mode"]): r["frozen_applicability_map"] for r in data["maps_v2"]}
    responses = {r["replay_record_id"]: r for r in data["responses"]}
    original = {r["rating_item_id"]: r for r in data["blank_human"]["A"]}
    by_visible_bytes = {}
    mappings = []
    require(len(data["human_mappings"]) == 108, "Human condition mapping population differs")
    require(len({m["replay_record_id"] for m in data["human_mappings"]}) == 108, "Human condition mapping duplicates")
    for mapping in data["human_mappings"]:
        old_id = mapping["r2_rating_item_id"]
        old = original[old_id]
        flags = maps[(mapping["scenario_id"], mapping["mode_id"])]["criteria"]
        old_flags = json.loads(old["applicability_flags"])
        require(old_flags == responses[mapping["replay_record_id"]]["frozen_applicability_map"]["criteria"], "Human V1 applicability join differs")
        visible = {f: old[f] for f in VISIBLE_FIELDS}
        visible["applicability_flags"] = canonical(flags).decode()
        full_bytes = canonical(visible)
        corrected_id = opaque(data["key"], HUMAN_DOMAIN, "corrected-human-item-id", full_bytes, "C4HC1-", 24)
        record = by_visible_bytes.setdefault(full_bytes, {"corrected_rating_item_id": corrected_id, "visible_payload": visible,
                                                        "visible_payload_sha256": digest(full_bytes), "old_item_ids": set(), "condition_records": []})
        record["old_item_ids"].add(old_id)
        record["condition_records"].append(mapping)
        mappings.append({"original_rating_item_id": old_id, "corrected_rating_item_id": corrected_id,
                         "corrected_visible_payload_sha256": digest(full_bytes),
                         "replay_record_id": mapping["replay_record_id"], "scenario_id": mapping["scenario_id"], "mode_id": mapping["mode_id"]})
    records = list(by_visible_bytes.values())
    old_to_corrected = defaultdict(set)
    for row in mappings: old_to_corrected[row["original_rating_item_id"]].add(row["corrected_rating_item_id"])
    split_count = sum(len(values) > 1 for values in old_to_corrected.values())
    merge_count = sum(len(row["old_item_ids"]) > 1 for row in records)
    pair_counts = Counter()
    pairs = []
    amendments = []
    semantic = []
    for record in records:
        flags = json.loads(record["visible_payload"]["applicability_flags"])
        original_flags = [json.loads(original[old_id]["applicability_flags"]) for old_id in sorted(record["old_item_ids"])]
        require(all(value == original_flags[0] for value in original_flags), "Merged Human item has incompatible original applicability; cannot select ratings without further authority")
        require(len(record["old_item_ids"]) == 1, "Merged Human item has multiple independent base ratings; no automatic rating selection is authorized")
        old_id = next(iter(record["old_item_ids"]))
        for criterion in CRITERIA:
            transition = human_transition(original_flags[0][criterion], flags[criterion])
            pair_counts[transition] += 1
            pair = {"corrected_rating_item_id": record["corrected_rating_item_id"], "criterion": criterion,
                    "classification": transition, "old_applicable": original_flags[0][criterion], "new_applicable": flags[criterion]}
            pairs.append(pair)
            if transition == AMEND:
                basis = canonical({"complete_corrected_visible_payload": record["visible_payload"], "newly_applicable_criterion": criterion})
                amendment_id = opaque(data["key"], HUMAN_DOMAIN, "amendment-item-id", basis, "C4HA1-", 24)
                amendments.append({"amendment_item_id": amendment_id, "corrected_rating_item_id": record["corrected_rating_item_id"],
                                   "criterion": criterion, "visible": {f: record["visible_payload"][f] for f in VISIBLE_FIELDS},
                                   "condition_records": record["condition_records"]})
            for rater in "AB":
                source_row = next(r for r in data["human"][rater] if r["rating_item_id"] == old_id)
                rating = None if transition == AMEND else "NA" if transition == TO_NA else source_row[criterion.lower() + "_rating"]
                rationale = None if transition in (AMEND, TO_NA) else source_row[criterion.lower() + "_rationale"]
                semantic.append({"rater": rater, "corrected_rating_item_id": record["corrected_rating_item_id"],
                                 "criterion": criterion, "classification": transition, "corrected_semantic_value": rating,
                                 "retained_source_rationale": rationale, "original_rating_item_id": old_id,
                                 "original_source_filename": f"human_rating_packet_{rater}_completed.csv",
                                 "new_rating_generated": False, "excluded_original_value_preserved_in_immutable_raw_source": transition == TO_NA})
        record["old_item_ids"] = sorted(record["old_item_ids"])
    counts = {key: pair_counts[key] for key in (KEEP, KEEP_NA, TO_NA, AMEND)}
    require(sum(counts.values()) == len(records) * len(CRITERIA), "Human impact pair accounting differs")
    require(len({r["amendment_item_id"] for r in amendments}) == len(amendments), "Human amendment ID collision")
    require(len(amendments) == counts[AMEND], "Newly applicable criterion lacks an amendment")
    return {"items": records, "condition_mappings": mappings, "criterion_pairs": pairs, "counts": counts,
            "amendments": amendments, "semantic_records": semantic, "corrected_unique_count": len(records),
            "old_item_split_count": split_count, "old_item_merge_count": merge_count,
            "split_additional_items": sum(len(v) - 1 for v in old_to_corrected.values())}
