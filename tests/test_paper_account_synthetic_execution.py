import tempfile
import unittest

from paper_account import seed_forward_paper_account, update_paper_account


class PaperAccountSyntheticExecutionTests(unittest.TestCase):
    def test_imputed_candles_update_history_but_never_open_or_close_positions(self):
        with tempfile.TemporaryDirectory() as folder:
            state_path = f"{folder}/paper.json"
            history = [
                [index * 3600, 0, 0, 0, str(100.0 + index)]
                for index in range(200)
            ]
            seed_forward_paper_account(
                history, state_path=state_path, initial_cash=1000.0,
                strategy="sma_trend",
            )

            synthetic_entry = [200 * 3600, 0, 0, 0, "300", False]
            skipped_entry = update_paper_account(
                [synthetic_entry], state_path=state_path, strategy="sma_trend",
            )
            self.assertEqual(skipped_entry["btc_units"], 0.0)
            self.assertFalse(skipped_entry["open_position"])

            real_entry = [201 * 3600, 0, 0, 0, "300", True]
            opened = update_paper_account(
                [real_entry], state_path=state_path, strategy="sma_trend",
            )
            self.assertGreater(opened["btc_units"], 0.0)
            self.assertTrue(opened["open_position"])

            synthetic_risk_exit = [10 * 86400, 0, 0, 0, "250", False]
            held = update_paper_account(
                [synthetic_risk_exit], state_path=state_path, strategy="sma_trend",
            )
            self.assertTrue(held["open_position"])
            self.assertTrue(held["daily_loss_paused"])
            self.assertEqual(held["completed_trades"], 0)
            self.assertTrue(held["pending_exit_on_next_executable"])

            # The next real candle is on a new UTC day. The pending risk exit
            # must survive the daily-loss pause reset and execute only here.
            real_risk_exit = [11 * 86400, 0, 0, 0, "250", True]
            closed = update_paper_account(
                [real_risk_exit], state_path=state_path, strategy="sma_trend",
            )
            self.assertFalse(closed["open_position"])
            self.assertEqual(closed["completed_trades"], 1)
            self.assertFalse(closed["pending_exit_on_next_executable"])

    def test_normal_exit_signal_on_synthetic_bar_is_recomputed_after_rebound(self):
        with tempfile.TemporaryDirectory() as folder:
            state_path = f"{folder}/paper.json"
            history = [
                [index * 3600, 0, 0, 0, str(100.0 + index)]
                for index in range(200)
            ]
            seed_forward_paper_account(
                history, state_path=state_path, initial_cash=1000.0,
                strategy="sma_trend",
            )
            limits = {
                "strategy": "sma_trend",
                "daily_loss_fraction": 0.99,
                "max_drawdown_fraction": 0.99,
            }
            opened = update_paper_account(
                [[200 * 3600, 0, 0, 0, "300", True]],
                state_path=state_path, **limits,
            )
            self.assertTrue(opened["open_position"])

            # First synthetic close depresses the trend; the next synthetic
            # bar observes that exit signal but cannot fill it.
            update_paper_account(
                [[201 * 3600, 0, 0, 0, "150", False]],
                state_path=state_path, **limits,
            )
            held = update_paper_account(
                [[202 * 3600, 0, 0, 0, "300", False]],
                state_path=state_path, **limits,
            )
            self.assertTrue(held["open_position"])
            self.assertFalse(held["pending_exit_on_next_executable"])

            # The rebound is now the prior completed close. The strategy
            # signal is bullish again, so the stale synthetic SELL must vanish.
            rebound = update_paper_account(
                [[203 * 3600, 0, 0, 0, "310", True]],
                state_path=state_path, **limits,
            )
            self.assertTrue(rebound["open_position"])
            self.assertEqual(rebound["completed_trades"], 0)
            self.assertFalse(rebound["pending_exit_on_next_executable"])

    def test_legacy_non_boolean_extra_fields_remain_compatible(self):
        with tempfile.TemporaryDirectory() as folder:
            result = update_paper_account(
                [[3600, 0, 0, 0, "100", "legacy-metadata"]],
                state_path=f"{folder}/paper.json",
            )
            self.assertEqual(result["processed_new_candles"], 1)


if __name__ == "__main__":
    unittest.main()
