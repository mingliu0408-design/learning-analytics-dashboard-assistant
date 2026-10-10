"""ARTIFICIAL_PROGRAM_FIXTURES_ONLY.

All responses, scores, source hashes, identities and approval strings constructed
here are program fixtures. They are not human records, consent, independent
review, calibration answers or study data. None are distributed in the human pack.
"""
import copy
import csv
import json
import sys
import tempfile
import unittest
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'tools'))
from h0 import *
from build_blank_packet import build
from validate import artifacts


def task_fixture():
    t = read_json(ROOT / 'templates/task_template.json')
    t.update(status='FROZEN_PRE_ANSWER', task_id='ARTIFICIAL_TASK', family_id='ARTIFICIAL_FAMILY', episode_id='ARTIFICIAL_EPISODE', split='DEV', group_keys=[{'kind':'episode','id':'ARTIFICIAL_EPISODE'}])
    t['provenance'] = {k: ('ARTIFICIAL_NOT_ATTESTED' if isinstance(v,str) else []) for k,v in t['provenance'].items()}
    t['provenance'].update(provenance_class='MODEL_AUTHORED_SYNTHETIC_DEVELOPMENT_EXAMPLE',human_author_id='ARTIFICIAL_WRITER',independent_reviewer_id='ARTIFICIAL_REVIEWER',exposure_status='EXPOSED_DEVELOPMENT')
    t['task'] = {k:'ARTIFICIAL_ONLY' for k in t['task']}
    t['task'].update(source_condition='PRESENT',target_time='2026-01-02T12:00:00+00:00',scope='ARTIFICIAL_SCOPE')
    t['visible_context'].update(text='ARTIFICIAL_CONTEXT',scope='ARTIFICIAL_SCOPE',snapshot_version='ARTIFICIAL_V1')
    t['evaluator_reference'].update(evidence_dossier='EVALUATOR_ONLY_SENTINEL_9467',acceptable_boundaries='ARTIFICIAL_ONLY',scope='ARTIFICIAL_SCOPE',version='ARTIFICIAL_V1',source_ids=['ARTIFICIAL_SOURCE'])
    s = read_json(ROOT / 'templates/source_span_template.json')
    s.update({k:'ARTIFICIAL_NOT_ATTESTED' for k,v in s.items() if isinstance(v,str)})
    s.update(source_id='ARTIFICIAL_SOURCE',sha256='a'*64,scope='ARTIFICIAL_SCOPE',captured_at='2026-01-01T12:00:00Z',event_time='2026-01-01T11:00:00Z',valid_from='2026-01-01T12:00:00Z',valid_to='',supersedes='',state='ACTIVE',permitted_use=['evaluation','generation'])
    t['sources']=[s]
    for c in CRITERIA:t['applicability'][c].update(applicable=True,reason='ARTIFICIAL_RULE')
    t['applicability']['MULTI_PAGE_COHESIVENESS']['applicable']=False
    t['observability'].update(multi_page_design='NONE_NOT_OBSERVABLE',context_reference='ARTIFICIAL_LIMITATION')
    t['freeze'].update(frozen_at='2026-01-03T12:00:00Z',source_manifest_sha256='b'*64,applicability_review_reference='ARTIFICIAL_NOT_APPROVED',author_protocol_approval_reference='ARTIFICIAL_NOT_APPROVED')
    return t


def item_fixture():
    p = read_json(ROOT / 'blank_packet/human/human_packet.json')
    i = copy.deepcopy(p['item_template'])
    i['item_id']='a'*32
    i['response']='ARTIFICIAL_PROGRAM_RESPONSE_ONLY'
    for c in CRITERIA:i['applicability'][c].update(applicable=True,reason='ARTIFICIAL_RULE')
    return i


def rows_fixture(item):
    return [{'item_id':item['item_id'],'rater_id':'ARTIFICIAL_RATER_NOT_A_PERSON','criterion_id':c,'score':3,'note':'ARTIFICIAL_PROGRAM_FIXTURE_ONLY','applicability_dispute':'','recorded_at':'2026-01-04T12:00:00Z'} for c in CRITERIA]


