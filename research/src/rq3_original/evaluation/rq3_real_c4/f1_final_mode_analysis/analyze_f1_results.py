"""Execute only the sealed eight-contrast statistical plan on frozen F1 inputs."""
from collections import Counter, defaultdict
import json
import statistics

from f1_common import *
from f1_controlled_unblinding_guard import controlled_jsonl, verify_entry
from f1_statistics import (mean, median, wins_ties_losses, family_means, cluster_bootstrap,
                           sign_flip, wilcoxon_and_rank_biserial, paired_dz, holm)


def is_numeric(x):
    return isinstance(x,(int,float)) and not isinstance(x,bool)


def complete_pairs(table, left_mode, right_mode, outcome, scenarios=None):
    by_scenario = defaultdict(dict)
    for r in table:
        if scenarios is None or r["scenario_id"] in scenarios:
            by_scenario[r["scenario_id"]][r["mode_id"]]=r
    pairs,exclusions=[],[]
    for sid in sorted(by_scenario):
        l=by_scenario[sid].get(left_mode); r=by_scenario[sid].get(right_mode)
        if l is None or r is None:
            exclusions.append({"scenario_id":sid,"reason":"MISSING_LEFT_CONDITION" if l is None else "MISSING_RIGHT_CONDITION"})
        elif not is_numeric(l.get(outcome)) or not is_numeric(r.get(outcome)):
            la=is_numeric(l.get(outcome));ra=is_numeric(r.get(outcome))
            reason="NA_BOTH_SIDES" if not la and not ra else ("NA_LEFT_ONLY" if not la else "NA_RIGHT_ONLY")
            exclusions.append({"scenario_id":sid,"scenario_family_id":l["scenario_family_id"],"reason":reason})
        else:
            assert l["scenario_family_id"]==r["scenario_family_id"]
            pairs.append((l,r))
    return pairs,exclusions


def describe_pairs(pairs,outcome):
    left=[l[outcome] for l,r in pairs];right=[r[outcome] for l,r in pairs]
    diff=[l-r for l,r in zip(left,right)]
    groups=defaultdict(list)
    for (l,r),d in zip(pairs,diff):groups[l["scenario_family_id"]].append(d)
    return {"paired_scenario_count":len(pairs),"scenario_family_count":len(groups),
            "left_mean":mean(left),"left_median":median(left),"right_mean":mean(right),"right_median":median(right),
            "paired_mean_difference":mean(diff),"paired_median_difference":median(diff),
            **wins_ties_losses(diff,higher_is_better=outcome!="UNSUPPORTED_CLAIM_COUNT")},dict(groups)


