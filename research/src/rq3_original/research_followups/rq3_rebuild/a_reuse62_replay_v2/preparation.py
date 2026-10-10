"""Task/source readiness is independent of P3 output and retrieval success."""
from replay_common import *
from controlled_runtime import source_for, select_domains, DOMAINS
import csv
from collections import Counter

# Review metadata only, derived from the literal questions and recovered source
# contracts. It is never consumed by the generator, router, scorer or Memory.
CRITICAL = {
 'U002':['ASSESSMENT_VIEWS_EVENT_DEFINITION_NOT_RECOVERED'],
 'U004':['TEN_DAY_START_AND_AVAILABILITY_UNKNOWN','REQUIRED_TASKS_AND_DEADLINES_NOT_BOUND'],
 'U009':['FEEDBACK_OR_REFLECTION_TEXT_NOT_RECOVERED'],
 'U014':['W4_SUBMISSION_RECEIPT_AND_DEADLINE_NOT_RECOVERED'],
 'U018':['REFLECTION_TEXT_FOR_STRENGTH_WEAKNESS_JUDGMENT_NOT_RECOVERED'],
 'U022':['NUMBERED_PLAN_2_AND_3_ANTECEDENT_NOT_RECOVERED'],
 'U039':['CURRENT_WEEK_TASK_NOT_IDENTIFIED'],
 'U059':['CURRENT_WEEK_TASK_NOT_IDENTIFIED'],
}
CONTROLS={'U031':'ORIGINAL_MISSING_NUMBERED_PLAN','U036':'ORIGINAL_IRRELEVANT_MEMORY','U046':'ORIGINAL_COURSE_ABSENCE_PROBE'}
REQUIREMENTS=[
 '总体活动模式','assessment views 的采集定义','邮件订阅阅读是否记入平台浏览','十天补进度安排与待完成任务',
 '结合当前总体数据细化建议；this 指代未恢复','资源时间管理建议','按资源数据识别活动缺口','录播与直播数据来源区分',
 '反馈含义与好坏，需要反馈/反思内容','资源浏览指标解释','资源浏览采集口径','反思字符活动量解释','反思改进建议',
 '核实 W4 按时提交与页面差异','讨论活动改进','按资源活动给建议','讨论表现建议','反思强弱项评判',
 '讨论数据采集口径','邮件阅读是否在当前数据采集范围','总体参与改进建议','原编号 2、3 的具体前文',
 '反思结构指导','W4 录播主题及课程内容边界','完整录播访问范围',
 '受控旧计划第 2、3 项','受控旧计划第二项','同会话最后一项','受控旧计划第一项','讨论建议且保留同会话历史',
 '原无编号计划对照','同会话讨论步骤','受控目标/限制/系统建议与当前完成自述','受控 W4 建议与当前 W5 更正',
 'Lecture 页面旧建议与反思目标','当前资源指标；旧讨论 Memory 无关','旧建议延续；today 限制不能当当前可用时间',
 '本周反思结构；只支持通用结构，当前课程周未知','当前周讨论任务','W4 录播主题','W5 讲座主题','W4 阅读导航',
 'W5 在线会议链接导航','Part A 任务要求','资源浏览数据','课程无关问题对照','个人反思分析文献导航',
 'Debate_replies 定义','Video View % 定义','Total_chars 定义','Resources_views 定义','回复网络定义',
 '讨论与反思活动联系','资源与视频活动联系','视频与讨论准备联系','反思与资源活动联系','四域总体模式',
 '同会话第二项和 W4 指导','讨论数据和当前周任务','同会话第二步与 Part A 指导','资源最活跃日（现有来源支持星期几）','同会话当前步骤解释']
assert len(REQUIREMENTS)==62

