"""One opt-in request -> E1 -> RAG/M1 -> compiler -> P1 -> final builder flow."""
from copy import deepcopy
from dataclasses import asdict
from utils.c4_dashboard_scoped import DOMAINS
from utils.c4_dashboard_scoped.scope import canonical, digest, instant, ScopeError
from utils.c4_dashboard_scoped.aggregate import aggregate
from utils.c4_dashboard_scoped.integration import build_scoped_request, ScopedEvidenceAdapter
from utils.c4_real_adapters import C4RealEvidenceCompilerV1, FrozenClarificationGateAdapter
from utils.c4_real_contracts import (EvidenceItem, EvidenceSynthesisResult, ModuleActivation,
    P3CapabilityRoute, P3_ROUTER_METHOD_ID, MemoryItem, MemoryReadResult)
from .contracts import POLICIES, Mode, execute_live, reject_sidecars
from .language import intent, purpose, numeric_constraint
from .memory import MemoryBundle
from .generation import final_request, candidate_request


def planner_base(request, compiled, task):
    # The task objective is the verbatim current request, not an inferred learner goal.
    base = dict(schema_version='P0_DRAFT_V0', scope=dict(learner_id=request.scope.learner_id,
        course_id=request.scope.course_id, session_id=request.session_id, as_of=request.as_of,
        horizon=deepcopy(request.schedule_horizon), timezone=request.schedule_timezone),
        context=dict(query=request.query, page=request.page,
            visible_conversation=[x['role']+': '+x['content'] for x in request.history]),
        goals=[dict(goal_id='current-request', text=request.query, evidence_refs=['current-request'])],
        hard_constraints=dict(budget=dict(required=False, minutes=None),
            schedule=dict(required=task['mode']=='EXPLICIT_SCHEDULE',
                allowed_windows=list(request.allowed_windows) or None,
                excluded_windows=[], forbidden_weekdays=[], non_overlap=True),
            forbid_completed_repeat=True, continue_active_plan=False,
            required_evidence_ids=[], task_prerequisites=[]),
        soft_preferences=[], completed_tasks=[], review_permissions=[], active_plan=None,
        facts=[], resources=[], source_versions=[], missing_information=[])
    def ref(sid, version):
        return dict(source_id=sid, version=version, learner_id=request.scope.learner_id,
            course_id=request.scope.course_id, scope='LEARNER', session_id=request.session_id,
            span_id=sid, page=request.page, observed_at=request.as_of,
            valid_from=request.scope.start, valid_to=request.scope.end, superseded_by=None, access='GRANTED')
    base['facts'].append(dict(fact_id='current-request', kind='DASHBOARD',
        fact_type='VERBATIM_CURRENT_TASK_REQUEST', value=request.query, source_ref=ref('current-request', '1'), available=True))
    base['source_versions'].append(dict(source_id='current-request', version='1'))
    for item in compiled.content['selected_evidence']:
        if item['source_kind'] == 'LEARNER_MEMORY':
            continue  # Memory enters only through its actual M1 source bridge.
        sid = item['evidence_id']
        version = request.scope.snapshot if item['source_kind']=='DASHBOARD' else request.source_version
        source_ref = ref(sid, version)
        if item['source_kind'] == 'COURSE_RAG':
            source_ref.update(scope='COURSE', learner_id=None,
                observed_at=item['provenance'].get('observed_at'),
                valid_from=item['provenance'].get('valid_from'), valid_to=item['provenance'].get('valid_to'))
        base['facts'].append(dict(fact_id=sid, kind=item['source_kind'],
            fact_type=item.get('evidence_type', 'COURSE_SOURCE'), value=canonical(item['content']),
            source_ref=source_ref, available=True))
        base['source_versions'].append(dict(source_id=sid, version=version))
    return base


