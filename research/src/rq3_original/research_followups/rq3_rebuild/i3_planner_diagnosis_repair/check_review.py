"""Pre-commit preservation/readback checks; writes only this new I3 directory."""
from pathlib import PurePosixPath
import json
import re
import subprocess
import zipfile
from i3_common import HERE, ROOT, LIVE, I2_ZIP, PACKET, START, BRANCH, SCOPE, read, write, sha, canonical, git


def main():
    assert git('branch','--show-current')==BRANCH and git('rev-parse','HEAD')==START
    changed=set(git('diff','--name-only',START).splitlines())
    assert all(p.startswith(SCOPE) for p in changed)
    assert all(p.startswith(SCOPE) for p in git('ls-files','--others','--exclude-standard').splitlines())
    source=read(HERE/'SOURCE_PRESERVATION_MANIFEST.json')
    with zipfile.ZipFile(I2_ZIP) as z,zipfile.ZipFile(PACKET) as packet:
        assert sha(I2_ZIP.read_bytes())=='b9506c17b67640b7868e9d9c4016f22f83d47934a844779e7a108987db3175f0'
        assert z.testzip() is None and len(z.infolist())==791
        for r in source['captured_sources']:
            p=HERE/r['path'];b=p.read_bytes();origin=r['source']
            assert not p.is_symlink() and len(b)==r['bytes'] and sha(b)==r['sha256']
            if origin['kind']=='ACTUAL_I2_FILE_AND_ZIP':
                assert b==(LIVE/origin['relative_path']).read_bytes()==z.read(origin['zip_member'])
            elif origin['kind']=='COMMITTED_SOURCE':
                assert b==(ROOT/origin['relative_path']).read_bytes()
                assert b==subprocess.check_output(['git','show',START+':'+origin['relative_path']],cwd=ROOT)
            elif origin['kind']=='I2_ZIP_MEMBER':assert b==z.read(origin['member'])
            elif origin['kind']=='USER_TASK_PACKET':assert b==packet.read(origin['member'])
            else:raise ValueError(origin)
        pm=json.loads(packet.read('MANIFEST.json'))
        assert set(packet.namelist())=={'MANIFEST.json'}|{r['path'] for r in pm['members']}
        for r in pm['members']:
            b=packet.read(r['path']);assert len(b)==r['bytes'] and sha(b)==r['sha256']
    for r in source['frozen_registry']:
        b=(ROOT/r['path']).read_bytes();assert len(b)==r['bytes'] and sha(b)==r['sha256']
    tests=read(HERE/'OFFLINE_TEST_SUMMARY.json')
    assert tests['distinct_tests_passed']==240
    assert all(r['errors']==r['failures']==r['skipped']==0 for r in tests['suites'])
    standalone=read(HERE/'STANDALONE_REPLAY_RECEIPT.json');assert standalone['status']=='PASS' and standalone['test_report']['passed']==31
    matrix=[json.loads(l) for l in (HERE/'PLANNER_ATTEMPT_ERROR_MATRIX.jsonl').read_text().splitlines()]
    assert len(matrix)==32 and len({r['attempt_id'] for r in matrix})==32
    assert all(r['all_saved_issues_reproduced'] and r['replayed_status']=='ENCODED_CHECK' for r in matrix)
    transitions=read(HERE/'OFFLINE_OLD_NEW_CLASSIFICATION_AUDIT.json')['transitions']
    assert len(transitions)==32 and all(t['old']==t['new']=='ENCODED_CHECK' for t in transitions)
    reading=(HERE/'DEVELOPMENT_READING_COPY_VERIFIED.md').read_bytes();index=read(HERE/'ANSWER_READING_COPY_INDEX.json')
    for row in index['entries']:
        raw=read(HERE/row['raw_record']);answer=json.loads(raw['choices'][0]['message']['content'])['answer'].encode()
        assert answer==reading[row['reading_start_byte']:row['reading_end_byte_exclusive']]
        assert sha(answer)==row['answer_sha256']
    blank=(HERE/'HUMAN_DEV_CHECKLIST_BLANK.md').read_text()
    form_rows=[line for line in blank.splitlines() if line.startswith('| I0-SYN-')]
    assert len(form_rows)==72 and all(line.endswith(' | | | | |') for line in form_rows)
    assert '[x]' not in blank.lower()
    configs=read(ROOT/'research_followups/rq3_rebuild/i1_pilot_launch/PILOT_CONFIGURATION_PROPOSED.json')
    previews=list((HERE/'proposed_requests_not_authorized').glob('*.json'))
    units=[len(canonical(read(p)))+256 for p in previews]
    assert len(previews)==32 and max(units)<=configs['max_request_input_byte_units']
    patch=subprocess.run(['git','apply','--check',str(HERE/'INTEGRATION_PATCH_NOT_APPLIED.patch')],cwd=ROOT,capture_output=True,text=True)
    assert patch.returncode==0,patch.stderr
    copy_names={r['path'] for r in source['captured_sources']}
    protected_whitespace=[]
    secrets=[]
    for p in sorted(HERE.rglob('*')):
        if not p.is_file():continue
        name=p.relative_to(HERE).as_posix();safe=PurePosixPath(name)
        assert not p.is_symlink() and not safe.is_absolute() and '..' not in safe.parts and '\\' not in name
        assert p.suffix in ('.py','.md','.json','.jsonl','.txt','.patch'),name
        b=p.read_bytes()
        if re.search(rb'sk-(?:proj-|svcacct-)?[A-Za-z0-9_-]{20,}|-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----',b):
            secrets.append(name)
        if name in copy_names or name=='DEVELOPMENT_READING_COPY_VERIFIED.md':
            for i,line in enumerate(b.splitlines(),1):
                if line.rstrip(b' \t')!=line:protected_whitespace.append(dict(path=name,line=i,reason='EXACT_SOURCE_OR_ANSWER_BYTES'))
    assert secrets==[]
    receipt=dict(status='PASS',captured_sources_verified=len(source['captured_sources']),frozen_registry_files_verified=len(source['frozen_registry']),
        live_sources_unchanged=True,task_packet_manifest_verified=True,original_tracked_modifications=[],
        start_head=START,branch=BRANCH,scope=SCOPE,provider_calls=0,model_inference=0,human_forms_blank=72,
        all_saved_candidates_replayed=32,exact_answers_verified=72,distinct_tests_passed=240,standalone_tests_repeated=31,
        secret_pattern_matches=0,credential_values_read=False,
        integration_patch_dry_run='PASS_NOT_APPLIED',
        preview_input_units=dict(min=min(units),max=max(units),original_limit=configs['max_request_input_byte_units']),
        retained_whitespace=protected_whitespace,
        verification_limit='Static secret-pattern scan, not credential-value scanning; no credentials or API keys were read.')
    write('PRESERVATION_AND_REVIEW_CHECKS.json',receipt)
    (HERE/'I3_COMPLETION_REPORT.md').write_text(f'''# I3 完成报告

状态：**READY_FOR_LIMITED_PLANNER_RETEST_APPROVAL**。该状态只表示诊断和候选请求补丁可进入有限复测审批；没有新的模型调用授权，也没有 Planner 功能成功或回答质量结论。

已读取并核验实际 I2 ZIP、32 次候选原文及对应输入/错误、72 份回答。实际总计 128 次历史物理尝试：RAG 8、Memory 8、B4 路由 8、候选 32、FINAL 72。候选为 16 个逻辑槽位，每个有一次修订；全部保留失败。14 个实际混合 Memory 读取条件的原生文本/版本回读一致，保存的只读状态均为真。没有重新运行检索或模型。

确认的直接拒绝原因：32 次候选均有必填 evidence_refs 空数组，共 128 条原始数组长度错误。原 Provider schema 删除了本地 minItems 等限制；纠错虽包含全部原错误路径，却没有说明所需下限。10 次候选另含 29 处不存在的来源 ID，这些是被前置错误遮蔽的静态发现，不冒充原检查器已报错。未发现普通无日历建议因日期字段被原检查器误拒的证据；真正排程的两处缺信息门控保留。

新增 repair_v1.py 仅补全候选请求中的本地限制、原样来源 ID 到现有内容的映射、具体反馈，并移除候选提示内 FINAL 专属字段指令。校验器、模型快照、token/重试上限、P3、RAG、Memory 策略和旧产物不变。INTEGRATION_PATCH_NOT_APPLIED.patch 已通过 git apply --check，但未应用。32 次旧输出的新旧分类仍全是 ENCODED_CHECK；不得改写 I2 canonical 结果。

FINAL 没有接收被拒候选作为已批准计划：72 份 accepted_plan/plan_fields 均为 null。16 个失败条件只收到统一失败摘要；14 份回答出现 checked plan，4 份为原本无日期建议索要可靠排程信息，3 份自行写出了步骤。这些观察均有实际请求及原文定位，不代表 Planner 成功。原样阅读副本按 72 组 UTF-8 字节范围和 SHA-256 回读；人工检查表 72 行全部空白。

离线测试：**240/240** 项不同测试通过，P0 70、P1 85、I1 54、新增 I3 31；另在独立临时目录重复通过 I3 31 项并复现所有 128 次保存记录。8 项调用旧 run_pilot.main 的测试按任务边界未执行。保留了一次新测试封装器的 common 模块重名错误日志；仅重命名 I3 工具模块后原 I1 测试 54/54 通过。无历史代码修复、环境升级或隐瞒失败。

尚未确定：更清晰提示能否修好新候选；旧无效候选未到达的后续语义检查；旧计划接受/完成状态；历史 this week 的时效；真实语义支撑与可行性；最终回答的人类质量评价。合法 ID 仍无法识别 +40% 无依据效果陈述，已保留该反例。未给人工评分预填分数或理由。

建议下一轮按失败类别选择 5 个候选槽位：5 次初始、最多 5 次修订；仅在已接受计划改变输入且另获授权时，最多重做对应 5 份 FINAL。路由/检索调用 0，不默认重跑 72 份。精确槽位和依赖哈希见 MINIMAL_RETEST_DEPENDENCIES_NOT_AUTHORIZED.json。

源保全核验：{len(source['captured_sources'])} 份来源副本和 161 份冻结来源均通过。新增请求最大输入计量为 {max(units)}，原上限 {configs['max_request_input_byte_units']}，没有增加模型 token 或重试预算。

Git 起始：`{START}`；分支 `research/rq3-rebuild-i1-pilot-launch`。将只新增本目录并提交一次，题目为 `RQ3-REBUILD-I3: diagnose planner contract failures and prepare minimal repair`。提交后的实际结束 Git ID 由审阅 ZIP 根目录 GIT_VERSION.json 记录，避免自引用伪造。

审阅 ZIP 目标：`/Users/liuming/Downloads/RQ3_REBUILD_I3_PLANNER_DIAGNOSIS_REVIEW_2026-09-07.zip`。ZIP 的实际 SHA-256、大小、成员数和重新打开后的 CRC/逐成员核验在外部 READBACK 收据中记录。ZIP 根目录 OUTPUT_MANIFEST.json 覆盖其余成员；本地提交内的 OUTPUT_MANIFEST.json 在 ZIP 中保存为 COMMITTED_OUTPUT_MANIFEST.json。没有对外上传或接收确认。
''')
    # Exclude only this manifest, not nested source manifests of the same basename.
    files=[]
    for p in sorted(HERE.rglob('*')):
        if p.is_file() and p!=HERE/'OUTPUT_MANIFEST.json':
            b=p.read_bytes();files.append(dict(path=p.relative_to(HERE).as_posix(),bytes=len(b),sha256=sha(b)))
    write('OUTPUT_MANIFEST.json',dict(version='I3_COMMITTED_OUTPUT_MANIFEST_V1',excluded_self='OUTPUT_MANIFEST.json',files=files,
        zip_manifest_note='ZIP root OUTPUT_MANIFEST.json is generated after commit; this file is included as COMMITTED_OUTPUT_MANIFEST.json.'))
    print(dict(status='PASS',source_files=len(source['captured_sources']),new_files=len(files)+1,tests=240,maximum_preview_input_units=max(units)))


if __name__=='__main__':main()
