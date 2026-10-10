"""Verify frozen sources and assemble review reports/manifests without new retrieval."""
import json
import csv
import subprocess
from collections import Counter
from pathlib import Path
from m1_common import OWNED,M0,REPO,START,sha,object_sha,utc,write_json
from probe_runtimes import snapshot


def main():
    source_paths=subprocess.check_output(['git','ls-tree','-r','--name-only',START,'--',str(M0.relative_to(REPO)),
        'utils/__init__.py','utils/c4_memory'],text=True,cwd=REPO).splitlines()
    source_rows=[]
    for rel in source_paths:
        p=REPO/rel;committed=subprocess.check_output(['git','show',START+':'+rel],cwd=REPO)
        assert p.read_bytes()==committed, 'INHERITED_SOURCE_CHANGED:'+rel
        source_rows.append({'path':str(p),'repository_path':rel,'bytes':p.stat().st_size,
                            'sha256':sha(p),'matches_starting_head':True})
    packet=Path('/Users/liuming/Downloads/RQ3_REBUILD_M1_CODEX_TASK_PACKET_2026-09-06.zip')
    before=json.loads((OWNED/'runtime_diagnostics/stages_v1/SNAPSHOT_BEFORE.json').read_text())
    after=snapshot();assert before==after
    write_json(OWNED/'runtime_diagnostics/FINAL_SNAPSHOT_VERIFICATION.json',{
        'execution_utc':utc(),'unchanged_before_after_all_diagnostics':True,'files':after,
        'scope':'Snapshot byte identity; loaded model and actual inference are separately observed in worker receipts.'})
    env_sources=[]
    base=Path('/Users/liuming/Downloads/duteaiapp_cfull_semantic_integrated_v1_副本3/.venv/lib/python3.13/site-packages/sentence_transformers')
    for rel in ('sentence_transformer/modules/pooling.py','base/modules/transformer.py'):
        p=base/rel;env_sources.append({'path':str(p),'bytes':p.stat().st_size,'sha256':sha(p),
            'use':'Read-only inspection of current installed pooling API and tokenizer serialization; no edits.'})
    native_source=Path('/opt/anaconda3/lib/python3.13/rlcompleter.py')
    env_sources.append({'path':str(native_source),'bytes':native_source.stat().st_size,'sha256':sha(native_source),'use':'Read-only confirmation that traceback line 212 imports readline.'})
    write_json(OWNED/'SOURCE_MANIFEST.json',{'generated_utc':utc(),'starting_head':START,
        'input_packet':{'path':str(packet),'bytes':packet.stat().st_size,'sha256':sha(packet)},
        'inherited_sources':source_rows,'environment_source_inspections':env_sources,
        'model_snapshot':after,'source_scope':'Completed inherited M0 and native Memory modules; attached references; exact local encoder snapshot and existing interpreter packages.',
        'not_accessed':['E1/R1/P1 working directories and unfinished outputs','private historical databases',
             'real student/course payloads','credentials','human/Judge score files'],
        'shared_packages_installed_or_modified':False})
    syntax=[]
    for p in sorted((OWNED/'code').glob('*.py'))+sorted((OWNED/'tests').glob('*.py')):
        compile(p.read_bytes(),str(p),'exec');syntax.append(str(p.relative_to(OWNED)))
    write_json(OWNED/'CODE_VALIDATION.json',{'execution_utc':utc(),'python_syntax_files':syntax,
        'syntax_status':'PASS','no_pyc_created':True,'inherited_byte_checks':len(source_rows)})
    # Confirm the original lexical run reproduces saved baseline fact selections/statuses.
    def csvrows(p):
        with p.open() as f:return list(csv.DictReader(f))
    prior=csvrows(M0/'diagnostics_v2/MEMORY_FIXTURE_DIAGNOSTIC.csv')
    current=csvrows(OWNED/'diagnostics/original_m0_lexical/MEMORY_FIXTURE_DIAGNOSTIC.csv')
    fields=['case_id','condition','coverage_status','retrieved_fact_ids','missing_fact_ids','status']
    assert [[r[k] for k in fields] for r in prior]==[[r[k] for k in fields] for r in current]
    write_json(OWNED/'diagnostics/BASELINE_REPRODUCTION_CHECK.json',{'execution_utc':utc(),
        'rows_compared':len(current),'fields_compared':fields,'all_equal':True,
        'M0_fixtures_and_rank_parameters_unchanged':True,'baseline_harness_runs':1,
        'gate_off_rows_are_stubs_not_P3':True})
    lex=json.loads((OWNED/'diagnostics/linked_lexical_v2/PAIRED_RESULTS.json').read_text())
    hyb=json.loads((OWNED/'diagnostics/linked_hybrid_v3/PAIRED_RESULTS.json').read_text())
    runtime=json.loads((OWNED/'diagnostics/linked_hybrid_v3/RUNTIME_IDENTITY.json').read_text())
    tests=json.loads((OWNED/'test_results_release/TEST_REPORT.json').read_text())
    assert tests['success']
    assert sum(r['encode_calls_during_read'] for r in hyb)==runtime['encode_calls']==54
    status={'phase':'BOUNDED_M1_IMPLEMENTATION_COMPLETE_PENDING_POSTCOMMIT_PACKAGING',
        'linked_prototype':'IMPLEMENTED_OFFLINE_SYNTHETIC_ONLY','semantic_inference':'VERIFIED_EXISTING_VENV_CPU',
        'base_environment':'SIGSEGV_AT_TORCH_IMPORT_ROOT_CAUSE_UNRESOLVED',
        'final_method_selected':False,'production_integration':False,'thesis_changed':False,
        'final_diagnostic_directories':['diagnostics/original_m0_lexical','diagnostics/original_m0_hybrid',
              'diagnostics/linked_lexical_v2','diagnostics/linked_hybrid_v3'],
        'release_tests':tests['tests_run'],'release_tests_passed':tests['passed'],
        'final_package_receipts':'Generated after the single commit: packaging/GIT_RECEIPT.json; external ZIP_READBACK_RECEIPT.json'}
    write_json(OWNED/'STATUS.json',status)
    # The planner fixture is an actual retained output, never a manually completed ideal bundle.
    envelopes=json.loads((OWNED/'diagnostics/linked_lexical_v2/PLANNER_ENVELOPES.json').read_text())
    selected=[e for e in envelopes if e['condition']=='EXPANDED' and e['case_id'] in (
        'SYN-M1-LINKED-13','SYN-M1-LINKED-03','SYN-M1-COMPLETION-CORRECTION','SYN-M1-AMBIGUOUS-PLANS')]
    write_json(OWNED/'PLANNER_ENVELOPE_SYNTHETIC_FIXTURES.json',{'flags':[
        'MODEL_AUTHORED','SYNTHETIC_DEVELOPMENT_FIXTURE','NOT_FOR_INDEPENDENT_TEST'],
        'source':'Exact selected outputs from linked_lexical_v2; no missing fields filled.', 'envelopes':selected})
    lines=['# Development fact coverage and negative controls','',
        'Primary paired outputs: `diagnostics/linked_lexical_v2/` and `diagnostics/linked_hybrid_v3/`.',
        'The same 33 exposed development cases occur in each condition: 16 linked versions of M0, 14 additional controls, and 3 opaque-ID/reordered-graph variants. Repeated implementation runs are not additional cases.', '',
        '| Mode / condition | Full | Partial | Miss | No authorized source | Ambiguous | No match | Not required | Required facts recovered | Wrong matches | Extra facts |',
        '|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|']
    for mode,rows in [('lexical',lex),('hybrid',hyb)]:
        for condition in ('UNEXPANDED','EXPANDED'):
            r=[x for x in rows if x['condition']==condition];c=Counter(x['coverage_status'] for x in r)
            vals=[c[s] for s in ('FULL','PARTIAL','MISS','NO_AUTHORIZED_SOURCE','AMBIGUOUS','NO_MATCH','NOT_REQUIRED')]
            lines.append('| '+mode+' / '+condition+' | '+' | '.join(map(str,vals))+
                ' | '+str(sum(x['correct_facts'] for x in r))+'/52 | '+str(sum(len(x['wrong_match_fact_ids']) for x in r))+
                ' | '+str(sum(len(x['extra_fact_ids']) for x in r))+' |')
    lines += ['', 'All three extra facts are unresolved alternative plans across the two ambiguous cases. They are counted as nonrequired candidates, not as three fabricated facts. No wrong task match outside those ambiguity alternatives was observed on these authored fixtures. This is neither general precision/recall nor an independent evaluation.', '',
        'The 52 required-fact annotations include absent/unauthorized requirements and repeated opaque-ID variants. They are descriptive bookkeeping, not a statistical denominator for a scientific claim. More AVAILABLE is not the objective.', '',
        '| Case | Lexical without → with links | Hybrid without → with links | Expanded lexical missing facts |',
        '|---|---|---|---|']
    h={(r['case_id'],r['condition']):r for r in hyb}
    for a,b in zip(lex[::2],lex[1::2]):
        ca,cb=h[a['case_id'],'UNEXPANDED'],h[a['case_id'],'EXPANDED']
        lines.append('| '+a['case_id']+' | '+a['coverage_status']+' → '+b['coverage_status']+' | '+ca['coverage_status']+' → '+cb['coverage_status']+' | '+(', '.join(b['missing_fact_ids']) or 'none')+' |')
    lines += ['', 'Among the original eight SOURCE_PRESENT families, unchanged lexical retrieval remains 5 full / 3 partial; the same linked-state unexpanded condition has the same split, and expansion gives 8 full. Unexpanded hybrid gives 7 full / 1 partial; linked expansion gives 8 full. These are observed development outcomes, never a required eight-of-eight acceptance rule.', '',
        'The completion correction supersedes the old completed-action fact. Lexical retrieval still misses the replacement correction; expansion does not follow the obsolete completion edge or invent a new link. Hybrid retrieves the correction by ordinary relevance. Both envelopes retain zero completed actions for this corrected case.', '',
        'Withdrawn/unsupported relationship sources do not authorize expansion. Hybrid may independently retrieve still-authorized endpoint facts by relevance: withdrawing a relation is distinct from deleting its endpoint fact. Expired/deleted nodes remain excluded; cross-course/learner edges are rejected; visible duplicates are omitted; no-seed controls do not trigger graph traversal. Two active plans remain ambiguous.', '',
        'The fixed budget stress case remains PARTIAL in both modes. Original semantic type thresholds, lexical threshold, top-k and score fusion were not changed. Engineering caps restrict retained/traversed facts; loading the sidecar and inherited active-record enumeration are not performance-bounded by those caps.', '',
        'Each paired condition used the same database files and graph snapshot. File/logical hashes and the exact original seed items matched; targets wrote no state. Graph candidates, edge receipts, exclusions, kept and omitted facts remain separate in TARGET_TRACES.json. Expectations are evaluated only after runtime returns.']
    (OWNED/'MEMORY_COMPLETENESS_AND_NEGATIVE_CONTROL_RESULTS.md').write_text('\n'.join(lines)+'\n')
    print({'inherited_sources_verified':len(source_rows),'syntax_files':len(syntax),'release_tests':tests['passed']})

if __name__=='__main__':main()
