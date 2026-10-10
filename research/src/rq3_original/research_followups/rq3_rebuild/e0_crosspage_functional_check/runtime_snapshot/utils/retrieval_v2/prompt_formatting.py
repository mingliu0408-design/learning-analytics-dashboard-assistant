"""V2-specific evidence formatting and generator boundaries."""

from __future__ import annotations

from .models import RetrievalResultV2, RetrievedChunkV2


GENERATOR_CONTRACT_V2 = """Retrieval v2 generator contract:
- Use only retrieved course evidence for course-content claims.
- Do not infer a paper's findings from its title or citation.
- Do not infer lecture content from a lecture title.
- Do not infer assessment requirements from dashboard behaviour.
- Keep course evidence, dashboard evidence, and Memory distinct.
- Name the supporting source for every course claim.
- State when evidence is partial; narrow or refuse unsupported claims.
- Do not fill missing course evidence using general world knowledge."""


def format_chunk_v2(item: RetrievedChunkV2) -> str:
    chunk = item.chunk
    section = " > ".join(chunk.section_path) or "unspecified"
    labels = (
        f"chunk_id={chunk.chunk_id}; source_title={chunk.metadata.get('document_title', chunk.title)}; "
        f"source_file={chunk.source_file}; week={chunk.week or 'unspecified'}; "
        f"section={section}; page={chunk.page_number or 'unspecified'}; "
        f"material_type={chunk.material_type}; content_level={chunk.content_level}"
    )
    return f"[{labels}]\nTitle: {chunk.title}\nExtracted text: {chunk.text}"


def format_allowed_retrieval_context_for_prompt(result: RetrievalResultV2) -> str:
    """Format only sufficiency-approved chunks; audit candidates never enter."""

    sufficiency = result.evidence_sufficiency
    sections = [
        "Retrieval v2 status:",
        f"status={sufficiency.status}; answerable={str(sufficiency.answerable).lower()}; "
        f"required_content_level={sufficiency.required_content_level}",
        f"Allowed claim scope: {', '.join(sufficiency.allowed_claim_scope) or 'none'}",
        f"Boundary: {sufficiency.user_facing_boundary}",
        GENERATOR_CONTRACT_V2,
    ]
    allowed = allowed_chunks_for_generation(result)
    if allowed:
        sections.extend(["Approved course evidence:", *[format_chunk_v2(item) for item in allowed]])
    else:
        sections.append("No sufficiency-approved course-evidence chunks are available to the generator.")
    return "\n\n".join(sections)


def format_retrieval_result_for_prompt(result: RetrievalResultV2) -> str:
    """Compatibility alias; prompt formatting is always generation-safe."""

    return format_allowed_retrieval_context_for_prompt(result)


def allowed_chunks_for_generation(result: RetrievalResultV2) -> tuple[RetrievedChunkV2, ...]:
    """Return only chunks whose use is allowed by the central gate."""

    status = result.evidence_sufficiency.status
    if status in {"no_result", "insufficient", "not_applicable"}:
        return ()
    supporting = set(result.evidence_sufficiency.supporting_chunk_ids)
    if not supporting:
        return ()
    return tuple(item for item in result.retrieved_chunks if item.chunk.chunk_id in supporting)


def render_student_boundary(result: RetrievalResultV2) -> str:
    sufficiency = result.evidence_sufficiency
    if sufficiency.status == "no_result":
        return "I could not find sufficiently relevant material in the indexed course corpus for that question."
    if sufficiency.status == "metadata_only":
        return sufficiency.user_facing_boundary
    if sufficiency.status in {"insufficient", "partially_sufficient"}:
        return sufficiency.user_facing_boundary
    if sufficiency.status == "not_applicable":
        return "Course-material retrieval is not applicable to this dashboard-only question."
    return ""
