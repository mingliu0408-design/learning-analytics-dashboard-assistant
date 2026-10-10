# G0-R1 actual validation record

Validation date: 2026-10-10 (Asia/Shanghai). This record describes engineering checks on the newly restored public adaptation. It does not revise dissertation scores or establish new learning outcomes.

## Environment and commands actually exercised

A fresh Python 3.13.0 macOS ARM64 venv was created without system packages. Installation from `requirements.txt` succeeded; `pip check` reported no broken requirements. The installed `pip freeze` is byte-for-byte identical to the checked-in `requirements-lock.txt`. The first PyPI attempt timed out; retrying with a longer download timeout completed. No original research environment or author provider key was used.

From the repository root, with Python 3.13 in an isolated venv:

```bash
python -m pip install -r requirements.txt
python -m pip check
python -m unittest discover -s tests -v
python scripts/security_scan.py --repo .
python -m streamlit run app.py --server.headless=true --browser.gatherUsageStats=false
```

From the `research` directory:

```bash
python -m unittest discover -s checks -p 'test_*.py' -v
python checks/check_snapshot.py
python checks/check_rq3.py
```

## Local tests: passed

| Checks | Actual result | What the evidence establishes |
| --- | --- | --- |
| Preserved demo suite | 19 tests passed as part of the original 41-test full run | Existing R0, SQLite/FTS, consent, learner/course separation, update rules, typed candidate validation, mocked online errors/citations and legacy UI still work. Only its UI test entrypoint follows the byte-preserved legacy application. |
| Independent publication suite | 19 tests passed, 21.963 s | 41 task identities, six modes and 246 rows are retained, including 179 distinct answer texts; all answer hashes match. The 624 actual course chunks have provenance and no evaluation fields. |
| Restored runtime suite | 10 tests passed, 15.036 s | Exact frozen three-role P3 payloads connect through original R0, full M1 worker, typed candidate, one repair and FINAL/citation checks. Missing optional MPNet is explicit. Gold sidecars are rejected. |
| Preserved research tests | 20 tests passed, 4.697 s | RQ1/RQ2/R7 saved-count and prediction regressions, ratings identity/NA handling and S7 analytical fixtures remain consistent. No historical answer or rating was regenerated. |
| Preserved RQ3 contract script | 7 tests passed, 0.223 s | Scope, unknown/zero, five source views, modes, frozen P3, single RAG gate, Memory role/readonly and typed/citation boundaries remain checked. |
| Preserved historical manifest | 315 files passed length and SHA-256 checks | The earlier public research snapshot remains internally intact. New publication manifests separately describe the restored additions. |

The first complete application run passed all 41 tests in 78.170 s. Six downloader fixtures and one additional HTTP isolation test were then added and both affected suites were rerun to pass. The final complete application runner then passed all 48 tests in 32.931 s: 19 preserved demo + 19 independent publication + 10 runtime.

AppTest actually changed all five page choices, replayed a stored answer, executed real local R0/M1 components, drove UI through exact mocked P3/candidate/FINAL requests and checked two independent visitor sessions. Visitor keys stayed out of global environment and writable files; chats and writable SQLite state were separated. Provider errors did not display a synthetic confidential detail. Streamlit's bare-mode ScriptRunContext warnings occurred during AppTest; there were no app exceptions in passing UI checks.

The runtime HTTP isolation fixture made five real local HTTP POSTs to a no-fee provider mock: three frozen P3 roles, candidate and FINAL. Those calls remained possible after the full original M1 imported its network-denial guard in the child. The main API process did not import that M1 guard. Exact request/response mocking proves integration, not model quality or a paid model call.

The local Streamlit server actually started. Its health route returned HTTP 200 with `ok`; its root returned the Streamlit HTML shell. These server checks are separate from the AppTest interactions and do not establish public cloud deployment.

## Safety and data download checks

`scripts/security_scan.py` inspects Git candidates and explicitly supplied archives, including nested Office ZIP containers. It reports paths and codes only; it blocks private key headers, known provider/GitHub credentials, literal authentication fields, actual secrets configurations, Git/environment/cache directories, fonts, signature/identity attachments, unsafe archive paths, duplicates and links. The scan is a pattern/policy guard plus manual candidate review, not a promise to recognize all secrets.

