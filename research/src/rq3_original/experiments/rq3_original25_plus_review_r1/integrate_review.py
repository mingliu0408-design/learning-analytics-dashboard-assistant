"""One bounded, source-checked R1 data revision; no runtime/tool redesign.

Run once in the existing checkout after byte-preserving intake. The V2 runner,
adapter, ordinary sources and closed native states are reused without rebuilding.
This script does not import the runtime, retrieve, score or read credentials.
"""
from pathlib import Path
from copy import deepcopy
from collections import Counter
import hashlib
import json
import shutil
import sys

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
OLD = HERE.with_name('rq3_original25_plus_v2')
REVISION = 'ORIGINAL25_PLUS_REVIEW_R1'


def read(p):
    return json.loads(Path(p).read_text())


def lines(p):
    return [json.loads(s) for s in Path(p).read_text().splitlines() if s.strip()]


def sha(b):
    return hashlib.sha256(b).hexdigest()


def write(p, v):
    p = Path(p)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(v, ensure_ascii=False, indent=2, allow_nan=False) + '\n')


def jsonl(p, rows):
    Path(p).write_text(''.join(json.dumps(r, ensure_ascii=False, allow_nan=False) + '\n' for r in rows))


def pointer(obj, ptr):
    for k in ptr.lstrip('/').split('/'):
        k = k.replace('~1', '/').replace('~0', '~')
        obj = obj[int(k)] if isinstance(obj, list) else obj[k]
    return obj


def source_fact(text, *pointers):
    name = 'source_materials/original25/PAGE_SOURCES.json'
    obj = read(HERE / name)
    return dict(fact=text, evidence=[dict(kind='STRUCTURED_SOURCE', path=name,
        json_pointer=p, value=deepcopy(pointer(obj, p))) for p in pointers])


def course_span(chunk_id, start=0, end=None):
    corpus = {c['chunk_id']: c for c in lines(HERE / 'source_materials/course/corpus.jsonl')}
    text = corpus[chunk_id]['text']
    end = len(text) if end is None else end
    manifest = read(HERE / 'source_materials/course/manifest.json')
    matches = [(d, i) for d in manifest['documents'] for i in d['native_chunk_intervals']
               if i['chunk_id'] == chunk_id]
    assert len(matches) == 1
    d, interval = matches[0]
    a, b = interval['char_start'] + start, interval['char_start'] + end
    quote = text[start:end]
    assert (HERE / d['extracted_path']).read_text()[a:b] == quote
    assert sha((HERE / d['raw_path']).read_bytes()) == d['raw_sha256']
    return dict(kind='COURSE_SPAN', path='source_materials/course/corpus.jsonl',
        chunk_id=chunk_id, document_id=d['document_id'], document_version=d['raw_sha256'],
        origin_raw_path=d['raw_path'], char_start=start, char_end=end, quote=quote,
        readable_path=d['extracted_path'], document_char_start=a, document_char_end=b,
        offset_unit='Unicode codepoints; extracted text; end exclusive')


def course_fact(text, chunk_id, start=0, end=None):
    return dict(fact=text, evidence=[course_span(chunk_id, start, end)])


