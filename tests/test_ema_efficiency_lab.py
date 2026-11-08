import math
import unittest

from ema_efficiency_lab import (
    _efficiency_ratio_series,
    _build_sleeve_signals,
    run_ema_efficiency_filter_lab,
)


def hourly_candles(count=2400):
    rows = []
    previous = 100.0
    for index in range(count):
        close = 100.0 + index * 0.025 + 4.0 * math.sin(index / 19.0)
        open_price = previous
        rows.append({
            "timestamp": index * 3600000,
            "open": open_price,
            "high": max(open_price, close) + 0.5,
            "low": min(open_price, close) - 0.5,
            "close": close,
            "volume": 10.0,
            "imputed": False,
        })
        previous = close
    return rows


class EfficiencyRatioLabTests(unittest.TestCase):
    def test_efficiency_ratio_tracks_direction_and_chop(self):
        rising = [100.0 + index for index in range(25)]
        ratios, directions = _efficiency_ratio_series(rising, 20)
        self.assertAlmostEqual(ratios[-1], 1.0)
        self.assertAlmostEqual(directions[-1], 1.0)

        falling = list(reversed(rising))
        ratios, directions = _efficiency_ratio_series(falling, 20)
        self.assertAlmostEqual(ratios[-1], 1.0)
        self.assertAlmostEqual(directions[-1], -1.0)

        choppy = [100.0 + (1.0 if index % 2 else 0.0) for index in range(25)]
        ratios, directions = _efficiency_ratio_series(choppy, 20)
        self.assertLess(ratios[-1], 0.10)
        self.assertAlmostEqual(directions[-1], 0.0)

    def test_efficiency_ratio_rejects_bad_lookback_and_short_history(self):
        with self.assertRaisesRegex(ValueError, "integer"):
            _efficiency_ratio_series([100.0] * 25, True)
        with self.assertRaisesRegex(ValueError, "Not enough"):
            _efficiency_ratio_series([100.0] * 20, 20)

    def test_filter_only_removes_baseline_long_regime_bars(self):
        baseline, filtered = _build_sleeve_signals(
            [{"close": 100.0 + index} for index in range(250)], 0.35
        )
        self.assertTrue(all(not filtered[i] or baseline[i] for i in range(len(baseline))))
        self.assertFalse(any(filtered[:199]))
        self.assertTrue(any(filtered[199:]))

    def test_lab_compares_same_50_50_portfolio_and_cost_scenarios(self):
        report = run_ema_efficiency_filter_lab(hourly_candles())
        self.assertEqual(report["mode"], "EMA50_200_4H_6H_50_50_ER20_FILTER_RESEARCH")
        self.assertTrue(report["research_only"])
        self.assertFalse(report["paper_state_touched"])
        self.assertFalse(report["live_orders_enabled"])
        self.assertIn("baseline", report["out_of_sample"])
        self.assertIn("er20_filtered", report["out_of_sample"])
        self.assertIn("matched_50_50_benchmark", report["out_of_sample"])
        self.assertEqual(set(report["cost_sensitivity"]), {"1x", "2x"})
        self.assertEqual(len(report["walk_forward_windows"]), 3)
        self.assertGreaterEqual(report["signal_activity"]["reduction_pct"], 0.0)

    def test_lab_rejects_invalid_threshold(self):
        with self.assertRaisesRegex(ValueError, "threshold"):
            run_ema_efficiency_filter_lab(hourly_candles(), threshold=0.0)


if __name__ == "__main__":
    unittest.main()
