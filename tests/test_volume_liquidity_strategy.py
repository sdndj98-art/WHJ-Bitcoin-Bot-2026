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

    def test_rejects_nonfinite_volume(self):
        bars = synthetic_bars()
        bars[300]["volume"] = float("nan")
        with self.assertRaisesRegex(ValueError, "finite"):
            _volume_liquidity_signals(bars)


if __name__ == "__main__":
    unittest.main()
