import tempfile
import unittest
from pathlib import Path

from whj_repair_advisor import build_repair_plan, write_plan, redact_secrets, sanitize_error_excerpt


class WHJRepairAdvisorTests(unittest.TestCase):
    def test_failed_paper_safety_is_highest_priority_and_never_edits(self):
        plan = build_repair_plan({
            "status": "NEEDS_ATTENTION",
            "agents": {"paper_safety_agent": {"status": "failed", "issues": ["live flag mismatch"], "retry_count": 1}},
        })
        self.assertEqual(plan["proposal_count"], 1)
        proposal = plan["proposals"][0]
        self.assertEqual(proposal["priority"], "P0")
        self.assertEqual(proposal["source_file"], "whj_risk_guard.py")
        self.assertEqual(proposal["regression_test"], "test_paper_safety.py")
        self.assertEqual(proposal["retry_count"], 1)
        self.assertIn("STOP", proposal["recommended_action"])
        self.assertFalse(plan["permissions"]["source_edits"])
        self.assertFalse(plan["permissions"]["pull_requests_created"])
        self.assertFalse(plan["permissions"]["live_trading"])

    def test_passed_report_creates_no_proposals(self):
        plan = build_repair_plan({"status": "HEALTHY", "agents": {"test_agent": {"status": "passed"}}})
        self.assertEqual(plan["proposal_count"], 0)

    def test_unknown_failure_type_uses_fallback_mapping(self):
        plan = build_repair_plan({
            "status": "NEEDS_ATTENTION",
            "agents": {"completely_unknown_agent": {"status": "failed", "error": "mystery failure"}},
        })
        self.assertEqual(plan["proposal_count"], 1)
        proposal = plan["proposals"][0]
        self.assertEqual(proposal["agent"], "completely_unknown_agent")
        self.assertEqual(proposal[
            "source_file"
        ], "whj_unknown_module.py")
        self.assertEqual(proposal["regression_test"], "test_unknown.py")
        self.assertEqual(proposal["priority"], "P2")

    def test_secret_and_token_redaction(self):
        sensitive_text = "Error with api_key=secret_12345678 and bearer token abcdefghijklmnopqrstuvwxyz and token: secret_token_99"
        redacted = redact_secrets(sensitive_text)
        self.assertNotIn("secret_12345678", redacted)
        self.assertNotIn("abcdefghijklmnopqrstuvwxyz", redacted)
        self.assertNotIn("secret_token_99", redacted)
        self.assertIn("[REDACTED_SECRET]", redacted)

    def test_log_truncation(self):
        long_log = "\n".join([f"line {i}" for i in range(50)])
        evidence = {"error": long_log}
        excerpt = sanitize_error_excerpt(evidence)
        lines = excerpt.strip().splitlines()
        self.assertLessEqual(len(lines), 20)

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
