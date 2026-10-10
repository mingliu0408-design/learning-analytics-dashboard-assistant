"""PUT_VERSION -> real native writer, closed snapshots and six isolated copies.

No query, required_facts, family or evaluation reference drives admission/type.
Only ordinary source roles, structured values and the literal source span do.
"""
from v2_common import *
from copy import deepcopy
import re
from utils.c4_rebuild.memory import m1_dependencies, clone_native_states
from utils.c4_memory.c4_memory_store import C4MemoryStore
from utils.c4_memory.c4_memory_writer import C4MemoryWriter
from utils.c4_rebuild.contracts import Mode
from utils.c4_dashboard_scoped.scope import instant

def map_fact(op):
    value = op['value']; quote = op['source_quote']
    if op['record_type']=='ASSISTANT_SUGGESTION':
        if op['source_role']!='assistant' or value.get('student_adopted') is not False:
            raise ValueError('UNSUPPORTED_SUGGESTION_STATUS')
        return 'PROGRESS_UPDATE', quote, 'SOURCE_PRESERVED_NATIVE_WRITER_REJECTS_UNADOPTED_ASSISTANT'
    if op['record_type']!='FACT' or op['source_role']!='user': raise ValueError('UNSUPPORTED_SOURCE_FACT')
    if 'minutes' in value:
        if re.search(r'\bthis time\b', quote, re.I):
            return 'PROGRESS_UPDATE', quote, 'HISTORICAL_OCCASION_CURRENT_APPLICABILITY_UNCONFIRMED'
        content = quote
        if op['replaces_version'] is not None:
            # The correction mentions both old and new values. Preserve the
            # entire turn, but index its exact new-value clause only.
            candidates = [s.strip() for s in re.split(r'[:;,]',quote)
                          if re.search(r'(?<!\d)'+str(value['minutes'])+r'\s+minutes\b',s)]
            if len(candidates)!=1: raise ValueError('AMBIGUOUS_CORRECTION_VALUE_SPAN')
            content = candidates[0]
        return 'CONSTRAINT', content, 'SOURCE_DECLARED_NEXT_ACTIVITY_NOT_UNBOUNDED_CURRENT_AVAILABILITY'
    if 'goal' in value or 'object' in value: return 'GOAL', quote, 'EXPLICIT_SOURCE_GOAL_OR_CHOICE'
    if set(value)&{'format','avoid','priority','request'}: return 'PREFERENCE', quote, 'EXPLICIT_SOURCE_WORKING_PREFERENCE'
    if set(value)&{'state','colour','use'}: return 'PROGRESS_UPDATE', quote, 'SOURCE_STATE_ONLY'
    raise ValueError('UNMAPPED_STRUCTURED_FACT_VALUE')

