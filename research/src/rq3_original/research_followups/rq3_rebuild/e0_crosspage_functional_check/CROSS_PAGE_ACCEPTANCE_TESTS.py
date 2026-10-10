#!/usr/bin/env python3
"""Offline E0 functional audit. No generation, deployment, or frozen replay.

Diagnostic assertions verify observed behavior. Requirement verdicts are separate
PASS/FAIL/UNKNOWN records; passing diagnostics does not mean acceptance passed.
Run once against the specified checkout; --source-root also supports the bundled
minimal, byte-identical runtime snapshot. Fixtures contain invented records only.
"""
from __future__ import annotations

import argparse
import copy
from dataclasses import replace
from datetime import datetime, timezone
import importlib.abc
import json
from pathlib import Path
import re
import sys
import traceback
import unittest

HERE = Path(__file__).resolve().parent
parser = argparse.ArgumentParser()
parser.add_argument('--source-root', type=Path)
parser.add_argument('--output-dir', type=Path, default=HERE)
ARGS = parser.parse_args()
ROOT = (ARGS.source_root or (HERE / 'runtime_snapshot' if (HERE / 'runtime_snapshot').is_dir() else HERE.parents[2])).resolve()
OUT = ARGS.output_dir.resolve()
sys.path.insert(0, str(ROOT))
BLOCKED = []


def audit_hook(event, args):
    if event in {'socket.connect', 'socket.bind', 'socket.getaddrinfo', 'socket.sendto', 'subprocess.Popen', 'os.system'}:
        BLOCKED.append(event)
        raise RuntimeError('E0 forbids network, subprocess, and server execution')


class NoModelImports(importlib.abc.MetaPathFinder):
    def find_spec(self, fullname, path=None, target=None):
        if fullname.split('.')[0] in {'openai', 'anthropic', 'torch', 'transformers', 'sentence_transformers', 'streamlit'}:
            BLOCKED.append('import:' + fullname.split('.')[0])
            raise RuntimeError('E0 forbids model/provider/Streamlit imports')
        return None


sys.addaudithook(audit_hook)
sys.meta_path.insert(0, NoModelImports())
import pandas as pd
from utils.evidence_synthesiser import DashboardData, synthesise_evidence, select_evidence
from utils.c4_real_adapters import C4RealEvidenceSynthesisAdapter, C4RealEvidenceCompilerV1, C4ProviderCompatibleGenerator, FrozenClarificationGateAdapter, canonical_sha256
from utils.c4_real_contracts import C4RealDependencies, C4RealRequest, C4Mode, ExecutionContext, EvidenceItem, EvidenceSynthesisResult
from utils.c4_real_service import C4RealService
from utils.c4_real_streamlit import build_streamlit_c4_request
from utils.c_full_service import build_c_full_context, build_c_full_openai_messages
from evaluation.rq3_real_c4.g2d0_response_format_repair.c4_real_generation_request_renderer_v3 import render_generation_request_v3_with_audit, source_substantive_facts

FIX = json.loads((HERE / 'SYNTHETIC_FIXTURE.json').read_text())
A, B = FIX['learner_aliases']['A'], FIX['learner_aliases']['B']
HISTORY = ({'role': 'user', 'content': 'Please use my activity counts carefully.'}, {'role': 'assistant', 'content': 'Activity counts describe recorded participation.'})
QUERIES = {
    'broad_weekly': 'summarise my learning this week',
    'broad_improvement': 'how can I improve my learning?',
    'lecture_metric': 'What is my completion rate for this lecture?',
    'comparison': 'Compare my Lecture and Debate activity.',
    'all_pages': 'Compare all four dashboard areas.'}
TRACES, ACCEPTANCE, OBSERVATIONS = {}, [], {}


def frames(window=None, only_learner=None):
    """Fixture slicing is explicit test setup, NOT a production scope resolver."""
    result = {}
    for name, rows in FIX['tables'].items():
        kept = []
        for row in rows:
            if window and FIX['row_scope'][row['_fixture_row_id']]['observation_window'] != window:
                continue
            if only_learner is not None and 'ID' in row and row['ID'] != only_learner:
                continue
            kept.append(row)
        result[name] = pd.DataFrame(kept, columns=[*FIX['columns'][name], '_fixture_row_id'])
    return DashboardData(**result)


