"""Versioned exact canonical-character spans, active tokenizer budgets, safe expansion.

Offsets refer to canonical extracted Unicode text, not HTML byte positions.
Table header spans may be repeated as references; source text is never rewritten.
"""
from dataclasses import dataclass, replace
import re
from .common import canonical, digest

VERSION = 'source_span_token_chunker_v1'

def source_text(text, spans):
    parts=[];last_end=None
    for a,b in spans:
        if parts and a!=last_end:
            parts.append('\n')
        parts.append(text[a:b]);last_end=b
    return ''.join(parts)

@dataclass(frozen=True)
class Block:
    start: int
    end: int
    kind: str = 'paragraph'
    header: tuple[int, int] | None = None

@dataclass(frozen=True)
class Section:
    document_id: str
    source_hash: str
    course: str
    access_scope: str
    text: str
    base_offset: int
    ancestry: tuple[str, ...]
    week: str | None = None
    assessment_part: str | None = None
    source_type: str = 'body'
    url: str | None = None
    page: int | None = None
    blocks: tuple[Block, ...] = ()

@dataclass(frozen=True)
class SpanChunk:
    chunk_id: str
    parent_id: str
    section: Section
    spans: tuple[tuple[int, int], ...]
    body_tokens: int
    metadata_tokens: int
    model_tokens: int
    previous_id: str | None = None
    next_id: str | None = None

    @property
    def text(self):
        return source_text(self.section.text,self.spans)

    @property
    def absolute_spans(self):
        return [(self.section.base_offset+a, self.section.base_offset+b) for a,b in self.spans]

def metadata(section):
    # Repeated ancestry entries occur in the inherited parser: include metadata once.
    ancestry = list(dict.fromkeys(section.ancestry))
    return ' > '.join(ancestry) + '\n' + '; '.join(str(v) for v in
        (section.week, section.assessment_part, section.source_type, section.page, section.url) if v)

def ntokens(tokenizer, text, special=False):
    return len(tokenizer(text, add_special_tokens=special, truncation=False)['input_ids'])

def default_blocks(text):
    # No content deletion. Blank separators remain in spans.
    edges = [0] + [m.end() for m in re.finditer(r'\n+', text)]
    if edges[-1] != len(text):
        edges.append(len(text))
    return tuple(Block(a,b,'atomic' if b-a < 220 else 'paragraph') for a,b in zip(edges,edges[1:]) if b>a)