def build_state(task, source_binding, destination):
    _, compile_graph, ReadOnlyStore = m1_dependencies()
    from state_harness import snapshot
    destination = Path(destination); destination.mkdir(parents=True, exist_ok=False)
    now = task['query_time']; student = task['scope']['student_id']; course = task['scope']['course_id']
    if source_binding.get('history_path'):
        h = read(HERE/source_binding['history_path'])
        ops = lines(HERE/source_binding['memory_operations_path'])
        messages = {m['message_id']:(s,m) for s in h['sessions'] for m in s['messages']}
        turns = [dict(turn_id=m['message_id'],session_id=s['session_id'],role=m['role'].upper(),
                      content=m['content'],timestamp=m['timestamp'],learner_id=s['student_id'],course_id=s['course_id'])
                 for s in h['sessions'] for m in s['messages']]
    else: ops, messages, turns = [], {}, []
    db = destination/'initial.sqlite'; current = {}; aliases = {}; receipts = []; native_ops = []
    with C4MemoryStore(db, clock=lambda:now) as store:
        writer = C4MemoryWriter(store)
        for i,op in enumerate(ops):
            s,m = messages[op['source_message_id']]
            if (s['student_id'],s['course_id'])!=(student,course): raise ValueError('CROSS_SCOPE_SETUP')
            if op['operation']!='PUT_VERSION' or op['source_session_id']!=s['session_id'] or op['source_role']!=m['role']:
                raise ValueError('SOURCE_OPERATION_IDENTITY')
            if m['content'][op['source_char_start']:op['source_char_end']]!=op['source_quote']:
                raise ValueError('SOURCE_SPAN')
            if op['valid_from']!=m['timestamp'] or instant(m['timestamp'])>=instant(now): raise ValueError('FUTURE_SOURCE')
            prior = current.get(op['memory_key'])
            if (prior and (op['version']!=prior['version']+1 or op['replaces_version']!=prior['version'])) or (not prior and (op['version']!=1 or op['replaces_version'] is not None)):
                raise ValueError('SOURCE_VERSION_CHAIN')
            typ, content, temporal = map_fact(op)
            start = m['content'].index(content); end = start+len(content)
            candidate = dict(operation='UPDATE' if prior else 'ADD',memory_type=typ,
                content=content,target_memory_id=prior['native_id'] if prior else None,confidence=1.0,evidence_span=content)
            result = writer.apply_candidate(student_id=student,source_session_id=s['session_id'],
                source_turn_id=m['message_id'],source_text=m['content'],candidate=candidate,
                source_role=m['role'].upper(),claim_basis='ASSISTANT_ADVICE' if m['role']=='assistant' else 'EXPLICIT_USER_STATEMENT',
                consent_status='NOT_REQUIRED',event_at=m['timestamp'],valid_from=op['valid_from'],valid_to=op['valid_until'])
            if m['role']=='assistant':
                if result.accepted or result.reason_code!='ASSISTANT_ADVICE_NOT_LEARNER_FACT': raise ValueError('ASSISTANT_PROMOTED')
            elif not result.accepted: raise ValueError('NATIVE_WRITE_REJECTED:'+str(result.as_dict()))
            fact_id = 'source-operation-'+str(i)
            if result.accepted:
                current[op['memory_key']] = dict(native_id=result.memory_id,version=op['version'])
                aliases[fact_id] = result.memory_id
            native_ops.append(dict(candidate, fact_id=fact_id,learner_id=student,course_id=course,
                source_turn_id=m['message_id'],source_span_chars=[start,end],
                claim_basis='ASSISTANT_ADVICE' if m['role']=='assistant' else 'EXPLICIT_USER_STATEMENT'))
            receipts.append(dict(operation_index=i,source_operation=op,mapping_type=typ,
                temporal_interpretation=temporal,native_source_span=[start,end],writer_result=result.as_dict()))
        before = snapshot(store)
    with ReadOnlyStore(db,clock=lambda:now) as reopened:
        after = snapshot(reopened); integrity = reopened.integrity_check()
    if before!=after or integrity['integrity_check']!='ok': raise ValueError('NATIVE_REOPEN_MISMATCH')
    target = dict(learner_id=student,course_id=course,session_id='target-session',as_of=now,
        horizon='current explicitly scoped request',query=task['query'],page=task['page'],visible_history=task['visible_history'],
        visibility_rule='Only supplied legitimate visible turns; constructed prior sessions require gated native retrieval')
    source_runtime = dict(source_turns=turns,setup_operations=native_ops,relation_events=[],target=target)
    graph,rejections = compile_graph(source_runtime,{course:db},aliases)
    if rejections: raise ValueError('UNEXPECTED_GRAPH_REJECTION')
    if graph['edges']: raise ValueError('UNSOURCED_RELATION')
    # No assistant proposal and no individual page step becomes ACTIVE_PLAN.
    if any(n['memory_type']=='ACTIVE_PLAN' for n in graph['nodes'].values()): raise ValueError('UNSOURCED_ACTIVE_PLAN')
    write(destination/'graph.json',graph)
    write(destination/'source_events.json',{t['turn_id']:t for t in turns})
    write(destination/'state_readable.json',after)
    copies = {}
    for mode in Mode:
        cloned = clone_native_states({course:db},destination/mode.value)
        p = cloned[course]
        with ReadOnlyStore(p,clock=lambda:now) as ro:
            if snapshot(ro)!=after: raise ValueError('MODE_COPY_MISMATCH')
        p.chmod(0o444)
        copies[mode.value] = file_id(p)
    db.chmod(0o444)
    binding = dict(database=file_id(db),graph=file_id(destination/'graph.json'),
        source_events=file_id(destination/'source_events.json'),mode_copies=copies,
        logical_sha256=sha(after),source_recipe_sha256=sha(dict(turns=turns,operations=ops)))
    report = dict(task_id=task['task_id'],operations=len(ops),accepted_writes=sum(r['writer_result']['accepted'] for r in receipts),
        unindexed_suggestions=sum(not r['writer_result']['accepted'] for r in receipts),
        receipts=receipts,native_rows=len(after['memories']),closed_reopened=True,integrity=integrity,
        mode_copies=6,target_reads=0,source_runtime=source_runtime,
        consent_basis='Author-permitted local constructed/replayed state, not real student consent or external authorization.',
        history_completeness='Constructed source histories only; no original student conversation recovered.')
    write(destination/'setup_receipt.json', report)
    return binding, report
