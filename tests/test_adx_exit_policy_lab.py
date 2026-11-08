import math
import unittest
from unittest.mock import patch

from adx_exit_policy_lab import (
    _adx_atr_exit_signals,
    _adx_entry_ema_exit_signals,
    run_exit_policy_lab,
)


def hourly_candles(count=3600):
    rows = []
    previous = 100.0
    for index in range(count):
        close = 100.0 + index * 0.025 + 4.0 * math.sin(index / 19.0)
        open_price = previous
        rows.append({
            "timestamp": index * 3600000,
            "open": open_price,
            "high": max(open_price, close) + 0.8,
            "low": min(open_price, close) - 0.8,
            "close": close,
            "volume": 12.0,
            "imputed": False,
        })
        previous = close
    return rows


class AdxExitPolicyTests(unittest.TestCase):
    def test_ema_exit_holds_through_adx_weakness_until_regime_off(self):
        baseline = [True, True, True, False, True, True]
        confirmed = [True, False, False, False, False, True]
        with patch(
            "adx_exit_policy_lab._build_sleeve_signals",
            return_value=(baseline, confirmed),
        ):
            signals = _adx_entry_ema_exit_signals([{}] * len(baseline), 20.0)
        self.assertEqual(signals, [True, True, True, False, False, True])

    def test_atr_exit_rejects_invalid_multiple(self):
        bars = []
        with self.assertRaisesRegex(ValueError, "ATR multiple"):
            _adx_atr_exit_signals(bars, atr_multiple=0)
        with self.assertRaisesRegex(ValueError, "ATR multiple"):
            _adx_atr_exit_signals(bars, atr_multiple=True)

    def test_atr_exit_rejects_non_finite_multiple(self):
        for value in (float("nan"), float("inf"), float("-inf")):
            with self.subTest(value=value):
                with self.assertRaisesRegex(ValueError, "finite positive"):
                    _adx_atr_exit_signals([], atr_multiple=value)

    def test_atr_trailing_stop_exits_on_completed_bar_close(self):
        bars = [
            {"open": 99.0, "high": 100.0, "low": 98.0, "close": 99.0, "volume": 1.0},
            {"open": 99.0, "high": 110.0, "low": 99.0, "close": 100.0, "volume": 1.0},
            {"open": 100.0, "high": 101.0, "low": 99.0, "close": 100.0, "volume": 1.0},
        ]
        with (
            patch("adx_exit_policy_lab._build_sleeve_signals",
                  return_value=([True, True, True], [True, True, True])),
            patch("adx_exit_policy_lab._adx_di_series",
                  return_value=([25.0] * 3, [2.0] * 3, [1.0] * 3)),
            patch("adx_exit_policy_lab._atr_series", return_value=[1.0] * 3),
        ):
            signals = _adx_atr_exit_signals(bars, 20.0, 2.5)
        self.assertEqual(signals, [True, False, True])

    def test_atr_exit_signal_is_bar_causal(self):
        hourly = hourly_candles()
        from historical_research import aggregate_candles
        bars = aggregate_candles(hourly, 4)
        full = _adx_atr_exit_signals(bars, 20.0, 3.0)
        cutoff = len(bars) - 20
        prefix = _adx_atr_exit_signals(bars[:cutoff], 20.0, 3.0)
        self.assertEqual(prefix, full[:cutoff])

    def test_exit_lab_compares_same_entry_and_keeps_safety(self):
        report = run_exit_policy_lab(hourly_candles())
        self.assertTrue(report["research_only"])
        self.assertFalse(report["paper_state_touched"])
        self.assertFalse(report["live_orders_enabled"])
        self.assertEqual(
            set(report["results"]),
            {"ema_regime_exit", "atr_trailing_2.5x", "atr_trailing_3x", "atr_trailing_4x"},
        )
        self.assertEqual(report["shared_12h_boundary_count"] > 0, True)
        self.assertEqual(len(report["temporal_subperiods"]), 3)
        self.assertIn("matched_50_50_buy_and_hold", report["results"])
        self.assertIn("3x", report["cost_sensitivity"])
        for name in ("ema_regime_exit", "atr_trailing_2.5x", "atr_trailing_3x", "atr_trailing_4x"):
            result = report["results"][name]
            self.assertIn("return_pct", result["base_cost"])
            self.assertIn("return_pct", result["double_cost"])
            self.assertIn("return_pct", result["triple_cost"])
            self.assertGreaterEqual(result["base_cost"]["max_drawdown_pct"], 0)
            self.assertEqual(report["temporal_subperiod_robustness"][name]["fold_count"], 3)


if __name__ == "__main__":
    unittest.main()
