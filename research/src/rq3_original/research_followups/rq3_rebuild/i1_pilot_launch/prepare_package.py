"""Build a new dormant proposal from exact exposed source recipes, no API client."""
from pathlib import Path
import json
import sys
ROOT=Path(__file__).resolve().parents[3]
sys.path.insert(0,str(ROOT))
from utils.c4_rebuild.i1.common import HOME, sha, canonical, load, write_once
from utils.c4_rebuild.i1.frozen_p3 import FrozenP3, ROLE_NAMES
from utils.c4_rebuild.i1.schemas import CANDIDATE, FINAL, VERSION
from utils.c4_rebuild.i1.policy import APPROVAL_VERSION, APPROVAL_SCHEMA, CONFIG_VERSION
from utils.c4_rebuild.i1.worker import OfflineWorker
from utils.c4_rebuild.contracts import Mode


def main():
    frozen=FrozenP3();worker=OfflineWorker()
    old=load(ROOT/'research_followups/rq3_rebuild/i0_human_integration/PILOT_TASKS.json')
    task_ids=[x['id'] for x in old['tasks']]
    modes=[m.value for m in Mode]
    config=dict(schema_version=CONFIG_VERSION,role_contract_version=VERSION,approved=False,
        author_signature=None,author_date=None,source_kind='SYNTHETIC_MODEL_AUTHORED_EXPOSED',
        task_ids=task_ids,modes=modes,frozen_p3_identity=frozen.identity,
        generation_roles={r:dict(model='gpt-4o-mini-2024-07-18',temperature=0,max_output_tokens=2048,tools=False,stream=False)
                          for r in ('CANDIDATE','FINAL')},
        initial_slot_ceilings=dict(ROUTE=36,CANDIDATE=24,FINAL=72),max_attempts_per_slot=2,
        aggregate_attempt_ceiling=264,sdk_max_retries=0,transport_timeout_seconds=30,
        offline_worker_timeout_seconds=150,minimum_start_interval_seconds=2.0,
        max_request_input_byte_units=36256,proposed_money_ceiling_usd=2.0,
        uncached_usd_per_million=dict(input=0.15,output=0.6),
        price_reference='https://developers.openai.com/api/docs/models/gpt-4o-mini',price_checked_date='2026-09-07',
        candidate_repair='ONE_FOR_CONCRETE_SCHEMA_OR_ENCODED_ISSUES_WITHIN_TWO_TOTAL_ATTEMPTS',
        route_retry='ONE_IDENTICAL_STRUCTURAL_OR_TRUNCATION_RETRY',
        final_retry='ONE_IDENTICAL_STRUCTURAL_OR_TRUNCATION_RETRY',
        transport_retry='RATE_LIMIT_ONCE; UNKNOWN_COMPLETION_REQUIRES_EXTERNAL_ACK_WITHIN_TWO_TOTAL',
        future_use_policy='RECONFIRM_FOR_SCHEDULE_ORDINARY_SCOPED_SNAPSHOT_WITH_WARNINGS',
        memory_component='M1_HYBRID_LINKS_DEV_CANDIDATE',
        preparation_memory_backend='LEXICAL_NATIVE_DIAGNOSTIC',
        retriever='R0_PROVISIONAL_ENGINEERING_BASELINE_R2_UNSELECTED',
        human_evaluation=dict(criteria='H0_SUPERVISOR_EIGHT',sample_size=None,raters=None,
            applicability=None,aggregation=None,multi_page_observation=None,approved=False))
    write_once(HOME/'PILOT_CONFIGURATION_PROPOSED.json',config)
    write_once(HOME/'FROZEN_ROLE_REGISTRY.json',frozen.receipt())
    for name,value in [('CANDIDATE_STRICT_V1.json',CANDIDATE),('FINAL_STRICT_V1.json',FINAL),('APPROVAL_V1.json',APPROVAL_SCHEMA)]:
        write_once(HOME/'schemas'/name,value)
    approval={k:'' for k in APPROVAL_SCHEMA['required']}
    approval.update(schema_version=APPROVAL_VERSION,status='PENDING_AUTHOR_APPROVAL',
        scope='EXPOSED_SYNTHETIC_ENGINEERING_PILOT_ONLY',resume_unknown_attempts=[],protocol_deviations=[])
    write_once(HOME/'EXTERNAL_APPROVAL_TEMPLATE.json',approval)
    sources=[];routes=[];groups={}
    for slot in task_ids:
        source=worker.call(dict(op='source',slot=slot))
        sources.append(dict(task_id=slot,source_sha256=sha(source),primary_sha256=source['primary_sha256'],source=source))
        groups.setdefault(source['primary_sha256'],[]).append(slot)
        for role in ROLE_NAMES:
            payload=frozen.request(role,source['primary'])
            routes.append(dict(task_id=slot,role=role,request_sha256=sha(payload),payload=payload,
                utf8_payload_bytes=len(canonical(payload)),actual_provider_response=None))
    manifest=dict(schema_version='I1_TASK_MANIFEST_V1',origin='SYNTHETIC_MODEL_AUTHORED_EXPOSED',
        task_ids=task_ids,modes=modes,sources=sources,
        same_input_groups=[dict(primary_sha256=k,task_ids=v) for k,v in groups.items()],
        old_stub_bit_ignored=True,actual_route_results_present=False)
    write_once(HOME/'TASK_MANIFEST.json',manifest)
    write_once(HOME/'ROUTE_REQUEST_REGISTRY.json',dict(status='UNSENT_EXACT_FROZEN_ROLE_MESSAGES',requests=routes))
    print(dict(tasks=len(task_ids),unique_primary_inputs=len(groups),route_blueprints=len(routes)))


if __name__=='__main__':main()
