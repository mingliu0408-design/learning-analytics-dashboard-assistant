"""Add only a typed FINAL citation boundary; keep the I1 final_errors unchanged."""
from copy import deepcopy
import json
from i6_common import canonical, require, sha
from utils.c4_rebuild.i1.renderer import final_payload as original_final_payload
from utils.c4_rebuild.i1.schemas import final_errors, strict_schema_check

VERSION = 'I6_FINAL_REFERENCE_CONTRACT_V1'
POLICY = '''I6_FINAL_REFERENCE_CONTRACT_V1. Use the same policy whether or not an accepted plan is supplied.
Top-level cited_evidence_ids lists only supplied source_facts actually used to support source-specific claims in answer. Use only final_citation_contract.allowed_source_evidence_ids. Use [] when no supplied source-specific claim is used; never insert a sham citation. Do not cite the current request, an intention, rationale, task, step or plan as a source fact. A learner request can justify proposing an action without proving its effectiveness or the content of a document. Preserve internal plan references, including current-request, inside plan_fields exactly as supplied; these do not become factual citations.
An accepted plan passed encoded checks only. This is not semantic entailment, pedagogical validation or evidence of learning effectiveness. Do not promise mastery, grades or improvement because plan wording says it will ensure understanding. Preserve plan_fields exactly; natural prose must not repeat unsupported guarantees. Any such plan wording remains a boundary for human review, not a reason to rewrite the plan.
Model durations are uncertain estimates, not known learner availability or source facts. When reproducing them, explicitly preserve approximate/uncertain status. Observation dates are not calendar availability. Ordinary advice does not require new calendar, timezone or budget information; ask for such details only if needed for an actually requested schedule.
A document named in the question but absent from supplied source content has not been read. Do not claim knowledge of unseen worksheet contents. General conditional advice is allowed and must distinguish unavailable contents from supplied facts. Historical records remain limited to their source scope; do not turn historical relative-week goals into established current goals.
'''

def final_payload(prepared, role_config, accepted_plan=None, candidate_failed=False):
    original = original_final_payload(prepared, role_config, accepted_plan, candidate_failed)
    # The separately scoped original failure fallback is deliberately byte-identical.
    if candidate_failed:
        return original
    result = deepcopy(original)
    body = json.loads(result['messages'][1]['content'])
    ids = [fact['id'] for fact in body['source_facts']]
    actual = [fact['evidence_id'] for fact in prepared['final_request']['runtime_input']['evidence']['selected_evidence']]
    require(ids == actual == prepared['trace']['retained_evidence_ids'], 'FINAL_SOURCE_TRACE_MISMATCH')
    require(len(ids) == len(set(ids)) and 'current-request' not in ids, 'INVALID_SOURCE_REFERENCE_BOUNDARY')
    body['final_citation_contract'] = dict(
        version=VERSION, allowed_source_evidence_ids=ids,
        citation_semantics='Only source_facts actually used for source-specific claims in answer.',
        excluded_reference_roles=['current-request', 'planning_intent', 'rationale', 'task', 'step', 'plan'],
        plan_reference_policy='Keep all nested accepted_plan references exactly; they are not top-level source citations.',
        empty_citation_policy='Use [] when no supplied source-specific claim is used. With no supplied source IDs, [] is mandatory; original local subset validation enforces this.',
        source_identity=dict(source_facts_sha256=sha(body['source_facts']), order='UNCHANGED'))
    result['messages'][0]['content'] += '\n' + POLICY
    result['messages'][1]['content'] = canonical(body).decode()
    wire = result['response_format']['json_schema']
    wire['name'] = 'i6_final_reference_v1'
    citation_schema = wire['schema']['properties']['cited_evidence_ids']
    citation_schema['description'] = body['final_citation_contract']['citation_semantics'] + ' Empty is valid when no source-specific claim is used.'
    if ids:
        citation_schema['items']['enum'] = list(ids)
    else:
        # No empty enum, dummy ID or new unsupported keyword. The unchanged
        # final_errors rejects every nonempty list for an empty retained set.
        citation_schema['description'] = 'No source facts supplied. Must be []; unchanged local subset validation enforces this.'
    strict_schema_check(wire['schema'])
    return result

def preservation_receipt(prepared, config, plan=None):
    old = json.loads(original_final_payload(prepared, config, plan)['messages'][1]['content'])
    new = json.loads(final_payload(prepared, config, plan)['messages'][1]['content'])
    return dict(fields={key: dict(sha256=sha(value), canonical_bytes_unchanged=canonical(value) == canonical(new[key]))
                        for key, value in old.items()},
                only_added_field=set(new) - set(old) == {'final_citation_contract'})
