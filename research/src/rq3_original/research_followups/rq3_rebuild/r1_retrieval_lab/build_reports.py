"""Report from saved results only: no ranking or model inference."""
from pathlib import Path
from collections import Counter
import csv
import json
import re
import statistics
import sys
sys.path.insert(0,str(Path(__file__).resolve().parents[3]))
from utils.c4_rag_lab.common import *
from utils.c4_rag_lab.evaluation import reference_id_metrics

def main():
    summary=json.loads((OUT/'FIXED_CORPUS_DIAGNOSTIC_SUMMARY.json').read_text())
    chunk_audit=json.loads((OUT/'CHUNK_SOURCE_COVERAGE_AUDIT.json').read_text())
    parity=json.loads((OUT/'R0_21_BASELINE_REPRODUCTION.json').read_text())
    assert parity['all_match']
    labels={r['id']:r for r in json.loads((LOCAL/'historical_labels.json').read_text())}
    queries={r['id']:r['query'] for r in json.loads((LOCAL/'historical_requests.json').read_text())}
    chunks={c['chunk_id']:c for c in json.loads((LOCAL/'v0_chunks.json').read_text())}
    docs={i:c['source_file'] for i,c in chunks.items()}
    allrows=[];context_summary={};taxonomy=[]
    for candidate in summary['candidates']:
        rows=json.loads((OUT/f'{candidate}_DIAGNOSTICS.json').read_text());allrows+=rows
        cm=[reference_id_metrics(r['context']['kept_ids'],labels[r['case_id']]['reference_ids'],docs) for r in rows]
        context_summary[candidate]={'macro_context_reference_id_recall':statistics.mean(r['recall_at_5'] for r in cm if r['reference_count']),
            'context_budget_dropped_chunks':sum(len(r['context']['dropped']) for r in rows),
            'max_context_tokens':max(r['context']['tokens'] for r in rows),'required_fact_coverage':None,
            'assembled_duplicate_rate':0}
        for r in rows:
            ids=r['ranked_ids'][:5];sid=r['case_id'];gold=set(labels[sid]['reference_ids'])
            weeks=set(re.findall(r'\bweek\s*(\d{1,2})\b',queries[sid],re.I))
            wrong=[i for i in ids if len(weeks)==1 and chunks[i]['week'] and chunks[i]['week']!='W'+next(iter(weeks))]
            metadata=[i for i in ids if chunks[i]['source_type'] in ('reading','literature','course_metadata','moodle_link')]
            flags=[]
            if gold-set(ids):flags.append('HISTORICAL_REFERENCE_ID_MISS')
            if not gold:flags.append('EMPTY_HISTORICAL_REFERENCE_REQUIRES_REVIEW')
            if wrong:flags.append('EXPLICIT_WEEK_METADATA_MISMATCH')
            if metadata:flags.append('METADATA_OR_SUMMARY_RESULT_REQUIRES_CLAIM_TYPE_REVIEW')
            if r['context']['dropped']:flags.append('CONTEXT_BUDGET_DROP')
            taxonomy.append({'case_id':sid,'candidate':candidate,'flags':'|'.join(flags) or 'NO_DETECTED_STRUCTURAL_FLAG',
                'reference_ids_missing_at5':len(gold-set(ids)),'explicit_week_mismatch_count':len(wrong),
                'metadata_or_summary_top5_count':len(metadata),'context_dropped_count':len(r['context']['dropped']),
                'required_fact_support':'NOT_ESTABLISHED','causal_diagnosis':'NOT_INFERRED_FROM_ID_METRICS'})
    with (OUT/'EXPOSED_CASE_ERROR_TAXONOMY.csv').open('w',newline='') as f:
        w=csv.DictWriter(f,lineterminator='\n',fieldnames=list(taxonomy[0]));w.writeheader();w.writerows(taxonomy)
    paired=[]
    for c in ('B_BM25','C_HYBRID','D_CROSS_ENCODER'):
        for sid in labels:
            a=next(r for r in allrows if r['case_id']==sid and r['candidate']=='A_R0')
            b=next(r for r in allrows if r['case_id']==sid and r['candidate']==c)
            delta=None if not a['reference_count'] else b['recall_at_5']-a['recall_at_5']
            paired.append({'case_id':sid,'candidate':c,'delta_reference_id_recall5_vs_A':delta,
                'change':'UNLABELLED_NEGATIVE' if delta is None else 'GAIN' if delta>0 else 'REGRESSION' if delta<0 else 'TIE'})
    write_json(OUT/'PAIRWISE_REFERENCE_ID_CHANGES.json',paired)
    token_summary={}
    for name,file in [('mpnet','MPNET_TOKEN_AUDIT.json'),('cross_encoder','CROSS_ENCODER_TOKEN_AUDIT.json')]:
        rows=json.loads((OUT/file).read_text())
        token_summary[name]={'sequences':len(rows),'truncated_sequences':sum(r['truncated_tokens']>0 for r in rows),
            'truncated_tokens':sum(r['truncated_tokens'] for r in rows),'max_original_tokens':max(r['untruncated_tokens'] for r in rows),
            'max_model_tokens':max(r['model_tokens'] for r in rows)}
        if name=='mpnet':
            token_summary[name]['standalone_query_max_tokens_with_specials']=max(r['untruncated_tokens'] for r in rows if r['id'] in labels)
            token_summary[name]['query_tokens_field_note']='0 in original audit denotes absence of paired query; standalone query lengths are untruncated_tokens on U rows'
    write_json(OUT/'TOKEN_AND_CONTEXT_SUMMARY.json',{'tokens':token_summary,'contexts':context_summary,
        'context_tokenizer':'MPNet actual tokenizer, conservative sum of separately serialized chunk lengths including per-chunk special tokens',
        'support':'historical reference IDs only; required fact and independently reviewed span support unavailable'})
    future=[]
    for repo,rev,license,name,size in [
        ('BAAI/bge-m3','5617a9f61b028005a4858fdac845db406aefb181','mit','pytorch_model.bin',2271145830),
        ('BAAI/bge-reranker-v2-m3','953dc6f6f85a1b2dbfca4c34a2796e7dde08d41e','apache-2.0','model.safetensors',2271071852),
        ('Qwen/Qwen3-Embedding-0.6B','97b0c614be4d77ee51c0cef4e5f07c00f9eb65b3','apache-2.0','model.safetensors',1191586416),
        ('Qwen/Qwen3-Reranker-0.6B','e61197ed45024b0ed8a2d74b80b4d909f1255473','apache-2.0','model.safetensors',1191588280)]:
        future.append({'repo':repo,'revision':rev,'license':license,'weight_file':name,'weight_bytes':size,
            'source':'https://huggingface.co/api/models/'+repo+'?blobs=true','checked_date':'2026-09-06',
            'status':'NOT_DOWNLOADED_NOT_RUN','checkpoint_or_inference_bytes_sent':0})
    write_json(OUT/'FUTURE_MODEL_METADATA.json',future)
    legacy_indexes={}
    for rel in ('evaluation/outputs/retrieval_v2/index/index_metadata_v2.json',
                'evaluation/outputs/retrieval_v2/index_v2_4/index_metadata_v2_4.json'):
        d=json.loads((ROOT/rel).read_text())
        legacy_indexes[rel]={'sha256':file_hash(ROOT/rel),**{k:d.get(k) for k in ('chunk_count','document_count','backend_mode','semantic_backend_available')}}
    write_json(OUT/'CANDIDATE_REGISTRY.json',{'actual':{
        'A_R0':{'status':'ACTUALLY_RUN','neural':False,'identity':'original corrected R0 at starting HEAD; ranking unchanged'},
        'B_BM25':{'status':'ACTUALLY_RUN','neural':False,'implementation':'inherited FieldAwareBM25 with common inputs'},
        'C_HYBRID':{'status':'ACTUALLY_RUN','model':'all-mpnet-base-v2','dtype':'float32','dimension':768,'corpus_vectors':624,'queries':15},
        'D_CROSS_ENCODER':{'status':'ACTUALLY_RUN_AFTER_COMPATIBILITY_REPAIR','model':'ms-marco-MiniLM-L6-v2',
            'dtype':'float64','attention':'eager','accepted_real_pairs':450,'failed_float32_pairs':30,'rerank_pool':'same C top30, all 15 case pools checked'}},
        'future_candidates':future,'legacy_index_metadata':legacy_indexes,
        'synthetic_only':'29 unit tests plus model compatibility/smoke probes are separate from real course diagnostics; no FakeEmbeddingProvider used',
        'deployment_selection':'NONE','new_thresholds_calibrated':False})
    table='\n'.join(f"| {c} | {r['recall_at_1']:.4f} | {r['recall_at_3']:.4f} | {r['recall_at_5']:.4f} | {r['mrr_at_5']:.4f} | {r['latency_ms_median']:.1f} |"
        for c,r in summary['candidates'].items())
    chunk_lines='\n'.join(f"- {size} token：{v['totals']['chunks']} chunks，覆盖 {v['totals']['covered_characters']:,} / {v['totals']['canonical_characters']:,} 字符，遗漏 {v['totals']['missing_characters']}，正文/metadata 截断均为 0。" for size,v in chunk_audit['versions'].items())
    changes={c:dict(Counter(p['change'] for p in paired if p['candidate']==c)) for c in ('B_BM25','C_HYBRID','D_CROSS_ENCODER')}
    report=f'''# RQ3-REBUILD-R1 审阅入口

状态：**COMPLETED_BOUNDED_DEVELOPMENT_LAB — NO_FINAL_SYSTEM_SELECTION**。四候选接口、真实本地诊断、独立跨度切块、测试及审阅包已完成。工作目录 `{ROOT}`；分支 `{BRANCH}`。起始 HEAD `{BASE}`；结束 HEAD 和仅一个提交的验证见 ZIP 根目录 `GIT_HANDOFF.json`。

## 实际结果

V0 为精确六源、624 chunks，SHA-256 `{V0}`。全部旧 source hashes 匹配；没有修复、去重或重切 V0。原 R0 21 例的返回 IDs 和状态 **21/21 完全一致**：11 SUPPORTED、3 LIMITED_EVIDENCE、7 NO_RESULT。这些 native 标签不证明回答充分性。

15 例为已暴露的历史开发材料。四份历史输入逐文件 hash 匹配；13 例有旧 reference IDs，2 例为空。26 条保存 reference body 与 V0 对应文本逐条匹配；这仍只支持旧 ID 检索工程比较，不能认证 passage sufficiency 或人工独立审查。历史记录的 approved/revised 字段原样保存，其独立人工审查链未在本次验证。旧 62/21/15 例没有被重新命名为 held-out。

下表是 **阈值前**、13 个非空参照案例的 macro reference-ID recall 和 MRR@5；不是最终回答准确率。

| 候选 | Recall@1 | Recall@3 | Recall@5 | MRR@5 | 查询阶段中位 ms |
|---|---:|---:|---:|---:|---:|
{table}

D 对 C 的 Recall@5 提高，但仍低于 R0；B/C/D 相对 R0 的逐例变化：`{json.dumps(changes,ensure_ascii=False)}`。不据此选择最终系统。A 保留原 page/query/task 奖励，所以 A 与其他候选是流程比较；B/C 是共同输入下增加 dense/RRF，C/D 是同一 C top30 池上的重排比较。C 关闭了历史 R1 特有 history/硬过滤/strong-match 筛选，不能声称历史 R1 原字节重放。

时延含本实验室 CPU 查询/排名工作；D 加入 C 保存的查询耗时和本次 float64 重排耗时。初始化/语料编码的精确一次性耗时未在首轮进程失败前持久化，保留 null，未重跑补数；时延不代表服务 SLA 或 GPU 性能。

## 模型实际执行与失败记录

C 实际运行本地 MPNet，生成 624×768 单位向量和 15 个查询向量。D 下载了唯一获准的 MiniLM cross-encoder 固定版本；首次 float32 尝试出现非有限分数，接受 0 个 D 排名。合成兼容性检查后，冻结 float64/eager 运行配置，仅续跑 D，完成 450 对有限评分；A/B/C 未重跑。模型、运行环境、SHA-256、下载前 RAM/磁盘、预算和失败细节见 `MODEL_RESOURCE_REPORT.md`、`MODEL_RUNTIME_IDENTITY.json`、`D_COMPATIBILITY_RETRY_MANIFEST.json`。

MPNet 共 639 个真实输入，其中 10 个语料输入发生模型截断、共 718 tokens；cross-encoder 的 450 对输入中 2 对发生段落截断、共 405 tokens。原始 V0 文本未被改写。token 审计记录原始长度与实际模型长度；审计时 tokenizer 的超长警告不表示把超长序列直接送入模型。没有将 logits/sigmoid 当作回答支持概率。

B/C/D 没有用无关分数尺度套 R0 阈值，未校准新阈值，其 native 返回为空且状态为 UNVALIDATED_RETRIEVAL_ONLY。2 个空旧参照案例上的非空排名仅作为检查提示；它们不是独立标注的 false-positive 率。4 个 deployment P3=false 控制全部零搜索。没有调用路由模型、最终回答生成器或 Judge。

## 来源与独立切块

六来源：2 个可用正文源，4 个元数据/链接/摘要源。讲座转录、被引用论文全文并未因此获得或授权；没有爬取链接。E0 学习者活动日志/身份表仅作为排除范围说明，未作为共享语料读取。`SOURCE_COVERAGE_AND_TEXT_MAP.csv` 区分可用正文、元数据、缺失目标正文和原始提取未核验。

V1a 两个尺寸复用同一份继承提取文本，548 个 sections、151,879 字符；每个 document 有 source/text hash，chunk 带 Unicode 字符范围、section 祖先、周次、assessment part、URL/page、parent/prev/next。最终实现保持相邻跨度的原始连接，并优先在句界切分长段落：

{chunk_lines}

覆盖是对 canonical extracted text 的机械覆盖；原 HTML/PDF 提取完整性仍为 EXTRACTION_UNVERIFIED。V1a 并未被宣称与 legacy V0 的正文完全相同，也未运行 V0-vs-V1 排名对比。V1b 提取修复未执行；V2 新授权正文仅登记规格。真实表格结构可能已在继承提取中丢失；新接口对显式表头/行的保留由合成测试证明，不能外推为真实 PDF 表格已恢复。

最终测试 **29/29 通过**，涵盖长段尾部、Unicode、原文连接、表头、短原子要求、跨课程/周次/权限边界、winning-span 优先、重复出处、精确候选池、非法输入、P3 零搜索与评价隔离。测试探针是合成的；兼容性模型探针另列。初次测试因包探测防护过强而失败的记录保留。原型切块为 648/585；句界优先改进后为 651/585，共享 canonical hash 未变。

## 评价与后续条件

8 类机器编写开发探针已在新候选排名前冻结，覆盖导航/metadata、正文、多 section、歧义追问、错误周次、仅标题不足、语料不可回答和 Dashboard 数值控制。全部标为 MACHINE_AUTHORED_DEVELOPMENT_PROBES / HUMAN_REVIEW_PENDING；它们未用于调参或本次评分。`SOURCE_SPAN_REFERENCE_TEMPLATE.json` 包含 draft anchors，required facts 与审核人留空。

`TOKEN_AND_CONTEXT_SUMMARY.json` 分开报告实际搜索、旧 ID/文档召回、context retained IDs、重复率、预算丢弃和 token 截断。D 有 3 个候选窗口因共同 1200-token context 预算被整体丢弃；不截断正文。独立 span/fact support、语义充分性、无支持误报率均缺少审阅参照，保持 null。

后续应先独立审核 source-span/required-fact 参照和无答案负例，再分别检验 query resolution、week filters、提取修复与 chunk size，冻结新阈值后设计真正独立评价。BGE-M3、BGE reranker、Qwen3 0.6B embedding/reranker 仅做官方资源比较，均未下载或运行。没有合并、部署、服务默认配置变更或最终 RQ3 胜者选择。

## 审阅与复现入口

- `CODE_AND_SOURCE_AUDIT.md`：继承算法、source namespaces、限制。
- `RUN_CONFIG.json`、`PRE_RANKING_FREEZE.json`：共同配置与输入/探针冻结。
- `*_DIAGNOSTICS.json`：只含 IDs、分数、hash、计数；不含课程正文或回答。
- `R0_21_BASELINE_REPRODUCTION.json`、`EXPOSED_CASE_ERROR_TAXONOMY.csv`：回归与结构风险提示。
- `CHUNK_SOURCE_COVERAGE_AUDIT.json`、`V1A_INDEX_MANIFEST.json`：覆盖和 ignored 索引身份。
- `README.md`：本地测试与 ignored-index 再生成命令。
- ZIP 根目录 `GIT_HANDOFF.json`、`REVIEW_MANIFEST.json`：起止 Git、允许文件及逐成员 SHA-256。权重、课程/学生全文、数据库、密钥、候选回答、评分理由和完整历史日志均排除。
'''
    (OUT/'START_HERE.md').write_text(report)
    (OUT/'STATUS.md').write_text('COMPLETED_BOUNDED_DEVELOPMENT_LAB\nFour candidates actually run; D requires recorded float64/eager compatibility override.\nNo final selection, no deployment, no new held-out evaluation.\nSee START_HERE.md.\n')
    readme=f'''# R1 lab commands

Use the existing runtime; do not install or upgrade dependencies. Run from `{ROOT}`.
The saved comparison is complete: do not rerun the comparison or preparation scripts to fill historical timings.

```sh
PYTHONDONTWRITEBYTECODE=1 TOKENIZERS_PARALLELISM=false HF_HUB_OFFLINE=1 TRANSFORMERS_OFFLINE=1 /opt/anaconda3/envs/bioredirect/bin/python3.11 -B research_followups/rq3_rebuild/r1_retrieval_lab/run_tests.py
```

Index regeneration reads only the six exact authorised sources and the local tokenizer. Supply a NEW directory within this lab's ignored `local_artifacts` directory; it refuses existing destinations. It does not regenerate saved diagnostic tables, human labels, or old service indexes.

```sh
PYTHONDONTWRITEBYTECODE=1 TOKENIZERS_PARALLELISM=false HF_HUB_OFFLINE=1 TRANSFORMERS_OFFLINE=1 /opt/anaconda3/envs/bioredirect/bin/python3.11 -B research_followups/rq3_rebuild/r1_retrieval_lab/regenerate_local_indexes.py --destination '{LOCAL}/review_regeneration'
```

Optional future local dense-index regeneration uses the same command with `--dense`, only when compute is authorised. It reuses existing MPNet and downloads nothing. The cross-encoder scorer is `LocalNeural(CE_ROOT, 'cross_encoder', dtype='float64', attention='eager')`; record this effective override rather than using the initial failed float32 specification.

Executed sequence: `prepare_lab.py`, synthetic tests, `audit_chunking.py`, `run_comparison.py` (A/B/C complete; D float32 failed), synthetic compatibility probes, `finish_saved_comparison.py` (only D continuation plus 21-case A regression), final synthetic tests/chunk audit, `build_reports.py`, `verify_delivery.py`, one Git commit, `build_review_zip.py`.

Preparation/comparison scripts use exclusive freeze/attempt markers. The input freeze was not changed after rankings. `COMPARISON_EXECUTION.json` contains the initial executed code hashes; compatibility and final output code versions are separately recorded. One preparation syntax error occurred before execution and was corrected. Test attempt 01 contains the harmless Transformers package-discovery guard conflict; attempt 02 passed 27 tests; final attempt 03 passed 29 tests after exact adjacency and sentence-boundary refinements.

Both report and ZIP omit full course/learner text and weights. Source locators, source hashes, tokenizer/model identities, and code are sufficient to check permitted local regeneration, but the review ZIP alone is not a full-data distribution. Source offsets are canonical Unicode characters, not raw HTML/PDF positions. V1a's original extractor is unchanged and its raw completeness remains unverified.
'''
    (OUT/'README.md').write_text(readme)
    print('Reports generated from saved results; no inference or ranking repeated.')

if __name__=='__main__':main()
