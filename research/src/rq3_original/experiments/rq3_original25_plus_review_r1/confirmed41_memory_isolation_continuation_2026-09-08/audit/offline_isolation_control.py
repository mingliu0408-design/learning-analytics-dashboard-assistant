import json
import socket
import subprocess
import sys
from pathlib import Path
import httpx
import openai
from openai import OpenAI

ROOT = Path('/Users/liuming/Downloads/rq2_v2_parallel/rq3-rebuild-i1-pilot-launch')
sys.path.insert(0, str(ROOT))
REPORT = Path(__file__).with_name('OFFLINE_ISOLATION_CONTROL.json')

# Allocate and close an unconnected socket. There is no DNS or network send.
def handler(request):
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM):
        pass
    return httpx.Response(200, request=request, json={
        'id': 'LOCAL_MOCK_ONLY', 'object': 'chat.completion', 'created': 0,
        'model': 'local-mock', 'choices': [{'index': 0, 'finish_reason': 'stop',
        'message': {'role': 'assistant', 'content': 'LOCAL_MOCK_RETURNED'}}]})

def make_client():
    return OpenAI(api_key='DUMMY_LOCAL_ONLY', base_url='https://diagnostic.invalid/v1',
                  max_retries=0, timeout=30,
                  http_client=httpx.Client(transport=httpx.MockTransport(handler)))

def probe(client, phase):
    try:
        result = client.chat.completions.create(model='local-mock',
                   messages=[{'role': 'user', 'content': 'synthetic local probe'}])
        return {'phase': phase, 'result': result.choices[0].message.content}
    except Exception as exc:
        chain = []
        while exc is not None:
            chain.append({'type': type(exc).__module__ + '.' + type(exc).__name__,
                          'message': str(exc)})
            exc = exc.__cause__
        return {'phase': phase, 'result': 'EXCEPTION', 'chain': chain}

client = make_client()
tests = [probe(client, 'parent_before_memory')]
child_code = '''import json, socket
from utils.c4_rebuild.memory import m1_dependencies
m1_dependencies()
try:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM):
        pass
    result = {'memory_worker_guard': 'UNEXPECTEDLY_ALLOWED'}
except RuntimeError as exc:
    result = {'memory_worker_guard': str(exc)}
print(json.dumps(result))
'''
child = subprocess.run([sys.executable, '-B', '-c', child_code], cwd=ROOT,
                       capture_output=True, text=True, check=True, timeout=30)
child_result = json.loads(child.stdout)
assert child_result['memory_worker_guard'] == 'M0_NETWORK_DISABLED'
tests.append({'phase': 'isolated_memory_child', **child_result})
tests.append(probe(client, 'parent_after_isolated_memory_child'))
from utils.c4_rebuild.memory import m1_dependencies
m1_dependencies()
tests.append(probe(client, 'parent_after_in_process_memory_import'))
client.close()
client = make_client()
tests.append(probe(client, 'parent_after_rebuilding_client'))
client.close()
assert tests[0]['result'] == tests[2]['result'] == 'LOCAL_MOCK_RETURNED'
for test in tests[3:]:
    assert test['chain'][-1]['message'] == 'M0_NETWORK_DISABLED'
    assert test['chain'][0]['type'] == 'openai.APIConnectionError'
report = {'test': 'UNCONNECTED_SOCKET_AND_MOCK_SDK_ISOLATION_CONTROL',
          'git_head': 'c0082814165067f4c0d157083bd5c5c1ad42a796',
          'openai_version': openai.__version__, 'httpx_version': httpx.__version__,
          'actual_network_requests': 0, 'actual_provider_calls': 0,
          'real_api_credentials_used': False, 'research_payloads_used': False,
          'repository_files_modified': False, 'tests': tests, 'assertions': 'PASS'}
REPORT.write_text(json.dumps(report, ensure_ascii=False, indent=2) + '\n')
print(json.dumps(report, ensure_ascii=False, indent=2))
print('REPORT=' + str(REPORT))
