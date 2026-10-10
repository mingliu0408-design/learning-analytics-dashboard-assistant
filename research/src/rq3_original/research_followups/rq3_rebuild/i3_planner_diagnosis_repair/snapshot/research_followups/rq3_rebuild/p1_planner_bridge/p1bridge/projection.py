"""Evidence-preserving projection of selected records, never retrieval/Gold repair."""
from copy import deepcopy
from hashlib import sha256
import json
from .contracts import (INPUT, STRUCTURED, POLICY_ID, POLICY_SHA, VERSION,
                        assert_schema, canonical)
from p0planner.validator import Report, moment


def issue(code,path,message,severity='NOT_CHECKABLE'):
    return dict(code=code,path=path,message=message,severity=severity)


def classify_exact_request(query):
    """Bounded parser, not a general intent model. Mixed/unknown language stays unknown."""
    phrases={'Give me next steps without scheduling dates.':'ORDINARY_ACTION_ADVICE',
             'Schedule these tasks in the stated time windows.':'EXPLICIT_SCHEDULE'}
    mode=phrases.get(query,'UNKNOWN')
    return dict(mode=mode,basis='RESTRICTED_EXACT_PHRASE_V1' if mode!='UNKNOWN' else 'UNKNOWN',source_quote=query)


def validity_mapping(ref,binding):
    if ref['valid_to'] is not None:
        return 'BOUNDED'
    policy=binding['validity_policy']
    if (ref['valid_from'] is not None and policy is not None
        and policy['policy_id']==POLICY_ID and policy['source_sha256']==POLICY_SHA
        and binding['current_version'] is not None
        and binding['learner_id'] is not None and binding['course_id'] is not None):
        return 'NO_DECLARED_EXPIRY'
    return 'UNKNOWN'


def structured_fields(native,binding):
    """Parse only the declared closed JSON source format. No regex dates/budgets."""
    if binding['encoding']=='FREE_TEXT':
        return None
    value=json.loads(native['content'])
    assert_schema(value,STRUCTURED)
    return value


def from_native_selected(envelope,base_input,task_request,*,bindings=None,future_use_policy):
    """Accept actual selected records with separately authorized provenance bindings.

    No native role, course, enablement or current-version authority is inferred.
    Supplied bindings are runtime provenance, never expected-fact lists.
    """
    bindings={} if bindings is None else bindings
    selected=envelope['selected_memory_items']
    if set(bindings)-{n['memory_id'] for n in selected}:
        raise ValueError('Bindings cannot introduce nonselected facts.')
    unknown=dict(learner_id=None,course_id=None,current_version=None,superseded_by=None,
        enabled=None,origin='UNKNOWN',origin_basis='UNKNOWN',source_role='UNKNOWN',
        source_span=None,encoding='FREE_TEXT',validity_policy=None)
    source=dict(schema_version=VERSION,base_input=deepcopy(base_input),task_request=deepcopy(task_request),
        selected_memory=[dict(native=deepcopy(n),binding=deepcopy(bindings.get(n['memory_id'],unknown))) for n in selected],
        memory_status=envelope['status'],future_use_policy=future_use_policy)
    assert_schema(source,INPUT)
    return source


