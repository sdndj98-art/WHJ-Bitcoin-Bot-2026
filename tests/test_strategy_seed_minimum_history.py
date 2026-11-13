import json
import tempfile
import unittest
from pathlib import Path

from paper_account import seed_forward_paper_account


class StrategyWarmupDepthTests(unittest.TestCase):
    def candles(self, count):
        return [
            [1_700_000_000 + index * 3600, 0, 0, 0, 2000.0 + index]
            for index in range(count)
        ]

    def test_ema_trend_can_seed_from_50_real_bars(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "ema.json"
            result = seed_forward_paper_account(
                self.candles(50), path, initial_cash=10.0, strategy="ema_trend"
            )
            state = json.loads(path.read_text(encoding="utf-8"))
            self.assertTrue(result["created"])
            self.assertEqual(len(state["recent_closes"]), 50)
            self.assertEqual(state["last_timestamp"], self.candles(50)[-1][0])

    def test_ema_trend_rejects_fewer_than_50_bars(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "ema.json"
            with self.assertRaisesRegex(ValueError, "At least 50"):
                seed_forward_paper_account(
                    self.candles(49), path, initial_cash=10.0, strategy="ema_trend"
                )
            self.assertFalse(path.exists())

    def test_sma200_rsi_mean_reversion_still_requires_200_bars(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "rsi.json"
            with self.assertRaisesRegex(ValueError, "At least 200"):
                seed_forward_paper_account(
                    self.candles(199), path, initial_cash=10.0,
                    strategy="rsi14_mean_reversion"
                )
            self.assertFalse(path.exists())


if __name__ == "__main__":
    unittest.main()