class ResearchService:
    def __init__(self, *, enabled, snapshot, router=None, retriever=None, memory=None,
                 evidence_budget=12000, request_budget=50000):
        if enabled is not True:
            raise ValueError('I0 requires explicit opt-in')
        self.snapshot, self.router, self.retriever, self.memory = snapshot, router, retriever, memory
        self.compiler = C4RealEvidenceCompilerV1(token_budget=evidence_budget)
        self.request_budget = request_budget
        self.clarification = FrozenClarificationGateAdapter()
        self.planner_work = 0

    execute = staticmethod(execute_live)

    def resolve_memory_use(self, request):
        """I0 default unchanged; versioned opt-in services may extend seed reads."""
        return purpose(request.query, request.memory_purpose)

    def validate_request_time(self, request):
        if not instant(request.scope.start) <= instant(request.as_of) < instant(request.scope.end):
            raise ScopeError('AS_OF_OUTSIDE_REQUEST_WINDOW')

    def resolve_task_intent(self, request):
        return intent(request.query, request.task_intent)

    def build_planning_bridge(self, request, compiled, task, memory):
        from .planning import bridge_from_m1
        return bridge_from_m1(memory, planner_base(request, compiled, task), task, request.future_policy)

    def check_planning_bridge(self, bridge):
        from .planning import validate_bridge
        return validate_bridge(bridge)

    def prepare(self, request):
        self.snapshot.validate_query(request.scope, request.query, instant(request.as_of))
        self.validate_request_time(request)
        scoped = build_scoped_request(snapshot=self.snapshot, scope=request.scope,
            query=request.query, page=request.page, now=instant(request.as_of),
            messages=request.history, session_id=request.session_id)
        visible = aggregate(self.snapshot, request.scope)
        events = ['SCOPE_AND_VISIBLE_PAGE', 'CLARIFICATION_GATE']
        clarification = self.clarification.evaluate(scoped.primary_input)
        policy = POLICIES[request.mode]
        route, route_status = None, 'BYPASSED_S0_S1'
        if any(policy[1:]) and not clarification.needs_clarification:
            events.append('P3_ON_ORIGINAL_FOUR_FIELDS')
            route = self.router.route(scoped.primary_input) if self.router else None
            if route is not None and (not isinstance(route, P3CapabilityRoute) or route.method_id != P3_ROUTER_METHOD_ID):
                raise ValueError('INVALID_FROZEN_P3_ROUTE')
            if route is not None and route.provider_identity.startswith('SYNTHETIC') and self.snapshot.origin!='SYNTHETIC':
                raise ValueError('SYNTHETIC_ROUTE_ON_REAL_SOURCE_FORBIDDEN')
            route_status = 'MISSING_ROUTE_NOT_YES' if route is None else route.provider_identity or 'UNSPECIFIED_ROUTE_PROVIDER'
        bits = (route.rag_required, route.memory_required, route.planning_required) if route else (False, False, False)
        allowed = (request.access.rag, request.access.memory, request.access.planning)
        activate = tuple(a and b and c and not clarification.needs_clarification for a, b, c in zip(policy[1:], bits, allowed))
        active = ModuleActivation(policy[0], *activate)
        current_id = 'page:'+digest(scoped.dashboard_context)
        current = EvidenceItem(current_id, 'LEGACY_RAW_PAGE_CONTEXT', scoped.dashboard_context,
                               evidence_strength='SCOPED_VISIBLE_FACTS')
        additional = ScopedEvidenceAdapter(self.snapshot).synthesise(request=scoped, primary_input=scoped.primary_input) if policy[0] else EvidenceSynthesisResult()
        dashboard = EvidenceSynthesisResult((current, *additional.items), additional.limitations, 'SCOPED_E1_FACTS')
        events.append('E1_SCOPED_AGGREGATION')
        rag = None
        if activate[0]:
            events.append('RAG_SINGLE_GATE_SCORER')
            if self.retriever is None:
                raise ValueError('ACTIVATED_RAG_INTERFACE_UNBOUND')
            rag = self.retriever.retrieve(request)
        from .planning import empty_envelope
        memory = MemoryBundle(empty_envelope(request), {}, {})
        use = self.resolve_memory_use(request)
        if activate[1] and use['value'] != 'UNKNOWN':
            events.append('M1_READ_ONLY_LINKED_RETRIEVAL')
            if self.memory is None:
                raise ValueError('ACTIVATED_MEMORY_INTERFACE_UNBOUND')
            memory = self.memory.read(request, use['value'])
            for key, value in [('learner_id', request.scope.learner_id), ('course_id', request.scope.course_id), ('as_of', request.as_of)]:
                if memory.envelope['scope'][key] != value:
                    raise ValueError('M1_REQUEST_SCOPE_MISMATCH')
            from .planning import source_bindings
            for f, bound in zip(memory.envelope['facts'], source_bindings(memory)):
                b, n = bound['binding'], bound['native']
                if (f['learner_id'] != request.scope.learner_id or f['course_id'] != request.scope.course_id
                    or b['current_version'] != str(f['native_version']) or b['enabled'] is not True
                    or b['origin'] == 'UNKNOWN' or n['timestamp_version']['status'] != 'ACTIVE'
                    or f['consent_status'] not in ('GRANTED', 'NOT_REQUIRED')):
                    raise ValueError('M1_RUNTIME_AUTHORITY_NOT_VERIFIED')
                lower, upper = f['validity']['valid_from'], f['validity']['valid_to']
                if lower is None or instant(lower) > instant(request.as_of) or (upper and instant(upper) <= instant(request.as_of)):
                    raise ValueError('M1_OUTSIDE_VALIDITY')
        memory_items = tuple(MemoryItem(f['native_id'], f['memory_type'], f['content'],
            provenance='ACTUAL_M1_ENVELOPE', version=f['native_version'], timestamp_version=f['validity'],
            provenance_details=f['source_ref']) for f in memory.envelope['facts'])
        mresult = MemoryReadResult(memory_items, ('PURPOSE_UNKNOWN' if activate[1] and use['value']=='UNKNOWN' else 'M1_RAW_CONSTRAINTS_NOT_CHECKABLE',), memory.envelope['status'])
        compiled = self.compiler.compile(request=scoped, clarification=clarification, route=route,
            activation=active, dashboard_evidence=dashboard, course_rag=rag, learner_memory=mresult if activate[1] else None)
        events.append('ACTUAL_C4_EVIDENCE_COMPILER')
        if current_id not in compiled.evidence_ids:
            raise ValueError('CURRENT_PAGE_EXCEEDS_COMMON_BUDGET')
        retained = set(compiled.evidence_ids)
        # An omitted fact may not re-enter through a raw envelope or the planner.
        omitted = [x.split(':', 1)[1] for x in compiled.limitations if x.startswith('TOKEN_BUDGET_EXCLUDED:')]
        full_ids = [f['native_id'] for f in memory.envelope['facts']]
        menv = deepcopy(memory.envelope)
        menv['facts'] = [f for f in menv['facts'] if f['native_id'] in retained]
        menv['source_link_edges'] = [e for e in menv['source_link_edges'] if {e['from_id'], e['to_id']} <= retained]
        for key in ('active_plan_ids', 'accepted_action_ids', 'completed_action_ids'):
            menv[key] = [x for x in menv[key] if x in retained]
        if menv['chosen_active_plan_id'] not in retained:
            menv['chosen_active_plan_id'] = None
        if any(mid not in retained for mid in full_ids):
            menv['missing_information'].append('COMPILER_BUDGET_OMISSIONS')
            if not menv['facts']:
                menv['status']='ALL_MEMORY_FACTS_BUDGET_OMITTED'
        memory = MemoryBundle(menv, {k:v for k,v in memory.authority.items() if k in retained}, memory.trace)
        task = self.resolve_task_intent(request)
        normalisations = [numeric_constraint(f['content'], f['native_id']) for f in menv['facts']
            if f['memory_type']=='CONSTRAINT' and f['source_ref']['origin']=='USER'
            and f['source_ref']['claim_basis']=='EXPLICIT_USER_STATEMENT']
        runtime = dict(context=deepcopy(compiled.content['request_context']),
            evidence=deepcopy(compiled.content), evidence_limitations=list(compiled.limitations),
            memory=deepcopy(menv), normalisations=normalisations,
            task_request=task, temporal_request=dict(timezone=request.schedule_timezone,
                horizon=request.schedule_horizon, allowed_windows=list(request.allowed_windows)),
            future_use_policy=request.future_policy)
        from .planning import source_bindings
        runtime['memory_source_bindings'] = source_bindings(memory)
        runtime['scope'] = dict(learner_id=request.scope.learner_id, course_id=request.scope.course_id,
            session_id=request.session_id, as_of=request.as_of, window=request.scope.public_window(),
            snapshot_version=request.scope.snapshot, corpus_version=request.source_version)
        reject_sidecars(runtime)
        clarification_codes = []
        if clarification.needs_clarification:
            clarification_codes.append('FROZEN_CLARIFICATION_GATE')
        if task['mode']=='EXPLICIT_SCHEDULE':
            for key, value in [('MISSING_TIMEZONE', request.schedule_timezone),
                               ('MISSING_ALLOWED_WINDOWS', request.allowed_windows), ('MISSING_HORIZON', request.schedule_horizon)]:
                if not value:
                    clarification_codes.append(key)
        planner = None
        if activate[2]:
            from .planning import bridge_from_m1, validate_bridge
            self.planner_work += 1
            events.append('P1_ACTUAL_ENVELOPE_PROJECTION')
            bridge = self.build_planning_bridge(request, compiled, task, memory)
            checked = self.check_planning_bridge(bridge)
            if task['mode']=='EXPLICIT_SCHEDULE':
                clarification_codes.extend(x['code'] for x in checked['issues'] if x['severity'] in ('ERROR', 'NOT_CHECKABLE', 'CONTRADICTION'))
            planner = dict(status='CANDIDATE_PENDING_DISABLED_TRANSPORT' if checked['outcome']=='PASSED_ENCODED_CHECKS' and not clarification_codes else 'NEEDS_INFORMATION',
                           bridge=bridge, validation=checked, request=None)
            if planner['status']=='CANDIDATE_PENDING_DISABLED_TRANSPORT':
                planner['request'] = candidate_request(runtime, bridge, checked)
        final = final_request(runtime, planner=planner, clarification=clarification_codes)
        events.append('FINAL_REQUEST_BUILT_TRANSPORT_DISABLED')
        # Common upper cap includes all model-visible duplication/schema overhead.
        if any(self.compiler._tokens(p) > self.request_budget for p in [final, *([planner['request']] if planner and planner['request'] else [])]):
            raise ValueError('COMPLETE_REQUEST_EXCEEDS_COMMON_BUDGET')
        key = digest(dict(final=final, candidate=planner['request'] if planner else None,
            scope=request.scope.internal(), source_version=request.source_version,
            memory_state_version=request.memory_state_version, session=request.session_id,
            native_state_sha256=memory.trace.get('native_state_sha256'),
            model_role_contract='PENDING_AUTHOR_APPROVAL', evidence_budget=self.compiler.token_budget,
            request_budget=self.request_budget))
        fact_trace = []
        records = final['runtime_input']['evidence']['selected_evidence']
        for fact in visible.facts:
            destinations = [(i, x['content']['activity'][fact.domain][fact.metric]) for i,x in enumerate(records)
                if isinstance(x['content'], dict) and fact.metric in x['content'].get('activity', {}).get(fact.domain, {})]
            if destinations:
                if len(destinations)!=1 or destinations[0][1]!=fact.public():
                    raise ValueError('E1_FACT_TO_FINAL_REQUEST_MISMATCH')
                fact_trace.append(dict(**fact.trace(), final_value_verified=True,
                    final_json_pointer=f'/runtime_input/evidence/selected_evidence/{destinations[0][0]}/content/activity/{fact.domain}/{fact.metric}'))
        course_ids = [s.source_id for s in rag.sources] if rag else []
        trace = dict(mode=request.mode.value, ordered_events=events,
            primary_p3_input=scoped.primary_input.to_payload(), route_status=route_status,
            route=route.to_trace_dict() if route else None, activation=active.to_trace_dict(),
            purpose_resolution=use, compiled_evidence_sha256=compiled.compiled_evidence_sha256,
            retained_evidence_ids=list(compiled.evidence_ids), budget_omitted_ids=omitted,
            e1_fact_trace=fact_trace, course_returned_ids=course_ids,
            course_retention_complete=set(course_ids) <= retained | set(omitted),
            memory_returned_ids=full_ids, memory_retention_complete=set(full_ids) <= retained | set(omitted),
            memory_diagnostics=memory.trace, request_cache_key=key,
            final_request_sha256=digest(final), generation_calls=0, candidate_calls=0,
            judge_calls=0, response_quality_scored=False)
        return dict(final_request=final, planner=planner, trace=trace)
