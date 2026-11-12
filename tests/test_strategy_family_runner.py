import unittest

from strategy_family_runner import run_strategy_universe

class StrategyFamilyRunnerTests(unittest.TestCase):
    def candles(self, count=260):
        rows = []
        price = 100.0
        for i in range(count):
            price *= 1.001 if i % 17 else 0.997
            rows.append([i, price, price*1.01, price*0.99, price, 1000.0])
        return rows

    def test_all_candidates_use_same_protocol_and_are_not_promoted(self):
        result = run_strategy_universe(self.candles(), 0.001, 0.0005, 24*365)
        self.assertEqual(result["candidate_count"], 17)
        self.assertEqual(set(result["results"]), set(result["descriptive_ranking_by_terminal_excess_equity"]))
        self.assertEqual(result["promotion_status"], "NO_CANDIDATE_PROMOTED")
        self.assertEqual(result["allocation_fraction"], 0.25)
        self.assertEqual(result["allocation_cap_fraction"], 0.25)
        for candidate in result["results"].values():
            self.assertEqual(candidate["protocol"], "completed_close_signal_next_open_fill_open_to_open_return")
            self.assertEqual(candidate["strategy"]["bars"], candidate["buy_and_hold"]["bars"])
            self.assertEqual(candidate["allocation_fraction"], 0.25)
            self.assertLessEqual(candidate["strategy"]["exposure"], 0.25)

    def test_lower_allocation_is_allowed_but_cap_cannot_be_raised(self):
        reduced = run_strategy_universe(self.candles(), allocation_fraction=0.10)
        self.assertEqual(reduced["allocation_fraction"], 0.10)
        with self.assertRaises(ValueError):
            run_strategy_universe(self.candles(), allocation_fraction=0.250001)
        with self.assertRaises(ValueError):
            run_strategy_universe(self.candles(), allocation_fraction=1.0)

    def test_oos_start_uses_previous_completed_bar_for_first_next_open_fill(self):
        candles = self.candles()
        result = run_strategy_universe(candles, evaluation_start_index=200)
        self.assertEqual(result["evaluation_start_index"], 200)
        for candidate in result["results"].values():
            self.assertEqual(candidate["strategy"]["bars"], len(candles)-201)
            self.assertEqual(candidate["strategy"]["bars"], candidate["buy_and_hold"]["bars"])

    def test_invalid_oos_start_fails_closed(self):
        candles = self.candles()
        for index in (True, 0, len(candles)-2, len(candles)):
            with self.subTest(index=index):
                with self.assertRaises(ValueError):
                    run_strategy_universe(candles, evaluation_start_index=index)

    def test_ranking_is_deterministic(self):
        candles = self.candles()
        first = run_strategy_universe(candles)
        second = run_strategy_universe(candles)
        self.assertEqual(first["descriptive_ranking_by_terminal_excess_equity"], second["descriptive_ranking_by_terminal_excess_equity"])

if __name__ == "__main__":
    unittest.main()
