"""H0-compatible pure projections; no scoring, no generated support as truth."""
from copy import deepcopy
import uuid
from .common import ROOT, sha, load, canonical

H0 = ROOT/'research_followups/rq3_rebuild/h0_human_evaluation'
RUBRIC = load(H0/'rubric.json')
TEMPLATE = load(H0/'templates/task_template.json')


def dossier(task, source_approved_common_reference):
    # Reference is separate input, fixed before any mode retrieves/generates.
    if set(source_approved_common_reference) != {'source_review_approved','reference','source_ids','version'}:
        raise ValueError('COMMON_DOSSIER_SCHEMA')
    return dict(query=task['primary']['current_query'],
        visible_context={'text':canonical(task['primary']['dashboard_context']).decode(),
                         'history':deepcopy(task['primary']['visible_conversation_history']),
                         'scope':sha(task['scope']), 'snapshot_version':task['scope'].get('snapshot','')},
        evidence_dossier=deepcopy(source_approved_common_reference),
        applicability=deepcopy(TEMPLATE['applicability']),
        observability=deepcopy(TEMPLATE['observability']))


def project(common, modes, freezes=(), *, artificial=False, protocol_approval=None):
    if freezes and not artificial:
        if not protocol_approval or protocol_approval.get('approved') is not True or not common['evidence_dossier']['source_review_approved']:
            raise PermissionError('REAL_RATING_PACKET_NOT_AUTHORIZED')
        if any(f['origin']!='LIVE' or f['result']['status']!='ACCEPTED' for f in freezes):
            raise PermissionError('ACTUAL_ACCEPTED_RESPONSES_REQUIRED')
        if any(v['applicable'] is None for v in common['applicability'].values()) or not common['observability']['author_approval_reference']:
            raise PermissionError('TASK_APPLICABILITY_AND_OBSERVATION_PENDING')
    if freezes and len(freezes)!=len(modes):
        raise ValueError('EXACT_SIX_MODE_FREEZE_SET_REQUIRED')
    if freezes and [f['mode'] for f in freezes] != list(modes):
        raise ValueError('MODE_ORDER_OR_IDENTITY_MISMATCH')
    items, mapping = [], []
    for i, mode in enumerate(modes):
        ident = uuid.uuid4().hex
        item = dict(item_id=ident, **deepcopy(common), response=None,
            instructions='共同来源与适用性尚待审核；没有真实回答时不能评分。',
            rubric_sha256=sha(RUBRIC))
        if freezes:
            if artificial:
                item['response'] = '[ARTIFICIAL MOCK — NOT FOR RATING] '+freezes[i]['result']['value']['answer']
            else:
                item['response'] = freezes[i]['result']['value']['answer']
        items.append(item)
        mapping.append(dict(item_id=ident,mode=mode,task_id=sha(common),family_id=sha(common)))
    common_hashes = {sha({k:v for k,v in i.items() if k not in ('item_id','response')}) for i in items}
    if len(common_hashes)!=1:
        raise ValueError('COMMON_DOSSIER_CHANGED_BETWEEN_MODES')
    return dict(schema_version='I1_H0_PROJECTION_V1', stage='ARTIFICIAL_TEST_ONLY' if artificial else 'RESPONSE_FREE_PREPARATION',
        rating_enabled=False, rubric=deepcopy(RUBRIC),items=items,ratings=[],
        real_response_count=0 if artificial or not freezes else len(freezes)), mapping
