"""Human-readable delivery and blank review forms; not human decisions."""
from v2_common import *
from copy import deepcopy
import shutil
from adapter import snapshot_for,DOMAINS

def run():
    tasks=lines(HERE/'runtime_tasks.jsonl');b=read(HERE/'BINDINGS.json');counts=read(HERE/'audit/COUNTS.json')
    original=lines(HERE/'original25_binding_status.jsonl');refs=lines(HERE/'evaluation_reference.jsonl')
    for i,r in enumerate(refs[:25]):
        mapping=original[i]
        r['source_availability_truth']='RELATED_INPUT_MISSING' if mapping['missing'] else 'SOURCED_CONTROLLED_REPLAY_WITH_LIMITS'
        r['source_material_file_status']='ORDINARY_REPLAY_PAGE_SOURCE_AND_SHARED_COURSE_PRESENT'
        r['answerability_design']='UNRESOLVED_REQUIRED_INPUT' if mapping['missing'] else 'CONTROLLED_RECONTEXTUALISATION_NOT_ORIGINAL_STUDENT_REPLICATION'
        r['source_mapping']=deepcopy(mapping)
        r['unknowns']=list(mapping['missing'])+mapping['nonblocking_limits']
    jsonl(HERE/'evaluation_reference.jsonl',refs)
    human=HERE/'human_review';human.mkdir(exist_ok=True)
    for name in ('rubric.json','task_review_blank.json'):
        shutil.copyfile(V1/'human_review'/name,human/name)
    shutil.copyfile(V1/'task_spec/SUPERVISOR_RUBRIC_REFERENCE.md',human/'SUPERVISOR_RUBRIC_REFERENCE.md')
    (human/'README.md').write_text('''# Blank task review

Use `TASK_REVIEW_PACK.md` with `task_review_blank.json`. All source sufficiency,
question naturalness, final inclusion, applicability, reviewer identity, rationale
and signatures remain null. This is task review, not answer scoring. The eight
rubric definitions are unchanged. One task has the same applicability across S0–S5;
conditions within a family may differ based on the task, never on observed outputs.
No answer responses or human ratings were created. Confirm the English draft and
source/external-use scope before the single subsequent execution approval.
''')
    design={r['task_id']:r for r in read(HERE/'family_design.json')['tasks']}
    lang={r['task_id']:r for r in read(HERE/'LANGUAGE_ALIGNMENT.json')['pairs']}
    sections=['# Task and source review pack','\nEnglish V2 is tool-assisted and unreviewed. Chinese V1 is a reading/source copy, not another task. No target routes, retrieval results or model answers were used to choose translations.\n',
        '## Original 25: preserved questions and controlled source mappings\n',
        '| Task | Verbatim question | Preparation status | Specific missing source |','|---|---|---|---|']
    for r in original:sections.append('| '+r['task_id']+' | '+r['original_query_verbatim'].replace('|','\\|')+' | '+r['status']+' | '+('; '.join(r['missing']) or 'None for bounded controlled replay')+' |')
    sections += ['\nOriginal questions and all 50 archival messages retain their exact bytes. The recovered ordinary page source is shared controlled input; it does not recover any original student identity or prove that the 25 questions came from one person. Old assistant messages stay in `legacy_only` and never seed Memory or supply missing numbered antecedents.\n',
        'Ordinary replay data: `source_materials/original25/PAGE_SOURCES.json`; prior raw aggregation provenance: `RAW_AGGREGATION_RECEIPT.json`. Shared course corpus: `source_materials/course/corpus.jsonl`. Detailed limits are in `original25_binding_status.jsonl`.\n']
    for t in tasks[25:]:
        tid=t['task_id'];d=design[tid];ref=next(r for r in refs if r['task_id']==tid);tb=b['tasks'][tid]
        sections += [f"## {d['family_id']} / {d['condition']} — {tid}\n",'English: '+t['query']+'\n','中文V1: '+lang[tid]['chinese_query']+'\n',
            f"Page: {t['page']}; query time: {t['query_time']}. Student/course/window: `{canonical(t['scope'])}`.\n",
            'Changed factor (design only): '+d['changed_factor']+'\n',
            '### Ordinary source material\n',f"Page source: `{tb['page_state_path']}`. Scoped view (all domains for human review; runtime S0 sees only its current page):\n",
            '```json\n'+json.dumps(snapshot_for(t,b).overview(),ensure_ascii=False,indent=2)+'\n```\n']
        if tb.get('history_path'):
            sections.append(f"Persistent source history: `{tb['history_path']}`. It is not visible conversation history.\n")
            for s in read(HERE/tb['history_path'])['sessions']:
                for m in s['messages']:sections.append(f"- {s['session_id']} / {m['message_id']} / {m['role'].upper()} / {m['timestamp']}: {m['content']}")
            sections.append('\nNative readback: `native_initial/'+tid+'/state_readable.json`; writer/source spans: `setup_receipt.json`.\n')
        sections += ['### Independent draft reference — not supplied to the model\n',ref['source_availability_truth']+'; actual retrieval: NOT_EXECUTED.\n']
        for label,facts in [('Required for the minimal task',ref['required_facts']),('Optional support',ref.get('optional_support',[]))]:
            if facts:sections.append(label+':\n')
            for f in facts:
                sections.append('- '+f['fact'])
                for e in f['evidence']:
                    locator=e.get('json_pointer',e.get('chunk_id',''))
                    quote=e.get('quote')
                    sections.append('  - `'+e['path']+'` `'+locator+'`'+(f" chars [{e['char_start']},{e['char_end']}): {quote}" if quote is not None else ' (structured value in source)'))
        sections += ['\nAcceptable alternatives: '+'; '.join(ref['acceptable_alternatives'])+'\n',
                     'Unknowns: '+'; '.join(ref['unknowns'])+'\n',
                     'Human review: all fields in `human_review/task_review_blank.json` remain blank.\n']
    (HERE/'TASK_REVIEW_PACK.md').write_text('\n'.join(line.rstrip() for line in '\n'.join(sections).splitlines())+'\n')
    (HERE/'FIX_STATUS.md').write_text('''# Implementation and remaining limits

| Item | Implemented / offline evidence | Still unconfirmed |
|---|---|---|
| English alignment | Same 24 IDs, 12 paired families; 8 histories and page natural language aligned; original 25/50 and course bytes preserved | Human naturalness/source review; no independent authorship or TEST claim |
| M01 time boundary | 18-minute statement is a dated PROGRESS_UPDATE, not a current CONSTRAINT; conditional reference | Whether the limit applies to the next activity |
| P01/P02 reference | Minimal structured task facts separated from optional course support; partial progress allowed | Final human applicability, unchanged eight criteria |
| Evidence | Actual C4 compiler consumes scoped events and record snapshots; current page and noncurrent projection traced | Target P3/RAG and response utility not observed |
| Memory | Real writer ADD/UPDATE; old 12 superseded by version 2 with 24; 20 native rows, 6 assistant rejections; 49 initial states, 294 independent clones | Target native recall and hybrid backend at execution; no ranking or quality claim |
| Planning | Existing typed planner, page budget projection, raw grouped steps/progress in source facts; application retains accepted_plan; FINAL wire has two fields | Raw source action semantics/completion and response-to-plan fidelity require future checks; no plan was generated |
| Original 25 | 17 source-qualified controlled replays; 8 cases with specific missing inputs; all 25 have input previews | Original identities/full conversations remain unrecovered; 25 independent learners not asserted |
| Execution | Explicit 41-task manifest, immutable source binding, common inherited model and instruction, durable runner and existing approval vocabulary | Human task/source confirmation plus one external-scope/model/budget approval; prices and total money ceiling blank |

The 16 source/native contract tests were followed by an independent planner fixture test.
See the final `audit/V2_TESTS.json` for the exact final count and outcome. Mechanical
preparation does not establish answer quality, educational benefit or source truth.
''')
    (HERE/'NATIVE_MAPPING.md').write_text('''# Native mapping and input boundary

The writer input comes solely from the eight English source histories and 26
PUT_VERSION operations. `record_type` and structured `value` determine the native
type, with literal role and time checks. GOAL: goal/object/choice; PREFERENCE:
format/avoid/priority/request; CONSTRAINT: next-activity minutes; PROGRESS_UPDATE:
historical “this time” minutes or other stated source state. Unknown structures
fail explicitly. No task ID, family, required_facts or reference lookup maps facts.

Native content is an exact English source span. For a replacement, the single
clause containing the new structured minute value is indexed; the full correction
and old value remain in history. Native UPDATE retains CONSTRAINT type, creates
version 2, and supersedes the old row in the same conflict group. All versions,
USER/ASSISTANT roles and source spans remain in setup receipts. Null valid_until
is source uncertainty, not confirmation for an arbitrary later activity. M01's
dated PROGRESS_UPDATE cannot enter constraint normalization as a hard budget.

ASSISTANT_SUGGESTION goes through the real writer with ASSISTANT_ADVICE and is
rejected as a learner fact. Its original source and rejected operation are kept,
with no native suggestion index in this implementation. No source gives accepted
ACTIVE_PLAN status; grouped page steps stay within a single plan source object.

Each condition has its own initial SQLite file and six separately reopened clones.
The same learner namespace in a pair never shares writable state. Model-time
Memory, when allowed by mode, actual P3 and permission, uses another fresh read-only
clone and native retrieval, never the entire history. Six-mode current visible
conversation history stays identical. P3 caches use only the actual four visible
fields; module keys also bind source and native logical state. Hidden history does
not become P3 input. No target query was used for rank/translation/task selection.

Current-page Evidence contains scoped counts with coverage and structured records;
S1 adds existing deterministic selected noncurrent domains. Overview projects the
four domains once. Event windows are start-inclusive/end-exclusive. Snapshot rows
use the latest known update at/before the query time, not event-count semantics.
Unknown coverage gives unknown count, not zero. Scope/coverage are ordinary facts;
family/condition/expected facts/availability labels are rejected from model input.
The unchanged final renderer preserves source IDs, origin and observed times.
''')
    (HERE/'COMMANDS.md').write_text('''# Batch commands

Run from this repository root (or the repository-shaped review ZIP root), with an
existing compatible Python runtime. No package install or key read is required for
the following commands:

```sh
python3 -B experiments/rq3_original25_plus_v2/run_batch.py --manifest experiments/rq3_original25_plus_v2/RUN_MANIFEST.json --preflight
python3 -B experiments/rq3_original25_plus_v2/run_batch.py --manifest experiments/rq3_original25_plus_v2/RUN_MANIFEST.json --prepare --output /private/tmp/rq3-en-v2-fresh-prepare
python3 -B experiments/rq3_original25_plus_v2/test_alignment.py
```

The prepare output directory must be new. `--prepare` compiles 294 diagnostic
inputs for all 49 roster entries, marks the eight pending-source entries, and
never calls P3, RAG, target Memory, candidate or FINAL. The 41 admitted tasks are
the separately enumerated `RUN_MANIFEST.json.task_ids`; they are not inferred from
an old script's roster. Both conditions of any selected new family must stay together.

The single future approval uses the existing consolidated replay vocabulary in
`EXECUTION_APPROVAL_TEMPLATE.json`. Copy the current preflight binding into the
approval after human task/source review; set the approved source/external-use scope,
41-or-subset roster, unchanged role model, price assumptions, money ceiling and a
new output directory. Do not treat the template or this command as authorization:

```sh
python3 -B experiments/rq3_original25_plus_v2/run_batch.py --manifest experiments/rq3_original25_plus_v2/RUN_MANIFEST.json --execute --approval /absolute/path/approved.json --output /absolute/path/new-run
```

`--resume` is available only for an exactly matching durable run. No old 62-task
script is called. P3 is the frozen three-role configuration (32/32/64 output caps);
CANDIDATE and FINAL retain gpt-4o-mini-2024-07-18, temperature 0, max output 2048.
For all 41 admitted tasks, upper bounds are 123 route slots, 82 optional candidate
slots and 246 FINAL slots; at most 902 physical attempts with the inherited bounded
retry policy. Actual calls depend on gates. Monetary approval and live model
availability remain pending. Hybrid Memory uses the existing host backend without
installing/downloading models or silently switching to lexical retrieval.
''')
    template=dict(status='PENDING',scope='ORIGINAL25_PLUS_EN_V2_FRESH_SIX_MODES_HUMAN_ONLY',
        user_decision=None,external_source_scope_confirmed=False,binding=None,task_ids=read(HERE/'RUN_MANIFEST.json')['task_ids'],
        selection_basis='PREDECLARED_BEFORE_NEW_OUTPUTS',output_directory=None,
        proposed_money_ceiling_usd=None,uncached_usd_per_million=None)
    write(HERE/'EXECUTION_APPROVAL_TEMPLATE.json',template)
    (HERE/'START_HERE.md').write_text('''# 原25＋新24：英文对齐与离线接线审阅

名册49题：原25题逐字保留，新24条件属于原有12个family。
**实际可准备41题：原25中的17题受控回放＋新24题。**
另8题已生成带缺件说明的输入预览，未列入待执行名单；它们不是自然负例。
没有生成任何答案或人工分数。294份输入预览不等于294个模型结果。

先看 `TASK_REVIEW_PACK.md` 和 `original25_binding_status.jsonl`，再看
`human_review/task_review_blank.json`。英文为作者批准的主运行语言；译稿仍待
人工自然性和来源审阅，中文V1保留在相邻 `rq3_original25_plus` 目录，不作为新增题。
原50条消息在 `legacy_only` 原样保存，旧assistant文本不进入新运行来源。

八项具体缺件：original-02 指标定义；04 十天安排起点、可用时间与待办/截止；
05 原“this”所指计划/建议；07 原“this”所指建议；09 反馈/反思正文；
14 W4提交和截止凭据；18 反思正文；22 编号2/3的原前文。
不要求无关生产身份或学校元数据，不据此阻塞已准备题。

实际模块结果：26条PUT_VERSION经native writer处理，20条写入、6条未采纳
assistant建议明确未索引；49份初态和294份模式副本均已关闭重开并核验。
M01的18分钟保留历史范围；P01/P02的RAG课程指导改为可选设计支持。
所有最终人工适用性、纳入、理由、身份和签名仍为空。

`adapter.py` 接现有C4 Evidence compiler、native M1和typed planner；
`prepared_inputs` 包含当前页/非当前页到最终请求字段的踪迹和空路由状态。
`RUN_MANIFEST.json` 明确列出41题；`COMMANDS.md` 给出实际批量入口。
新R03-B、M03-B、E03-B按原设计保留，不视为准备缺件或据输出删题。

剩余：人类确认题目自然性、来源充分性、最终纳入与同题固定适用性；
对选定任务和来源外发范围、沿用模型及一次预算作集中批准后才能生成。
本轮Provider/P3模型/候选/FINAL/Judge调用均为0；未读API密钥、未运行旧62批次。
检查通过只证明机械接线和隔离，不代表回答质量提高。

版本、测试、来源和ZIP核验见 `audit` 以及包根的 `GIT_LINEAGE.json`、`MANIFEST.json`。
''')
    print(canonical(dict(review_tasks=49,blank_items=len(read(human/'task_review_blank.json')['items']),review_pack_bytes=(HERE/'TASK_REVIEW_PACK.md').stat().st_size)))

if __name__=='__main__':offline();run()
