"""Freeze explicit implementation dependencies; no private source discovery."""
from pathlib import Path
import json
import subprocess
import sys
ROOT=Path(__file__).resolve().parents[3]
sys.path.insert(0,str(ROOT))
from utils.c4_rebuild.i1.common import HOME,sha,load
from utils.c4_rebuild.i1.frozen_p3 import FrozenP3


def selected_paths():
    paths=set()
    # Python dependencies are source only; not native DBs, weights or result dumps.
    for prefix in ('utils/c4_rebuild','utils/c4_dashboard_scoped','utils/c4_memory','utils/c4_rag',
        'research_followups/rq3_rebuild/p0_planner_prototype/p0planner',
        'research_followups/rq3_rebuild/p0_planner_prototype/tools',
        'research_followups/rq3_rebuild/p0_planner_prototype/schemas',
        'research_followups/rq3_rebuild/p1_planner_bridge/p1bridge',
        'research_followups/rq3_rebuild/m0_memory_data/code',
        'research_followups/rq3_rebuild/m1_memory_completeness/code',
        'research_followups/rq3_rebuild/h0_human_evaluation/tools',
        'research_followups/rq3_rebuild/h0_human_evaluation/schemas',
        'research_followups/rq3_rebuild/h0_human_evaluation/ui'):
        paths.update(p for p in (ROOT/prefix).rglob('*') if p.is_file() and p.suffix in ('.py','.json','.html','.js','.css'))
    paths.update((ROOT/'utils').glob('c4_real*.py'))
    paths.add(ROOT/'utils/course_material_retriever.py')
    paths.add(ROOT/'utils/course_metadata.py')
    paths.add(ROOT/'utils/recommendation_planner.py')
    paths.add(ROOT/'evaluation/capability_routing_rq2_v2_stage4/track_g_b0_b1/clarification_gate.py')
    paths.add(ROOT/'evaluation/capability_routing_rq2_v2_stage4/track_g_b0_b1/clarification_candidate_configs_v1.json')
    paths.add(ROOT/'evaluation/capability_routing_rq2_v2_stage4/track_g_b0_b1/clarification_gate_frozen_v1.json')
    paths.add(ROOT/'evaluation/capability_routing_rq2_v2_stage4/track_m_specialist_composition/p3_rag_memory_specialists_frozen_v1.json')
    paths.update(HOME.glob('*.py'))
    paths.update((HOME/'tests').glob('*.py'))
    p0=ROOT/'research_followups/rq3_rebuild/p0_planner_prototype'
    paths.update(p0/r['path'] for r in load(ROOT/'research_followups/rq3_rebuild/p1_planner_bridge/P0_DEPENDENCY_LOCK.json')['files'])
    for p in ('PILOT_CONFIGURATION_PROPOSED.json','TASK_MANIFEST.json','FROZEN_ROLE_REGISTRY.json','EXTERNAL_RUNTIME_RECEIPT.json'):
        paths.add(HOME/p)
    paths.update((HOME/'schemas').glob('*.json'))
    for p in ('research_followups/rq3_rebuild/i0_human_integration/fixtures.py',
        'research_followups/rq3_rebuild/i0_human_integration/PILOT_TASKS.json',
        'research_followups/rq3_rebuild/i0_human_integration/schemas/STRUCTURED_PLAN_SCHEMA.json',
        'research_followups/rq3_rebuild/e1_five_page/SYNTHETIC_FIXTURE.json',
        'research_followups/rq3_rebuild/m1_memory_completeness/fixtures/linked_runtime_v1.json',
        'research_followups/rq3_rebuild/p1_planner_bridge/P0_DEPENDENCY_LOCK.json',
        'research_followups/rq3_rebuild/h0_human_evaluation/rubric.json',
        'research_followups/rq3_rebuild/h0_human_evaluation/templates/task_template.json',
        'research_followups/rq3_rebuild/h0_human_evaluation/templates/blank_ratings.json',
        'research_followups/rq3_rebuild/r2_candidate_reference/I0_RETRIEVER_INTERFACE_RECOMMENDATION.md',
        'evaluation/rq3_real_c4/i0_integration/build_r1_route_packages.py',
        'evaluation/rq3_real_c4/i0_integration/route_package_validator_v1.py',
        'evaluation/rq3_real_c4/i0_integration/route_execution_runner.py'):
        paths.add(ROOT/p)
    paths.update(ROOT/r['path'] for r in FrozenP3().sources)
    return sorted(paths)


def main():
    files=[dict(path=str(p.relative_to(ROOT)),bytes=p.stat().st_size,sha256=sha(p.read_bytes())) for p in selected_paths()]
    document=dict(schema_version='I1_SOURCE_MANIFEST_V1',starting_head='517c2097ceb454a0273b41ad790e5c498fd39985',
        integration_head='44bc6745a8a37176ad39d3890c5390f5d64221ac',files=files,
        excluded='No private learner files, ratings, API keys, native DBs, weights or historical final responses.',
        external_resource_policy='Separately identified in EXTERNAL_RUNTIME_RECEIPT.json; reverified before approved SDK construction.')
    # This preparation manifest is not a frozen historical source. Update only before task commit.
    (HOME/'SOURCE_MANIFEST.json').write_text(json.dumps(document,indent=2,ensure_ascii=False)+'\n')
    print('source files',len(files))


if __name__=='__main__':main()
