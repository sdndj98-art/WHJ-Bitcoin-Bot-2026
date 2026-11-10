import tempfile
import unittest

from atr_trailing_paper import (
    seed_atr_trailing_account,
    update_atr_trailing_account,
)


class AtrTrailingForwardPaperTests(unittest.TestCase):
    @staticmethod
    def market(days=220):
        daily = []
        for day in range(days):
            close = 100.0 + day
            daily.append({
                "timestamp": day * 86400,
                "open": close - 0.2,
                "high": close + 1.0,
                "low": close - 1.0,
                "close": close,
            })
        four_hour = []
        for index in range(days * 6):
            close = 100.0 + index * 0.1
            four_hour.append({
                "timestamp": index * 4 * 3600,
                "open": close - 0.05,
                "high": close + 0.5,
                "low": close - 0.5,
                "close": close,
            })
        return four_hour, daily

    def test_seed_has_no_historical_trade_or_pnl_and_repeated_update_is_idempotent(self):
        four_hour, daily = self.market()
        with tempfile.TemporaryDirectory() as folder:
            path = f"{folder}/atr.json"
            seed = seed_atr_trailing_account(four_hour, daily, path)
            self.assertTrue(seed["created"])
            seeded = update_atr_trailing_account(four_hour, daily, path)
            self.assertEqual(seeded["equity_usd"], 250.0)
            self.assertEqual(seeded["return_pct"], 0.0)
            self.assertEqual(seeded["completed_trades"], 0)
            self.assertEqual(seeded["processed_new_candles"], 0)
            again = update_atr_trailing_account(four_hour, daily, path)
            self.assertEqual(again["processed_new_candles"], 0)
            self.assertEqual(again["completed_trades"], 0)

    def test_entry_signal_fills_only_at_following_completed_bar_close(self):
        four_hour, daily = self.market()
        with tempfile.TemporaryDirectory() as folder:
            path = f"{folder}/atr.json"
            seed_atr_trailing_account(four_hour, daily, path)
            next_index = len(four_hour)
            next_bar = {
                "timestamp": next_index * 4 * 3600,
                "open": 100.0 + next_index * 0.1 - 0.05,
                "high": 100.0 + next_index * 0.1 + 0.5,
                "low": 100.0 + next_index * 0.1 - 0.5,
                "close": 100.0 + next_index * 0.1,
            }
            one = update_atr_trailing_account(four_hour + [next_bar], daily, path)
            self.assertEqual(one["last_signal"], "entry_queued")
            self.assertFalse(one["open_position"])
            next_bar2 = dict(next_bar)
            next_bar2["timestamp"] += 4 * 3600
            next_bar2["open"] += 0.1
            next_bar2["high"] += 0.1
            next_bar2["low"] += 0.1
            next_bar2["close"] += 0.1
            two = update_atr_trailing_account(
                four_hour + [next_bar, next_bar2], daily, path
            )
            self.assertTrue(two["open_position"])
            self.assertEqual(two["completed_trades"], 0)
            self.assertEqual(two["processed_new_candles"], 2)

    def test_rejects_gap_between_saved_checkpoint_and_new_bar(self):
        four_hour, daily = self.market()
        with tempfile.TemporaryDirectory() as folder:
            path = f"{folder}/atr.json"
            seed_atr_trailing_account(four_hour, daily, path)
            index = len(four_hour) + 1
            gap_bar = {
                "timestamp": index * 4 * 3600,
                "open": 250.0, "high": 251.0, "low": 249.0, "close": 250.0,
            }
            with self.assertRaisesRegex(ValueError, "continue exactly"):
                update_atr_trailing_account(four_hour + [gap_bar], daily, path)

    def test_rejects_invalid_ohlc(self):
        four_hour, daily = self.market()
        four_hour[-1]["high"] = four_hour[-1]["close"] - 1
        with tempfile.TemporaryDirectory() as folder:
            with self.assertRaisesRegex(ValueError, "high is inconsistent"):
                seed_atr_trailing_account(four_hour, daily, f"{folder}/atr.json")


if __name__ == "__main__":
    unittest.main()
