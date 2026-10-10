"""Strict provider-neutral schemas. No free-text constraint extraction."""
from copy import deepcopy
from pathlib import Path
import sys
import json
from hashlib import sha256

ROOT = Path(__file__).resolve().parent.parent
P0 = ROOT.parent / 'p0_planner_prototype'
if not P0.is_dir():
    P0 = ROOT / 'inherited_p0'  # exact dependency copy for standalone review
for dependency in json.loads((ROOT / 'P0_DEPENDENCY_LOCK.json').read_text())['files']:
    if sha256((P0 / dependency['path']).read_bytes()).hexdigest() != dependency['sha256']:
        raise RuntimeError('Frozen P0 dependency differs: ' + dependency['path'])
if str(P0) not in sys.path:
    sys.path.insert(0, str(P0))
from p0planner.contracts import canonical, CandidateRequest
from p0planner.schema import schema_errors, load_schema as p0_schema
from tools.schema_definitions import obj, arr, nullable, S, B, IDS, REF, MINUTES, ISSUE

VERSION = 'P1_MEMORY_PLANNER_BRIDGE_V1_DRAFT'
POLICY_ID = 'C4_STORE_8b22f73_NULL_NO_DECLARED_EXPIRY_V1'
POLICY_SHA = '42f0979f28701f26d8b7f55f149997ac66da44e1d6575abe75db3a7474830b2b'

def enum(*values):
    return {'type':'string','enum':list(values)}

P0_INPUT = p0_schema('PLANNER_INPUT_SCHEMA_DRAFT.json')
BASE = deepcopy(P0_INPUT)
# A missing goal is a legitimate incomplete bridge input; final checking blocks it.
BASE['properties']['goals']['minItems'] = 0
NATIVE = obj(memory_id=S, memory_type=S, content=S,
    timestamp_version=obj(created_at=S, valid_from=nullable(S), valid_to=nullable(S),
        last_confirmed_at=S, version={'type':'integer','minimum':1}, status=S),
    provenance=obj(source_session_id=S,source_turn_id=S,supersedes_memory_id=nullable(S),
        consent_status=S,content_sha256=S),
    read_only_evidence=obj(representation=S,mutable=B,content=S,content_sha256=S))
# Retrieval diagnostics are retained as opaque finite scalars in the actual native shape.
NATIVE['properties']['relevance_components'] = obj(
    **{key:{'type':'number'} for key in ('lexical','semantic','memory_type_alignment','recency','importance','confidence','fusion')},
    lexical_supported=B, semantic_supported=B)
NATIVE['required'].append('relevance_components')
ORIGIN = enum('LEARNER_STATED_FACT','SYSTEM_ORIGIN_PLAN','EXPLICITLY_ACCEPTED_PLAN',
              'OBSERVED_COMPLETED_ACTION','MODEL_INFERENCE','UNKNOWN')
BINDING = obj(learner_id=nullable(S),course_id=nullable(S),current_version=nullable(S),
    superseded_by=nullable(S),enabled=nullable(B),origin=ORIGIN,
    origin_basis=enum('EXPLICIT_USER_STATEMENT','VERIFIED_SYSTEM_EVENT','EXPLICIT_ACCEPTANCE_EVENT','MODEL_OUTPUT','UNKNOWN'),
    source_role=enum('USER','SYSTEM','OBSERVER','MODEL','UNKNOWN'),
    source_span=nullable(obj(text=S,start={'type':'integer','minimum':0},end={'type':'integer','minimum':1})),
    encoding=enum('FREE_TEXT','P1_EXPLICIT_FIELDS_JSON_V1'),
    validity_policy=nullable(obj(policy_id=S,source_sha256=S)))
MEMORY = obj(native=NATIVE,binding=BINDING)
REQUEST_INTENT = obj(mode=enum('ORDINARY_ACTION_ADVICE','EXPLICIT_SCHEDULE','UNKNOWN'),
    basis=enum('EXPLICIT_TASK_REQUEST_FIELD','RESTRICTED_EXACT_PHRASE_V1','UNKNOWN'),source_quote=S)
