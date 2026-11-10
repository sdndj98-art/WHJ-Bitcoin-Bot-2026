"""Unit tests for the historical data ingestion gate."""
import math
import unittest
from datetime import datetime, timezone
from unittest.mock import patch

from historical_research import (INTERVAL_MS, _blocked_execution_indices, _research_output_paths, aggregate_candles, load_two_year_candles, run_forward_paper_accounts, run_ohlc_breakout_lab, run_long_short_lab, run_daily_regime_filter_lab, run_multi_timeframe_ensemble_lab, run_six_hour_atr_trailing_lab, _adx_di_series, _atr_series, _regime_switching_atr_signals, _rsi_series, _simulate_equal_weight_multitimeframe, _simulate_long_short, _simulate_ohlc, assess_strategy_qualification, assess_research_lab_qualification, build_qualification_markdown, summarize_qualification, _turtle_signals)
from strategy_lab import _simulate, run_strategy_lab


class HistoricalResearchTests(unittest.TestCase):
    def make_page(self, start_ms, end_ms, skip_timestamp=None):
        rows = []
        timestamp = start_ms
        while timestamp <= end_ms:
            if timestamp != skip_timestamp:
                price = 50000.0 + (timestamp // INTERVAL_MS % 1000)
                rows.append([timestamp, price, price + 10, price - 10, price + 1, 2.0])
            timestamp += INTERVAL_MS
        return rows

    def test_strategy_qualification_rejects_small_or_fragile_samples(self):
        metrics = {
            "out_of_sample": {
                "return_pct": 2.0,
                "max_drawdown_pct": 4.0,
                "profit_factor": 1.8,
                "closed_trades": 40,
            },
            "walk_forward_windows": [
                {"metrics": {"return_pct": 0.5, "closed_trades": 12}},
                {"metrics": {"return_pct": 0.1, "closed_trades": 13}},
                {"metrics": {"return_pct": 1.0, "closed_trades": 15}},
            ],
        }
        stress = {"out_of_sample": {"return_pct": 0.4}}
        benchmark = {"out_of_sample": {"return_pct": 1.0}}
        stress_benchmark = {"out_of_sample": {"return_pct": 0.1}}
        self.assertTrue(assess_strategy_qualification(
            metrics, stress, benchmark_metrics=benchmark,
            stress_benchmark_metrics=stress_benchmark,
        )["qualified_for_extended_paper_review"])

        small_sample = {
            **metrics,
            "out_of_sample": {**metrics["out_of_sample"], "closed_trades": 5},
        }
        self.assertFalse(
            assess_strategy_qualification(
                small_sample, stress, benchmark_metrics=benchmark,
                stress_benchmark_metrics=stress_benchmark,
            )["qualified_for_extended_paper_review"]
        )

        fragile = {
            **metrics,
            "walk_forward_windows": [
                {"metrics": {"return_pct": 0.5, "closed_trades": 12}},
                {"metrics": {"return_pct": -0.1, "closed_trades": 13}},
                {"metrics": {"return_pct": 1.0, "closed_trades": 15}},
            ],
        }
        self.assertIn(
            "all_walk_forward_windows_nonnegative",
            assess_strategy_qualification(
                fragile, stress, benchmark_metrics=benchmark,
                stress_benchmark_metrics=stress_benchmark,
            )["failed_checks"],
        )

        sparse_windows = {
            **metrics,
            "walk_forward_windows": [
                {"metrics": {"return_pct": 0.5, "closed_trades": 20}},
                {"metrics": {"return_pct": 0.1, "closed_trades": 2}},
                {"metrics": {"return_pct": 1.0, "closed_trades": 18}},
            ],
        }
        self.assertIn(
            "minimum_trades_each_walk_forward_window",
            assess_strategy_qualification(
                sparse_windows, stress, benchmark_metrics=benchmark,
                stress_benchmark_metrics=stress_benchmark,
            )["failed_checks"],
        )

        stress_loss = {"out_of_sample": {"return_pct": -0.01}}
        self.assertIn(
            "positive_stress_oos_return",
            assess_strategy_qualification(
                metrics, stress_loss, benchmark_metrics=benchmark,
                stress_benchmark_metrics=stress_benchmark,
            )["failed_checks"],
        )

    def test_qualification_rejects_nonfinite_and_malformed_metrics(self):
        base = {
            "out_of_sample": {
                "return_pct": 2.0,
                "max_drawdown_pct": 4.0,
                "profit_factor": 1.8,
                "closed_trades": 40,
            },
            "walk_forward_windows": [
                {"metrics": {"return_pct": 0.5, "closed_trades": 12}},
                {"metrics": {"return_pct": 0.1, "closed_trades": 13}},
                {"metrics": {"return_pct": 1.0, "closed_trades": 15}},
            ],
        }
        stress = {"out_of_sample": {"return_pct": 0.4}}
        benchmark = {"out_of_sample": {"return_pct": 1.0}}
        stress_benchmark = {"out_of_sample": {"return_pct": 0.1}}

        def assess(candidate):
            return assess_strategy_qualification(
                candidate, stress,
                benchmark_metrics=benchmark,
                stress_benchmark_metrics=stress_benchmark,
            )

        cases = [
            ("NaN return", {"return_pct": float("nan")}, "positive_oos_return"),
            ("infinite return", {"return_pct": float("inf")}, "positive_oos_return"),
            ("boolean return", {"return_pct": True}, "positive_oos_return"),
            ("infinite profit factor", {"profit_factor": float("inf")}, "minimum_profit_factor"),
            ("negative drawdown", {"max_drawdown_pct": -1.0}, "maximum_oos_drawdown"),
            ("infinite drawdown", {"max_drawdown_pct": float("inf")}, "maximum_oos_drawdown"),
            ("fractional trade count", {"closed_trades": 40.5}, "minimum_oos_trades"),
            ("boolean trade count", {"closed_trades": True}, "minimum_oos_trades"),
        ]
        for label, update, failed_check in cases:
            with self.subTest(label=label):
                candidate = {
                    **base,
                    "out_of_sample": {**base["out_of_sample"], **update},
                }
                result = assess(candidate)
                self.assertFalse(result["qualified_for_extended_paper_review"])
                self.assertIn(failed_check, result["failed_checks"])

        malformed = [
            {},
            {"out_of_sample": None, "walk_forward_windows": []},
            {**base, "walk_forward_windows": None},
            {**base, "walk_forward_windows": [
                {"metrics": {"return_pct": 0.5, "closed_trades": 12}},
                None,
                {"metrics": {"return_pct": 1.0, "closed_trades": 15}},
            ]},
            {**base, "walk_forward_windows": [
                {"metrics": {"return_pct": float("nan"), "closed_trades": 12}},
                {"metrics": {"return_pct": 0.1, "closed_trades": 13}},
                {"metrics": {"return_pct": 1.0, "closed_trades": 15}},
            ]},
        ]
        for candidate in malformed:
            with self.subTest(candidate=candidate):
                result = assess(candidate)
                self.assertFalse(result["qualified_for_extended_paper_review"])

        for kwargs in (
            {"min_oos_trades": True},
            {"min_window_trades": 1.5},
            {"min_profit_factor": float("nan")},
            {"max_drawdown_pct": float("inf")},
        ):
            with self.subTest(kwargs=kwargs):
                with self.assertRaises(ValueError):
                    assess_strategy_qualification(
                        base, stress, benchmark_metrics=benchmark,
                        stress_benchmark_metrics=stress_benchmark, **kwargs,
                    )

        result = assess(base)
        self.assertTrue(result["qualified_for_extended_paper_review"])

    def test_download_paginates_and_discards_current_open_hour(self):
        now = datetime(2026, 11, 7, 12, 0, tzinfo=timezone.utc)
        with patch("historical_research.fetch_page", side_effect=self.make_page):
            candles = load_two_year_candles(days=45, now=now)
        self.assertEqual(len(candles), 45 * 24)
        self.assertEqual(candles[-1]["timestamp"], int(now.timestamp() * 1000) - INTERVAL_MS)
        self.assertEqual(candles[0]["timestamp"] + (len(candles) - 1) * INTERVAL_MS,
                         candles[-1]["timestamp"])

    def test_short_missing_hour_is_imputed_and_flagged(self):
        now = datetime(2026, 11, 7, 12, 0, tzinfo=timezone.utc)
        calls = {"count": 0}

        def page_with_gap(start_ms, end_ms):
            calls["count"] += 1
            missing = start_ms + 100 * INTERVAL_MS if calls["count"] == 1 else None
            return self.make_page(start_ms, end_ms, skip_timestamp=missing)

        with patch("historical_research.fetch_page", side_effect=page_with_gap):
            candles = load_two_year_candles(days=45, now=now)
        self.assertEqual(candles[0]["_imputed_hour_count"], 1)
        self.assertEqual(sum(1 for candle in candles if candle["imputed"]), 1)

    def test_large_missing_interval_is_rejected(self):
        now = datetime(2026, 11, 7, 12, 0, tzinfo=timezone.utc)
        calls = {"count": 0}

        def page_with_large_gap(start_ms, end_ms):
            calls["count"] += 1
            missing = start_ms + 100 * INTERVAL_MS if calls["count"] == 1 else None
            rows = self.make_page(start_ms, end_ms)
            if missing is not None:
                rows = [row for row in rows if row[0] < missing or row[0] >= missing + 8 * INTERVAL_MS]
            return rows

        with patch("historical_research.fetch_page", side_effect=page_with_large_gap):
            with self.assertRaisesRegex(ValueError, "six-hour repair limit"):
                load_two_year_candles(days=45, now=now)

    def test_timeframe_aggregation_uses_only_complete_utc_bars(self):
        candles = []
        for index in range(24 * 205):
            timestamp = index * INTERVAL_MS
            price = 100.0 + index
            candles.append({
                "timestamp": timestamp,
                "open": price,
                "high": price + 2,
                "low": price - 2,
                "close": price + 1,
                "volume": 1.0,
                "imputed": index == 10,
            })
        four_hour = aggregate_candles(candles, 4)
        daily = aggregate_candles(candles, 24)
        self.assertEqual(len(four_hour), (24 * 205) // 4)
        self.assertEqual(len(daily), 205)
        self.assertEqual(four_hour[0]["open"], candles[0]["open"])
        self.assertEqual(four_hour[0]["close"], candles[3]["close"])
        self.assertEqual(four_hour[0]["high"], candles[3]["high"])
        self.assertTrue(four_hour[2]["imputed"])
        self.assertTrue(daily[0]["imputed"])
        self.assertEqual(_blocked_execution_indices(four_hour), {2})
        self.assertEqual(_blocked_execution_indices(daily), {0})
        self.assertEqual(daily[0]["volume"], 24.0)

    def test_synthetic_execution_bars_are_blocked_for_entry_and_exit(self):
        prices = [100.0, 105.0, 120.0, 130.0, 140.0]
        signals = [True, True, False, False, False]
        metrics = _simulate(
            prices, signals, 1, len(prices), fee=0.0, slippage=0.0,
            blocked_execution_indices={1, 3},
        )
        # Entry waits from blocked index 1 to executable index 2; exit waits
        # from blocked index 3 to executable index 4.
        self.assertEqual(metrics["closed_trades"], 1)
        self.assertEqual(metrics["final_equity_usd"], 1041.67)
        self.assertFalse(metrics["open_position"])

    def test_terminal_valuation_does_not_assume_fill_on_imputed_last_bar(self):
        prices = [100.0, 100.0, 120.0, 130.0]
        signals = [True, True, True, True]
        metrics = _simulate(
            prices, signals, 1, len(prices), fee=0.0, slippage=0.0,
            blocked_execution_indices={3},
        )
        self.assertTrue(metrics["open_position"])
        # The last executable close is 120, not the synthetic terminal close 130.
        self.assertEqual(metrics["final_equity_usd"], 1050.0)

    def test_strategy_lab_passes_blocked_indices_to_every_simulation_window(self):
        prices = [100.0 + index for index in range(300)]
        blocked = {220, 260}
        stub_metrics = {
            "return_pct": 0.1,
            "final_equity_usd": 1001.0,
            "max_drawdown_pct": 0.0,
            "closed_trades": 1,
            "win_rate_pct": 100.0,
            "profit_factor": None,
            "open_position": False,
        }
        with patch("strategy_lab._simulate", return_value=stub_metrics) as simulator:
            result = run_strategy_lab(
                prices, blocked_execution_indices=blocked
            )
        self.assertGreater(simulator.call_count, 10)
        self.assertTrue(all(call.args[6] == blocked for call in simulator.call_args_list))
        self.assertEqual(result["blocked_execution_bar_count"], len(blocked))

    def test_strategy_lab_rejects_invalid_blocked_execution_indices(self):
        prices = [100.0 + index for index in range(300)]
        for invalid in ({True}, {-1}, {300}, {1.5}):
            with self.subTest(invalid=invalid):
                with self.assertRaises(ValueError):
                    run_strategy_lab(prices, blocked_execution_indices=invalid)

    def test_ohlc_simulator_blocks_synthetic_entry_and_exit_fills(self):
        bars = [
            {"close": price, "imputed": index in {1, 3}}
            for index, price in enumerate((100.0, 105.0, 120.0, 130.0, 140.0))
        ]
        signals = [True, True, False, False, False]
        metrics = _simulate_ohlc(bars, signals, 1, len(bars), 0.0, 0.0)
        self.assertEqual(metrics["closed_trades"], 1)
        self.assertEqual(metrics["final_equity_usd"], 1041.67)
        self.assertFalse(metrics["open_position"])

    def test_ohlc_terminal_valuation_uses_last_executable_bar(self):
        bars = [
            {"close": price, "imputed": index == 3}
            for index, price in enumerate((100.0, 100.0, 120.0, 130.0))
        ]
        metrics = _simulate_ohlc(bars, [True] * 4, 1, len(bars), 0.0, 0.0)
        self.assertTrue(metrics["open_position"])
        self.assertEqual(metrics["final_equity_usd"], 1050.0)

    def test_long_short_simulator_blocks_synthetic_reversals(self):
        bars = [
            {"close": price, "imputed": index in {1, 3}}
            for index, price in enumerate((100.0, 105.0, 120.0, 130.0, 140.0))
        ]
        metrics = _simulate_long_short(
            bars, [1, 1, -1, -1, -1], 1, len(bars), 0.0, 0.0, 0.0
        )
        self.assertEqual(metrics["closed_trades"], 2)
        self.assertFalse(metrics["open_position"])

    def test_equal_weight_simulator_blocks_synthetic_fills(self):
        bars = [
            {"timestamp": index * INTERVAL_MS, "close": price, "imputed": index in {1, 3}}
            for index, price in enumerate((100.0, 105.0, 120.0, 130.0, 140.0))
        ]
        result = _simulate_equal_weight_multitimeframe(
            [bars], [[True, True, False, False, False]], [1],
            0, 5 * INTERVAL_MS, 0.0, 0.0,
        )
        self.assertEqual(result["closed_trades"], 1)
        self.assertEqual(result["final_equity_usd"], 1041.67)

    def test_ohlc_buy_and_hold_benchmark_skips_synthetic_entry_and_exit(self):
        bars = []
        for index in range(500):
            bars.append({
                "timestamp": index * 86400000,
                "open": 100.0, "high": 101.0, "low": 99.0,
                "close": 100.0, "volume": 1.0,
                "imputed": index in {350, 499},
            })
        result = run_ohlc_breakout_lab(bars)
        benchmark = result["strategies"]["buy_and_hold_25pct"]["out_of_sample"]
        self.assertEqual(benchmark["entry_index"], 351)
        self.assertEqual(benchmark["exit_index"], 498)

    def test_forward_paper_accounts_persist_and_are_idempotent(self):
        import tempfile

        candles = []
        for index in range(24 * 210):
            timestamp = index * INTERVAL_MS
            price = 50000.0 + index * 2.0
            candles.append({
                "timestamp": timestamp,
                "open": price,
                "high": price + 5,
                "low": price - 5,
                "close": price + 2,
                "volume": 3.0,
                "imputed": False,
            })
        future_candles = list(candles)
        for index in range(24 * 210, 24 * 211):
            timestamp = index * INTERVAL_MS
            price = 50000.0 + index * 2.0
            future_candles.append({
                "timestamp": timestamp,
                "open": price,
                "high": price + 5,
                "low": price - 5,
                "close": price + 2,
                "volume": 3.0,
                "imputed": False,
            })
        with tempfile.TemporaryDirectory() as folder:
            first = run_forward_paper_accounts(candles, state_dir=folder)
            second = run_forward_paper_accounts(candles, state_dir=folder)
            third = run_forward_paper_accounts(future_candles, state_dir=folder)
        self.assertEqual(first["daily_sma20_50"]["processed_new_candles"], 210)
        self.assertEqual(first["four_hour_ema50_200"]["processed_new_candles"], 1260)
        self.assertEqual(first["daily_bollinger_mean_reversion"]["processed_new_candles"], 210)
        self.assertEqual(first["six_hour_rsi14_mean_reversion"]["processed_new_candles"], 840)
        ensemble = first["ema50_200_4h_6h_50_50_portfolio"]
        self.assertEqual(ensemble["initial_cash_usd"], 1000.0)
        self.assertEqual(ensemble["sleeves"]["4h"]["initial_cash_usd"], 500.0)
        self.assertEqual(ensemble["sleeves"]["6h"]["initial_cash_usd"], 500.0)
        self.assertEqual(ensemble["sleeves"]["4h"]["processed_new_candles"], 1260)
        self.assertEqual(ensemble["sleeves"]["6h"]["processed_new_candles"], 840)
        self.assertEqual(second["ema50_200_4h_6h_50_50_portfolio"]["sleeves"]["4h"]["processed_new_candles"], 0)
        self.assertEqual(second["ema50_200_4h_6h_50_50_portfolio"]["sleeves"]["6h"]["processed_new_candles"], 0)
        self.assertEqual(second["daily_sma20_50"]["processed_new_candles"], 0)
        self.assertEqual(second["four_hour_ema50_200"]["processed_new_candles"], 0)
        self.assertEqual(second["daily_bollinger_mean_reversion"]["processed_new_candles"], 0)
        self.assertEqual(second["six_hour_rsi14_mean_reversion"]["processed_new_candles"], 0)
        forward = first["forward_only_ema50_200_4h_6h_50_50_portfolio"]
        self.assertEqual(forward["mode"], "GENUINE_FORWARD_ONLY_50_50_PAPER")
        self.assertEqual(forward["initial_cash_usd"], 1000.0)
        self.assertEqual(forward["completed_trades"], 0)
        self.assertEqual(forward["return_pct"], 0.0)
        self.assertTrue(forward["seed"]["4h"]["created"])
        self.assertTrue(forward["seed"]["6h"]["created"])
        self.assertEqual(forward["sleeves"]["4h"]["processed_new_candles"], 0)
        self.assertEqual(forward["sleeves"]["6h"]["processed_new_candles"], 0)
        self.assertFalse(forward["sleeves"]["4h"]["risk_pause_reasons"])
        self.assertFalse(forward["sleeves"]["6h"]["risk_pause_reasons"])
        self.assertFalse(second["forward_only_ema50_200_4h_6h_50_50_portfolio"]["seed"]["4h"]["created"])
        self.assertEqual(second["forward_only_ema50_200_4h_6h_50_50_portfolio"]["sleeves"]["4h"]["processed_new_candles"], 0)
        self.assertEqual(third["forward_only_ema50_200_4h_6h_50_50_portfolio"]["sleeves"]["4h"]["processed_new_candles"], 6)
        self.assertEqual(third["forward_only_ema50_200_4h_6h_50_50_portfolio"]["sleeves"]["6h"]["processed_new_candles"], 4)

    def test_turtle_breakout_uses_prior_channel_and_reports_costs(self):
        bars = []
        for index in range(600):
            close = 100.0 + index * 1.0
            bars.append({
                "timestamp": index * 86400000,
                "open": close - 0.1,
                "high": close + 0.5,
                "low": close - 0.5,
                "close": close,
                "volume": 10.0,
                "imputed": False,
            })
        signals = _turtle_signals(bars, 55, 20)
        self.assertFalse(signals[54])
        self.assertTrue(signals[55])
        result = run_ohlc_breakout_lab(bars)
        self.assertIn("donchian_55_20_sma200", result["strategies"])
        self.assertIn("donchian_55_20_sma200_atr3_trailing", result["strategies"])
        expected_families = (
            "donchian_10_5", "donchian_20_10", "donchian_40_20",
            "donchian_55_20", "donchian_100_50",
            "donchian_20_10_sma200", "donchian_55_20_sma200",
            "donchian_100_50_sma200",
            "donchian_55_20_atr2_5_trailing",
            "donchian_55_20_atr3_trailing",
            "donchian_55_20_atr4_trailing",
            "donchian_55_20_sma200_atr3_trailing",
        )
        for name in expected_families:
            self.assertIn(name, result["strategies"])
            self.assertEqual(len(result["strategies"][name]["walk_forward_windows"]), 3)
            self.assertIn(name, result["cost_sensitivity"]["1x"]["strategies"])

        self.assertIn("buy_and_hold_25pct", result["strategies"])
        self.assertTrue(all(
            window["start_index"] >= result["split_index"]
            for window in result["strategies"]["donchian_55_20"]["walk_forward_windows"]
        ))
        self.assertTrue(math.isfinite(result["strategies"]["donchian_55_20"]["out_of_sample"]["return_pct"]))
        self.assertEqual(list(result["cost_sensitivity"]), ["1x", "1.5x", "2x", "3x"])
        base = result["strategies"]["donchian_55_20"]["out_of_sample"]
        one_x = result["cost_sensitivity"]["1x"]["strategies"]["donchian_55_20"]
        self.assertEqual(one_x["return_pct"], base["return_pct"])
        self.assertEqual(
            one_x["benchmark_edge_pp"],
            round(base["return_pct"] - result["strategies"]["buy_and_hold_25pct"]["out_of_sample"]["return_pct"], 2),
        )
        self.assertGreater(
            result["cost_sensitivity"]["3x"]["fee_rate_each_side"],
            result["cost_sensitivity"]["1x"]["fee_rate_each_side"],
        )

    def test_atr_trailing_exit_uses_completed_close_and_next_bar_execution(self):
        bars = []
        for index in range(56):
            close = 100.0 + index
            bars.append({"open": close - 0.1, "high": close + 0.2, "low": close - 0.2, "close": close, "volume": 1.0})
        close = 140.0
        bars.append({"open": 155.0, "high": 155.2, "low": 139.8, "close": close, "volume": 1.0})
        signals = _turtle_signals(bars, 55, 20, atr_stop_multiple=3.0)
        self.assertTrue(signals[55])
        self.assertFalse(signals[56])
        combined = _turtle_signals(bars, 55, 20, regime_period=50, atr_stop_multiple=3.0)
        self.assertTrue(combined[55])
        with self.assertRaises(ValueError):
            _turtle_signals(bars, 55, 20, atr_stop_multiple=0)
    def test_ohlc_drawdown_includes_open_position_liquidation_costs(self):
        bars = [
            {"open": 100.0, "high": 101.0, "low": 99.0, "close": 100.0, "volume": 1.0},
            {"open": 100.0, "high": 101.0, "low": 99.0, "close": 100.0, "volume": 1.0},
            {"open": 50.0, "high": 51.0, "low": 49.0, "close": 50.0, "volume": 1.0},
        ]
        fee = 0.01
        slippage = 0.02
        result = _simulate_ohlc(bars, [True, True, True], 1, 3, fee, slippage)

        allocation = 250.0
        units = (allocation - allocation * fee) / (100.0 * (1 + slippage))
        expected_equity = 750.0 + units * 50.0 * (1 - slippage) * (1 - fee)
        expected_drawdown = (1000.0 - expected_equity) / 1000.0 * 100
        self.assertAlmostEqual(result["max_drawdown_pct"], round(expected_drawdown, 2), places=2)
        self.assertAlmostEqual(result["final_equity_usd"], round(expected_equity, 2), places=2)

    def test_atr_series_uses_prior_close_and_wilder_smoothing(self):
        bars = [
            {"high": 101.0 + i, "low": 99.0 + i, "close": 100.0 + i}
            for i in range(20)
        ]
        values = _atr_series(bars, 14)
        self.assertIsNone(values[13])
        self.assertAlmostEqual(values[14], 2.0)
        self.assertAlmostEqual(values[-1], 2.0)
        with self.assertRaises(ValueError):
            _atr_series(bars[:2], 2)

    def test_wilder_rsi_series_validates_and_tracks_momentum(self):
        rising = [100.0 + index for index in range(30)]
        values = _rsi_series(rising, 14)
        self.assertIsNone(values[13])
        self.assertEqual(values[14], 100.0)
        self.assertEqual(values[-1], 100.0)
        with self.assertRaises(ValueError):
            _rsi_series([1.0, 2.0], 2)

    def test_multi_timeframe_ensemble_uses_completed_4h_and_6h_series(self):
        candles = []
        for index in range(24 * 210):
            timestamp = index * INTERVAL_MS
            price = 50000.0 + index * 0.2
            candles.append({
                "timestamp": timestamp,
                "open": price - 1,
                "high": price + 3,
                "low": price - 3,
                "close": price,
                "volume": 2.0,
                "imputed": False,
            })
        result = run_multi_timeframe_ensemble_lab(candles)
        self.assertEqual(result["bar_count_4h"], 24 * 210 // 4)
        self.assertEqual(result["bar_count_6h"], 24 * 210 // 6)
        self.assertIn("most recent fully closed 6h", result["execution"])
        candidate = result["strategies"]["ema50_200_4h_6h_consensus"]
        self.assertEqual(len(candidate["walk_forward_windows"]), 3)
        self.assertTrue(math.isfinite(candidate["out_of_sample"]["return_pct"]))
        self.assertIn("buy_and_hold_25pct", result["strategies"])
        portfolio = result["strategies"]["ema50_200_4h_6h_50_50_portfolio"]
        self.assertEqual(len(portfolio["walk_forward_windows"]), 3)
        self.assertEqual(portfolio["out_of_sample"]["sleeve_count"], 2)

    def test_native_timeframe_sleeves_match_same_total_initial_exposure(self):
        four_hour = [
            {"timestamp": index * 4 * 3600000, "open": 100.0, "high": 101.0,
             "low": 99.0, "close": 100.0, "volume": 1.0}
            for index in range(20)
        ]
        six_hour = [
            {"timestamp": index * 6 * 3600000, "open": 100.0, "high": 101.0,
             "low": 99.0, "close": 100.0, "volume": 1.0}
            for index in range(14)
        ]
        signals_4h = [True] * len(four_hour)
        signals_6h = [True] * len(six_hour)
        single = _simulate_ohlc(four_hour, signals_4h, 2, 17, 0.01, 0.02)
        combined = _simulate_equal_weight_multitimeframe(
            [four_hour, six_hour], [signals_4h, signals_6h], [4, 6],
            12 * 3600000, 72 * 3600000, 0.01, 0.02,
        )
        self.assertAlmostEqual(combined["final_equity_usd"], single["final_equity_usd"], places=2)
        self.assertAlmostEqual(combined["max_drawdown_pct"], single["max_drawdown_pct"], places=2)
        self.assertEqual(combined["sleeve_count"], 2)

    def test_daily_regime_filter_uses_complete_daily_history(self):
        candles = []
        for index in range(24 * 210):
            timestamp = index * INTERVAL_MS
            price = 50000.0 + index * 0.2
            candles.append({
                "timestamp": timestamp,
                "open": price - 1,
                "high": price + 3,
                "low": price - 3,
                "close": price,
                "volume": 2.0,
                "imputed": False,
            })
        result = run_daily_regime_filter_lab(candles)
        self.assertEqual(result["daily_bar_count"], 210)
        self.assertIn("ema50_200_with_daily_sma200", result["strategies"])
        self.assertIn("ema20_50_daily_sma200_rsi50", result["strategies"])
        self.assertIn("ema20_50_daily_sma200_rsi50_rising", result["strategies"])
        self.assertIn("ema20_50_daily_sma200_ema20_exit", result["strategies"])
        self.assertIn("ema20_50_daily_sma200_rsi45_exit", result["strategies"])
        self.assertIn("ema20_50_daily_sma200_atr3_trailing", result["strategies"])
        self.assertIn("regime_switching_atr3_long_short", result["strategies"])
        self.assertTrue(all(
            window["start_index"] >= result["split_index"]
            for window in result["strategies"]["ema50_200_with_daily_sma200"]["walk_forward_windows"]
        ))

        with self.assertRaises(ValueError):
            run_daily_regime_filter_lab(candles, funding_rate_per_8h=-0.1)

    def test_long_short_drawdown_includes_exit_costs_for_long_and_short(self):
        from historical_research import _simulate_long_short

        bars = [
            {"close": 100.0},
            {"close": 100.0},
            {"close": 100.0},
        ]
        fee = 0.01
        slippage = 0.02
        for direction in (1, -1):
            result = _simulate_long_short(
                bars, [direction, direction, direction], 1, 3,
                fee, slippage, funding_rate_per_8h=0.0, bar_hours=24,
            )
            entry_fill = 100.0 * (1 + direction * slippage)
            units = direction * 250.0 / entry_fill
            entry_fee = 250.0 * fee
            cash = 1000.0 - units * entry_fill - entry_fee
            exit_fill = 100.0 * (1 - direction * slippage)
            exit_fee = abs(units * exit_fill) * fee
            net_equity = cash + units * exit_fill - exit_fee
            expected_drawdown = (1000.0 - net_equity) / 1000.0 * 100.0
            self.assertAlmostEqual(
                result["max_drawdown_pct"], round(expected_drawdown, 2), places=2
            )

    def test_ohlc_benchmark_drawdown_includes_exit_costs(self):
        bars = [
            {"open": 100.0, "high": 101.0, "low": 99.0, "close": 100.0, "volume": 1.0}
            for _ in range(600)
        ]
        fee = 0.01
        slippage = 0.02
        result = run_ohlc_breakout_lab(bars, fee=fee, slippage=slippage)
        benchmark = result["strategies"]["buy_and_hold_25pct"]["out_of_sample"]
        units = (250.0 * (1 - fee)) / (100.0 * (1 + slippage))
        liquidation = units * 100.0 * (1 - slippage) * (1 - fee)
        expected_drawdown = (1000.0 - (750.0 + liquidation)) / 1000.0 * 100.0
        self.assertAlmostEqual(benchmark["max_drawdown_pct"], expected_drawdown, places=2)

    def test_long_short_research_charges_funding_and_matches_benchmark(self):
        bars = []
        for index in range(600):
            close = 50000.0 + index * 10.0
            bars.append({
                "timestamp": index * 86400000,
                "open": close - 1,
                "high": close + 5,
                "low": close - 5,
                "close": close,
                "volume": 10.0,
                "imputed": False,
            })
        result = run_long_short_lab(bars)
        self.assertIn("sma200_long_short", result["strategies"])
        self.assertIn("sma200_slope_20_long_short", result["strategies"])
        self.assertIn("ema50_200_slope_20_long_short", result["strategies"])
        self.assertIn("sma200_slope_50_long_short", result["strategies"])
        self.assertIn("donchian_20_10_long_short", result["strategies"])
        self.assertIn("buy_and_hold_25pct", result["strategies"])
        self.assertTrue(all(
            window["start_index"] >= result["split_index"]
            for window in result["strategies"]["sma200_long_short"]["walk_forward_windows"]
        ))
        metrics = result["strategies"]["sma200_long_short"]["out_of_sample"]
        self.assertGreater(metrics["funding_paid_usd"], 0)
        self.assertTrue(math.isfinite(metrics["return_pct"]))
        with self.assertRaises(ValueError):
            run_long_short_lab(bars, funding_rate_per_8h=-0.1)

    def test_turtle_breakout_rejects_invalid_ohlc(self):
        bars = []
        for index in range(600):
            price = 100.0 + index
            bars.append({
                "timestamp": index,
                "open": price,
                "high": price + 1,
                "low": price - 1,
                "close": price,
                "volume": 1.0,
            })
        bars[100]["high"] = bars[100]["open"] - 2
        with self.assertRaisesRegex(ValueError, "Invalid OHLC high"):
            run_ohlc_breakout_lab(bars)

    def test_invalid_ohlc_relationship_is_rejected(self):
        now = datetime(2026, 11, 7, 12, 0, tzinfo=timezone.utc)

        def invalid_page(start_ms, end_ms):
            rows = self.make_page(start_ms, end_ms)
            if rows:
                rows[0][2] = rows[0][1] - 5
            return rows

        with patch("historical_research.fetch_page", side_effect=invalid_page):
            with self.assertRaisesRegex(ValueError, "Impossible OHLC"):
                load_two_year_candles(days=45, now=now)


    def test_all_research_labs_receive_conservative_qualification(self):
        good = {
            "out_of_sample": {
                "return_pct": 4.0, "closed_trades": 35,
                "profit_factor": 1.5, "max_drawdown_pct": 6.0,
            },
            "walk_forward_windows": [
                {"metrics": {"return_pct": 1.0, "closed_trades": 12}},
                {"metrics": {"return_pct": 0.5, "closed_trades": 11}},
                {"metrics": {"return_pct": 2.0, "closed_trades": 12}},
            ],
        }
        weak = {
            "out_of_sample": {
                "return_pct": 4.0, "closed_trades": 5,
                "profit_factor": 1.5, "max_drawdown_pct": 6.0,
            },
            "walk_forward_windows": good["walk_forward_windows"],
        }
        research = {"strategies": {
            "candidate": good,
            "small_sample": weak,
            "buy_and_hold_25pct": {
                **good,
                "out_of_sample": {**good["out_of_sample"], "return_pct": 3.0},
            },
        }}
        stress = {"strategies": {
            "candidate": {"out_of_sample": {"return_pct": 1.0}},
            "small_sample": {"out_of_sample": {"return_pct": 1.0}},
            "buy_and_hold_25pct": {"out_of_sample": {"return_pct": 0.5}},
        }}
        result = assess_research_lab_qualification(research, stress)
        self.assertTrue(result["candidate"]["qualified_for_extended_paper_review"])
        self.assertFalse(result["small_sample"]["qualified_for_extended_paper_review"])
        self.assertNotIn("buy_and_hold_25pct", result)


    def test_qualification_report_discloses_failures_and_no_live_approval(self):
        result = {
            "source": "test source", "candles": 1000,
            "first_closed_candle_utc": "start", "last_closed_candle_utc": "end",
            "strategy_qualification_policy": {
                "minimum_oos_trades": 30, "minimum_profit_factor": 1.2,
                "maximum_oos_drawdown_pct": 10.0,
            },
            "strategy_qualification": {
                "1d": {
                    "bollinger": {
                        "qualified_for_extended_paper_review": False,
                        "failed_checks": ["minimum_oos_trades"],
                        "benchmark_comparison": {
                            "benchmark_available": True,
                            "oos_outperformance_pct_points": 8.87,
                            "stress_oos_outperformance_pct_points": 8.53,
                        },
                    },
                    "weak_edge": {
                        "qualified_for_extended_paper_review": False,
                        "failed_checks": ["minimum_oos_trades", "minimum_profit_factor"],
                        "benchmark_comparison": {
                            "benchmark_available": True,
                            "oos_outperformance_pct_points": 4.0,
                            "stress_oos_outperformance_pct_points": 3.0,
                        },
                    }
                }
            },
            "forward_paper_accounts": {
                "daily_sma20_50": {
                    "equity_after_estimated_exit_costs_usd": 891.87,
                    "return_pct": -10.81, "completed_trades": 6,
                    "win_rate_pct": 16.67, "profit_factor": 0.01,
                    "max_drawdown_pct": 10.81,
                    "risk_pause_reasons": ["maximum_drawdown"],
                },
                "four_hour_ema50_200": {
                    "equity_after_estimated_exit_costs_usd": 1324.68,
                    "return_pct": 32.47, "completed_trades": 96,
                    "win_rate_pct": 25.0, "profit_factor": 1.83,
                    "max_drawdown_pct": 9.23,
                    "risk_pause_reasons": ["consecutive_loss_limit"],
                },
            },
            "extended_lab_strategy_qualification": {
                "ohlc_breakout": {}, "long_short": {}, "daily_regime_filter": {},
            },
        }
        report = build_qualification_markdown(result)
        self.assertIn("NOT QUALIFIED", report)
        self.assertIn("minimum_oos_trades", report)
        self.assertIn("Qualified strategies: 0 / 2", report)
        self.assertIn("No strategy is approved for live trading", report)
        self.assertIn("Benchmark-edge research watchlist (diagnostic only)", report)
        self.assertIn("+8.87 pp base", report)
        self.assertIn("+8.53 pp elevated costs", report)
        self.assertIn("1 failed gate", report)
        self.assertIn("2 failed gates", report)
        self.assertLess(report.index("1d / bollinger"), report.index("1d / weak_edge"))
        self.assertIn("Persistent forward paper-account snapshot", report)
        self.assertIn("Daily SMA20/SMA50", report)
        self.assertIn("PAUSED — maximum_drawdown", report)
        self.assertIn("4h EMA50/EMA200", report)
        self.assertIn("PAUSED — consecutive_loss_limit", report)


    def test_qualification_summary_counts_gates_and_ranks_watchlist_diagnostically(self):
        passing = {
            "qualified_for_extended_paper_review": True,
            "failed_checks": [],
            "benchmark_comparison": {
                "benchmark_available": True,
                "oos_outperformance_pct_points": 2.0,
                "stress_oos_outperformance_pct_points": 1.0,
            },
        }
        close_but_failed = {
            "qualified_for_extended_paper_review": False,
            "failed_checks": ["minimum_profit_factor"],
            "benchmark_comparison": {
                "benchmark_available": True,
                "oos_outperformance_pct_points": 1.5,
                "stress_oos_outperformance_pct_points": 0.5,
            },
        }
        missing_benchmark = {
            "qualified_for_extended_paper_review": False,
            "failed_checks": ["outperform_buy_and_hold_oos"],
            "benchmark_comparison": {"benchmark_available": False},
        }
        result = summarize_qualification({
            "strategy_qualification": {
                "1h": {"passing": passing, "close": close_but_failed},
                "4h": {"missing": missing_benchmark},
            },
            "extended_lab_strategy_qualification": {
                "ohlc_breakout": {"candidate": close_but_failed},
                "long_short": {},
                "daily_regime_filter": {},
            },
        })
        self.assertEqual(result["qualified"], 1)
        self.assertEqual(result["tested"], 4)
        self.assertEqual(result["by_group"]["hourly_multi_timeframe"], {
            "qualified": 1, "tested": 3,
        })
        self.assertEqual(
            result["diagnostic_watchlist"][0]["strategy"],
            "1h / passing",
        )
        self.assertIn("does not waive", result["watchlist_note"])
        with self.assertRaises(ValueError):
            summarize_qualification({}, watchlist_limit=-1)

    def test_qualification_requires_outperformance_of_matched_benchmark(self):
        candidate = {
            "out_of_sample": {
                "return_pct": 1.5, "closed_trades": 40,
                "profit_factor": 1.8, "max_drawdown_pct": 5.0,
            },
            "walk_forward_windows": [
                {"metrics": {"return_pct": 1.0, "closed_trades": 12}},
                {"metrics": {"return_pct": 0.5, "closed_trades": 13}},
                {"metrics": {"return_pct": 1.0, "closed_trades": 15}},
            ],
        }
        stress = {"out_of_sample": {"return_pct": 1.0}}
        benchmark = {"out_of_sample": {"return_pct": 2.0}}
        stress_benchmark = {"out_of_sample": {"return_pct": 0.5}}

        missing_benchmark = assess_strategy_qualification(candidate, stress)
        self.assertFalse(missing_benchmark["qualified_for_extended_paper_review"])
        self.assertIn("outperform_buy_and_hold_oos", missing_benchmark["failed_checks"])
        self.assertFalse(missing_benchmark["benchmark_comparison"]["benchmark_available"])

        result = assess_strategy_qualification(
            candidate, stress,
            benchmark_metrics=benchmark,
            stress_benchmark_metrics=stress_benchmark,
        )
        self.assertFalse(result["qualified_for_extended_paper_review"])
        self.assertIn("outperform_buy_and_hold_oos", result["failed_checks"])
        self.assertTrue(result["checks"]["outperform_buy_and_hold_stress"])
        self.assertEqual(result["benchmark_comparison"]["oos_outperformance_pct_points"], -0.5)
        self.assertEqual(result["benchmark_comparison"]["stress_oos_outperformance_pct_points"], 0.5)

        stronger = {
            **candidate,
            "out_of_sample": {**candidate["out_of_sample"], "return_pct": 2.5},
        }
        passing = assess_strategy_qualification(
            stronger,
            stress,
            benchmark_metrics=benchmark,
            stress_benchmark_metrics=stress_benchmark,
        )
        self.assertTrue(passing["qualified_for_extended_paper_review"])


    def test_50_50_portfolio_qualification_uses_matched_50_50_benchmark(self):
        good = {
            "out_of_sample": {
                "return_pct": 4.0, "closed_trades": 40,
                "profit_factor": 1.5, "max_drawdown_pct": 6.0,
            },
            "walk_forward_windows": [
                {"metrics": {"return_pct": 1.0, "closed_trades": 12}},
                {"metrics": {"return_pct": 0.5, "closed_trades": 13}},
                {"metrics": {"return_pct": 2.0, "closed_trades": 15}},
            ],
        }
        stress_candidate = {"out_of_sample": {"return_pct": 3.0}}
        research = {"strategies": {
            "ema50_200_4h_6h_consensus": good,
            "ema50_200_4h_6h_50_50_portfolio": good,
            "buy_and_hold_25pct": {"out_of_sample": {"return_pct": 1.0}},
            "buy_and_hold_25pct_50_50_portfolio": {"out_of_sample": {"return_pct": 5.0}},
        }}
        stress = {"strategies": {
            "ema50_200_4h_6h_consensus": stress_candidate,
            "ema50_200_4h_6h_50_50_portfolio": stress_candidate,
            "buy_and_hold_25pct": {"out_of_sample": {"return_pct": 0.5}},
            "buy_and_hold_25pct_50_50_portfolio": {"out_of_sample": {"return_pct": 3.5}},
        }}
        result = assess_research_lab_qualification(research, stress)
        self.assertTrue(result["ema50_200_4h_6h_consensus"]["qualified_for_extended_paper_review"])
        portfolio = result["ema50_200_4h_6h_50_50_portfolio"]
        self.assertFalse(portfolio["qualified_for_extended_paper_review"])
        self.assertEqual(portfolio["benchmark_comparison"]["benchmark_oos_return_pct"], 5.0)

    def test_qualification_report_discloses_synthetic_gap_repairs(self):
        result = {
            "source": "test source", "candles": 1000,
            "first_closed_candle_utc": "start", "last_closed_candle_utc": "end",
            "data_quality": {
                "imputed_missing_hour_count": 20,
                "imputation_method": "forward-filled prior close with zero volume",
            },
            "strategy_qualification_policy": {
                "minimum_oos_trades": 30, "minimum_profit_factor": 1.2,
                "maximum_oos_drawdown_pct": 10.0,
            },
        }
        report = build_qualification_markdown(result)
        self.assertIn("Imputed missing hourly candles: 20 (2.0000% of the series)", report)
        self.assertIn("synthetic observations, not exchange trades", report)
        self.assertIn("forward-filled prior close with zero volume", report)


    def test_six_hour_atr_trailing_lab_uses_fixed_rule_and_reports_benchmark(self):
        hourly = []
        start = (1_700_000_000_000 // INTERVAL_MS) * INTERVAL_MS
        for index in range(6 * 520):
            close = 20000.0 + index * 0.8 + 250.0 * math.sin(index / 110.0)
            hourly.append({
                "timestamp": start + index * INTERVAL_MS,
                "open": close - 2.0,
                "high": close + 8.0,
                "low": close - 8.0,
                "close": close,
                "volume": 10.0,
            })
        result = run_six_hour_atr_trailing_lab(hourly)
        self.assertEqual(result["mode"], "SIX_HOUR_EMA50_200_EXIT_AND_ADX_CONFIRMATION_RESEARCH")
        self.assertEqual(result["atr_period"], 14)
        self.assertEqual(result["atr_trailing_multiple"], 2.5)
        self.assertEqual(len(result["strategies"]["ema50_200_atr2_5_trailing"]["walk_forward_windows"]), 3)
        self.assertIn("buy_and_hold_25pct", result["strategies"])
        self.assertEqual(len(result["strategies"]["ema50_200_close_below_ema50_exit"]["walk_forward_windows"]), 3)
        self.assertEqual(
            result["strategies"]["ema50_200_atr2_5_trailing"]["entry_rule"],
            result["strategies"]["ema50_200_close_below_ema50_exit"]["entry_rule"],
        )
        self.assertEqual(
            result["strategies"]["ema50_200_atr2_5_trailing"]["entry_bar_indices"][0],
            result["strategies"]["ema50_200_close_below_ema50_exit"]["entry_bar_indices"][0],
        )
        self.assertIn("next six-hour close", result["execution"])

    def test_six_hour_atr_trailing_lab_rejects_insufficient_data(self):
        with self.assertRaises(ValueError):
            run_six_hour_atr_trailing_lab([])


    def test_wilder_adx_directional_series_and_validation(self):
        bars = []
        for index in range(100):
            close = 100.0 + index * 2.0
            bars.append({
                "open": close - 0.5,
                "high": close + 1.0,
                "low": close - 1.0,
                "close": close,
                "volume": 10.0,
            })
        adx, plus_di, minus_di = _adx_di_series(bars, 14)
        self.assertIsNotNone(adx[-1])
        self.assertGreaterEqual(adx[-1], 20.0)
        self.assertGreater(plus_di[-1], minus_di[-1])
        with self.assertRaises(ValueError):
            _adx_di_series(bars[:20], 14)
        with self.assertRaises(ValueError):
            _adx_di_series(bars, True)

    def test_six_hour_ema_lab_reports_fixed_adx_variants(self):
        hourly = []
        start = (1_700_000_000_000 // INTERVAL_MS) * INTERVAL_MS
        for index in range(6 * 520):
            close = 20000.0 + index * 0.8 + 250.0 * math.sin(index / 110.0)
            hourly.append({
                "timestamp": start + index * INTERVAL_MS,
                "open": close - 2.0,
                "high": close + 8.0,
                "low": close - 8.0,
                "close": close,
                "volume": 10.0,
            })
        result = run_six_hour_atr_trailing_lab(hourly)
        self.assertEqual(result["adx_period"], 14)
        self.assertEqual(result["adx_entry_threshold"], 20.0)
        self.assertEqual(result["adx_thresholds_tested"], [15.0, 20.0, 25.0])
        for key in ("ema50_200_adx_entry_filter", "ema50_200_adx_entry_and_di_exit"):
            candidate = result["strategies"][key]
            self.assertEqual(len(candidate["walk_forward_windows"]), 3)
            self.assertIn("ADX(14) >= 20", candidate["entry_rule"])
            self.assertIn("out_of_sample", candidate)
        for threshold in (15, 25):
            candidate = result["strategies"][f"ema50_200_adx_{threshold}_entry_filter"]
            self.assertEqual(len(candidate["walk_forward_windows"]), 3)
            self.assertIn(f"ADX(14) >= {threshold}", candidate["entry_rule"])
            self.assertIn("out_of_sample", candidate)



    def test_qualification_markdown_includes_new_extended_groups_automatically(self):
        result = {
            "strategy_qualification_policy": {
                "minimum_oos_trades": 30,
                "minimum_trades_each_walk_forward_window": 5,
                "minimum_profit_factor": 1.2,
                "maximum_oos_drawdown_pct": 10.0,
            },
            "extended_lab_strategy_qualification": {
                "experimental_volume_profile": {
                    "candidate_alpha": {
                        "qualified_for_extended_paper_review": False,
                        "failed_checks": ["minimum_oos_trades"],
                        "benchmark_comparison": {"benchmark_available": False},
                    },
                },
            },
        }
        report = build_qualification_markdown(result)
        self.assertIn("## Experimental Volume Profile strategies", report)
        self.assertIn("candidate_alpha: NOT QUALIFIED", report)
    def test_qualification_summary_includes_volume_liquidity_group(self):
        qualification = {
            "qualified_for_extended_paper_review": True,
            "failed_checks": [],
            "benchmark_comparison": {
                "benchmark_available": True,
                "oos_outperformance_pct_points": 1.25,
                "stress_oos_outperformance_pct_points": 0.5,
            },
        }
        summary = summarize_qualification({
            "extended_lab_strategy_qualification": {
                "volume_liquidity_momentum": {
                    "volume_liquidity_candidate": qualification,
                },
            },
        })
        self.assertEqual(
            summary["by_group"]["volume_liquidity_momentum"],
            {"qualified": 1, "tested": 1},
        )
        self.assertEqual(
            summary["diagnostic_watchlist"][0]["group"],
            "volume_liquidity_momentum",
        )

    def test_default_research_run_preserves_legacy_paper_state_location(self):
        output, paper_state = _research_output_paths()
        self.assertEqual(str(output), ".")
        self.assertEqual(str(paper_state), ".")

    def test_explicit_research_output_and_paper_state_paths_are_isolated(self):
        output, paper_state = _research_output_paths("tmp/research-run")
        self.assertEqual(str(output), "tmp/research-run")
        self.assertEqual(str(paper_state), "tmp/research-run/paper_state")
        self.assertNotEqual(str(paper_state), ".")


if __name__ == "__main__":
    unittest.main()
