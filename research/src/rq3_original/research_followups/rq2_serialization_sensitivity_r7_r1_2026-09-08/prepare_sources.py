"""Prepare only the frozen inference sources. Does not read TEST Gold."""
from pathlib import Path
import hashlib,json,subprocess,zipfile
BASE=Path(__file__).resolve().parent
REPO=BASE.parents[1]
S4=REPO/'evaluation/capability_routing_rq2_v2_stage4'
S5=REPO/'evaluation/capability_routing_rq2_v2_stage5'
def sha(p):
 h=hashlib.sha256()
 with p.open('rb') as f:
  for b in iter(lambda:f.read(1048576),b''): h.update(b)
 return h.hexdigest()
def write(name,obj): (BASE/name).write_text(json.dumps(obj,ensure_ascii=False,indent=2)+'\n')
def main():
 assert subprocess.check_output(['git','rev-parse','HEAD'],cwd=REPO,text=True).strip()=='1ddad9c9050565b56e15fe6cfb7982ce1d78cce0'
 (BASE/'sources').mkdir(exist_ok=True)
 (BASE/'runtime').mkdir(exist_ok=True)
 receipt=json.loads((S5/'track_a_deterministic_test_predictions/deterministic_test_execution_source_manifest_v1.json').read_text())
 specs={
 'track_h.py':(S4/'track_h_b2_b3/track_h.py','90025880bb523fae599060e8acd6c883d7f1aac1532b5c6d0faa97e6bf56ee59'),
 'canonical_text.py':(REPO/'evaluation/capability_routing_rq2_v2_stage1/track_c_b2_b3/canonical_text.py','d6eaf3216d40e24c22dd4e4a9e47b49f2542460a2c763a330ee348d1c0ed219d'),
 'execute_deterministic_test.py':(S4/'final_integration/execute_deterministic_test.py',receipt['frozen_execution']['runner_sha256']),
 'b2_frozen_model_v1.json':(S4/'track_h_b2_b3/b2_frozen_model_v1.json','fec02db702dd9ce0a86934c4fe626b27944657b92241ce8e35d4cf06c3fbda17'),
 'b3_frozen_model_v1.json':(S4/'track_h_b2_b3/b3_frozen_model_v1.json','256315f594687763513d7586f18b76e94e073ec87e3babec842eab9e3430eb32'),
 'test_inputs.jsonl':(S4/'final_integration/deterministic_test_execution_manifest_v1.jsonl',receipt['frozen_test_inputs']['execution_manifest']['sha256']),
 'original_deterministic.jsonl':(S5/'track_a_deterministic_test_predictions/deterministic_test_terminal_results_v1.jsonl',receipt['terminal_output']['sha256']),
 'original_b4.jsonl':(S5/'track_b_b4_test_predictions/b4_test_terminal_results_v1.jsonl','f8c0c0e8e1debc34b99107ee6b1850391a911bfcb15e16be82bcb54c562d5270'),
 }
 bindings=[]
 for dest,(p,expected) in specs.items():
  actual=sha(p);assert actual==expected,(p,actual,expected)
  (BASE/'sources'/dest).write_bytes(p.read_bytes())
  bindings.append({'packaged_path':'sources/'+dest,'source_path':str(p),'sha256':actual,'size_bytes':p.stat().st_size,'verification':'MATCHED_HISTORICAL_BINDING'})
 encoder=Path(receipt['execution_roots']['c0_root'])/'semantic_runtime/models/all-mpnet-base-v2/e8c3b32edf5434bc2275fc9bab85f82640a19130'
 historical={e['path']:e['sha256'] for e in receipt['frozen_source_registry']['external_files'] if '/models/' in e['path']}
 encoder_files=[]
 for p in sorted(encoder.rglob('*')):
  if not p.is_file():continue
  actual=sha(p);expected=historical.get(str(p))
  if expected:assert actual==expected,(p,actual,expected)
  encoder_files.append({'path':str(p),'relative_path':str(p.relative_to(encoder)),'sha256':actual,'historical_sha256':expected,'size_bytes':p.stat().st_size,'binding':'MATCHED_STAGE5A' if expected else 'CURRENT_FIXED_REVISION_FILE_SNAPSHOT'})
 cfg={'encoder_path':str(encoder),'python':'/Users/liuming/Downloads/duteaiapp_cfull_semantic_integrated_v1_副本3/.venv/bin/python','sources':bindings,'encoder_files':encoder_files,'source_stage_head':receipt['frozen_source_registry']['source_stage_head'],'original_starting_head':receipt['starting_state']['starting_head'],'feature_fields':['current_query','current_page','dashboard_context','visible_conversation_history'],'inference_budget':{'test_labelled':36,'dev_compact':36},'normalization':'L2_UNIT','batch_size':16,'device':'cpu','dtype':'float32'}
 write('SOURCE_IDENTITY.json',cfg)
 packets=[]
 for name in ['THESIS_R7_R1_SERIALIZER_SENSITIVITY_CODEX_TASK_PACKET_2026-09-08.zip','THESIS_TECH1_RQ2_REVIEW_2026-09-03.zip','THESIS_RQ3_41_T6_R1_INTRO_FUTURE_REVIEW_2026-09-08.zip']:
  p=Path('/Users/liuming/Downloads')/name
  with zipfile.ZipFile(p) as z:
   names=z.namelist(); assert len(names)==len(set(names)); assert all(not Path(n).is_absolute() and '..' not in Path(n).parts for n in names)
   # Relevant task/TECH1/T6 RQ2 text is read selectively; no RQ3 scoring material is opened.
   selected=([n for n in names if n.endswith(('START_HERE.md','COMMON_BOUNDARIES.md','SKILLS_PROTOCOL.md','CODEX_R7_R1_SERIALIZER_SENSITIVITY.md'))] if 'TASK_PACKET' in name else [n for n in names if n.endswith('RQ2_B2_B3_DEV_TEST_SERIALIZATION_AUDIT.md')])
   if 'T6_R1' in name:selected=['source/tables/chapter4/rq2_frozen_test.tex','source/appendices/tables/rq2_results.tex']
   members={n:hashlib.sha256(z.read(n)).hexdigest() for n in selected}
   if 'T6_R1' in name:
    (BASE/'T6_RQ2_FROZEN_EXCERPTS.txt').write_text('\n\n'.join(n+'\n'+z.read(n).decode() for n in selected))
  packets.append({'path':str(p),'sha256':sha(p),'size_bytes':p.stat().st_size,'member_count':len(names),'read_members':members})
 write('INPUT_PACKETS.json',packets)
 print('PASS inference source hashes and 3 historical encoder fingerprints; prepared 36 TEST inputs without Gold')
if __name__=='__main__':main()
