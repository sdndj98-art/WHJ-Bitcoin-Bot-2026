import unittest

from market_scanner import scan_btc_market


def candles(prior_high=100.0, current_close=101.0, current_volume=30.0):
    rows = []
    for index in range(50):
        close = 95.0 + index * 0.05 + (0.15 if index % 2 == 0 else -0.15)
        open_price = close - 0.03
        rows.append([
            index * 3600, open_price, prior_high, close - 0.35,
            close, 0.0, 10.0, 100
        ])
    current_open = min(100.0, current_close - 0.01)
    current_low = min(current_open, current_close) - 0.5
    current_high = max(prior_high, current_open, current_close) + 0.5
    rows.append([
        50 * 3600, current_open, current_high, current_low,
        current_close, 0.0, current_volume, 150
    ])
    return rows


HEALTHY = {"quality_status": "HEALTHY", "paper_execution_allowed": True}


class MarketScannerTests(unittest.TestCase):
    def test_candidate_requires_all_six_confirmations_and_good_data(self):
        result = scan_btc_market(candles(), HEALTHY)
        self.assertEqual(result["status"], "PAPER_CANDIDATE")
        self.assertEqual(result["confluence_score"], 6)
        self.assertEqual(result["confluence_total"], 6)
        self.assertTrue(result["paper_candidate_only"])
        self.assertFalse(result["live_orders_placed"])

    def test_returns_ema_rsi_and_atr_context(self):
        result = scan_btc_market(candles(), HEALTHY)
        self.assertGreater(result["ema20"], result["ema50"])
        self.assertGreaterEqual(result["rsi14"], 0)
        self.assertLessEqual(result["rsi14"], 100)
        self.assertGreater(result["atr14"], 0)
        self.assertGreater(result["atr_pct"], 0)
        self.assertGreaterEqual(result["close_position_pct"], 0)
        self.assertLessEqual(result["close_position_pct"], 100)

    def test_no_candidate_when_volume_is_not_elevated(self):
        result = scan_btc_market(candles(current_volume=12.0), HEALTHY)
        self.assertNotEqual(result["status"], "PAPER_CANDIDATE")
        self.assertIn("volume_spike_not_confirmed", result["reasons"])

    def test_no_candidate_when_close_does_not_break_prior_high(self):
        result = scan_btc_market(candles(prior_high=100.0, current_close=99.0), HEALTHY)
        self.assertNotEqual(result["status"], "PAPER_CANDIDATE")
        self.assertIn("close_not_above_prior_lookback_high", result["reasons"])

    def test_bad_market_data_blocks_candidate(self):
        result = scan_btc_market(
            candles(),
            {"quality_status": "BLOCKED", "paper_execution_allowed": False},
        )
        self.assertNotEqual(result["status"], "PAPER_CANDIDATE")
        self.assertIn("market_data_quality_blocked_or_unknown", result["reasons"])

    def test_rejects_insufficient_history(self):
        with self.assertRaisesRegex(ValueError, "50-period"):
            scan_btc_market(candles()[:10], HEALTHY)

    def test_rejects_duplicate_or_unsorted_timestamps(self):
        rows = candles()
        rows[-1][0] = rows[-2][0]
        with self.assertRaisesRegex(ValueError, "strictly increasing"):
            scan_btc_market(rows, HEALTHY)

    def test_rejects_hourly_timestamp_gaps(self):
        rows = candles()
        rows[-1][0] += 60
        with self.assertRaisesRegex(ValueError, "contiguous"):
            scan_btc_market(rows, HEALTHY)

    def test_rejects_boolean_timestamp_and_fractional_trade_count(self):
        rows = candles()
        rows[-1][0] = True
        with self.assertRaisesRegex(ValueError, "booleans"):
            scan_btc_market(rows, HEALTHY)
        rows = candles()
        rows[-1][7] = 1.5
        with self.assertRaisesRegex(ValueError, "trade count"):
            scan_btc_market(rows, HEALTHY)

    def test_rejects_non_finite_volume(self):
        rows = candles()
        rows[-1][6] = float("nan")
        with self.assertRaises(ValueError):
            scan_btc_market(rows, HEALTHY)


if __name__ == "__main__":
    unittest.main()
