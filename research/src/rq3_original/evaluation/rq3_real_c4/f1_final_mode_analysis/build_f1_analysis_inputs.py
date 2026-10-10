"""Join frozen IDs into private F1 condition and pair tables, without text joins."""
from __future__ import annotations

from collections import Counter
import json
import math

from f1_common import *
from f1_controlled_unblinding_guard import controlled_csv, controlled_json, controlled_jsonl, verify_entry

READER = "build_f1_analysis_inputs.py"


def keyed(rows, key):
    result = {key(r) if callable(key) else r[key]: r for r in rows}
    assert len(result) == len(rows), "DUPLICATED_FROZEN_SOURCE_IDENTITY"
    return result


def load_sources():
    verify_entry()
    sources = {}
    for label, name in {
        "projection": "c4_real_corrected_condition_result_projection_f0_v1.jsonl",
        "condition_map": "c4_real_response_to_condition_mapping_frozen_v3.csv",
        "mode_map": "c4_real_response_to_mode_mapping_frozen_v3.csv",
        "scenario_map": "c4_real_response_to_scenario_mapping_frozen_v3.csv",
        "generation_map": "c4_real_condition_to_unique_request_mapping_frozen_v3.csv",
        "corrected_judge_map": "c4_real_condition_to_corrected_judge_request_mapping_r4_v1.csv",
        "r3_response_map": "c4_real_r3_response_to_condition_mapping_frozen_v1.csv",
    }.items():
        loader = controlled_csv if name.endswith(".csv") else controlled_jsonl
        sources[label] = loader(RI/name, "IDENTITY_JOIN", READER)
    for label, name in {
        "replay": "track_d_dataset/c4_real_replay_manifest_unexecuted_v1.jsonl",
        "mechanism": "i1_route_integration/c4_real_condition_mechanism_records_frozen_v1.jsonl",
        "traces": "i1_route_integration/c4_real_condition_execution_traces_frozen_v1.jsonl",
        "rag": "i1_route_integration/c4_real_condition_rag_results_frozen_v1.jsonl",
        "memory": "i1_route_integration/c4_real_condition_memory_results_frozen_v1.jsonl",
        "planner": "i1_route_integration/c4_real_condition_planner_results_frozen_v1.jsonl",
        "routes": "i1_route_integration/c4_real_p3_routes_frozen_v1.jsonl",
        "canonical_generation": "r3d1_response_integration/c4_real_r3_canonical_unique_responses_frozen_v1.jsonl",
    }.items():
        sources[label] = controlled_jsonl(C4/name, "IDENTITY_JOIN", READER)
    for label, name in {
        "dataset": "track_d_dataset/final_62_scenario_identity_v1.json",
        "original25": "track_d_dataset/original_25_subset_identity_v1.json",
    }.items():
        sources[label] = controlled_json(C4/name, "COHORT_IDENTITY_VERIFICATION", READER)
    sources["memory_registry"] = controlled_csv(C4/"track_d_dataset/memory_scenario_registry_v1.csv", "COHORT_IDENTITY_VERIFICATION", READER)
    # F0 is already blind and frozen; read directly without invoking its closed guard.
    sources["judge"] = [json.loads(x) for x in (F0/"c4_real_corrected_judge_results_frozen_v1.jsonl").read_text().splitlines()]
    sources["mode_registry"] = read_json(REGISTRY)
    return sources


