"""Shared paths and unchanged R1 imports for the additive A1 continuation."""
from pathlib import Path
import json
import hashlib
import sys
import importlib.util

HERE=Path(__file__).resolve().parent
DATA=HERE.parent
ROOT=DATA.parents[1]
PARENT=DATA/'confirmed41_generation_2026-09-07/results'
PARENT_RUN=PARENT/'run'
sys.dont_write_bytecode=True
sys.path.insert(0,str(DATA))
import adapter as base
_spec=importlib.util.spec_from_file_location('a1_parent_r1_entry',DATA/'run_batch.py')
legacy=importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(legacy)
from utils.c4_rebuild.i1.common import canonical,sha,load,write_once,append,utc

def policy():return load(HERE/'CONTINUATION_POLICY.json')
def rows(path):return [json.loads(s) for s in Path(path).read_text().splitlines() if s]
def save(path,value):
    path=Path(path);path.parent.mkdir(parents=True,exist_ok=True)
    with path.open('x') as f:json.dump(value,f,ensure_ascii=False,indent=2,allow_nan=False);f.write('\n')
def file_entry(path,root):
    path=Path(path)
    return dict(path=str(path.relative_to(root)),sha256=sha(path.read_bytes()),bytes=path.stat().st_size)
