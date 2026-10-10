"""Offline mock-only loop. Every returned candidate and exception is retained."""
from copy import deepcopy
from datetime import datetime, timezone
import json
from .contracts import canonical
from .projection import project
from .checker import validate_bridge,validate_candidate
from .requests import candidate_request
from p0planner.offline_guard import install


class ScriptedMock:
    def __init__(self,outputs):self.outputs=deepcopy(outputs);self.requests=[]
    def send(self,request):
        self.requests.append(request)
        if not self.outputs:raise RuntimeError('Mock sequence exhausted.')
        result=self.outputs.pop(0)
        if isinstance(result,Exception):raise result
        return deepcopy(result)


def failure_kind(validation):
    codes={i['code'] for i in validation['issues']}
    if codes & {'CANDIDATE_JSON_SYNTAX','REQUIRED_FIELD','SCHEMA_TYPE','SCHEMA_ENUM','SCHEMA_CONST','UNEXPECTED_FIELD','NON_JSON_CANDIDATE','NON_FINITE_NUMBER','EMPTY_STRING','NUMERIC_RANGE','ARRAY_SIZE'}:
        return 'SYNTAX_OR_SCHEMA_FAILURE'
    if validation['outcome']=='NEEDS_INFORMATION':return 'MISSING_INFORMATION'
    return 'EXPLICIT_CONSTRAINT_VIOLATION'


def run_mock(source,mock,*,max_repairs=0):
    if type(mock) is not ScriptedMock:raise TypeError('Only the owned ScriptedMock transport is executable in P1.')
    if type(max_repairs) is not int or max_repairs not in (0,1,2):raise ValueError('Engineering limits: 0/1/2, no approved live budget.')
    install()
    bridge=project(source); history=[]; events=[]; calls={'candidate':0,'repair':0,'final':0,'real':0}
    def event(name):events.append(dict(event=name,sequence=len(events),utc=datetime.now(timezone.utc).isoformat()))
    def finish(status,validation,plan=None,kind=None):
        event('TERMINAL')
        return dict(status=status,failure_kind=kind,plan=deepcopy(plan),validation=validation,repair_history=history,
            provider_calls=calls,trace_events=events,semantic_support='NOT_CHECKED',deployment_suitability='NOT_ESTABLISHED',
            actual_feasibility='NOT_CHECKED',final_response_generated=False)
    event('INPUT_PROJECTED_AND_FROZEN'); pre=validate_bridge(bridge)
    if pre['outcome']!='PASSED_ENCODED_CHECKS':
        status='INVALID_INPUT' if pre['outcome']=='FAILED_VALIDATION' else pre['outcome']
        return finish(status,pre,kind='RUNTIME_INPUT')
    previous=None; feedback=None
    for attempt in range(max_repairs+1):
        req=candidate_request(bridge,attempt,previous,feedback);event('REQUEST_BUILT')
        calls['candidate' if attempt==0 else 'repair']+=1;event('MOCK_ENTERED')
        try:raw=mock.send(req)
        except Exception as exc:
            v={'outcome':'FAILED_VALIDATION','issues':[dict(code='MOCK_TRANSPORT_FAILURE',path='$',message=f'{type(exc).__name__}: {exc}',severity='ERROR')],'checks':[]}
            history.append(dict(attempt=attempt,request=req.payload,request_sha256=req.sha256,raw_candidate=None,candidate=None,exception=str(exc),validation=v))
            return finish('MOCK_TRANSPORT_FAILURE',v,kind='TRANSPORT_FAILURE')
        candidate=raw
        if isinstance(raw,str):
            try:candidate=json.loads(raw)
            except ValueError:candidate=raw
        # Keep transport text exactly; the checker separates syntax and schema issues.
        validation=validate_candidate(bridge,candidate)
        try:canonical(raw); saved=deepcopy(raw)
        except (ValueError,TypeError,OverflowError):saved={'non_json_representation':repr(raw)}
        try:canonical(candidate)
        except (ValueError,TypeError,OverflowError):
            candidate=saved;validation=validate_candidate(bridge,candidate)
        # Repair always recomputes local feedback from the exact rejected candidate.
        feedback=validate_candidate(bridge,candidate);previous=deepcopy(candidate)
        history.append(dict(attempt=attempt,request=req.payload,request_sha256=req.sha256,raw_candidate=saved,candidate=deepcopy(candidate),validation=validation))
        event('LOCAL_VALIDATION_COMPLETE')
        if validation['outcome']=='PASSED_ENCODED_CHECKS':return finish('PASSED_ENCODED_CHECKS',validation,candidate)
    return finish('BOUNDED_REPAIR_EXHAUSTED',validation,kind=failure_kind(validation))
