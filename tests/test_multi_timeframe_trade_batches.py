import unittest

from multi_timeframe_cvd import analyze_multi_timeframe_cvd


class PerTimeframeTradeBatchTests(unittest.TestCase):
    def test_uses_distinct_trade_batches_for_distinct_candle_coverage(self):
        candles = {
            "1s": [[10, 100, 101, 100, 101, 100.5, 2, 2]],
            "1m": [[0, 100, 101, 100, 101, 100.5, 2, 2]],
        }
        batches = {
            "1s": [
                {"trade_id": 1, "timestamp": 10.1, "qty": 2, "side": "buy"},
                {"trade_id": 2, "timestamp": 10.8, "qty": 1, "side": "sell"},
            ],
            "1m": [
                {"trade_id": 1, "timestamp": 10.1, "qty": 2, "side": "buy"},
                {"trade_id": 2, "timestamp": 10.8, "qty": 1, "side": "sell"},
            ],
        }
        result = analyze_multi_timeframe_cvd(
            candles, batches, {"1s": True, "1m": True},
            max_last_trade_lag_seconds_by_timeframe={"1s": 1, "1m": 60},
        )
        self.assertEqual(result["consensus"]["available_timeframes"], 2)
        self.assertEqual(result["timeframes"]["1s"]["latest_status"], "OK")
        self.assertEqual(result["timeframes"]["1m"]["latest_status"], "OK")


if __name__ == "__main__":
    unittest.main()
