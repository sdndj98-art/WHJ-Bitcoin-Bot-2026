import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from office.ai_code_agent import parse_requested_files


class AICodeAgentAllowlistTests(unittest.TestCase):
    def test_accepts_existing_allowlisted_source(self):
        self.assertEqual(
            parse_requested_files("Task details\nFiles: whj_24h_development_team.py"),
            ["whj_24h_development_team.py"],
        )

    def test_rejects_workflow_path(self):
        with self.assertRaises(ValueError):
            parse_requested_files("Task\nFiles: .github/workflows/whj-ai-code-agent.yml")

    def test_rejects_path_traversal(self):
        with self.assertRaises(ValueError):
            parse_requested_files("Task\nFiles: ../README.md")

    def test_rejects_too_many_files(self):
        with self.assertRaises(ValueError):
            parse_requested_files(
                "Task\nFiles: whj_24h_development_team.py, "
                "strategy_lab.py, tests/test_main.py, tests/test_dashboard_contract.py"
            )

    def test_rejects_missing_file(self):
        with self.assertRaises(ValueError):
            parse_requested_files("Task\nFiles: whj_nonexistent_file.py")


if __name__ == "__main__":
    unittest.main()
