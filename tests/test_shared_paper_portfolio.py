import tempfile
import unittest
from pathlib import Path
import json

from shared_paper_portfolio import SharedPaperPortfolio, SUPPORTED_STRATEGIES


class SharedPaperPortfolioTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.path = Path(self.temp.name) / "shared.json"
        self.book = SharedPaperPortfolio(self.path, initial_cash_usd=100.0, fee_rate=0.001)

    def tearDown(self):
        self.temp.cleanup()

    def test_single_100_dollar_pool_shared_across_strategies(self):
        self.book.open_position("sma_trend", "BTC/USD", 100, 30, "btc-a")
        self.book.open_position(
            "ema_trend", "XAU/USD", 200, 40, "gold-a"
        )
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
        trade = self.book.close_position("p1", 110, reason="take_profit")
        self.assertGreater(trade["pnl_usd"], 0)
        self.assertEqual(trade["exit_reason"], "take_profit")
        self.assertAlmostEqual(self.book.state["cash_usd"], 104.895)
        self.assertEqual(self.book.state["positions"], {})
        self.assertEqual(len(self.book.state["closed_trades"]), 1)

    def test_persistent_state_reloads_without_reset(self):
        self.book.open_position("ema_trend", "BTC/USD", 100, 25, "persist")
        restored = SharedPaperPortfolio(self.path, initial_cash_usd=100)
        self.assertAlmostEqual(restored.state["cash_usd"], 74.975)
        self.assertIn("persist", restored.state["positions"])

    def test_rejects_capital_mismatch_instead_of_resetting(self):
        with self.assertRaises(ValueError):
            SharedPaperPortfolio(self.path, initial_cash_usd=200)

    def test_all_eight_strategy_families_are_supported(self):
        self.assertEqual(len(SUPPORTED_STRATEGIES), 8)
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

    # Additional rigorous unit tests for input validation, edge cases, and fee/slippage accounting:

    def test_invalid_fee_rate_initialization(self):
        with self.assertRaises(ValueError):
            SharedPaperPortfolio(self.path, initial_cash_usd=100.0, fee_rate=1.0)
        with self.assertRaises(ValueError):
            SharedPaperPortfolio(self.path, initial_cash_usd=100.0, fee_rate=-0.01)
        with self.assertRaises(ValueError):
            SharedPaperPortfolio(self.path, initial_cash_usd=100.0, fee_rate="invalid")

    def test_invalid_initial_cash_validation(self):
        with self.assertRaises(ValueError):
            SharedPaperPortfolio(self.path, initial_cash_usd=0.0)
        with self.assertRaises(ValueError):
            SharedPaperPortfolio(self.path, initial_cash_usd=-10.0)
        with self.assertRaises(ValueError):
            SharedPaperPortfolio(self.path, initial_cash_usd="100")

    def test_open_position_input_validation(self):
        # Unsupported strategy
        with self.assertRaises(ValueError):
            self.book.open_position("unsupported_strategy", "BTC/USD", 100, 10)
        # Invalid asset type or empty asset
        with self.assertRaises(ValueError):
            self.book.open_position("sma_trend", "", 100, 10)
        with self.assertRaises(ValueError):
            self.book.open_position("sma_trend", 123, 100, 10)
        # Invalid price (non-finite or <= 0)
        with self.assertRaises(ValueError):
            self.book.open_position("sma_trend", "BTC/USD", 0, 10)
        with self.assertRaises(ValueError):
            self.book.open_position("sma_trend", "BTC/USD", -50, 10)
        with self.assertRaises(ValueError):
            self.book.open_position("sma_trend", "BTC/USD", float("nan"), 10)
        # Invalid notional (below minimum 0.01 or non-finite)
        with self.assertRaises(ValueError):
            self.book.open_position("sma_trend", "BTC/USD", 100, 0.0)
        with self.assertRaises(ValueError):
            self.book.open_position("sma_trend", "BTC/USD", 100, float("inf"))
        # Duplicate explicit position_id
        self.book.open_position("sma_trend", "BTC/USD", 100, 10, "unique-id")
        with self.assertRaises(ValueError):
            self.book.open_position("ema_trend", "ETH/USD", 100, 10, "unique-id")

    def test_close_position_input_validation(self):
        self.book.open_position("sma_trend", "BTC/USD", 100, 10, "p-close")
        # Unknown position id
        with self.assertRaises(ValueError):
            self.book.close_position("non-existent", 110)
        # Invalid exit price
        with self.assertRaises(ValueError):
            self.book.close_position("p-close", 0)
        with self.assertRaises(ValueError):
            self.book.close_position("p-close", -10)
        with self.assertRaises(ValueError):
            self.book.close_position("p-close", float("nan"))

    def test_snapshot_input_validation(self):
        self.book.open_position("sma_trend", "BTC/USD", 100, 10)
        with self.assertRaises(ValueError):
            self.book.snapshot("not-a-dict")
        with self.assertRaises(ValueError):
            self.book.snapshot({"BTC/USD": float("inf")})

    def test_corrupted_json_state_raises_value_error(self):
        self.path.write_text("{ invalid json ", encoding="utf-8")
        with self.assertRaises(ValueError):
            SharedPaperPortfolio(self.path, initial_cash_usd=100.0)

    def test_invalid_schema_or_mode_state_raises_value_error(self):
        # Unsupported schema version
        bad_state = {
            "schema_version": 999,
            "mode": "PAPER_ONLY",
            "live_trading_enabled": False,
            "initial_cash_usd": 100.0,
            "cash_usd": 100.0,
            "positions": {},
            "closed_trades": [],
            "fees_paid_usd": 0.0,
            "next_position_number": 1,
            "strategy_state": {},
        }
        self.path.write_text(json.dumps(bad_state), encoding="utf-8")
        with self.assertRaises(ValueError):
            SharedPaperPortfolio(self.path, initial_cash_usd=100.0)

        # Unsafe live trading enabled
        bad_state["schema_version"] = 1
        bad_state["live_trading_enabled"] = True
        self.path.write_text(json.dumps(bad_state), encoding="utf-8")
        with self.assertRaises(ValueError):
            SharedPaperPortfolio(self.path, initial_cash_usd=100.0)

    def test_save_strategy_state_validation(self):
        with self.assertRaises(ValueError):
            self.book.save_strategy_state(["not-a-dict"])

    def test_save_extension_state_validation(self):
        with self.assertRaises(ValueError):
            self.book.save_extension_state("schema_version", {"foo": "bar"})
        with self.assertRaises(ValueError):
            self.book.save_extension_state("", {"foo": "bar"})
        with self.assertRaises(ValueError):
            self.book.save_extension_state("custom_key", [1, 2, 3])

    def test_fee_and_realized_pnl_accounting_precision(self):
        # Verify exact fee deductions and P&L computation with non-zero fee rate
        book_fee = SharedPaperPortfolio(self.path, initial_cash_usd=100.0, fee_rate=0.01)
        res = book_fee.open_position("sma_trend", "BTC/USD", 100.0, 50.0, "pos-fee")
        # Notional 50, entry fee 0.50, total debit 50.50, cash remaining 49.50, fees paid 0.50
        self.assertAlmostEqual(res["cash_usd"], 49.50)
        self.assertAlmostEqual(book_fee.state["fees_paid_usd"], 0.50)

        # Close position at 120.0 (units = 50 / 100 = 0.5)
        # Gross proceeds = 0.5 * 120 = 60.0, exit fee = 60.0 * 0.01 = 0.60, net proceeds = 59.40
        # New cash = 49.50 + 59.40 = 108.90
        # Total fees paid = 0.50 + 0.60 = 1.10
        # PnL = net_proceeds (59.40) - entry_notional (50.0) - entry_fee (0.50) = 8.90
        trade = book_fee.close_position("pos-fee", 120.0)
        self.assertAlmostEqual(trade["gross_proceeds_usd"], 60.0)
        self.assertAlmostEqual(trade["fees_usd"], 1.10)
        self.assertAlmostEqual(trade["pnl_usd"], 8.90)
        self.assertAlmostEqual(book_fee.state["cash_usd"], 108.90)
        self.assertAlmostEqual(book_fee.state["fees_paid_usd"], 1.10)


if __name__ == "__main__":
    unittest.main()
