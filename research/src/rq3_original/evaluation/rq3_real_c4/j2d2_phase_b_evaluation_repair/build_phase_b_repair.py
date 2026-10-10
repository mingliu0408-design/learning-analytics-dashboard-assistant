#!/usr/bin/env python3
"""Build corrected evaluation artifacts, without executing either evaluation."""

from __future__ import annotations

import csv
import io
import json
import os
from pathlib import Path
import subprocess
import sys
from zipfile import ZipFile, ZipInfo, ZIP_DEFLATED

import phase_b_access_guard as guard
from phase_b_sources import Sources, ROOT, BASE, HERE, PHASE_A, RESTRICTED, DOWNLOADS, KEY_COMMITMENT, HUMAN_HASHES, canonical, pretty, digest, require
from phase_b_model import (historical_judge_eligibility, repair_judge, assign_shards, validate_human_base,
                          repair_human, RETAIN, REJUDGE, NEW, FAILED, KEEP, KEEP_NA, TO_NA, AMEND,
                          CRITERIA, VISIBLE_FIELDS, HUMAN_DOMAIN, opaque)

SUPPORT = HERE / "package_support"
sys.path.insert(0, str(SUPPORT))
import validate_package as package_validator


def offline_network_guard(event, args):
    if event in {"socket.connect", "socket.connect_ex", "socket.getaddrinfo", "urllib.Request"}:
        raise RuntimeError("NETWORK_PROHIBITED_IN_PHASE_B")


def durable_write_once(path: Path, raw: bytes, mode=0o644):
    require(not path.exists(), "Refusing to overwrite artifact: " + str(path))
    require(path.parent.is_dir(), "Output parent absent")
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, mode)
    with os.fdopen(fd, "wb") as handle:
        handle.write(raw); handle.flush(); os.fsync(handle.fileno())
    fd = os.open(path.parent, os.O_RDONLY)
    try: os.fsync(fd)
    finally: os.close(fd)


def jsonl_bytes(rows):
    return b"".join(canonical(row) + b"\n" for row in rows)


def csv_bytes(rows, fields):
    stream = io.StringIO(newline="")
    writer = csv.DictWriter(stream, fieldnames=fields, lineterminator="\n")
    writer.writeheader()
    for row in rows:
        writer.writerow({key: canonical(value).decode() if isinstance(value, (list, dict, bool)) else value
                         for key, value in row.items()})
    return stream.getvalue().encode()


def zip_bytes(members):
    buffer = io.BytesIO()
    with ZipFile(buffer, "w", compression=ZIP_DEFLATED, compresslevel=9) as archive:
        for name, raw in sorted(members.items()):
            info = ZipInfo(name, date_time=(2026, 9, 2, 0, 0, 0))
            info.create_system = 3; info.external_attr = 0o100644 << 16; info.compress_type = ZIP_DEFLATED
            archive.writestr(info, raw)
    raw = buffer.getvalue()
    with ZipFile(io.BytesIO(raw)) as archive:
        require(archive.testzip() is None, "Generated ZIP CRC mismatch")
        require(set(archive.namelist()) == set(members), "Generated ZIP allowlist mismatch")
        require(all(archive.read(name) == content for name, content in members.items()), "Generated ZIP byte mismatch")
    return raw


