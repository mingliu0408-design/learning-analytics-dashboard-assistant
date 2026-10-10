"""M1 paths and inherited imports; no writes or ML imports at module import."""
from pathlib import Path
import sys

OWNED = Path(__file__).resolve().parents[1]
REPO = OWNED.parents[2]
M0 = OWNED.parent / 'm0_memory_data'
START = '8b22f73aab1930c2850b0301ceffe785a7599138'
sys.dont_write_bytecode = True
sys.path.insert(0, str(M0 / 'code'))
sys.path.insert(0, str(REPO))
from common import disable_network, object_sha, sha, utc, write_json, FLAGS
disable_network()

def fresh_output(path):
    path = Path(path).resolve()
    path.relative_to(OWNED)
    path.mkdir(parents=True, exist_ok=False)
    return path
