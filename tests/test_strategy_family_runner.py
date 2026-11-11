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
        for candidate in result["results"].values():
            self.assertEqual(candidate["protocol"], "completed_close_signal_next_open_fill_open_to_open_return")
            self.assertEqual(candidate["strategy"]["bars"], candidate["buy_and_hold"]["bars"])

    def test_ranking_is_deterministic(self):
        candles = self.candles()
        first = run_strategy_universe(candles)
        second = run_strategy_universe(candles)
        self.assertEqual(first["descriptive_ranking_by_terminal_excess_equity"], second["descriptive_ranking_by_terminal_excess_equity"])

if __name__ == "__main__":
    unittest.main()