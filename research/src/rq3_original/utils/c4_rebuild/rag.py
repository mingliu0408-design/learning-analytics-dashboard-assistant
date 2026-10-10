"""Interchangeable course boundary, provisional corrected R0 operational scorer."""
from utils.c4_rag.retrievers import C4RAGLegacyLexical, legacy_chunk_corpus_hash
from utils.c4_rag.models import EvidenceStrength
from utils.c4_real_contracts import CourseSource, CourseRAGResult
from utils.c4_real_adapters import C4SelectedR0CourseRAGAdapter
from utils.c4_dashboard_scoped.scope import digest


class R0OnExplicitCorpus(C4RAGLegacyLexical):
    """Constructor-only DI; inherits the unchanged R0 scoring and single gate."""
    def __init__(self, chunks):
        self.chunks = tuple(chunks)
        # The inherited helper treats [] as an instruction to load its real
        # corpus. An explicitly empty injected corpus must remain empty.
        self.corpus_hash = legacy_chunk_corpus_hash(self.chunks) if self.chunks else digest([])


class ProvisionalR0:
    identity = 'CORRECTED_R0_PROVISIONAL_DEVELOPMENT_NOT_FINAL_SELECTION'

    def __init__(self, scorer, *, course_id, source_version, expected_corpus_sha256, source_window=None):
        if not all((course_id, source_version, expected_corpus_sha256)):
            raise ValueError('Explicit course corpus binding required')
        self.scorer, self.course_id = scorer, course_id
        self.source_version, self.expected_hash = source_version, expected_corpus_sha256
        self.source_window = source_window
        self.calls = 0

    def retrieve(self, request):
        if request.scope.course_id != self.course_id or request.source_version != self.source_version:
            raise ValueError('RAG_COURSE_OR_VERSION_MISMATCH')
        if self.scorer.corpus_hash != self.expected_hash:
            raise ValueError('RAG_CORPUS_HASH_MISMATCH')
        result = self.scorer.retrieve(request.query, request.page, request.history,
                                     top_k=5, upstream_authorised=True)
        self.calls += 1
        sources = []
        for chunk in result.selected_chunks:
            if chunk.evidence_strength == EvidenceStrength.WEAK_MATCH:
                continue
            sources.append(CourseSource(source_id=chunk.chunk_id, source_type=chunk.source_type,
                content=C4SelectedR0CourseRAGAdapter._bounded_content(chunk),
                document_title=chunk.document_title, week=chunk.week, section=chunk.section,
                evidence_strength=chunk.evidence_strength.value,
                provenance=dict(course_id=self.course_id, source_version=self.source_version,
                    source_sha256=chunk.source_sha256 or digest(chunk.text), source_span=chunk.section,
                    observed_at=request.as_of,
                    valid_from=self.source_window[0] if self.source_window else None,
                    valid_to=self.source_window[1] if self.source_window else None)))
        return CourseRAGResult(tuple(sources), tuple(result.limitations), result.result_status.value)
