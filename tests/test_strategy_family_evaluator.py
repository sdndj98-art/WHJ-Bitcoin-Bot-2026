import unittest

from strategy_family_evaluator import evaluate_candidate

class StrategyFamilyEvaluatorTests(unittest.TestCase):
    def candles(self, opens):
        return [[i, x, x*1.01, x*0.99, x, 1000] for i, x in enumerate(opens)]

    def test_signal_at_close_fills_next_open_and_returns_following_open_interval(self):
        rows = self.candles([100, 110, 121, 133.1, 146.41])
        result = evaluate_candidate(rows, [True, True, True, True, True], 0, 0, 1)
        self.assertAlmostEqual(result["strategy"]["net_return"], 0.331)
        self.assertEqual(result["strategy"]["bars"], 3)

    def test_flat_candidate_has_no_market_exposure(self):
        result = evaluate_candidate(self.candles([100, 101, 102, 103]), [False]*4, 0, 0, 1)
        self.assertEqual(result["strategy"]["net_return"], 0)
        self.assertEqual(result["strategy"]["exposure"], 0)

    def test_turnover_costs_are_charged_on_entry_and_exit(self):
        rows = self.candles([100, 100, 110, 110, 110])
        signals = [True, False, False, False, False]
        result = evaluate_candidate(rows, signals, 0.01, 0, 1)
        no_cost = evaluate_candidate(rows, signals, 0, 0, 1)
        self.assertEqual(result["strategy"]["closed_trades"], 1)
        self.assertAlmostEqual(result["strategy"]["turnover"], 2.0)
        self.assertLess(result["strategy"]["net_return"], no_cost["strategy"]["net_return"])

    def test_future_signal_changes_do_not_change_prior_return_stream(self):
        rows = self.candles([100, 101, 102, 103, 104, 105])
        first = evaluate_candidate(rows, [True, True, False, False, False, False], 0, 0, 1)
        second = evaluate_candidate(rows, [True, True, True, True, True, True], 0, 0, 1)
        self.assertEqual(first["net_returns"][:1], second["net_returns"][:1])

    def test_misaligned_inputs_and_non_boolean_signals_fail_closed(self):
        rows = self.candles([100, 101, 102, 103])
        with self.assertRaises(ValueError):
            evaluate_candidate(rows, [True, False])
        with self.assertRaises(ValueError):
            evaluate_candidate(rows, [1, False, True, False])

    def test_invalid_cost_and_nonpositive_open_rejected(self):
        rows = self.candles([100, 101, 102, 103])
        with self.assertRaises(ValueError):
            evaluate_candidate(rows, [False]*4, -0.1, 0, 1)
        rows[2][1] = 0
        with self.assertRaises(ValueError):
            evaluate_candidate(rows, [False]*4)

if __name__ == "__main__":
    unittest.main()