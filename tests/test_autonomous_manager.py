import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from office.autonomous_manager import select_next_task


class AutonomousManagerSelectionTests(unittest.TestCase):
    def setUp(self):
        self.tasks = [
            {"id": "first", "title": "First"},
            {"id": "second", "title": "Second"},
        ]

    def test_selects_first_unattempted_task(self):
        selected = select_next_task(self.tasks, [], set())
        self.assertEqual(selected["id"], "first")
        self.assertEqual(selected["branch"], "ai-office/auto-first")

    def test_does_not_start_when_an_ai_pr_is_open(self):
        prs = [{"headRefName": "ai-office/auto-first", "state": "OPEN", "mergedAt": None}]
        self.assertIsNone(select_next_task(self.tasks, prs, set()))

    def test_skips_merged_task_and_selects_next(self):
        prs = [{"headRefName": "ai-office/auto-first", "state": "CLOSED",
                "mergedAt": "2026-11-22T00:00:00Z"}]
        selected = select_next_task(self.tasks, prs, set())
        self.assertEqual(selected["id"], "second")

    def test_does_not_overwrite_existing_unmerged_branch(self):
        selected = select_next_task(self.tasks, [], {"ai-office/auto-first"})
        self.assertEqual(selected["id"], "second")

    def test_skips_task_blocked_after_retry_limit(self):
        selected = select_next_task(
            self.tasks, [], set(), {"First"}
        )
        self.assertEqual(selected["id"], "second")

    def test_skips_closed_unmerged_attempt(self):
        prs = [{"headRefName": "ai-office/auto-first", "state": "CLOSED", "mergedAt": None}]
        selected = select_next_task(self.tasks, prs, set())
        self.assertEqual(selected["id"], "second")


if __name__ == "__main__":
    unittest.main()