class ForbiddenDependency:
    def __getattr__(self, name):
        def fail(*args, **kwargs):
            BLOCKED.append('optional_dependency:' + name)
            raise AssertionError('Optional dependency must remain off in E0 C0/C1')
        return fail


def service_for(data, adapter=None):
    evidence = adapter or C4RealEvidenceSynthesisAdapter(dashboard_data=data)
    generator = C4ProviderCompatibleGenerator(execution_authorised=False)
    forbidden = ForbiddenDependency()
    dependencies = C4RealDependencies(
        clarification_gate=FrozenClarificationGateAdapter(), p3_router=forbidden,
        evidence_synthesiser=evidence, course_rag=forbidden,
        learner_memory=forbidden, evidence_compiler=C4RealEvidenceCompilerV1(),
        planner=forbidden, generator=generator, output_guard=forbidden)
    return C4RealService(dependencies), evidence, generator


def request(query, sid=A, mode=C4Mode.C1_EVIDENCE, context=None):
    return C4RealRequest(request_id='SYNTHETIC_REQUEST', scenario_id='SYNTHETIC_SCENARIO',
        mode=mode, current_query=query, current_page='Lecture',
        dashboard_context={} if context is None else context,
        visible_conversation_history=HISTORY, student_id=str(sid),
        session_id='SYNTHETIC_SESSION', state_reset_id='SYNTHETIC_RESET',
        execution_context=ExecutionContext.INTERACTIVE)


def prepare(data, query, sid=A, mode=C4Mode.C1_EVIDENCE, context=None):
    service, adapter, generator = service_for(data)
    prepared = service.prepare_generation_request(request(query, sid, mode, context))
    assert prepared.success, prepared.error
    assert not prepared.generation_sent and generator.transport_call_count == 0
    assert prepared.route is None and prepared.course_rag is None and prepared.learner_memory is None and prepared.planner_result is None
    assert not any('TOKEN_BUDGET_EXCLUDED' in s for s in prepared.compiled_evidence.limitations)
    return prepared, adapter


def numeric_facts(value, path=''):
    """Activity/row/calculation numerics and compact aggregate strings only."""
    found = {}
    if isinstance(value, dict):
        for k, v in value.items():
            if k not in {'metric_definitions', 'data_provenance', 'data_limitations', 'claim_boundary', 'interpretation', 'uncertainty'}:
                found.update(numeric_facts(v, f'{path}.{k}' if path else k))
    elif isinstance(value, list):
        for i, v in enumerate(value):
            found.update(numeric_facts(v, f'{path}[{i}]'))
    elif isinstance(value, (int, float)) and not isinstance(value, bool):
        found[path] = value
    elif isinstance(value, str) and path.split('.')[-1] in {'preparation_pattern', 'participation_pattern', 'reflection_pattern'}:
        found[path] = value
    return found


def row_provenance(data, sid, fact_path):
    page = fact_path.split('.')[0]
    if page == 'overview':
        page = next((p for p in ('lecture', 'debate', 'resources', 'reflection') if p + '_activity_summary' in fact_path), 'overview')
    rows = []
    for table in ('moodle', 'echo', 'gdocs'):
        df = getattr(data, table)
        if df.empty:
            continue
        df = df[pd.to_numeric(df['ID']).eq(sid)]
        if page == 'lecture':
            if 'click' in fact_path:
                if table != 'moodle': continue
                df = df[df.Event.eq('Video_views')]
            elif table != 'echo': continue
            elif (match := re.search(r'(?:records|row_level_records)\[(\d+)\]', fact_path)):
                df = df.iloc[int(match[1]):int(match[1]) + 1]
        elif page in {'debate', 'resources'}:
            if table != 'moodle': continue
            if page == 'resources': df = df[df.Event.eq('Resources_views')]
            else:
                df = df[df.Activity.eq('Debate')]
                metric = next((m for m in ('posts', 'replies', 'views') if '.' + m in fact_path), None)
                if metric: df = df[df.Event.eq('Debate_' + metric)]
        elif page == 'reflection':
            if table != 'gdocs': continue
        else: continue
        for week in ('W1', 'W2'):
            if fact_path.endswith('.' + week) and 'Week' in df:
                df = df[df.Week.eq(int(week[1:]))]
        rows.extend({'table': table, 'row_id': rid, 'scope': FIX['row_scope'].get(rid, {'note': 'SYNTHETIC perturbation'})} for rid in df['_fixture_row_id'])
    return rows


