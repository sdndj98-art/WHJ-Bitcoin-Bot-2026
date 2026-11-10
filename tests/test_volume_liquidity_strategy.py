import unittest

from strategy_lab import _volume_liquidity_signals, run_volume_liquidity_lab


def synthetic_bars(count=900):
    rows = []
    price = 100.0
    for i in range(count):
        drift = 0.0008 if (i // 180) % 2 == 0 else -0.00015
        pulse = 0.0012 * ((i % 13) - 6) / 6
        previous = price
        price *= 1.0 + drift + pulse
        op = previous
        close = price
        spread = max(price * 0.002, 0.02)
        rows.append({
            "timestamp": i * 3600,
            "open": op,
            "high": max(op, close) + spread,
            "low": min(op, close) - spread,
            "close": close,
            "volume": 100.0 + (i % 9) * 7.0,
        })
    return rows


class VolumeLiquidityStrategyTests(unittest.TestCase):
    def test_signal_series_is_aligned_and_boolean(self):
        bars = synthetic_bars()
        signals, scores, diagnostics = _volume_liquidity_signals(bars)
        self.assertEqual(len(signals), len(bars))
        self.assertEqual(len(scores), len(bars))
        self.assertEqual(len(diagnostics), len(bars))
        self.assertTrue(all(isinstance(value, bool) for value in signals))
        self.assertTrue(all(0 <= value <= 9 for value in scores))

    def test_signal_series_is_prefix_causal(self):
        bars = synthetic_bars()
        full = _volume_liquidity_signals(bars)[0]
        prefix = _volume_liquidity_signals(bars[:700])[0]
        self.assertEqual(full[:700], prefix)

    def test_research_lab_rejects_invalid_cost_assumptions_and_bar_container(self):
        bars = synthetic_bars()
        for fee, slippage in ((True, 0.001), (0.001, float("nan")),
                              ("0.001", 0.001), (0.001, float("inf"))):
            with self.subTest(fee=fee, slippage=slippage):
                with self.assertRaisesRegex(ValueError, "finite number"):
                    run_volume_liquidity_lab(bars, fee=fee, slippage=slippage)
        with self.assertRaisesRegex(ValueError, "At least 300 OHLCV bars"):
            run_volume_liquidity_lab(None)

    def test_research_lab_validates_bars_before_extracting_close_prices(self):
        bars = synthetic_bars()
        del bars[350]["close"]
        with self.assertRaisesRegex(ValueError, "missing or non-numeric fields"):
            run_volume_liquidity_lab(bars)
    def test_research_report_has_holdout_and_three_walk_forward_windows(self):
        report = run_volume_liquidity_lab(synthetic_bars())
        self.assertEqual(report["mode"], "OHLCV_VOLUME_LIQUIDITY_RESEARCH_ONLY")
        self.assertFalse(report["execution_enabled"])
        self.assertTrue(report["research_only"])
        self.assertEqual(len(report["walk_forward_windows"]), 3)
        self.assertIn("out_of_sample", report)

    def test_rejects_invalid_ohlcv_and_duplicate_timestamps(self):
        bars = synthetic_bars()
        bars[10]["high"] = bars[10]["low"] - 1
        with self.assertRaisesRegex(ValueError, "inconsistent OHLC"):
            _volume_liquidity_signals(bars)
        bars = synthetic_bars()
        bars[10]["timestamp"] = bars[9]["timestamp"]
        with self.assertRaisesRegex(ValueError, "strictly increasing"):
            _volume_liquidity_signals(bars)

    def test_rejects_non_integer_and_non_numeric_timestamps(self):
        for value in (True, 36000.5, float("nan"), float("inf"), "36000"):
            with self.subTest(timestamp=value):
                bars = synthetic_bars()
                bars[10]["timestamp"] = value
                with self.assertRaisesRegex(ValueError, "timestamp must be a finite integer"):
                    _volume_liquidity_signals(bars)

    def test_rejects_irregular_timestamp_spacing(self):
        bars = synthetic_bars()
        bars[300]["timestamp"] += 1
        with self.assertRaisesRegex(ValueError, "evenly spaced"):
            _volume_liquidity_signals(bars)
    def test_simulator_skips_fills_on_imputed_execution_bars(self):
        prices = [100.0, 100.0, 110.0, 110.0]
        signals = [True, True, True, False]
        blocked = _simulate(prices, signals, 1, 4, blocked_execution_indices={1})
        immediate = _simulate(prices, signals, 1, 4)
        self.assertTrue(blocked["open_position"])
        self.assertGreater(blocked["final_equity_usd"], immediate["final_equity_usd"])
    def test_imputed_candles_block_signals_until_200_bar_context_clears(self):
        bars = synthetic_bars()
        bars[300]["imputed"] = True
        signals, _, diagnostics = _volume_liquidity_signals(bars)
        self.assertTrue(all(not value for value in signals[300:500]))
        self.assertTrue(all(
            diagnostics[index].get("data_quality_blocked", False)
            for index in range(300, 500)
        ))
        self.assertNotIn("data_quality_blocked", diagnostics[500])

    def test_rejects_non_boolean_imputed_flag(self):
        bars = synthetic_bars()
        bars[250]["imputed"] = "false"
        with self.assertRaisesRegex(ValueError, "imputed flag must be boolean"):
            _volume_liquidity_signals(bars)
    def test_rejects_nonfinite_volume(self):
        bars = synthetic_bars()
        bars[300]["volume"] = float("nan")
        with self.assertRaisesRegex(ValueError, "finite"):
            _volume_liquidity_signals(bars)


if __name__ == "__main__":
    unittest.main()
