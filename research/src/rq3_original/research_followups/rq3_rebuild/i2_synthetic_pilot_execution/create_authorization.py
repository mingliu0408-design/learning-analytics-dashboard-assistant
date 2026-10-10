"""Record this session's explicit user message using the unchanged I1 schema."""
from pathlib import Path
from datetime import datetime
from zoneinfo import ZoneInfo
import sys
ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT))
from utils.c4_rebuild.i1.common import HOME, load, sha, write_once
from utils.c4_rebuild.i1.policy import preflight

HERE = Path(__file__).resolve().parent
AUTH = Path('/Users/liuming/Downloads/RQ3_REBUILD_I2_SYNTHETIC_PILOT_AUTHORIZATION_2026-09-07.json')
OUTPUT = Path('/Users/liuming/Downloads/RQ3_REBUILD_I2_SYNTHETIC_PILOT_OUTPUT_2026-09-07')

if __name__ == '__main__':
    assert load(HERE/'PREFLIGHT_VERIFICATION.json')['status'] == 'PASS'
    assert not AUTH.exists() and not OUTPUT.exists()
    tests = (HERE/'OFFLINE_TEST_OUTPUT.txt').read_text()
    assert 'Ran 62 tests' in tests and '\nOK\n' in tests
    config, manifest, binding, _ = preflight(HOME/'PILOT_CONFIGURATION_PROPOSED.json',
        HOME/'TASK_MANIFEST.json', HOME/'SOURCE_MANIFEST.json')
    approval = load(HOME/'EXTERNAL_APPROVAL_TEMPLATE.json')
    approval.update(status='AUTHORIZED', authorized_by='DIRECT_USER_OF_CURRENT_CODEX_CONVERSATION',
        authorized_at=datetime.now(ZoneInfo('Europe/Oslo')).isoformat(),
        signature='OPERATOR_RECORDED_EXPLICIT_USER_MESSAGE_APPROVAL',
        output_directory=str(OUTPUT), **binding)
    write_once(AUTH, approval)
    preflight(HOME/'PILOT_CONFIGURATION_PROPOSED.json', HOME/'TASK_MANIFEST.json',
        HOME/'SOURCE_MANIFEST.json', execute=True, approval_path=AUTH, output=OUTPUT)
    message = (HERE/'DIRECT_USER_APPROVAL_MESSAGE.txt').read_bytes()
    write_once(HERE/'DIRECT_APPROVAL_AUDIT.json', dict(
        authority='DIRECT_USER_MESSAGE_IN_CURRENT_CONVERSATION',
        quotation_file='DIRECT_USER_APPROVAL_MESSAGE.txt', quotation_sha256=sha(message),
        quotation_boundary='Exact request text beginning My request; Markdown escapes preserved. No attached activation template substituted.',
        authorization_file=str(AUTH), authorization_sha256=sha(AUTH.read_bytes()),
        approval_recorded_at=approval['authorized_at'],
        timestamp_basis='CURRENT_SYSTEM_TIME_AT_RECORDING; MESSAGE_ARRIVAL_TIMESTAMP_NOT_EXPOSED',
        signature_semantics='OPERATOR_RECORD_ONLY; NO_PERSONAL_SIGNATURE_IMITATION_OR_CRYPTOGRAPHIC_AUTHENTICATION',
        approved_scope='EXPOSED_SYNTHETIC_ENGINEERING_PILOT_ONLY',
        research_deployment_authorized=False, judge_authorized=False, human_scoring_authorized=False,
        resume_unknown_attempts=[], protocol_deviations=[], original_config_approved_field=False,
        key_material_recorded=False))
    print('EXTERNAL_I1_APPROVAL_RECORDED_AND_VALIDATED')