class SourceAndBlankTests(unittest.TestCase):
    def test_artifacts_source_and_blank_integrity(self): self.assertEqual(artifacts(), [])
    def test_source_pdf_hash(self): self.assertEqual(digest((ROOT/'input/REFERENCES/SOURCE_PAPER.pdf').read_bytes()),'781dfea68b7236cfdb74eb051c379bf803d9a5202d675cf25fec83a5be807b23')
    def test_blank_task_is_editable_but_never_ready(self):
        t=read_json(ROOT/'templates/task_template.json');self.assertFalse(validate_task(t));self.assertTrue(validate_task(t,True))
    def test_human_roles_and_signatures_blank(self):
        for n in ['writer','reviewer','rater']:
            t=read_json(ROOT/f'templates/{n}_template.json')
            self.assertEqual(t['signature'],'');self.assertFalse(any(v is True for v in t.values()))
    def test_builder_default_no_responses_or_scores(self):
        with tempfile.TemporaryDirectory(prefix='h0_test_') as tmp:
            out=Path(tmp)/'packet';result=build(out)
            self.assertEqual(result,{'items':0,'blank_rating_rows':8,'mapping_rows':0,'response_count':0})
            self.assertFalse(packet_errors(read_json(out/'human/human_packet.json')))
            self.assertTrue(all(r['score'] is None and r['rater_id']=='' for r in read_json(out/'human/ratings.json')))
    def test_builder_never_overwrites(self):
        with tempfile.TemporaryDirectory(prefix='h0_test_') as tmp:
            with self.assertRaises(ValueError):build(tmp)
    def test_builder_six_mode_reference_parity_and_separate_mapping(self):
        with tempfile.TemporaryDirectory(prefix='h0_test_') as tmp:
            out=Path(tmp)/'packet';build(out,[task_fixture()]);p=read_json(out/'human/human_packet.json');m=read_json(out/'restricted/mode_mapping.json')
            self.assertEqual([x['mode'] for x in m],list(MODES));self.assertEqual(len(p['items']),6)
            for i in p['items']:
                self.assertNotIn('mode',i);self.assertNotIn('family_id',i);self.assertNotIn('provenance',i)
                self.assertEqual(i['applicability'],p['items'][0]['applicability']);self.assertEqual(i['evidence_dossier'],p['items'][0]['evidence_dossier'])
    def test_builder_rejects_candidate_in_task(self):
        t=task_fixture();t['response']='ARTIFICIAL_FORBIDDEN'
        with tempfile.TemporaryDirectory(prefix='h0_test_') as tmp:
            with self.assertRaises(ValueError):build(Path(tmp)/'packet',[t])
    def test_packet_malformed_source_panel_rejected(self):
        p=read_json(ROOT/'blank_packet/human/human_packet.json');p['item_template']['evidence_dossier']['source_ids']=None;self.assertTrue(packet_errors(p))
    def test_packet_source_rubric_drift_rejected_even_with_new_hash(self):
        p=read_json(ROOT/'blank_packet/human/human_packet.json');p['rubric']['criteria'][0]['source_description']='ARTIFICIAL_CHANGED_MEANING';p['item_template']['rubric_sha256']=digest(canonical_bytes(p['rubric']));self.assertTrue(packet_errors(p))


