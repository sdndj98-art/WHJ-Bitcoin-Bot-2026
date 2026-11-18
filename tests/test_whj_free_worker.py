import tempfile
import unittest
from pathlib import Path

from whj_free_worker import build_free_report, inspect_file, write_report


class WHJFreeWorkerTests(unittest.TestCase):
    def test_free_report_has_all_24_roles_and_zero_cost(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "strategy_family_lab.py").write_text("def signal():\n    return 'HOLD'\n", encoding="utf-8")
            (root / "gold_market_data.py").write_text("# GC=F source adapter\n", encoding="utf-8")
            result = build_free_report(root)
        self.assertEqual(result["task_count"], 24)
        self.assertEqual(result["provider"], "none")
        self.assertEqual(result["provider_calls"], 0)
        self.assertEqual(result["cost_usd"], 0.0)
        self.assertEqual(result["executed_research_tasks"], 0)
        self.assertEqual(result["plan_only_tasks"], 24)
        self.assertTrue(all(row["execution_status"] == "not_executed_plan_only" for row in result["reports"]))
        self.assertGreater(result["deterministic_checks_executed"], 0)
        self.assertEqual(result["deterministic_checks_failed"], 0)
        self.assertEqual(
            result["deterministic_checks_executed"],
            sum(row["deterministic_checks_executed"] for row in result["reports"]),
        )
        self.assertTrue(all("deterministic_checks" in row for row in result["reports"]))
        self.assertFalse(result["live_trading_enabled"])
        self.assertFalse(result["repository_writes_enabled"])
        self.assertEqual(len({row["owner_role"] for row in result["reports"]}), 24)

    def test_inventory_uses_sha256_and_python_ast(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "sample.py").write_text("x = 1\n", encoding="utf-8")
            item = inspect_file(root, "sample.py")
        self.assertEqual(len(item["sha256"]), 64)
        self.assertTrue(item["python_ast_valid"])
        self.assertEqual(item["bytes"], 6)

    def test_invalid_python_is_flagged_not_executed(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "bad.py").write_text("def broken(:\n", encoding="utf-8")
            item = inspect_file(root, "bad.py")
        self.assertFalse(item["python_ast_valid"])
        self.assertIn("syntax_error", item)

    def test_write_report_renders_ast_and_check_evidence(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "strategy_family_lab.py").write_text("def signal():\n    return 'HOLD'\n", encoding="utf-8")
            output = root / "out"
            result = write_report(root, output)
            markdown = (output / "latest_free_worker_results.md").read_text(encoding="utf-8")
            self.assertGreater(result["deterministic_checks_passed"], 0)
            self.assertIn("python_ast_syntax", markdown)
            self.assertIn("Python AST valid: True", markdown)
            self.assertTrue((output / "latest_free_worker_results.json").is_file())

    def test_path_traversal_is_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            item = inspect_file(root, "../outside.py")
        self.assertIsNone(item)

    def test_missing_sources_are_reported_as_blocked_or_missing(self):
        with tempfile.TemporaryDirectory() as directory:
            result = build_free_report(Path(directory))
        self.assertGreater(result["blocked_tasks"], 0)
        self.assertTrue(all(row["semantic_review_required"] for row in result["reports"]))


if __name__ == "__main__":
    unittest.main()