def assess(tasks,binding,*,with_diagnostics=True):
    memory=read(HERE/'MEMORY_RESULTS.json') if with_diagnostics and (HERE/'MEMORY_RESULTS.json').exists() else {'tasks':{}}
    roster={r['task_id']:r for r in read(HERE/'audit/ROSTER_IDENTITY.json')}
    results=[]
    for t,req in zip(tasks,REQUIREMENTS):
        tid=t['task_id'];gaps=list(CRITICAL.get(tid,[]));error=None
        try:source=source_for(t,binding)
        except Exception as exc:source=None;error=type(exc).__name__+':'+str(exc)
        selected,reason=select_domains(t['query'],t['page'])
        visible=list(DOMAINS) if t['page']=='Overview' else [t['page']]
        added=[d for d in selected if d not in visible]
        mt=memory['tasks'].get(tid,{})
        status='WIRING_ERROR' if error else 'IMPORTANT_FACT_MISSING' if gaps else 'BOUND_ORIGINAL_CONTROL' if tid in CONTROLS else 'BOUND_WITH_SOURCE_LIMITS'
        results.append(dict(**roster[tid],page=t['page'],query=t['query'],task_requirement=req,input_recovered=True,
            input_binding_status='BOUND' if source else 'FAILED',preparation_status=status,
            source_sufficient_for_bounded_replay=not gaps and not error,
            source_layers=dict(Resources='RAW_MOODLE_EVENTS',Lecture='RAW_CLICK_EVENTS_AND_CUMULATIVE_ECHO_SNAPSHOT',
                Debate='RAW_MOODLE_EVENTS_AND_CUMULATIVE_FEATURES',Reflection='CUMULATIVE_FEATURES_ONLY',
                course='SHARED_624_DOCUMENT_CORPUS',system_metrics='IMPLEMENTED_COLLECTION_CONTRACT'),
            current_domains=visible,additional_domains=added,evidence_selection=reason,
            important_missing=gaps,nonblocking_limits=['NO_COMMON_OBSERVATION_WINDOW','NO_AUTHENTICATED_ENROLMENT_OR_REAL_STUDENT_CLOCK',
                'ACTIVITY_NOT_QUALITY','UNSELECTED_DOMAIN_ABSENCE_IS_NOT_A_GLOBAL_GATE'],
            original_control=CONTROLS.get(tid),wire_error=error,
            gate_needs_clarification=source['clarification'] if source else None,
            memory_setup='CONTROLLED_NATIVE_INITIAL_STATE' if tid in NINE else 'NO_PERSISTENT_SETUP; ORIGINAL_SAME_SESSION_HISTORY',
            memory_writes=mt.get('accepted_writes',0),memory_diagnostic=mt.get('read_status','NOT_APPLICABLE'),
            memory_read_conditions={m:('MODE_PERMITS; ACTUAL_P3_YES_AND_GATE_PASS_REQUIRED' if m in ('S3_EVIDENCE_MEMORY','S5_FULL') else 'OFF_BY_MODE') for m in ('S0_PAGE_ONLY','S1_CROSS_PAGE_EVIDENCE','S2_EVIDENCE_RAG','S3_EVIDENCE_MEMORY','S4_EVIDENCE_PLANNING','S5_FULL')},
            primary_sha256=source['primary_sha256'] if source else None,
            external_permission='PENDING_ONE_CONSOLIDATED_USER_DECISION',generation_authorized=False,
            current_p3='NOT_RUN',candidate_and_final='NOT_RUN',human_evaluation='BLANK_NOT_RUN'))
    return results

def main():
    tasks=lines(HERE/'runtime/TASKS_62.jsonl');b=read(HERE/'runtime/BINDINGS.json');rows=assess(tasks,b)
    write(HERE/'PREPARATION_RESULTS_62.json',rows)
    with (HERE/'PREPARATION_RESULTS_62.csv').open('w',newline='') as f:
        w=csv.DictWriter(f,fieldnames=list(rows[0]));w.writeheader()
        for r in rows:w.writerow({k:json.dumps(v,ensure_ascii=False) if isinstance(v,(dict,list)) else v for k,v in r.items()})
    counts=dict(recovered=62,bound_inputs=sum(r['input_binding_status']=='BOUND' for r in rows),
        source_sufficient_bounded_replay=sum(r['source_sufficient_for_bounded_replay'] for r in rows),
        important_fact_missing=sum(bool(r['important_missing']) for r in rows),statuses=dict(Counter(r['preparation_status'] for r in rows)),
        externally_authorized=0,newly_generated=0,newly_human_scored=0,source_state_checks=62)
    write(HERE/'PREPARATION_COUNTS.json',counts)
    print(json.dumps(counts,ensure_ascii=False))

if __name__=='__main__':offline();main()
