import unittest

from multi_timeframe_cvd import TIMEFRAME_SECONDS, analyze_multi_timeframe_cvd


def candle(start=0, interval=60, bullish=True):
    return [start, 100, 102 if bullish else 101, 99 if bullish else 98,
            101 if bullish else 99, 100, 3, 2]


class MultiTimeframeCvdTests(unittest.TestCase):
    def setUp(self):
        self.trades = [
            {"trade_id": 1, "timestamp": 0.2, "qty": 2.0, "side": "buy"},
            {"trade_id": 2, "timestamp": 0.6, "qty": 1.0, "side": "sell"},
        ]

    def test_every_supported_timeframe_can_be_analyzed(self):
        candles = {name: [candle()] for name in TIMEFRAME_SECONDS}
        continuity = {name: True for name in TIMEFRAME_SECONDS}
        report = analyze_multi_timeframe_cvd(candles, self.trades, continuity)
        self.assertEqual(set(report["timeframes"]), set(TIMEFRAME_SECONDS))
        self.assertEqual(report["consensus"]["available_timeframes"], len(TIMEFRAME_SECONDS))
        self.assertEqual(report["consensus"]["bias"], "BULLISH")
        self.assertFalse(report["execution_enabled"])

    def test_unverified_frame_does_not_vote(self):
        candles = {"1s": [candle()], "1m": [candle()]}
        report = analyze_multi_timeframe_cvd(
            candles, self.trades, {"1s": True, "1m": False}
        )
        self.assertEqual(report["consensus"]["available_timeframes"], 1)
        self.assertEqual(report["timeframes"]["1m"]["latest_direction"], "UNAVAILABLE")
        self.assertEqual(report["consensus"]["bias"], "BULLISH")
        self.assertEqual(report["status"], "PARTIAL_OR_UNAVAILABLE")

    def test_no_verified_frames_means_unavailable_consensus(self):
        report = analyze_multi_timeframe_cvd(
            {"1s": [candle()]}, self.trades, {"1s": False}
        )
        self.assertEqual(report["consensus"]["bias"], "UNAVAILABLE")
        self.assertEqual(report["consensus"]["available_timeframes"], 0)

    def test_rejects_unknown_timeframe(self):
        with self.assertRaises(ValueError):
            analyze_multi_timeframe_cvd(
                {"7h": [candle()]}, self.trades, {"7h": True}
            )

    def test_rejects_empty_candle_map(self):
        with self.assertRaises(ValueError):
            analyze_multi_timeframe_cvd({}, self.trades, {})

    def test_requires_consensus_above_half(self):
        with self.assertRaises(ValueError):
            analyze_multi_timeframe_cvd(
                {"1s": [candle()]}, self.trades, {"1s": True},
                consensus_ratio=0.5,
            )


if __name__ == "__main__":
    unittest.main()
