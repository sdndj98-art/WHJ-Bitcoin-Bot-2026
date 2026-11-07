import json
import unittest
from io import BytesIO
from unittest.mock import patch

import main
from dashboard import build_dashboard
from notify_telegram import format_message
from paper_trading import run_backtest
from paper_account import run_paper_portfolio
from strategy_lab import run_strategy_lab


class PortfolioHealthGuardTests(unittest.TestCase):
    @patch("paper_account.update_paper_account")
    def test_all_legacy_paper_sleeves_enable_rolling_health_pause(self, mocked_update):
        mocked_update.return_value = {"mode": "PERSISTENT_PAPER_ONLY"}
        result = run_paper_portfolio([[1_750_000_000, 0, 0, 0, "100"]])
        self.assertEqual(len(result["accounts"]), 5)
        self.assertEqual(mocked_update.call_count, 5)
        for call in mocked_update.call_args_list:
            self.assertIs(call.kwargs["strategy_health_pause"], True)
            self.assertEqual(call.kwargs["strategy_health_drawdown_fraction"], 0.08)


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

    def test_candle_quality_blocks_recent_gaps_and_stale_data(self):
        candles = [[i * 3600, "1", "1", "1", "100", "1", "1", 1] for i in range(60)]
        now = candles[-1][0] + 3600 + 300
        self.assertTrue(main.assess_candle_quality(candles, now)["paper_execution_allowed"])
        recent_gap = [row[:] for row in candles]
        for i in range(30, len(recent_gap)):
            recent_gap[i][0] += 3600
        quality = main.assess_candle_quality(recent_gap, now + 3600)
        self.assertFalse(quality["paper_execution_allowed"])
        stale = main.assess_candle_quality(candles, now + 3 * 3600)
        self.assertFalse(stale["paper_execution_allowed"])

    @patch("main.urllib.request.urlopen")
    def test_fetch_excludes_current_incomplete_candle(self, mocked_open):
        candles = [[i * 3600, str(100 + i), str(102 + i), str(99 + i), str(100 + i), "100", "1", 1]
                   for i in range(52)]
        payload = {"error": [], "result": {"XXBTZUSD": candles, "last": "123"}}
        mocked_open.return_value.__enter__.return_value = BytesIO(
            json.dumps(payload).encode("utf-8")
        )
        closes = main.fetch_closes()
        self.assertEqual(len(closes), 51)
        self.assertEqual(closes[-1], 150.0)

    @patch("main.urllib.request.urlopen")
    def test_fetch_rejects_inconsistent_ohlc(self, mocked_open):
        candles = [[i * 3600, "100", "99", "98", "101", "100", "1", 1]
                   for i in range(52)]
        payload = {"error": [], "result": {"XXBTZUSD": candles, "last": "123"}}
        mocked_open.return_value.__enter__.return_value = BytesIO(
            json.dumps(payload).encode("utf-8")
        )
        with self.assertRaises(ValueError):
            main.fetch_closed_candles()

    @patch("main.urllib.request.urlopen")
    def test_fetch_rejects_fractional_trade_count_and_boolean_ohlcv(self, mocked_open):
        valid = [[i * 3600, "100", "102", "99", "101", "100", "1", 1]
                 for i in range(52)]
        for label, mutation in (
            ("fractional_trade_count", lambda rows: rows[0].__setitem__(7, 1.5)),
            ("boolean_timestamp", lambda rows: rows[0].__setitem__(0, True)),
            ("boolean_price", lambda rows: rows[0].__setitem__(1, True)),
            ("boolean_volume", lambda rows: rows[0].__setitem__(6, True)),
        ):
            rows = json.loads(json.dumps(valid))
            mutation(rows)
            payload = {"error": [], "result": {"XXBTZUSD": rows, "last": "123"}}
            mocked_open.return_value.__enter__.return_value = BytesIO(
                json.dumps(payload).encode("utf-8")
            )
            with self.subTest(case=label):
                with self.assertRaises(ValueError):
                    main.fetch_closed_candles()

    def test_quality_rejects_boolean_timestamps(self):
        candles = [[i * 3600, "100", "102", "99", "101", "100", "1", 1]
                   for i in range(60)]
        candles[10][0] = True
        with self.assertRaisesRegex(ValueError, "cannot be boolean"):
            main.assess_candle_quality(candles)

    def test_quality_report_explains_future_and_stale_data(self):
        candles = [[i * 3600, "100", "102", "99", "101", "100", "1", 1]
                   for i in range(60)]
        future = main.assess_candle_quality(candles, candles[-1][0] + 3600 - 600)
        self.assertEqual(future["quality_status"], "BLOCKED")
        self.assertIn("stale_or_future_candle", future["quality_block_reasons"])

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
        self.assertIn("sma200_regime", result["strategies"])
        self.assertIn("donchian_55_20", result["strategies"])
        self.assertIn("ema200_filter", result["strategies"])
        self.assertIn("rsi2_mean_reversion", result["strategies"])
        self.assertIn("bollinger_mean_reversion", result["strategies"])
        self.assertIn("market_regime_diagnostics", result)
        self.assertIn("bullish", result["market_regime_diagnostics"]["regimes"])

    def test_strategy_lab_reports_causal_out_of_sample_market_regimes(self):
        from strategy_lab import _market_regime_diagnostics

        prices = (
            [100.0] * 250
            + [100.0 + index for index in range(100)]
            + [200.0 - index * 0.4 for index in range(250)]
        )
        signals = {
            "always_on": [True] * len(prices),
            "always_off": [False] * len(prices),
        }
        result = _market_regime_diagnostics(prices, signals, 200)
        regimes = result["regimes"]
        self.assertGreater(regimes["bullish"]["bars"], 0)
        self.assertGreater(regimes["bearish"]["bars"], 0)
        self.assertGreater(regimes["sideways_or_transition"]["bars"], 0)
        for regime in regimes.values():
            if regime["bars"]:
                self.assertEqual(regime["strategy_exposure_pct"]["always_on"], 100.0)
                self.assertEqual(regime["strategy_exposure_pct"]["always_off"], 0.0)
                self.assertIsNotNone(regime["market_forward_return_pct"])
        self.assertIn("not strategy PnL", result["measurement"])

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

    def test_dashboard_renders_nonempty_strategy_lab_rows(self):
        report = self.sample_report()
        report["strategy_lab"] = {
            "strategies": {
                "ema_trend": {
                    "out_of_sample": {
                        "return_pct": 2.5,
                        "max_drawdown_pct": 1.2,
                        "closed_trades": 8,
                    },
                    "worst_window_return_pct": -0.4,
                }
            }
        }
        page = build_dashboard(report)
        self.assertIn("ema_trend", page)
        self.assertIn("2.5", page)
        self.assertIn("-0.4", page)

    def test_telegram_message_contains_signal_and_paper_equity(self):
        message = format_message(self.sample_report())
        self.assertIn("Signal: HOLD", message)
        self.assertIn("Paper equity: 1010 USD", message)
        self.assertIn("no real orders", message.lower())


if __name__ == "__main__":
    unittest.main()
