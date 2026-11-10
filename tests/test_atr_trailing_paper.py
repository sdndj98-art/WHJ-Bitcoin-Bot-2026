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

    def test_fixture_has_bullish_prior_daily_regime_and_ema_alignment(self):
        four_hour, daily = self.market()
        timestamp = len(four_hour) * 4 * 3600
        closes = [bar["close"] for bar in four_hour]
        self.assertTrue(_daily_regime(daily, timestamp))
        self.assertGreater(_ema(closes, 20), _ema(closes, 50))
        self.assertGreater(closes[-1], _ema(closes, 50))

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

    def test_atr_trailing_exit_is_queued_then_filled_on_next_bar(self):
        four_hour, daily = self.market()
        with tempfile.TemporaryDirectory() as folder:
            path = f"{folder}/atr.json"
            seed_atr_trailing_account(four_hour, daily, path)
            index = len(four_hour)
            base = 100.0 + index * 0.1
            entry_signal_bar = {
                "timestamp": index * 4 * 3600,
                "open": base - 0.05, "high": base + 0.5,
                "low": base - 0.5, "close": base,
            }
            first = update_atr_trailing_account(
                four_hour + [entry_signal_bar], daily, path
            )
            self.assertEqual(first["pending_action"], "buy")
            entry_fill_bar = dict(entry_signal_bar)
            entry_fill_bar["timestamp"] += 4 * 3600
            for field in ("open", "high", "low", "close"):
                entry_fill_bar[field] += 0.1
            second = update_atr_trailing_account(
                four_hour + [entry_signal_bar, entry_fill_bar], daily, path
            )
            self.assertTrue(second["open_position"])
            peak_bar = dict(entry_fill_bar)
            peak_bar["timestamp"] += 4 * 3600
            peak_bar["open"] += 5.0
            peak_bar["high"] += 5.5
            peak_bar["low"] += 4.5
            peak_bar["close"] += 5.0
            third = update_atr_trailing_account(
                four_hour + [entry_signal_bar, entry_fill_bar, peak_bar], daily, path
            )
            self.assertTrue(third["open_position"])
            stop_bar = dict(peak_bar)
            stop_bar["timestamp"] += 4 * 3600
            stop_bar["open"] -= 12.0
            stop_bar["high"] -= 11.5
            stop_bar["low"] -= 12.5
            stop_bar["close"] -= 12.0
            fourth = update_atr_trailing_account(
                four_hour + [entry_signal_bar, entry_fill_bar, peak_bar, stop_bar],
                daily, path,
            )
            self.assertEqual(fourth["pending_action"], "sell")
            self.assertTrue(fourth["open_position"])
            fill_bar = dict(stop_bar)
            fill_bar["timestamp"] += 4 * 3600
            fifth = update_atr_trailing_account(
                four_hour + [entry_signal_bar, entry_fill_bar, peak_bar, stop_bar, fill_bar],
                daily, path,
            )
            self.assertFalse(fifth["open_position"])
            self.assertEqual(fifth["completed_trades"], 1)

    def test_synthetic_bar_cannot_fill_or_create_a_signal(self):
        four_hour, daily = self.market()
        with tempfile.TemporaryDirectory() as folder:
            path = f"{folder}/atr.json"
            seed_atr_trailing_account(four_hour, daily, path)
            index = len(four_hour)
            price = 100.0 + index * 0.1
            synthetic = {
                "timestamp": index * 4 * 3600,
                "open": price - 0.05, "high": price + 0.5,
                "low": price - 0.5, "close": price,
                "execution_eligible": False,
            }
            blocked = update_atr_trailing_account(four_hour + [synthetic], daily, path)
            self.assertEqual(blocked["last_signal"], "blocked_synthetic_bar")
            self.assertIsNone(blocked["pending_action"])
            self.assertFalse(blocked["open_position"])
            real = dict(synthetic)
            real["timestamp"] += 4 * 3600
            real["execution_eligible"] = True
            for field in ("open", "high", "low", "close"):
                real[field] += 0.1
            allowed = update_atr_trailing_account(
                four_hour + [synthetic, real], daily, path
            )
            self.assertEqual(allowed["last_signal"], "entry_queued")
            self.assertEqual(allowed["pending_action"], "buy")

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
