"""Ordinary advice may cite an exact bound undated snapshot, never availability.

Only this controlled loader's exact source contents qualify. The existing
permissions, identities, validity checks for dated facts and all scheduling
checks remain in the inherited checker. Existing FINAL/time fixes are reused.
"""
from replay_common import *
from copy import deepcopy
from itertools import combinations
from types import SimpleNamespace
import interfaces
from interfaces import clone_function
from utils.c4_rebuild import planning as api
from utils.c4_dashboard_scoped.scope import canonical

def allowed_values():
    from controlled_runtime import BoundPages,DOMAINS
    page=BoundPages(read(HERE/'runtime/BINDINGS.json'))
    return {canonical(page.overview())}|{canonical(page.context(ds)) for n in range(1,5) for ds in combinations(DOMAINS,n)}

def source_check(bridge):
    inherited=interfaces.replay_source_check(bridge)
    bound=allowed_values()
    def check(ref,path,inp,report,at=None):
        local=api.p1v.p0.Report();inherited(ref,path,inp,local,at)
        fs=[f for f in inp['facts'] if f['source_ref']==ref]
        exact=(len(fs)==1 and fs[0]['kind']=='DASHBOARD'
            and fs[0]['fact_type'] in ('CONTROLLED_CURRENT_PAGE_VIEW','CONTROLLED_NONCURRENT_SOURCE_SYNTHESIS')
            and fs[0]['value'] in bound and ref['version']==VERSION
            and ref['learner_id']==LEARNER and ref['course_id']==COURSE
            and ref['observed_at'] is ref['valid_from'] is ref['valid_to'] is None
            and bridge['source_input']['task_request']['mode']=='ORDINARY_ACTION_ADVICE'
            and bridge['source_input']['future_use_policy']=='WARN_SNAPSHOT_ONLY' and at is None)
        for issue in local.issues:
            if not (exact and issue['code']=='MISSING_TIME' and issue['path'].startswith(path)):
                report.issues.append(issue)
        if exact:
            report.add('UNDATED_BOUND_SNAPSHOT_ORDINARY_ONLY',path,
                'Exact hash-bound historical input supports ordinary advice only; no observation time or availability inferred.','WARNING')
    return check

def validators(bridge):
    return clone_function(api.p1v.validators,{'source_extension':source_check})(bridge)

def validate_bridge(bridge):
    return clone_function(api.p1v.validate_bridge,{'project':api.project,'validators':validators,'source_extension':source_check})(bridge)

def validate_candidate(bridge,candidate):
    return clone_function(api.p1v.validate_candidate,{'validate_bridge':validate_bridge,'validators':validators,'source_extension':source_check})(bridge,candidate)

def typed_planner():
    inherited=interfaces.typed_planner()
    original=inherited.candidate_issues.__globals__['ORIGINAL']
    oi=clone_function(original.candidate_issues,{'validate_candidate':validate_candidate})
    op=clone_function(original.candidate_payload,{'validate_bridge':validate_bridge,'candidate_issues':oi})
    proxy=SimpleNamespace(**vars(original));proxy.candidate_issues=oi;proxy.candidate_payload=op
    kind=clone_function(inherited.plan_kind,{'validate_bridge':validate_bridge})
    issues=clone_function(inherited.candidate_issues,{'ORIGINAL':proxy,'plan_kind':kind})
    payload=clone_function(inherited.candidate_payload,{'ORIGINAL':proxy,'plan_kind':kind,'candidate_issues':issues})
    return SimpleNamespace(plan_kind=kind,candidate_issues=issues,candidate_payload=payload)
