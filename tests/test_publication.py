"""Independent publication checks. No real key, provider traffic or rerating."""
from contextlib import ExitStack
import hashlib
import io
import json
import os
from pathlib import Path
import socket
import stat
import tempfile
import unittest
from unittest.mock import patch
import warnings
import zipfile

from scripts.security_scan import scan_bytes, scan_path

ROOT = Path(__file__).resolve().parents[1]


def make_zip(entries):
    buffer = io.BytesIO()
    with warnings.catch_warnings():
        warnings.simplefilter('ignore', UserWarning)
        with zipfile.ZipFile(buffer, 'w') as archive:
            for name, data in entries:
                archive.writestr(name, data)
    return buffer.getvalue()


class PublicationSecurityTests(unittest.TestCase):
    def test_no_secret_values_printed_or_reported(self):
        credential = 'gh' + 'p_' + 'A9' * 24
        payload = ('token = "' + credential + '"').encode()
        findings = scan_bytes('candidate.py', payload)
        self.assertIn('GITHUB_TOKEN', [f.code for f in findings])
        self.assertNotIn(credential, str(findings))

    def test_placeholder_configuration_is_allowed(self):
        payload = b'OPENAI_API_KEY="your_api_key_here"\npassword="synthetic_test_placeholder"\n'
        self.assertEqual(scan_bytes('.env.example', payload), [])

    def test_nested_archive_credential_and_font_blocked(self):
        credential = ('sk' + '-proj-' + 'B7' * 30).encode()
        nested = make_zip([('credentials.json', credential), ('font.otf', b'font')])
        found = scan_bytes('release.zip', make_zip([('nested.zip', nested)]))
        self.assertIn('PROVIDER_KEY', [f.code for f in found])
        self.assertIn('FONT_OR_AUTHENTICATION_OR_CACHE_FILE', [f.code for f in found])

    def test_archive_traversal_duplicates_and_symlinks_blocked(self):
        found = scan_bytes('release.zip', make_zip([('../escape.txt', b'x'), ('same.txt', b'a'), ('same.txt', b'b')]))
        self.assertIn('UNSAFE_ARCHIVE_PATH', [f.code for f in found])
        self.assertIn('DUPLICATE_ARCHIVE_PATH', [f.code for f in found])
        buffer = io.BytesIO()
        member = zipfile.ZipInfo('link')
        member.create_system = 3
        member.external_attr = (stat.S_IFLNK | 0o777) << 16
        with zipfile.ZipFile(buffer, 'w') as archive:
            archive.writestr(member, '../escape.txt')
        self.assertIn('ARCHIVE_SYMLINK', [f.code for f in scan_bytes('release.zip', buffer.getvalue())])

    def test_secret_cache_git_and_identity_paths_blocked(self):
        for name in ('.streamlit/secrets.toml', '.env', '.git/config', '.venv/lib/dependency.py', 'review/signature.png', 'font.ttf'):
            with self.subTest(name=name):
                self.assertTrue(scan_bytes(name, b'harmless'))

    def test_clean_archive_passes_crc_and_nested_policy(self):
        payload = make_zip([('data/README.md', b'Research data'), ('data/rows.json', b'[{"anonymous_id":"u1","value":0}]')])
        self.assertEqual(scan_bytes('research.zip', payload), [])


