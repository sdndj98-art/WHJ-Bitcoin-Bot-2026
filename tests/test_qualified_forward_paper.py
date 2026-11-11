import tempfile
import unittest

from historical_research import run_forward_paper_accounts
from paper_account import seed_forward_paper_account, update_paper_account
from strategy_lab import _signals


class QualifiedForwardPaperCandidateTests(unittest.TestCase):
    @staticmethod
    def candles(hours=24 * 220):
        rows = []
        for index in range(hours):
            price = 100.0 + index * 0.01
            rows.append({
                "timestamp": index * 60 * 60 * 1000,
                "open": price,
                "high": price + 0.2,
                "low": price - 0.2,
                "close": price,
                "volume": 10.0,
                "imputed": False,
            })
        return rows

    def test_qualified_candidates_seed_without_historical_trades_or_pnl(self):
        with tempfile.TemporaryDirectory() as folder:
            result = run_forward_paper_accounts(self.candles(), state_dir=folder)
            portfolio = result["forward_only_qualified_candidates"]
            self.assertEqual(portfolio["initial_cash_usd"], 750.0)
            self.assertEqual(portfolio["equity_after_estimated_exit_costs_usd"], 750.0)
            self.assertEqual(portfolio["return_pct"], 0.0)
            self.assertEqual(portfolio["completed_trades"], 0)
            self.assertEqual(
                set(portfolio["candidates"]),
                {"1d_sma_trend", "6h_ema50_200_regime", "6h_ema_pullback_trend"},
            )
            for account in portfolio["candidates"].values():
                self.assertEqual(account["initial_cash_usd"], 250.0)
                self.assertEqual(account["completed_trades"], 0)
                self.assertEqual(account["return_pct"], 0.0)
                self.assertEqual(account["processed_new_candles"], 0)

    def test_ema_pullback_forward_entry_matches_fixed_research_signal(self):
        prices = [100.0 + index * 0.5 for index in range(220)]
        self.assertTrue(_signals(prices)["ema_pullback_trend"][-1])
        candles = [
            [index * 6 * 3600, 0, 0, 0, str(price)]
            for index, price in enumerate(prices)
        ]
        with tempfile.TemporaryDirectory() as folder:
            path = f"{folder}/ema_pullback.json"
            seed = seed_forward_paper_account(
                candles, state_path=path, initial_cash=250.0,
                strategy="ema_pullback_trend",
            )
            self.assertTrue(seed["created"])
            seeded = update_paper_account(
                candles, state_path=path, initial_cash=250.0,
                strategy="ema_pullback_trend",
            )
            self.assertEqual(seeded["completed_trades"], 0)
            next_bar = [[len(prices) * 6 * 3600, 0, 0, 0, str(prices[-1] + 0.5)]]
            updated = update_paper_account(
                next_bar, state_path=path, initial_cash=250.0,
                strategy="ema_pullback_trend",
            )
            self.assertTrue(updated["open_position"])
            self.assertEqual(updated["completed_trades"], 0)

    def test_normal_exit_signal_on_synthetic_bar_is_recomputed_after_rebound(self):
        with tempfile.TemporaryDirectory() as folder:
            path = f"{folder}/paper.json"
            history = [
                [index * 3600, 0, 0, 0, str(100.0 + index)]
                for index in range(200)
            ]
            seed_forward_paper_account(
                history, state_path=path, initial_cash=1000.0,
                strategy="sma_trend",
            )
            limits = {
                "strategy": "sma_trend",
                "daily_loss_fraction": 0.99,
                "max_drawdown_fraction": 0.99,
            }
            opened = update_paper_account(
                [[200 * 3600, 0, 0, 0, "300", True]],
                state_path=path, **limits,
            )
            self.assertTrue(opened["open_position"])
            update_paper_account(
                [[201 * 3600, 0, 0, 0, "150", False]],
                state_path=path, **limits,
            )
            held = update_paper_account(
                [[202 * 3600, 0, 0, 0, "300", False]],
                state_path=path, **limits,
            )
            self.assertTrue(held["open_position"])
            self.assertFalse(held["pending_exit_on_next_executable"])
            rebound = update_paper_account(
                [[203 * 3600, 0, 0, 0, "310", True]],
                state_path=path, **limits,
            )
            self.assertTrue(rebound["open_position"])
            self.assertEqual(rebound["completed_trades"], 0)
            self.assertFalse(rebound["pending_exit_on_next_executable"])

    def test_qualified_candidate_ledgers_are_idempotent_on_repeated_history(self):
        with tempfile.TemporaryDirectory() as folder:
            candles = self.candles()
            first = run_forward_paper_accounts(candles, state_dir=folder)
            second = run_forward_paper_accounts(candles, state_dir=folder)
            first_candidates = first["forward_only_qualified_candidates"]["candidates"]
            second_candidates = second["forward_only_qualified_candidates"]["candidates"]
            for name in first_candidates:
                self.assertTrue(first["forward_only_qualified_candidates"]["seed"][name]["created"])
                self.assertFalse(second["forward_only_qualified_candidates"]["seed"][name]["created"])
                self.assertEqual(second_candidates[name]["processed_new_candles"], 0)
                self.assertEqual(
                    second_candidates[name]["completed_trades"],
                    first_candidates[name]["completed_trades"],
                )


if __name__ == "__main__":
    unittest.main()
