"""Read exact committed P3 roles; never substitute I0 synthetic route stubs."""
from .common import ROOT, sha, load
from .schemas import strict_schema_check
from evaluation.rq3_real_c4.i0_integration.build_r1_route_packages import PACKAGE_SPECS
from evaluation.rq3_real_c4.i0_integration.route_execution_runner import build_payload

ROLE_NAMES = ('RAG', 'MEMORY', 'B4_PLANNING')
FOUR = {'current_query', 'current_page', 'dashboard_context', 'visible_conversation_history'}


def nested_values(obj, key):
    out = []
    if isinstance(obj, dict):
        if key in obj:
            out.append(obj[key])
        for value in obj.values():
            out.extend(nested_values(value, key))
    elif isinstance(obj, list):
        for value in obj:
            out.extend(nested_values(value, key))
    return out


class FrozenP3:
    def __init__(self):
        self.roles, self.sources = {}, []
        for role in ROLE_NAMES:
            spec = PACKAGE_SPECS[role]
            for key in ('frozen_configuration', 'prompt', 'schema', 'prompt_package'):
                path = spec[key]
                if sha(path.read_bytes()) != spec[key+'_sha256']:
                    raise ValueError('FROZEN_P3_SOURCE_MISMATCH:'+str(path.relative_to(ROOT)))
                self.sources.append(dict(path=str(path.relative_to(ROOT)), sha256=sha(path.read_bytes()), bytes=path.stat().st_size))
            config = load(spec['frozen_configuration'])
            tokens = nested_values(config, spec['frozen_token_field'])
            if tokens != [spec['max_output_tokens']]:
                raise ValueError('FROZEN_ROLE_TOKEN_SETTING_MISMATCH:'+role)
            models = nested_values(config, 'model_snapshot')
            if models != ['gpt-4o-mini-2024-07-18'] or nested_values(config, 'temperature') != [0]:
                raise ValueError('FROZEN_MODEL_IDENTITY_MISSING')
            package = load(spec['prompt_package'])
            examples = package['few_shot_examples']
            self.roles[role] = dict(model='gpt-4o-mini-2024-07-18', max_output_tokens=tokens[0],
                temperature=0, response_schema_name=spec['response_schema_name'],
                prompt=spec['prompt'].read_text(), schema=load(spec['schema']), examples=examples,
                method_id=spec['method_id'], original_config_sha256=spec['frozen_configuration_sha256'])
            strict_schema_check(self.roles[role]['schema'])
        self.identity = sha(self.roles)

    def request(self, role, primary):
        if set(primary) != FOUR:
            raise ValueError('P3_EXACT_FOUR_FIELDS_REQUIRED')
        r = self.roles[role]
        return build_payload(plan=r, prompt=r['prompt'], schema=r['schema'], examples=r['examples'],
                             request={'semantic_input': primary})

    def receipt(self):
        return dict(identity=self.identity, sources=self.sources,
                    roles={k:{n:r[n] for n in ('model', 'max_output_tokens', 'temperature', 'method_id', 'original_config_sha256')}
                           for k,r in self.roles.items()})
