"""Synthetic engineering fixtures; no learner/course body data or fake real-model claims."""
from dataclasses import replace
import json
import unittest
from utils.course_material_retriever import CourseChunk
from utils.c4_rag.retrievers import C4RAGLegacyLexical
from utils.c4_rag_lab.common import OUT, COURSE, offline_guard
from utils.c4_rag_lab.retrieval import RetrievalLab, SearchInput
from utils.c4_rag_lab.chunking import Section, Block, chunk_section, coverage, expand_context
from utils.c4_rag_lab.evaluation import reviewed_span_metrics, reference_id_metrics

def chunk(ident='a',text='Week 4 reading task is a synthetic requirement.',title='Week 4',source='synthetic.html'):
    return CourseChunk(chunk_id=ident,source_file=source,source_type='weekly_page',title=title,text=text,
                       week='W4',page='resources',task_type='reading',metadata={})

class RetrievalTests(unittest.TestCase):
    def setUp(self):
        self.config=json.loads((OUT/'RUN_CONFIG.json').read_text())
        self.cs=[chunk(),chunk('b','A different synthetic lecture covers music.','Music')]
        self.lab=RetrievalLab(self.cs,self.config)
        self.req=SearchInput('  Week 4 reading task  ','resources',COURSE,frozenset({'synthetic.html'}),p3_required=True)
    def test_p3_false_zero_search_all_candidates(self):
        for candidate in ('A_R0','B_BM25','C_HYBRID','D_CROSS_ENCODER'):
            r=self.lab.search(candidate,replace(self.req,p3_required=False))
            self.assertFalse(r.searched);self.assertEqual(r.scored_chunks,0)
    def test_access_before_search(self):
        for req in (replace(self.req,course='OTHER'),replace(self.req,allowed_sources=frozenset())):
            self.assertEqual(self.lab.search('C_HYBRID',req).status,'ACCESS_BLOCKED')
    def test_bad_gate_not_truthy(self):
        with self.assertRaises(TypeError):self.lab.search('A_R0',replace(self.req,p3_required='yes'))
    def test_disabled_and_empty(self):
        self.assertFalse(self.lab.search('A_R0',replace(self.req,mode_allowed=False)).searched)
        self.assertFalse(self.lab.search('A_R0',replace(self.req,query='  ')).searched)
    def test_diagnostic_explicit(self):
        r=self.lab.search('B_BM25',replace(self.req,p3_required=False,mode='retriever_only'))
        self.assertTrue(r.searched)
    def test_r0_exact_native(self):
        b=object.__new__(C4RAGLegacyLexical);b.chunks=tuple(self.cs)
        old=b.retrieve(self.req.effective_query,self.req.page,(),top_k=5,upstream_authorised=True)
        r=self.lab.search('A_R0',self.req)
        self.assertEqual(r.native_returned,list(old.chunk_ids));self.assertEqual(r.status,old.result_status.value)
    def test_no_cross_source_scores(self):
        self.lab=RetrievalLab(self.cs+[chunk('private',source='not-authorised')],self.config)
        r=self.lab.search('B_BM25',self.req)
        self.assertNotIn('private',[i for i,_ in r.ranked]);self.assertEqual(r.scored_chunks,2)
    def test_real_dense_required(self):
        with self.assertRaises(RuntimeError):self.lab.search('C_HYBRID',self.req)
    def test_synthetic_rrf_and_exact_pool(self):
        # Synthetic scalar score fixture tests algebra only; never a model execution.
        c=self.lab.search('C_HYBRID',self.req,dense_scores={'a':0.1,'b':0.9})
        d=self.lab.search('D_CROSS_ENCODER',self.req,hybrid=c,cross_scores={'a':2.0,'b':3.0})
        self.assertEqual(set(d.candidate_pool),{i for i,_ in c.ranked})
        self.assertEqual(d.ranked[0][0],'b')
        with self.assertRaises(ValueError):self.lab.search('D_CROSS_ENCODER',self.req,hybrid=c,cross_scores={'a':2})
    def test_wrong_query_pool_rejected(self):
        c=self.lab.search('C_HYBRID',self.req,dense_scores={'a':0.1,'b':0.9})
        with self.assertRaises(ValueError):self.lab.search('D_CROSS_ENCODER',replace(self.req,query='changed'),hybrid=c,cross_scores={})
    def test_nonfinite_rejected(self):
        with self.assertRaises(ValueError):self.lab.search('C_HYBRID',self.req,dense_scores={'a':float('nan'),'b':0.1})
    def test_no_support_from_uncalibrated_score(self):
        r=self.lab.search('B_BM25',self.req)
        self.assertTrue(r.ranked);self.assertEqual(r.native_returned,[])
    def test_tie_break_is_id(self):
        lab=RetrievalLab([chunk('z'),chunk('a')],self.config)
        self.assertEqual([i for i,_ in lab.search('B_BM25',self.req).ranked],['a','z'])
    def test_network_denied(self):
        import socket
        with offline_guard() as g:
            with self.assertRaises(RuntimeError):socket.create_connection(('example.com',443))
        self.assertEqual(g['network_attempts'],1)

class ChunkTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from transformers import AutoTokenizer
        from utils.c4_rag.corpus import CANONICAL_MPNET_ROOT
        cls.tok=AutoTokenizer.from_pretrained(str(CANONICAL_MPNET_ROOT),local_files_only=True,trust_remote_code=False)
    def section(self,text,**kw):
        return Section('SYNTHETIC_DOC','synthetic-source-hash',COURSE,'synthetic_scope',text,100,('Title','Task'),**kw)
    def test_long_single_paragraph_no_tail_loss(self):
        s=self.section(('Long synthetic paragraph without punctuation '*200)+'SENTINEL_TAIL')
        for size in (256,384):
            cs=chunk_section(s,self.tok,size)
            self.assertEqual(coverage(s,cs)['missing_characters'],0)
            self.assertIn('SENTINEL_TAIL',cs[-1].text)
            self.assertTrue(all(c.model_tokens<=size for c in cs))
    def test_unicode_exact_offsets(self):
        s=self.section(('中英文测试 evidence 🧪 完整文本。 '*120))
        cs=chunk_section(s,self.tok,128)
        self.assertEqual(coverage(s,cs)['missing_characters'],0)
        self.assertEqual(cs[0].absolute_spans[0][0],100)
    def test_table_header_with_every_row(self):
        header='Task | Deadline\n'; row='Synthetic task | Friday\n'
        text=header+row*50
        blocks=(Block(0,len(header),'table_header'),)+tuple(Block(len(header)+i*len(row),len(header)+(i+1)*len(row),
            'table_row',(0,len(header))) for i in range(50))
        s=replace(self.section(text),blocks=blocks)
        cs=chunk_section(s,self.tok,128)
        self.assertEqual(coverage(s,cs)['missing_characters'],0)
        self.assertTrue(all('Task | Deadline' in c.text for c in cs))
    def test_atomic_short_requirement(self):
        s=self.section('Submit the synthetic assignment by Friday at noon.')
        cs=chunk_section(s,self.tok,128)
        self.assertEqual(len(cs),1);self.assertEqual(cs[0].text,s.text)
    def test_adjacent_spans_preserve_exact_text(self):
        s=self.section('First paragraph.\nSecond paragraph.\n')
        cs=chunk_section(s,self.tok,128)
        self.assertEqual(len(cs),1);self.assertEqual(cs[0].text,s.text)
    def test_mixed_course_selection_rejected(self):
        a=chunk_section(self.section('Synthetic support.'),self.tok,128)[0]
        b=replace(a,chunk_id='foreign',section=replace(a.section,course='other'))
        with self.assertRaises(ValueError):expand_context([a,b],[a,b],self.tok)
    def test_winner_first_and_same_scope(self):
        s=self.section('Synthetic support. '*1000,week='W4')
        cs=chunk_section(s,self.tok,128)
        changed=replace(cs[0],section=replace(s,week='W5'))
        selected=[replace(cs[1],previous_id=changed.chunk_id)]
        out,audit=expand_context(selected,[changed]+cs[1:],self.tok,budget=500)
        self.assertEqual(out[0].chunk_id,selected[0].chunk_id)
        self.assertNotIn(changed,out);self.assertLessEqual(audit['tokens'],500)
    def test_duplicate_preserves_provenance(self):
        a=chunk_section(self.section('Unique synthetic support.'),self.tok,128)[0]
        b=replace(a,chunk_id='alternative')
        out,audit=expand_context([a,b],[a,b],self.tok)
        self.assertEqual(len(out),1)
        self.assertEqual(next(iter(audit['duplicate_provenance'].values())),[a.chunk_id,b.chunk_id])
    def test_parent_identity_scope(self):
        a=self.section('Synthetic support',week='W4')
        b=replace(a,week='W5')
        self.assertNotEqual(chunk_section(a,self.tok)[0].parent_id,chunk_section(b,self.tok)[0].parent_id)
    def test_metadata_overflow_explicit(self):
        s=replace(self.section('body'),ancestry=('many words '*500,))
        with self.assertRaises(ValueError):chunk_section(s,self.tok,128)
    def test_block_gap_rejected(self):
        s=replace(self.section('abcdef'),blocks=(Block(0,2),Block(3,6)))
        with self.assertRaises(ValueError):chunk_section(s,self.tok)
    def test_winner_cannot_be_displaced(self):
        c=chunk_section(self.section('synthetic support '*40),self.tok,128)[0]
        with self.assertRaises(ValueError):expand_context([c],[c],self.tok,budget=2)

class MetricTests(unittest.TestCase):
    def test_unreviewed_facts_not_scored(self):
        self.assertIsNone(reviewed_span_metrics([],{'review_status':'HUMAN_REVIEW_PENDING'})['required_fact_coverage'])
    def test_span_union_and_hash_boundaries(self):
        r={'review_status':'INDEPENDENTLY_REVIEWED','spans':[('doc','h',0,10)],
           'facts':[{'required_spans':[('doc','h',0,10)]}]}
        self.assertEqual(reviewed_span_metrics([('doc','h',0,5),('doc','h',5,10)],r)['required_fact_coverage'],1)
        self.assertEqual(reviewed_span_metrics([('doc','wrong',0,10)],r)['span_recall'],0)
    def test_reference_id_definition(self):
        r=reference_id_metrics(['x','a'],['a','b'],{'x':'d','a':'d','b':'d'})
        self.assertEqual(r['recall_at_5'],0.5);self.assertEqual(r['mrr_at_5'],0.5)

if __name__=='__main__':unittest.main()
