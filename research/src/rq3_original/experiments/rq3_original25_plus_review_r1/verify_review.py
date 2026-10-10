"""Focused offline verification of the R1 data revision, using inherited adapters."""
from v2_common import *
offline()
from collections import Counter
from copy import deepcopy
from contextlib import ExitStack
from itertools import permutations
from unittest.mock import patch
import argparse
import sqlite3
import unittest

import run_batch
import adapter
from utils.c4_rebuild.i1.frozen_p3 import FrozenP3, ROLE_NAMES

OLD = HERE.with_name('rq3_original25_plus_v2')
OBSERVED = dict(sidecar_guard_active=False, forbidden_opens=[], source_prepare_files=[])


def guard(event, args):
    if event == 'open' and isinstance(args[0], (str, bytes)):
        p = Path(str(args[0]))
        if p.name.lower() in ('secrets.toml', '.env', 'auth.json', 'credentials.json'):
            raise AssertionError('CREDENTIAL_READ_FORBIDDEN')
        if OBSERVED['sidecar_guard_active']:
            if p.name in ('evaluation_reference.jsonl', 'family_design.json', 'applicability.json',
                          'AUTHOR_DECISIONS.json', 'QUERY_CHANGES.json', 'translation_map.json',
                          'LANGUAGE_ALIGNMENT.json') or set(p.parts) & {'received_review', 'human_review', 'task_spec', 'baseline'}:
                OBSERVED['forbidden_opens'].append(str(p))
                raise AssertionError('SIDECAR_OPEN_IN_PREPARATION')
            if p.is_absolute() and p.is_relative_to(ROOT):
                OBSERVED['source_prepare_files'].append(str(p.relative_to(ROOT)))


sys.addaudithook(guard)


def identity_rows(sources, prepared):
    frozen = FrozenP3()
    grouped = {}
    for row in prepared:
        grouped.setdefault(row['task_id'], {})[row['mode']] = dict(
            module_state_key=row['prepared']['trace']['module_state_key'],
            final_wire_sha256=sha(row['final_wire_preview']))
    return {s['task_id']: dict(primary_sha256=s['primary_sha256'],
        query_utf8_sha256=sha(s['primary']['current_query'].encode()),
        route_cache_keys={role: 'P3:' + role + ':' + sha(frozen.request(role, s['primary'])) for role in ROLE_NAMES},
        modes=grouped[s['task_id']]) for s in sources}


def prepare_and_bind():
    m, tasks, b, c = run_batch.load_run(HERE / 'RUN_MANIFEST.json')
    with ExitStack() as stack:
        for cls in (adapter.R0OnExplicitCorpus, adapter.I1NativeM1):
            stack.enter_context(patch.object(cls, '__init__', side_effect=AssertionError('TARGET_RETRIEVAL_OR_MEMORY_FORBIDDEN')))
        OBSERVED['sidecar_guard_active'] = True
        try:
            run_batch.prepare_batch(m, tasks, b, c, HERE / 'prepared_inputs')
        finally:
            OBSERVED['sidecar_guard_active'] = False
    old = identity_rows(lines(OLD / 'prepared_inputs/SOURCE_INPUTS_49.jsonl'),
                        lines(OLD / 'prepared_inputs/PREPARED_INPUTS_294.jsonl'))
    new = identity_rows(lines(HERE / 'prepared_inputs/SOURCE_INPUTS_49.jsonl'),
                        lines(HERE / 'prepared_inputs/PREPARED_INPUTS_294.jsonl'))
    write(HERE / 'baseline/INPUT_IDENTITIES.json', old)
    write(HERE / 'prepared_inputs/INPUT_IDENTITIES.json', new)
    changed = read(HERE / 'QUERY_CHANGES.json')['changes']
    write(HERE / 'INPUT_IDENTITY_CHANGES.json', dict(
        data_revision=read(HERE / 'REVISION.json')['data_revision'],
        cache_policy='FRESH_R1_INPUTS_NO_V2_ROUTE_OR_RESPONSE_CACHE_COPIED',
        identity_basis='Inherited FrozenP3.request constructs bytes locally; no P3 model call.',
        inherited_schema='ORIGINAL25_PLUS_EN_V2',
        counts=dict(source_primary_changed=sum(old[k]['primary_sha256'] != new[k]['primary_sha256'] for k in old),
            source_primary_unchanged=sum(old[k]['primary_sha256'] == new[k]['primary_sha256'] for k in old),
            route_cache_keys_changed=sum(old[k]['route_cache_keys'][r] != new[k]['route_cache_keys'][r] for k in old for r in ROLE_NAMES),
            module_state_keys_changed=sum(old[k]['modes'][m]['module_state_key'] != new[k]['modes'][m]['module_state_key'] for k in old for m in c['modes']),
            final_wire_previews_changed=sum(old[k]['modes'][m]['final_wire_sha256'] != new[k]['modes'][m]['final_wire_sha256'] for k in old for m in c['modes'])),
        rows=[dict(task_id=r['task_id'], before=old[r['task_id']], after=new[r['task_id']]) for r in changed]))
    write(HERE / 'audit/PREPARATION_ISOLATION.json', dict(
        sidecar_open_guard=True, forbidden_opens=OBSERVED['forbidden_opens'],
        target_retriever_and_memory_constructors_blocked=True, network_and_credentials_guard=True,
        opened_repository_files=sorted(set(OBSERVED['source_prepare_files'])),
        provider_calls=0, p3_calls=0, retrieval_calls=0, embedding_calls=0, judge_calls=0))