class TaskTests(unittest.TestCase):
    def test_artificial_ready_structure_fixture(self): self.assertFalse(validate_task(task_fixture(),True))
    def test_no_mode_specific_applicability(self):
        t=task_fixture();t['applicability']['CLARITY']['mode']='S0';self.assertTrue(validate_task(t))
    def test_no_p3_task_gate(self):
        t=task_fixture();t['p3_yes']=True;self.assertTrue(validate_task(t))
    def test_task_error_handling_fixed_for_missing_source(self):
        t=task_fixture();t['task']['source_condition']='MISSING';t['applicability']['ERROR_HANDLING']['applicable']=False;self.assertTrue(validate_task(t,True))
    def test_no_response_based_weight(self):
        t=task_fixture();t['applicability']['RELIABILITY']['weight']=2;self.assertTrue(validate_task(t))
    def test_unobserved_multi_page_rejected(self):
        t=task_fixture();t['applicability']['MULTI_PAGE_COHESIVENESS']['applicable']=True;self.assertTrue(validate_task(t,True))
    def test_single_response_adaptation_requires_approval(self):
        t=task_fixture();t['applicability']['MULTI_PAGE_COHESIVENESS']['applicable']=True;t['observability']['multi_page_design']='SINGLE_RESPONSE_ADAPTATION';self.assertTrue(validate_task(t,True))
    def test_source_version_required(self):
        t=task_fixture();t['sources'][0]['version']='';self.assertTrue(validate_task(t,True))
    def test_future_source_rejected(self):
        t=task_fixture();t['sources'][0]['captured_at']='2026-02-01T12:00:00Z';self.assertTrue(validate_task(t,True))
    def test_naive_source_time_rejected(self):
        t=task_fixture();t['sources'][0]['captured_at']='2026-01-01T12:00:00';self.assertTrue(validate_task(t,True))
    def test_unbound_source_reference_rejected(self):
        t=task_fixture();t['evaluator_reference']['source_ids']=['UNKNOWN'];self.assertTrue(validate_task(t,True))
    def test_no_evaluation_permission_rejected(self):
        t=task_fixture();t['sources'][0]['permitted_use']=['generation'];self.assertTrue(validate_task(t,True))
    def test_expired_generation_source_rejected(self):
        t=task_fixture();t['sources'][0]['valid_to']='2026-01-02T10:00:00Z';self.assertTrue(validate_task(t,True))
    def test_wrong_scope_generation_source_rejected(self):
        t=task_fixture();t['sources'][0]['scope']='OTHER';self.assertTrue(validate_task(t,True))
    def test_source_absence_must_be_documented(self):
        t=task_fixture();t['sources']=[];t['evaluator_reference']['source_ids']=[];t['task']['source_condition']='ABSENT';self.assertTrue(validate_task(t,True))
    def test_self_review_rejected(self):
        t=task_fixture();t['provenance']['independent_reviewer_id']=t['provenance']['human_author_id'];self.assertTrue(validate_task(t))
    def test_legacy_cannot_be_heldout(self):
        t=task_fixture();t['status']='DRAFT';t['split']='HELD_OUT';t['provenance']['legacy_relations']=['OLD_62'];self.assertTrue(validate_task(t))
    def test_model_synthetic_cannot_be_heldout(self):
        t=task_fixture();t['status']='DRAFT';t['split']='HELD_OUT';self.assertTrue(validate_task(t))
    def test_unknown_fields_rejected(self):
        t=task_fixture();t['evaluator_reference']['expected_score']=5;self.assertTrue(validate_task(t))


class GroupTests(unittest.TestCase):
    def drafts(self):
        a=read_json(ROOT/'templates/task_template.json');b=copy.deepcopy(a)
        for i,t in enumerate([a,b]):t.update(status='DRAFT',task_id=str(i),family_id='F',episode_id='E',split='DEV',group_keys=[{'kind':'episode','id':'E'}])
        return a,b
    def test_related_episode_cross_split_rejected(self):
        a,b=self.drafts();b['split']='HELD_OUT';self.assertTrue(validate_collection([a,b]))
    def test_connected_keys_cannot_use_different_families(self):
        a,b=self.drafts();b['family_id']='OTHER';self.assertTrue(validate_collection([a,b]))
    def test_one_target_per_heldout_family(self):
        a,b=self.drafts();a['split']=b['split']='HELD_OUT';self.assertTrue(validate_collection([a,b]))
    def test_general_corpus_reuse_not_global_group(self):
        a,b=self.drafts();a['group_keys']=[{'kind':'source_proposition','id':'P1'}];b['group_keys']=[{'kind':'source_proposition','id':'P2'}];b['family_id']='G';b['provenance']['general_corpus_reuse']=a['provenance']['general_corpus_reuse']='SAME_CORPUS';self.assertFalse(validate_collection([a,b]))
    def test_transitive_learner_plan_grouping(self):
        a,b=self.drafts();c=copy.deepcopy(b);c['task_id']='C';c['family_id']='G';a['group_keys']=[{'kind':'learner','id':'L'}];b['group_keys']=[{'kind':'learner','id':'L'},{'kind':'plan','id':'P'}];c['group_keys']=[{'kind':'plan','id':'P'}];self.assertTrue(validate_collection([a,b,c]))


