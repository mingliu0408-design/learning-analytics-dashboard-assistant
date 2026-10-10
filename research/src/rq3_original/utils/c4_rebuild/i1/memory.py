"""Generic, query-relevant seed read with no purpose-specific relationship use."""
from copy import deepcopy
from types import FunctionType
from utils.c4_rebuild.language import purpose
from utils.c4_rebuild.memory import NativeM1, MemoryBundle, m1_dependencies
from utils.c4_rebuild.service import ResearchService

GENERIC = 'I1_GENERIC_SEED_V1'


class I1ResearchService(ResearchService):
    def resolve_memory_use(self, request):
        result = purpose(request.query, request.memory_purpose)
        if result['value'] == 'UNKNOWN':
            result = dict(result, original_purpose='UNKNOWN', value=GENERIC,
                          fallback='GENERIC_READ_ONLY_SEED', expansion='UNSUPPORTED_PURPOSE')
        return result

    def prepare(self, request):
        result = super().prepare(request)
        trace = result['trace']
        if trace['route_status'] == 'MISSING_ROUTE_NOT_YES':
            # Unavailable is an explicit failure/clarification, never a valid all-NO route.
            result['final_request']['clarification_required'].append('P3_ROUTE_UNAVAILABLE')
            result['final_request']['plan_status'] = 'ROUTE_UNAVAILABLE'
            from utils.c4_dashboard_scoped.scope import digest
            trace['final_request_sha256'] = digest(result['final_request'])
        trace['integration_version'] = 'I1_GENERIC_SEED_V1'
        return result


class I1NativeM1(NativeM1):
    def read_envelope(self, target, use):
        if use != GENERIC:
            return super().read_envelope(target, use)
        inherited, _, _ = m1_dependencies()
        # Private function globals preserve the original body and all native checks.
        # There is no mutation of M1 PURPOSES or its process-global network guard.
        local = dict(inherited.__globals__)
        local['PURPOSES'] = dict(local['PURPOSES'], **{GENERIC: ()})
        reader = FunctionType(inherited.__code__, local, 'i1_generic_seed', inherited.__defaults__)
        reader.__kwdefaults__ = inherited.__kwdefaults__
        env, trace = reader(self.databases, self.graph, dict(target=target, purpose=use),
                            expand=False, backend=self.backend)
        body = env.payload
        # Even relations between two seeds are not consumed under unknown purpose.
        body['source_link_edges'] = []
        body['accepted_action_ids'] = []
        body['chosen_active_plan_id'] = None
        body['missing_information'].append('RELATION_EXPANSION_UNSUPPORTED_PURPOSE')
        cls = inherited.__globals__['ReadOnlyEnvelope']
        import json
        return cls(json.dumps(body, ensure_ascii=False, sort_keys=True)), trace

    def read(self, request, use):
        result = super().read(request, use)
        trace = deepcopy(result.trace)
        trace['generic_fallback'] = 'EXERCISED' if use == GENERIC else 'NOT_NEEDED'
        trace['record_state'] = 'AVAILABLE' if result.envelope['facts'] else 'UNAVAILABLE_OR_NO_RELEVANT_SOURCE'
        trace['plan_state'] = 'AMBIGUOUS' if result.envelope['status'] == 'AMBIGUOUS' else 'NO_AMBIGUITY_DETECTED'
        trace['relation_expansion'] = 'UNSUPPORTED_PURPOSE' if use == GENERIC else ('ENABLED_SUPPORTED_PURPOSE' if self.expand else 'DISABLED')
        return MemoryBundle(result.envelope, result.authority, trace)
