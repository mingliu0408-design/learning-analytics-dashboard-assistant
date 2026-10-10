"""Run the frozen R7 analysis on text-free saved predictions; no encoding."""
import importlib.util
import json
from pathlib import Path
import shutil
ROOT = Path(__file__).resolve().parents[1]


def run(output_dir):
    output = Path(output_dir); output.mkdir(parents=True,exist_ok=True)
    data = ROOT/'data/reproduction/r7'
    for source in data.rglob('*'):
        if source.is_file():
            destination=output/source.relative_to(data);destination.parent.mkdir(parents=True,exist_ok=True);shutil.copyfile(source,destination)
    for source in (ROOT/'src/rq2_original/r7/sources').glob('*.py'):
        shutil.copyfile(source,output/'sources'/source.name)
    path=ROOT/'src/rq2_original/r7/analyze.py'
    spec=importlib.util.spec_from_file_location('r7_frozen_analysis',path)
    module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
    module.BASE=output
    module.main()
    for name in ['METRICS_ALL.json','CHANGE_SUMMARY.json','ALL_METRIC_DELTAS.json']:
        calculated=json.loads((output/name).read_text());expected=json.loads((ROOT/'results/reference'/('r7_'+name)).read_text())
        assert calculated==expected, name
    summary=json.loads((output/'CHANGE_SUMMARY.json').read_text())
    return {'status':'PASS','layer':'L1_SAVED_SERIALIZER_PREDICTIONS','representations':['original_frozen','test_labelled','dev_compact'],'case_count':36,'all_metric_objects_and_changes_exact':True,'encoding_calls':0,'case_changes':{m:summary[m]['case_signatures_changed_36'] for m in ('B2','B3','P1')}}