class RuntimeSeparationTests(unittest.TestCase):
    def capture(self):
        t=task_fixture();r=read_json(ROOT/'templates/runtime_capture_template.json');r.update(target_time=t['task']['target_time'],query='ARTIFICIAL_NATURAL_UTTERANCE_NO_P1_PHRASE_REQUIRED',visible_context=t['visible_context'])
        a=read_json(ROOT/'templates/source_annotation_template.json');a.update(annotation_id='ARTIFICIAL_A',source_id='ARTIFICIAL_SOURCE',field='learner_constraint',value='ARTIFICIAL_CAPTURED_VALUE',captured_at='2026-01-01T12:00:00Z',confirmed_by_reference='ARTIFICIAL_NOT_ATTESTED',available_pre_target=True,permitted_runtime_use=True);r['source_annotations']=[a]
        return r,t
    def test_evaluator_sentinel_never_projected(self):
        r,t=self.capture();out=project_runtime_capture(r,t['sources']);self.assertNotIn('EVALUATOR_ONLY_SENTINEL',json.dumps(out));self.assertIn('ARTIFICIAL_CAPTURED_VALUE',json.dumps(out))
    def test_evaluator_top_level_rejected(self):
        r,t=self.capture();r['evaluator_reference']=t['evaluator_reference']
        with self.assertRaises(ValueError):project_runtime_capture(r,t['sources'])
    def test_expected_answer_annotation_rejected(self):
        r,t=self.capture();r['source_annotations'][0]['field']='expected_answer'
        with self.assertRaises(ValueError):project_runtime_capture(r,t['sources'])
    def test_unconfirmed_annotation_rejected(self):
        r,t=self.capture();r['source_annotations'][0]['confirmed_by_reference']=''
        with self.assertRaises(ValueError):project_runtime_capture(r,t['sources'])
    def test_revoked_source_rejected(self):
        r,t=self.capture();t['sources'][0]['state']='REVOKED'
        with self.assertRaises(ValueError):project_runtime_capture(r,t['sources'])


