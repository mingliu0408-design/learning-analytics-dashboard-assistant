"""Artificial transport only. Never imports a provider SDK."""
import json
from copy import deepcopy


def candidate(body):
    p = body['encoded_planning_fields']
    ids = ['current-request'] + p['hard_constraints']['required_evidence_ids']
    budget = p['hard_constraints']['budget']
    minutes = min(10, budget['minutes']) if budget['required'] else 10
    return dict(plan_id='artificial-plan',goal_id='current-request',goal=body['current_query'],
        actions=[dict(step_id='step-1',task_id='artificial-action',kind='TASK',
            action='ARTIFICIAL MOCK: review the current example.',
            estimated_duration=dict(value=minutes,unit='minutes',origin='MODEL_ESTIMATE',evidence_refs=[],
                uncertainty='Artificial estimate, not a measured duration.'),resource_ids=[],dependencies=[],
            schedule=None,completion_check='ARTIFICIAL MOCK: compare the steps.',evidence_refs=ids,
            brief_rationale='Artificial mechanical test.')],evidence_refs=ids,continues_plan_id=None,
        brief_rationale='Artificial mechanical test, no educational quality claim.')


class MockTransport:
    kind = 'MOCK'
    def __init__(self, transform=None):
        self.requests=[]
        self.transform=transform

    def send(self, payload):
        self.requests.append(deepcopy(payload))
        schema=payload['response_format']['json_schema']['schema']
        props=schema['properties']
        body=json.loads(payload['messages'][-1]['content'])
        if 'rag_required' in props or 'memory_required' in props or 'planning_required' in props:
            value={k:True for k in props}
        elif 'plan_id' in props:
            value=candidate(body)
        else:
            value=dict(answer='ARTIFICIAL MOCK RESPONSE: explain the scoped information and ask for missing details.',
                cited_evidence_ids=[],plan_fields=body['accepted_plan'])
        raw=dict(id=f'artificial-response-{len(self.requests)}',_request_id=f'mock-request-{len(self.requests)}',
            model=payload['model'],choices=[dict(finish_reason='stop',message=dict(content=json.dumps(value),refusal=None))],
            usage=dict(prompt_tokens=1,completion_tokens=1,total_tokens=2),_artificial=True)
        return self.transform(payload,raw,len(self.requests)) if self.transform else raw

    def close(self):
        pass


class MockClock:
    def __init__(self): self.value=0.0
    def __call__(self): return self.value
    def sleep(self,n): self.value += n
