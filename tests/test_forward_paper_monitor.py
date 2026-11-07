import json
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path

from forward_paper_monitor import assess_sleeve_health, process_forward_accounts, validate_hourly_feed
from paper_account import seed_forward_paper_account, update_paper_account


class ForwardPaperMonitorTests(unittest.TestCase):
    def test_github_monitor_runs_hourly_to_review_each_closed_hour(self):
        workflow = Path(".github/workflows/forward-paper-monitor.yml").read_text(
            encoding="utf-8"
        )
        self.assertIn('cron: "17 * * * *"', workflow)
        self.assertNotIn('cron: "17 */4 * * *"', workflow)

    def make_candles(self, hours=24 * 60):
        start = 1_700_000_000
        start -= start % 3600
        rows = []
        for i in range(hours):
            close = 30000 + i * 2 + (i % 19) * 3
            rows.append({
                "timestamp": (start + i * 3600) * 1000,
                "open": float(close - 1),
                "high": float(close + 2),
                "low": float(close - 2),
                "close": float(close),
                "volume": 10.0,
                "imputed": False,
            })
        return rows

    def test_health_assessment_requires_forward_sample_and_never_promotes_live(self):
        base = {
            "completed_trades": 0,
            "max_drawdown_pct": 0.0,
            "profit_factor": 0.0,
            "return_pct": 0.0,
            "risk_pause_reasons": [],
        }
        self.assertEqual(
            assess_sleeve_health(base)["status"], "INSUFFICIENT_FORWARD_SAMPLE"
        )
        strong = {
            "completed_trades": 35,
            "max_drawdown_pct": 4.0,
            "profit_factor": 1.3,
            "return_pct": 2.0,
            "risk_pause_reasons": [],
        }
        result = assess_sleeve_health(strong)
        self.assertEqual(result["status"], "CONTINUE_PAPER_REVIEW")
        self.assertFalse(result["live_trading_eligible"])
        deteriorated = dict(strong, return_pct=-0.1)
        self.assertEqual(
            assess_sleeve_health(deteriorated)["status"], "REVIEW_REQUIRED"
        )
        paused = dict(strong, risk_pause_reasons=["maximum_drawdown"])
        self.assertEqual(assess_sleeve_health(paused)["status"], "RISK_PAUSED")

    def test_rolling_trade_window_detects_recent_deterioration(self):
        base = {
            "completed_trades": 40,
            "max_drawdown_pct": 3.0,
            "profit_factor": 1.4,
            "return_pct": 5.0,
            "risk_pause_reasons": [],
            "recent_trades": [{"pnl_usd": 2.0} for _ in range(10)],
        }
        healthy = assess_sleeve_health(base)
        self.assertEqual(healthy["rolling_status"], "ROLLING_STABLE")
        self.assertEqual(healthy["status"], "CONTINUE_PAPER_REVIEW")
        deteriorated = dict(
            base,
            recent_trades=[{"pnl_usd": -1.0} for _ in range(10)],
        )
        result = assess_sleeve_health(deteriorated)
        self.assertEqual(result["rolling_status"], "ROLLING_REVIEW_REQUIRED")
        self.assertEqual(result["status"], "REVIEW_REQUIRED")
        self.assertFalse(result["live_trading_eligible"])

    def test_rolling_drawdown_triggers_review_even_when_net_pnl_is_positive(self):
        account = {
            "completed_trades": 40,
            "initial_cash_usd": 200.0,
            "max_drawdown_pct": 2.0,
            "profit_factor": 1.5,
            "return_pct": 8.0,
            "risk_pause_reasons": [],
            "recent_trades": (
                [{"pnl_usd": 10.0} for _ in range(5)]
                + [{"pnl_usd": -4.0} for _ in range(5)]
            ),
        }
        result = assess_sleeve_health(account)
        self.assertEqual(result["rolling_net_pnl_usd"], 30.0)
        self.assertEqual(result["rolling_max_drawdown_pct"], 10.0)
        self.assertEqual(result["rolling_status"], "ROLLING_REVIEW_REQUIRED")
        self.assertEqual(result["status"], "REVIEW_REQUIRED")
        self.assertFalse(result["live_trading_eligible"])

    def test_rolling_drawdown_guard_pauses_new_entries(self):
        start = 1_750_000_000
        start -= start % 3600
        prices = [250.0 + i * 0.2 for i in range(220)]
        history = [
            [start + i * 3600, 0, 0, 0, str(price)]
            for i, price in enumerate(prices)
        ]
        with tempfile.TemporaryDirectory() as folder:
            state_path = str(Path(folder) / "rolling-guard.json")
            seed_forward_paper_account(
                history, state_path, initial_cash=200.0,
                strategy="ema50_200_regime",
            )
            state = json.loads(Path(state_path).read_text(encoding="utf-8"))
            state["trades"] = (
                [{"timestamp": start + i, "side": "SELL", "pnl_usd": 10.0, "result": "WIN"}
                 for i in range(5)]
                + [{"timestamp": start + 10 + i, "side": "SELL", "pnl_usd": -4.0, "result": "LOSS"}
                   for i in range(5)]
            )
            Path(state_path).write_text(json.dumps(state), encoding="utf-8")
            next_bar = [[start + len(prices) * 3600, 0, 0, 0, str(prices[-1] + 1.0)]]
            result = update_paper_account(
                next_bar, state_path=state_path, initial_cash=200.0,
                allocation_fraction=0.10, strategy="ema50_200_regime",
                strategy_health_pause=True,
                strategy_health_drawdown_fraction=0.08,
            )
            self.assertTrue(result["paused_for_strategy_health"])
            self.assertIn("strategy_health_deterioration", result["risk_pause_reasons"])
            self.assertFalse(result["open_position"])
            self.assertEqual(result["completed_trades"], 10)

    def test_strategy_health_drawdown_threshold_is_validated(self):
        with tempfile.TemporaryDirectory() as folder:
            with self.assertRaisesRegex(ValueError, "strategy_health_drawdown_fraction"):
                update_paper_account(
                    [[1_750_000_000, 0, 0, 0, "100"]],
                    state_path=str(Path(folder) / "invalid-threshold.json"),
                    strategy_health_drawdown_fraction=0,
                )

    def test_rolling_window_rejects_invalid_trade_pnl(self):
        account = {
            "completed_trades": 12,
            "max_drawdown_pct": 1.0,
            "profit_factor": 1.0,
            "return_pct": 1.0,
            "risk_pause_reasons": [],
            "recent_trades": [{"pnl_usd": float("nan")}],
        }
        with self.assertRaisesRegex(ValueError, "Recent trade PnL"):
            assess_sleeve_health(account)

    def test_health_assessment_rejects_invalid_metrics(self):
        invalid = {
            "completed_trades": True,
            "max_drawdown_pct": 0.0,
            "profit_factor": 1.0,
            "return_pct": 1.0,
            "risk_pause_reasons": [],
        }
        with self.assertRaisesRegex(ValueError, "trade count"):
            assess_sleeve_health(invalid)

    def test_initialization_is_forward_only_and_idempotent(self):
        candles = self.make_candles()
        now = candles[-1]["timestamp"] / 1000 + 3600 + 60
        with tempfile.TemporaryDirectory() as folder:
            first = process_forward_accounts(candles, folder, now)
            self.assertEqual(first["initial_cash_usd"], 1600.0)
            self.assertEqual(first["completed_trades"], 0)
            self.assertEqual(first["schema_version"], 1)
            self.assertEqual(first["status"], "PAPER_MONITORING")
            self.assertEqual(
                set(first["sleeves_summary"]),
                {"1h_sma_trend", "1h_ema_trend", "1h_rsi14_mean_reversion", "4h", "6h"},
            )
            for timeframe in ("1h_sma_trend", "1h_ema_trend", "1h_rsi14_mean_reversion", "4h", "6h"):
                health = first["sleeves_summary"][timeframe]["health_assessment"]
                self.assertEqual(health["status"], "INSUFFICIENT_FORWARD_SAMPLE")
                self.assertFalse(health["live_trading_eligible"])
            for timeframe in ("1h_sma_trend", "1h_ema_trend", "1h_rsi14_mean_reversion", "4h", "6h"):
                account = first["sleeves"][timeframe]["account"]
                self.assertEqual(account["processed_new_candles"], 0)
                self.assertEqual(account["return_pct"], 0.0)
                self.assertEqual(account["completed_trades"], 0)
            second = process_forward_accounts(candles, folder, now)
            for timeframe in ("4h", "6h"):
                self.assertEqual(
                    second["sleeves"][timeframe]["account"]["processed_new_candles"], 0
                )
            self.assertEqual(first["equity_after_estimated_exit_costs_usd"],
                             second["equity_after_estimated_exit_costs_usd"])

    def test_new_bars_are_processed_once_after_seed(self):
        candles = self.make_candles()
        now = candles[-1]["timestamp"] / 1000 + 3600 + 60
        with tempfile.TemporaryDirectory() as folder:
            process_forward_accounts(candles, folder, now)
            extended = candles + self.make_candles(8)
            # Shift appended fixture timestamps to immediately follow the original feed.
            for i, row in enumerate(extended[len(candles):]):
                row["timestamp"] = candles[-1]["timestamp"] + (i + 1) * 3_600_000
            now2 = extended[-1]["timestamp"] / 1000 + 3600 + 60
            result = process_forward_accounts(extended, folder, now2)
            self.assertGreater(result["sleeves"]["1h_sma_trend"]["account"]["processed_new_candles"], 0)
            self.assertGreater(result["sleeves"]["1h_ema_trend"]["account"]["processed_new_candles"], 0)
            self.assertGreater(result["sleeves"]["1h_rsi14_mean_reversion"]["account"]["processed_new_candles"], 0)
            self.assertGreater(result["sleeves"]["4h"]["account"]["processed_new_candles"], 0)
            self.assertGreater(result["sleeves"]["6h"]["account"]["processed_new_candles"], 0)
            again = process_forward_accounts(extended, folder, now2)
            self.assertEqual(again["sleeves"]["4h"]["account"]["processed_new_candles"], 0)
            self.assertEqual(again["sleeves"]["6h"]["account"]["processed_new_candles"], 0)

    def test_rsi_mean_reversion_opens_and_closes_a_forward_paper_trade(self):
        start = 1_750_000_000
        start -= start % 3600
        prices = [250.0 + i * 0.2 for i in range(220)]
        # A forward-seed setup with an oversold pullback that remains above
        # the long-term regime average.
        for _ in range(14):
            prices.append(prices[-1] - 0.5)
        history = [
            [start + i * 3600, 0, 0, 0, str(price)]
            for i, price in enumerate(prices)
        ]
        with tempfile.TemporaryDirectory() as folder:
            state_path = str(Path(folder) / "rsi-forward.json")
            seed_forward_paper_account(
                history, state_path, initial_cash=200.0,
                strategy="rsi14_mean_reversion",
            )
            first_future = [
                [start + len(prices) * 3600, 0, 0, 0, str(prices[-1] - 0.2)]
            ]
            opened = update_paper_account(
                first_future, state_path=state_path, initial_cash=200.0,
                allocation_fraction=0.10, strategy="rsi14_mean_reversion",
            )
            self.assertTrue(opened["open_position"])
            self.assertEqual(opened["completed_trades"], 0)

            rebound = []
            price = float(first_future[-1][-1])
            for i in range(1, 17):
                price += 2.0
                rebound.append([
                    start + (len(prices) + i) * 3600, 0, 0, 0, str(price)
                ])
            closed = update_paper_account(
                rebound, state_path=state_path, initial_cash=200.0,
                allocation_fraction=0.10, strategy="rsi14_mean_reversion",
            )
            self.assertFalse(closed["open_position"])
            self.assertGreaterEqual(closed["completed_trades"], 1)
            self.assertGreater(closed["processed_new_candles"], 0)

    def test_hourly_timestamps_must_align_to_utc_hour_boundaries(self):
        candles = self.make_candles(48)
        for candle in candles:
            candle["timestamp"] += 30_000
        now = candles[-1]["timestamp"] / 1000 + 3600 + 60
        with self.assertRaisesRegex(ValueError, "align to UTC hour boundaries"):
            validate_hourly_feed(candles, now)

    def test_recent_hourly_gap_is_rejected(self):
        candles = self.make_candles(48)
        candles[-1]["timestamp"] += 3_600_000
        now = candles[-1]["timestamp"] / 1000 + 3600 + 60
        with self.assertRaisesRegex(ValueError, "gap"):
            validate_hourly_feed(candles, now)

    def test_invalid_ohlcv_values_are_rejected(self):
        mutations = [
            ("close", float("nan"), "finite number"),
            ("volume", -1.0, "volume cannot be negative"),
            ("high", 1.0, "high is inconsistent"),
            ("low", 999999.0, "low is inconsistent"),
            ("open", True, "finite number"),
            ("imputed", "false", "imputed flag must be boolean"),
        ]
        for field, value, message in mutations:
            with self.subTest(field=field):
                candles = self.make_candles(48)
                candles[-1][field] = value
                if field == "low":
                    candles[-1]["high"] = 1_000_000.0
                now = candles[-1]["timestamp"] / 1000 + 3600 + 60
                with self.assertRaisesRegex(ValueError, message):
                    validate_hourly_feed(candles, now)

    def test_non_integer_or_boolean_timestamp_is_rejected(self):
        for value in (True, 1.5, float("inf")):
            with self.subTest(timestamp=value):
                candles = self.make_candles(48)
                candles[-1]["timestamp"] = value
                with self.assertRaisesRegex(ValueError, "timestamp"):
                    validate_hourly_feed(candles, 1_800_000_000)

    def test_non_finite_current_time_is_rejected(self):
        candles = self.make_candles(48)
        with self.assertRaisesRegex(ValueError, "Current timestamp must be finite"):
            validate_hourly_feed(candles, float("nan"))

    def test_stale_or_imputed_feed_is_rejected(self):
        candles = self.make_candles(48)
        last_close = candles[-1]["timestamp"] / 1000 + 3600
        with self.assertRaisesRegex(ValueError, "stale"):
            validate_hourly_feed(candles, last_close + 3 * 3600)
        candles[-3]["imputed"] = True
        with self.assertRaisesRegex(ValueError, "imputed"):
            validate_hourly_feed(candles, last_close + 60)


if __name__ == "__main__":
    unittest.main()
