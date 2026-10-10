"""Native source-operation setup, closed clones, exactly one diagnostic read per case."""
from replay_common import *
import fcntl
from utils.c4_rebuild.memory import m1_dependencies, clone_native_states
from utils.c4_rebuild.i1.memory import I1NativeM1, GENERIC
from utils.c4_rebuild.language import purpose
from utils.c4_rebuild.contracts import Mode, reject_sidecars

def resolved(query):
    p=purpose(query)
    if p['value']=='UNKNOWN':p=dict(p,original_purpose='UNKNOWN',value=GENERIC,expansion='UNSUPPORTED_PURPOSE')
    return p

def setup_one(tid, source, root):
    _,compile_graph,ReadOnlyStore=m1_dependencies()
    from state_harness import snapshot
    from utils.c4_memory.c4_memory_store import C4MemoryStore
    from utils.c4_memory.c4_memory_writer import C4MemoryWriter, StructuredMemoryCandidate
    reject_sidecars(source)
    root.mkdir(parents=True,exist_ok=False)
    db=root/'initial.sqlite'; aliases={};writes=[]
    turns={t['turn_id']:t for t in source['source_turns']}
    with C4MemoryStore(db,clock=lambda:CLOCK) as store:
        writer=C4MemoryWriter(store)
        for op in source['setup_operations']:
            t=turns[op['source_turn_id']];a,b=op['source_span_chars']
            assert t['content'][a:b]==op['evidence_span']==op['content']
            c=StructuredMemoryCandidate.from_mapping({k:op[k] for k in ('operation','memory_type','content','confidence','evidence_span')}|{'target_memory_id':None})
            r=writer.apply_candidate(student_id=LEARNER,source_session_id=t['session_id'],source_turn_id=t['turn_id'],
                source_text=t['content'],candidate=c,source_role=t['role'],claim_basis=op['claim_basis'],
                consent_status=op['consent_status'],event_at=t['timestamp'],valid_from=op['valid_from'],valid_to=op['valid_to'])
            writes.append(dict(alias=op['fact_id'],role=t['role'],event_at=t['timestamp'],outcome=r.as_dict()))
            if not r.accepted:raise ValueError('NATIVE_SETUP_REJECTED:'+str(r.as_dict()))
            aliases[op['fact_id']]=r.memory_id
        before=snapshot(store)
    with ReadOnlyStore(db,clock=lambda:CLOCK) as reopened:
        after=snapshot(reopened);integrity=reopened.integrity_check()
    assert before==after and integrity['integrity_check']=='ok'
    db.chmod(0o444)
    databases={COURSE:db}
    graph,rejections=compile_graph(source,databases,aliases)
    assert not rejections
    # No relation assertion was present in the old operation receipts. Do not invent one.
    assert graph['edges']==[]
    copies={}
    for mode in Mode:
        cloned=clone_native_states(databases,root/mode.value)
        for p in cloned.values():p.chmod(0o444)
        with ReadOnlyStore(cloned[COURSE],clock=lambda:CLOCK) as store:assert snapshot(store)==before
        copies[mode.value]={k:file_id(p) for k,p in cloned.items()}
    write(root/'graph.json',graph);write(root/'source_events.json',turns)
    binding=dict(databases={k:file_id(p) for k,p in databases.items()},graph=file_id(root/'graph.json'),
        source_events=file_id(root/'source_events.json'),mode_copies=copies)
    summary=dict(task_id=tid,writes=writes,accepted_writes=len(writes),stored_rows=len(before['memories']),
        state_origin='CONTROLLED_RECONSTRUCTION_FROM_HISTORICAL_SOURCE_OPERATIONS',original_database_recovered=False,
        consent_semantics='NOT_REQUIRED is local controlled-setting permission only, not evidence of real student consent or external-use permission.',
        clock=CLOCK,clock_kind='EXISTING_EXPERIMENTAL_QUERY_TIME',real_observation_time=None,
        active_plan_adoption='UNKNOWN_SYSTEM_PROPOSALS_ARE_NOT_LEARNER_COMMITMENTS',
        unresolved_relative_time='today/each day are preserved source text; not converted into current availability',
        target_user_corrections='U033 completion and U034 W5 correction remain current user text; target is read-only, no fabricated setup update',
        relation_edges=0,closed_reopened=True,logical_sha256=sha(after),integrity=integrity,clones=6,
        binding=binding,read_status='NOT_RUN')
    write(HERE/f'receipts/memory/{tid}_SETUP.json',summary)
    return binding,summary,graph,turns