def applicability_contract(entry):
    return {
        "schema_version": "c4-real-applicability-contract-v2",
        "authority_status": guard.AUTHORITY_STATUS,
        "condition_map_v2_sha256": entry["accepted_applicability_v2_artifact_hashes"]["c4_real_condition_applicability_maps_frozen_v2.jsonl"],
        "phase_a_authority_hashes": entry["phase_a_authority_hashes"],
        "phase_b_entry_receipt_sha256": guard.ENTRY_SHA256,
        "original_receipt_status": "PRESERVED_QUALIFIED_BY_PHASE_A_BOUNDARY_INCIDENT",
        "incident_disclosure_preserved": True,
        "output_map_version": "rq3-dimension-applicability-map-v1",
        "decision_recomputation_permitted": False,
        "execution_rule": "Consume the supplied frozen map exactly. Never infer applicability from the candidate response or an outcome.",
        "decision_sources": {
            "CLARITY": "ALWAYS_APPLICABLE", "CONTEXT_AWARENESS": "ALWAYS_APPLICABLE", "RELIABILITY": "ALWAYS_APPLICABLE",
            "PERSONALISATION": "FROZEN_INDEPENDENT_RESEARCHER_DECISION",
            "ACTIONABILITY": "FROZEN_INDEPENDENT_RESEARCHER_DECISION",
            "MOTIVATION_AND_ENGAGEMENT": "FROZEN_INDEPENDENT_RESEARCHER_DECISION",
            "MULTI_PAGE_COHESIVENESS": "FROZEN_RESEARCHER_MATERIAL_PAGE_COUNT_GREATER_THAN_ONE",
            "ERROR_HANDLING": "PRESERVED_CONDITION_SPECIFIC_V1_VALUE",
        },
        "material_page_count_zero_permitted": True,
        "score_contract": "An applicable criterion requires an integer from 1 to 5; a nonapplicable criterion requires NA. Low quality alone never permits NA.",
        "parser_version": "JUDGE_PARSER_V3",
        "primary_rubric_unchanged": True,
    }


