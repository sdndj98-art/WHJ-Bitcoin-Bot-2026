import unittest

from advanced_market_analysis import analyze_advanced_market, _rsi, _efficiency_ratio


def sample_candles(count=80, final_volume=300.0, final_close=None):
    rows = []
    price = 100.0
    for i in range(count):
        price += 0.08 + (0.015 if i % 3 else -0.01)
        op = price - 0.04
        close = price
        high = price + 0.12
        low = price - 0.12
        volume = 100.0 + (i % 5) * 2.0
        if i == count - 1:
            volume = final_volume
            if final_close is not None:
                close = final_close
                high = max(high, close + 0.05)
            # Large bullish body with close near high.
            op = close - 1.0
            high = close + 0.05
            low = op - 0.05
        rows.append([i * 3600, op, high, low, close, 0.0, volume, 20])
    return rows


class AdvancedMarketAnalysisTests(unittest.TestCase):
    def test_returns_separate_bullish_and_bearish_diagnostics(self):
        result = analyze_advanced_market(sample_candles())
        self.assertIn("bullish_score", result)
        self.assertIn("bearish_score", result)
        self.assertEqual(result["score_total"], 10)
        self.assertEqual(result["version"], "advanced_ohlcv_confluence_v2")
        self.assertTrue(result["research_only"])
        self.assertFalse(result["execution_enabled"])
        self.assertFalse(result["live_orders_placed"])

    def test_relative_volume_uses_prior_bars_not_current_bar(self):
        rows = sample_candles(final_volume=300.0)
        result = analyze_advanced_market(rows)
        self.assertGreater(result["relative_volume"], 2.0)
        self.assertAlmostEqual(result["average_prior_volume"],
                               sum(r[6] for r in rows[-21:-1]) / 20)

    def test_zero_volume_is_safe_and_does_not_invent_volume_confirmation(self):
        rows = sample_candles()
        for row in rows:
            row[6] = 0.0
        result = analyze_advanced_market(rows)
        self.assertEqual(result["relative_volume"], 0.0)
        self.assertEqual(result["cmf20"], 0.0)
        self.assertAlmostEqual(result["rolling_vwap20"], rows[-1][4], places=6)

    def test_bullish_liquidity_sweep_detected_on_reclaim(self):
        rows = sample_candles()
        prior_low = min(r[3] for r in rows[-21:-1])
        rows[-1][3] = prior_low - 0.2
        rows[-1][4] = prior_low + 0.1
        rows[-1][1] = prior_low + 0.05
        rows[-1][2] = prior_low + 0.15
        result = analyze_advanced_market(rows)
        self.assertTrue(result["bullish_liquidity_sweep"])

    def test_bullish_bos_uses_previous_swing_high(self):
        rows = sample_candles()
        prior_high = max(r[2] for r in rows[-21:-1])
        rows[-1][4] = prior_high + 0.5
        rows[-1][1] = prior_high - 0.1
        rows[-1][2] = prior_high + 0.6
        rows[-1][3] = prior_high - 0.2
        result = analyze_advanced_market(rows)
        self.assertTrue(result["bullish_bos"])

    def test_accepts_scanner_normalized_six_column_rows(self):
        rows = [[r[0], r[1], r[2], r[3], r[4], r[6]] for r in sample_candles()]
        result = analyze_advanced_market(rows)
        self.assertIn(result["status"], (
            "BULLISH_RESEARCH_CANDIDATE", "BEARISH_RESEARCH_CANDIDATE", "WATCH"
        ))

    def test_rejects_invalid_and_non_monotonic_input(self):
        rows = sample_candles()
        rows[-1][6] = float("nan")
        with self.assertRaisesRegex(ValueError, "finite"):
            analyze_advanced_market(rows)
        rows = sample_candles()
        rows[-1][0] = rows[-2][0]
        with self.assertRaisesRegex(ValueError, "strictly increasing"):
            analyze_advanced_market(rows)

    def test_efficiency_ratio_confirms_directional_trend(self):
        rising = [100.0 + index for index in range(25)]
        ratio, direction = _efficiency_ratio(rising, 20)
        self.assertAlmostEqual(ratio, 1.0)
        self.assertAlmostEqual(direction, 1.0)

        falling = list(reversed(rising))
        ratio, direction = _efficiency_ratio(falling, 20)
        self.assertAlmostEqual(ratio, 1.0)
        self.assertAlmostEqual(direction, -1.0)

    def test_efficiency_ratio_rejects_choppy_path_and_flat_series(self):
        alternating = [100.0 + (1.0 if index % 2 else 0.0) for index in range(25)]
        ratio, direction = _efficiency_ratio(alternating, 20)
        self.assertLess(ratio, 0.10)
        self.assertAlmostEqual(direction, 0.0)
        self.assertEqual(_efficiency_ratio([100.0] * 25, 20), (0.0, 0.0))

    def test_efficiency_ratio_requires_valid_history_and_lookback(self):
        with self.assertRaisesRegex(ValueError, "Not enough"):
            _efficiency_ratio([100.0] * 20, 20)
        with self.assertRaisesRegex(ValueError, "integer"):
            _efficiency_ratio([100.0] * 25, True)

    def test_rsi_uses_wilder_recursive_smoothing(self):
        values = [100.0]
        for _ in range(14):
            values.append(values[-1] + 1.0)
        for _ in range(14):
            values.append(values[-1] - 1.0)
        expected = 100.0 * (13.0 / 14.0) ** 14
        self.assertAlmostEqual(_rsi(values, 14), expected, places=6)

    def test_flat_rsi_returns_neutral_value(self):
        self.assertEqual(_rsi([100.0] * 20, 14), 50.0)

    def test_requires_enough_history_and_valid_lookbacks(self):
        with self.assertRaisesRegex(ValueError, "At least"):
            analyze_advanced_market(sample_candles(20))
        with self.assertRaisesRegex(ValueError, "integer"):
            analyze_advanced_market(sample_candles(), volume_lookback=True)


if __name__ == "__main__":
    unittest.main()
