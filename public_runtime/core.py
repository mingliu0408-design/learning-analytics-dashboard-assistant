"""Public adapter: historical replay, actual local core and visitor-key live.

The research core runs in a credential-free process. No original M1 module is
imported in this API/UI process, and visitor keys never enter global env/cache.
"""
from copy import deepcopy
from pathlib import Path
import hashlib
import json
import os
import subprocess
import sys
import tempfile
from datetime import datetime, timezone

ROOT=Path(__file__).resolve().parents[1]
CORE=ROOT/'research/src/rq3_original'
PAGES=('Overview','Resources','Lecture','Debate','Reflection')
MODES=('S0_PAGE_ONLY','S1_CROSS_PAGE_EVIDENCE','S2_EVIDENCE_RAG','S3_EVIDENCE_MEMORY','S4_EVIDENCE_PLANNING','S5_FULL')
PROFILES=('REPLAY','COMPONENTS','LIVE')

def lines(path):return [json.loads(x) for x in Path(path).read_text().splitlines() if x.strip()]

def tasks():return lines(ROOT/'data/replay/final_tasks.jsonl')

def responses():return lines(ROOT/'data/replay/RESPONSE_HANDOFF.jsonl')

class CoreFailure(RuntimeError):pass

class PublicAssistant:
    def __init__(self,session_id,*,storage_root=None,python=sys.executable):
        if not session_id or not session_id.isalnum():raise ValueError('ALPHANUMERIC_SESSION_REQUIRED')
        self.session_id=session_id
        self.python=python
        root=Path(storage_root) if storage_root is not None else Path(tempfile.gettempdir())/'lad-assistant-sessions'
        self.workspace=root/session_id
        self.workspace.mkdir(parents=True,exist_ok=True)
        self._histories={}
        self.active_task_id=None
        self.history=[]
        self._api_key=None

    def select_task(self,task_id):
        self.active_task_id=task_id
        self.history=self._histories.setdefault(task_id,[])

    def bind_key(self,key):
        """In-memory visitor object only; never persisted or placed in env."""
        self._api_key=key or None

    def call(self,op,*,task_id='original-01',query=None,page='Overview',history=None,controls=None,**extra):
        if self.active_task_id != task_id:self.select_task(task_id)
        message=dict(op=op,task_id=task_id,session_id=self.session_id,workspace=str(self.workspace),**extra)
        if query is not None:
            message.update(query=query,page=page,history=deepcopy(history if history is not None else self.history[-10:]),request_time=datetime.now(timezone.utc).isoformat(),controls=controls or {})
        # Provider credentials cannot cross this boundary, even if configured in
        # the launcher. Optional pinned model path is an explicit local resource.
        allowed=('PATH','TMPDIR','LANG','LC_CTYPE','LC_ALL','LAD_MPNET_PATH','LAD_MODEL_PYTHON')
        env={k:os.environ[k] for k in allowed if k in os.environ}
        env.update(PYTHONDONTWRITEBYTECODE='1',HF_HUB_OFFLINE='1',TRANSFORMERS_OFFLINE='1',HF_HUB_DISABLE_TELEMETRY='1',TOKENIZERS_PARALLELISM='false',OMP_NUM_THREADS='1')
        child=subprocess.run([self.python,'-B',str(CORE/'public_core_worker.py')],input=json.dumps(message,ensure_ascii=False),text=True,capture_output=True,timeout=180,cwd=CORE,env=env)
        try:value=json.loads(child.stdout)
        except ValueError:raise CoreFailure('CORE_WORKER_INVALID_JSON:'+child.stderr[-1000:]) from None
        if child.returncode or value.get('ok') is not True:raise CoreFailure(value.get('error','CORE_WORKER_FAILED'))
        return value['result']

    def replay(self,task_id,mode):
        rows=[r for r in responses() if r['task_id']==task_id and r['mode']==mode]
        if len(rows)!=1:raise ValueError('NO_HISTORICAL_RESPONSE_FOR_NEW_INPUT')
        result=deepcopy(rows[0])
        if hashlib.sha256(result['answer'].encode()).hexdigest()!=result['answer_sha256']:raise ValueError('REPLAY_ANSWER_HASH_MISMATCH')
        result['runtime_profile']='REPLAY'
        result['generation']='SAVED_HISTORICAL_ANSWER_NO_NEW_MODEL_CALL'
        return result

    def components(self,query,*,task_id='original-01',page='Overview',rag=True,memory=True,planning=False,controls=None):
        # Explicit UI bits are test/demonstration demands, never P3 inference.
        route=dict(rag_required=bool(rag),memory_required=bool(memory),planning_required=bool(planning),provider_identity='PUBLIC_EXPLICIT_COMPONENT_GATE_NO_P3')
        result=self.call('prepare',task_id=task_id,query=query,page=page,controls=controls,route=route,memory_backend='LEXICAL')
        result.update(runtime_profile='COMPONENTS',generation='NO_LLM_NO_NATURAL_ANSWER_GENERATION',route=route)
        return result

    @staticmethod
    def value(response,payload):
        # Accept native provider completion shape or a test transport object.
        if not isinstance(response,dict):response=response.model_dump(mode='json')
        if response.get('model') and response['model'] != payload['model']:
            raise CoreFailure('PROVIDER_RETURNED_MODEL_MISMATCH')
        choice=response.get('choices',[{}])[0]
        if choice.get('finish_reason') not in ('stop',None):raise CoreFailure('PROVIDER_COMPLETION_NOT_STOP')
        message=choice.get('message',{})
        if message.get('refusal'):raise CoreFailure('PROVIDER_REFUSAL')
        try:value=json.loads(message['content'])
        except (KeyError,ValueError,TypeError):raise CoreFailure('PROVIDER_OUTPUT_INVALID_JSON') from None
        from jsonschema import Draft202012Validator
        schema=payload['response_format']['json_schema']['schema']
        if list(Draft202012Validator(schema).iter_errors(value)):raise CoreFailure('PROVIDER_OUTPUT_SCHEMA_MISMATCH')
        return value

    def live(self,query,*,task_id='original-01',page='Overview',controls=None,transport=None,memory_backend='HYBRID'):
        """Exact frozen P3 -> source/core -> typed candidate/check -> FINAL.

        A supplied test transport validates the same payloads without paid calls.
        Live MEMORY requires the declared optional pinned MPNet resource.
        """
        if transport is None:
            if not self._api_key:raise PermissionError('VISITOR_KEY_REQUIRED')
            from openai import OpenAI
            client=OpenAI(api_key=self._api_key,max_retries=0,timeout=60)
            send=lambda payload:client.chat.completions.create(**payload)
            kind='LIVE_VISITOR_KEY'
        else:
            client=None
            send=transport.send
            kind='MOCK_EXACT_CORE_NO_PAID_CALL'
        trace=[]
        def perform(role,payload):
            trace.append({'role':role,'payload_sha256':hashlib.sha256(json.dumps(payload,sort_keys=True,ensure_ascii=False).encode()).hexdigest(),'model':payload['model'],'max_tokens':payload['max_tokens']})
            return self.value(send(payload),payload)
        try:
            shared=dict(task_id=task_id,query=query,page=page,controls=controls)
            routing=self.call('p3_requests',**shared)
            # Check all exact three role payloads. B4 contains legacy extra bits;
            # only its planning bit supplies the planning demand.
            role_values={role:perform(role,payload) for role,payload in routing['requests'].items()}
            route=dict(rag_required=role_values['RAG']['rag_required'],memory_required=role_values['MEMORY']['memory_required'],planning_required=role_values['B4_PLANNING']['planning_required'],provider_identity='ACTUAL_FROZEN_P3' if transport is None else 'MOCK_TRANSPORT_NO_P3_INFERENCE')
            prepared_result=self.call('prepare',**shared,route=route,memory_backend=memory_backend)
            if prepared_result['source']['primary_sha256'] != routing['source']['primary_sha256']:
                raise CoreFailure('FROZEN_P3_PRIMARY_CHANGED_AT_PREPARE')
            prepared=prepared_result['prepared']
            accepted=None
            issues=[]
            planner=prepared['planner']
            if planner and planner['status']=='CANDIDATE_PENDING_DISABLED_TRANSPORT':
                payload=self.call('candidate_payload',**shared,prepared=prepared)
                candidate=perform('CANDIDATE',payload)
                issues=self.call('check_candidate',**shared,prepared=prepared,candidate=candidate)['issues']
                if issues:
                    payload=self.call('candidate_payload',**shared,prepared=prepared,previous=candidate,issues=issues)
                    candidate=perform('CANDIDATE_REPAIR',payload)
                    issues=self.call('check_candidate',**shared,prepared=prepared,candidate=candidate)['issues']
                if not issues:accepted=candidate
            final_payload=self.call('final_payload',**shared,prepared=prepared,accepted_plan=accepted,candidate_failed=bool(issues))
            value=perform('FINAL',final_payload)
            checked=self.call('check_final',**shared,value=value,evidence_ids=prepared['trace']['retained_evidence_ids'])['issues']
            if checked:raise CoreFailure('FINAL_CHECK_FAILED:'+','.join(map(str,checked)))
            result=dict(runtime_profile='LIVE',generation=kind,answer=value['answer'],cited_evidence_ids=value['cited_evidence_ids'],accepted_plan=accepted,candidate_issues=issues,route=route,provider_trace=trace,frozen_p3=routing['receipt'],core=prepared_result,semantic_support='NOT_CHECKED',live_model_call=transport is None)
            self.history += [{'role':'user','content':query},{'role':'assistant','content':value['answer']}]
            return result
        finally:
            if client is not None:client.close()

    def memory_list(self,task_id):return self.call('memory_list',task_id=task_id,query='Read my explicit learning memory',page='Overview')

    def memory_write(self,task_id,content,memory_type,*,consent,target_memory_id=None):
        if not isinstance(content,str) or not 0<len(content.strip())<=1000:raise ValueError('MEMORY_TEXT_LENGTH')
        return self.call('memory_write',task_id=task_id,query='Save my explicit learning memory',page='Overview',content=content.strip(),memory_type=memory_type,consent=bool(consent),target_memory_id=target_memory_id)