def original_supplements():
    resource_count = source_fact('所附资源访问记录为221次，不等于221个不同资源或阅读完成。',
        '/pages/Resources/resource_events/count', '/pages/Resources/metrics/Resources_views',
        '/pages/Resources/resource_events/boundary')
    resource_distribution = source_fact('来源标签Week6为3次，来源星期Thursday为81次；这些标签不是当前周或当前可用时间。',
        '/pages/Resources/resource_events/by_source_week/6',
        '/pages/Resources/resource_events/by_source_weekday/Thursday',
        '/pages/Resources/resource_events/boundary')
    resource_method = source_fact('定义为Moodle资源或阅读view事件，计算标记为COUNT_ROWS_FILTER_EVENT；按匹配事件行计数，未任意删除外观重复行。',
        '/pages/Resources/metrics/Resources_views', '/pages/Resources/resource_events/calculation',
        '/pages/Resources/resource_events/boundary')
    debate = source_fact('所附讨论记录为浏览50次、发帖6次、回复11次；分别表示访问和互动频率，不能据此评价帖子质量。',
        '/pages/Debate/events/views/count', '/pages/Debate/events/posts/count',
        '/pages/Debate/events/replies/count', '/pages/Debate/metrics')
    mail = source_fact('所附实现范围为Moodle论坛view/post/reply事件；邮件阅读回执未出现在所附表或实现指标中。',
        '/pages/Debate/collection_scope', '/pages/Debate/metrics/Debate_views')
    reflection = source_fact('所附Reflection Total_chars为45,093，表示累计字符编辑活动，不能当作当前文档长度或学习质量。',
        '/pages/Reflection/writing_snapshot', '/pages/Reflection/metrics', '/pages/Reflection/boundary')
    reflection_conditional = deepcopy(reflection)
    reflection_conditional['fact'] = '若原题指当前材料可解释的字符编辑指标，Total_chars为45,093；这是累计编辑活动，不能确认为strings的精确同义词，也不是当前文档字数或质量。'
    missing_text = source_fact('所附材料没有反思正文、周级编辑事件、提交回执或反馈成绩。', '/pages/Reflection/missing')
    playback = source_fact('所附录播观看快照共11次观看事件；指标定义保留Panopto字样，来源ID为echo，两者映射未确认。',
        '/pages/Lecture/playback_snapshot/total_view_events', '/pages/Lecture/playback_snapshot/source_id',
        '/pages/Lecture/metrics/Video Views')
    playback_kind = source_fact('Video Views和Video View %是录播观看活动及播放比例，Video_clicks是Moodle视频相关点击；这些字段不能证明现场出勤。',
        '/pages/Lecture/metrics', '/pages/Lecture/playback_snapshot/boundary')
    lecture_absence = source_fact('当前快照明确说明未提供讲座录像或转录；课程入口和元数据不能替代完整内容。',
        '/pages/Lecture/playback_snapshot/boundary')
    week4 = course_fact('所附课程元数据将W4标为Learning Analytics，涉及学习理论、学习设计、数字痕迹与学习分析；Multimodal Learning Analytics归W5。仅为元数据概括。', 'course_metadata_w4')
    return {
        1: [resource_count, debate, reflection, playback],
        3: [mail], 6: [resource_count, resource_distribution], 8: [playback_kind, playback],
        10: [resource_count, resource_method], 11: [resource_method],
        12: [reflection_conditional, missing_text], 15: [debate], 16: [resource_count, resource_distribution],
        17: [debate, source_fact('互动汇总只有结构和人数计数，没有交流正文或质量判定。',
             '/pages/Debate/interaction_snapshot', '/pages/Debate/metrics/Reply network')],
        19: [mail, source_fact('回复和浏览网络说明谁与谁互动及频率，不说明交流质量或理解。',
             '/pages/Debate/metrics/Reply network', '/pages/Debate/metrics/View network')],
        20: [mail], 21: [resource_count, debate, reflection, playback],
        24: [week4, lecture_absence], 25: [lecture_absence],
    }


