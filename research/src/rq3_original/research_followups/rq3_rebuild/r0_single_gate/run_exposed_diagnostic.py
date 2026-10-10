"""ONE paired retrospective lexical diagnostic; --execute is single-use.

Reads only saved P3 inputs/routes, mechanism/RAG provenance and six authorised
course sources. Never reads responses, ratings, learner stores or route Gold.
Exports hashes/IDs/counts only. --preflight performs no retrieval.
"""
from __future__ import annotations
import argparse
from collections import Counter
from dataclasses import asdict
from datetime import datetime, timezone
import csv
import io
import json
from pathlib import Path
import sys
import types
from unittest.mock import patch
from zipfile import ZipFile
from offline_common import BASE, BRANCH, I0, I1, OUT, ROOT, PRODUCTION, canonical, digest, git, offline_guard, write_json, diagnostic_exit

sys.path.insert(0, str(ROOT))
FULL = 'C5_FULL_C4'


def prepare():
    assert Path.cwd().resolve() == ROOT
    assert git('branch', '--show-current').decode().strip() == BRANCH
    assert git('rev-parse', 'HEAD').decode().strip() == BASE
    tracked = git('diff', '--name-only', BASE).decode().splitlines()
    assert set(tracked) <= set(PRODUCTION), 'OUT_OF_SCOPE_TRACKED_CHANGE'
    sources = []
    def read(path, expected=None, role='input'):
        path = Path(path)
        data = path.read_bytes()
        observed = digest(data)
        if expected is not None:
            assert observed == expected, 'SOURCE_HASH_MISMATCH:' + path.name
        sources.append({'path': str(path.resolve()), 'bytes': len(data), 'sha256': observed,
                        'expected_sha256': expected, 'verified': True, 'role': role})
        return data
    packet = Path('/Users/liuming/Downloads/RQ3_REBUILD_R0_CODEX_TASK_PACKET_2026-09-06.zip')
    with ZipFile(io.BytesIO(read(packet, role='author-adopted execution specification'))) as z:
        assert z.testzip() is None
        prefix = 'RQ3_REBUILD_R0_CODEX_TASK_PACKET_2026-09-06/'
        manifest = json.loads(z.read(prefix + 'MANIFEST.json'))
        for r in manifest['members_excluding_manifest']:
            b = z.read(prefix + r['path'])
            assert len(b) == r['bytes'] and digest(b) == r['sha256']
            sources.append({'path': str(packet) + '::' + prefix + r['path'], 'bytes': len(b),
                            'sha256': digest(b), 'expected_sha256': r['sha256'], 'verified': True,
                            'role': 'task specification' if not r['path'].startswith('REFERENCES/') else 'locator only'})
    prior_path = ROOT / 'research_followups/rq3_reassessment/pipeline_rag_audit/SOURCE_MANIFEST.json'
    prior = json.loads(read(prior_path, role='prior audit hash anchors'))
    def prior_read(path):
        hits = [r for r in prior['files'] if r['path'].endswith('/' + str(path.relative_to(ROOT)))]
        assert len(hits) == 1, 'PRIOR_ANCHOR_MISSING'
        return read(path, hits[0]['sha256'])
    identity_path = ROOT / 'evaluation/rq3_real_c4/track_r_rag/c4_rag_r0_identity_v1.json'
    identity = json.loads(read(identity_path, role='frozen R0 identity at original version'))
    from utils.c4_rag.corpus import CANONICAL_CFULL_ROOT
    for rel, expected in identity['source_hashes'].items():
        path = ROOT / rel if rel == 'utils/course_metadata.py' else CANONICAL_CFULL_ROOT / rel
        read(path, expected, 'authorised frozen course source; content excluded from review')
    for rel, expected in {**identity['adapter_code_hashes'], **identity['legacy_code_hashes']}.items():
        base_bytes = git('show', BASE + ':' + rel)
        assert digest(base_bytes) == expected, 'BASE_CODE_IDENTITY_MISMATCH'
        sources.append({'path': str(ROOT / rel), 'version': BASE, 'sha256': digest(base_bytes),
                        'bytes': len(base_bytes), 'expected_sha256': expected, 'verified': True,
                        'role': 'historical source bytes from Git; no new identity claim'})
    for rel in (*PRODUCTION, 'utils/c4_real_service.py', 'utils/c4_real_contracts.py', 'utils/c4_real_trace.py'):
        read(ROOT / rel, role='current implementation or unchanged gate contract')
    inputs_data = prior_read(I0 / 'c4_real_p3_route_input_manifest_v1.jsonl')
    mechanism_data = prior_read(I1 / 'c4_real_condition_mechanism_records_frozen_v1.jsonl')
    rag_data = prior_read(I1 / 'c4_real_condition_rag_results_frozen_v1.jsonl')
    anchor = json.loads(read(I1 / 'c4_real_i1_r1_scientific_preservation_manifest_v1.json', role='frozen route hash anchor'))
    route_hash = anchor['scientific_artifacts']['c4_real_p3_routes_frozen_v1.jsonl']['sha256_after']
    routes = [json.loads(line) for line in read(I1 / 'c4_real_p3_routes_frozen_v1.jsonl', route_hash).splitlines()]
    from utils.c4_real_contracts import P3CapabilityRoute, P3_ROUTER_METHOD_ID
    route_map = {}
    for row in routes:
        assert row['scenario_id'] not in route_map
        assert row['method_id'] == P3_ROUTER_METHOD_ID
        P3CapabilityRoute(row['rag_required'], row['memory_required'], row['planning_required'])
        route_map[row['scenario_id']] = row
    ids = sorted(sid for sid, r in route_map.items() if r['rag_required'])
    assert len(ids) == 21
    inputs = {r['scenario_id']: r for r in map(json.loads, inputs_data.splitlines()) if r['scenario_id'] in ids}
    mechanism = {r['scenario_id']: r for r in map(json.loads, mechanism_data.splitlines())
                 if r['mode'] == FULL and r['scenario_id'] in ids}
    saved_rag = {r['scenario_id']: r for r in map(json.loads, rag_data.splitlines())
                 if r['mode'] == FULL and r['scenario_id'] in ids}
    assert set(inputs) == set(mechanism) == set(saved_rag) == set(ids)
    for sid in ids:
        value = inputs[sid]
        h = digest(canonical(value['semantic_input']))
        assert h == value['semantic_input_sha256'] == route_map[sid]['semantic_input_sha256'] == mechanism[sid]['semantic_input_sha256']
        assert mechanism[sid]['route_signature'][0] == '1'
        assert saved_rag[sid]['result'] is not None
        assert digest(canonical(saved_rag[sid]['result'])) == saved_rag[sid]['result_sha256'] == mechanism[sid]['rag_result_sha256']
    read(ROOT / 'evaluation/rq3_real_c4/track_r_rag/c4_rag_r1_identity_v1.json', role='comparison plan configuration only; no R1 execution')
    result = {'task': 'RQ3-REBUILD-R0', 'verified_at_utc': datetime.now(timezone.utc).isoformat(),
              'base_head': BASE, 'branch': BRANCH, 'working_directory': str(ROOT),
              'initial_git_gate': {'pwd_matches': True, 'branch_matches': True, 'head_matches': True,
                                   'tracked_and_untracked_status_empty': True,
                                   'evidence': 'Initial git status --porcelain=v1 was empty before any writes.'},
              'source_status': 'EXACT_INPUTS_AND_AUTHORISED_SOURCE_BYTES_VERIFIED',
              'missing_sources': [], 'files': sources, 'selected_scenario_ids': ids,
              'allowed_diagnostic': 'One pair per selected input; Full P3 RAG=true; raw query/page/history; k=5.',
              'excluded_inputs': ['responses', 'ratings', 'restricted mappings', 'learner Memory stores', 'Gold'],
              'locator_note': 'B source manifest did not list frozen P3 routes; their hash was verified against I1-R1 scientific preservation manifest instead. No observed hash mismatch.'}
    return result, inputs, saved_rag, identity


