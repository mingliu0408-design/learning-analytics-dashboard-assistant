"""Apply a fixed, pre-retrieval translation; references are output-only sidecars."""
from v2_common import *
from copy import deepcopy
import shutil
import re
import zipfile

def translate(value, mapping):
    if isinstance(value, str): return mapping.get(value, value)
    if isinstance(value, list): return [translate(x, mapping) for x in value]
    if isinstance(value, dict): return {k:translate(v, mapping) for k,v in value.items()}
    return value

def run():
    mapping = read(HERE/'translation_map.json')
    source = HERE/'source_materials'
    if source.exists(): raise FileExistsError('English sources already exist; no automatic retranslation')
    write(HERE/'audit/V1_PRESERVATION_BASELINE.json', {
        str(p.relative_to(ROOT)):sha(p.read_bytes()) for p in V1.rglob('*') if p.is_file()})
    shutil.copytree(V1/'source_materials', source)
    for kind in ('page_states','histories'):
        for p in sorted((source/kind).glob('*.json')):
            obj = translate(read(p), mapping)
            obj['language_version'] = 'EN_V2_TOOL_ASSISTED_UNREVIEWED'
            write(p, obj)
    for p in sorted((source/'memory_operations').glob('*.jsonl')):
        ops = translate(lines(p), mapping)
        for op in ops:
            op['source_char_start'] = 0
            op['source_char_end'] = len(op['source_quote'])
        jsonl(p, ops)
    tasks = translate(lines(V1/'runtime_tasks.jsonl'), mapping)
    jsonl(HERE/'runtime_tasks.jsonl', tasks)
    for name in ('family_design.json','original25_roster.jsonl'):
        shutil.copyfile(V1/name, HERE/name)
    # Preserve all 50 messages as archival material, including old assistant
    # messages. This directory is never imported by preparation or generation.
    (HERE/'legacy_only').mkdir()
    for name in ('source_messages_50.jsonl','Example Conversation Data(5).csv'):
        shutil.copyfile(V1/'legacy_only'/name, HERE/'legacy_only'/name)
    refs = deepcopy(lines(V1/'evaluation_reference.jsonl'))
    for ref in refs:
        ref['reference_version'] = 'EN_V2_DRAFT_NOT_HUMAN_DECISION'
        for fact in ref.get('required_facts', []):
            for ev in fact['evidence']:
                if ev['kind'] == 'HISTORY_SPAN':
                    value = pointer(read(HERE/ev['path']), ev['json_pointer'])
                    ev.update(quote=value, char_start=0, char_end=len(value))
                elif ev['kind'] == 'STRUCTURED_SOURCE':
                    ev['value'] = pointer(read(HERE/ev['path']), ev['json_pointer'])
        if ref.get('family_id') == 'M01':
            ref['required_facts'][2]['fact'] = ('On 2026-08-25 the learner said they had 18 minutes for that occasion and wanted a short outline. '
                'The 2026-08-31 request concerns next time; continued applicability of 18 minutes is unconfirmed.')
            ref['unknowns'].append('Whether the historical 18-minute limit still applies to the next activity.')
            ref['acceptable_alternatives'].append('Recall the prior 18 minutes conditionally, or ask a brief reasonable confirmation; do not enforce it as the current budget.')
        if ref.get('family_id') in ('P01','P02'):
            required, optional = [], []
            for fact in ref['required_facts']:
                (optional if any(e['kind']=='COURSE_SPAN' for e in fact['evidence']) else required).append(fact)
            ref['required_facts'] = required
            ref['required_for_minimal_answer'] = deepcopy(required)
            ref['optional_support'] = optional
            ref['expected_capabilities_design_only'] = [x for x in ref['expected_capabilities_design_only'] if x!='RAG']
            ref['optional_capabilities_design_only'] = ['RAG']
            ref['acceptable_alternatives'].append('Optional course retrieval is not required for the minimal answer. A feasible partial sequence is allowed; no unique answer is imposed.')
        assert all(v is None for v in ref['applicability_by_criterion'].values())
        assert all(v is None for v in ref['human_review'].values())
    jsonl(HERE/'evaluation_reference.jsonl', refs)
    write(HERE/'LANGUAGE_ALIGNMENT.json', dict(version=VERSION, author_approved_language='English',
        translation_status='TOOL_ASSISTED_UNREVIEWED', selection_basis='FIXED_BEFORE_TARGET_RETRIEVAL_ROUTING_OR_ANSWERS',
        v1_preserved=True, task_id_unchanged=True, independent_new_task_count=24,
        pairs=[dict(task_id=a['task_id'],chinese_query=a['query'],english_query=b['query'])
               for a,b in zip(lines(V1/'runtime_tasks.jsonl')[25:],tasks[25:])],
        source_files={str(p.relative_to(HERE)):sha(p.read_bytes()) for p in source.rglob('*') if p.is_file()}))
    packet = Path('/Users/liuming/Downloads/RQ3_ORIGINAL25_PLUS_NEXT_CODEX_TASK_PACKET_2026-09-07.zip')
    (HERE/'task_spec').mkdir()
    with zipfile.ZipFile(packet) as z:
        for name in z.namelist():
            if '/' in name or name.startswith('.'): raise ValueError('Unexpected packet member')
            (HERE/'task_spec'/name).write_bytes(z.read(name))
    write(HERE/'audit/START.json', dict(cwd=str(ROOT),branch='research/rq3-rebuild-i1-pilot-launch',
        starting_head=START_HEAD, clean_start=True, language_authorization='USER_MESSAGE',
        controlled_replay_authorization='USER_MESSAGE', packet_sha256=sha(packet.read_bytes()),
        no_provider=True,no_target_retrieval=True,no_credentials=True))

if __name__=='__main__': offline(); run()
