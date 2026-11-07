import json
import unittest
from io import BytesIO
from unittest.mock import patch

import main
from dashboard import build_dashboard
from notify_telegram import format_message
from paper_trading import run_backtest
from strategy_lab import run_strategy_lab


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
        with self.assertRaises(ValueError):
            main.analyze([100.0] * 50)

    def test_rejects_non_positive_prices(self):
        with self.assertRaises(ValueError):
            main.analyze([100.0] * 50 + [0.0])

    def test_rejects_non_finite_or_boolean_prices(self):
        with self.assertRaises(ValueError):
            main.analyze([100.0] * 50 + [float("nan")])
        with self.assertRaises(ValueError):
            main.analyze([100.0] * 50 + [True])

    @patch("main.urllib.request.urlopen")
    def test_fetch_excludes_current_incomplete_candle(self, mocked_open):
        candles = [[i, "1", "1", "1", str(100 + i), "1", "1", 1] for i in range(52)]
        payload = {"error": [], "result": {"XXBTZUSD": candles, "last": "123"}}
        mocked_open.return_value.__enter__.return_value = BytesIO(
            json.dumps(payload).encode("utf-8")
        )
        closes = main.fetch_closes()
        self.assertEqual(len(closes), 51)
        self.assertEqual(closes[-1], 150.0)

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
        self.assertEqual(result["max_drawdown_pct"], 0.0)
        self.assertEqual(result["profit_factor"], 0.0)

    def test_rejects_short_history(self):
        with self.assertRaises(ValueError):
            run_backtest([100.0] * 50)

    def test_rejects_invalid_fee(self):
        with self.assertRaises(ValueError):
            run_backtest([100.0] * 51, fee_rate=1.0)

    def test_rejects_non_finite_prices(self):
        with self.assertRaises(ValueError):
            run_backtest([100.0] * 50 + [float("nan")])

    def test_signal_does_not_use_execution_candle_close(self):
        result = run_backtest([100.0] * 50 + [200.0])
        self.assertEqual(result["completed_trades"], 0)
        self.assertFalse(result["open_position"])
        self.assertEqual(result["final_equity_usd"], 1000.0)

    def test_returns_risk_and_trade_quality_metrics(self):
        result = run_backtest([float(i) for i in range(1, 101)])
        self.assertIn("max_drawdown_pct", result)
        self.assertIn("average_trade_pnl_usd", result)
        self.assertIn("profit_factor", result)
        self.assertIn("max_consecutive_losses", result)

    def test_strategy_lab_reports_chronological_holdout_and_benchmark(self):
        prices = [100 + i * 0.1 + (i % 9) for i in range(180)]
        result = run_strategy_lab(prices)
        self.assertEqual(result["mode"], "FIXED_RULE_CHRONOLOGICAL_HOLDOUT")
        self.assertIn("buy_and_hold", result["strategies"])
        self.assertIn("out_of_sample", result["strategies"]["ema_trend"])

    def test_strategy_lab_rejects_short_or_invalid_data(self):
        with self.assertRaises(ValueError):
            run_strategy_lab([100.0] * 119)
        with self.assertRaises(ValueError):
            run_strategy_lab([100.0] * 119 + [float("nan")])


class ReportingTests(unittest.TestCase):
    def sample_report(self):
        return {
            "time": "2026-11-07T00:00:00Z", "market": "BTC/USD",
            "BTC_price": 65000, "signal": "HOLD", "SMA20": 64000, "SMA50": 63000,
            "paper_backtest": {
                "final_equity_usd": 1010, "return_pct": 1.0,
                "completed_trades": 1, "win_rate_pct": 100,
                "fees_paid_usd": 2, "max_drawdown_pct": 3.2,
                "average_trade_pnl_usd": 10, "profit_factor": None,
                "max_consecutive_losses": 0,
                "trade_log": [{"result": "WIN", "pnl": 10}]
            }
        }

    def test_dashboard_contains_report_metrics_and_escapes_html(self):
        report = self.sample_report()
        report["signal"] = "<script>alert(1)</script>"
        page = build_dashboard(report)
        self.assertIn("BTC/USD", page)
        self.assertIn("1010", page)
        self.assertIn("Max drawdown (%)", page)
        self.assertNotIn("<script>alert(1)</script>", page)

    def test_telegram_message_contains_signal_and_paper_equity(self):
        message = format_message(self.sample_report())
        self.assertIn("Signal: HOLD", message)
        self.assertIn("Paper equity: 1010 USD", message)
        self.assertIn("no real orders", message.lower())


if __name__ == "__main__":
    unittest.main()