class HistoricalDataTests(unittest.TestCase):
    def test_all_246_conditions_keep_identity_and_answer_hash(self):
        rows = [json.loads(line) for line in (ROOT / 'data/replay/RESPONSE_HANDOFF.jsonl').read_text().splitlines() if line]
        tasks = [json.loads(line) for line in (ROOT / 'data/replay/final_tasks.jsonl').read_text().splitlines() if line]
        self.assertEqual(len(tasks), 41)
        self.assertEqual(len(rows), 246)
        self.assertEqual(len({(r['task_id'], r['mode']) for r in rows}), 246)
        self.assertEqual(len({r['answer'] for r in rows}), 179)
        for row in rows:
            self.assertEqual(hashlib.sha256(row['answer'].encode()).hexdigest(), row['answer_sha256'])
        modes = {r['mode'] for r in rows}
        self.assertEqual(len(modes), 6)
        for task in tasks:
            self.assertEqual({r['mode'] for r in rows if r['task_id'] == task['task_id']}, modes)

    def test_course_is_actual_624_chunks_and_has_no_evaluation_fields(self):
        rows = [json.loads(line) for line in (ROOT / 'data/course/corpus.jsonl').read_text().splitlines() if line]
        self.assertEqual(len(rows), 624)
        self.assertEqual(len({row['chunk_id'] for row in rows}), 624)
        forbidden = {'gold', 'gold_answer', 'ratings', 'rating', 'rubric', 'reference_answer', 'scores'}
        for row in rows:
            self.assertFalse(forbidden.intersection(row))
            self.assertTrue(row['text'])
            self.assertTrue(row['source_file'])


