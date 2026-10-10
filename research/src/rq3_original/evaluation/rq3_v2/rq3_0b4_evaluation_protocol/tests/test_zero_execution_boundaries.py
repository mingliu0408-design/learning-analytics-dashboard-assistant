from __future__ import annotations

import ast
from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parents[1]


class ZeroExecutionBoundaryTests(unittest.TestCase):
    def test_python_has_no_provider_or_network_client_imports(self) -> None:
        forbidden = {"openai", "anthropic", "requests", "httpx", "aiohttp", "urllib3"}
        imports = set()
        for path in ROOT.glob("*.py"):
            tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
            for node in ast.walk(tree):
                if isinstance(node, ast.Import):
                    imports.update(alias.name.split(".")[0] for alias in node.names)
                elif isinstance(node, ast.ImportFrom) and node.module:
                    imports.add(node.module.split(".")[0])
        self.assertFalse(imports & forbidden)

    def test_python_has_no_process_socket_or_url_execution(self) -> None:
        forbidden_imports = {"subprocess", "socket", "urllib", "http", "ftplib"}
        imports = set()
        for path in ROOT.glob("*.py"):
            tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
            for node in ast.walk(tree):
                if isinstance(node, ast.Import):
                    imports.update(alias.name.split(".")[0] for alias in node.names)
                elif isinstance(node, ast.ImportFrom) and node.module:
                    imports.add(node.module.split(".")[0])
        self.assertFalse(imports & forbidden_imports)

    def test_no_actual_packet_or_rating_data_files_exist(self) -> None:
        forbidden_suffixes = {".csv", ".tsv", ".xlsx", ".xls", ".jsonl"}
        actual = [path for path in ROOT.rglob("*") if path.is_file() and path.suffix in forbidden_suffixes]
        self.assertEqual(actual, [])

    def test_no_response_or_provider_output_directories_exist(self) -> None:
        forbidden_names = {"live_outputs", "provider_outputs", "responses", "actual_packets", "ratings"}
        actual = [path.name for path in ROOT.rglob("*") if path.is_dir() and path.name in forbidden_names]
        self.assertEqual(actual, [])

    def test_status_records_every_zero_action_boundary(self) -> None:
        status = (ROOT / "STATUS.md").read_text(encoding="utf-8")
        for phrase in (
            "zero student-facing response generations",
            "zero LLM judge calls",
            "zero provider calls",
            "zero human ratings",
            "zero actual human packets",
            "zero real RQ3 response reads or scores",
            "zero RQ2 modifications",
            "zero RQ3 asset or adapter modifications",
        ):
            self.assertIn(phrase, status)

    def test_method_explicitly_blocks_real_evaluation(self) -> None:
        method = (ROOT / "RQ3_EVALUATION_METHOD.md").read_text(encoding="utf-8")
        self.assertIn("authorizes no response generation", method)
        self.assertIn("Real evaluation remains blocked", method)
        self.assertIn("creates no real key, mapping, ID, order, judge packet, or human packet", method)

    def test_existing_rq3_0a_assets_are_not_copied_into_new_package(self) -> None:
        names = {path.name for path in ROOT.iterdir() if path.is_file()}
        self.assertNotIn("condition_builder.py", names)
        self.assertNotIn("rq3_toy_condition_manifest_v1.jsonl", names)
        self.assertNotIn("rq3_experiment_contract_draft_v1.yaml", names)


if __name__ == "__main__":
    unittest.main()