def judge_packages(data, judge, shards, entry):
    support = {name: (SUPPORT / name).read_bytes() for name in
               ("JUDGE_PROMPT.txt", "JUDGE_SCHEMA.json", "PRIMARY_RUBRIC.json", "judge_execution_runner_v3.py",
                "judge_result_parser_v3.py", "validate_package.py", "test_package.py")}
    support["APPLICABILITY_CONTRACT_V2.json"] = pretty(applicability_contract(entry))
    manifests, outputs, configurations, contracts = {}, {}, {}, {}
    for shard in "ABC":
        records = sorted((r for r in judge["records"] if r["shard_id"] == shard), key=lambda r: r["logical_order"])
        rows = [{"schema_version": "c4-real-corrected-judge-execution-request-r4-v1",
                 **{k: r[k] for k in ("logical_order", "logical_judge_request_id", "judge_result_blind_id", "provider_payload_sha256", "estimated_input_tokens", "provider_payload")}}
                for r in records]
        requests_raw = jsonl_bytes(rows)
        package_id = f"C4_REAL_CORRECTED_JUDGE_SHARD_{shard}_R4_20260902"
        config = {"schema_version": "c4-real-corrected-judge-configuration-r4-v1", "package_id": package_id,
                  "shard_id": shard, "model": "gpt-4.1-2025-04-14", "temperature": 0, "maximum_output_tokens": 2048,
                  "runtime": {"python_executable": "/opt/anaconda3/bin/python3", "python_version": "3.13.5", "openai_sdk_version": "1.109.1"},
                  "sdk_retries": 0, "request_timeout_seconds": 120.0, "minimum_initial_start_interval_seconds": 15.0,
                  "stream": False, "tools": "NONE", "request_count": len(rows), "maximum_physical_attempts": len(rows) * 2,
                  "estimated_input_tokens": shards["shards"][shard]["estimated_input_tokens"],
                  "blinded_judge_manifest_sha256": digest(requests_raw), "execution_authorized": False,
                  "support_hashes": {name: digest(raw) for name, raw in support.items()}}
        contract = {"schema_version": "c4-real-corrected-judge-execution-contract-r4-v1",
                    **{k: config[k] for k in ("package_id", "shard_id", "request_count", "maximum_physical_attempts", "blinded_judge_manifest_sha256")},
                    "external_authorization_record_required": True,
                    "authorization_environment_variable": "C4_REAL_JUDGE_EXECUTION_AUTHORIZATION",
                    "authorization_environment_value": "AUTHORIZED_C4_REAL_CORRECTED_JUDGE_EXECUTION_R4",
                    "authorization_record_schema_version": "c4-real-corrected-judge-execution-authorization-r4-v1",
                    "authorization_record_exact_fields": ["schema_version", "authorization_id", "authorized_by", "authorized_at_utc", "package_id", "shard_id", "request_count", "maximum_physical_attempts", "package_zip_sha256", "blinded_judge_manifest_sha256", "status"],
                    "required_cli_flags": ["--package-zip", "--authorization-record", "--output-dir", "--execute"],
                    "retryable_failure_codes": package_validator.RETRYABLE,
                    "maximum_byte_identical_invalid_output_retries": 1,
                    "all_other_failures_non_retryable": True,
                    "nonretryable_failures": ["timeout", "transport", "billing", "rate_limit", "authentication", "permission", "refusal", "model_error"],
                    "automatic_resume_permitted": False, "existing_output_overwrite_permitted": False,
                    "phase_b_entry_receipt_sha256": guard.ENTRY_SHA256, "execution_authorized": False,
                    "runtime_gate": config["runtime"], "request_timeout_seconds": 120.0,
                    "sdk_retries": 0, "minimum_initial_start_interval_seconds": 15.0,
                    "failure_policy": "STOP_ENTIRE_SHARD_AND_REQUIRE_NEW_DIRECT_AUTHORIZATION"}
        readme = f"""# Corrected Judge Shard {shard} R4

Status: FROZEN_DORMANT_REQUIRES_SEPARATE_DIRECT_EXECUTION_AUTHORIZATION

This package contains {len(rows)} corrected blinded requests. Estimated input tokens: {config['estimated_input_tokens']}.
The package does not authorize execution. A new external record with the exact fields and bindings in EXECUTION_CONTRACT.json is mandatory, together with the exact environment gate and all required CLI flags. The output directory must be new.

Use /opt/anaconda3/bin/python3, Python 3.13.5, OpenAI SDK 1.109.1, SDK retries 0, timeout 120.0 seconds, and at least 15.0 seconds between initial request starts. Model: gpt-4.1-2025-04-14; temperature 0; maximum output tokens 2048. The prompt, Provider schema, primary rubric, and Parser V3 are preserved.

Only INVALID_JSON, STRICT_SCHEMA_VALIDATION_FAILED, or APPLICABILITY_CONTRACT_VIOLATION permits one byte-identical retry. Every other failure stops the shard. Refusals, including responses carrying both a refusal marker and content, stop without retry.

Applicability Contract V2 is supported by a score-isolated replay with the prior boundary incident explicitly preserved. Consume supplied applicability maps exactly.

Offline validation: python -B validate_package.py --package-dir .
Offline synthetic tests: python -B -m unittest -v test_package
The synthetic tests never execute this package or read its candidate responses.
""".encode()
        members = {**support, "README.md": readme, "BLINDED_JUDGE_REQUESTS.jsonl": requests_raw,
                   "JUDGE_CONFIGURATION.json": pretty(config), "EXECUTION_CONTRACT.json": pretty(contract)}
        members["PACKAGE_SOURCE_HASHES.json"] = pretty({"schema_version": "c4-real-corrected-judge-package-hashes-r4-v1",
                                                       "files": {name: digest(raw) for name, raw in sorted(members.items())}})
        archive = zip_bytes(members)
        validation = package_validator.validate_members(members, package_zip_sha256=digest(archive))
        require(data["key"] not in archive and all(data["key"] not in raw for raw in members.values()), "HMAC key leaked to Judge package")
        filename = f"C4_REAL_CORRECTED_JUDGE_SHARD_{shard}_EXECUTION_PACKAGE_R4_2026-09-02.zip"
        outputs[DOWNLOADS / filename] = archive
        manifests[shard] = {"filename": filename, "path": str(DOWNLOADS / filename), "sha256": digest(archive),
                            "bytes": len(archive), "request_count": len(rows), "estimated_input_tokens": config["estimated_input_tokens"],
                            "members": {name: digest(raw) for name, raw in sorted(members.items())}, "validation": validation}
        configurations[shard] = config; contracts[shard] = contract
    return outputs, manifests, configurations, contracts, support["APPLICABILITY_CONTRACT_V2.json"]


def human_guide():
    return b"""# Human applicability amendment guide

Each row requests one newly applicable criterion. Read the student query, page, conversation history, supplied evidence and candidate response shown in that row. Rate only the named criterion using its definition and full 1-5 anchors. Every rating and criterion-specific rationale starts blank.

Enter an integer from 1 to 5 and a non-empty rationale specific to that criterion. Applicability is already frozen as true: a weak response still receives a numeric rating. Do not change any supplied source field, item identifier, criterion, definition or anchor. Do not fill another criterion.

Complete your packet independently. Do not consult previous ratings or rationales, another rater, an LLM Judge, an AI rating template, or generative AI to make, revise or validate ratings or rationales. The item order differs between the two packets. Experimental identities and previous outcomes are not supplied.

After independently completing every row, sign the amendment attestation. Keep the original completed base packet immutable; submit the amended packet as a separate file. The base ratings do not need to be reopened to perform this amendment.

This packet was prepared only. No amendment rating has been completed by the assistant, and no agreement or statistical analysis has been performed.
"""


