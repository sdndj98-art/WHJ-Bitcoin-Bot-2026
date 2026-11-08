import unittest

from trade_candle_builder import build_trade_candles


class TradeCandleBuilderTests(unittest.TestCase):
    def test_excludes_current_forming_candle(self):
        trades = [
            {"trade_id": 1, "timestamp": 1.0, "price": 100, "qty": 2, "side": "buy"},
            {"trade_id": 2, "timestamp": 61.0, "price": 101, "qty": 1, "side": "sell"},
            {"trade_id": 3, "timestamp": 121.0, "price": 105, "qty": 1, "side": "buy"},
        ]
        result = build_trade_candles(trades, 60, 125)
        self.assertEqual([row[0] for row in result["candles"]], [0, 60])
        self.assertEqual(result["trade_count"], 2)
        self.assertEqual(result["excluded_forming_candle_trades"], 1)
        self.assertEqual(result["candles"][0][1:5], [100, 100, 100, 100])
        self.assertEqual(result["candles"][1][1:5], [101, 101, 101, 101])

    def test_fills_empty_interior_bucket_without_fabricating_volume(self):
        trades = [
            {"trade_id": 1, "timestamp": 1, "price": 100, "qty": 1, "side": "buy"},
            {"trade_id": 2, "timestamp": 121, "price": 105, "qty": 2, "side": "sell"},
        ]
        result = build_trade_candles(trades, 60, 180)
        empty = result["candles"][1]
        self.assertEqual(empty, [60, 100, 100, 100, 100, 100, 0.0, 0])
        self.assertEqual(result["empty_candle_count"], 1)

    def test_exact_boundary_trade_belongs_to_new_candle(self):
        trades = [
            {"trade_id": 1, "timestamp": 59.999, "price": 100, "qty": 1, "side": "buy"},
            {"trade_id": 2, "timestamp": 60.0, "price": 102, "qty": 1, "side": "sell"},
        ]
        result = build_trade_candles(trades, 60, 120)
        self.assertEqual(result["candles"][0][4], 100)
        self.assertEqual(result["candles"][1][1], 102)

    def test_supports_second_interval(self):
        trades = [
            {"trade_id": 1, "timestamp": 10.1, "price": 100, "qty": 1, "side": "buy"},
            {"trade_id": 2, "timestamp": 11.2, "price": 101, "qty": 2, "side": "sell"},
        ]
        result = build_trade_candles(trades, 1, 12.5)
        self.assertEqual([row[0] for row in result["candles"]], [10, 11])
        self.assertEqual(result["candles"][1][7], 1)

    def test_rejects_duplicate_ids(self):
        trade = {"trade_id": 1, "timestamp": 1, "price": 100, "qty": 1, "side": "buy"}
        with self.assertRaises(ValueError):
            build_trade_candles([trade, dict(trade)], 60, 120)

    def test_rejects_out_of_order_events(self):
        trades = [
            {"trade_id": 1, "timestamp": 2, "price": 100, "qty": 1, "side": "buy"},
            {"trade_id": 2, "timestamp": 1, "price": 100, "qty": 1, "side": "buy"},
        ]
        with self.assertRaises(ValueError):
            build_trade_candles(trades, 60, 120)

    def test_rejects_timezone_naive_timestamp(self):
        trade = {"trade_id": 1, "timestamp": "2026-11-08T10:00:00", "price": 100, "qty": 1, "side": "buy"}
        with self.assertRaises(ValueError):
            build_trade_candles([trade], 60, 1790000000)

    def test_requires_nonempty_completed_coverage(self):
        trade = {"trade_id": 1, "timestamp": 121, "price": 100, "qty": 1, "side": "buy"}
        with self.assertRaises(ValueError):
            build_trade_candles([trade], 60, 125)


    def test_forming_trade_count_excludes_pre_coverage_trades(self):
        trades = [
            {"trade_id": 1, "timestamp": 1, "price": 99, "qty": 1, "side": "buy"},
            {"trade_id": 2, "timestamp": 61, "price": 100, "qty": 1, "side": "buy"},
            {"trade_id": 3, "timestamp": 121, "price": 101, "qty": 1, "side": "sell"},
            {"trade_id": 4, "timestamp": 181, "price": 102, "qty": 1, "side": "buy"},
        ]
        result = build_trade_candles(
            trades, 60, 125, start_timestamp=60
        )
        self.assertEqual(result["trade_count"], 2)
        self.assertEqual(result["excluded_forming_candle_trades"], 1)


if __name__ == "__main__":
    unittest.main()
