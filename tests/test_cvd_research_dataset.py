import os
import tempfile
import unittest

from cvd_research_dataset import build_research_report
from trade_journal_checkpoint import build_continuity_checkpoint


class CvdResearchDatasetTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.journal_path = os.path.join(self.temp.name, "trades.jsonl")
        self.candles = []
        self.trades = []
        lines = []
        for index in range(500):
            start = index * 3600
            open_price = 100.0 + index
            close = open_price + 1.0
            self.candles.append([
                start, open_price, close + 1, open_price - 1,
                close, close, 2.0, 1,
            ])
            event = {
                "trade_id": index + 1,
                "timestamp": start + 3599,
                "price": close,
                "qty": 1.0,
                "side": "buy",
                "symbol": "BTC/USD",
            }
            self.trades.append(event)
            lines.append(
                '{"trade_id":%d,"timestamp":%d,"price":%.1f,"qty":1.0,"side":"buy","symbol":"BTC/USD"}\n'
                % (index + 1, start + 3599, close)
            )
        with open(self.journal_path, "w", encoding="utf-8") as handle:
            handle.writelines(lines)
        self.checkpoint = build_continuity_checkpoint(
            self.journal_path, "BTC/USD", 500
        )
        self.as_of = 500 * 3600

    def test_builds_report_only_from_checkpointed_completed_data(self):
        report = build_research_report(
            self.candles, self.trades, self.checkpoint,
            self.journal_path, "BTC/USD", self.as_of,
        )
        self.assertTrue(report["dataset"]["journal_continuity_checkpoint_validated"])
        self.assertEqual(report["dataset"]["available_cvd_bars"], 500)
        self.assertTrue(report["research_only"])
        self.assertFalse(report["execution_enabled"])
        self.assertEqual(report["promotion_status"], "NOT_EVALUATED")

    def test_rejects_trade_events_not_from_checkpointed_journal(self):
        altered = list(self.trades)
        altered[0] = dict(altered[0], qty=99.0)
        with self.assertRaisesRegex(ValueError, "exact checkpointed journal"):
            build_research_report(
                self.candles, altered, self.checkpoint,
                self.journal_path, "BTC/USD", self.as_of,
            )

    def test_rejects_incomplete_final_candle(self):
        with self.assertRaisesRegex(ValueError, "last candle is not completed"):
            build_research_report(
                self.candles, self.trades, self.checkpoint,
                self.journal_path, "BTC/USD", self.as_of - 1,
            )

    def test_rejects_non_finite_as_of_timestamp(self):
        with self.assertRaisesRegex(ValueError, "finite non-negative"):
            build_research_report(
                self.candles, self.trades, self.checkpoint,
                self.journal_path, "BTC/USD", float("nan"),
            )

    def test_rejects_modified_journal_checkpoint(self):
        with open(self.journal_path, "a", encoding="utf-8") as handle:
            handle.write("{}\n")
        with self.assertRaisesRegex(ValueError, "does not match journal"):
            build_research_report(
                self.candles, self.trades, self.checkpoint,
                self.journal_path, "BTC/USD", self.as_of,
            )


if __name__ == "__main__":
    unittest.main()
