# G0-R1 engineering guidance actually applied

Checked on 2026-10-10. The provided local skill catalog and installed skill roots contain no Python refactoring, Streamlit, testing, application-security, GitHub Actions, or Streamlit deployment SKILL.md appropriate to this task. A targeted filename search confirmed that absence. No unrelated Nature writing/review skill was applied and no skill installation was required.

The implementation instead follows the public primary documentation below, read during this run:

| Area | Guidance and concrete application |
| --- | --- |
| Python environment | [Python 3.13 venv](https://docs.python.org/3.13/library/venv.html): a new isolated environment, no system site packages and no packaged virtual environment. |
| Tests and mocks | [unittest.mock](https://docs.python.org/3.13/library/unittest.mock.html) and [pytest monkeypatch guidance](https://docs.pytest.org/en/stable/how-to/monkeypatch.html): scoped, automatically restored patches; no real provider request. Tests use the repository's existing unittest runner. |
| Streamlit UI | [AppTest](https://docs.streamlit.io/develop/api-reference/app-testing/st.testing.v1.apptest): initialize the published entrypoint; explicitly rerun after widget changes; inspect errors, state, five page choices, replay, worker execution and session separation. AppTest is simulated UI evidence, not a browser screenshot or public cloud verification. |
| Linux CI | [GitHub Actions quickstart](https://docs.github.com/en/actions/get-started/quickstart): workflow in .github/workflows, checkout, Python 3.13, dependencies, safety scan, all regression checks, then entrypoint health. Permissions are contents: read. No API key secrets are requested. |
| Secret safety | [GitHub secret scanning](https://docs.github.com/en/code-security/secret-scanning/introduction/about-secret-scanning): keep platform protections enabled; add candidate and recursive ZIP/Office policy scans that only report paths and issue codes. Explicit placeholder tests distinguish examples from credentials. |
| Deployment | [Streamlit Community Cloud deployment](https://docs.streamlit.io/deploy/streamlit-community-cloud/deploy-your-app/deploy): existing repository, main, app.py and Python matching the tested environment; actual app interaction is required before claiming deployment. |

The relevant task instructions are the user's current G0-R1 request. Historical research freeze/no-push documents remain provenance records and do not prevent the newly authorized publication. The original research sources remain read-only.