class NewStreamlitUITests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(prefix='lad-ui-publication-')
        self.addCleanup(self.tmp.cleanup)
        self.stack = ExitStack()
        self.addCleanup(self.stack.close)
        self.stack.enter_context(patch.dict(os.environ, {'LAD_SESSION_STORAGE': self.tmp.name, 'OPENAI_API_KEY': ''}))
        # Block actual provider networking in the UI/main process. Child core
        # imports its original no-network guard in its own process.
        for target in ('socket.socket.connect', 'socket.socket.connect_ex', 'socket.create_connection', 'socket.getaddrinfo'):
            self.stack.enter_context(patch(target, side_effect=AssertionError('Networking denied in publication UI tests')))
        from streamlit.testing.v1 import AppTest
        self.AppTest = AppTest

    def app(self):
        app = self.AppTest.from_file(str(ROOT / 'app.py'), default_timeout=120).run()
        self.assertEqual(len(app.exception), 0)
        self.assertEqual(len(app.error), 0)
        return app

    @staticmethod
    def labeled(elements, label):
        return next(element for element in elements if element.label == label)

    def test_five_pages_and_historical_replay(self):
        app = self.app()
        for page in ('Overview', 'Resources', 'Lecture', 'Debate', 'Reflection'):
            self.labeled(app.radio, '学习页面').set_value(page).run()
            self.assertEqual(len(app.exception), 0, page)
            self.assertEqual(len(app.error), 0, page)
        self.labeled(app.button, '回放保存回答').click().run()
        self.assertEqual(len(app.exception), 0)
        result = app.session_state.last_result
        self.assertEqual(result['runtime_profile'], 'REPLAY')
        self.assertEqual(result['generation'], 'SAVED_HISTORICAL_ANSWER_NO_NEW_MODEL_CALL')
        self.assertTrue(result['answer'])

    def test_local_components_execute_full_worker_and_single_gate(self):
        app = self.app()
        self.labeled(app.selectbox, '运行 profile').set_value('COMPONENTS').run()
        self.labeled(app.button, '执行本地组件').click().run()
        self.assertEqual(len(app.exception), 0)
        self.assertEqual(len(app.error), 0)
        result = app.session_state.last_result
        self.assertEqual(result['runtime_profile'], 'COMPONENTS')
        self.assertEqual(result['generation'], 'NO_LLM_NO_NATURAL_ANSWER_GENERATION')
        self.assertEqual(result['rag_calls'], 1)
        self.assertEqual(result['memory_calls'], 1)
        self.assertEqual(result['route']['provider_identity'], 'PUBLIC_EXPLICIT_COMPONENT_GATE_NO_P3')

    def test_two_sessions_isolate_visitor_key_history_and_writable_database(self):
        app = self.app()
        self.labeled(app.selectbox, '运行 profile').set_value('LIVE').run()
        self.labeled(app.text_input, '访客 OpenAI API Key').set_value('synthetic_visitor_only').run()
        first = app.session_state.engine
        self.assertEqual(first._api_key, 'synthetic_visitor_only')
        self.labeled(app.text_area, '你明确声明的内容').set_value('My learning goal is understanding analytics.')
        self.labeled(app.checkbox, '同意在当前session保存这条学习信息').set_value(True)
        self.labeled(app.button, '保存原生Memory').click().run()
        self.assertEqual(len(app.exception), 0)
        selected = first.active_task_id
        self.assertTrue(first.memory_list(selected))
        first.history.append({'role': 'user', 'content': 'session one only'})
        other_app = self.app()
        other = other_app.session_state.engine
        self.assertNotEqual(first.workspace, other.workspace)
        self.assertIsNone(other._api_key)
        self.assertEqual(other.history, [])
        self.assertEqual(other.memory_list(selected), [])
        self.assertEqual(os.environ.get('OPENAI_API_KEY'), '')
        for path in Path(self.tmp.name).rglob('*'):
            if path.is_file():
                self.assertNotIn(b'synthetic_visitor_only', path.read_bytes())

    def test_ui_to_full_core_with_exact_provider_mock(self):
        from public_runtime.core import PublicAssistant
        from test_runtime import ExactMock
        original = PublicAssistant.live
        transport = ExactMock(planning=True, memory=True)
        def mocked_live(engine, query, **kwargs):
            return original(engine, query, transport=transport, memory_backend='LEXICAL', **kwargs)
        with patch.object(PublicAssistant, 'live', mocked_live):
            app = self.app()
            self.labeled(app.selectbox, '运行 profile').set_value('LIVE').run()
            self.labeled(app.selectbox, '显式任务类型').set_value('ORDINARY_ACTION_ADVICE').run()
            self.labeled(app.text_area, '当前问题').set_value('Give me an action plan without dates to study learning analytics.').run()
            self.labeled(app.button, '实时发送到 OpenAI').click().run()
        self.assertEqual(len(app.exception), 0)
        self.assertEqual(len(app.error), 0)
        result = app.session_state.last_result
        self.assertEqual([r['role'] for r in result['provider_trace']], ['RAG', 'MEMORY', 'B4_PLANNING', 'CANDIDATE', 'FINAL'])
        self.assertEqual(result['generation'], 'MOCK_EXACT_CORE_NO_PAID_CALL')
        self.assertFalse(result['live_model_call'])
        self.assertEqual(len(app.session_state.engine.history), 2)

    def test_live_provider_error_does_not_expose_private_details(self):
        from public_runtime.core import PublicAssistant
        private_detail = 'synthetic_confidential_provider_detail'
        with patch.object(PublicAssistant, 'live', side_effect=RuntimeError(private_detail)):
            app = self.app()
            self.labeled(app.selectbox, '运行 profile').set_value('LIVE').run()
            self.labeled(app.button, '实时发送到 OpenAI').click().run()
        self.assertEqual(len(app.exception), 0)
        self.assertTrue(app.error)
        self.assertNotIn(private_detail, '\n'.join(element.value for element in app.error))


class SafeDownloaderTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(prefix='lad-download-fixture-', dir='/private/tmp' if Path('/private/tmp').exists() else None)
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        from scripts import download_research_data
        self.downloader = download_research_data

    def archive(self, payload):
        path = self.root / 'fixture.zip'
        path.write_bytes(payload)
        return path

    def test_extract_is_idempotent_and_never_overwrites_user_file(self):
        archive = self.archive(make_zip([('rows.json', b'{"value":0}'), ('docs/readme.txt', b'actual data')]))
        target = self.root / 'published'
        self.assertEqual(self.downloader.safe_extract(archive, target), {'written': 2, 'identical': 0})
        self.assertEqual(self.downloader.safe_extract(archive, target), {'written': 0, 'identical': 2})
        (target / 'rows.json').write_text('user modified')
        with self.assertRaises(FileExistsError):
            self.downloader.safe_extract(archive, target)
        self.assertEqual((target / 'rows.json').read_text(), 'user modified')

    def test_unsafe_archives_leave_destination_uncreated(self):
        for entries in ([('../outside.txt', b'x')], [('same.txt', b'a'), ('same.txt', b'b')], [('Data.txt', b'a'), ('data.txt', b'b')]):
            with self.subTest(entries=[name for name, _ in entries]):
                target = self.root / 'uncreated'
                with self.assertRaises(ValueError):
                    self.downloader.safe_extract(self.archive(make_zip(entries)), target)
                self.assertFalse(target.exists())
        member = zipfile.ZipInfo('link')
        member.create_system = 3
        member.external_attr = (stat.S_IFLNK | 0o777) << 16
        with self.assertRaises(ValueError):
            self.downloader.safe_extract(self.archive(make_zip([(member, '../outside')])), self.root / 'linked')

    def test_existing_symlink_is_rejected(self):
        archive = self.archive(make_zip([('rows.txt', b'data')]))
        outside = self.root / 'outside'
        outside.mkdir()
        link = self.root / 'link'
        link.symlink_to(outside, target_is_directory=True)
        with self.assertRaises(ValueError):
            self.downloader.safe_extract(archive, link)
        self.assertEqual(list(outside.iterdir()), [])

    def test_member_total_and_count_limits(self):
        archive = self.archive(make_zip([('one.txt', b'1234'), ('two.txt', b'5678')]))
        for setting, limit in [('MAX_MEMBER_BYTES', 3), ('MAX_TOTAL_BYTES', 7), ('MAX_MEMBERS', 1)]:
            with self.subTest(setting=setting), patch.object(self.downloader, setting, limit):
                with self.assertRaises(ValueError):
                    self.downloader.safe_extract(archive, self.root / setting)
                self.assertFalse((self.root / setting).exists())

    def test_manifest_hash_mismatch_is_rejected_before_publication(self):
        manifest = {'files': [{'destination': 'rows.txt', 'published_sha256': '0' * 64}]}
        archive = self.archive(make_zip([('rows.txt', b'actual'), ('PUBLIC_FILE_MANIFEST.json', json.dumps(manifest))]))
        target = self.root / 'mismatch'
        with self.assertRaisesRegex(ValueError, 'per-file hash'):
            self.downloader.safe_extract(archive, target)
        self.assertFalse(target.exists())

    def response(self, payload, *, redirected='https://example.org/research.zip', announced=None):
        class Response(io.BytesIO):
            headers = {'Content-Length': str(announced if announced is not None else len(payload))}
            def geturl(self):
                return redirected
        return Response(payload)

    def test_download_checks_full_sha_size_and_https_redirect(self):
        payload = make_zip([('rows.txt', b'actual')])
        url = 'https://example.org/research.zip'
        target = self.root / 'downloaded'
        with patch.object(self.downloader.urllib.request, 'urlopen', return_value=self.response(payload)):
            result = self.downloader.download(url, hashlib.sha256(payload).hexdigest(), target)
        self.assertEqual(result['written'], 1)
        for digest, response in [('0' * 64, self.response(payload)), (hashlib.sha256(payload).hexdigest(), self.response(payload, redirected='http://example.org/data.zip')), (hashlib.sha256(payload).hexdigest(), self.response(payload, announced=self.downloader.MAX_ARCHIVE_BYTES + 1))]:
            with patch.object(self.downloader.urllib.request, 'urlopen', return_value=response):
                with self.assertRaises(ValueError):
                    self.downloader.download(url, digest, self.root / 'rejected')
            self.assertFalse((self.root / 'rejected').exists())
        for invalid_url, digest in [('http://example.org/data.zip', '0' * 64), (url, 'abc')]:
            with patch.object(self.downloader.urllib.request, 'urlopen') as fetch:
                with self.assertRaises(ValueError):
                    self.downloader.download(invalid_url, digest, self.root / 'bad')
                fetch.assert_not_called()


if __name__ == '__main__':
    unittest.main()
