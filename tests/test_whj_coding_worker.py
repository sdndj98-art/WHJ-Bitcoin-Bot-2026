import unittest

from whj_coding_worker import allowed_path, extract_patch


class CodingWorkerGuardTests(unittest.TestCase):
    def test_allows_isolated_research_and_test_paths(self):
        self.assertTrue(allowed_path("research/new_audit.md"))
        self.assertTrue(allowed_path("tests/test_new_lab.py"))
        self.assertTrue(allowed_path("strategy_family_lab.py"))

    def test_blocks_trading_dashboard_state_and_workflows(self):
        for path in (
            "index.html", "dual_portfolio.json", "broker.py",
            "research_runs/run.py", ".github/workflows/worker.yml",
            "state/portfolio.json", "../outside.py",
        ):
            with self.subTest(path=path):
                self.assertFalse(allowed_path(path))

    def test_rejects_patch_with_unsafe_path(self):
        patch = "--- a/index.html\n+++ b/index.html\n@@ -1 +1 @@\n-old\n+new\n"
        with self.assertRaises(ValueError):
            extract_patch('{"patch": ' + __import__("json").dumps(patch) + "}")

    def test_accepts_small_safe_patch(self):
        patch = "--- a/research/example.md\n+++ b/research/example.md\n@@ -1 +1 @@\n-old\n+new\n"
        result = extract_patch('{"patch": ' + __import__("json").dumps(patch) + "}")
        self.assertIn("research/example.md", result)


if __name__ == "__main__":
    unittest.main()
