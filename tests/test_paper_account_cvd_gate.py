import tempfile
import unittest
from pathlib import Path

from paper_account import seed_forward_paper_account, update_paper_account


class PaperAccountCvdEntryGateTests(unittest.TestCase):
    def run_one(self, *, required, available=False, confirmation_timestamp=None):
        with tempfile.TemporaryDirectory() as folder:
            state_path = Path(folder) / "paper.json"
            history = [
                [index * 3600, 0, 0, 0, 100.0 + index]
                for index in range(200)
            ]
            seed_forward_paper_account(
                history, str(state_path), initial_cash=1000.0, strategy="sma_trend"
            )
            latest_timestamp = 200 * 3600
            candles = history + [[latest_timestamp, 0, 0, 0, 300.0]]
            result = update_paper_account(
                candles,
                state_path=str(state_path),
                initial_cash=1000.0,
                allocation_fraction=0.10,
                strategy="sma_trend",
                require_entry_confirmation=required,
                entry_confirmation_timestamp=confirmation_timestamp,
                entry_confirmation_available=available,
            )
            return result

    def test_required_cvd_confirmation_blocks_entry_when_missing(self):
        result = self.run_one(required=True)
        self.assertFalse(result["open_position"])
        self.assertEqual(result["btc_units"], 0.0)

    def test_required_cvd_confirmation_must_match_exact_candle(self):
        result = self.run_one(
            required=True, available=True, confirmation_timestamp=199 * 3600
        )
        self.assertFalse(result["open_position"])
        self.assertEqual(result["btc_units"], 0.0)

    def test_exact_candle_bullish_confirmation_allows_paper_entry(self):
        result = self.run_one(
            required=True, available=True, confirmation_timestamp=200 * 3600
        )
        self.assertTrue(result["open_position"])
        self.assertGreater(result["btc_units"], 0.0)

    def test_invalid_entry_confirmation_inputs_are_rejected(self):
        with tempfile.TemporaryDirectory() as folder:
            history = [
                [index * 3600, 0, 0, 0, 100.0 + index]
                for index in range(200)
            ]
            state_path = Path(folder) / "paper.json"
            seed_forward_paper_account(
                history, str(state_path), initial_cash=1000.0, strategy="sma_trend"
            )
            candles = history + [[200 * 3600, 0, 0, 0, 300.0]]
            with self.assertRaises(ValueError):
                update_paper_account(
                    candles, state_path=str(state_path), initial_cash=1000.0,
                    strategy="sma_trend", require_entry_confirmation="yes",
                )
            with self.assertRaises(ValueError):
                update_paper_account(
                    candles, state_path=str(state_path), initial_cash=1000.0,
                    strategy="sma_trend", require_entry_confirmation=True,
                    entry_confirmation_timestamp=True,
                )

    def test_legacy_strategy_behavior_is_unchanged_when_gate_is_disabled(self):
        result = self.run_one(required=False)
        self.assertTrue(result["open_position"])
        self.assertGreater(result["btc_units"], 0.0)


if __name__ == "__main__":
    unittest.main()