def build_inputs(sources):
    s = sources
    projection = keyed(s["projection"], "opaque_condition_id")
    condition = keyed(s["condition_map"], "replay_record_id")
    # These two response-level relations are many-to-many because exact
    # generation requests can be shared. The condition registry below is the
    # authoritative single-valued condition-to-mode-and-scenario mapping.
    old_mode_pairs = {(x["response_blind_id"],x["mode_id"]) for x in s["mode_map"]}
    old_scenario_pairs = {(x["response_blind_id"],x["scenario_id"]) for x in s["scenario_map"]}
    generation = keyed(s["generation_map"], "replay_record_id")
    corrected = keyed(s["corrected_judge_map"], "replay_record_id")
    responses = keyed(s["r3_response_map"], "replay_record_id")
    replay = keyed(s["replay"], "replay_record_id")
    mechanism = keyed(s["mechanism"], "replay_record_id")
    traces = keyed(s["traces"], lambda r:(r["scenario_id"],r["mode"]))
    rag = keyed(s["rag"], lambda r:(r["scenario_id"],r["mode"]))
    memory = keyed(s["memory"], lambda r:(r["scenario_id"],r["mode"]))
    planner = keyed(s["planner"], lambda r:(r["scenario_id"],r["mode"]))
    routes = keyed(s["routes"], "scenario_id")
    scenario = keyed(s["dataset"]["rows"], "scenario_id")
    judge = keyed(s["judge"], "logical_judge_request_id")
    canonical = keyed(s["canonical_generation"], "logical_generation_request_id")
    mode_specs = keyed(s["mode_registry"]["modes"], "mode_id")
    population = set(scenario)
    original25 = set(s["original25"]["unified_scenario_ids"])
    assert original25 == {r["unified_scenario_id"] for r in s["original25"]["rows"]}
    assert len(original25) == 25 and original25 <= population
    assert {r["persistent_replay_eligible"] for r in s["memory_registry"]} <= {"YES", "NO"}
    persistent = {r["unified_scenario_id"] for r in s["memory_registry"] if r["persistent_replay_eligible"]=="YES"}
    assert len(persistent) == 9 and persistent <= population
    assert len(scenario) == len(routes) == 62
    assert len(judge) == 149 and len(canonical) == 147
    for source in [condition,generation,corrected,responses,replay,mechanism]:
        assert set(source) == set(projection) and len(source)==558
    assert len(s["mode_map"]) == len(s["scenario_map"]) == 558
    assert set(routes) == population
    # Real-C4's pre-response registry defines the paired scenario as its unit.
    # The frozen R3 family-sampling implementation uses that same scenario ID.
    # scenario_family_id is a column alias for this frozen ID, not a new cluster.
    family_metadata = read_json(C4/"r3d1_response_integration/c4_real_human_validation_sample_metadata_v1.json")
    assert family_metadata["selection_unit"] == "scenario_family_id"
    assert family_metadata["eligible_family_count"] == 62
    assert s["mode_registry"]["evaluation_contract"]["analysis"]["unit"] == "paired scenario"
    result = []
    for condition_id in sorted(projection):
        f0 = projection[condition_id]
        old_blind_id = condition[condition_id]["response_blind_id"]
        mode_id = generation[condition_id]["mode_id"]
        scenario_id = generation[condition_id]["scenario_id"]
        assert (old_blind_id,mode_id) in old_mode_pairs
        assert (old_blind_id,scenario_id) in old_scenario_pairs
        pair = (scenario_id,mode_id)
        rp, me, gt, cm, rm = replay[condition_id], mechanism[condition_id], generation[condition_id], corrected[condition_id], responses[condition_id]
        for rec, mode_key in [(rp,"mode_id"),(me,"mode"),(gt,"mode_id"),(cm,"mode_id")]:
            assert rec["scenario_id"]==scenario_id and rec[mode_key]==mode_id
        assert gt["response_blind_id"] == old_blind_id
        assert f0["corrected_judge_request_id"] == cm["corrected_logical_judge_request_id"]
        assert f0["corrected_judge_result_id"] == cm["corrected_judge_result_blind_id"]
        jr = judge[f0["corrected_judge_request_id"]]
        assert jr["judge_result_blind_id"] == f0["corrected_judge_result_id"]
        assert jr["provider_payload_sha256"] == cm["corrected_provider_payload_sha256"]
        assert jr["frozen_applicability_map"]["applicability_sha256"] == f0["corrected_applicability_map_sha256"] == cm["corrected_applicability_sha256"]
        score = jr["parsed_semantic_result"]
        assert score == f0["score_record"], "F0_PROJECTION_SCORE_IDENTITY_MISMATCH"
        numeric = [score[k.lower()] for k in CRITERIA if jr["frozen_applicability_map"]["criteria"][k]]
        assert len(numeric)>=3 and all(type(x) is int and 1<=x<=5 for x in numeric)
        assert score["overall_applicable_mean"] == sum(numeric)/len(numeric)
        for name in CRITERIA:
            if not jr["frozen_applicability_map"]["criteria"][name]:
                assert score[name.lower()] == "NA"
        gr = canonical[rm["logical_generation_request_id"]]
        assert gr["response_blind_id"] == rm["response_blind_id"]
        assert gr["provider_payload_sha256"] == rm["provider_payload_sha256"] == gt["provider_payload_sha256_v3"]
        assert rm["logical_generation_request_id"] == gt["logical_generation_request_id"]
        route = routes[scenario_id]
        active = me["activation_mask"]
        assert bool(active["evidence_synthesis"]) == mode_specs[mode_id]["condition_lock"]["evidence_synthesis"]
        for module, rfield in [("rag","rag_required"),("memory","memory_required"),("planning","planning_required")]:
            assert bool(active[module]) == (mode_specs[mode_id]["condition_lock"][module] and route[rfield])
        for mod, records in [("rag",rag),("memory",memory),("planning",planner)]:
            assert records[pair]["activation"] == active[mod]
            assert records[pair]["status"] == me["typed_statuses"][mod]
        assert rp["memory_session_fixture"]["persistent_replay_eligible"] == (scenario_id in persistent)
        assert rp["provider_input"]["current_page"] == gt["current_page"] == scenario[scenario_id]["primary_input"]["current_page"]
        tr = traces[pair]
        assert tr["module_activation"] == active
        assert tr["modules_actually_called"] == me["modules_actually_called"]
        plan_result = planner[pair]["result"] or {}
        memory_result = memory[pair]["result"] or {}
        rag_result = rag[pair]["result"] or {}
        row = {
            "opaque_condition_id": condition_id, "replay_record_id": condition_id,
            "scenario_id": scenario_id, "scenario_family_id": scenario_id,
            "mode_id": mode_id, "analysis_tier": rp["analysis_tier"],
            "current_page": gt["current_page"], "source_dataset": scenario[scenario_id]["source_dataset"],
            "original_25_member": scenario_id in original25, "persistent_memory_replay_member": scenario_id in persistent,
            "p3_rag_required": route["rag_required"], "p3_memory_required": route["memory_required"],
            "p3_planning_required": route["planning_required"], "route_signature": me["route_signature"],
            "evidence_synthesis_active": active["evidence_synthesis"], "rag_active": active["rag"],
            "memory_active": active["memory"], "planning_active": active["planning"],
            "rag_status": rag[pair]["status"], "memory_status": memory[pair]["status"], "planner_status": planner[pair]["status"],
            "rag_selected_source_count": len(rag_result.get("sources",[])),
            "memory_selected_item_count": len(memory_result.get("items",[])), "memory_item_types": tr["memory_item_types"],
            "planner_action_step_count": len((plan_result.get("plan") or {}).get("action_steps",[])),
            "execution_error_count": len(tr["errors"]), "modules_actually_called": me["modules_actually_called"],
            "target_memory_write_count": me["target_memory_write_count"], "target_memory_write_proposal_count": me["memory_write_proposal_count"],
            "frozen_logical_order": me["logical_order"], "semantic_input_sha256": me["semantic_input_sha256"],
            "logical_generation_request_id": rm["logical_generation_request_id"], "response_blind_id": gr["response_blind_id"],
            "generation_payload_sha256": gr["provider_payload_sha256"], "answer_text_sha256": gr["answer_text_sha256"],
            "canonical_generation_input_tokens": gr["prompt_tokens"], "canonical_generation_output_tokens": gr["completion_tokens"],
            "canonical_generation_total_tokens": gr["total_tokens"], "canonical_generation_cached_input_tokens": gr["cached_input_tokens"],
            "corrected_judge_request_id": f0["corrected_judge_request_id"], "corrected_judge_result_id": f0["corrected_judge_result_id"],
            "corrected_judge_payload_sha256": jr["provider_payload_sha256"], "corrected_applicability_map_sha256": f0["corrected_applicability_map_sha256"],
            "applicable_primary_criterion_count": len(numeric), "OVERALL_APPLICABLE_MEAN": score["overall_applicable_mean"],
        }
        row.update({name:score[name.lower()] for name in SECONDARY})
        result.append(row)
    by_pair = keyed(result, lambda r:(r["scenario_id"],r["mode_id"]))
    assert len(by_pair) == 558
    modes = [x["mode_id"] for x in s["mode_registry"]["modes"]]
    assert Counter(x["mode_id"] for x in result) == Counter({m:62 for m in modes})
    assert all({x["mode_id"] for x in result if x["scenario_id"]==sid} == set(modes) for sid in population)
    assert len({x["corrected_judge_result_id"] for x in result}) == 149
    assert len({x["response_blind_id"] for x in result}) == 147
    assert len({x["scenario_family_id"] for x in result}) == 62
    assert all(len({x["corrected_judge_payload_sha256"] for x in result if x["corrected_judge_result_id"]==j})==1
               for j in {x["corrected_judge_result_id"] for x in result})
    pairs = []
    for contrast, left, right, family in CONTRASTS:
        for sid in sorted(population):
            l,r = by_pair[(sid,left)],by_pair[(sid,right)]
            pairs.append({"contrast_id":contrast,"scenario_id":sid,"scenario_family_id":sid,
                "left_condition_id":l["opaque_condition_id"],"right_condition_id":r["opaque_condition_id"],
                "left_mode_id":left,"right_mode_id":right,"holm_family":family,"primary_complete":True,
                "left_value":l[PRIMARY_OUTCOME],"right_value":r[PRIMARY_OUTCOME],
                "paired_difference":l[PRIMARY_OUTCOME]-r[PRIMARY_OUTCOME]})
    audit = {
        "schema_version":"F1_ANALYSIS_INPUT_INTEGRITY_V1","status":"PASS", "condition_rows":558,
        "scenario_count":62,"scenario_family_count":62,"modes_per_scenario":9,"conditions_per_mode":62,
        "corrected_judge_result_count":149,"canonical_generated_response_count":147,
        "missing_conditions":0,"duplicate_conditions":0,"unequal_payload_result_sharing":0,
        "f0_primary_means_preserved_exactly":558,"score_projection_equalities":558,
        "primary_pair_count_per_contrast":{c:62 for c,l,r,f in CONTRASTS},
        "primary_excluded_cases":{c:0 for c,l,r,f in CONTRASTS},"primary_excluded_families":{c:0 for c,l,r,f in CONTRASTS},
        "frozen_pair_registry_rows":len(pairs),"original_25_scenarios":25,"persistent_memory_scenarios":9,
        "cohort_identity_frozen_before_responses":True,"join_method":"EXACT_FROZEN_ID_KEYS_ONLY",
        "text_or_row_position_joins":0,"human_mode_effects_computed":0,"judge_recalibration_operations":0,
    }
    unit = {
        "schema_version":"F1_PAIRING_UNIT_AND_IDENTITY_AUDIT_V1","status":"PASS",
        "pair_key_in_frozen_sources":"scenario_id", "analysis_cluster_column":"scenario_family_id",
        "cluster_column_binding":"Exact alias of frozen scenario_id; no new grouping, split or merge.",
        "scenario_count":62,"family_count":62,"paired_cases_per_family":1,
        "real_c4_unit_authority":{"path":str(REGISTRY.relative_to(ROOT)),"sha256":sha(REGISTRY),"unit":"paired scenario"},
        "frozen_family_binding_evidence":[
            {"path":"evaluation/rq3_real_c4/r3d1_response_integration/build_r3d1_artifacts.py","function":"select_human_families","binding":"Uses frozen scenario_id as family key and requires exactly 62 unique scenario families."},
            {"path":"evaluation/rq3_real_c4/r3d1_response_integration/c4_real_human_validation_sample_metadata_v1.json","selection_unit":"scenario_family_id","eligible_family_count":62}],
        "record_level_family_id_present_in_track_d":False,
        "separate_multi_case_family_mapping_present":False,
        "generic_multi_case_rule":"Available in the frozen algorithms; not invoked because each family has one paired scenario.",
        "clustering_changed_after_result_access":False,
        "semantic_payload_deduplication_is_not_family_redefinition":True,
        "no_independence_assumption_for_558_conditions_or_149_requests":True,
    }
    return result,pairs,audit,unit


def main():
    table,pairs,audit,unit = build_inputs(load_sources())
    files = []
    for name,writer,rows in [
        ("c4_real_f1_unblinded_condition_analysis_table_v1.csv",write_csv,table),
        ("c4_real_f1_unblinded_condition_analysis_table_v1.jsonl",write_jsonl,table),
        ("c4_real_f1_frozen_pair_registry_v1.jsonl",write_jsonl,pairs),
    ]:
        writer(RI/name,rows,mode=0o600)
        files.append(file_metadata(RI/name,len(rows)))
        assert (RI/name).stat().st_mode & 0o777 == 0o600
    write_json(HERE/"F1_RESTRICTED_ANALYSIS_METADATA_V1.json",{
        "schema_version":"F1_RESTRICTED_ANALYSIS_METADATA_V1","files":files,
        "mode_counts":dict(sorted(Counter(x["mode_id"] for x in table).items())),
    })
    write_json(HERE/"F1_ANALYSIS_INPUT_INTEGRITY_V1.json",audit)
    write_json(HERE/"F1_PAIRING_UNIT_AND_IDENTITY_AUDIT_V1.json",unit)
    print(json.dumps(audit,indent=2))


if __name__=="__main__":
    main()