def trace(name, prepared, adapter, data, window=None):
    payload = dict(prepared.provider_generation_payload)
    projected = json.loads(payload['messages'][1]['content'])
    rendered = render_generation_request_v3_with_audit(projected)
    assert sorted(rendered.rendered_substantive_facts) == sorted(source_substantive_facts(projected))
    raw = prepared.dashboard_evidence.items[0].content if prepared.dashboard_evidence else {}
    facts = numeric_facts(raw.get('selected_evidence', {}))
    provider_contents = [i['content'] for i in projected['evidence']['evidence']]
    preserved = all(any(value == numeric_facts(c.get('selected_evidence', c)).get(path) for c in provider_contents if isinstance(c, dict)) for path, value in facts.items())
    assert preserved
    TRACES[name] = {
        'classification': 'SYNTHETIC_FUNCTIONAL_TEST_ONLY', 'current_page': 'Lecture',
        'requested_window': window or 'NOT_RESOLVED_BY_PRODUCTION',
        'input_filter': 'EXPLICIT_FIXTURE_SLICE_NOT_PRODUCTION' if window else 'NO_TIME_FILTER',
        'interval': FIX['windows'].get(window), 'course': 'SYNTHETIC_COURSE_A_TEST_SETUP_ONLY',
        'selected_sources': raw.get('selected_sources', []), 'selected_evidence': raw.get('selected_evidence', {}),
        'native_bundle_evidence_ids': list(prepared.compiled_evidence.evidence_ids),
        'fact_id_note': 'Atomic fact IDs below are audit-assigned JSON paths. Production provides only a bundle hash, not atomic IDs or row lineage.',
        'facts': [{'fact_id': f'SYNTHETIC:{name}:{path}', 'path': path, 'value': value, 'row_provenance': row_provenance(data, A, path), 'survives_provider_projection': True} for path, value in facts.items()],
        'compiled_sha256': prepared.compiled_evidence.compiled_evidence_sha256,
        'compiler_tokens': prepared.compiled_evidence.deterministic_token_count,
        'compiler_budget': prepared.compiled_evidence.deterministic_token_budget,
        'compiled_limitations': list(prepared.compiled_evidence.limitations),
        'actual_prepared_v2_generator_payload': payload,
        'v3_renderer_check': {'text': rendered.text, 'scalar_count': len(rendered.rendered_substantive_facts), 'all_source_scalars_retained': True},
        'modules_called': list(prepared.trace.modules_actually_called),
        'actual_raw_synthesiser_calls': adapter.actual_synthesiser_calls,
        'frozen_pack_reads': adapter.frozen_pack_reads, 'generation_sent': False,
    }


def verdict(case_id, passed, requirement, observation, path='raw adapter + prepared generator'):
    ACCEPTANCE.append({'case_id': case_id, 'path': path, 'status': 'PASS' if passed else 'FAIL', 'requirement': requirement, 'observation': observation})