The downloader passed positive extraction and repeat-use tests and rejected path traversal, duplicate and case-colliding paths, archive links, destination links, member/total/count overflow, incorrect per-file hashes, changed existing user files, wrong archive SHA-256, HTTP URLs and insecure redirects. All rejection fixtures left their destination unpublished. Downloads use public HTTPS with an expected full SHA-256 and archives are staged and fully checked before publication.

The final candidate code scan passed 2,120 files with zero findings. The research data archive `LAD_ASSISTANT_G0_R1_RESEARCH_DATA_2026-10-10.zip` passed independent recursive scanning with zero findings, SHA-256 `cb690dc0adbf361ea437a72e8beae319fdee3ca25b5311403cb497ffc7843612`, 67,328,343 bytes and 17,704 members. The real archive then passed full safe extraction, CRC and every published per-file manifest hash: first use wrote 17,704 files; second use wrote zero and recognized all 17,704 as identical. These local archive checks are separate from public GitHub download verification. Final code/author archive hashes and public-download outcomes are recorded with the publication artifacts after those exact packages are built.

## CI, public deployment and live boundaries

The added GitHub Actions workflow uses Ubuntu and Python 3.13, read-only repository permissions, no API key, all preserved tests, publication tests, research contract checks, safety scan and a real Streamlit health startup. Its actual GitHub run URL and outcome are reported by the final publication record; creating a workflow file alone is not a passed CI run.

The current validation used explicit lexical Memory in no-key components/mocks. Full Hybrid Memory requires the separately documented pinned MPNet resources and optional dependencies. Missing resources produce a clear failure rather than a silent backend substitution. Those optional resources and real paid LLM inference were not tested in this validation. `LIVE_LLM_TESTED = false`.

Public Community Cloud state is reported separately after login/deployment and correct UI interaction. A localhost app, GitHub Pages, a login page or HTTP 200 alone does not establish a deployed Streamlit app. Cloud writable files are temporary; local session storage is persistent only while its selected filesystem remains available. Public historical seeds stay read-only.

## Actual local browser evidence

The local browser rendered all five page choices with their expected page identity, replayed original-01/S0 from the saved dataset, and executed the real original R0 and complete M1 in COMPONENTS. The result identity was COMPONENTS / NO_LLM_NO_NATURAL_ANSWER_GENERATION. Actual screenshots are docs/screenshots/replay-local.jpg and components-local.jpg. This browser evidence is in addition to AppTest; it remains localhost evidence, not Community Cloud.

## Actual GitHub publication and anonymous readback

The core code commit `a2ec4f177072ec287a4f46bb0afb0a968a8bc255` was normally pushed to main and [Linux CI](https://github.com/mingliu0408-design/learning-analytics-dashboard-assistant/actions/runs/38022488036) completed SUCCESS on that exact commit. A credential-free clean clone independently passed all 48 app tests, 20 research tests, 7 RQ3 contracts, 315 preserved snapshot hashes, safety scan and Streamlit startup. The [new Release](https://github.com/mingliu0408-design/learning-analytics-dashboard-assistant/releases/tag/v0.2.0-g0-r1) targets the core commit and retains the older v0.1.0 tag. Later documentation/link commits do not move this release tag.

The actual published archive was anonymously downloaded over public HTTPS, with no author credential headers or cookies: HTTP 200, 67,328,343 bytes, 17,704 members, SHA-256 `cb690dc0adbf361ea437a72e8beae319fdee3ca25b5311403cb497ffc7843612`. CRC and every published manifest member hash passed. Safe extraction wrote 17,704 files; repeated extraction wrote zero and recognized 17,704 identical files. This confirms public data availability, separately from the local ZIP and cloud application.

The complete recovered-source commit `b64d991fb669e1d02f05c513fcde3f79a871c3ff` also passed [Linux CI](https://github.com/mingliu0408-design/learning-analytics-dashboard-assistant/actions/runs/38024812270) SUCCESS, including the recovered Unicode original UI page and public download manifest. Streamlit login and GitHub OAuth are completed; repo/main/app.py have been entered. The native browser tool currently cannot submit the Python version selection. No deployed app URL is claimed from this form.
