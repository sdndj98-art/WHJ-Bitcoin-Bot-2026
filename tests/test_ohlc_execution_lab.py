import unittest

from ohlc_execution_lab import simulate_ohlc_risk


class OhlcExecutionLabTests(unittest.TestCase):
    def test_signal_executes_at_next_open_not_signal_close(self):
        result = simulate_ohlc_risk(
            [100, 101, 103], [101, 104, 105], [99, 100, 102],
            [100, 103, 104], [False, True, False], [False, False, False],
            fee=0, slippage=0, stop_loss_pct=0.5, take_profit_pct=0.5,
        )
        # Entry at bar 2 open (103), with 25% of initial capital invested.
        self.assertEqual(result["open_position_count"], 1)
        self.assertAlmostEqual(result["final_net_liquidation_equity_usd"], 1002.4272, places=3)

    def test_gap_through_stop_fills_at_open_not_stop(self):
        result = simulate_ohlc_risk(
            [100, 100, 90], [101, 101, 95], [99, 99, 85],
            [100, 100, 92], [True, False, False], [False, False, False],
            fee=0, slippage=0, stop_loss_pct=0.05, take_profit_pct=0.5,
        )
        event = result["exit_events"][0]
        self.assertEqual(event["reason"], "stop_loss_gap")
        self.assertTrue(event["gap_through_stop"])
        self.assertEqual(event["raw_reference_price"], 90.0)

    def test_same_bar_stop_and_target_uses_adverse_stop_first(self):
        result = simulate_ohlc_risk(
            [100, 100, 100], [101, 110, 101], [99, 90, 99],
            [100, 100, 100], [True, False, False], [False, False, False],
            fee=0, slippage=0, stop_loss_pct=0.05, take_profit_pct=0.05,
        )
        event = result["exit_events"][0]
        self.assertEqual(event["reason"], "stop_loss_adverse_order")
        self.assertEqual(event["raw_reference_price"], 95.0)

    def test_intrabar_drawdown_exceeds_close_only_when_low_wicks(self):
        result = simulate_ohlc_risk(
            [100, 100, 100], [101, 102, 105], [99, 80, 99],
            [100, 101, 104], [False, True, False], [False, False, False],
            fee=0, slippage=0, stop_loss_pct=0.5, take_profit_pct=0.5,
        )
        self.assertGreater(
            result["max_intrabar_ohlc_envelope_drawdown_pct"],
            result["max_close_to_close_drawdown_pct"],
        )

    def test_realized_stop_loss_is_in_intrabar_drawdown(self):
        result = simulate_ohlc_risk(
            [100, 100, 100], [100, 100, 100], [99, 90, 99],
            [100, 100, 100], [True, False, False], [False, False, False],
            fee=0, slippage=0, stop_loss_pct=0.05, take_profit_pct=0.5,
        )
        self.assertEqual(result["exit_events"][0]["reason"], "stop_loss")
        self.assertAlmostEqual(
            result["max_intrabar_ohlc_envelope_drawdown_pct"], 1.25, places=4
        )


    def test_same_bar_high_peak_is_counted_before_realized_stop_exit(self):
        result = simulate_ohlc_risk(
            [100, 100, 100], [101, 101, 120], [99, 99, 95],
            [100, 100, 100], [True, False, False], [False, False, False],
            fee=0, slippage=0, stop_loss_pct=0.05, take_profit_pct=0.04,
        )
        self.assertEqual(
            result["exit_events"][0]["reason"], "stop_loss_adverse_order"
        )
        # 25% of $1,000 buys 2.5 units: bar high marks $1,050,
        # and the 5% stop exits at $987.50. The envelope DD is peak-to-fill.
        self.assertAlmostEqual(
            result["max_intrabar_ohlc_envelope_drawdown_pct"],
            (1050.0 - 987.5) / 1050.0 * 100.0,
            places=4,
        )

    def test_next_open_signal_exit_loss_is_in_intrabar_drawdown(self):
        result = simulate_ohlc_risk(
            [100, 100, 90], [101, 101, 91], [99, 99, 89],
            [100, 100, 90], [True, False, False], [False, True, False],
            fee=0, slippage=0, stop_loss_pct=0.5, take_profit_pct=0.5,
        )
        self.assertEqual(result["exit_events"][0]["reason"], "signal_exit_at_next_open")
        self.assertGreater(result["max_intrabar_ohlc_envelope_drawdown_pct"], 0.0)

    def test_allocation_cap_and_ohlc_validation_fail_closed(self):
        args = dict(
            opens=[100, 100], highs=[101, 101], lows=[99, 99],
            closes=[100, 100], entry_signals=[False, False],
            exit_signals=[False, False],
        )
        with self.assertRaises(ValueError):
            simulate_ohlc_risk(**args, allocation_fraction=0.30)
        with self.assertRaises(ValueError):
            simulate_ohlc_risk(
                [100, 100], [101, 98], [99, 99], [100, 100],
                [False, False], [False, False],
            )


if __name__ == "__main__":
    unittest.main()
