import json
import os
import tempfile
import unittest

from cvd_timeframes import (
    TIMEFRAMES,
    aggregate_all_timeframes,
    aggregate_trade_events,
    read_trade_journal,
)


def trade(trade_id, second, price, qty, side="buy", symbol="BTC/USD"):
    return {
        "trade_id": trade_id,
        "timestamp": second,
        "price": price,
        "qty": qty,
        "side": side,
        "symbol": symbol,
    }


class CvdTimeframeReplayTests(unittest.TestCase):
    def test_native_bars_ohlcv_delta_and_cumulative_cvd(self):
        events = [
            trade(1, 100.1, 100, 2, "buy"),
            trade(2, 100.8, 102, 1, "sell"),
            trade(3, 101.2, 101, 3, "buy"),
        ]
        result = aggregate_trade_events(events, 1, as_of=103)
        self.assertEqual(result["bar_count"], 2)
        first, second = result["bars"]
        self.assertEqual((first["open"], first["high"], first["low"], first["close"]), (100, 102, 100, 102))
        self.assertEqual(first["buy_volume"], 2)
        self.assertEqual(first["sell_volume"], 1)
        self.assertEqual(first["delta"], 1)
        self.assertEqual(first["cvd_open"], 0)
        self.assertEqual(first["cvd_close"], 1)
        self.assertEqual(second["delta"], 3)
        self.assertEqual(second["cvd_close"], 4)
        self.assertTrue(first["is_closed"])
        self.assertTrue(second["is_closed"])

    def test_incomplete_current_bucket_is_flagged_not_dropped(self):
        result = aggregate_trade_events([trade(1, 100.2, 100, 1)], 60, as_of=120)
        self.assertEqual(result["bar_count"], 1)
        self.assertFalse(result["bars"][0]["is_closed"])

    def test_empty_intervals_are_not_synthesized_and_gap_is_marked(self):
        events = [trade(1, 100.2, 100, 1), trade(2, 103.2, 101, 1)]
        result = aggregate_trade_events(events, 1, as_of=105)
        self.assertEqual(result["bar_count"], 2)
        self.assertFalse(result["bars"][0]["gap_before"])
        self.assertTrue(result["bars"][1]["gap_before"])

    def test_multiple_timeframes_use_the_same_source_events(self):
        events = [trade(1, 100.2, 100, 1), trade(2, 101.2, 101, 2, "sell")]
        report = aggregate_all_timeframes(events, as_of=200, timeframes={"1s": 1, "1m": 60})
        self.assertEqual(set(report["timeframes"]), {"1s", "1m"})
        self.assertEqual(report["timeframes"]["1s"]["bar_count"], 2)
        self.assertEqual(report["timeframes"]["1m"]["bar_count"], 1)
        self.assertEqual(report["timeframes"]["1m"]["bars"][0]["delta"], -1)

    def test_rejects_duplicate_or_regressing_trade_ids(self):
        with self.assertRaisesRegex(ValueError, "strictly increasing"):
            aggregate_trade_events([trade(2, 100, 100, 1), trade(2, 101, 101, 1)], 1)

    def test_rejects_timestamp_regression(self):
        with self.assertRaisesRegex(ValueError, "non-decreasing"):
            aggregate_trade_events([trade(1, 101, 100, 1), trade(2, 100, 101, 1)], 1)

    def test_rejects_mixed_symbols(self):
        with self.assertRaisesRegex(ValueError, "mix symbols"):
            aggregate_trade_events([
                trade(1, 100, 100, 1, symbol="BTC/USD"),
                trade(2, 101, 101, 1, symbol="ETH/USD"),
            ], 1)

    def test_rejects_boolean_or_invalid_quantities(self):
        with self.assertRaisesRegex(ValueError, "finite number"):
            aggregate_trade_events([trade(1, 100, 100, True)], 1)

    def test_reads_complete_jsonl_journal_and_rejects_truncated_tail(self):
        with tempfile.TemporaryDirectory() as directory:
            path = os.path.join(directory, "trades.jsonl")
            with open(path, "wb") as handle:
                handle.write((json.dumps(trade(1, 100, 100, 1)) + "\\n").encode("utf-8"))
            self.assertEqual(len(read_trade_journal(path)), 1)
            with open(path, "wb") as handle:
                handle.write(json.dumps(trade(1, 100, 100, 1)).encode("utf-8"))
            with self.assertRaisesRegex(ValueError, "incomplete"):
                read_trade_journal(path)

    def test_rejects_explicitly_empty_timeframe_selection(self):
        with self.assertRaisesRegex(ValueError, "non-empty"):
            aggregate_all_timeframes([], timeframes={})

    def test_default_timeframes_cover_seconds_through_daily(self):
        self.assertEqual(TIMEFRAMES["1s"], 1)
        self.assertEqual(TIMEFRAMES["1m"], 60)
        self.assertEqual(TIMEFRAMES["1h"], 3600)
        self.assertEqual(TIMEFRAMES["1d"], 86400)


if __name__ == "__main__":
    unittest.main()
