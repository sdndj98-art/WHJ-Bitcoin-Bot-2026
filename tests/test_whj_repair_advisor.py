import tempfile
import unittest
from pathlib import Path

from whj_repair_advisor import build_repair_plan, write_plan


class WHJRepairAdvisorTests(unittest.TestCase):
    def test_failed_paper_safety_is_highest_priority_and_never_edits(self):
        plan = build_repair_plan({
            "status": "NEEDS_ATTENTION",
            "agents": {"paper_safety_agent": {"status": "failed", "issues": ["live flag mismatch"]}},
        })
        self.assertEqual(plan["proposal_count"], 1)
        self.assertEqual(plan["proposals"][0]["priority"], "P0")
        self.assertFalse(plan["permissions"]["source_edits"])
        self.assertFalse(plan["permissions"]["pull_requests_created"])
        self.assertFalse(plan["permissions"]["live_trading"])

    def test_passed_report_creates_no_proposals(self):
        plan = build_repair_plan({"status": "HEALTHY", "agents": {"test_agent": {"status": "passed"}}})
        self.assertEqual(plan["proposal_count"], 0)

    def test_write_plan_outputs_json_and_markdown(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            report = root / "report.json"
            report.write_text(
                '{"status":"NEEDS_ATTENTION","generated_at_utc":"test",'
                '"agents":{"test_agent":{"status":"failed","output_tail":"AssertionError"}}}',
                encoding="utf-8",
            )
            plan = write_plan(report, root / "out")
            self.assertEqual(plan["proposal_count"], 1)
            self.assertTrue((root / "out" / "repair_proposals.json").is_file())
            self.assertIn("proposal only", (root / "out" / "repair_proposals.md").read_text(encoding="utf-8").lower())


if __name__ == "__main__":
    unittest.main()
