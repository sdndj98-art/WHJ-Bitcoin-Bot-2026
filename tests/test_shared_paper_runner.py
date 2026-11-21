import tempfile
import unittest
from pathlib import Path

from shared_paper_portfolio import SharedPaperPortfolio, SUPPORTED_STRATEGIES
from shared_paper_runner import _new_strategy_state, strategy_signal


class SharedPaperRunnerTests(unittest.TestCase):
    def test_seven_strategies_are_seeded_from_same_forward_cursor(self):
        rows = [[i * 3600, 1, 1, 1, 100 + i, 0] for i in range(220)]
        state = _new_strategy_state(rows)
        self.assertEqual(set(state), set(SUPPORTED_STRATEGIES))
        self.assertEqual({item["last_timestamp"] for item in state.values()}, {rows[-1][0]})
        self.assertTrue(all(len(item["recent_closes"]) == 200 for item in state.values()))

    def test_insufficient_history_never_emits_entry(self):
        for strategy in SUPPORTED_STRATEGIES:
            want_long, want_flat = strategy_signal(strategy, [100 + i for i in range(30)])
            self.assertFalse(want_long)
            self.assertFalse(want_flat)

    def test_trend_signals_are_boolean_and_use_prior_completed_history(self):
        rising = [100.0 + i for i in range(220)]
        for strategy in ("sma_trend", "ema_trend", "sma200_regime", "ema50_200_regime"):
            want_long, want_flat = strategy_signal(strategy, rising)
            self.assertIsInstance(want_long, bool)
            self.assertIsInstance(want_flat, bool)
            self.assertTrue(want_long)
            self.assertFalse(want_flat)

    def test_shared_strategy_cursor_persists_with_same_100_dollar_pool(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "shared.json"
            book = SharedPaperPortfolio(path, 100)
            cursor = {"sma_trend": {"last_timestamp": 123, "recent_closes": [1.0]}}
            book.save_strategy_state(cursor)
            restored = SharedPaperPortfolio(path, 100)
            self.assertEqual(restored.state["strategy_state"], cursor)
            self.assertEqual(restored.state["cash_usd"], 100.0)
            self.assertFalse(restored.state["live_trading_enabled"])


if __name__ == "__main__":
    unittest.main()