class RatingTests(unittest.TestCase):
    def test_artificial_valid_program_scores(self):
        i=item_fixture();self.assertFalse(validate_ratings(rows_fixture(i),[i],complete=True))
    def test_invalid_score_types_and_bounds(self):
        i=item_fixture()
        for value in [True,False,0,6,1.0,'1','5.0','NaN','',float('nan')]:
            with self.subTest(value=repr(value)):
                r=rows_fixture(i);r[0]['score']=value;self.assertTrue(validate_ratings(r,[i]))
    def test_applicable_na_rejected(self):
        i=item_fixture();r=rows_fixture(i);r[0]['score']='NA';self.assertTrue(validate_ratings(r,[i]))
    def test_inapplicable_numeric_rejected(self):
        i=item_fixture();i['applicability']['CLARITY']['applicable']=False;self.assertTrue(validate_ratings(rows_fixture(i),[i]))
    def test_inapplicable_human_na_accepted_as_program_fixture(self):
        i=item_fixture();i['applicability']['CLARITY']['applicable']=False;r=rows_fixture(i);r[0]['score']='NA';self.assertFalse(validate_ratings(r,[i],True))
    def test_missing_score_blocks_complete_but_not_draft(self):
        i=item_fixture();r=rows_fixture(i);r[0]['score']=None;self.assertTrue(validate_ratings(r,[i],True));self.assertFalse(validate_ratings(r,[i]))
    def test_no_scores_for_missing_response(self):
        i=item_fixture();i['response']=None;self.assertTrue(validate_ratings(rows_fixture(i),[i]))
    def test_duplicate_rating_row_rejected(self):
        i=item_fixture();r=rows_fixture(i);r.append(copy.deepcopy(r[0]));self.assertTrue(validate_ratings(r,[i]))
    def test_missing_criterion_row_rejected(self):
        i=item_fixture();self.assertTrue(validate_ratings(rows_fixture(i)[1:],[i],True))
    def test_dispute_retained_blocks_final(self):
        i=item_fixture();r=rows_fixture(i);r[0]['score']='NA';r[0]['applicability_dispute']='ARTIFICIAL_DISPUTE';original=copy.deepcopy(r);self.assertFalse(validate_ratings(r,[i]));self.assertTrue(validate_ratings(r,[i],True));self.assertEqual(r,original)
    def test_h0_prefilled_note_or_identity_rejected(self):
        p=read_json(ROOT/'blank_packet/human/human_packet.json');r=read_json(ROOT/'blank_packet/human/ratings.json');r[0]['note']='ARTIFICIAL_FORBIDDEN_PREFILL';self.assertTrue(validate_ratings(r,[p['item_template']],blank_only=True))
    def test_csv_strict_roundtrip_blank(self):
        self.assertEqual(load_ratings_csv(ROOT/'blank_packet/human/ratings.csv'),read_json(ROOT/'blank_packet/human/ratings.json'))


class DedupeTests(unittest.TestCase):
    def test_same_visible_item_ignores_only_opaque_id(self):
        a=item_fixture();b=copy.deepcopy(a);b['item_id']='b'*32;self.assertTrue(identical_visible_items(a,b))
    def test_each_visible_field_change_prevents_dedup(self):
        a=item_fixture()
        for key in VISIBLE_FIELDS:
            with self.subTest(key=key):
                b=copy.deepcopy(a)
                if isinstance(b[key],dict):b[key]['ARTIFICIAL_CHANGE']='X'
                else:b[key]+=' '
                self.assertFalse(identical_visible_items(a,b))
    def test_unicode_not_normalized(self):
        a=item_fixture();b=copy.deepcopy(a);a['query']='é';b['query']='e\u0301';self.assertFalse(identical_visible_items(a,b))
    def test_response_free_slots_not_deduplicable(self):
        a=item_fixture();a['response']=None
        with self.assertRaises(ValueError):identical_visible_items(a,a)
    def test_hidden_mode_rejected_from_visible_payload(self):
        a=item_fixture();a['mode']='S5'
        with self.assertRaises(ValueError):visible_bytes(a)


class ConditionParityTests(unittest.TestCase):
    def bundle(self):
        items, mapping = [], []
        for n,mode in enumerate(MODES):
            i=item_fixture();i['item_id']=str(n)*32;items.append(i);mapping.append({'item_id':i['item_id'],'task_id':'ARTIFICIAL_TASK','family_id':'ARTIFICIAL_FAMILY','mode':mode})
        return items,mapping
    def test_same_task_different_responses_keep_common_denominator(self):
        items,m=self.bundle();items[0]['response']='DIFFERENT_ARTIFICIAL_RESPONSE';self.assertFalse(validate_condition_parity(items,m))
    def test_mode_specific_applicability_tampering_rejected(self):
        items,m=self.bundle();items[0]['applicability']['ERROR_HANDLING']['applicable']=False;self.assertTrue(validate_condition_parity(items,m))
    def test_mode_specific_truth_tampering_rejected(self):
        items,m=self.bundle();items[0]['evidence_dossier']['evidence_dossier']='DIFFERENT_ARTIFICIAL_TRUTH';self.assertTrue(validate_condition_parity(items,m))
    def test_missing_or_duplicate_mode_rejected(self):
        items,m=self.bundle();m[0]['mode']='S5';self.assertTrue(validate_condition_parity(items,m))


if __name__ == '__main__':unittest.main()