# These are evaluator-side answer boundaries, not ratings or model prompts.
MINIMUM = {
    1: ['给出一项主要观察即可；从相关且正确的记录中选择支持，不要求复述四域或全部数字。', '不把异质活动次数合成投入、掌握或动机诊断。'],
    3: ['说明本回放看不到邮件阅读回执，并区分Moodle页面访问与在邮件中阅读。'],
    6: ['给出至少一项可实行的资源学习时间管理建议，并结合资源记录的有限含义。', '无需完整日历即可提供一般建议；不编造当前空闲时段或精确截止日。'],
    8: ['说明这些字段描述所附录播观看或Moodle访问，不能据此判断现场参与。', '使用中性平台称谓，不认证echo与Panopto的映射。'],
    10: ['解释Resources_views是资源/阅读访问事件频率，并说明不是阅读完成或掌握程度。'],
    11: ['解释按所附匹配view事件行计数的口径，不把访问次数说成去重资源数。'],
    12: ['条件式解释当前材料能说明的字符编辑指标；不断言strings就是累计编辑字符量。', '不从累计编辑量推断当前篇幅、反思质量或周级进步。'],
    13: ['基于课程指南提出至少一项一般反思写作改进方法，不伪称读过未提供的正文。'],
    15: ['提出至少一项与讨论活动有关的可实行建议，区分活动频率和讨论质量。'],
    16: ['以当前Resources页面限定活动域，给出至少一项有记录依据的可选策略。'],
    17: ['以当前Debate页面限定活动域，给出范围受限的参与建议；更细的this aspect指代仍未知。'],
    19: ['说明所附Moodle论坛事件及互动汇总的记录口径，不认证实时采集管线或同意流程。'],
    20: ['直接说明本回放无法观察邮件阅读，不否认用户实际读过邮件。'],
    21: ['选择少量有记录依据的具体参与建议；不要求覆盖所有页面、固定顺序或精确日历。'],
    23: ['给出与课程指南一致的可用反思结构，并标明它是合理组织方式而非唯一规定格式。'],
    24: ['仅按所附课程元数据概括W4 Learning Analytics，不把W5主题或未提供的讲授细节加入。'],
    25: ['明确当前材料没有完整录像或转录；入口信息不等于已获得内容或账号权限。'],
}

ALTERNATIVES = {
    1: '可只选资源、讨论、录播或编辑活动中的一个有根据的观察；遗漏无关数字不是缺事实。',
    3: '可用不同表达说明记录可见性边界；无需否认学生在邮件中阅读。',
    6: '优先排序、短阅读与回顾单元或自定可用时间均可；具体日程仅在所需信息存在时给出。',
    8: '可分别解释观看次数、播放比例或平台点击；无需枚举全部字段。',
    10: '可用定义加一个计数示例，或只解释指标及关键局限。',
    11: '可概括事件行计数及其范围；无需伪称独立重跑采集实现。',
    12: '可以先限定“若你指的是所附字符编辑指标”，再说明数值及局限；可请求明确术语。',
    13: '可以围绕经验与理论连接、论点、证据或不同视角选一项展开；需要逐段诊断时再请求正文。',
    15: '有理由的回应、提出问题、对照证据或回顾自己的贡献均可；不要求唯一策略。',
    16: '可选一项相关资源并做摘要、自测或回顾；不能把较少访问视为已证实的学习缺陷。',
    17: '可给一般讨论策略并说明范围；若需针对更细指代，则作有针对性的澄清。',
    19: '可解释浏览/发帖/回复中的相关事件，或说明互动网络是结构摘要。',
    20: '可简短确认当前记录不可见，不必提供额外学习计划。',
    21: '不同的少量步骤、优先级或部分计划均可，只要符合已知数据与限制。',
    23: '经验—分析/理论—不同视角—所得—后续应用是一个选项；其他能满足指南原则的结构同样可接受。',
    24: '可提供谨慎的主题概览并指出没有完整视频/转录；无需逐段课程总结。',
    25: '可说明可用元数据范围，并请提供获准使用的录像或转录；不能保证外部链接可访问。',
}