class ReviewChecks(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tasks = lines(HERE / 'runtime_tasks.jsonl')
        cls.old_tasks = lines(HERE / 'baseline/runtime_tasks.jsonl')
        cls.refs = lines(HERE / 'evaluation_reference.jsonl')
        cls.old_refs = lines(HERE / 'baseline/evaluation_reference.jsonl')
        cls.manifest = read(HERE / 'RUN_MANIFEST.json')
        cls.binding = read(HERE / 'BINDINGS.json')
        cls.config = read(HERE / 'CONFIG_PROPOSED.json')
        cls.prepared = lines(HERE / 'prepared_inputs/PREPARED_INPUTS_294.jsonl')
        cls.design = read(HERE / 'family_design.json')['tasks']
        cls.pair = {(r['family_id'], r['condition']): r['task_id'] for r in cls.design}
        cls.by_id = {t['task_id']: t for t in cls.tasks}

    def test_01_original25_exact_and_nine_edits_only(self):
        self.assertEqual(self.tasks[:25], self.old_tasks[:25])
        edits = {c['task_id']: c for c in read(HERE / 'QUERY_CHANGES.json')['changes']}
        changed = []
        for old, new in zip(self.old_tasks, self.tasks):
            self.assertEqual(old['task_id'], new['task_id'])
            if old != new:
                c = edits[old['task_id']]
                self.assertEqual(old['query'], c['before'])
                self.assertEqual(new, dict(old, query=c['applied_after']))
                changed.append(old['task_id'])
        self.assertEqual(set(changed), set(edits))
        self.assertEqual(len(changed), 9)

    def test_02_family_and_runtime_inheritance(self):
        self.assertEqual(len(self.design), 24)
        self.assertTrue(all(n == 2 for n in Counter(r['family_id'] for r in self.design).values()))
        self.assertEqual(len({r['family_id'] for r in self.design}), 12)
        for family in ('E01', 'E03', 'P01', 'P03'):
            self.assertEqual(self.by_id[self.pair[family, 'A']]['query'], self.by_id[self.pair[family, 'B']]['query'])
        intake = read(HERE / 'audit/INTAKE.json')['preserved_files']
        for name in ('v2_common.py', 'adapter.py', 'run_batch.py', 'BINDINGS.json', 'CONFIG_PROPOSED.json', 'family_design.json', 'original25_roster.jsonl'):
            self.assertEqual(sha((HERE / name).read_bytes()), intake['experiments/rq3_original25_plus_v2/' + name])
        self.assertEqual(len(self.manifest['task_ids']), 41)
        self.assertFalse(self.manifest['provider_authorized'])
        self.assertEqual(self.manifest['approved_for_run_task_ids'], [])

    def test_03_c01_counts_and_existing_facts(self):
        self.assertEqual(sum(not r['required_facts'] for r in self.old_refs[:25]), 23)
        ready = set(self.manifest['task_ids'])
        self.assertEqual(sum(not r['required_facts'] and r['task_id'] in ready for r in self.old_refs[:25]), 15)
        for old, new in zip(self.old_refs[:25], self.refs[:25]):
            if old['task_id'] in ('original-13', 'original-23'):
                self.assertEqual(old['required_facts'], new['required_facts'])
            self.assertEqual(bool(new['required_facts']), new['task_id'] in ready)
        self.assertIn('一项主要观察', self.refs[0]['minimum_answer_requirements'][0])
        self.assertIn('条件式', self.refs[11]['minimum_answer_requirements'][0])

    def test_04_all_evidence_locations_and_old67_retained(self):
        corpus = {r['chunk_id']: r for r in lines(HERE / 'source_materials/course/corpus.jsonl')}
        checks = []
        for old, new in zip(self.old_refs, self.refs):
            old_ev = [e for f in old['required_facts'] for e in f['evidence']]
            new_ev = [e for f in new['required_facts'] for e in f['evidence']]
            for e in old_ev:
                self.assertIn(e, new_ev)
            for f in new['required_facts'] + new.get('optional_support', []):
                for e in f['evidence']:
                    self.assertTrue((HERE / e['path']).resolve().is_relative_to(HERE))
                    if e['kind'] == 'STRUCTURED_SOURCE':
                        self.assertEqual(canonical(pointer(read(HERE / e['path']), e['json_pointer'])), canonical(e['value']))
                    elif e['kind'] == 'HISTORY_SPAN':
                        value = pointer(read(HERE / e['path']), e['json_pointer'])
                        self.assertEqual(value[e['char_start']:e['char_end']], e['quote'])
                    elif e['kind'] == 'COURSE_SPAN':
                        self.assertEqual(corpus[e['chunk_id']]['text'][e['char_start']:e['char_end']], e['quote'])
                        self.assertEqual((HERE / e['readable_path']).read_text()[e['document_char_start']:e['document_char_end']], e['quote'])
                        self.assertEqual(sha((HERE / e['origin_raw_path']).read_bytes()), e['document_version'])
                    else:
                        self.fail('Unsupported locator: ' + e['kind'])
                    checks.append(dict(task_id=new['task_id'], kind=e['kind'], locator_sha256=sha(e), passed=True))
        old_count = sum(len(f['evidence']) for r in self.old_refs for f in r['required_facts'])
        self.assertEqual(old_count, 67)
        write(HERE / 'audit/SOURCE_LOCATIONS.json', dict(old_required_locator_occurrences_retained=old_count,
            checked_occurrences_including_optional_duplicates=len(checks),
            unique_task_locators=len({(r['task_id'], r['locator_sha256']) for r in checks}), checks=checks))

    def test_05_c06_c09_and_no_answer_conditions(self):
        refs = {r['task_id']: r for r in self.refs}
        for cond in ('A', 'B'):
            r = refs[self.pair['R03', cond]]
            self.assertIn('改编', r['required_facts'][0]['fact'])
            self.assertIn('没有该论文全文', r['required_facts'][0]['fact'])
            p = refs[self.pair['P03', cond]]['required_facts'][6]['evidence'][-1]
            self.assertEqual((p['char_start'], p['char_end'], p['document_char_start'], p['document_char_end']), (317, 464, 12133, 12280))
        for family in ('E03', 'R03', 'M03'):
            tid = self.pair[family, 'B']
            old = next(r for r in self.old_refs if r['task_id'] == tid)
            self.assertEqual(refs[tid]['source_availability_truth'], old['source_availability_truth'])
            self.assertEqual(refs[tid]['answerability_design'], old['answerability_design'])

    def test_06_six_budgets_and_alternatives(self):
        results = []
        for old, ref in zip(self.old_refs, self.refs):
            w = ref.get('feasibility_witness')
            if not w:
                continue
            self.assertEqual(w, old['feasibility_witness'])
            plan = pointer(read(HERE / w['plan_source_path']), w['plan_pointer'])
            steps = {s['step_id']: s for s in plan['steps']}
            done = set(w['already_completed'])
            cost = 0
            for name in w['one_feasible_sequence']:
                self.assertNotIn(name, done)
                self.assertLessEqual(set(steps[name]['depends_on']), done)
                cost += steps[name]['estimated_minutes']
                done.add(name)
            self.assertEqual(cost, w['estimated_minutes'])
            self.assertLessEqual(cost, w['budget_minutes'])
            todo = [s for s in steps if s not in w['already_completed']]
            possible = []
            for n in range(1, len(todo) + 1):
                for sequence in permutations(todo, n):
                    done = set(w['already_completed']); minutes = 0
                    for name in sequence:
                        if not set(steps[name]['depends_on']) <= done:
                            break
                        done.add(name); minutes += steps[name]['estimated_minutes']
                    else:
                        if minutes <= w['budget_minutes']:
                            possible.append(list(sequence))
            self.assertIn(w['one_feasible_sequence'], possible)
            self.assertTrue(any('不是唯一答案' in s for s in ref['acceptable_alternatives']))
            results.append(dict(task_id=ref['task_id'], budget_minutes=w['budget_minutes'],
                recorded_witness_minutes=cost, feasible_source_step_sequences=possible,
                enumeration_scope='Arithmetic only; does not exclude other valid prose or strategies.'))
        self.assertEqual(len(results), 6)
        write(HERE / 'audit/BUDGET_CHECKS.json', results)

    def test_07_review_bytes_applicability_and_blank_decisions(self):
        m = read(HERE / 'task_spec/PACKET_MANIFEST.json')
        for e in m['members']:
            if e['path'].startswith('received_review/'):
                p = HERE / e['path']
                self.assertEqual(p.stat().st_size, e['bytes'])
                self.assertEqual(sha(p.read_bytes()), e['sha256'])
        raw = read(HERE / 'received_review/01_填写表.json')
        projected = read(HERE / 'applicability.json')['items']
        self.assertEqual(raw['status'], 'DRAFT_PENDING_CONFIRMATION')
        for a, p, ref in zip(raw['items'], projected, self.refs):
            self.assertEqual(a['task_id'], p['task_id'])
            self.assertEqual(a['applicability'], p['draft'])
            for k in ('final_inclusion', 'reviewer_id', 'signature'):
                self.assertIsNone(a[k])
            self.assertTrue(all(v is None for v in p['confirmed'].values()))
            self.assertTrue(all(v is None for v in ref['human_review'].values()))
            self.assertTrue(all(v is None for v in ref['applicability_by_criterion'].values()))
        d = read(HERE / 'AUTHOR_DECISIONS.json')
        self.assertEqual([g['count'] for g in d['applicability_groups']], [41, 22, 5, 1])
        self.assertTrue(all(g['author_decision'] is None for g in d['applicability_groups']))
        self.assertEqual(d['candidate41_draft_counts'], dict(true=208, false=51, null=69))
        self.assertEqual(set(d['applicability_groups'][2]['task_ids']), {'original-06', 'original-15', 'original-16', 'original-17', 'original-21'})

    def test_08_input_identity_rebuilt_only_changed_queries(self):
        old = read(HERE / 'baseline/INPUT_IDENTITIES.json')
        new = read(HERE / 'prepared_inputs/INPUT_IDENTITIES.json')
        changes = {r['task_id'] for r in read(HERE / 'QUERY_CHANGES.json')['changes']}
        for t in self.tasks:
            tid = t['task_id']
            if tid in changes:
                self.assertNotEqual(old[tid]['primary_sha256'], new[tid]['primary_sha256'])
                for role in ROLE_NAMES:
                    self.assertNotEqual(old[tid]['route_cache_keys'][role], new[tid]['route_cache_keys'][role])
                for mode in self.config['modes']:
                    self.assertNotEqual(old[tid]['modes'][mode]['module_state_key'], new[tid]['modes'][mode]['module_state_key'])
                    self.assertNotEqual(old[tid]['modes'][mode]['final_wire_sha256'], new[tid]['modes'][mode]['final_wire_sha256'])
            else:
                self.assertEqual(old[tid], new[tid])
        self.assertEqual(read(HERE / 'INPUT_IDENTITY_CHANGES.json')['counts'], dict(
            source_primary_changed=9, source_primary_unchanged=40, route_cache_keys_changed=27,
            module_state_keys_changed=54, final_wire_previews_changed=54))

    def test_09_source_only_modes_and_target_activation_block(self):
        self.assertEqual(len(self.prepared), 294)
        for row in self.prepared:
            self.assertEqual(row['rag_calls'], 0)
            self.assertEqual(row['memory_calls'], 0)
            for k in ('required_facts', 'family_id', 'applicability_by_criterion', 'source_review', 'minimum_answer_requirements'):
                self.assertNotIn('"' + k + '"', canonical(row['source']['primary']))
                self.assertNotIn('"' + k + '"', canonical(row['final_wire_preview']))
        for key in ('family_id', 'condition', 'required_facts', 'source_availability_truth', 'optional_support'):
            with self.assertRaises(ValueError):
                adapter.source_guard({'ordinary': {key: 'poison'}})
        with self.assertRaises(PermissionError):
            adapter.prepare(self.tasks[-1], self.binding, 'S5_FULL', self.config,
                route=dict(rag_required=True, memory_required=True, planning_required=True))
        with self.assertRaises(PermissionError):
            run_batch.approve(read(HERE / 'EXECUTION_APPROVAL_TEMPLATE.json'), {}, self.manifest, self.config, '/private/tmp/unapproved')
        self.assertEqual(read(HERE / 'audit/PREPARATION_ISOLATION.json')['forbidden_opens'], [])

    def test_10_native_sources_closed_and_unchanged(self):
        from utils.c4_rebuild.memory import m1_dependencies
        _, _, ReadOnlyStore = m1_dependencies()
        from state_harness import snapshot
        baseline = read(HERE / 'audit/INTAKE.json')['preserved_files']
        for folder in ('source_materials', 'native_initial'):
            for p in (HERE / folder).rglob('*'):
                if p.is_file() and p != HERE / 'source_materials/README.md':
                    rel = str(p.relative_to(HERE))
                    self.assertEqual(sha(p.read_bytes()), baseline['experiments/rq3_original25_plus_v2/' + rel])
        for tid, b in self.binding['native'].items():
            p = checked(b['database'])
            with sqlite3.connect(p.as_uri() + '?mode=ro', uri=True) as con:
                self.assertEqual(con.execute('PRAGMA integrity_check').fetchone()[0], 'ok')
            for e in [b['database'], *b['mode_copies'].values()]:
                # SQLite backup copies can have different page layouts. Each
                # retains its own V2 byte identity and the same logical state.
                q = checked(e)
                with ReadOnlyStore(q, clock=lambda: self.by_id[tid]['query_time']) as store:
                    self.assertEqual(sha(snapshot(store)), b['logical_sha256'])

    def test_11_mock_final_plan_custody_contract(self):
        from interfaces import FINAL_SCHEMA, freeze_answer
        self.assertEqual(set(FINAL_SCHEMA['properties']), {'answer', 'cited_evidence_ids'})
        plan = {'engineering_fixture_only': True}
        self.assertEqual(freeze_answer({'answer': 'Fixture answer', 'cited_evidence_ids': []}, [], plan)['accepted_plan'], plan)


def main():
    p = argparse.ArgumentParser()
    p.add_argument('--prepare', action='store_true', help='Create fresh R1 previews once; never call models/retrieval.')
    a = p.parse_args()
    if a.prepare:
        prepare_and_bind()
    result = unittest.TextTestRunner(verbosity=2).run(unittest.defaultTestLoader.loadTestsFromTestCase(ReviewChecks))
    receipt = dict(tests=result.testsRun, failures=len(result.failures), errors=len(result.errors),
        passed=result.wasSuccessful(), failure_details=[dict(test=str(t), detail=s) for t, s in result.failures + result.errors],
        provider_calls=0, p3_calls=0, target_retrieval_calls=0, embedding_calls=0,
        candidate_calls=0, final_calls=0, judge_calls=0, scores_filled=0,
        test_scope='R1 data/reference/input identity, byte preservation, and inherited mock FINAL custody; excludes historical test counts.')
    write(HERE / 'audit/R1_TESTS.json', receipt)
    write(HERE / 'audit/LOADED_TEST_CODE_DEPENDENCIES.json', {
        str(Path(m.__file__).resolve().relative_to(ROOT)): sha(Path(m.__file__).read_bytes())
        for m in list(sys.modules.values()) if getattr(m, '__file__', None)
        and str(Path(m.__file__).resolve()).startswith(str(ROOT) + '/') and str(m.__file__).endswith('.py')})
    print(canonical(receipt))
    raise SystemExit(0 if result.wasSuccessful() else 1)


if __name__ == '__main__':
    main()