def run():
    args = argparse.ArgumentParser()
    args.add_argument('--preflight', action='store_true')
    args.add_argument('--execute', action='store_true')
    selected = args.parse_args()
    assert selected.preflight != selected.execute
    with offline_guard() as counters:
        sources, inputs, saved_rag, identity = prepare()
        write_json(OUT / 'SOURCE_MANIFEST.json', sources)
        if selected.preflight:
            print('Preflight PASS: 21 bound inputs; six source hashes; no retrieval or corpus build.')
            return
        attempts = sorted(OUT.glob('SYNTHETIC_TEST_ATTEMPT_*.json'))
        assert attempts and json.loads(attempts[-1].read_text())['passed']
        marker = OUT / 'EXPOSED_DIAGNOSTIC_EXECUTION.json'
        # Exclusive creation prevents accidental repetition even after interruption.
        with marker.open('x') as f:
            json.dump({'status': 'STARTED_DO_NOT_RERUN', 'started_at_utc': datetime.now(timezone.utc).isoformat()}, f)
        from utils import course_material_retriever as legacy
        from utils.c4_real_adapters import C4SelectedR0CourseRAGAdapter
        from utils.c4_rag.provider import C4CourseRAGProvider
        from utils.c4_rag.retrievers import R0_ID
        from utils.c4_real_contracts import C4Mode, C4RealRequest
        provider = C4CourseRAGProvider(implementation_id=R0_ID)
        corpus = provider._retriever.chunks
        assert len(corpus) == identity['chunk_count']
        assert provider._retriever.corpus_hash == identity['chunk_corpus_hash']
        baseline = types.ModuleType('r0_baseline_adapter_for_one_diagnostic')
        baseline.__file__ = str(ROOT / 'utils/c4_real_adapters.py')
        sys.modules[baseline.__name__] = baseline
        exec(compile(git('show', BASE + ':utils/c4_real_adapters.py'), '<base-adapter>', 'exec'), baseline.__dict__)
        old = baseline.C4SelectedR0CourseRAGAdapter(provider)
        new = C4SelectedR0CourseRAGAdapter(provider)
        rows, detail = [], []
        chunk_by_id = {c.chunk_id: c for c in corpus}
        for sid in sorted(inputs):
            raw = inputs[sid]['semantic_input']
            request = C4RealRequest('offline-' + sid, sid, C4Mode.C5_FULL_C4,
                raw['current_query'], raw['current_page'], raw['dashboard_context'],
                tuple(raw['visible_conversation_history']), 'offline-no-learner-store', 'offline-session', 'offline-reset')
            pair = {}
            for label, adapter in (('old', old), ('new', new)):
                scores, selected_rescores = [], []
                original_score = legacy._score_chunk
                def measured(*args, **kwargs):
                    value = original_score(*args, **kwargs)
                    c = kwargs['chunk'] if kwargs else args[2]
                    (scores if kwargs else selected_rescores).append((c.chunk_id, value))
                    return value
                with patch.object(legacy, '_score_chunk', side_effect=measured):
                    result = adapter.retrieve(request=request, evidence=None)
                assert len(scores) in (0, len(corpus)), 'MORE_THAN_ONE_RANKING_PASS'
                ranked = sorted(((cid, score) for cid, score in scores if score > 0), key=lambda x: (-x[1], x[0]))
                passed = bool(ranked and ranked[0][1] >= 2.0)
                expected_ids = [cid for cid, _ in ranked[:5]] if passed else []
                assert [cid for cid, _ in selected_rescores] == expected_ids
                result_dict = json.loads(canonical(asdict(result)))
                sources_detail = [{'chunk_id': s.source_id, 'source_path': s.provenance['source_path'],
                    'source_sha256': s.provenance['source_sha256'],
                    'chunk_text_sha256': digest(chunk_by_id[s.source_id].text.encode()),
                    'chunk_record_sha256': digest(canonical(asdict(chunk_by_id[s.source_id]))),
                    'strength': s.evidence_strength, 'rank': expected_ids.index(s.source_id)+1,
                    'lexical_score': dict(scores)[s.source_id]} for s in result.sources]
                pair[label] = {'ranking_occurred': bool(scores), 'candidate_score_calls': len(scores),
                    'selected_score_reporting_calls': len(selected_rescores), 'passed_threshold': passed,
                    'positive_candidate_count': len(ranked), 'best_score': ranked[0][1] if ranked else None,
                    'status': result.result_status, 'exit': diagnostic_exit(ranking=bool(scores), status=result.result_status),
                    'source_count': len(result.sources), 'strength_counts': dict(Counter(s.evidence_strength for s in result.sources)),
                    'sources': sources_detail, 'result_sha256': digest(canonical(result_dict)),
                    'candidate_scores_sha256': digest(canonical(scores)), 'ranked_candidates_sha256': digest(canonical(ranked)),
                    'source_correctness': 'NOT_ASSESSED', 'independent_sufficiency': 'NOT_ASSESSED'}
                if label == 'old':
                    pair[label]['saved_result_identical'] = result_dict == saved_rag[sid]['result']
            row = {'scenario_id': sid, 'semantic_input_sha256': inputs[sid]['semantic_input_sha256'],
                   'raw_query_sha256': digest(raw['current_query'].encode()),
                   'page_sha256': digest(raw['current_page'].encode()),
                   'visible_history_sha256': digest(canonical(raw['visible_conversation_history'])), 'top_k': 5,
                   'mode': FULL, 'saved_p3_rag_required': True,
                   'additional_search': not pair['old']['ranking_occurred'] and pair['new']['ranking_occurred'],
                   'old_saved_result_identical': pair['old']['saved_result_identical']}
            for label in ('old', 'new'):
                for name in ('exit', 'ranking_occurred', 'candidate_score_calls', 'selected_score_reporting_calls',
                             'passed_threshold', 'source_count', 'status', 'best_score'):
                    row[label + '_' + name] = pair[label][name]
                row[label+'_source_ids'] = '|'.join(s['chunk_id'] for s in pair[label]['sources'])
                row[label+'_strength_counts'] = json.dumps(pair[label]['strength_counts'], sort_keys=True)
            rows.append(row)
            detail.append({'scenario_id': sid, **pair})
        summary = {'status': 'COMPLETED_ONE_PAIRED_DIAGNOSTIC', 'completed_at_utc': datetime.now(timezone.utc).isoformat(),
                   'cases': len(rows), 'paired_passes': 1, 'corpus_hash': identity['chunk_corpus_hash'],
                   'corpus_chunks': len(corpus), 'top_k': 5,
                   'old_searches': sum(r['old_ranking_occurred'] for r in rows),
                   'new_searches': sum(r['new_ranking_occurred'] for r in rows),
                   'additional_searches': sum(r['additional_search'] for r in rows),
                   'additional_search_ids': [r['scenario_id'] for r in rows if r['additional_search']],
                   'old_threshold_passes': sum(r['old_passed_threshold'] for r in rows),
                   'new_threshold_passes': sum(r['new_passed_threshold'] for r in rows),
                   'new_no_result_ids': [r['scenario_id'] for r in rows if r['new_status']=='NO_RESULT'],
                   'old_status_counts': dict(Counter(r['old_status'] for r in rows)),
                   'new_status_counts': dict(Counter(r['new_status'] for r in rows)),
                   'all_21_old_results_match_frozen': all(r['old_saved_result_identical'] for r in rows),
                   'admitted_cases_ranking_unchanged': all(p['old']['candidate_scores_sha256']==p['new']['candidate_scores_sha256'] and p['old']['ranked_candidates_sha256']==p['new']['ranked_candidates_sha256'] and p['old']['sources']==p['new']['sources'] for p in detail if p['old']['ranking_occurred']),
                   'old_adapter_calls': old.retrieval_call_count, 'new_adapter_calls': new.retrieval_call_count,
                   'guard_counters': counters, 'router_calls': 0, 'generator_calls': 0, 'judge_calls': 0,
                   'embedding_inferences': 0, 'alternative_retriever_runs': 0,
                   'interpretation': 'Retrospective engineering diagnostic on exposed inputs; no independent correctness, sufficiency, Recall@k, response-quality or significance claim.'}
        with (OUT / 'EXPOSED_21_CASE_GATE_DIAGNOSTIC.csv').open('x', newline='') as f:
            writer = csv.DictWriter(f, fieldnames=list(rows[0]), lineterminator='\n')
            writer.writeheader(); writer.writerows(rows)
        write_json(OUT / 'EXPOSED_21_CASE_SOURCE_DETAILS.json', detail)
        write_json(OUT / 'EXPOSED_21_CASE_DIAGNOSTIC_SUMMARY.json', summary)
        write_json(marker, summary)
        print(json.dumps(summary, indent=2))

if __name__ == '__main__':
    run()
