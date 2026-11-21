import tempfile
import unittest
from pathlib import Path

from shared_paper_portfolio import SharedPaperPortfolio, SUPPORTED_STRATEGIES


class SharedPaperPortfolioTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.path = Path(self.temp.name) / "shared.json"
        self.book = SharedPaperPortfolio(self.path, initial_cash_usd=100.0)

    def tearDown(self):
        self.temp.cleanup()

    def test_single_100_dollar_pool_shared_across_strategies(self):
        self.book.open_position("sma_trend", "BTC/USD", 100, 30, "btc-a")
        self.book.open_position("ema_trend", "XAU/USD", 200, 40, "gold-a")
        snap = self.book.snapshot({"BTC/USD": 100, "XAU/USD": 200})
        self.assertAlmostEqual(snap["initial_cash_usd"], 100)
        self.assertLess(snap["cash_usd"], 30)
        self.assertEqual(len(snap["open_positions"]), 2)
        self.assertAlmostEqual(snap["equity_usd"], 99.93)

    def test_prevents_double_spending_and_negative_cash(self):
        self.book.open_position("sma_trend", "BTC/USD", 100, 70)
        with self.assertRaises(ValueError):
            self.book.open_position("ema_trend", "BTC/USD", 100, 40)
        self.assertGreaterEqual(self.book.state["cash_usd"], 0)

    def test_entry_fee_is_reserved_before_accepting_trade(self):
        with self.assertRaises(ValueError):
            self.book.open_position("sma_trend", "BTC/USD", 100, 99.95)

    def test_duplicate_strategy_asset_position_is_rejected(self):
        self.book.open_position("sma_trend", "BTC/USD", 100, 10)
        with self.assertRaises(ValueError):
            self.book.open_position("sma_trend", "BTC/USD", 100, 10)

    def test_close_compounds_net_proceeds_and_tracks_fees(self):
        self.book.open_position("rsi_momentum", "BTC/USD", 100, 50, "p1")
        trade = self.book.close_position("p1", 110)
        self.assertGreater(trade["pnl_usd"], 0)
        self.assertAlmostEqual(self.book.state["cash_usd"], 104.895)
        self.assertEqual(self.book.state["positions"], {})

    def test_persistent_state_reloads_without_reset(self):
        self.book.open_position("ema_trend", "BTC/USD", 100, 25, "persist")
        restored = SharedPaperPortfolio(self.path, initial_cash_usd=100)
        self.assertAlmostEqual(restored.state["cash_usd"], 74.975)
        self.assertIn("persist", restored.state["positions"])

    def test_rejects_capital_mismatch_instead_of_resetting(self):
        with self.assertRaises(ValueError):
            SharedPaperPortfolio(self.path, initial_cash_usd=200)

    def test_all_seven_strategy_families_are_supported(self):
        self.assertEqual(len(SUPPORTED_STRATEGIES), 7)
        for strategy in SUPPORTED_STRATEGIES:
            self.book.open_position(strategy, strategy + "-asset", 10, 1)
        self.assertGreaterEqual(self.book.state["cash_usd"], 0)

    def test_requires_marks_for_every_open_position(self):
        self.book.open_position("sma_trend", "BTC/USD", 100, 10)
        with self.assertRaises(ValueError):
            self.book.snapshot({})

    def test_namespaced_extension_state_does_not_replace_btc_strategy_state(self):
        btc_state = {"sma_trend": {"last_timestamp": 123}}
        self.book.save_strategy_state(btc_state)
        self.book.save_extension_state("multi_asset_strategy_state", {
            "ETH/USD": {"ema_trend": {"last_timestamp": 456}}
        })
        restored = SharedPaperPortfolio(self.path, initial_cash_usd=100)
        self.assertEqual(restored.state["strategy_state"], btc_state)
        self.assertEqual(
            restored.state["multi_asset_strategy_state"]["ETH/USD"]["ema_trend"]["last_timestamp"],
            456,
        )


if __name__ == "__main__":
    unittest.main()
