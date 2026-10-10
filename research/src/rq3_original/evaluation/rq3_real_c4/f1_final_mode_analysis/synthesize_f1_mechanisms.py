"""Descriptive synthesis of frozen mechanism records and physical usage logs."""
from collections import Counter
import json

from f1_common import *
from f1_controlled_unblinding_guard import controlled_json, controlled_jsonl
from f1_statistics import mean, median

READER="synthesize_f1_mechanisms.py"
NE="NOT_EVALUABLE_SOURCE_NOT_AVAILABLE"
COST="COST_NOT_COMPUTED_NO_FROZEN_PRICING_AUTHORITY"


def metric(mode,name,value=None,status="EVALUABLE_FROZEN_RECORDS",denominator=None,scope="FROZEN_CONDITION_REPLAY",reason=""):
    return {"mode_id":mode,"metric":name,"value":value,"denominator":denominator,
            "status":status,"scope":scope,"reason":reason}


def trigger_metrics(predicted,truth):
    tp=sum(a and b for a,b in zip(predicted,truth)); fp=sum(a and not b for a,b in zip(predicted,truth))
    fn=sum(not a and b for a,b in zip(predicted,truth)); tn=sum(not a and not b for a,b in zip(predicted,truth))
    precision=tp/(tp+fp) if tp+fp else None
    recall=tp/(tp+fn) if tp+fn else None
    f1=2*tp/(2*tp+fp+fn) if 2*tp+fp+fn else None
    return {"tp":tp,"fp":fp,"fn":fn,"tn":tn,"precision":precision,"recall":recall,"f1":f1,
            "precision_status":"ESTIMABLE" if precision is not None else "NOT_ESTIMABLE_NO_POSITIVE_PREDICTIONS",
            "recall_status":"ESTIMABLE" if recall is not None else "NOT_ESTIMABLE_NO_GOLD_POSITIVES"}