class E0Tests(unittest.TestCase):
    def test_01_scope_and_hand_arithmetic(self):
        for window, expected_key in [('W1', 'A_W1'), ('W2', 'A_W2'), (None, 'A_ALL')]:
            data = frames(window)
            selected = synthesise_evidence(QUERIES['all_pages'], 'Lecture', A, data)['selected_evidence']
            expected = FIX['hand_expected'][expected_key]
            actual = {'resource_views': selected['resources']['activity_summary']['views'], 'debate_posts': selected['debate']['activity_summary']['posts'], 'debate_replies': selected['debate']['activity_summary']['replies'], 'debate_views': selected['debate']['activity_summary']['views'], 'lecture_video_views': selected['lecture']['activity_summary']['video_views_sum'], 'lecture_mean_percent': selected['lecture']['activity_summary']['average_video_view_percent'], 'lecture_video_clicks': selected['lecture']['activity_summary']['video_clicks'], 'reflection_chars': selected['reflection']['activity_summary']['total_chars']}
            self.assertEqual(actual, expected)
        verdict('E01', True, 'Existing raw aggregators match hand arithmetic on explicitly scoped fixtures.', FIX['hand_expected'])

    def test_02_queries_reach_real_prepared_payload(self):
        data = frames('W1')
        for name, query in QUERIES.items():
            prep, adapter = prepare(data, query)
            trace(name, prep, adapter, data, 'W1')
            selected = prep.dashboard_evidence.items[0].content
            pages = set(selected['selected_evidence'])
            required = {'lecture'} if name == 'lecture_metric' else ({'lecture', 'debate'} if name == 'comparison' else {'lecture', 'debate', 'resources', 'reflection'})
            passed = pages == required
            verdict('E02_' + name, passed, 'Query-sensitive page selection and factual survival to the generator.', {'query': query, 'query_type': selected['query_type'], 'selected_sources': selected['selected_sources'], 'required_pages': sorted(required), 'facts_retained': True})
            self.assertEqual(adapter.actual_synthesiser_calls, 1)
            self.assertEqual(adapter.frozen_pack_reads, 0)

    def test_03_unrelated_learner_raw_filtering(self):
        for key in ('comparison', 'all_pages', 'lecture_metric'):
            both = synthesise_evidence(QUERIES[key], 'Lecture', A, frames('W1'))
            alone = synthesise_evidence(QUERIES[key], 'Lecture', A, frames('W1', A))
            self.assertEqual(both, alone)
        verdict('E03', True, 'Core ID filtering excludes unrelated learner rows before aggregation.', 'Same facts with and without learner B on fresh raw calls.')

    def test_04_week_not_resolved_by_query(self):
        data = frames()
        prep, adapter = prepare(data, 'Compare my Lecture and Debate activity in week 1.')
        trace('week_qualified_comparison_route', prep, adapter, data)
        first_selection = prep.dashboard_evidence.items[0].content
        self.assertEqual(first_selection['query_type'], 'hybrid_course_and_planning')
        self.assertNotIn('debate', first_selection['selected_evidence'])
        verdict('E04_route', False, 'Explicit weekly Lecture-versus-Debate comparison retains both named pages.', {'query_type': first_selection['query_type'], 'selected_sources': first_selection['selected_sources'], 'reason': 'The earlier week-plus-Lecture hybrid classification wins before cross-page relationship classification.'})
        prep, adapter = prepare(data, 'Compare all four dashboard areas for week 1.')
        trace('unresolved_week_1', prep, adapter, data)
        selected = prep.dashboard_evidence.items[0].content['selected_evidence']
        self.assertEqual(selected['debate']['activity_summary']['posts'], 7)
        self.assertIn('W2', selected['debate']['activity_summary']['weekly_event_counts']['posts'])
        verdict('E04', False, 'Unrelated week must be excluded for an explicit week-1 query.', {'expected_posts': 2, 'observed_posts': 7, 'week_2_survives': True, 'no_week_parameter': True})

    def test_05_missing_required_identity(self):
        for missing in (None, '', [], 'SYNTHETIC_NOT_NUMERIC'):
            with self.assertRaises((ValueError, TypeError)):
                synthesise_evidence(QUERIES['comparison'], 'Lecture', missing, frames('W1'))
        for sid in ('', None):
            with self.assertRaises(ValueError):
                request(QUERIES['comparison'], sid=sid if sid is not None else '')
        verdict('E05_student', True, 'Missing/invalid student identity cannot guess a private ID.', 'Raw parser and request empty-ID gate reject these synthetic invalid IDs.')
        prep, _ = prepare(frames(), QUERIES['broad_weekly'])
        self.assertTrue(prep.success)
        verdict('E05_week', False, 'A relative weekly query needs an explicitly resolved authorised week.', 'Preparation succeeds with both windows and no week identity; no clarification is requested.')

    def test_06_missing_page_vs_observed_zero(self):
        base = frames('W1')
        missing = replace(base, moodle=base.moodle[~base.moodle.Activity.eq('Debate')], features=base.features.iloc[0:0])
        zero_features = pd.DataFrame([{'ID': A, 'Debate_posts': 0, 'Debate_replies': 0, 'Debate_views': 0}])
        zero = replace(missing, features=zero_features)
        unrelated_feature = replace(missing, features=pd.DataFrame([{'ID': A, 'Resources_views': 3}]))
        def summary(d): return select_evidence(QUERIES['comparison'], 'Lecture', A, d)['debate']['activity_summary']
        self.assertFalse(summary(missing)['available'])
        self.assertTrue(summary(zero)['available'])
        self.assertEqual(summary(zero)['posts'], 0)
        self.assertTrue(summary(unrelated_feature)['available'])
        verdict('E06_activity', True, 'Missing page versus explicit measured zero needs distinguishable state.', {'missing': summary(missing), 'explicit_zero': summary(zero)})
        verdict('E06_feature', False, 'An unrelated feature row must not make an absent Debate page observed.', summary(unrelated_feature))
        missing_support = replace(base, moodle=base.moodle[~base.moodle.Activity.eq('Resources')], features=base.features.iloc[0:0])
        zero_support = replace(missing_support, features=pd.DataFrame([{'ID': A, 'Resources_views': 0}]))
        m = select_evidence(QUERIES['broad_improvement'], 'Lecture', A, missing_support)['resources']['preparation_summary']
        z = select_evidence(QUERIES['broad_improvement'], 'Lecture', A, zero_support)['resources']['preparation_summary']
        self.assertEqual(m, z)
        verdict('E06_preparation', False, 'Preparation summaries must retain missing versus observed-zero distinction.', {'missing': m, 'observed_zero': z, 'equal': True})

    def test_07_debate_perturbation(self):
        base = frames('W1')
        row = dict(base.moodle[(base.moodle.ID.eq(A)) & base.moodle.Event.eq('Debate_posts')].iloc[0])
        row['_fixture_row_id'] = 'SYNTHETIC:PERTURBED_DEBATE_POST'
        changed = replace(base, moodle=pd.concat([base.moodle, pd.DataFrame([row])], ignore_index=True))
        self.assertTrue(base.echo.equals(changed.echo))
        self.assertTrue(base.moodle[base.moodle.Activity.eq('Lecture')].equals(changed.moodle[changed.moodle.Activity.eq('Lecture')]))
        for name in ('broad_weekly', 'broad_improvement', 'lecture_metric', 'comparison'):
            before, _ = prepare(base, QUERIES[name])
            after, adapter = prepare(changed, QUERIES[name])
            facts_before = numeric_facts(before.dashboard_evidence.items[0].content['selected_evidence'])
            facts_after = numeric_facts(after.dashboard_evidence.items[0].content['selected_evidence'])
            changed_facts = {k: [facts_before.get(k), v] for k, v in facts_after.items() if facts_before.get(k) != v}
            want_change = name != 'lecture_metric'
            verdict('E07_' + name, bool(changed_facts) == want_change, 'Debate-only perturbation affects broad/comparison facts, leaving strict Lecture facts unchanged.', {'substantive_changes': changed_facts, 'prepared_payload_equal': before.provider_generation_payload == after.provider_generation_payload})
            if name == 'comparison':
                self.assertEqual(changed_facts['debate.activity_summary.posts'], [2, 3])
                trace('debate_perturbed_comparison', after, adapter, changed, 'W1')
            if name == 'lecture_metric': self.assertEqual(before.provider_generation_payload, after.provider_generation_payload)

    def test_08_adapter_cache_is_not_learner_scoped(self):
        adapter = C4RealEvidenceSynthesisAdapter(dashboard_data=frames('W1'))
        a, b = request(QUERIES['comparison'], A), request(QUERIES['comparison'], B)
        first = adapter.synthesise(request=a, primary_input=a.primary_input)
        second = adapter.synthesise(request=b, primary_input=b.primary_input)
        fresh = C4RealEvidenceSynthesisAdapter(dashboard_data=frames('W1')).synthesise(request=b, primary_input=b.primary_input)
        self.assertIs(first, second)
        self.assertNotEqual(second.items[0].content, fresh.items[0].content)
        verdict('E08', False, 'Shared raw-adapter cache must isolate learner identity even for equal four-field inputs.', {'second_learner_observed_posts': second.items[0].content['selected_evidence']['debate']['activity_summary']['posts'], 'fresh_second_learner_posts': 8, 'cached_raw_calls': adapter.actual_synthesiser_calls, 'condition': 'Identical JSON Dashboard context, page, query and history; different request.student_id.'})

    def test_09_adapter_cache_ignores_snapshot_changes(self):
        adapter = C4RealEvidenceSynthesisAdapter(dashboard_data=frames('W1'))
        req = request(QUERIES['comparison'])
        before = adapter.synthesise(request=req, primary_input=req.primary_input)
        adapter.dashboard_data = frames('W2')
        after = adapter.synthesise(request=req, primary_input=req.primary_input)
        self.assertIs(before, after)
        verdict('E09', False, 'Raw-cache identity must include source snapshot and authorised interval.', {'observed_posts_after_W2_rebind': 2, 'W2_expected': 5, 'condition': 'Same adapter reused after rebinding DashboardData; primary four-field input unchanged.'})

    def test_10_course_and_optional_text_scope(self):
        base = frames('W1')
        row = dict(base.moodle[(base.moodle.ID.eq(A)) & base.moodle.Event.eq('Debate_posts')].iloc[0])
        row['_fixture_row_id'] = 'SYNTHETIC:OTHER_COURSE_POST'
        changed = replace(base, moodle=pd.concat([base.moodle, pd.DataFrame([row])], ignore_index=True))
        raw = synthesise_evidence('Compare my Lecture and Debate activity in SYNTHETIC_COURSE_A.', 'Lecture', A, changed)
        self.assertEqual(raw['selected_evidence']['debate']['activity_summary']['posts'], 3)
        verdict('E10_course', False, 'Course membership must be enforced before aggregation.', 'Same-ID second-course synthetic event is counted; legacy schemas have no course field and API has no course argument.')
        text = synthesise_evidence('Set a goal for my reflection this week.', 'Lecture', A, base)
        items = text['selected_evidence']['reflection']['student_goals']['items']
        self.assertTrue(any('learner B' in item for item in items))
        verdict('E10_text', False, 'Optional goals/reflections require learner and time filtering too.', {'synthetic_goal_items': items, 'function': '_summarise_optional_text_table receives no student_id'})

    def test_11_feature_aggregate_window_mismatch(self):
        data = replace(frames('W1'), features=pd.DataFrame([{'ID': A, 'Debate_posts': 7, 'Resources_views': 10}]))
        result = synthesise_evidence(QUERIES['all_pages'], 'Lecture', A, data)['selected_evidence']
        self.assertEqual(result['debate']['activity_summary']['posts'], 7)
        self.assertEqual(result['debate']['activity_summary']['weekly_event_counts']['posts'], {'W1': 2})
        verdict('E11', False, 'Period-bound aggregations must not be overridden by all-period features.', {'posts_total': 7, 'W1_raw_posts': 2, 'resource_views_total': 10, 'W1_resource_views': 3})

    def test_12_ui_dataclass_request_fails_before_payload(self):
        req = build_streamlit_c4_request(request_id='SYNTHETIC_UI', scenario_id='SYNTHETIC_UI', mode=C4Mode.C1_EVIDENCE, current_query=QUERIES['comparison'], current_page='Lecture', dashboard_context=frames('W1'), messages=HISTORY, student_id=str(A), session_id='SYNTHETIC_SESSION', state_reset_id='SYNTHETIC_RESET')
        for raw_bound in (False, True):
            service, _, generator = service_for(frames('W1') if raw_bound else None)
            result = service.prepare_generation_request(req)
            self.assertFalse(result.success)
            self.assertIn('TypeError', result.error)
            self.assertFalse(result.generation_sent)
            self.assertEqual(generator.transport_call_count, 0)
            OBSERVATIONS['ui_' + str(raw_bound)] = {'error': result.error, 'errors': list(result.trace.errors), 'modules': list(result.trace.modules_actually_called)}
        verdict('E12', False, 'The checked-in UI request shape must be accepted by integrated preparation.', OBSERVATIONS['ui_False'], 'feature-gated UI shape with real service, no server')

    def test_13_fair_comparison_interfaces(self):
        data = frames('W1')
        visible_lecture = synthesise_evidence(QUERIES['lecture_metric'], 'Lecture', A, data)['selected_evidence']['lecture']
        for name in ('comparison', 'all_pages', 'lecture_metric'):
            # PAGE_ONLY keeps all legitimate visible Lecture rows and metrics,
            # including row records even when another query would omit them.
            baseline = {'selected_evidence': {'lecture': copy.deepcopy(visible_lecture)}}
            page_only, _ = prepare(data, QUERIES[name], mode=C4Mode.C0_ORIGINAL, context=baseline)
            cross_page, adapter = prepare(data, QUERIES[name], context=baseline)
            p = json.loads(page_only.provider_generation_payload['messages'][1]['content'])
            c = json.loads(cross_page.provider_generation_payload['messages'][1]['content'])
            pf = numeric_facts(p['evidence']['evidence'][0]['content']['selected_evidence'])
            cf = numeric_facts(c['evidence']['evidence'][0]['content']['selected_evidence'])
            extra = {k: v for k, v in cf.items() if k.split('.')[0] != 'lecture'}
            self.assertEqual(p['visible_conversation_history'], c['visible_conversation_history'])
            self.assertEqual(bool(extra), name != 'lecture_metric')
            baseline_preserved = all(cf.get(k) == v for k, v in pf.items())
            verdict('E13_current_' + name, baseline_preserved, 'Current C1 keeps every legitimate current-page fact already supplied to C0.', {'baseline_numeric_or_aggregate_facts': len(pf), 'missing_current_page_fact_paths': sorted(set(pf) - set(cf))})
            # Proposed interface contract demonstration ONLY. Cross-page facts
            # are the untouched actual raw adapter output above, not a mock.
            # The proposed wiring adds the same legitimate page input alongside
            # that result before the existing compiler. No product change.
            common_item = EvidenceItem(evidence_id='SYNTHETIC_COMMON_PAGE', evidence_type='SYNTHETIC_LEGITIMATE_VISIBLE_PAGE', content=baseline)
            union = EvidenceSynthesisResult(items=(common_item, *cross_page.dashboard_evidence.items), limitations=cross_page.dashboard_evidence.limitations)
            compiled = C4RealEvidenceCompilerV1().compile(request=request(QUERIES[name], context=baseline), clarification=cross_page.clarification, route=None, activation=cross_page.activation, dashboard_evidence=union, course_rag=None, learner_memory=None)
            self.assertFalse(any('TOKEN_BUDGET_EXCLUDED' in s for s in compiled.limitations))
            payload = C4ProviderCompatibleGenerator().build_request_payload_v2(request=request(QUERIES[name], context=baseline), compiled_evidence=compiled, planner_result=None)
            projected = json.loads(payload['messages'][1]['content'])
            union_facts = {}
            for item in projected['evidence']['evidence']:
                union_facts.update(numeric_facts(item['content']['selected_evidence']))
            self.assertTrue(all(union_facts.get(k) == v for k, v in pf.items()))
            self.assertEqual({k: v for k, v in union_facts.items() if k.split('.')[0] != 'lecture'}, extra)
            rendered = render_generation_request_v3_with_audit(projected)
            self.assertEqual(sorted(rendered.rendered_substantive_facts), sorted(source_substantive_facts(projected)))
            OBSERVATIONS['comparison_' + name] = {'PAGE_ONLY': page_only.provider_generation_payload, 'CURRENT_RAW_C1': cross_page.provider_generation_payload, 'PROPOSED_CROSS_PAGE_SYNTHESIS_INTERFACE_ONLY': payload, 'proposal_not_production_implementation': True, 'baseline_facts': pf, 'substantive_added_facts': extra, 'current_C1_common_page_facts_preserved': baseline_preserved, 'proposed_common_page_facts_preserved': True, 'common_visible_history_preserved': True, 'source_of_added_facts': 'Actual C4 raw adapter + compiler result, not pre-synthesised mock data', 'v3_renderer_all_scalars_retained': True}
        verdict('E13_proposed', True, 'Corrected interface retains baseline facts and adds substantive cross-page facts; same-page control has equal facts.', 'Test-only union at the existing compiler input. No production correction. Broad natural-language cases remain failed E02/E07.')

    def test_14_ordinary_service_payload(self):
        data = frames('W1')
        for name, query in QUERIES.items():
            ctx = build_c_full_context(student_query=query, student_id=str(A), current_page='Lecture', conversation_history=list(HISTORY), existing_session_memory={}, dashboard_data=data, intent_router_mode='keyword_baseline', retrieval_backend='v1')
            messages = build_c_full_openai_messages(ctx)
            evidence = ctx['rq1_evidence_summary']
            # The literal JSON block that the production prompt builder inserts.
            self.assertIn(json.dumps(evidence, ensure_ascii=False, indent=2), messages[1]['content'])
            self.assertFalse(ctx.get('retrieval_used'))
            OBSERVATIONS['ordinary_' + name] = {'selected_sources': evidence.get('selected_sources'), 'query_type': ctx['query_type'], 'source_scope': ctx['source_scope'], 'actual_prepared_messages': messages, 'retrieval_used': False, 'generation_sent': False}
            required = {'lecture'} if name == 'lecture_metric' else ({'lecture', 'debate'} if name == 'comparison' else {'lecture', 'debate', 'resources', 'reflection'})
            verdict('E14_' + name, set(evidence.get('selected_evidence', {})) == required, 'Ordinary shared C_FULL context selects required pages and includes them in generator messages.', {'selected_sources': evidence.get('selected_sources'), 'query_type': ctx['query_type']}, 'ordinary/legacy shared C_FULL service')

    def test_15_no_forbidden_execution(self):
        self.assertEqual(BLOCKED, [])


