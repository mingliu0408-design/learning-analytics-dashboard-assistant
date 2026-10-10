"""Narrow dependency injection over exact P0 function bodies; no module monkeypatch.

P0 has global function dependencies but no public extension hook. New function
objects share frozen bytecode with private globals; source_check/load_schema are
rebound only inside this invocation. No inherited byte or global is modified.
"""
from types import FunctionType
import json
from .contracts import CANDIDATE, canonical
from .projection import project
from p0planner import validator as p0
from p0planner.schema import load_schema, schema_errors


def extend_report(a,b):
    r=p0.Report();r.issues=a['issues']+b['issues'];r.checks=a['checks']+b['checks'];return r.result()


def source_extension(bridge):
    mappings=bridge['validity_mapping']
    policy=bridge['source_input']['future_use_policy']
    def check(ref,path,inp,report,at=None):
        mapping=mappings.get(ref['source_id'])
        opened=bool(mapping and mapping['kind']=='NO_DECLARED_EXPIRY' and ref['valid_to'] is None)
        local=p0.Report()
        p0.source_check(ref,path,inp,local,at=at)
        # Only remove the upper-bound missing marker for an explicitly recognized policy.
        # All P0 scope/access/version/future-observation failures survive unchanged.
        report.issues.extend(i for i in local.issues if not (opened and i['code']=='MISSING_TIME' and i['path']==path+'.valid_to'))
        if ref['valid_to'] is None:
            lower=p0.moment(ref['valid_from'],path+'.valid_from',report,required=False)
            now=p0.moment(inp['scope']['as_of'],'$.scope.as_of',report,required=False)
            if lower and now and lower>now:
                report.add('SOURCE_OUTSIDE_VALIDITY',path,'Source valid_from is later than as_of.')
            if at and lower and at[0]<lower:
                report.add('RESOURCE_OUTSIDE_USE_VALIDITY',path,'Use begins before valid_from.')
            if opened and at and now and at[1]>now:
                report.add('OPEN_ENDED_FUTURE_UNCONFIRMED',path,
                    'No declared expiry supports snapshot applicability only; future availability requires reconfirmation.',
                    'NOT_CHECKABLE' if policy=='RECONFIRM_FOR_SCHEDULE' else 'WARNING')
    return check


def validators(bridge):
    env=dict(p0.validate_input.__globals__)
    env['source_check']=source_extension(bridge)
    def schema(name):
        return CANDIDATE if name=='PLANNER_CANDIDATE_SCHEMA_DRAFT.json' else load_schema(name)
    env['load_schema']=schema
    vin=FunctionType(p0.validate_input.__code__,env,'p1_inherited_validate_input',p0.validate_input.__defaults__,p0.validate_input.__closure__)
    env['validate_input']=vin
    vcan=FunctionType(p0.validate_candidate.__code__,env,'p1_inherited_validate_candidate',p0.validate_candidate.__defaults__,p0.validate_candidate.__closure__)
    return vin,vcan


def validate_bridge(bridge):
    # Do not trust caller-supplied projected fields/mappings/issues. Reproject and compare.
    rebuilt=project(bridge['source_input'])
    if canonical(rebuilt)!=canonical(bridge):
        r=p0.Report();r.add('PROJECTION_TAMPERED','$','Projection differs from immutable source input.');return r.result()
    r=p0.Report();r.issues.extend(bridge['projection_issues'])
    if not bridge['planner_input']['goals']:
        # Missing goals are information gaps, not a manufactured goal or malformed plan.
        inp=bridge['planner_input'];check_source=source_extension(bridge)
        for collection in ('facts','resources'):
            for i,item in enumerate(inp[collection]):
                check_source(item['source_ref'],f'$.{collection}[{i}].source_ref',inp,r)
        return r.result()
    inherited=validators(bridge)[0](bridge['planner_input'])
    return extend_report(r.result(),inherited)


def validate_candidate(bridge,candidate):
    pre=validate_bridge(bridge)
    if pre['outcome']!='PASSED_ENCODED_CHECKS':return pre
    vin,check=validators(bridge)
    result=check(bridge['planner_input'],candidate)
    result=extend_report({'issues':bridge['projection_issues'],'checks':[]},result)
    if schema_errors(candidate,CANDIDATE):
        if isinstance(candidate,str):
            try:json.loads(candidate)
            except ValueError:
                result['issues'].append(dict(code='CANDIDATE_JSON_SYNTAX',path='$',message='Candidate text is not valid JSON.',severity='ERROR'))
        return result
    r=p0.Report(); inp=bridge['planner_input']; source_check=source_extension(bridge)
    facts={x['fact_id']:x for x in inp['facts']}
    # P0 checks resources at use time. P1 also checks cited and required facts,
    # goals, completion/plan state, and projected hard constraints at every use.
    structural=set(inp['hard_constraints']['required_evidence_ids'])
    for col in ('goals','completed_tasks','review_permissions'):
        for row in inp[col]:structural.update(row['evidence_refs'])
    if inp['active_plan']:structural.update(inp['active_plan']['evidence_refs'])
    for mem in bridge['source_input']['selected_memory']:
        if mem['binding']['encoding']=='P1_EXPLICIT_FIELDS_JSON_V1':
            fields=json.loads(mem['native']['content'])
            if fields['constraints']:structural.add(mem['native']['memory_id'])
    for i,action in enumerate(candidate['actions']):
        if action['schedule'] is not None:
            when=p0.interval(action['schedule'],f'$.candidate.actions[{i}].schedule',r)
            if when:
                for fid in sorted(structural | set(candidate['evidence_refs']) | set(action['evidence_refs']) | set(action['estimated_duration']['evidence_refs'])):
                    if fid in facts:
                        source_check(facts[fid]['source_ref'],f'$.candidate.actions[{i}].fact[{fid}]',inp,r,at=when)
        duration=action['estimated_duration']
        if duration['origin'] in ('SOURCE_ESTIMATE','LEARNER_ESTIMATE'):
            matches=[]
            for mem in bridge['source_input']['selected_memory']:
                if mem['native']['memory_id'] not in duration['evidence_refs'] or mem['binding']['encoding']!='P1_EXPLICIT_FIELDS_JSON_V1':continue
                if duration['origin']=='LEARNER_ESTIMATE' and mem['binding']['origin']!='LEARNER_STATED_FACT':continue
                for estimate in json.loads(mem['native']['content'])['duration_estimates']:
                    if estimate['task_id']==action['task_id'] and estimate['value']==duration['value'] and estimate['uncertainty']==duration['uncertainty']:
                        matches.append(estimate)
            if not matches:
                r.add('ESTIMATE_SOURCE_VALUE_UNVERIFIED',f'$.candidate.actions[{i}].estimated_duration','No exact structured source estimate/value/uncertainty for this task.','NOT_CHECKABLE')
    r.checks.append(dict(check='deployment_suitability',status='NOT_IMPLEMENTED',detail='Mock admission never authorizes student-facing deployment or semantic correctness.'))
    return extend_report(result,r.result())
