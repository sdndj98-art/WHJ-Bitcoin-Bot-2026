import json
import forward_paper_monitor
import tempfile
import unittest
from unittest.mock import patch
from datetime import datetime, timezone
from pathlib import Path

from forward_paper_monitor import (assess_sleeve_health, build_qualified_ensemble, process_forward_accounts, validate_hourly_feed, write_report_atomically)
from paper_account import seed_forward_paper_account, update_paper_account


class ForwardPaperMonitorTests(unittest.TestCase):

    def test_qualified_ensemble_combines_only_equal_weight_4h_and_6h_sleeves(self):
        summary = {}
        sleeves = {}
        for timeframe, equity, trades, status in (
            ("4h", 510.0, 3, "INSUFFICIENT_FORWARD_SAMPLE"),
            ("6h", 520.0, 4, "INSUFFICIENT_FORWARD_SAMPLE"),
        ):
            summary[timeframe] = {
                "equity_usd": equity,
                "exposure_usd": 25.0,
                "max_drawdown_pct": 2.0,
                "health_assessment": {"status": status},
            }
            sleeves[timeframe] = {"account": {
                "initial_cash_usd": 500.0,
                "equity_after_estimated_exit_costs_usd": equity,
                "completed_trades": trades,
                "processed_new_candles": 2,
                "fees_paid_usd": 0.5,
                "cash_usd": equity - 25.0,
                "btc_units": 0.001,
            }}
        # Unqualified hourly sleeves must not affect the selected ensemble.
        summary["1h_sma_trend"] = {"equity_usd": 10_000.0}
        sleeves["1h_sma_trend"] = {"account": {"initial_cash_usd": 10_000.0}}

        result = build_qualified_ensemble(summary, sleeves)
        self.assertEqual(result["initial_cash_usd"], 1000.0)
        self.assertEqual(result["equity_after_estimated_exit_costs_usd"], 1030.0)
        self.assertEqual(result["return_pct"], 3.0)
        self.assertEqual(result["completed_trades"], 7)
        self.assertEqual(result["processed_new_candles"], 4)
        self.assertEqual(result["max_drawdown_by_sleeve_pct"], {"4h": 2.0, "6h": 2.0})
        self.assertEqual(result["status"], "INSUFFICIENT_FORWARD_SAMPLE")
        self.assertFalse(result["live_trading_eligible"])
        self.assertEqual(result["allocation"]["4h_capital_pct"], 50)
        self.assertEqual(result["allocation"]["6h_capital_pct"], 50)

    def test_qualified_ensemble_pauses_if_either_selected_sleeve_is_paused(self):
        summary = {}
        sleeves = {}
        for timeframe, status in (("4h", "CONTINUE_PAPER_REVIEW"), ("6h", "RISK_PAUSED")):
            summary[timeframe] = {
                "equity_usd": 500.0,
                "exposure_usd": 0.0,
                "max_drawdown_pct": 0.0,
                "health_assessment": {"status": status},
            }
            sleeves[timeframe] = {"account": {
                "initial_cash_usd": 500.0,
                "equity_after_estimated_exit_costs_usd": 500.0,
                "completed_trades": 30,
                "processed_new_candles": 0,
                "fees_paid_usd": 0.0,
                "cash_usd": 500.0,
                "btc_units": 0.0,
            }}
        result = build_qualified_ensemble(summary, sleeves)
        self.assertEqual(result["status"], "RISK_PAUSED")
        self.assertFalse(result["live_trading_eligible"])

    def test_forward_report_write_preserves_previous_file_if_replace_fails(self):
        with tempfile.TemporaryDirectory() as folder:
            target = Path(folder) / "forward_paper_report.json"
            target.write_text('{"previous": true}\n', encoding="utf-8")
            with patch("forward_paper_monitor.os.replace", side_effect=OSError("simulated replace failure")):
                with self.assertRaisesRegex(OSError, "simulated replace failure"):
                    write_report_atomically({"current": True}, target)
            self.assertEqual(
                target.read_text(encoding="utf-8"), '{"previous": true}\n'
            )
            self.assertEqual(list(Path(folder).glob(".forward_paper_report.json.*.tmp")), [])

    def test_forward_report_write_rejects_non_finite_json_without_corrupting_previous_file(self):
        with tempfile.TemporaryDirectory() as folder:
            target = Path(folder) / "forward_paper_report.json"
            target.write_text('{"previous": true}\n', encoding="utf-8")
            with self.assertRaises(ValueError):
                write_report_atomically({"invalid": float("nan")}, target)
            self.assertEqual(
                target.read_text(encoding="utf-8"), '{"previous": true}\n'
            )
            self.assertEqual(list(Path(folder).glob(".forward_paper_report.json.*.tmp")), [])

    def test_forward_report_write_replaces_file_with_valid_json(self):
        with tempfile.TemporaryDirectory() as folder:
            target = Path(folder) / "forward_paper_report.json"
            target.write_text('{"previous": true}\n', encoding="utf-8")
            returned = write_report_atomically({"schema_version": 1, "status": "PAPER_MONITORING"}, target)
            self.assertEqual(returned, target)
            self.assertEqual(
                json.loads(target.read_text(encoding="utf-8")),
                {"schema_version": 1, "status": "PAPER_MONITORING"},
            )

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

    def test_rolling_health_pause_reconciles_without_a_new_candle(self):
        start = 1_750_000_000
        start -= start % 3600
        prices = [250.0 + i * 0.2 for i in range(220)]
        candles = [
            [start + i * 3600, 0, 0, 0, str(price)]
            for i, price in enumerate(prices)
        ]
        with tempfile.TemporaryDirectory() as folder:
            state_path = str(Path(folder) / "no-new-candle-health.json")
            seed_forward_paper_account(
                candles, state_path, initial_cash=200.0,
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
            result = update_paper_account(
                candles, state_path=state_path, initial_cash=200.0,
                strategy="ema50_200_regime", strategy_health_pause=True,
                strategy_health_drawdown_fraction=0.08,
            )
            self.assertEqual(result["processed_new_candles"], 0)
            self.assertTrue(result["paused_for_strategy_health"])
            self.assertIn("strategy_health_deterioration", result["risk_pause_reasons"])
            saved = json.loads(Path(state_path).read_text(encoding="utf-8"))
            self.assertTrue(saved["paused_for_strategy_health"])

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

    def test_health_assessment_rejects_impossible_drawdown_metrics(self):
        base = {
            "completed_trades": 30,
            "max_drawdown_pct": 0.0,
            "profit_factor": 1.2,
            "return_pct": 1.0,
            "risk_pause_reasons": [],
        }
        for value in (-0.01, 100.01):
            with self.subTest(max_drawdown_pct=value):
                with self.assertRaisesRegex(ValueError, "Max drawdown metric"):
                    assess_sleeve_health(dict(base, max_drawdown_pct=value))

    def test_health_assessment_rejects_recent_window_larger_than_trade_ledger(self):
        account = {
            "completed_trades": 2,
            "max_drawdown_pct": 1.0,
            "profit_factor": 1.2,
            "return_pct": 1.0,
            "risk_pause_reasons": [],
            "recent_trades": [{"pnl_usd": 1.0} for _ in range(3)],
        }
        with self.assertRaisesRegex(ValueError, "Recent trade count"):
            assess_sleeve_health(account)

    def test_initialization_is_forward_only_and_idempotent(self):
        candles = self.make_candles()
        now = candles[-1]["timestamp"] / 1000 + 3600 + 60
        with tempfile.TemporaryDirectory() as folder:
            first = process_forward_accounts(candles, folder, now)
            self.assertEqual(first["initial_cash_usd"], 10.0)
            self.assertEqual(first["completed_trades"], 0)
            self.assertEqual(first["schema_version"], 1)
            self.assertEqual(first["qualified_ensemble"]["initial_cash_usd"], 1000.0)
            self.assertEqual(first["qualified_ensemble"]["return_pct"], 0.0)
            self.assertEqual(first["qualified_ensemble"]["completed_trades"], 0)
            self.assertEqual(first["qualified_ensemble"]["status"], "INSUFFICIENT_FORWARD_SAMPLE")
            self.assertFalse(first["qualified_ensemble"]["live_trading_eligible"])
            self.assertEqual(first["status"], "PAPER_MONITORING")
            self.assertEqual(first["cycle_status"], "WAITING_FOR_NEW_CLOSED_CANDLES")
            self.assertEqual(first["total_processed_new_candles"], 0)
            self.assertEqual(first["cash_usd"], 10.0)
            self.assertEqual(first["btc_units"], 0.0)
            self.assertEqual(first["gross_exposure_usd"], 0.0)
            self.assertEqual(first["gross_exposure_pct_of_equity"], 0.0)
            self.assertEqual(first["fees_paid_usd"], 0.0)
            self.assertEqual(first["open_positions"], 0)
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
                sleeve = first["sleeves_summary"][timeframe]
                self.assertEqual(sleeve["cash_usd"], 2.0)
                self.assertEqual(sleeve["btc_units"], 0.0)
                self.assertEqual(sleeve["exposure_usd"], 0.0)
                self.assertEqual(sleeve["exposure_pct_of_equity"], 0.0)
                self.assertEqual(sleeve["fees_paid_usd"], 0.0)
                self.assertEqual(sleeve["current_consecutive_losses"], 0)
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
            self.assertEqual(result["cycle_status"], "PROCESSED_NEW_CANDLES")
            self.assertGreater(result["total_processed_new_candles"], 0)
            self.assertAlmostEqual(result["gross_exposure_usd"], sum(x["exposure_usd"] for x in result["sleeves_summary"].values()), places=2)
            self.assertAlmostEqual(result["fees_paid_usd"], sum(x["fees_paid_usd"] for x in result["sleeves_summary"].values()), places=4)
            self.assertEqual(result["open_positions"], sum(1 for x in result["sleeves_summary"].values() if x["open_position"]))
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

    def test_minimum_24_hour_feed_accepts_contiguous_candles(self):
        candles = self.make_candles(24)
        now = candles[-1]["timestamp"] / 1000 + 3600 + 60
        quality = validate_hourly_feed(candles, now)
        self.assertEqual(quality["quality"], "HEALTHY")
        self.assertEqual(quality["total_hourly_candles"], 24)
        self.assertEqual(quality["imputed_hourly_candles"], 0)

    def test_insufficient_multitimeframe_warmup_fails_before_any_ledger_is_created(self):
        candles = self.make_candles(24 * 50 - 1)
        now = candles[-1]["timestamp"] / 1000 + 3600 + 60
        with tempfile.TemporaryDirectory() as folder:
            with self.assertRaisesRegex(
                ValueError, "Insufficient completed candles.*no paper account state was changed"
            ):
                process_forward_accounts(candles, folder, now)
            self.assertEqual(list(Path(folder).iterdir()), [])

    def test_recent_hourly_gap_is_rejected(self):
        candles = self.make_candles(48)
        candles[-1]["timestamp"] += 3_600_000
        now = candles[-1]["timestamp"] / 1000 + 3600 + 60
        with self.assertRaisesRegex(ValueError, "gap"):
            validate_hourly_feed(candles, now)

    def test_historical_imputed_candles_are_counted_but_recent_ones_are_blocked(self):
        candles = self.make_candles(48)
        candles[5]["imputed"] = True
        now = candles[-1]["timestamp"] / 1000 + 3600 + 60
        quality = validate_hourly_feed(candles, now)
        self.assertEqual(quality["total_hourly_candles"], 48)
        self.assertEqual(quality["observed_hourly_candles"], 47)
        self.assertEqual(quality["imputed_hourly_candles"], 1)
        self.assertEqual(quality["imputed_hourly_pct"], 2.0833)

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


    def test_main_uses_documented_kraken_cvd_journal_and_checkpoint_paths(self):
        with patch("forward_paper_monitor.load_two_year_candles", return_value=[{"timestamp": 1}]):
            with patch("forward_paper_monitor.process_forward_accounts", return_value={"status": "PAPER_MONITORING"}) as processor:
                with patch("forward_paper_monitor.write_report_atomically"):
                    with patch("builtins.print"):
                        forward_paper_monitor.main()
        kwargs = processor.call_args.kwargs
        self.assertEqual(
            kwargs["cvd_journal_path"],
            "state/kraken_btc_usd_trades.jsonl",
        )
        self.assertEqual(
            kwargs["cvd_checkpoint_path"],
            "state/kraken_btc_usd_trades.jsonl.checkpoint.json",
        )
        self.assertTrue(kwargs["require_cvd_confirmation"])

    def test_forward_monitor_loads_verified_cvd_and_reports_entry_gate(self):
        candles = self.make_candles()
        now = candles[-1]["timestamp"] / 1000 + 3600 + 60
        unavailable = {
            "status": "UNAVAILABLE", "available": False,
            "direction": "UNKNOWN", "reason": "test_missing_checkpoint",
            "research_only": True, "execution_enabled": False,
        }
        with tempfile.TemporaryDirectory() as folder:
            with patch(
                "forward_paper_monitor.build_latest_cvd_confirmation",
                return_value=unavailable,
            ) as builder:
                report = process_forward_accounts(
                    candles, folder, now,
                    require_cvd_confirmation=True,
                    cvd_journal_path=str(Path(folder) / "trades.jsonl"),
                    cvd_checkpoint_path=str(Path(folder) / "checkpoint.json"),
                )
            builder.assert_called_once()
            self.assertTrue(report["cvd_requirement_enabled"])
            self.assertEqual(
                report["cvd_confirmation"]["reason"], "test_missing_checkpoint"
            )
            for sleeve in ("1h_sma_trend", "1h_ema_trend", "1h_rsi14_mean_reversion"):
                self.assertFalse(report["sleeves"][sleeve]["account"]["open_position"])
                self.assertEqual(report["sleeves"][sleeve]["account"]["btc_units"], 0.0)

if __name__ == "__main__":
    unittest.main()
