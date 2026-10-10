"""Source -> shared actual P3 -> cloned modules -> P1 -> final -> freeze."""
from .common import sha, write_once, load
from .frozen_p3 import ROLE_NAMES
from .renderer import candidate_payload, final_payload
from .schemas import final_errors, errors, LOCAL_CANDIDATE


class Orchestrator:
    def __init__(self, runner, frozen, worker):
        self.runner, self.frozen, self.worker = runner, frozen, worker

    def route(self, source):
        results = {}
        for role in ROLE_NAMES:
            payload = self.frozen.request(role, source['primary'])
            # Full messages/model/schema/settings identity, shared for every identical input.
            logical = 'P3:'+role+':'+sha(payload)
            results[role] = self.runner.perform(logical, role, payload)
        if any(r['status'] != 'ACCEPTED' for r in results.values()):
            route = None
        else:
            route = dict(rag_required=results['RAG']['value']['rag_required'],
                memory_required=results['MEMORY']['value']['memory_required'],
                planning_required=results['B4_PLANNING']['value']['planning_required'],
                provider_identity=('ACTUAL_FROZEN_P3' if self.runner.transport.kind=='LIVE' else 'MOCK_TRANSPORT_NO_P3_INFERENCE'))
        self.runner.stage(source['primary_sha256'], 'B_FROZEN_P3',
                          {'primary':source['primary_sha256'],'frozen_roles':self.frozen.identity},
                          dict(route=route, roles=results))
        return route

    def condition(self, slot, mode, source, route):
        logical = slot+':'+mode
        message = dict(op='prepare',slot=slot,mode=mode,primary_sha256=source['primary_sha256'],route=route,
            memory_backend=('M1_HYBRID_LINKS_DEV' if self.runner.transport.kind=='LIVE' else 'LEXICAL_NATIVE_DIAGNOSTIC'))
        rebuilt = self.worker.call(message)
        self.runner.stage(logical, 'C_MODULE_REBUILD', message, rebuilt)
        prepared = rebuilt['prepared']
        planner = prepared['planner']
        accepted = None
        failed = False
        candidate_result = None
        if planner and planner['status'] == 'CANDIDATE_PENDING_DISABLED_TRANSPORT':
            config = self.runner.config['generation_roles']['CANDIDATE']
            initial = candidate_payload(prepared, config)
            def validate(value):
                structural = errors(value, LOCAL_CANDIDATE)
                if structural:
                    return structural
                checked = self.worker.call(dict(op='check_candidate', bridge=planner['bridge'], candidate=value))
                return [x for x in checked['issues'] if x['severity'] in ('ERROR','CONTRADICTION','NOT_CHECKABLE')] if checked['outcome'] != 'PASSED_ENCODED_CHECKS' else []
            candidate_result = self.runner.perform(logical+':CANDIDATE', 'CANDIDATE', initial, validate,
                lambda previous, issues: candidate_payload(prepared, config, previous=previous, issues=issues))
            if candidate_result['status'] == 'ACCEPTED':
                accepted = candidate_result['value']
            else:
                failed = True
        self.runner.stage(logical, 'D_E_CANDIDATE_CHECK_REPAIR',
            {'modules':sha(rebuilt),'admitted':bool(planner and planner['request'])},
            {'result':candidate_result,'accepted_plan':accepted,'planning_failed':failed,
             'planning_status':('ACCEPTED_ENCODED_CHECKS_SEMANTICS_UNCHECKED' if accepted else 'CANDIDATE_FAILED' if failed else planner['status'] if planner else 'NOT_ACTIVATED')})
        payload = final_payload(prepared, self.runner.config['generation_roles']['FINAL'], accepted, failed)
        ids = prepared['trace']['retained_evidence_ids']
        result = self.runner.perform(logical+':FINAL', 'FINAL', payload,
                                   lambda value: final_errors(value, ids, accepted))
        freeze = dict(task_id=slot, mode=mode, result=result,
                      source_sha256=sha(source), modules_sha256=sha(rebuilt), final_request_sha256=sha(payload),
                      accepted_plan_sha256=sha(accepted) if accepted else None,
                      origin=self.runner.transport.kind, human_scores=[], semantic_support='NOT_CHECKED',
                      answer_plan_fidelity='NOT_CHECKED', planning_failed=failed,
                      planning_status=('ACCEPTED_ENCODED_CHECKS_SEMANTICS_UNCHECKED' if accepted else 'CANDIDATE_FAILED' if failed else planner['status'] if planner else 'NOT_ACTIVATED'))
        return self.runner.stage(logical, 'F_G_RESPONSE_FREEZE', {'payload':sha(payload)}, freeze)

    def run(self, manifest):
        outputs = []
        for slot in manifest['task_ids']:
            source = self.worker.call(dict(op='source',slot=slot))
            expected = next(x for x in manifest['sources'] if x['task_id']==slot)
            if sha(source) != expected['source_sha256']:
                raise ValueError('SOURCE_STAGE_CHANGED_AFTER_MANIFEST')
            self.runner.stage(slot, 'A_VALIDATED_SOURCE', {'source_task':source['source_task_sha256']}, source)
            route = None
            routed = False
            for mode in manifest['modes']:
                if mode.startswith(('S2','S3','S4','S5')) and not source['clarification'] and not routed:
                    route = self.route(source)
                    routed = True
                outputs.append(self.condition(slot, mode, source, route if mode.startswith(('S2','S3','S4','S5')) else None))
        return outputs