def calculate(table):
    plan=read_json(HERE/"C4_REAL_F1_PREDECLARED_ANALYSIS_PLAN_V1.json")
    modes=plan["mode_identities"]
    summaries=[]
    for mode in modes:
        rows=[x for x in table if x["mode_id"]==mode]
        for outcome in [PRIMARY_OUTCOME,*SECONDARY]:
            values=[x[outcome] for x in rows if is_numeric(x[outcome])]
            summaries.append({"mode_id":mode,"outcome":outcome,"scenario_count":len(rows),
                "scenario_family_count":len({x["scenario_family_id"] for x in rows}),
                "applicable_score_count":len(values),"na_count":len(rows)-len(values),
                "mean":mean(values),"median":median(values),
                "standard_deviation_descriptive_only":float(statistics.stdev(values)) if len(values)>1 else None,
                "minimum":min(values) if values else None,"maximum":max(values) if values else None,
                "analysis_role":"PRIMARY_OUTCOME" if outcome==PRIMARY_OUTCOME else "SECONDARY_EXPLORATORY"})
    primary=[]; secondary=[]
    for cid,lmode,rmode,fam in CONTRASTS:
        pairs,excluded=complete_pairs(table,lmode,rmode,PRIMARY_OUTCOME)
        desc,groups=describe_pairs(pairs,PRIMARY_OUTCOME)
        fd=family_means(groups)
        row={"contrast_id":cid,"left_mode_id":lmode,"right_mode_id":rmode,"holm_family":fam,
             "outcome":PRIMARY_OUTCOME,"difference_direction":"LEFT_MINUS_RIGHT",**desc,
             "excluded_case_count":len(excluded),"excluded_family_count":len({x.get("scenario_family_id",x["scenario_id"]) for x in excluded}),
             "exclusion_reason_counts":dict(Counter(x["reason"] for x in excluded)),
             "bootstrap":cluster_bootstrap(groups),"sign_flip":sign_flip(fd),
             **wilcoxon_and_rank_biserial(fd),**paired_dz(fd)}
        row["raw_p_value"]=row["sign_flip"]["p_value"]
        primary.append(row)
        for outcome in SECONDARY:
            pairs,excluded=complete_pairs(table,lmode,rmode,outcome)
            desc,_=describe_pairs(pairs,outcome)
            secondary.append({"contrast_id":cid,"left_mode_id":lmode,"right_mode_id":rmode,"outcome":outcome,
                "analysis_role":"SECONDARY_EXPLORATORY","difference_direction":"LEFT_MINUS_RIGHT",
                "favourable_direction":"LOWER" if outcome=="UNSUPPORTED_CLAIM_COUNT" else "HIGHER",**desc,
                "applicable_pair_count":len(pairs),"excluded_pair_count":len(excluded),
                "exclusion_reason_counts":dict(Counter(x["reason"] for x in excluded)),
                "p_values_computed":False,"holm_family":None})
    for family in ["PRIMARY_ADD_ONE","TARGETED_REMOVE_ONE"]:
        members=[r for r in primary if r["holm_family"]==family]
        for row,p in zip(members,holm([r["raw_p_value"] for r in members])):
            row["holm_adjusted_p_value"]=p
            lo,hi=row["bootstrap"]["ci_low"],row["bootstrap"]["ci_high"]
            row["bootstrap_interval_includes_zero"]=lo<=0<=hi
            row["reliable_improvement_established_under_frozen_judge_analysis"]=(row["paired_mean_difference"]>0 and lo>0 and p<0.05)
            row["interpretation"]=("EVIDENCE_OF_HIGHER_JUDGE_RATED_PRIMARY_OUTCOME" if row["reliable_improvement_established_under_frozen_judge_analysis"]
                else "EXPERIMENT_DOES_NOT_ESTABLISH_A_RELIABLE_IMPROVEMENT")
    sensitivities=[]
    for cname,field in [("C4_REAL_ORIGINAL_25_AUTHENTIC_SUBSET_V1","original_25_member"),
                        ("NINE_SCENARIO_PERSISTENT_MEMORY_REPLAY_COHORT","persistent_memory_replay_member")]:
        ids={x["scenario_id"] for x in table if x[field]}
        rows=[]
        for cid,lmode,rmode,family in CONTRASTS:
            pairs,excluded=complete_pairs(table,lmode,rmode,PRIMARY_OUTCOME,ids)
            desc,groups=describe_pairs(pairs,PRIMARY_OUTCOME)
            rows.append({"contrast_id":cid,**desc,"excluded_pair_count":len(excluded),
                         "exploratory_bootstrap":cluster_bootstrap(groups),"confirmatory_p_values_computed":False})
        sensitivities.append({"cohort_id":cname,"scenario_count":len(ids),"family_count":len(ids),
            "analysis_role":"FROZEN_COHORT_SENSITIVITY_EXPLORATORY","pre_response_identity_verified":True,"contrasts":rows})
    full=[x for x in table if x["mode_id"]=="C5_FULL_C4"]
    strata={
        "P3_RAG_REQUIRED":{x["scenario_id"] for x in full if x["p3_rag_required"]},
        "P3_MEMORY_REQUIRED":{x["scenario_id"] for x in full if x["p3_memory_required"]},
        "P3_PLANNING_REQUIRED":{x["scenario_id"] for x in full if x["p3_planning_required"]},
    }
    for prefix,field,statuses in [("RAG","rag_status",["SUPPORTED","LIMITED_EVIDENCE","NO_RESULT"]),
                                  ("MEMORY","memory_status",["AVAILABLE","NO_MATCH"]),
                                  ("PLANNER","planner_status",["USED","INSUFFICIENT_EVIDENCE"])]:
        for status in statuses:strata[prefix+"_"+status]={x["scenario_id"] for x in full if x[field]==status}
    stratified=[]
    for name,ids in strata.items():
        rows=[]
        for cid,lmode,rmode,family in CONTRASTS:
            pairs,excluded=complete_pairs(table,lmode,rmode,PRIMARY_OUTCOME,ids)
            desc,_=describe_pairs(pairs,PRIMARY_OUTCOME)
            rows.append({"contrast_id":cid,**desc,"excluded_pair_count":len(excluded)})
        stratified.append({"stratum":name,"scenario_count":len(ids),"membership_reference_mode":"C5_FULL_C4",
            "analysis_role":"ROUTER_SELECTED_OR_MECHANISM_STRATIFIED_EXPLORATORY","inference_computed":False,
            "unbiased_component_causal_effect_claim":False,"contrasts":rows})
    return summaries,primary,secondary,sensitivities,stratified


def main():
    verify_entry()
    table=controlled_jsonl(RI/"c4_real_f1_unblinded_condition_analysis_table_v1.jsonl","IDENTITY_JOIN","analyze_f1_results.py")
    summaries,primary,secondary,sensitivities,stratified=calculate(table)
    for name,rows in [("MODE_SUMMARIES",summaries),("PRIMARY_CONTRAST_RESULTS",primary),("SECONDARY_OUTCOME_RESULTS",secondary)]:
        write_json(HERE/f"C4_REAL_F1_{name}_V1.json",{"schema_version":f"C4_REAL_F1_{name}_V1","records":rows})
        write_csv(HERE/f"C4_REAL_F1_{name}_V1.csv",rows)
    write_json(HERE/"C4_REAL_F1_FROZEN_COHORT_SENSITIVITY_V1.json",{"schema_version":"C4_REAL_F1_FROZEN_COHORT_SENSITIVITY_V1","cohorts":sensitivities})
    write_json(HERE/"C4_REAL_F1_MECHANISM_STRATIFIED_DESCRIPTIVES_V1.json",{"schema_version":"C4_REAL_F1_MECHANISM_STRATIFIED_DESCRIPTIVES_V1","strata":stratified})
    print(json.dumps({"status":"EIGHT_PREDECLARED_CONTRASTS_COMPUTED","primary":[
        {k:r[k] for k in ["contrast_id","paired_scenario_count","paired_mean_difference","paired_median_difference","wins","ties","losses","raw_p_value","holm_adjusted_p_value","paired_dz","rank_biserial","wilcoxon_p_value","bootstrap"]}
        for r in primary]},indent=2))


if __name__=="__main__":
    main()