def project(source):
    assert_schema(source,INPUT)
    frozen=deepcopy(source)
    inp=deepcopy(frozen['base_input'])
    problems=[]; lineage=[]; mappings={}; parsed_records=[]
    if any(f['kind']=='LEARNER_MEMORY' for f in inp['facts']):
        raise ValueError('Memory must enter via selected_memory; base_input cannot bypass provenance mapping.')
    task=frozen['task_request']; query=inp['context']['query']
    if task['source_quote'] not in query:
        problems.append(issue('INTENT_SOURCE_MISMATCH','$.task_request','Intent quote is absent from the legitimate request.','ERROR'))
    if task['basis']=='RESTRICTED_EXACT_PHRASE_V1' and task!=classify_exact_request(query):
        problems.append(issue('INTENT_PARSER_MISMATCH','$.task_request','Restricted parser output differs.','ERROR'))
    if task['mode']=='UNKNOWN' or task['basis']=='UNKNOWN':
        problems.append(issue('PLANNING_INTENT_UNKNOWN','$.task_request','Clarify whether dates/time scheduling were requested.'))
    else:
        requested=task['mode']=='EXPLICIT_SCHEDULE'
        if inp['hard_constraints']['schedule']['required'] != requested:
            problems.append(issue('INTENT_SCHEDULE_CONFLICT','$.task_request','Explicit schedule requirement conflicts with request mode.','ERROR'))
    if frozen['memory_status']!='AVAILABLE' and frozen['selected_memory']:
        problems.append(issue('MEMORY_STATUS_CONFLICT','$.memory_status','Non-available envelope carries selected records.','ERROR'))
    seen=set()
    for index,mem in enumerate(frozen['selected_memory']):
        n=mem['native']; b=mem['binding']; tv=n['timestamp_version']; prov=n['provenance']; mid=n['memory_id']; at=f'$.selected_memory[{index}]'
        if mid in seen or mid in {f['fact_id'] for f in inp['facts']}:
            problems.append(issue('DUPLICATE_MEMORY_ID',at,'Memory ID collides with another permitted fact.','ERROR'))
        seen.add(mid)
        digest=sha256(n['content'].encode()).hexdigest()
        if digest!=prov['content_sha256'] or digest!=n['read_only_evidence']['content_sha256'] or n['content']!=n['read_only_evidence']['content'] or n['read_only_evidence']['mutable']:
            problems.append(issue('MEMORY_CONTENT_INTEGRITY',at,'Native content/hash/read-only evidence differs.','ERROR'))
        temporal=Report()
        created=moment(tv['created_at'],at+'.created_at',temporal)
        confirmed=moment(tv['last_confirmed_at'],at+'.last_confirmed_at',temporal)
        now=moment(inp['scope']['as_of'],'$.scope.as_of',temporal)
        if created and confirmed and created>confirmed:
            temporal.add('MEMORY_EVENT_ORDER',at,'Creation cannot follow last confirmation.')
        if created and now and created>now:
            temporal.add('SOURCE_FROM_FUTURE',at+'.created_at','Creation is later than as_of.')
        problems.extend(temporal.issues)
        origin_pairs={'LEARNER_STATED_FACT':('USER','EXPLICIT_USER_STATEMENT'),
            'SYSTEM_ORIGIN_PLAN':('SYSTEM','VERIFIED_SYSTEM_EVENT'),
            'EXPLICITLY_ACCEPTED_PLAN':('USER','EXPLICIT_ACCEPTANCE_EVENT'),
            'OBSERVED_COMPLETED_ACTION':('OBSERVER','VERIFIED_SYSTEM_EVENT'),
            'MODEL_INFERENCE':('MODEL','MODEL_OUTPUT'),'UNKNOWN':('UNKNOWN','UNKNOWN')}
        if (b['source_role'],b['origin_basis'])!=origin_pairs[b['origin']]:
            problems.append(issue('ORIGIN_BASIS_CONFLICT',at,'Origin does not match explicit role/event basis.','ERROR'))
        span=b['source_span']
        if span and (span['start']>=span['end'] or span['end']>len(span['text']) or span['text'][span['start']:span['end']]!=n['content']):
            problems.append(issue('SOURCE_SPAN_MISMATCH',at,'Source character span does not equal native content.','ERROR'))
        if b['origin']!='UNKNOWN' and span is None:
            problems.append(issue('ORIGIN_SOURCE_SPAN_UNKNOWN',at,'Origin assertion lacks source span.'))
        if b['origin']=='UNKNOWN':
            problems.append(issue('MEMORY_ORIGIN_UNKNOWN',at,'Native envelope does not establish learner/system origin.'))
        if b['learner_id'] is None or b['course_id'] is None:
            problems.append(issue('MEMORY_SCOPE_UNKNOWN',at,'Do not infer learner/course from current target alone.'))
        access=('DENIED' if b['enabled'] is False or tv['status']!='ACTIVE' or prov['consent_status'] not in ('GRANTED','NOT_REQUIRED')
                else 'UNKNOWN' if b['enabled'] is None else 'GRANTED')
        # UNKNOWN markers are declared missing IDs, never inferred identities.
        ref=dict(source_id=mid,version=str(tv['version']),learner_id=b['learner_id'],
            course_id=b['course_id'] or 'UNKNOWN',scope='LEARNER',session_id=prov['source_session_id'],
            span_id=prov['source_turn_id'],page='UNKNOWN_NATIVE_SOURCE_PAGE',observed_at=tv['last_confirmed_at'],
            valid_from=tv['valid_from'],valid_to=tv['valid_to'],superseded_by=b['superseded_by'],access=access)
        if b['current_version'] is not None:
            inp['source_versions'].append(dict(source_id=mid,version=b['current_version']))
        inp['facts'].append(dict(fact_id=mid,kind='LEARNER_MEMORY',fact_type=n['memory_type'],value=n['content'],source_ref=ref,available=access=='GRANTED'))
        mapping=validity_mapping(ref,b)
        mappings[mid]=dict(kind=mapping,source_policy=deepcopy(b['validity_policy']),source_ref_sha256=sha256(canonical(ref).encode()).hexdigest())
        lineage.append(dict(memory_id=mid,origin=b['origin'],source_session_id=prov['source_session_id'],source_turn_id=prov['source_turn_id'],
            source_span=deepcopy(span),supersedes_memory_id=prov['supersedes_memory_id'],source_version=str(tv['version']),
            learner_id=b['learner_id'],course_id=b['course_id'],projection='UNSTRUCTURED',learner_adoption='EXPLICIT' if b['origin']=='EXPLICITLY_ACCEPTED_PLAN' else 'NOT_ESTABLISHED'))
        try:
            fields=structured_fields(n,b)
        except (ValueError,TypeError) as exc:
            problems.append(issue('STRUCTURED_MEMORY_INVALID',at,str(exc),'ERROR'));continue
        if fields is None:
            problems.append(issue('UNSTRUCTURED_MEMORY',at,'Original text retained; structured constraints/state not extracted.'))
            continue
        if b['origin'] in ('MODEL_INFERENCE','UNKNOWN'):
            problems.append(issue('ORIGIN_NOT_AUTHORITATIVE_FOR_STATE',at,'Inference/unknown origin cannot supply learner facts, constraints or adopted plans.'));continue
        if b['origin']=='SYSTEM_ORIGIN_PLAN' and any([fields['goal'],fields['constraints'],fields['completed_task_ids'],fields['review_permissions']]):
            problems.append(issue('SYSTEM_ADVICE_NOT_LEARNER_FACT',at,'System plan cannot create learner goals, constraints, completion or review permission.','ERROR'));continue
        if fields['completed_task_ids'] and b['origin'] not in ('LEARNER_STATED_FACT','OBSERVED_COMPLETED_ACTION'):
            problems.append(issue('COMPLETION_ORIGIN_INVALID',at,'Completion requires a learner statement or observed event.','ERROR'));continue
        if fields['review_permissions'] and b['origin']!='LEARNER_STATED_FACT':
            problems.append(issue('REVIEW_ORIGIN_INVALID',at,'Review permission requires an explicit learner source.','ERROR'));continue
        lineage[-1]['projection']='EXPLICIT_STRUCTURED_FIELDS_COPIED'
        parsed_records.append((mid,fields))
    # Declared supersession may not leave both predecessor and successor selected.
    for mem in frozen['selected_memory']:
        previous=mem['native']['provenance']['supersedes_memory_id']
        if previous in seen:
            problems.append(issue('SUPERSEDED_MEMORY_SELECTED','$.selected_memory','Both declared predecessor and successor were supplied.','ERROR'))
    plans=[]; constraints={}; completions={}; review={}
    for mid,f in parsed_records:
        if f['goal']:
            row=dict(**f['goal'],evidence_refs=[mid]); existing=next((g for g in inp['goals'] if g['goal_id']==row['goal_id']),None)
            if existing and existing['text']!=row['text']:
                problems.append(issue('GOAL_CONFLICT','$.goals','Multiple source goals share an ID but disagree.'))
            elif existing:
                existing['evidence_refs']=sorted(set(existing['evidence_refs']+[mid]))
            else:inp['goals'].append(row)
        if f['constraints']:
            for key,value in f['constraints'].items():
                if key in constraints and constraints[key][0]!=value:
                    problems.append(issue('MEMORY_CONSTRAINT_CONFLICT','$.hard_constraints.'+key,'Selected constraints disagree; no automatic resolver.'))
                else:constraints[key]=(deepcopy(value),mid)
        for tid in f['completed_task_ids']:completions.setdefault(tid,[]).append(mid)
        for r in f['review_permissions']:review.setdefault(r['task_id'],[]).append(dict(**r,evidence_refs=[mid]))
        if f['active_plan']:plans.append(dict(**f['active_plan'],evidence_refs=[mid]))
    neutral={'budget':{'required':False,'minutes':None},'schedule':{'required':False,'allowed_windows':None,'excluded_windows':[],'forbidden_weekdays':[],'non_overlap':True},'required_evidence_ids':[],'task_prerequisites':[]}
    for key,(value,mid) in constraints.items():
        current=inp['hard_constraints'][key]
        if current!=value and current!=neutral.get(key):
            problems.append(issue('CURRENT_MEMORY_CONSTRAINT_CONFLICT','$.hard_constraints.'+key,'Current and memory constraints differ; neither is silently overwritten.'))
        else:inp['hard_constraints'][key]=value
    if task['mode']!='UNKNOWN' and inp['hard_constraints']['schedule']['required']!=(task['mode']=='EXPLICIT_SCHEDULE'):
        problems.append(issue('MEMORY_SCHEDULE_INTENT_CONFLICT','$.hard_constraints.schedule.required',
            'A memory scheduling flag conflicts with the current task request; calendar requirements cannot be silently promoted.'))
    for tid,refs in completions.items():
        existing=next((x for x in inp['completed_tasks'] if x['task_id']==tid),None)
        if existing:existing['evidence_refs']=sorted(set(existing['evidence_refs']+refs))
        else:inp['completed_tasks'].append(dict(task_id=tid,evidence_refs=refs))
    for tid,rows in review.items():
        if len({x['rationale'] for x in rows})>1:
            problems.append(issue('REVIEW_PERMISSION_CONFLICT','$.review_permissions','Different permission statements require reconciliation.'))
        elif not any(x['task_id']==tid for x in inp['review_permissions']):inp['review_permissions'].append(rows[0])
    if inp['active_plan']:plans.insert(0,inp['active_plan'])
    if len(plans)>1:
        inp['active_plan']=None
        problems.append(issue('AMBIGUOUS_ACTIVE_PLAN','$.active_plan','Multiple possible plans retained in evidence; no merging or selection.'))
    elif plans:
        inp['active_plan']=plans[0]
        done={x['task_id'] for x in inp['completed_tasks']}
        # Explicit task-ID completion overlay; preserve original plan in immutable evidence.
        active=inp['active_plan']; newly_done=done & set(active['remaining_task_ids'])
        active['remaining_task_ids']=[x for x in active['remaining_task_ids'] if x not in newly_done]
        active['completed_task_ids']=sorted(set(active['completed_task_ids'])|newly_done)
    if not inp['goals']:
        problems.append(issue('GOAL_INFORMATION_MISSING','$.goals','No explicit source goal; do not invent one.'))
    return dict(schema_version=VERSION,source_input=frozen,planner_input=inp,validity_mapping=mappings,
                memory_lineage=lineage,projection_issues=problems)