def load_and_synthesize():
    table=controlled_jsonl(RI/"c4_real_f1_unblinded_condition_analysis_table_v1.jsonl","MECHANISM_SYNTHESIS",READER)
    dataset=controlled_json(C4/"track_d_dataset/final_62_scenario_identity_v1.json","MECHANISM_SYNTHESIS",READER)
    replay=controlled_jsonl(C4/"track_d_dataset/c4_real_replay_manifest_unexecuted_v1.jsonl","MECHANISM_SYNTHESIS",READER)
    mem=controlled_jsonl(C4/"i1_route_integration/c4_real_condition_memory_results_frozen_v1.jsonl","MECHANISM_SYNTHESIS",READER)
    plans=controlled_jsonl(C4/"i1_route_integration/c4_real_condition_planner_results_frozen_v1.jsonl","MECHANISM_SYNTHESIS",READER)
    mechanisms=controlled_jsonl(C4/"i1_route_integration/c4_real_condition_mechanism_records_frozen_v1.jsonl","MECHANISM_SYNTHESIS",READER)
    canonical=controlled_jsonl(C4/"r3d1_response_integration/c4_real_r3_canonical_unique_responses_frozen_v1.jsonl","MECHANISM_SYNTHESIS",READER)
    preconditioning=controlled_jsonl(C4/"i1_route_integration/c4_real_memory_preconditioning_receipts_v1.jsonl","MECHANISM_SYNTHESIS",READER)
    frozen_replay=read_json(C4/"i1_route_integration/c4_real_mechanism_replay_summary_v1.json")
    generator_usage=read_json(C4/"r3d1_response_integration/c4_real_r3_generation_usage_frozen_v1.json")
    judge_usage=read_json(F0/"F0_JUDGE_USAGE_ACCOUNTING_V1.json")
    registry=read_json(REGISTRY)
    modes=[x["mode_id"] for x in registry["modes"]]
    truth={x["scenario_id"]:("course_material_retrieval" in x["required_capabilities"]) for x in dataset["rows"]}
    mech={(x["scenario_id"],x["mode"]):x for x in mechanisms}
    mode_rows=[]; metrics=[]; coverage=[]
    metric_names={group:names for group,names in registry["evaluation_contract"].items() if group.endswith("_metrics")}
    unavailable={
        "REFERENCE_CHUNK_RECALL_AT_K":"Frozen references name legacy chunks; the actual retrieval envelopes expose source IDs without a frozen crosswalk and matched relevance labels for this corpus.",
        "REFERENCE_CHUNK_PRECISION_AT_K":"No frozen mapping aligns the final 62-scenario reference chunk identities with the returned source identities in the actual lexical RAG corpus.",
        "MEAN_RECIPROCAL_RANK":"No aligned frozen relevant-chunk identity and rank ground truth for the actual retrieval corpus.",
        "NO_RESULT_CORRECTNESS":"No independent frozen correctness label for an empty actual retrieval result; a Router requirement is not an absence-of-relevant-evidence label.",
        "WRITE_DECISION_ACCURACY":"Preconditioning logs count fixture writes, but no condition-level target-write decision truth table was frozen for this final response replay.",
        "WRITE_FIELD_PRECISION_RECALL_F1":"No matched, field-level expected and observed target-write records in the frozen 558-condition replay.",
        "RETRIEVAL_DECISION_ACCURACY":"Persistent-retrieval correctness is not identified by generic short-term-memory capability labels; no complete aligned decision truth table was frozen.",
        "REQUIRED_MEMORY_ITEM_RECALL":"No exact expected-to-selected Memory ID crosswalk for the 558-condition replay. Separate Track-M component fixtures do not define the final C4 denominator.",
        "IRRELEVANT_MEMORY_RETRIEVAL_FALSE_POSITIVE_RATE":"No complete frozen per-condition relevance labels for every selected persistent Memory item.",
        "UPDATE_OPERATION_ACCURACY":"No target update observations with aligned operation labels in the frozen replay; target-session writes are zero.",
        "CURRENT_VALUE_ACCURACY_AFTER_UPDATE":"No final-replay target-update truth and post-update value observations. Preconditioning persistence is a different diagnostic.",
        "CROSS_LEARNER_OR_CROSS_CONDITION_LEAK_COUNT":"Selected item envelopes do not supply a complete owner-to-condition audit table. Isolated namespace preparation and forced-OFF checks are reported separately.",
        "SUPPORTED_ACTION_STEP_RATE":"No independent frozen step-level support labels; a USED status or matching evidence hash is not an action-level semantic rating.",
        "UNSUPPORTED_PLAN_STEP_COUNT":"No independent frozen support labels for every emitted action step; do not convert zero inconsistent-plan statuses into zero unsupported steps.",
        "CONSTRAINT_ADHERENCE":"No independent frozen per-plan constraint-adherence labels. The old aggregate diagnostic is retained as context, not promoted to measured adherence.",
        "END_TO_END_LATENCY_MS":"The local replay has no durable end-to-end timing field. Provider start times and separate component latency cannot be substituted.",
    }
    for mode in modes:
        rows=[x for x in table if x["mode_id"]==mode]
        mr=[x for x in mem if x["mode"]==mode]; pr=[x for x in plans if x["mode"]==mode]
        selected=[i for x in mr for i in (x["result"] or {}).get("items",[])]
        pc=[x for x in preconditioning if x["mode"]==mode]
        calls=Counter(m for x in rows for m in x["modules_actually_called"])
        rag_count=sum(x["rag_active"] for x in rows)
        stale=sum(x["timestamp_version"].get("status")!="ACTIVE" for x in selected)
        emitted=[x for x in pr if (x["result"] or {}).get("plan")]
        plan_hash_mismatches=sum(x["result"]["plan"]["compiled_evidence_sha256"]!=mech[(x["scenario_id"],mode)]["compiled_evidence_sha256"] for x in emitted)
        inconsistent=sum(x["status"]=="UNSUPPORTED_OR_INCONSISTENT" for x in pr)
        forced_off_leakage=sum((not x["activation"]) and x["result"] is not None for x in [*mr,*pr])
        # RAG off-state integrity was verified by the frozen input join and I1 source audit.
        assert plan_hash_mismatches==0
        info={"mode_id":mode,"condition_count":len(rows),"scenario_family_count":len({x["scenario_family_id"] for x in rows}),
            "evidence_synthesis_call_count":calls["dashboard_evidence_synthesis"],"p3_lookup_count":calls["frozen_scenario_route_provider"],
            "evidence_compiler_call_count":calls["evidence_compiler"],"rag_activation_count":rag_count,
            "rag_retrieval_computation_count":0 if not rag_count else None,
            "rag_cache_hit_count":0 if not rag_count else None,
            "rag_cache_attribution_status":"KNOWN_ZERO_NO_ACTIVATION" if not rag_count else NE,
            "rag_cache_attribution_reason":"Only aggregate 21 computations and 63 cache hits are durably frozen; no per-condition cache-event attribution was retained.",
            "rag_status_counts":dict(sorted(Counter(x["rag_status"] for x in rows).items())),
            "rag_selected_source_count":sum(x["rag_selected_source_count"] for x in rows),
            "memory_activation_count":sum(x["memory_active"] for x in rows),
            "memory_status_counts":dict(sorted(Counter(x["memory_status"] for x in rows).items())),
            "memory_selected_item_count":len(selected),"memory_selected_type_counts":dict(sorted(Counter(x["item_type"] for x in selected).items())),
            "superseded_memory_violation_count":stale,"target_memory_write_count":sum(x["target_memory_write_count"] for x in rows),
            "target_memory_write_proposal_count":sum(x["target_memory_write_proposal_count"] for x in rows),
            "memory_preconditioning_reopen_count":len(pc),"memory_preconditioning_accepted_write_count":sum(x["accepted_write_count"] for x in pc),
            "planner_activation_count":sum(x["planning_active"] for x in rows),
            "planner_status_counts":dict(sorted(Counter(x["planner_status"] for x in rows).items())),
            "planner_zero_step_count":sum(x["planning_active"] and x["planner_action_step_count"]==0 for x in rows),
            "planner_action_step_count":sum(x["planner_action_step_count"] for x in rows),
            "planner_inconsistent_status_count":inconsistent,"planner_evidence_hash_mismatch_count":plan_hash_mismatches,
            "forced_off_memory_or_planner_result_leakage_count":forced_off_leakage,
            "execution_error_count":sum(x["execution_error_count"] for x in rows),
            "associated_distinct_canonical_generator_requests":len({x["logical_generation_request_id"] for x in rows}),
            "associated_request_counts_are_additive_across_modes":False,
            "condition_deployment_generator_call_count":len(rows),"condition_deployment_judge_call_count":0,
            "condition_deployment_provider_calls_with_frozen_route_cache":len(rows),
            "actual_local_mechanism_replay_provider_call_count":0,
        }
        for label,field in [("input","canonical_generation_input_tokens"),("output","canonical_generation_output_tokens"),("total","canonical_generation_total_tokens")]:
            values=[x[field] for x in rows]
            info[f"condition_projected_generator_{label}_tokens"]={"sum":sum(values),"mean":mean(values),"median":median(values),"minimum":min(values),"maximum":max(values)}
        mode_rows.append(info)
        for name,value in info.items():
            if name not in {"mode_id","rag_cache_attribution_reason"}:
                metrics.append(metric(mode,name,value,scope="CONDITION_PROJECTION" if name.startswith("condition_") else "FROZEN_REPLAY_OR_ASSOCIATED_REQUEST_SET"))
        rag_trigger=trigger_metrics([x["rag_active"] for x in rows],[truth[x["scenario_id"]] for x in rows])
        for category,names in metric_names.items():
            for name in names:
                reason=""; value=None; status="EVALUABLE_FROZEN_RECORDS";scope="FROZEN_CONDITION_REPLAY";denominator=62
                if name in unavailable:status=NE;reason=unavailable[name];denominator=None
                elif name=="RAG_TRIGGER_PRECISION_RECALL_F1":
                    value=rag_trigger;reason="Availability-gated frozen P3 RAG activation versus pre-response required_capabilities containing course_material_retrieval. Descriptive system trigger behaviour only."
                elif name=="RETRIEVAL_CALL_COUNT":value=rag_count;reason="Logical RAG activations; actual cached computation counts are separately reported at aggregate level."
                elif name=="SUPERSEDED_MEMORY_VIOLATION_COUNT":value=stale;denominator=len(selected);reason="Frozen selected-item timestamp_version.status differs from ACTIVE; this is a trace diagnostic."
                elif name=="PLANNER_EVIDENCE_CONSISTENCY":
                    value={"emitted_plan_count":len(emitted),"compiled_evidence_hash_mismatch_count":plan_hash_mismatches,"inconsistent_status_count":inconsistent}
                    denominator=len(emitted);reason="Frozen status and compiled-evidence hash consistency only; does not measure semantic support of individual steps."
                elif name=="MODULE_CALL_COUNTS":value=dict(sorted(calls.items()))
                elif name=="PROVIDER_CALL_COUNTS":
                    value={"actual_local_replay_provider_calls":0,"associated_canonical_generator_requests":info["associated_distinct_canonical_generator_requests"],"counterfactual_generator_calls_with_frozen_route_cache":62}
                    reason="Associated request sets overlap across modes. Actual experimental physical attempts are counted once in the separate global usage account."
                elif name in {"INPUT_TOKENS","OUTPUT_TOKENS","TOTAL_TOKENS"}:
                    value=info["condition_projected_generator_"+name.split("_")[0].lower()+"_tokens"]
                    scope="COUNTERFACTUAL_FROZEN_RESPONSE_PROJECTION";reason="Project the accepted frozen response usage to 62 separate interactions; not an actual billing total or a new response-length prediction."
                elif name=="COST_USD_FROM_SEPARATELY_FROZEN_PRICE_TABLE":
                    status=COST;denominator=None;reason="Approximate router-only prices were frozen historically, but no authoritative complete generator/Judge price schedule exists for this final experiment; no cost computed."
                else:raise AssertionError("UNHANDLED_PREDECLARED_MECHANISM_METRIC")
                item=metric(mode,name,value,status,denominator,scope,reason)
                coverage.append({"category":category,**item});metrics.append(item)
    assert sum(x["evidence_synthesis_call_count"] for x in mode_rows)==496
    assert sum(x["p3_lookup_count"] for x in mode_rows)==434
    assert sum(x["rag_activation_count"] for x in mode_rows)==84
    assert sum(x["memory_activation_count"] for x in mode_rows)==76
    assert sum(x["planner_activation_count"] for x in mode_rows)==60
    assert sum(x["memory_selected_item_count"] for x in mode_rows)==12
    assert sum(x["superseded_memory_violation_count"] for x in mode_rows)==frozen_replay["memory"]["stale_or_superseded_selection_count"]==0
    route_reports=[]
    for path in ["r1_memory_route_execution/execution_output_v1/route_usage_and_cost_v1.json",
                 "r1_rag_route_execution/execution_output_v2/route_usage_and_cost_v1.json",
                 "r1_b4_planning_route_execution/execution_output_v1/route_usage_and_cost_v1.json"]:
        route_reports.append(read_json(C4/path))
    superseded=[read_json(C4/f"g2{letter}_generation_shard_{letter}/execution_output_v1/GENERATION_USAGE_AND_COST.json") for letter in "abc"]
    canonical_tokens={"input_tokens":sum(x["prompt_tokens"] for x in canonical),"output_tokens":sum(x["completion_tokens"] for x in canonical),"total_tokens":sum(x["total_tokens"] for x in canonical)}
    physical_generator=generator_usage["aggregate"]
    usage={
        "scope":"Actual recorded experimental requests and physical attempts, never weighted by 558 conditions.",
        "router_precomputation":{"logical_component_requests":sum(x["logical_requests"] for x in route_reports),
            "physical_attempts":sum(x["physical_attempts"] for x in route_reports),
            "input_tokens":sum(x["input_tokens"] for x in route_reports),"output_tokens":sum(x["output_tokens"] for x in route_reports),"total_tokens":sum(x["total_tokens"] for x in route_reports)},
        "final_response_generation":{"logical_requests":147,"canonical_responses":147,"physical_attempts":physical_generator["physical_attempts"],
            "redundant_historical_retries":physical_generator["historical_redundant_retries"],
            "all_physical_attempt_tokens":{"input_tokens":physical_generator["prompt_tokens"],"output_tokens":physical_generator["completion_tokens"],"total_tokens":physical_generator["total_tokens"]},
            "canonical_accepted_response_tokens":canonical_tokens},
        "judge_evaluation_overhead":{"canonical_result_requests":149,"physical_attempts_started":judge_usage["physical_attempts_started"],
            "returned_outputs":judge_usage["all_returned_output_count"],"canonical_tokens":judge_usage["canonical_corrected_results"]["known_token_totals"],
            "all_returned_output_known_tokens":judge_usage["all_historical_returned_outputs"]["known_token_totals"],
            "unknown_completion_and_billing_attempts":len(judge_usage["unknown_provider_outcome_attempts"]),
            "recorded_api_rejections_without_results":len(judge_usage["recorded_api_rejections_without_result"]),
            "unknown_usage_imputed":False,"condition_usage_multiplier":1},
        "superseded_g2_generation":{"included_in_final_responses_or_scores":False,"provider_calls_observed":sum(x["provider_calls_observed"] for x in superseded),
            "input_tokens":sum(x["prompt_tokens"] for x in superseded),"output_tokens":sum(x["completion_tokens"] for x in superseded),"total_tokens":sum(x["total_tokens"] for x in superseded)},
        "counterfactual_558_individual_interactions":{"generator_calls":558,"judge_calls":0,"p3_cache_lookups":434,
            "provider_calls_with_frozen_precomputed_route_cache":558,"rag_logical_activations":84,"memory_reads":76,"planner_activations":60,
            "input_tokens":sum(x["canonical_generation_input_tokens"] for x in table),"output_tokens":sum(x["canonical_generation_output_tokens"] for x in table),"total_tokens":sum(x["canonical_generation_total_tokens"] for x in table),
            "assumption":"Repeat each frozen condition and accepted response as a separate interaction with the frozen precomputed route cache; exclude evaluation-only Judge calls.",
            "uncached_live_p3_provider_calls_status":NE,
            "uncached_live_p3_reason":"No frozen deployment rule specifies cross-interaction routing cache reuse or which forced-OFF component predictions a live deployment would skip."},
        "f1_new_provider_calls":0,"cost_status":COST,"exact_monetary_cost":None,
        "provider_wire_send_count_and_billing_limit":"Attempt logs do not prove HTTP wire-send timing or resolve unknown provider completion/billing outcomes.",
    }
    usage["recorded_attempts_router_r3_and_all_judge_histories"]=usage["router_precomputation"]["physical_attempts"]+physical_generator["physical_attempts"]+judge_usage["physical_attempts_started"]
    usage["recorded_attempts_including_superseded_g2"]=usage["recorded_attempts_router_r3_and_all_judge_histories"]+usage["superseded_g2_generation"]["provider_calls_observed"]
    mechanism_aggregate={
        "evidence_synthesis_calls":496,"p3_cache_lookups":434,"rag_activations":84,
        "rag_retrieval_computations":frozen_replay["rag"]["lexical_retrieval_computation_count"],
        "rag_cache_hits":frozen_replay["rag"]["retrieval_cache_hit_count"],"rag_status_counts":frozen_replay["rag"]["result_status_counts"],
        "rag_evidence_strength_counts":frozen_replay["rag"]["evidence_strength_counts"],
        "memory_activations":76,"memory_status_counts":frozen_replay["memory"]["status_counts"],
        "selected_memory_items":12,"selected_memory_types":frozen_replay["memory"]["selected_memory_type_counts"],
        "planner_activations":60,"planner_status_counts":frozen_replay["planner"]["status_counts"],
        "planner_zero_step_count":6,"planner_emitted_action_step_count":sum(x["planner_action_step_count"] for x in mode_rows),
        "planner_inconsistent_status_count":sum(x["planner_inconsistent_status_count"] for x in mode_rows),
        "target_memory_writes":0,"superseded_memory_selection_count":0,
        "independent_full_learner_leakage_metric_status":NE,
    }
    result={"schema_version":"C4_REAL_F1_MECHANISM_AND_EFFICIENCY_RESULTS_V1","analysis_role":"PREDECLARED_DESCRIPTIVE_MECHANISM_AND_EFFICIENCY_SYNTHESIS",
        "modes":mode_rows,"predeclared_metric_coverage":coverage,"aggregate_mechanism":mechanism_aggregate,
        "actual_and_counterfactual_usage":usage,"cost_status":COST,
        "component_fixture_metrics_not_substituted_for_final_scenarios":True,
        "source_policy":"Frozen execution and replay records only. No module, Provider or Judge execution in F1."}
    return result,metrics


def main():
    result,metrics=load_and_synthesize()
    write_json(HERE/"C4_REAL_F1_MECHANISM_AND_EFFICIENCY_RESULTS_V1.json",result)
    write_csv(HERE/"C4_REAL_F1_MECHANISM_AND_EFFICIENCY_RESULTS_V1.csv",metrics)
    print(json.dumps({"aggregate":result["aggregate_mechanism"],"usage":result["actual_and_counterfactual_usage"],
                      "predeclared_metric_mode_records":len(result["predeclared_metric_coverage"]),"csv_rows":len(metrics)},indent=2))


if __name__=="__main__":main()