def human_attestation(rater):
    return f"""# Human rater {rater} applicability amendment attestation

Packet status: BLANK_TEMPLATE_NOT_COMPLETED
Reviewer role: {rater}

Independent completion of every supplied amendment rating and criterion-specific rationale: __________
Only the named newly applicable criterion was rated in each row: __________
No supplied source field or opaque item ID was changed: __________
No prior rating, prior rationale, other rater result, or Judge result was consulted: __________
No generative AI or AI rating template was used to make, revise or validate an amendment rating or rationale: __________

Reviewer signature: ______________________________
Completion date/time with timezone: ______________________________
Any assistance used solely to format this later attestation, after completing ratings: ______________________________
""".encode()


def human_packages(data, human):
    guide = human_guide()
    rubric = json.loads(data["old_packages"]["A"]["PRIMARY_RUBRIC.json"])
    definitions = {item["criterion_name"]: item for item in rubric["criteria"]}
    fields = ["amendment_item_id", *VISIBLE_FIELDS, "newly_applicable_criterion", "criterion_definition",
              "criterion_anchors_1_to_5", "corrected_applicability", "amendment_rating", "criterion_specific_rationale"]
    rows = []
    for item in human["amendments"]:
        definition = definitions[item["criterion"]]
        rows.append({"amendment_item_id": item["amendment_item_id"], **item["visible"],
                     "newly_applicable_criterion": item["criterion"], "criterion_definition": definition["original_meaning_preserved"],
                     "criterion_anchors_1_to_5": canonical(definition["behavioural_anchors"]).decode(),
                     "corrected_applicability": "true", "amendment_rating": "", "criterion_specific_rationale": ""})
    outputs, manifests = {}, {}
    if not rows: return outputs, manifests, fields, guide
    item_set_hash = digest(canonical(sorted(row["amendment_item_id"] for row in rows)))
    orders = {}
    for rater in "AB":
        ordered = sorted(rows, key=lambda row: opaque(data["key"], HUMAN_DOMAIN, "rater-" + rater + "-order",
                                                    row["amendment_item_id"].encode(), "", 64))
        orders[rater] = [row["amendment_item_id"] for row in ordered]
        csv_name = f"human_applicability_amendment_packet_{rater}.csv"
        members = {"HUMAN_APPLICABILITY_AMENDMENT_GUIDE.md": guide, csv_name: csv_bytes(ordered, fields),
                   f"human_amendment_attestation_{rater}.md": human_attestation(rater)}
        manifest = {"schema_version": "c4-real-human-applicability-amendment-packet-r1-v1", "rater": rater,
                    "status": "FROZEN_BLANK_INDEPENDENT_AMENDMENT_PACKET", "amendment_item_count": len(rows),
                    "item_set_sha256": item_set_hash, "order_sha256": digest(canonical(orders[rater])),
                    "rating_fields_filled": 0, "rationale_fields_filled": 0, "prior_ratings_or_rationales_included": False,
                    "experimental_identities_included": False, "members": {name: digest(raw) for name, raw in members.items()}}
        members["PACKET_MANIFEST.json"] = pretty(manifest)
        archive = zip_bytes(members)
        require(data["key"] not in archive and all(data["key"] not in raw for raw in members.values()), "HMAC key leaked to Human amendment packet")
        filename = f"C4_REAL_HUMAN_RATER_{rater}_APPLICABILITY_AMENDMENT_PACKET_R1_2026-09-02.zip"
        outputs[DOWNLOADS / filename] = archive
        manifests[rater] = {"filename": filename, "path": str(DOWNLOADS / filename), "sha256": digest(archive), "bytes": len(archive),
                            "item_count": len(rows), "item_set_sha256": item_set_hash, "order_sha256": manifest["order_sha256"],
                            "members": {name: digest(raw) for name, raw in members.items()}, "ratings_completed": 0, "rationales_completed": 0}
    require(set(orders["A"]) == set(orders["B"]), "Amendment packet item sets differ")
    require(len(rows) == 1 or orders["A"] != orders["B"], "Amendment packet deterministic orders are identical")
    return outputs, manifests, fields, guide