def dump(name, value):
    (OUT / name).write_text(json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False) + '\n')


if __name__ == '__main__':
    OUT.mkdir(parents=True, exist_ok=True)
    started = datetime.now(timezone.utc).isoformat()
    with (OUT / 'TEST_STDOUT.txt').open('w') as log:
        result = unittest.TextTestRunner(stream=log, verbosity=2).run(unittest.defaultTestLoader.loadTestsFromTestCase(E0Tests))
    dump('PAGE_FACT_TO_GENERATOR_TRACE.json', {'classification': FIX['data_classification'], 'production_atomic_fact_ids': False, 'traces': TRACES})
    dump('FUNCTIONAL_ACCEPTANCE_RESULTS.json', {'requirements': ACCEPTANCE, 'observations': OBSERVATIONS})
    loaded = sorted({str(Path(m.__file__).resolve().relative_to(ROOT)) for m in tuple(sys.modules.values()) if getattr(m, '__file__', None) and Path(m.__file__).resolve().is_relative_to(ROOT) and Path(m.__file__).suffix == '.py' and not Path(m.__file__).resolve().is_relative_to(HERE)})
    dump('RUNTIME_SOURCE_CLOSURE.json', {'source_root': str(ROOT), 'imported_python_files': loaded})
    summary = {'started_at_utc': started, 'finished_at_utc': datetime.now(timezone.utc).isoformat(), 'python': sys.version, 'pandas_version': pd.__version__, 'tests_run': result.testsRun, 'failures': len(result.failures), 'errors': len(result.errors), 'skips': len(result.skipped), 'diagnostic_suite_success': result.wasSuccessful(), 'acceptance_pass': sum(x['status'] == 'PASS' for x in ACCEPTANCE), 'acceptance_fail': sum(x['status'] == 'FAIL' for x in ACCEPTANCE), 'blocked_execution_attempts': BLOCKED, 'provider_calls': 0, 'llm_calls': 0, 'judge_calls': 0, 'model_loads': 0, 'streamlit_launches': 0, 'real_rows_parsed_by_tests': 0, 'limitations': ['Synthetic-only functional results.', 'Fixture time slicing is not implemented production time resolution.', 'No model answers or learning outcomes measured.', 'Legacy context preparation may run its existing deterministic planner with synthetic data; integrated C0/C1 keeps Planning off.']}
    dump('TEST_RESULTS.json', summary)
    print(json.dumps(summary, indent=2))
    raise SystemExit(0 if result.wasSuccessful() else 1)
