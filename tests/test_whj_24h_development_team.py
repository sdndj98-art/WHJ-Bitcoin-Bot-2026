import json
import tempfile
import unittest
from pathlib import Path

from whj_24h_development_team import audit_hourly_schedule, audit_portfolio, file_fingerprint


class WHJDevelopmentCouncilTests(unittest.TestCase):
    def test_portfolio_requires_paper_only_and_live_disabled(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "dual_portfolio.json"
            snapshot = {
                "paper_only": True,
                "live_trading_enabled": False,
                "btc": {"paper_only": True},
                "gold": {"paper_only": True},
            }
            path.write_text(json.dumps(snapshot), encoding="utf-8")
            self.assertEqual(audit_portfolio(path)["status"], "passed")
            snapshot["live_trading_enabled"] = True
            path.write_text(json.dumps(snapshot), encoding="utf-8")
            self.assertEqual(audit_portfolio(path)["status"], "failed")

    def test_hourly_workflow_requires_hourly_cron_and_read_only_permission(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "workflow.yml"
            path.write_text('schedule:\n  - cron: "0 * * * *"\npermissions:\n  contents: read\n', encoding="utf-8")
            self.assertEqual(audit_hourly_schedule(path)["status"], "passed")
            path.write_text('schedule:\n  - cron: "0 0 * * *"\npermissions:\n  contents: write\n', encoding="utf-8")
            self.assertEqual(audit_hourly_schedule(path)["status"], "failed")

    def test_dashboard_fingerprint_is_sha256(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "index.html"
            path.write_text("<html></html>", encoding="utf-8")
            digest = file_fingerprint(path)
            self.assertEqual(len(digest), 64)
            self.assertIsNone(file_fingerprint(Path(directory) / "missing.html"))


if __name__ == "__main__":
    unittest.main()