def prepare():
    source = Sources(); data = source.load()
    history = historical_judge_eligibility(data)
    judge = repair_judge(data, history)
    shards = assign_shards(judge)
    intake = validate_human_base(data)
    human = repair_human(data)
    judge_outputs, judge_packages_meta, configs, contracts, applicability_raw = judge_packages(data, judge, shards, source.entry)
    human_outputs, human_packages_meta, template_fields, guide = human_packages(data, human)
    outputs = {**judge_outputs, **human_outputs}
    tracked = {"package_support/APPLICABILITY_CONTRACT_V2.json": applicability_raw}
    registry = []
    for record in sorted(judge["records"], key=lambda r: r["logical_judge_request_id"]):
        registry.append({"schema_version": "c4-real-corrected-judge-request-registry-v1",
                         **{k: record[k] for k in ("logical_judge_request_id", "judge_result_blind_id", "provider_payload_sha256", "estimated_input_tokens", "eligibility_class", "shard_id", "original_request_ids", "changed_criteria")},
                         "logical_order": record.get("logical_order"),
                         "condition_mapping_count": len(record["member_mappings"]),
                         "corrected_applicability_sha256": record["member_mappings"][0]["corrected_applicability_sha256"],
                         "existing_result_retained": record["eligibility_class"] == RETAIN,
                         "raw_payload_or_scores_in_registry": False})
    by_old = {}
    for mapping in judge["condition_mappings"]:
        by_old.setdefault(mapping["original_logical_judge_request_id"], set()).add(mapping["corrected_logical_judge_request_id"])
    dispositions = [{**result, "corrected_primary_disposition": "RETAIN_UNCHANGED" if identity in judge["retained_old_ids"] else "EXCLUDE_CHANGED_APPLICABILITY_PRESERVE_ORIGINAL",
                     "scores_transformed": False}
                    for identity, result in sorted(history["canonical"].items())]
    impact = {"schema_version": "c4-real-judge-result-eligibility-after-applicability-v2", "status": "PASS_ELIGIBILITY_RESOLVED_WITHOUT_SCORING",
              "condition_mapping_count": 558, "original_unique_request_count": len(data["requests"]),
              "corrected_unique_request_count": judge["unique_count"], "corrected_map_only_unique_count": judge["provisional_map_only_unique_count"],
              "class_counts": judge["counts"], "original_canonical_result_counts": history["canonical_counts"],
              "retained_existing_result_count": len(judge["retained_old_ids"]), "excluded_changed_applicability_result_count": len(judge["excluded_old_ids"]),
              "previously_unattempted_original_unique_requests": len({r["logical_judge_request_id"] for r in data["requests"]} - history["attempted"]),
              "previously_unattempted_corrected_requests": judge["counts"][NEW], "failed_no_valid_result_corrected_requests": judge["counts"][FAILED],
              "corrected_execution_request_count": judge["execution_count"], "original_request_split_count": sum(len(ids) > 1 for ids in by_old.values()),
              "c_order_40": {"original_request_id": history["c_order_40_id"], "classification": FAILED, "valid_canonical_results": 0,
                             "old_outputs_preserved_and_excluded": 2,
                             "corrected_request_ids": sorted(by_old[history["c_order_40_id"]])},
              "existing_result_dispositions": dispositions,
              "deduplication_rule": "COMPLETE_FINAL_PROVIDER_FACING_PAYLOAD_BYTES_ONLY",
              "identity_rebinding": "Task 1 changes only the applicability map in scientific content. Task 3 necessarily replaces the embedded opaque response_blind_id and external request/result IDs for nonretained requests. A fixed opaque placeholder is used only to assign new HMAC identities; final complete bytes alone determine deduplication.",
              "retained_payload_and_applicability_byte_identical": True,
              "parser_v3_aggregate_callback": "REPLACED_IN_PRIVATE_IN_MEMORY_VALIDATION_MODULE_WITH_IDENTICAL_DOMAIN_AND_NA_CHECKS_AND_NO_SCORE_ARITHMETIC",
              "existing_results_rewritten": False, "scores_transformed": False, "score_aggregates_computed": 0, "new_judge_calls": 0}
    tracked["c4_real_corrected_judge_request_registry_v1.jsonl"] = jsonl_bytes(registry)
    tracked["c4_real_judge_result_eligibility_after_applicability_v2.json"] = pretty(impact)
    tracked["c4_real_corrected_judge_shard_metadata_v1.json"] = pretty(shards)
    tracked["c4_real_corrected_judge_package_manifest_r4_v1.json"] = pretty({"schema_version": "c4-real-corrected-judge-packages-r4-v1", "packages": judge_packages_meta, "new_judge_calls": 0})
    tracked["c4_real_corrected_judge_configurations_r4.json"] = pretty(configs)
    tracked["c4_real_corrected_judge_execution_contracts_r4.json"] = pretty(contracts)
    tracked["PHASE_A_AUTHORITY_REFERENCES_V1.json"] = pretty({"final_phase_a_status": guard.AUTHORITY_STATUS, "original_receipt_status": source.entry["original_receipt_status"],
                                                            "phase_a_authority_hashes": source.entry["phase_a_authority_hashes"], "phase_a_cleanroom_hashes": source.entry["phase_a_cleanroom_hashes"],
                                                            "accepted_applicability_v2_artifact_hashes": source.entry["accepted_applicability_v2_artifact_hashes"], "incident_disclosure_preserved": True})
    restricted_artifacts = {}
    judge_mapping_name = "c4_real_condition_to_corrected_judge_request_mapping_r4_v1.csv"
    restricted_artifacts[judge_mapping_name] = (csv_bytes(judge["condition_mappings"], list(judge["condition_mappings"][0])), 558)
    payload_name = "c4_real_corrected_judge_unique_payloads_r4_v1.jsonl"
    payloads = [{k: value for k, value in r.items() if k not in {"member_mappings"}} for r in judge["records"]]
    restricted_artifacts[payload_name] = (jsonl_bytes(payloads), len(payloads))
    human_mapping_name = "c4_real_corrected_human_item_to_condition_mapping_v2.jsonl"
    restricted_artifacts[human_mapping_name] = (jsonl_bytes(human["condition_mappings"]), 108)
    amendment_mapping_name = "c4_real_human_applicability_amendment_to_condition_mapping_r1.jsonl"
    amendment_mappings = [{"amendment_item_id": item["amendment_item_id"], "corrected_rating_item_id": item["corrected_rating_item_id"], "criterion": item["criterion"],
                           "original_rating_item_id": mapping["r2_rating_item_id"], "replay_record_id": mapping["replay_record_id"], "scenario_id": mapping["scenario_id"], "mode_id": mapping["mode_id"]}
                          for item in human["amendments"] for mapping in item["condition_records"]]
    restricted_artifacts[amendment_mapping_name] = (jsonl_bytes(amendment_mappings), len(amendment_mappings))
    semantic_name = "c4_real_corrected_human_semantic_records_v2.jsonl"
    restricted_artifacts[semantic_name] = (jsonl_bytes(human["semantic_records"]), len(human["semantic_records"]))
    restricted_metadata = {"hmac_commitment": KEY_COMMITMENT,
                           "files": [{"filename": name, "row_count": count, "sha256": digest(raw)} for name, (raw, count) in restricted_artifacts.items()]}
    tracked["C4_REAL_PHASE_B_RESTRICTED_MAPPING_METADATA_V1.json"] = pretty(restricted_metadata)
    tracked["c4_real_human_completed_source_intake_v1.json"] = pretty({**intake, "sources": [{"path": str(DOWNLOADS / name), "sha256": value} for name, value in HUMAN_HASHES.items()]})
    human_impact = {"schema_version": "c4-real-human-applicability-impact-v1", "original_unique_visible_items": 44, "sampled_condition_mappings": 108,
                    "corrected_unique_visible_items": human["corrected_unique_count"], "criterion_pair_counts": human["counts"],
                    "count_unit": "unique corrected item/criterion pairs, before multiplying by two raters",
                    "old_item_split_count": human["old_item_split_count"], "old_item_merge_count": human["old_item_merge_count"],
                    "corrected_criterion_pair_count": len(human["criterion_pairs"]), "amendment_items_per_rater": len(human["amendments"]),
                    "required_new_ratings_across_both_raters": 2 * len(human["amendments"]),
                    "criterion_pair_classifications": human["criterion_pairs"],
                    "old_applicable_to_na_requires_rerating": False, "newly_applicable_always_requires_blind_amendment": True,
                    "completed_sources_modified": False, "amendment_ratings_completed": 0, "agreement_calculations": 0, "score_aggregates_computed": 0}
    tracked["c4_real_human_applicability_impact_v1.json"] = pretty(human_impact)
    tracked["c4_real_human_amendment_packet_manifest_v1.json"] = pretty({"schema_version": "c4-real-human-amendment-deliveries-v1", "packages": human_packages_meta,
                                                                      "same_item_set": True, "different_deterministic_orders": bool(human_packages_meta), "all_rating_and_rationale_fields_blank": True})
    tracked["HUMAN_APPLICABILITY_AMENDMENT_GUIDE.md"] = guide
    for rater in "AB": tracked[f"human_amendment_attestation_{rater}.md"] = human_attestation(rater)
    tracked["human_applicability_amendment_blank_template.csv"] = csv_bytes([], template_fields)
    tracked["PHASE_B_SOURCE_PRESERVATION_MANIFEST_V1.json"] = pretty({"schema_version": "phase-b-source-preservation-v1", "sources": list(source.catalog.values()),
                                                                  "historical_execution_sources": history["history_counts"], "source_values_included": False,
                                                                  "historical_j2d0_reclassification_preserved_by_unchanged_committed_tree": True})
    tracked["C4_REAL_JUDGE_REPAIR_IMPACT_REPORT.md"] = f"""# Corrected Judge evaluation repair

The 558 frozen conditions independently produce {judge['unique_count']} corrected unique Judge requests. The original {len(data['requests'])}-request population splits in {impact['original_request_split_count']} cases under frozen Applicability V2. No target count was imposed.

Retained existing results: {judge['counts'][RETAIN]}. Existing results excluded because applicability changed: {len(judge['excluded_old_ids'])}. Previously unattempted corrected requests: {judge['counts'][NEW]} (from {impact['previously_unattempted_original_unique_requests']} old requests). Failed with no valid result: {judge['counts'][FAILED]}. Corrected execution requests: {judge['execution_count']}.

All retained results require exact original/corrected Provider bytes, exact applicability bytes, matching opaque identities and hashes, and Parser V3 validity. Old outputs and scores are preserved. No old score or NA is transformed to manufacture a corrected Judge result. C order 40 has no valid result; its two rejected outputs remain preserved and excluded.

Scientific payload changes are confined to frozen applicability. Fresh request/result IDs are assigned under the authorized R4 HMAC domain; the embedded result label is rebound consistently with the new external result ID. The prompt template, schema, rubric, response and all substantive evidence bytes remain unchanged. Deduplication is performed on complete final Provider-facing bytes, after opaque labels are assigned.

The private eligibility validator runs exact Parser V3 validation with only its aggregate callback replaced by the same per-criterion domain and NA checks. It performs no score arithmetic and writes no replacement Judge result. Delivery Parser V3 remains byte-identical.

Shards A/B/C contain {shards['shards']['A']['request_count']}/{shards['shards']['B']['request_count']}/{shards['shards']['C']['request_count']} requests and {shards['shards']['A']['estimated_input_tokens']}/{shards['shards']['B']['estimated_input_tokens']}/{shards['shards']['C']['estimated_input_tokens']} estimated input tokens. Seed 20260902; scenario/family components remain atomic. Token totals are deterministic byte-based estimates, not measured usage or outcome statistics.

R4 support preserves the existing durable execution logic, binds a new strict external authorization record and exact environment gate, and explicitly treats refusal markers/content-filter returns as non-retryable. The original runner and all historical executions remain unchanged.

Provider calls, new Judge calls, score aggregates, system comparisons and statistics: 0.
""".encode()
    tracked["C4_REAL_HUMAN_APPLICABILITY_IMPACT_REPORT.md"] = f"""# Human applicability repair

Both immutable completed sources pass intake: 44 rows each, the same opaque item set in different frozen orders, unchanged source fields, complete V1-required scores/NA and rationales, and signed attestations.

Rater A declares independent completion of all 44 ratings and rationales. Generative AI was used only for drafting/formatting the later attestation, not for making, revising or validating a rating. Rater B declares independent completion and no use of the AI-generated reference template for ratings or rationales. These are self-attestations; technical verification of independence is not claimed.

The preserved 108 sampled condition mappings produce {human['corrected_unique_count']} corrected unique visible items. Splits: {human['old_item_split_count']}; merges: {human['old_item_merge_count']}.

Counts per unique corrected item/criterion pair: unchanged applicable {human['counts'][KEEP]}; unchanged NA {human['counts'][KEEP_NA]}; old applicable to new NA {human['counts'][TO_NA]}; newly applicable {human['counts'][AMEND]}. These counts are not doubled for raters. The {human['counts'][TO_NA]} newly nonapplicable pairs need no rater action; old raw values and rationales remain immutable while corrected semantic values are NA. The {human['counts'][AMEND]} newly applicable pairs require {2 * human['counts'][AMEND]} independent ratings across the two original raters.

Each amendment row exposes one newly applicable criterion, its definition and all five original anchors, the same visible context and candidate response, and blank rating/rationale fields. No prior score, prior rationale, other-rater output or Judge output is included.

Amendment ratings filled, agreement calculations, score aggregates, system comparisons and final statistics: 0.
""".encode()
    summary = {"schema_version": "phase-b-build-result-v1", "status": "PREPARED_FOR_TARGETED_TESTS_AND_WRITE_ONCE_FREEZE",
               "entry_receipt_sha256": guard.ENTRY_SHA256, "corrected_unique_judge_requests": judge["unique_count"],
               "judge_class_counts": judge["counts"], "corrected_execution_requests": judge["execution_count"],
               "shards": shards["shards"], "human_corrected_unique_items": human["corrected_unique_count"], "human_pair_counts": human["counts"],
               "judge_packages": judge_packages_meta, "human_packages": human_packages_meta,
               "restricted_files": restricted_metadata, "provider_calls": 0, "judge_executions": 0,
               "human_amendment_ratings": 0, "score_aggregates": 0, "agreement_calculations": 0, "statistical_analyses": 0}
    tracked["BUILD_RESULT_METADATA_V1.json"] = pretty(summary)
    return {"source": source, "data": data, "history": history, "judge": judge, "shards": shards,
            "intake": intake, "human": human, "tracked": tracked, "outputs": outputs,
            "restricted": restricted_artifacts, "summary": summary}


