import unittest
from datetime import datetime, timezone

from strategy_opportunity_research import analyze_prices, normalize_gold_history, write_report


class StrategyOpportunityResearchTests(unittest.TestCase):
    def test_gold_history_rejects_insufficient_sample(self):
        payload = {
            "symbol": "XAUUSD",
            "interval": "1h",
            "bars": [{
                "openTime": datetime.fromtimestamp(3600, timezone.utc).isoformat(),
                "isOpen": False,
                "open": 2000, "high": 2002, "low": 1998, "close": 2001,
            }],
        }
        with self.assertRaises(ValueError):
            normalize_gold_history(payload)

    def test_analysis_is_research_only_and_does_not_enable_execution(self):
        prices = [
            100.0 + index * 0.15 + ((index % 17) - 8) * 0.7
            for index in range(900)
        ]
        result = analyze_prices("BTC", prices, "unit-test")
        self.assertTrue(result["research_only"])
        self.assertTrue(result["paper_only"])
        self.assertFalse(result["live_trading_enabled"])
        self.assertFalse(result["execution_enabled"])
        self.assertFalse(result["production_strategy_changed"])
        self.assertFalse(result["paper_ledger_modified"])
        self.assertEqual(result["sample_count"], 900)

    def test_report_writer_creates_json_and_markdown(self):
        import tempfile
        from pathlib import Path
        report = {
            "generated_at_utc": "2026-11-18T00:00:00+00:00",
            "status": "NO_VALID_MARKET_DATA",
            "assets": {},
            "data_errors": {"BTC": "no test data"},
        }
        with tempfile.TemporaryDirectory() as directory:
            write_report(report, directory)
            self.assertTrue((Path(directory) / "latest_report.json").exists())
            self.assertTrue((Path(directory) / "latest_report.md").exists())


if __name__ == "__main__":
    unittest.main()