def run():
    report_path=HERE/'MEMORY_RESULTS.json'
    if report_path.exists():raise FileExistsError('Finite diagnostic already started; no automatic repeat.')
    root=HERE/'local_private/native';root.mkdir(parents=True,exist_ok=False)
    bindings=read(HERE/'runtime/BINDINGS.json')
    sources={tid:read(checked(bindings['tasks'][tid]['memory_source'])) for tid in NINE}
    # Validate the complete bounded batch before constructing any state or encoder.
    for tid,s in sources.items():
        reject_sidecars(s)
        assert set(s)=={'source_turns','setup_operations','relation_events','target'}
        assert s['target']['as_of']==CLOCK and s['target']['visible_history']==[]
        for op in s['setup_operations']:
            t=next(t for t in s['source_turns'] if t['turn_id']==op['source_turn_id'])
            a,b=op['source_span_chars'];assert t['content'][a:b]==op['content']
    report=dict(started_utc=utc(),setup_writes=0,setup_cases=0,mode_clones=0,read_limit=9,
        reads_started=0,reads_completed=0,read_retries=0,encoder_startups=0,target_writes=0,
        llm_provider_calls=0,p3_calls=0,candidate_calls=0,final_calls=0,judge_calls=0,tasks={})
    write(report_path,report)
    states={}
    for tid,s in sources.items():
        b,summary,graph,turns=setup_one(tid,s,root/tid)
        report['tasks'][tid]=summary;report['setup_writes']+=summary['accepted_writes'];report['setup_cases']+=1;report['mode_clones']+=6
        states[tid]=(b,graph,turns)
        write(report_path,report)
    write(HERE/'runtime/MEMORY_BINDINGS.json',{tid:states[tid][0] for tid in NINE})
    from utils.c4_rebuild.i1.native_backend import I1LocalBackend
    backend=None
    with open('/private/tmp/rq3-rebuild-local-inference.lock','a+') as lock:
        try:
            fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
            report['encoder_startups']+=1;write(report_path,report)
            backend=I1LocalBackend(root)
            write(HERE/'receipts/NATIVE_BACKEND.json',dict(ready=backend.ready,warmup_batches=1,
                worker=file_id(ROOT/'research_followups/rq3_rebuild/m1_memory_completeness/code/native_stage_worker.py'),
                installed_or_downloaded=False))
            for tid,s in sources.items():
                b,graph,turns=states[tid]
                dbs={k:checked(v) for k,v in b['mode_copies']['S3_EVIDENCE_MEMORY'].items()}
                hashes_before={k:file_id(p) for k,p in dbs.items()}
                native=I1NativeM1(dbs,graph,turns,backend=backend)
                p=resolved(s['target']['query']);report['reads_started']+=1;write(report_path,report)
                env,trace=native.read_envelope(s['target'],p['value'])
                authority=native.authority_for(env.payload,trace['original_seed_items'])
                report['reads_completed']+=1
                assert {k:file_id(p) for k,p in dbs.items()}==hashes_before and trace['readonly_state_unchanged']
                r=dict(status=env.payload['status'],purpose_resolution=p,native_ids=[f['native_id'] for f in env.payload['facts']],
                    contents=[dict(content=f['content'],memory_type=f['memory_type'],origin=f['source_ref']['origin'],
                        confirmation=f['source_ref']['confirmation']) for f in env.payload['facts']],
                    raw_seed_count=len(trace['original_seed_ids']),added_ids=trace['added_facts'],
                    retriever_calls=trace['original_read']['retriever_calls'],readonly_unchanged=True,
                    diagnostic='ONE_FORCED_LOCAL_READ_NOT_P3_OUTPUT',future_read_condition='S3/S5 AND actual P3 MEMORY=YES AND clarification gate passes; S0/S1/S2/S4 never read')
                report['tasks'][tid].update(read_status=env.payload['status'],read=r)
                write(HERE/f'receipts/memory/{tid}_READ.json',dict(envelope=env.payload,trace=trace,authority=authority))
                write(report_path,report)
                print(tid,r['status'],'seed',r['raw_seed_count'],'retained',len(r['native_ids']),flush=True)
        except Exception as exc:
            report['interruption']=dict(type=type(exc).__name__,message=str(exc),retry=False)
            raise
        finally:
            if backend:
                report['encoder_batches']=backend.inputs;backend.close();report['worker_exit_code']=backend.process.returncode
            report['ended_utc']=utc();write(report_path,report)

if __name__=='__main__':offline();run()
