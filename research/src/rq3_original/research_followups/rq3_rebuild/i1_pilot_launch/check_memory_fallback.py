"""Tiny exposed lexical/native exercise, separate from any benchmark."""
from pathlib import Path
from tempfile import TemporaryDirectory
import sys
ROOT=Path(__file__).resolve().parents[3]
sys.path.insert(0,str(ROOT))
from utils.c4_rebuild.i1.common import HOME,write_once,sha
from utils.c4_rebuild.i1.memory import I1NativeM1,I1ResearchService
from utils.c4_rebuild.contracts import Mode
from research_followups.rq3_rebuild.i0_human_integration.fixtures import memory_source,request,snapshot,SyntheticRouter


def main():
    records=[]
    for query in ('What did I previously say about the quadratic formula?',
                  'What preferences or constraints did I mention about study time?',
                  'zzzxqv telescope galaxies'):
        with TemporaryDirectory(prefix='i1-fallback-check-') as td:
            native,_=memory_source(0,td)
            memory=I1NativeM1(native.databases,native.graph,native.source_events)
            output=I1ResearchService(enabled=True,snapshot=snapshot(),router=SyntheticRouter(False,True,False),memory=memory).prepare(
                request(Mode.S3_EVIDENCE_MEMORY,query=query))
            t=output['trace']
            records.append(dict(query=query,route_origin='P3_BIT_MOCK_ONLY',purpose=t['purpose_resolution'],
                native_memory_calls=memory.calls,trace=t['memory_diagnostics'],
                selected_facts=output['final_request']['runtime_input']['memory']['facts'],
                envelope_sha256=sha(output['final_request']['runtime_input']['memory'])))
    assert all(r['native_memory_calls']==1 for r in records)
    assert records[0]['selected_facts'] and not records[-1]['selected_facts']
    write_once(HOME/'receipts/GENERIC_MEMORY_NATIVE_CHECK.json',dict(status='PASS',records=records,
        exercised='ACTUAL_SYNTHETIC_SQLITE_LEXICAL_STATES',provider_calls=0,model_forward_calls=0,
        limitations='Only exposed source records; no full benchmark or native hybrid forward evaluation.'))
    print([(len(r['selected_facts']),r['trace']['record_state']) for r in records])


if __name__=='__main__':main()