def chunk_section(section, tokenizer, window_tokens=256, overlap_tokens=24):
    if not 0 <= overlap_tokens < window_tokens:
        raise ValueError('Invalid overlap')
    text, meta = section.text, metadata(section)
    parent = digest(canonical([section.course, section.document_id, section.source_hash, section.base_offset,
                               section.ancestry, section.week, section.assessment_part, section.access_scope]))
    blocks = section.blocks or default_blocks(text)
    if [(b.start,b.end) for b in blocks] and (blocks[0].start != 0 or blocks[-1].end != len(text)
        or any(a.end != b.start for a,b in zip(blocks,blocks[1:]))):
        raise ValueError('BLOCKS_MUST_PARTITION_SECTION')
    def assembled(spans):
        return source_text(text,spans)
    def fits(spans):
        return ntokens(tokenizer, meta + '\n' + assembled(spans), True) <= window_tokens
    if ntokens(tokenizer,meta,True) >= window_tokens-8:
        raise ValueError('METADATA_EXCEEDS_BUDGET_NO_SILENT_TRUNCATION')
    pieces = []
    for block in blocks:
        if not (0 <= block.start < block.end <= len(text)):
            raise ValueError('INVALID_SOURCE_SPAN')
        header = () if block.header is None else (block.header,)
        if header and not (0 <= header[0][0] < header[0][1] <= block.start):
            raise ValueError('INVALID_TABLE_HEADER_SPAN')
        whole = header + ((block.start,block.end),)
        if fits(whole):
            # Pack only non-table blocks; title/heading remains in metadata with support.
            if not header and pieces and not pieces[-1][1] and fits(pieces[-1][0]+whole):
                old, _ = pieces.pop()
                pieces.append((old+whole, False))
            else:
                pieces.append((whole, bool(header)))
            continue
        if header and not fits(header):
            raise ValueError('TABLE_HEADER_EXCEEDS_BUDGET')
        start = block.start
        while start < block.end:
            # Character bisection followed by actual token recount, including metadata.
            lo, hi = start+1, block.end
            best = start
            while lo <= hi:
                mid = (lo+hi)//2
                if fits(header+((start,mid),)):
                    best, lo = mid, mid+1
                else:
                    hi = mid-1
            if best == start:
                raise ValueError('NO_TOKEN_BUDGET_FOR_BODY')
            if best < block.end:
                sentences = [m.end()+start for m in re.finditer(r'[.!?]\s+',text[start:best])]
                words = [m.end()+start for m in re.finditer(r'\s+',text[start:best])]
                useful = [b for b in sentences if b > start+(best-start)//2]
                if not useful:
                    useful = [b for b in words if b > start+(best-start)//2]
                if useful:
                    best = useful[-1]
            spans = header+((start,best),)
            assert fits(spans)
            pieces.append((spans, bool(header)))
            if best == block.end:
                break
            offsets = tokenizer(text[start:best],add_special_tokens=False,
                                return_offsets_mapping=True)['offset_mapping']
            nxt = start+offsets[max(0,len(offsets)-overlap_tokens)][0] if offsets and overlap_tokens else best
            start = nxt if start < nxt < best else best
    result = []
    for spans, _ in pieces:
        body = assembled(spans)
        model_tokens = ntokens(tokenizer,meta+'\n'+body,True)
        assert model_tokens <= window_tokens
        ident = digest(canonical([VERSION,parent,spans,window_tokens,overlap_tokens]))
        result.append(SpanChunk(ident,parent,section,spans,ntokens(tokenizer,body),
                                ntokens(tokenizer,meta),model_tokens))
    return [replace(c,previous_id=result[i-1].chunk_id if i else None,
        next_id=result[i+1].chunk_id if i+1<len(result) else None) for i,c in enumerate(result)]

def coverage(section, chunks):
    counts = [0]*len(section.text)
    for c in chunks:
        if c.section != section:
            raise ValueError('FOREIGN_SECTION')
        for a,b in c.spans:
            for i in range(a,b):
                counts[i] += 1
    return {'canonical_characters':len(counts), 'covered_characters':sum(n>0 for n in counts),
            'missing_characters':sum(n==0 for n in counts), 'overlap_characters':sum(max(0,n-1) for n in counts),
            'chunks':len(chunks), 'canonical_text_sha256':digest(section.text.encode())}

def expand_context(selected, all_chunks, tokenizer, budget=1200, neighbour_radius=1):
    if len({(c.section.course,c.section.access_scope) for c in selected})>1:
        raise ValueError('MIXED_COURSE_OR_ACCESS_SCOPE')
    by_id = {c.chunk_id:c for c in all_chunks}
    result, provenance, seen, used = [], {}, set(), 0
    def key(c):
        return (c.section.course,c.section.access_scope,c.section.week,c.section.assessment_part,c.parent_id)
    def add(c, winner=False):
        nonlocal used
        fingerprint = digest(c.text.encode())
        if fingerprint in seen:
            if c.chunk_id not in provenance[fingerprint]:
                provenance[fingerprint].append(c.chunk_id)
            return
        n = ntokens(tokenizer, metadata(c.section)+'\n'+c.text, True)
        if n+used > budget:
            if winner and not result:
                raise ValueError('WINNING_SPAN_EXCEEDS_CONTEXT_BUDGET')
            return
        result.append(c); used+=n; seen.add(fingerprint)
        provenance[fingerprint]=[c.chunk_id]
    # All selected winners have budget priority over neighbours.
    for i,c in enumerate(selected):
        add(c, winner=i==0)
    for c in selected:
        for direction in ('previous_id','next_id'):
            cur=c
            for _ in range(neighbour_radius):
                nxt=by_id.get(getattr(cur,direction))
                if nxt is None or key(nxt)!=key(c):
                    break
                add(nxt); cur=nxt
    return result, {'tokens':used,'duplicate_provenance':provenance}
