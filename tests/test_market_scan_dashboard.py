import unittest
from pathlib import Path


class MultiMarketDashboardTests(unittest.TestCase):
    def test_published_dashboard_surfaces_read_only_scan_report(self):
        index = Path("index.html").read_text(encoding="utf-8")
        dual = Path("dual_portfolio_dashboard.html").read_text(encoding="utf-8")
        for source in (index, dual):
            for element_id in (
                "market-scan-panel", "market-scan-status",
                "market-scan-discovered", "market-scan-scanned",
                "market-scan-success", "market-scan-opportunities-count",
                "market-scan-opportunities", "market-scan-errors",
            ):
                self.assertIn('id="' + element_id + '"', source)
            self.assertIn("fetch('./research/multi_market_scan/latest.json'", source)
            self.assertIn("await refreshMarketScan();", source)
            self.assertIn("cell.textContent = String(value);", source)
            self.assertIn("المحافظ الورقية: دون تغيير", source)
        self.assertEqual(index, dual)

    def test_pages_workflow_copies_latest_scan_report_when_available(self):
        workflow = Path(".github/workflows/btc-10usd-paper.yml").read_text(encoding="utf-8")
        self.assertIn("research/multi_market_scan/latest.json", workflow)
        self.assertIn("_site/research/multi_market_scan/latest.json", workflow)

    def test_scan_workflow_publishes_report_without_live_execution(self):
        workflow = Path(".github/workflows/whj-multi-market-scan.yml").read_text(encoding="utf-8")
        self.assertIn("contents: write", workflow)
        self.assertIn("git push origin HEAD:main", workflow)
        self.assertIn("python multi_market_opportunity_scan.py", workflow)
        self.assertNotIn("live trading", workflow.lower())


if __name__ == "__main__":
    unittest.main()
