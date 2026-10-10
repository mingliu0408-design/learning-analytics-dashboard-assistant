"""Common authorised lab interface. No history, label, or answerability input."""
from dataclasses import dataclass, field
import time
from typing import Literal
from utils import course_material_retriever as legacy
from utils.c4_rag.retrievers import C4RAGLegacyLexical, FieldAwareBM25, _legacy_query_type
from .common import COURSE, canonical, digest

@dataclass(frozen=True)
class SearchInput:
    query: str
    page: str
    course: str
    allowed_sources: frozenset[str]
    mode: Literal['deployment', 'retriever_only'] = 'deployment'
    p3_required: bool = False
    mode_allowed: bool = True

    @property
    def effective_query(self):
        return self.query.strip()

    @property
    def identity(self):
        return digest(canonical({'query': self.effective_query, 'page': self.page,
            'course': self.course, 'sources': sorted(self.allowed_sources), 'normalisation': 'raw_strip_v1'}))

@dataclass
class SearchResult:
    candidate: str
    input_identity: str
    searched: bool = False
    scored_chunks: int = 0
    ranked: list = field(default_factory=list)
    native_returned: list = field(default_factory=list)
    status: str = 'NOT_SEARCHED'
    latency_ms: float = 0
    candidate_pool: list = field(default_factory=list)

class RetrievalLab:
    def __init__(self, chunks, config):
        self.chunks = tuple(chunks)
        self.by_id = {c.chunk_id: c for c in chunks}
        if len(self.by_id) != len(self.chunks):
            raise ValueError('DUPLICATE_CHUNK_ID')
        self.config = config

    def eligibility(self, request):
        if type(request.p3_required) is not bool or type(request.mode_allowed) is not bool:
            raise TypeError('Strict boolean gates required')
        if request.mode not in ('deployment', 'retriever_only'):
            raise ValueError('Unknown execution mode')
        if not request.mode_allowed:
            return [], 'MODE_DISABLED'
        if request.course != COURSE or not request.allowed_sources:
            return [], 'ACCESS_BLOCKED'
        if request.mode == 'deployment' and not request.p3_required:
            return [], 'P3_NOT_REQUIRED'
        if not request.effective_query:
            return [], 'EMPTY_QUERY'
        eligible = [c for c in self.chunks if c.source_file in request.allowed_sources]
        return eligible, 'READY' if eligible else 'CORPUS_UNAVAILABLE'

    def search(self, candidate, request, *, dense_scores=None, hybrid=None, cross_scores=None):
        start = time.perf_counter()
        result = SearchResult(candidate, request.identity)
        eligible, result.status = self.eligibility(request)
        if result.status != 'READY':
            return result
        if candidate not in ('A_R0', 'B_BM25', 'C_HYBRID', 'D_CROSS_ENCODER'):
            raise ValueError('Unknown candidate')
        query = request.effective_query
        result.searched, result.scored_chunks = True, len(eligible)
        if candidate == 'A_R0':
            # Invoke original ranking and native threshold unchanged. No service imports.
            baseline = object.__new__(C4RAGLegacyLexical)
            baseline.chunks = tuple(eligible)
            native = baseline.retrieve(query, request.page, (), top_k=self.config['final_k'],
                                       upstream_authorised=True)
            qtype = _legacy_query_type(query, request.page, None)
            scored = [(c.chunk_id, legacy._score_chunk(query, qtype, c)) for c in eligible]
            result.ranked = sorted(((i, float(s)) for i, s in scored if s > 0), key=lambda v: (-v[1], v[0]))
            result.native_returned = list(native.chunk_ids)
            result.status = native.result_status.value
        elif candidate in ('B_BM25', 'C_HYBRID'):
            bm25 = FieldAwareBM25(eligible, k1=self.config['bm25']['k1'], b=self.config['bm25']['b'])
            bm25.weights = dict(self.config['bm25']['field_weights'])
            scores = dict(zip((c.chunk_id for c in eligible), bm25.scores(query)))
            lex = sorted(((i, s) for i, s in scores.items() if s > 0), key=lambda v: (-v[1], v[0]))
            if candidate == 'B_BM25':
                result.ranked = lex
            else:
                if dense_scores is None or not all(c.chunk_id in dense_scores for c in eligible):
                    raise RuntimeError('REAL_DENSE_SCORES_REQUIRED')
                import math
                if not all(math.isfinite(float(dense_scores[c.chunk_id])) for c in eligible):
                    raise ValueError('NONFINITE_DENSE_SCORE')
                den = sorted(((c.chunk_id, float(dense_scores[c.chunk_id])) for c in eligible),
                             key=lambda v: (-v[1], v[0]))[:self.config['dense_depth']]
                fused = {}
                for ranked, vote in ((lex[:self.config['lexical_depth']], 2), (den, 1)):
                    for rank, (ident, _) in enumerate(ranked, 1):
                        fused[ident] = fused.get(ident, 0) + vote / (self.config['rrf_constant'] + rank)
                result.ranked = sorted(fused.items(), key=lambda v: (-v[1], v[0]))
            result.native_returned = []  # No uncalibrated score promoted to answer support.
            result.status = 'UNVALIDATED_RETRIEVAL_ONLY' if result.ranked else 'NO_RESULT'
        else:
            if hybrid is None or hybrid.candidate != 'C_HYBRID' or hybrid.input_identity != request.identity:
                raise ValueError('EXACT_C_INPUT_AND_POOL_REQUIRED')
            pool = [i for i, _ in hybrid.ranked[:self.config['rerank_depth']]]
            if cross_scores is None or set(cross_scores) != set(pool):
                raise ValueError('CROSS_ENCODER_POOL_MISMATCH')
            import math
            if not all(math.isfinite(float(s)) for s in cross_scores.values()):
                raise ValueError('NONFINITE_CROSS_ENCODER_SCORE')
            if not set(pool) <= {c.chunk_id for c in eligible}:
                raise ValueError('POOL_SCOPE_MISMATCH')
            result.scored_chunks = len(pool)
            result.ranked = sorted(cross_scores.items(), key=lambda v: (-v[1], v[0]))
            result.candidate_pool = pool
            result.status = 'UNVALIDATED_RETRIEVAL_ONLY' if pool else 'NO_RESULT'
        if not result.candidate_pool:
            result.candidate_pool = [i for i, _ in result.ranked]
        result.latency_ms = (time.perf_counter() - start) * 1000
        return result