INPUT = obj(schema_version={'type':'string','const':VERSION},base_input=BASE,
    task_request=REQUEST_INTENT,selected_memory=arr(MEMORY),
    memory_status=enum('AVAILABLE','NO_MATCH','NOT_ACTIVATED','UNKNOWN'),
    future_use_policy=enum('RECONFIRM_FOR_SCHEDULE','WARN_SNAPSHOT_ONLY'))

# Only explicitly serialized source fields can become encoded constraints.
constraint_props=deepcopy(P0_INPUT['properties']['hard_constraints']['properties'])
CONSTRAINTS={'type':'object','properties':constraint_props,'required':[],'additionalProperties':False}
GOAL=obj(goal_id=S,text=S)
PLAN=obj(plan_id=S,goal_id=S,remaining_task_ids=IDS,completed_task_ids=IDS)
STRUCTURED=obj(goal=nullable(GOAL),constraints=nullable(CONSTRAINTS),completed_task_ids=IDS,
               active_plan=nullable(PLAN),review_permissions=arr(obj(task_id=S,rationale=S)),
               duration_estimates=arr(obj(task_id=S,value=MINUTES,uncertainty=S)))
CANDIDATE=p0_schema('PLANNER_CANDIDATE_SCHEMA_DRAFT.json')
DURATION=CANDIDATE['properties']['actions']['items']['properties']['estimated_duration']
DURATION['properties']['origin']['enum'].append('MODEL_ESTIMATE')
DURATION['properties']['uncertainty']=S
DURATION['required'].append('uncertainty')


def assert_schema(value, schema):
    errors=schema_errors(value,schema)
    if errors:
        raise ValueError(canonical(errors))
    canonical(value)  # reject NaN/Infinity even in incidental JSON


def schemas():
    return {'P1_BRIDGE_INPUT_SCHEMA_DRAFT.json':INPUT,
            'P1_CANDIDATE_SCHEMA_DRAFT.json':CANDIDATE,
            'P1_STRUCTURED_MEMORY_FIELDS_SCHEMA_DRAFT.json':STRUCTURED}

# Full output/request contracts; projections are recomputed before use, including
# the dynamic source-ID mapping. Invalid candidate history remains arbitrary JSON.
BRIDGE_OUTPUT=obj(schema_version={'type':'string','const':VERSION},source_input=INPUT,planner_input=BASE,
    validity_mapping={'type':'object'},memory_lineage=arr({'type':'object'}),projection_issues=arr(ISSUE))
from tools.schema_definitions import VALIDATION
CANDIDATE_REQUEST=obj(contract_version={'type':'string','const':'P1_REQUEST_V1_DRAFT'},phase=enum('CANDIDATE','REPAIR'),
    attempt={'type':'integer','minimum':0,'maximum':2},instruction=S,runtime_input=BRIDGE_OUTPUT,
    response_schema={'type':'object','const':CANDIDATE},previous_candidate=nullable({}),local_validation=nullable(VALIDATION))
OUTPUT=obj(status=S,failure_kind=nullable(S),plan=nullable(CANDIDATE),validation=VALIDATION,
    repair_history=arr({'type':'object'},maximum=3),provider_calls=obj(
        candidate={'type':'integer','minimum':0,'maximum':1},repair={'type':'integer','minimum':0,'maximum':2},
        final={'type':'integer','const':0},real={'type':'integer','const':0}),
    trace_events=arr(obj(event=S,sequence={'type':'integer','minimum':0},utc=S)),
    semantic_support={'type':'string','const':'NOT_CHECKED'},deployment_suitability={'type':'string','const':'NOT_ESTABLISHED'},
    actual_feasibility={'type':'string','const':'NOT_CHECKED'},final_response_generated={'type':'boolean','const':False})
_BASE_SCHEMAS=schemas

def schemas():
    return {**_BASE_SCHEMAS(),'P1_BRIDGE_OUTPUT_SCHEMA_DRAFT.json':BRIDGE_OUTPUT,
            'P1_CANDIDATE_REQUEST_SCHEMA_DRAFT.json':CANDIDATE_REQUEST,'P1_MOCK_OUTPUT_SCHEMA_DRAFT.json':OUTPUT}
