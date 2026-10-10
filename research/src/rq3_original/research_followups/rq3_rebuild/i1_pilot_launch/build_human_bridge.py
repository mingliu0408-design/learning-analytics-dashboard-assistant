"""Independent common source dossiers and the inherited blank H0 UI."""
from pathlib import Path
import sys
ROOT=Path(__file__).resolve().parents[3]
sys.path.insert(0,str(ROOT))
from utils.c4_rebuild.i1.common import HOME, load, write_once
from utils.c4_rebuild.i1.worker import OfflineWorker
from utils.c4_rebuild.i1.human import dossier, project


def main():
    manifest=load(HOME/'TASK_MANIFEST.json');worker=OfflineWorker();drafts=[];packets=[];maps=[]
    for entry in manifest['sources']:
        common=worker.call(dict(op='dossier',slot=entry['task_id']))
        drafts.append(dict(task_id=entry['task_id'],common_source_dossier=common))
        packet,mapping=project(dossier(entry['source'],common),manifest['modes'])
        packets.append(packet);maps+=mapping
    write_once(HOME/'COMMON_SOURCE_DOSSIERS_PROPOSED.json',dict(status='SOURCE_REVIEW_PENDING',tasks=drafts))
    write_once(HOME/'human_preparation/NO_RESPONSE_PROJECTIONS.json',dict(packets=packets,real_responses=0,ratings=[]))
    write_once(HOME/'restricted_preparation/EMPTY_RESPONSE_MODE_MAPPING.json',maps)
    sys.path.insert(0,str(ROOT/'research_followups/rq3_rebuild/h0_human_evaluation/tools'))
    from build_blank_packet import build
    receipt=build(HOME/'human_preparation/h0_blank_ui')
    write_once(HOME/'receipts/H0_BLANK_UI_BUILD.json',receipt)
    print(receipt)


if __name__=='__main__':main()