def main():
    sys.addaudithook(offline_network_guard)
    require(subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=ROOT, text=True).strip() == "cc66a6050be995cfdf6e13ca12135d09c20537f9", "Starting HEAD changed")
    require(not (HERE / "BUILD_RESULT_METADATA_V1.json").exists(), "Build already materialized")
    prepared = prepare()
    for path in prepared["outputs"]: require(not path.exists(), "Delivery output already exists")
    for name in prepared["tracked"]: require(not (HERE / name).exists(), "Tracked output already exists: " + name)
    for name in prepared["restricted"]:
        path = RESTRICTED / name
        require(not path.exists(), "Restricted output already exists")
        require(subprocess.run(["git", "check-ignore", "-q", str(path.relative_to(ROOT))], cwd=ROOT).returncode == 0, "New restricted output not ignored")
    for name, raw in prepared["tracked"].items(): durable_write_once(HERE / name, raw)
    for name, (raw, count) in prepared["restricted"].items(): durable_write_once(RESTRICTED / name, raw, 0o600)
    for path, raw in prepared["outputs"].items(): durable_write_once(path, raw)
    print(json.dumps({"status": "PACKAGES_PREPARED_WITHOUT_EXECUTION", "corrected_unique_judge_requests": prepared["judge"]["unique_count"],
                      "corrected_execution_requests": prepared["judge"]["execution_count"], "human_amendment_items_per_rater": len(prepared["human"]["amendments"]),
                      "judge_packages": 3, "human_packages": len(prepared["summary"]["human_packages"]), "provider_calls": 0, "freeze_receipts_written": 0}, sort_keys=True))


if __name__ == "__main__": main()
