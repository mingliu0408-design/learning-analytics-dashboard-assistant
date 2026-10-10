from pathlib import Path
import io
import sys
import unittest
sys.path.insert(0,str(Path(__file__).resolve().parents[3]))
from utils.c4_rag_lab.common import OUT, write_json, offline_guard

stream=io.StringIO()
with offline_guard() as guard:
    suite=unittest.defaultTestLoader.discover(str(OUT),pattern='test_lab.py')
    r=unittest.TextTestRunner(stream=stream,verbosity=2).run(suite)
attempt=len(list(OUT.glob('TEST_ATTEMPT_*.json')))+1
write_json(OUT/f'TEST_ATTEMPT_{attempt:02}.json',{'synthetic_only':True,'tests':r.testsRun,
    'passed':r.wasSuccessful(),'failures':len(r.failures),'errors':len(r.errors),'skipped':len(r.skipped),
    'network_guard':guard,'output':stream.getvalue(),'tokenizer':'actual local MPNet tokenizer; no model weights loaded'})
print(stream.getvalue())
sys.exit(not r.wasSuccessful())
