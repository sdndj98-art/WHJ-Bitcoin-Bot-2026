import unittest

from cvd_candle_research import align_trade_flow_to_candles


def candle(start, open_price=100.0, close=101.0):
    return [start, open_price, max(open_price, close) + 1,
            min(open_price, close) - 1, close, 100.0, 10.0, 20]


def trade(trade_id, timestamp, qty, side):
    return {"trade_id": trade_id, "timestamp": timestamp,
            "qty": qty, "side": side}


class CvdCandleResearchTests(unittest.TestCase):
    def test_aligns_events_to_completed_candle_and_confirms_buy_flow(self):
        rows = [candle(0)]
        events = [trade(1, 3590, 8, "buy"), trade(2, 3595, 2, "sell")]
        result = align_trade_flow_to_candles(
            rows, events, continuity_verified=True, max_last_trade_lag_seconds=10
        )
        bar = result["bars"][0]
        self.assertTrue(bar["available"])
        self.assertTrue(bar["bullish_flow_confirmation"])
        self.assertEqual(bar["delta_pct"], 60.0)

    def test_fails_closed_without_verified_continuity(self):
        result = align_trade_flow_to_candles(
            [candle(0)], [trade(1, 3599, 1, "buy")]
        )
        self.assertFalse(result["bars"][0]["available"])
        self.assertEqual(result["bars"][0]["status"], "CONTINUITY_UNVERIFIED")
        self.assertFalse(result["bars"][0]["bullish_flow_confirmation"])

    def test_rejects_stale_last_trade(self):
        result = align_trade_flow_to_candles(
            [candle(0)], [trade(1, 3500, 1, "buy")],
            continuity_verified=True, max_last_trade_lag_seconds=30
        )
        self.assertFalse(result["bars"][0]["available"])

    def test_reports_bullish_absorption_divergence(self):
        result = align_trade_flow_to_candles(
            [candle(0, 101, 100)],
            [trade(1, 3599, 9, "buy"), trade(2, 3599, 1, "sell")],
            continuity_verified=True, max_last_trade_lag_seconds=2
        )
        self.assertTrue(result["bars"][0]["bullish_absorption_divergence"])

    def test_reports_bearish_absorption_divergence(self):
        result = align_trade_flow_to_candles(
            [candle(0, 100, 101)],
            [trade(1, 3599, 1, "buy"), trade(2, 3599, 9, "sell")],
            continuity_verified=True, max_last_trade_lag_seconds=2
        )
        self.assertTrue(result["bars"][0]["bearish_absorption_divergence"])

    def test_rejects_duplicate_trade_ids(self):
        events = [trade(1, 3590, 1, "buy"), trade(1, 3591, 1, "sell")]
        with self.assertRaisesRegex(ValueError, "duplicate trade_id"):
            align_trade_flow_to_candles([candle(0)], events, continuity_verified=True)

    def test_rejects_out_of_order_timestamps(self):
        events = [trade(2, 3591, 1, "buy"), trade(3, 3590, 1, "sell")]
        with self.assertRaisesRegex(ValueError, "non-decreasing"):
            align_trade_flow_to_candles([candle(0)], events, continuity_verified=True)

    def test_rejects_gaps_in_candle_series(self):
        with self.assertRaisesRegex(ValueError, "contiguous"):
            align_trade_flow_to_candles(
                [candle(0), candle(7200)], [], continuity_verified=True
            )

    def test_rejects_timezone_naive_iso_timestamp(self):
        events = [trade(1, "2026-11-08T12:00:00", 1, "buy")]
        with self.assertRaisesRegex(ValueError, "include timezone"):
            align_trade_flow_to_candles([candle(0)], events, continuity_verified=True)

    def test_prefix_causality_no_future_trade_leakage(self):
        first = [candle(0), candle(3600)]
        events = [
            trade(1, 3599, 2, "buy"),
            trade(2, 3601, 100, "sell"),
        ]
        result = align_trade_flow_to_candles(
            first, events, continuity_verified=True, max_last_trade_lag_seconds=2
        )
        self.assertEqual(result["bars"][0]["delta_volume"], 2.0)
        self.assertEqual(result["bars"][0]["trade_count"], 1)

    def test_rejects_trade_outside_candle_coverage(self):
        with self.assertRaisesRegex(ValueError, "outside supplied"):
            align_trade_flow_to_candles(
                [candle(0)], [trade(1, 3600, 1, "buy")],
                continuity_verified=True
            )

    def test_empty_bar_is_unavailable_even_when_continuity_is_verified(self):
        result = align_trade_flow_to_candles(
            [candle(0)], [], continuity_verified=True
        )
        self.assertFalse(result["bars"][0]["available"])
        self.assertEqual(result["available_bars"], 0)


if __name__ == "__main__":
    unittest.main()
