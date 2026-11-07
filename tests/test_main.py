import json
import unittest
from io import BytesIO
from unittest.mock import patch

import main
from paper_trading import run_backtest


class AnalysisTests(unittest.TestCase):
    def test_buy_signal_for_strong_uptrend(self):
        result = main.analyze(list(range(1, 101)))
        self.assertEqual(result["signal"], "BUY")
        self.assertEqual(result["mode"], "ANALYSIS_AND_HISTORICAL_PAPER_ONLY")
        self.assertIn("paper_backtest", result)

    def test_sell_signal_for_downtrend(self):
        result = main.analyze(list(range(100, 0, -1)))
        self.assertEqual(result["signal"], "SELL")

    def test_hold_signal_for_flat_market(self):
        result = main.analyze([100.0] * 100)
        self.assertEqual(result["signal"], "HOLD")

    def test_rejects_too_few_prices(self):
        with self.assertRaises(ValueError):
            main.analyze([100.0] * 49)

    def test_rejects_non_positive_prices(self):
        with self.assertRaises(ValueError):
            main.analyze([100.0] * 49 + [0.0])

    @patch("main.urllib.request.urlopen")
    def test_fetch_excludes_current_incomplete_candle(self, mocked_open):
        candles = [[i, "1", "1", "1", str(100 + i), "1", "1", 1] for i in range(51)]
        payload = {"error": [], "result": {"XXBTZUSD": candles, "last": "123"}}
        mocked_open.return_value.__enter__.return_value = BytesIO(
            json.dumps(payload).encode("utf-8")
        )
        closes = main.fetch_closes()
        self.assertEqual(len(closes), 50)
        self.assertEqual(closes[-1], 149.0)

    @patch("main.urllib.request.urlopen")
    def test_fetch_raises_on_exchange_error(self, mocked_open):
        payload = {"error": ["EGeneral: temporary failure"], "result": {}}
        mocked_open.return_value.__enter__.return_value = BytesIO(
            json.dumps(payload).encode("utf-8")
        )
        with self.assertRaises(RuntimeError):
            main.fetch_closes()


class PaperTradingTests(unittest.TestCase):
    def test_flat_series_keeps_cash_and_places_no_trades(self):
        result = run_backtest([100.0] * 100)
        self.assertEqual(result["final_equity_usd"], 1000.0)
        self.assertEqual(result["completed_trades"], 0)
        self.assertFalse(result["open_position"])

    def test_rejects_short_history(self):
        with self.assertRaises(ValueError):
            run_backtest([100.0] * 50)

    def test_rejects_invalid_fee(self):
        with self.assertRaises(ValueError):
            run_backtest([100.0] * 51, fee_rate=1.0)


if __name__ == "__main__":
    unittest.main()
