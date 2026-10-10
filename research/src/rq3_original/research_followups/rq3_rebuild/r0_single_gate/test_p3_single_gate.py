"""Synthetic-only tests. No real queries, corpus build or Generator execution."""
from dataclasses import asdict, replace
import ast
import sys
import types
import unittest
from unittest.mock import patch, Mock
from offline_common import BASE, ROOT, git, diagnostic_exit

sys.path.insert(0, str(ROOT))
from utils import course_material_retriever as legacy
from utils.c4_rag import retrievers
from utils.c4_rag.provider import C4CourseRAGProvider
from utils.c4_real_adapters import C4SelectedR0CourseRAGAdapter, EXPECTED_R0_CORPUS_SHA256
from utils.c4_real_contracts import C4Mode, C4RealRequest, MODE_POLICIES, P3CapabilityRoute
from utils.c4_real_service import C4RealService
from utils.c4_real_trace import C4TraceRecorder
from evaluation.rq3_real_c4.mock_providers import build_mock_dependencies

TRACES = []
BASE_MODULE = types.ModuleType('r0_original_base_for_synthetic_tests')
BASE_MODULE.__file__ = str(ROOT / 'utils/course_material_retriever.py')
sys.modules[BASE_MODULE.__name__] = BASE_MODULE
BASE_TEXT = git('show', BASE + ':utils/course_material_retriever.py').decode()
exec(compile(BASE_TEXT, '<verified-base-legacy>', 'exec'), BASE_MODULE.__dict__)


def chunk(identity='synthetic-a', *, text=None, week='W4', kind='weekly_page'):
    return legacy.CourseChunk(identity, 'System Data/Module/Module Weekly Pages.html', kind,
        'Synthetic W4 laboratory', text or ' '.join(['synthetic explanation laboratory procedure example'] * 8),
        week=week, page='Lecture', task_type='course_material')


def retriever_for(chunks):
    value = retrievers.C4RAGLegacyLexical.__new__(retrievers.C4RAGLegacyLexical)
    value.chunks = tuple(chunks)
    # Synthetic fixture identity; never asserted to be a real corpus hash verification.
    value.corpus_hash = EXPECTED_R0_CORPUS_SHA256
    return value


def provider_for(chunks):
    provider = C4CourseRAGProvider.__new__(C4CourseRAGProvider)
    provider._retriever = retriever_for(chunks)
    provider.implementation_id = retrievers.R0_ID
    return provider


def request_for(query='W4', mode=C4Mode.C5_FULL_C4, student='synthetic-learner-a', history=()):
    return C4RealRequest('synthetic-request', 'synthetic-scenario', mode, query, 'Overview',
                         {'synthetic': True}, history, student, 'synthetic-session', 'synthetic-reset')


def run_slice(adapter, *, route=None, request=None, clarify=False):
    req = request or request_for()
    deps, _, _, _ = build_mock_dependencies(route=route or P3CapabilityRoute(True, False, False), clarify=clarify)
    deps = replace(deps, course_rag=adapter)
    recorder = C4TraceRecorder(req)
    with patch.object(deps.generator, 'generate', side_effect=AssertionError('GENERATOR_FORBIDDEN')):
        state = C4RealService(deps)._run_pre_generation(req, recorder, payload_builder=None)
    return state, recorder


