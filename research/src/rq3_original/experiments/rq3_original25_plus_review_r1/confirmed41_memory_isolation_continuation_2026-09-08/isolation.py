"""Credential-free subprocess for complete frozen A1 module preparation."""
from recovery import ROOT, HERE, DATA, sha, load, StopRun
from contextlib import ExitStack
from pathlib import Path
import fcntl
import json
import os
import signal
import socket
import subprocess
import sys
import tempfile


def child_environment():
    env={k:os.environ[k] for k in ('PATH','TMPDIR','LANG','LC_CTYPE','LC_ALL') if k in os.environ}
    env.update(PYTHONDONTWRITEBYTECODE='1',HF_HUB_OFFLINE='1',TRANSFORMERS_OFFLINE='1',
        HF_DATASETS_OFFLINE='1',HF_HUB_DISABLE_TELEMETRY='1',TOKENIZERS_PARALLELISM='false',
        OMP_NUM_THREADS='1',MKL_NUM_THREADS='1')
    return env


def parent_socket_allocation_check():
    # Allocating and closing an unconnected socket sends no traffic.
    try:
        with socket.socket(socket.AF_INET,socket.SOCK_STREAM):pass
    except RuntimeError as exc:
        if exc.args==('M0_NETWORK_DISABLED',):
            raise StopRun('PARENT_CONTAMINATED_BY_MEMORY_NETWORK_GUARD') from None
        raise


def prepare_many(request):
    """Run only inside a disposable process; scientific functions unchanged."""
    import interface_a1 as interface
    from utils.c4_rebuild.i1.native_backend import I1LocalBackend
    task=request['task'];binding=request['binding'];config=request['config'];route=request['route']
    result={};backend=None
    with ExitStack() as stack:
        for mode in request['modes']:
            native=None
            if backend is None and mode.startswith(('S3','S5')) and route and route['memory_required'] and load(DATA/'native_initial'/task['task_id']/'state_readable.json')['memories']:
                lock=stack.enter_context(open('/private/tmp/rq3-rebuild-local-inference.lock','a+'))
                fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
                td=stack.enter_context(tempfile.TemporaryDirectory(prefix='rq3-a3-native-backend-'))
                backend=I1LocalBackend(Path(td));stack.callback(backend.close)
                native=dict(identity=backend.identity,ready=backend.ready)
            r=interface.prepare(task,binding,mode,config,
                route=route if mode.startswith(('S2','S3','S4','S5')) else None,
                allow_target_reads=True,backend=backend)
            result[mode]=dict(modules=r,native_backend=native)
    return result


def isolated_prepare(task,binding,modes,config,route,timeout=180):
    parent_socket_allocation_check()
    request=dict(task=task,binding=binding,modes=modes,config=config,route=route)
    process=subprocess.Popen([sys.executable,'-B',str(HERE/'isolation.py')],
        cwd=ROOT,stdin=subprocess.PIPE,stdout=subprocess.PIPE,stderr=subprocess.PIPE,
        env=child_environment(),start_new_session=True)
    try:
        stdout,stderr=process.communicate(json.dumps(request,ensure_ascii=False).encode(),timeout=timeout)
    except subprocess.TimeoutExpired:
        os.killpg(process.pid,signal.SIGTERM)
        try:process.communicate(timeout=5)
        except subprocess.TimeoutExpired:
            os.killpg(process.pid,signal.SIGKILL);process.communicate(timeout=5)
        raise StopRun('OFFLINE_PREPARATION_TIMEOUT_NO_AUTORESTART') from None
    try:result=json.loads(stdout)
    except (ValueError,UnicodeError):
        raise StopRun('OFFLINE_PREPARATION_INVALID_RESULT') from None
    if process.returncode or result.get('ok') is not True:
        raise StopRun('OFFLINE_PREPARATION_FAILED:'+result.get('safe_error_class','UNKNOWN'))
    assert result['request_sha256']==sha(request) and result['result_sha256']==sha(result['results'])
    assert set(result['results'])==set(modes)
    assert result['memory_guard']=='M0_NETWORK_DISABLED' and result['credentials_available'] is False
    parent_socket_allocation_check()
    return result['results'],dict(worker_pid=process.pid,request_sha256=sha(request),
        result_sha256=result['result_sha256'],memory_guard=result['memory_guard'],
        parent_socket_allocation_passed=True,credentials_available=False,stderr_bytes=len(stderr))


def main():
    from utils.c4_rebuild.memory import m1_dependencies
    from recovery import base
    m1_dependencies();base.offline()
    try:
        with socket.socket(socket.AF_INET,socket.SOCK_STREAM):pass
    except RuntimeError as exc:
        assert exc.args==('M0_NETWORK_DISABLED',)
    else:raise RuntimeError('OFFLINE_GUARD_NOT_INSTALLED')
    request=json.loads(sys.stdin.buffer.read())
    results=prepare_many(request)
    print(json.dumps(dict(ok=True,request_sha256=sha(request),results=results,result_sha256=sha(results),
        memory_guard='M0_NETWORK_DISABLED',credentials_available=any(
            k.startswith(('OPENAI_','AZURE_','ANTHROPIC_')) for k in os.environ)),
        ensure_ascii=False,allow_nan=False))


if __name__=='__main__':
    try:main()
    except BaseException as exc:
        print(json.dumps(dict(ok=False,safe_error_class=type(exc).__module__+'.'+type(exc).__name__)))
        raise SystemExit(1)
