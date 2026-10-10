#!/usr/bin/env python3
"""Read-only E0 artifact/source validator; does not repeat functional tests."""
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import subprocess

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]
checks = []


def check(label, condition):
    checks.append({'check': label, 'passed': bool(condition)})
    if not condition:
        raise AssertionError(label)


def sha(p):
    return hashlib.sha256(p.read_bytes()).hexdigest()


required = ['START_HERE.md', 'COMPLETION_REPORT.md', 'STATUS.md', 'CROSS_PAGE_FUNCTIONAL_STATUS.md', 'RAW_DASHBOARD_SOURCE_MAP.csv', 'CROSS_PAGE_ACCEPTANCE_TESTS.py', 'SYNTHETIC_FIXTURE.json', 'SYNTHETIC_FIXTURE_ARITHMETIC.md', 'PAGE_FACT_TO_GENERATOR_TRACE.json', 'MINIMAL_EVIDENCE_WIRING_CHANGE_PLAN.md', 'SOURCE_MANIFEST.json', 'TEST_REPORT.md', 'TEST_RESULTS.json', 'TEST_STDOUT.txt', 'PORTABILITY_CHECK.json', 'FUNCTIONAL_ACCEPTANCE_RESULTS.json']
check('Required pre-commit deliverables exist', all((HERE / n).is_file() for n in required))
sources = json.loads((HERE / 'SOURCE_MANIFEST.json').read_text())
check('All 63 source files still match verified bytes', len(sources['committed_sources']) == 63 and all(sha(Path(r['path'])) == r['sha256'] for r in sources['committed_sources']))
snapshot = [r for r in sources['committed_sources'] if 'review_snapshot' in r]
check('54 snapshot files are exact source copies', len(snapshot) == 54 and all(sha(HERE / r['review_snapshot']) == r['sha256'] for r in snapshot))
raw = sources['raw_source_metadata_only']
check('8 current raw paths absent and 8 legacy metadata records present', sum(r['exists'] for r in raw) == 8 and sum(not r['exists'] for r in raw) == 8)
check('No private source rows were parsed', all(r['private_rows_parsed'] is False for r in raw))
result = json.loads((HERE / 'TEST_RESULTS.json').read_text())
check('15 diagnostic tests pass without failures errors skips', result['tests_run'] == 15 and result['diagnostic_suite_success'] and result['failures'] == result['errors'] == result['skips'] == 0)
acceptance = json.loads((HERE / 'FUNCTIONAL_ACCEPTANCE_RESULTS.json').read_text())
reqs = acceptance['requirements']
check('33 acceptance observations remain explicit: 14 pass and 19 fail', len(reqs) == 33 and sum(r['status'] == 'PASS' for r in reqs) == 14 and sum(r['status'] == 'FAIL' for r in reqs) == 19)
check('No provider model Judge server or blocked attempts', not result['blocked_execution_attempts'] and all(result[k] == 0 for k in ('provider_calls','llm_calls','judge_calls','model_loads','streamlit_launches','real_rows_parsed_by_tests')))
port = json.loads((HERE / 'PORTABILITY_CHECK.json').read_text())
check('Portable snapshot yields identical acceptance observations', port['exit_code'] == 0 and port['acceptance_observations_identical'] and port['results']['diagnostic_suite_success'])
check('Portable test used final harness bytes', sha(HERE / 'CROSS_PAGE_ACCEPTANCE_TESTS.py') == port['script_sha256'])
traces = json.loads((HERE / 'PAGE_FACT_TO_GENERATOR_TRACE.json').read_text())['traces']
check('All 8 trace cases execute actual raw synthesis without frozen pack reads', len(traces) == 8 and all(t['actual_raw_synthesiser_calls'] == 1 and t['frozen_pack_reads'] == 0 and not t['generation_sent'] for t in traces.values()))
check('All traced facts survive projection and V3 rendering', all(t['v3_renderer_check']['all_source_scalars_retained'] and all(f['survives_provider_projection'] for f in t['facts']) for t in traces.values()))
check('All traced facts have synthetic row provenance', all(f['fact_id'].startswith('SYNTHETIC:') and f['row_provenance'] and all(r['row_id'].startswith('SYNTHETIC:') for r in f['row_provenance']) for t in traces.values() for f in t['facts']))
check('Historical failed diagnostic run retained', (HERE / 'test_history/attempt01/TEST_STDOUT.txt').is_file() and json.loads((HERE / 'test_history/attempt01/TEST_RESULTS.json').read_text())['errors'] == 1)
files = [p for p in HERE.rglob('*') if p.is_file()]
check('No archive cache credentials raw pickle or git internals in output', not any(p.suffix in {'.zip','.pkl','.pickle','.xlsx','.pyc','.sqlite','.sqlite3'} or any(part in {'.git','.env','__pycache__','.DS_Store','.venv'} for part in p.relative_to(HERE).parts) for p in files))
check('No symlink output', not any(p.is_symlink() for p in HERE.rglob('*')))
changed = subprocess.check_output(['git','diff','--name-only','595b949185ad1b97cdbb9b0fdaeb9804aff7c45c'],cwd=ROOT,text=True).splitlines()
check('No pre-existing or out-of-scope tracked modifications', all(p.startswith('research_followups/rq3_rebuild/e0_crosspage_functional_check/') for p in changed))
print(json.dumps({'verified_at_utc': datetime.now(timezone.utc).isoformat(), 'passed': len(checks), 'checks': checks}, ensure_ascii=False, indent=2))
