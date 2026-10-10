"""Launch the existing native venv with an explicit credential-free environment."""
import json,subprocess,sys
from pathlib import Path
base=Path(__file__).resolve().parent
cfg=json.loads((base/'SOURCE_IDENTITY.json').read_text())
(base/'runtime/tmp').mkdir(parents=True,exist_ok=True)
env={'PATH':'/usr/bin:/bin:/usr/sbin:/sbin','LANG':'en_US.UTF-8','PYTHONDONTWRITEBYTECODE':'1','HF_HUB_OFFLINE':'1','TRANSFORMERS_OFFLINE':'1','HF_DATASETS_OFFLINE':'1','TOKENIZERS_PARALLELISM':'false','OMP_NUM_THREADS':'1','MKL_NUM_THREADS':'1','OPENBLAS_NUM_THREADS':'1','VECLIB_MAXIMUM_THREADS':'1','NUMEXPR_NUM_THREADS':'1','HF_HOME':str(base/'runtime/hf'),'XDG_CACHE_HOME':str(base/'runtime/cache'),'TMPDIR':str(base/'runtime/tmp'),'MPLCONFIGDIR':str(base/'runtime/mpl')}
cmd=[cfg['python'],'-I','-B',str(base/'run_inference.py'),*sys.argv[1:]]
print('Starting bounded local CPU inference; no inherited credential environment.',flush=True)
with (base/'runtime/inference_stdout.log').open('w') as log:
 p=subprocess.run(cmd,cwd=base,env=env,stdout=log,stderr=subprocess.STDOUT)
print((base/'runtime/inference_stdout.log').read_text())
raise SystemExit(p.returncode)
