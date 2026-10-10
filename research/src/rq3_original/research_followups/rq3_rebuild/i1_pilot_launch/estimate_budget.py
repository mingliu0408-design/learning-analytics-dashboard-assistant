"""Tokenizer-only prospective estimate. No model construction or inference."""
from pathlib import Path
import json
import sys
ROOT=Path(__file__).resolve().parents[3]
sys.path.insert(0,str(ROOT))
from utils.c4_rebuild.i1.common import HOME, load, sha, canonical, write_once
from utils.c4_memory.c4_memory_retriever import MPNET_REVISION, MPNET_REQUIRED_HASHES
from tokenizers import Tokenizer


def main(output):
    p=Path('/Users/liuming/Downloads/duteaiapp_cfull_semantic_integrated_v1_副本3/semantic_runtime/models/all-mpnet-base-v2')/MPNET_REVISION/'tokenizer.json'
    assert sha(p.read_bytes())==MPNET_REQUIRED_HASHES['tokenizer.json']
    tokenizer=Tokenizer.from_file(str(p));tokenizer.no_truncation();tokenizer.no_padding()
    routes=load(HOME/'ROUTE_REQUEST_REGISTRY.json')['requests']
    requests=load(HOME/'receipts/mock_final_02/MOCK_REQUEST_REGISTRY.json')['requests']
    rows=[]
    for origin,items in [('UNSENT_FROZEN_P3',routes),('MOCK_DERIVED_CONDITIONAL_RENDERING',requests)]:
        for record in items:
            payload=record['payload'];text=canonical(payload).decode()
            rows.append(dict(origin=origin,request_sha256=sha(payload),utf8_bytes=len(text.encode()),
                approximate_mpnet_subword_units=len(tokenizer.encode(text).ids),output_cap=payload['max_tokens']))
    config=load(HOME/'PILOT_CONFIGURATION_PROPOSED.json')
    count=264;inputs=count*config['max_request_input_byte_units']
    outputs=2*(12*(32+32+64)+(24+72)*2048)
    rates=config['uncached_usd_per_million']
    cost=(inputs*rates['input']+outputs*rates['output'])/1e6
    report=dict(status='PROSPECTIVE_NOT_APPROVED',provider_calls=0,tokenizer_path=str(p),tokenizer_sha256=sha(p.read_bytes()),
        tokenizer_kind='MPNET_TOKENIZER_ONLY_NOT_OPENAI_TOKEN_COUNTS',interpreter=sys.executable,
        provider_tokenizer_available=False,provider_tokenizer_note='tiktoken absent in inspected existing interpreters; no installation/download.',
        measured_records=rows,maximum_observed_utf8_bytes=max(x['utf8_bytes'] for x in rows),
        measured_uncached_cost_not_asserted=True,
        dynamic_headroom='Every actual serialized request, including accepted plan/correction, must fit 36,000 UTF-8 bytes plus 256 overhead units. No silent truncation.',
        conservative_initial_calls=dict(P3=36,CANDIDATE=24,FINAL=72,total=132),
        physical_attempt_upper_bound=count,maximum_output_tokens=outputs,
        conservative_input_byte_units=inputs,conservative_prospective_usd=cost,
        price_reference=config['price_reference'],pricing_checked_date=config['price_checked_date'],
        proposed_money_ceiling_usd=2.0,
        calculation_limit='UTF-8 byte units plus 256 overhead are a conservative budgeting convention for serialized text, not exact provider prompt accounting or a billing guarantee. SDK/internal provider accounting and future pricing need recheck at approved execution.',
        unknown_usage_policy='Reserve the full pre-call upper estimate for every attempt, including unknown completion; never record unknown billing as zero.')
    assert cost<=2
    write_once(Path(output),report)
    print(json.dumps({k:report[k] for k in ('maximum_observed_utf8_bytes','physical_attempt_upper_bound','maximum_output_tokens','conservative_input_byte_units','conservative_prospective_usd')},indent=2))


if __name__=='__main__':main(sys.argv[1])