class SingleGateTests(unittest.TestCase):
    def setUp(self):
        # Corpus loading is always forbidden in this synthetic suite.
        self.no_load = patch.object(legacy, 'load_course_material_chunks', side_effect=AssertionError('REAL_CORPUS_FORBIDDEN'))
        self.no_load.start()
        self.addCleanup(self.no_load.stop)

    def test_p3_false_no_ranking_or_corpus_access(self):
        adapter = C4SelectedR0CourseRAGAdapter()
        with patch.object(legacy, '_score_chunk', wraps=legacy._score_chunk) as score:
            state, trace = run_slice(adapter, route=P3CapabilityRoute(False, False, False))
        self.assertFalse(state.activation.rag)
        self.assertIsNone(adapter._provider)
        self.assertEqual(score.call_count, 0)
        self.assertNotIn('course_rag', trace.modules_called)
        TRACES.append({'case': self._testMethodName, 'exit': diagnostic_exit(p3_required=False), 'score_calls': 0})

    def test_all_mode_off_cases_no_ranking(self):
        for mode, policy in MODE_POLICIES.items():
            if policy.allow_rag:
                continue
            adapter = C4SelectedR0CourseRAGAdapter()
            with patch.object(legacy, '_score_chunk', wraps=legacy._score_chunk) as score:
                state, trace = run_slice(adapter, request=request_for(mode=mode))
            self.assertFalse(state.activation.rag)
            self.assertIsNone(adapter._provider)
            self.assertEqual(score.call_count, 0)
            TRACES.append({'case': mode.value, 'exit': diagnostic_exit(mode_allowed=False), 'score_calls': 0})

    def test_clarification_blocks_route_and_ranking(self):
        adapter = C4SelectedR0CourseRAGAdapter()
        state, trace = run_slice(adapter, clarify=True)
        self.assertFalse(state.activation.rag)
        self.assertIsNone(adapter._provider)
        self.assertNotIn('frozen_scenario_route_provider', trace.modules_called)

    def test_invalid_or_missing_route_never_becomes_yes(self):
        for value in (None, {}, True, P3CapabilityRoute(True, False, False, method_id='wrong')):
            deps, _, _, _ = build_mock_dependencies()
            adapter = C4SelectedR0CourseRAGAdapter()
            deps = replace(deps, course_rag=adapter)
            with patch.object(deps.p3_router, 'route', return_value=value):
                with self.assertRaises((TypeError, ValueError)):
                    C4RealService(deps)._run_pre_generation(request_for(), C4TraceRecorder(request_for()), payload_builder=None)
            self.assertIsNone(adapter._provider)
        for bad in ('false', 1, None):
            with self.assertRaises(TypeError):
                P3CapabilityRoute(bad, False, False)

    def test_access_denied_and_wrong_corpus_block_before_ranking(self):
        provider = provider_for([chunk()])
        provider._retriever.corpus_hash = 'unapproved-other-course'
        with patch.object(legacy, '_score_chunk', wraps=legacy._score_chunk) as score:
            with self.assertRaisesRegex(ValueError, 'corpus identity mismatch'):
                run_slice(C4SelectedR0CourseRAGAdapter(provider))
            with patch('utils.c4_real_adapters.C4CourseRAGProvider', side_effect=PermissionError('synthetic access denied')):
                with self.assertRaises(PermissionError):
                    run_slice(C4SelectedR0CourseRAGAdapter())
        self.assertEqual(score.call_count, 0)
        TRACES.append({'case': self._testMethodName, 'exit': diagnostic_exit(access_blocked=True), 'score_calls': 0})

    def test_p3_yes_old_rejects_ranks_once_and_legacy_stays_rejected(self):
        corpus = [chunk(), chunk('synthetic-b')]
        provider = provider_for(corpus)
        self.assertFalse(legacy.should_use_course_retrieval('W4', 'course_content_question'))
        adapter = C4SelectedR0CourseRAGAdapter(provider)
        with patch.object(legacy, '_score_chunk', wraps=legacy._score_chunk) as score, \
             patch.object(legacy, 'retrieve_course_chunks', wraps=legacy.retrieve_course_chunks) as entry:
            state, _ = run_slice(adapter)
            self.assertEqual(entry.call_count, 1)
            self.assertEqual(score.call_count, len(corpus) + len(state.course_rag.sources))
            self.assertEqual([c.kwargs['chunk'].chunk_id for c in score.call_args_list[:len(corpus)]], [c.chunk_id for c in corpus])
        self.assertTrue(state.course_rag.sources)
        self.assertFalse(legacy.retrieve_course_chunks('W4', 'course_content_question').retrieval_used)
        TRACES.append({'case': self._testMethodName, 'exit': diagnostic_exit(ranking=True, status=state.course_rag.result_status),
                       'ranking_passes': 1, 'candidate_score_calls': len(corpus), 'selected_score_reporting_calls': len(state.course_rag.sources)})

    def test_irrelevant_corpus_still_no_result(self):
        adapter = C4SelectedR0CourseRAGAdapter(provider_for([chunk(week='W9')]))
        with patch.object(legacy, '_score_chunk', wraps=legacy._score_chunk) as score:
            state, _ = run_slice(adapter, request=request_for('zyzzyva'))
        self.assertEqual(score.call_count, 1)
        self.assertEqual(state.course_rag.result_status, 'NO_RESULT')
        self.assertEqual(state.course_rag.sources, ())
        TRACES.append({'case': self._testMethodName, 'exit': diagnostic_exit(ranking=True, status='NO_RESULT'), 'score_calls': 1})

    def test_authorised_empty_corpus_never_falls_back(self):
        result = legacy.retrieve_course_chunks('W4', upstream_authorised_chunks=())
        self.assertFalse(result.retrieval_used)
        self.assertEqual(result.reason, 'No course-material chunks were available.')

    def test_authorised_corpus_ignores_foreign_global_cache(self):
        corpus = [chunk()]
        foreign = chunk('other-learner-private-chunk', text='private learner marker')
        with patch.object(legacy, '_CHUNK_CACHE', [foreign]), \
             patch.object(legacy, '_score_chunk', wraps=legacy._score_chunk) as score:
            result = provider_for(corpus).retrieve('W4', 'Overview', (), upstream_authorised=True)
        self.assertEqual(result.chunk_ids, ('synthetic-a',))
        touched = [c.kwargs.get('chunk', c.args[2] if len(c.args) > 2 else None) for c in score.call_args_list]
        self.assertNotIn(foreign, touched)

    def test_cross_learner_scope_does_not_supply_private_history_to_ranker(self):
        adapter = C4SelectedR0CourseRAGAdapter(provider_for([chunk()]))
        for learner in ('synthetic-learner-a', 'synthetic-learner-b'):
            req = request_for(student=learner, history=({'role': 'user', 'content': learner + ' private marker'},))
            with patch.object(legacy, '_score_chunk', wraps=legacy._score_chunk) as score:
                state, _ = run_slice(adapter, request=req)
            self.assertEqual(tuple(s.source_id for s in state.course_rag.sources), ('synthetic-a',))
            self.assertNotIn('private marker', repr(score.call_args_list))
            self.assertNotIn('private marker', repr(state.course_rag.sources))

    def test_cache_rechecks_access_before_serving(self):
        provider = provider_for([chunk()])
        adapter = C4SelectedR0CourseRAGAdapter(provider)
        run_slice(adapter)
        provider._retriever.corpus_hash = 'revoked-corpus'
        with self.assertRaisesRegex(ValueError, 'corpus identity mismatch'):
            run_slice(adapter)

    def test_already_admitted_old_new_scores_ranks_topk_identical(self):
        corpus = [chunk('synthetic-z'), chunk('synthetic-a'), chunk('synthetic-c', week='W5')]
        provider = provider_for(corpus)
        query = 'What does the W4 course material explain?'
        self.assertTrue(legacy.should_use_course_retrieval(query, 'course_content_question'))
        for k in (0, 1, 2, 5):
            with patch.object(legacy, 'load_course_material_chunks', return_value=corpus):
                old = provider.retrieve(query, 'Overview', (), top_k=k)
            new = provider.retrieve(query, 'Overview', (), top_k=k, upstream_authorised=True)
            a, b = old.to_dict(), new.to_dict()
            a.pop('latency_ms'); b.pop('latency_ms')
            self.assertEqual(a, b)
        self.assertEqual(new.chunk_ids[:2], ('synthetic-a', 'synthetic-z'))

    def test_best_threshold_only_positive_tail_and_tie_order_preserved(self):
        corpus = [chunk('b'), chunk('a'), chunk('tail'), chunk('zero')]
        scores = {'a': 2.0, 'b': 2.0, 'tail': 0.1, 'zero': 0.0}
        for best, expected in ((1.999, ()), (2.0, ('a', 'b', 'tail'))):
            scores.update(a=best, b=best)
            with patch.object(legacy, '_score_chunk', side_effect=lambda **kw: scores[kw['chunk'].chunk_id]):
                result = legacy.retrieve_course_chunks('W4', top_k=5, upstream_authorised_chunks=corpus)
            self.assertEqual(tuple(c.chunk_id for c in result.chunks), expected)

    def test_real_scoring_and_legacy_outputs_match_base_commit(self):
        corpus = [chunk('b'), chunk('a'), chunk('c', week='W5')]
        queries = ('W4', 'What do my Resources_views show?', 'What does W4 course material explain?',
                   'What readings should I look at for W4?', 'Explain reflection guidance', '', 'zyzzyva')
        types_ = (None, 'course_content_question', 'reflection_structure_question', 'metric_clarification')
        for query in queries:
            for kind in types_:
                for item in corpus:
                    self.assertEqual(legacy._score_chunk(query, kind, item), BASE_MODULE._score_chunk(query, kind, item))
                for k in (0, 1, 5):
                    with patch.object(legacy, 'load_course_material_chunks', return_value=corpus), \
                         patch.object(BASE_MODULE, 'load_course_material_chunks', return_value=corpus):
                        old = BASE_MODULE.retrieve_course_chunks(query, kind, k)
                        new = legacy.retrieve_course_chunks(query, kind, k)
                    self.assertEqual(asdict(old), asdict(new))

    def test_all_other_legacy_symbols_ast_unchanged(self):
        before = ast.parse(BASE_TEXT)
        after = ast.parse((ROOT / 'utils/course_material_retriever.py').read_text())
        def other(tree):
            return [ast.dump(x, include_attributes=False) for x in tree.body
                    if not isinstance(x, ast.FunctionDef) or x.name != 'retrieve_course_chunks']
        self.assertEqual(other(before), other(after))

    def test_limited_evidence_redaction_and_weak_match_retained(self):
        for kind, expected in (('reading', 'LIMITED_EVIDENCE'), ('moodle_link', 'LIMITED_EVIDENCE'), ('unknown', 'WEAK_MATCH')):
            adapter = C4SelectedR0CourseRAGAdapter(provider_for([chunk(kind=kind)]))
            state, _ = run_slice(adapter)
            self.assertEqual(state.course_rag.result_status, expected)
            for source in state.course_rag.sources:
                self.assertNotIn('text', source.content)
            if expected == 'WEAK_MATCH':
                self.assertEqual(state.course_rag.sources, ())
            TRACES.append({'case': kind, 'exit': diagnostic_exit(ranking=True, status=expected)})

    def test_non_boolean_authorisation_rejected_and_r1_not_enabled(self):
        provider = provider_for([chunk()])
        for value in ('false', 1, None):
            with self.assertRaises(TypeError):
                provider.retrieve('W4', 'Overview', (), upstream_authorised=value)
            with self.assertRaises(TypeError):
                provider._retriever.retrieve('W4', 'Overview', (), upstream_authorised=value)
        provider.implementation_id = retrievers.R1_ID
        with self.assertRaises(ValueError):
            provider.retrieve('W4', 'Overview', (), upstream_authorised=True)

    def test_disabled_and_empty_query_do_not_score_when_authorised(self):
        retriever = retriever_for([chunk()])
        with patch.object(legacy, '_score_chunk', wraps=legacy._score_chunk) as score:
            self.assertEqual(retriever.retrieve('W4', 'Overview', (), retrieval_enabled=False, upstream_authorised=True).chunk_ids, ())
            self.assertEqual(retriever.retrieve('', 'Overview', (), upstream_authorised=True).chunk_ids, ())
        self.assertEqual(score.call_count, 0)
