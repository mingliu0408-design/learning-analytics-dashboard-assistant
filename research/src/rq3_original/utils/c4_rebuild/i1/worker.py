"""Network-free, finite subprocess protocol; guards stay inside the worker."""
import json
import os
import signal
import subprocess
import sys
from .common import ROOT, HOME, canonical


class OfflineWorker:
    def __init__(self, python=sys.executable, timeout=45):
        self.python, self.timeout = python, timeout

    def call(self, message):
        child = subprocess.Popen([self.python, '-B', str(HOME/'offline_worker.py')],
            stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
            cwd=ROOT, start_new_session=True)
        try:
            stdout, stderr = child.communicate(canonical(message), timeout=self.timeout)
        except subprocess.TimeoutExpired:
            os.killpg(child.pid, signal.SIGTERM)
            try:
                child.communicate(timeout=5)
            except subprocess.TimeoutExpired:
                os.killpg(child.pid, signal.SIGKILL)
                child.communicate()
            raise RuntimeError('OFFLINE_WORKER_TIMEOUT_NO_AUTORESTART') from None
        try:
            result = json.loads(stdout)
        except (ValueError, UnicodeError) as exc:
            raise RuntimeError('OFFLINE_WORKER_INVALID_RESULT:'+stderr.decode(errors='replace')[-1200:]) from exc
        if child.returncode or result.get('ok') is not True:
            raise RuntimeError('OFFLINE_WORKER_FAILED:'+result.get('error', 'unknown'))
        return result['result']
