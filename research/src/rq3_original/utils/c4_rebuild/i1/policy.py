"""One approval contract shared by template, validator and runner."""
from datetime import datetime
from pathlib import Path
from .common import HOME, ROOT, load, sha
from .schemas import errors, VERSION

APPROVAL_VERSION = 'I1_EXECUTION_APPROVAL_V1'
CONFIG_VERSION = 'I1_PILOT_CONFIG_V1'
APPROVAL_SCHEMA = {'type':'object','additionalProperties':False,'required':[
    'schema_version','status','authorized_by','authorized_at','signature','scope','config_sha256',
    'manifest_sha256','source_manifest_sha256','output_directory','resume_unknown_attempts','protocol_deviations'],
    'properties':{
        **{k:{'type':'string'} for k in ('schema_version','status','authorized_by','authorized_at','signature',
            'scope','config_sha256','manifest_sha256','source_manifest_sha256','output_directory')},
        'resume_unknown_attempts':{'type':'array','items':{'type':'string'}},
        'protocol_deviations':{'type':'array','items':{'type':'string'}}}}


def verify_source_manifest(path):
    manifest = load(path)
    if manifest.get('schema_version') != 'I1_SOURCE_MANIFEST_V1':
        raise ValueError('SOURCE_MANIFEST_VERSION')
    for row in manifest['files']:
        p = ROOT/row['path']
        if not p.resolve().is_relative_to(ROOT) or p.is_symlink() or sha(p.read_bytes()) != row['sha256'] or p.stat().st_size != row['bytes']:
            raise ValueError('SOURCE_HASH_OR_SCOPE_MISMATCH:'+row['path'])
    return manifest


def verify_external_resources():
    receipt = load(HOME/'EXTERNAL_RUNTIME_RECEIPT.json')
    if receipt['status'] != 'AVAILABLE_HASH_CHECKED':
        raise ValueError('NATIVE_HYBRID_RESOURCE_UNAVAILABLE')
    for row in receipt['models']:
        p = Path(row['path'])
        if not p.is_file() or sha(p.read_bytes()) != row['expected_sha256']:
            raise ValueError('NATIVE_MODEL_SOURCE_CHANGED')
    for row in receipt['interpreters']:
        if str(Path(row['path']).resolve()) != row['resolved_path'] or sha(Path(row['resolved_path']).read_bytes()) != row['sha256']:
            raise ValueError('EXISTING_INTERPRETER_CHANGED')


def validate_config(config):
    template = load(HOME/'PILOT_CONFIGURATION_PROPOSED.json')
    if set(config) != set(template) or config.get('schema_version') != CONFIG_VERSION or config.get('role_contract_version') != VERSION:
        raise ValueError('CONFIG_SCHEMA_VERSION_OR_FIELDS')
    # I1 supports this bounded proposal only; changed policies require review/rebuild.
    if config != template:
        raise ValueError('CONFIG_DIFFERS_FROM_REVIEWED_PROPOSAL')
    if config['sdk_max_retries'] != 0 or config['max_attempts_per_slot'] != 2:
        raise ValueError('RETRY_POLICY')
    return config


def preflight(config_path, manifest_path, source_path, *, execute=False, approval_path=None, output=None):
    config, manifest = validate_config(load(config_path)), load(manifest_path)
    verify_source_manifest(source_path)
    if manifest.get('schema_version') != 'I1_TASK_MANIFEST_V1' or manifest.get('origin') != 'SYNTHETIC_MODEL_AUTHORED_EXPOSED':
        raise ValueError('MANIFEST_SCHEMA_OR_SOURCE_SCOPE')
    if manifest['task_ids'] != config['task_ids'] or manifest['modes'] != config['modes']:
        raise ValueError('ROSTER_OR_MODES_MISMATCH')
    binding = dict(config_sha256=sha(Path(config_path).read_bytes()),
                   manifest_sha256=sha(Path(manifest_path).read_bytes()),
                   source_manifest_sha256=sha(Path(source_path).read_bytes()))
    if execute:
        if not approval_path:
            raise PermissionError('NEW_DIRECT_AUTHOR_APPROVAL_REQUIRED')
        p = Path(approval_path).resolve()
        if p.is_relative_to(HOME) or p.is_symlink():
            raise PermissionError('APPROVAL_MUST_BE_EXTERNAL')
        a = load(p)
        if errors(a, APPROVAL_SCHEMA) or a['schema_version'] != APPROVAL_VERSION:
            raise PermissionError('APPROVAL_SCHEMA_VERSION')
        if a['status'] != 'AUTHORIZED' or a['scope'] != 'EXPOSED_SYNTHETIC_ENGINEERING_PILOT_ONLY':
            raise PermissionError('APPROVAL_SCOPE_OR_STATUS')
        if any(not a[k].strip() for k in ('authorized_by','authorized_at','signature')):
            raise PermissionError('AUTHOR_SIGNATURE_REQUIRED')
        date = datetime.fromisoformat(a['authorized_at'])
        if date.tzinfo is None:
            raise PermissionError('AUTHOR_DATE_REQUIRES_TIMEZONE')
        if any(a[k] != v for k,v in binding.items()) or not output or Path(a['output_directory']).resolve() != Path(output).resolve():
            raise PermissionError('APPROVAL_HASH_OR_OUTPUT_MISMATCH')
        if len(a['protocol_deviations']) > 3:
            raise PermissionError('DEVIATION_LIMIT_EXCEEDED')
        verify_external_resources()
        return config, manifest, binding, a
    return config, manifest, binding, None
