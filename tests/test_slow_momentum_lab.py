import math
import unittest

from slow_momentum_lab import (
    _simulate,
    evaluate_slow_momentum,
    momentum_signals,
)


class SlowMomentumLabTests(unittest.TestCase):
    def test_signal_uses_only_lookback_close_and_is_long_cash(self):
        closes = [100.0, 101.0, 99.0, 102.0, 103.0]
        self.assertEqual(
            momentum_signals(closes, 2),
            [False, False, False, True, True],
        )

    def test_signal_is_causal_under_truncated_history(self):
        closes = [100.0 + i * 0.1 + math.sin(i / 5) for i in range(220)]
        full = momentum_signals(closes, 56)
        for end in (57, 80, 120, 180, 220):
            truncated = momentum_signals(closes[:end], 56)
            self.assertEqual(full[:end], truncated)

    def test_future_prices_do_not_change_past_signals(self):
        closes = [100.0 + i * 0.2 for i in range(220)]
        original = momentum_signals(closes, 84)
        changed = closes[:150] + [value * 4 for value in closes[150:]]
        altered = momentum_signals(changed, 84)
        self.assertEqual(original[:150], altered[:150])

    def test_evaluation_reports_all_horizons_and_three_oos_windows(self):
        closes = [100.0 * math.exp(0.001 * i + 0.08 * math.sin(i / 17)) for i in range(500)]
        result = evaluate_slow_momentum(closes)
        self.assertEqual(set(result["candidates"]), {"56", "84", "112"})
        for candidate in result["candidates"].values():
            self.assertEqual(len(candidate["walk_forward_windows"]), 3)
        self.assertEqual(len(result["buy_and_hold_25pct"]["walk_forward_windows"]), 3)
        self.assertFalse(result["execution_enabled"])
        self.assertIn("84", result["cost_stress"]["2x"]["candidates"])
        self.assertIn("84", result["cost_stress"]["3x"]["candidates"])
        self.assertIn("out_of_sample", result["cost_stress"]["2x"]["matched_buy_and_hold"])
        self.assertEqual(len(result["cost_stress"]["3x"]["matched_buy_and_hold"]["walk_forward_windows"]), 3)

    def test_open_position_reports_unrealized_net_liquidation_pnl_separately(self):
        result = _simulate(
            [100.0, 100.0, 120.0, 132.0],
            [False, True, True, True],
            1, 4, 0.0, 0.0,
        )
        self.assertEqual(result["open_position_count"], 1)
        self.assertEqual(result["closed_trades"], 0)
        self.assertEqual(result["realized_pnl_usd"], 0.0)
        self.assertEqual(result["unrealized_net_liquidation_pnl_usd"], 25.0)
        self.assertEqual(result["final_net_liquidation_equity_usd"], 1025.0)
        self.assertEqual(result["closed_trade_profit_factor"], 0.0)
        self.assertEqual(
            result["drawdown_measurement"], "close_to_close_net_liquidation"
        )

    def test_closed_trade_pnl_is_realized_and_open_pnl_is_zero(self):
        result = _simulate(
            [100.0, 100.0, 120.0, 110.0],
            [False, True, False, False],
            1, 4, 0.0, 0.0,
        )
        self.assertEqual(result["open_position_count"], 0)
        self.assertEqual(result["closed_trades"], 1)
        self.assertAlmostEqual(result["realized_pnl_usd"], -20.8333, places=4)
        self.assertEqual(result["unrealized_net_liquidation_pnl_usd"], 0.0)
        self.assertAlmostEqual(
            result["final_net_liquidation_equity_usd"], 979.1667, places=4
        )
        self.assertEqual(result["closed_trade_profit_factor"], 0.0)

    def test_close_drawdown_field_is_explicit_and_legacy_alias_matches(self):
        result = _simulate(
            [100.0, 100.0, 120.0, 90.0],
            [False, True, True, True],
            1, 4, 0.0, 0.0,
        )
        self.assertEqual(
            result["max_close_to_close_drawdown_pct"], result["max_drawdown_pct"]
        )
        self.assertEqual(
            result["drawdown_measurement"], "close_to_close_net_liquidation"
        )

    def test_validation_rejects_bad_prices_and_parameters(self):
        with self.assertRaises(ValueError):
            evaluate_slow_momentum([100.0] * 159)
        with self.assertRaises(ValueError):
            evaluate_slow_momentum([100.0] * 200 + [float("nan")])
        with self.assertRaises(ValueError):
            momentum_signals([100.0, 101.0], True)
        with self.assertRaises(ValueError):
            evaluate_slow_momentum([100.0 + i for i in range(200)], lookbacks=(0,))


if __name__ == "__main__":
    unittest.main()