def run():
    assert not (HERE / 'runtime_tasks.jsonl').exists(), 'R1 already exists; do not overwrite a revision'
    intake = read(HERE / 'audit/INTAKE.json')
    for path, digest in intake['preserved_files'].items():
        assert sha((ROOT / path).read_bytes()) == digest, path
    # Independent old-query assertions precede every write to the runtime roster.
    tasks = lines(OLD / 'runtime_tasks.jsonl')
    refs = lines(OLD / 'evaluation_reference.jsonl')
    review = read(HERE / 'received_review/01_填写表.json')
    proposals = read(HERE / 'task_spec/QUERY_EDIT_PROPOSALS.json')['changes']
    assert [r['task_id'] for r in review['items']] == [t['task_id'] for t in tasks]
    assert len(tasks) == len(review['items']) == 49
    assert len(proposals) == len({p['task_id'] for p in proposals}) == 9
    by_id = {t['task_id']: t for t in tasks}
    for change in proposals:
        assert by_id[change['task_id']]['query'] == change['before'], change['task_id']
    old_facts = {r['task_id']: deepcopy(r['required_facts']) for r in refs[:25]}
    manifest = read(OLD / 'RUN_MANIFEST.json')
    ready = manifest['task_ids']
    empty = [r['task_id'] for r in refs[:25] if not r['required_facts']]
    assert len(empty) == 23 and sum(t in ready for t in empty) == 15
    assert [t for t, facts in old_facts.items() if facts] == ['original-13', 'original-23']
    for name in ['v2_common.py', 'adapter.py', 'run_batch.py', 'original25_roster.jsonl',
                 'original25_binding_status.jsonl', 'family_design.json', 'BINDINGS.json',
                 'CONFIG_PROPOSED.json', 'EXECUTION_APPROVAL_TEMPLATE.json']:
        shutil.copy2(OLD / name, HERE / name)
    for folder in ['source_materials', 'native_initial', 'human_review']:
        shutil.copytree(OLD / folder, HERE / folder)
    # Setup receipts are inherited evidence of the earlier state build, including
    # its earlier target query; they are never used as current prepared inputs.
    baseline = HERE / 'baseline'
    baseline.mkdir()
    for name in ['runtime_tasks.jsonl', 'evaluation_reference.jsonl', 'LANGUAGE_ALIGNMENT.json',
                 'translation_map.json', 'RUN_MANIFEST.json']:
        shutil.copy2(OLD / name, baseline / name)
    changes = []
    for c in proposals:
        by_id[c['task_id']]['query'] = c['proposed_after']
        changes.append(dict(c, applied_after=c['proposed_after'],
            applied_status='USER_AUTHORIZED_LIMITED_QUERY_REVISION', old_query_exact_match=True,
            runtime_query_version=REVISION))
    jsonl(HERE / 'runtime_tasks.jsonl', tasks)
    write(HERE / 'QUERY_CHANGES.json', dict(data_revision=REVISION, changes=changes))

    supplements = original_supplements()
    assert {f'original-{n:02}' for n in supplements} == set(empty) & set(ready)
    core = 'handbook_the_core_elements_of_academic_reflective_writing_1'
    for i, r in enumerate(refs[:25], 1):
        if i in supplements:
            r['required_facts'] = deepcopy(supplements[i])
        if r['task_id'] in ready:
            r['minimum_answer_requirements'] = MINIMUM[i]
            r['acceptable_alternatives'] = [ALTERNATIVES[i]]
            r['fact_list_semantics'] = 'Evaluator fact pool; select what the question needs. Not an exhaustive answer checklist.'
            r['optional_support'] = deepcopy(r['required_facts'])
            if i in (13, 23):
                assert r['required_facts'] == old_facts[r['task_id']]
                r['optional_support'] += [course_fact(
                    '指南支持论证线索、经验与已有知识的连接、不同视角及反思所得/后续使用；具体结构为合理整理而非唯一模板。', core),
                    course_fact('所附Part A说明每周问题、个人分析、文献及同伴观点归属；不能认证为原提问者当时的作业要求。',
                        'handbook_part_a_critical_analysis_and_reflection_portfolio')]
                if i == 13:
                    r['optional_support'].append(source_fact('没有个人反思正文，不能逐段诊断。', '/pages/Reflection/missing/reflection_text'))
            r['unknowns'] = list(dict.fromkeys(r['unknowns'] + [
                '所用背景为受控复用，原提问者身份、完整会话与原时间语境未恢复。',
                '一般建议可以基于现有资料提出；只有具体缺件影响所问判断时才需要针对性澄清。']))
        else:
            assert not r['required_facts']
            missing = next(b['missing'] for b in lines(HERE / 'original25_binding_status.jsonl') if b['task_id'] == r['task_id'])
            r['minimum_answer_requirements'] = ['本轮保留缺件，不纳入来源可准备队列；不从旧答案反造上下文。']
            r['acceptable_alternatives'] = ['需补的特定来源：' + '; '.join(missing)]
        if i == 12:
            r['unknowns'].append('strings与当前字符编辑指标的对应未确认；45093不能认证为strings个数或当前文档长度。')

    bibliography = '所附手册提供Ryan (2011)书目：Improving reflective writing in higher education: a social semiotic perspective；Teaching in Higher Education 16(1), 99–111，并有标明据其及其他来源改编的课程反思指南。固定材料没有该论文全文，不能由课程指南核验原文实施步骤。'
    adaptation = course_span('handbook_the_core_elements_of_academic_reflective_writing_3', 243)
    assert adaptation['quote'].startswith('Developed from:')
    extra_p03 = course_span('handbook_part_b_design_case_extension_or_design_critique_3', 317, 464)
    assert (extra_p03['document_char_start'], extra_p03['document_char_end']) == (12133, 12280)
    assert extra_p03['quote'] == 'What are the theoretical underpinnings if any that the given technology is based and what is the evidence that motivates its design and evaluation?'
    for r in refs[25:]:
        if r['family_id'] == 'R03':
            r['required_facts'][0]['fact'] = bibliography
            r['required_facts'][0]['evidence'] += [deepcopy(adaptation), course_span(core, 169, 379)]
            r['unknowns'] = ['允许固定资料中没有Ryan论文全文；课程改编指南不能作为其原文实施步骤。']
            if r['condition'] == 'A':
                r['minimum_answer_requirements'] = ['提供题名、期刊和页码即可；不强制复述课程指南或不存在的论文训练程序。']
                r['acceptable_alternatives'] = ['正常书目格式或清晰自然语言均可。']
            else:
                r['minimum_answer_requirements'] = ['说明固定资料无法核验所问论文实施步骤，区分书目、课程改编指南与论文全文。']
                r['acceptable_alternatives'] = ['可以仅说明来源不足；也可另给明确标为课程指南的一般练习，不能称作Ryan原文步骤。']
        if r['family_id'] == 'P03':
            assert len(r['required_facts'][6]['evidence']) == 1
            r['required_facts'][6]['evidence'].append(deepcopy(extra_p03))
        if r['family_id'].startswith('P'):
            r['minimum_answer_requirements'] = ['根据可用来源、估计用时、依赖、已完成状态和已知偏好提出合理的部分或完整方案；不要求复制参考顺序。']
            r['acceptable_alternatives'] = list(dict.fromkeys(r['acceptable_alternatives'] + [
                '参考预算例证不是唯一答案；任何遵守依赖、完成状态、预算和已知偏好的合理部分方案或完整方案均可。']))
        r['fact_list_semantics'] = 'Evaluator-side support and boundaries; do not require verbatim or exhaustive reproduction.'
    for r in refs:
        r['reference_version'] = REVISION + '_LIMITED_SOURCE_CHECKED_NOT_HUMAN_APPROVAL'
        r['source_review_status'] = review['status']
        r['integration_authority'] = 'USER_MESSAGE_LIMITED_OFFLINE_DATA_REFERENCE_EDITS_ONLY'
    jsonl(HERE / 'evaluation_reference.jsonl', refs)

    modes = read(HERE / 'CONFIG_PROPOSED.json')['modes']
    projection = []
    for r in review['items']:
        projection.append(dict(task_id=r['task_id'], source_preparable=r['task_id'] in ready,
            review_status=review['status'], draft=deepcopy(r['applicability']),
            confirmed={k: None for k in r['applicability']}, confirmed_final_inclusion=None,
            approved_for_run=False, shared_across_modes=modes, reviewer_id=r['reviewer_id'],
            signature=r['signature'], confirmed_by=None, confirmed_at=None))
    write(HERE / 'applicability.json', dict(status='DRAFT_PROJECTION_NOT_AUTHOR_DECISION', items=projection))
    criteria = [('Multi41', 'MULTI_PAGE_COHESIVENESS', 41), ('Motivation22', 'MOTIVATION_AND_ENGAGEMENT', 22),
                ('Error5', 'ERROR_HANDLING', 5), ('R03-B Actionability1', 'ACTIONABILITY', 1)]
    suggestions = [
        '附件建议：未增加跨页连续回答采集时按原定义记不可观察/NA；另一方案需预先明确批准单回答适配及适用范围。',
        '附件建议：22个事实/规范说明或提醒任务不另要求独立鼓励策略，记NA。',
        '附件建议：5个可按现有材料给一般建议的原题记NA；现有15个draft true不自动改。',
        '附件建议：按原文方法来源边界题记NA；若评价替代学习步骤需作者预先明确规则。']
    groups = []
    for (name, criterion, count), suggestion in zip(criteria, suggestions):
        ids = [r['task_id'] for r in projection if r['source_preparable'] and r['draft'][criterion] is None]
        assert len(ids) == count
        groups.append(dict(group=name, criterion=criterion, task_ids=ids, count=count,
            attachment_suggestion=suggestion, suggestion_status='NOT_APPROVED', author_decision=None,
            author_id=None, decision_reason=None, decided_at=None, same_map_for_six_modes=True))
    counts = Counter('null' if v is None else str(v).lower() for r in projection if r['source_preparable'] for v in r['draft'].values())
    assert dict(counts) == {'true': 208, 'false': 51, 'null': 69}
    write(HERE / 'AUTHOR_DECISIONS.json', dict(status='PENDING_AUTHOR_DECISIONS', applicability_groups=groups,
        candidate41_draft_counts=dict(counts), final_sample_size=None, multi_page_observation_design=None,
        final_inclusion=None, rater_arrangement=None, aggregation_and_multiplicity=None,
        external_source_authorization=None, model_budget_authorization=None,
        notes=['17个共享受控回放与新12个family分别报告，不能视为41个独立学生。',
               '同一任务六模式使用相同最终map；条件间真实差异需事先记录，不由模型输出决定。',
               '用户已批准本轮限定资料修订，未批准正式纳入、最终适用性或独立人评认证。']))

    source_readme = '''# 来源范围（R1限定修订）

新24条件的活动、页面状态和历史是构造情境；原25中的17个可准备任务使用既有普通来源的受控重置背景。两者均不声称恢复原学生身份、原完整会话或原时间语境。8个缺件原题保留缺件。来源可准备不等于正式纳入或获准运行。

固定课程库保留624个既有chunk、六份原件和其固定导出。原始ID、版本、Unicode字符区间及来源值均不变；区间不是原DOC/PDF的字节偏移。书目、课程改编指南、入口和元数据均不能替代被引论文全文或完整讲座。C09只增加评价侧定位。

原25的PAGE_SOURCES.json及RAW_AGGREGATION_RECEIPT.json逐字节沿用V2。收据记录2026-09-07本地受控回放聚合及四项raw/features计数相合：Resources views 221、Debate views 50、posts 6、replies 11。本轮核对所附快照、收据及已存在的实现文件身份；未重新读取原始CSV或执行全量采集/权限审计。收据不能认证同意流程、原身份恢复或外发许可。

Lecture解释采用“所附录播观看记录”。源ID echo和原指标定义中的Panopto均保持；其平台映射待作者核实。Content_week是材料周，不是观看日期；No Lecture Video的零不等于缺席。累计快照没有共同观察窗口，活动不等于质量。

新24保留范围过滤、记录快照与事件计数的区别。COMPLETE的零仅限所声明实验事件流；UNKNOWN保持null。E03-B、R03-B、M03-B的无答案或未知条件不补事实。8份历史及26条PUT_VERSION源操作保留角色、版本与原句；assistant未采纳建议不提升为学生承诺或ACTIVE_PLAN。valid_until=null不保证无限适用。

runtime_tasks只含普通任务字段。评价参考、family、适用性、审阅理由和最低要求只保存在sidecar。原始五份回传保持DRAFT_PENDING_CONFIRMATION。旧native setup_receipt按原字节保留，是V2状态构建的历史收据，内含旧target query；当前查询与身份以R1 runtime_tasks、prepared_inputs和INPUT_IDENTITY_CHANGES为准。状态内容未因查询修订而重造。
'''
    (HERE / 'source_materials/README.md').write_text(source_readme)
    alignment = read(OLD / 'LANGUAGE_ALIGNMENT.json')
    alignment['data_revision'] = REVISION
    alignment['translation_status'] = 'NINE_USER_AUTHORIZED_QUERY_EDITS_OTHER_TRANSLATIONS_INHERITED'
    alignment.pop('independent_new_task_count', None)
    alignment.update(new_condition_count=24, new_family_count=12, independent_student_count=None)
    translations = read(OLD / 'translation_map.json')
    for p in alignment['pairs']:
        old_query = p['english_query']
        p['english_query'] = by_id[p['task_id']]['query']
        if p['english_query'] != old_query:
            p['prior_english_query'] = old_query
            assert translations[p['chinese_query']] == old_query or translations[p['chinese_query']] == p['english_query']
            translations[p['chinese_query']] = p['english_query']
    alignment['source_files'] = {n: sha((HERE / n).read_bytes()) for n in alignment['source_files']}
    write(HERE / 'LANGUAGE_ALIGNMENT.json', alignment)
    write(HERE / 'translation_map.json', translations)
    manifest.update(data_revision=REVISION, roster_sha256=sha((HERE / 'runtime_tasks.jsonl').read_bytes()),
        approved_for_run_task_ids=[], final_inclusion_status='PENDING_AUTHOR_DECISION',
        reference_sidecar='evaluation_reference.jsonl', references_allowed_in_model_input=False)
    write(HERE / 'RUN_MANIFEST.json', manifest)
    write(HERE / 'audit/COUNTS.json', dict(roster=49, original_roster=25, new_conditions=24, new_families=12,
        preparable=41, preparable_original=17, pending_source_original=8, query_edits=9,
        original_empty_before=23, preparable_original_empty_before=15, supplemented_originals=15,
        original_existing_fact_rows_retained=['original-13', 'original-23'], provider_calls=0,
        p3_calls=0, target_retrieval_calls=0, embedding_calls=0, candidate_calls=0, final_calls=0,
        judge_calls=0, human_scores_filled=0, signatures_filled=0, human_decisions=0, api_key_reads=0))
    write(HERE / 'REVISION.json', dict(data_revision=REVISION, runtime_schema=manifest['version'],
        inherited_runtime_files={n: sha((HERE / n).read_bytes()) for n in ['v2_common.py', 'adapter.py', 'run_batch.py']},
        runtime_logic_changed=False, generation_config_changed=False, native_initial_rebuilt=False,
        native_binding_sha256=sha((HERE / 'BINDINGS.json').read_bytes()),
        course_sha256=sha((HERE / 'source_materials/course/corpus.jsonl').read_bytes()),
        start_head=intake['starting_head'], data_authority='Direct user message in this task',
        review_adoption_scope='LIMITED_SOURCE_REFERENCE_EDITS_ONLY_NOT_INDEPENDENT_HUMAN_CERTIFICATION'))
    print(json.dumps(read(HERE / 'audit/COUNTS.json'), ensure_ascii=False))


if __name__ == '__main__':
    sys.dont_write_bytecode = True
    run()
