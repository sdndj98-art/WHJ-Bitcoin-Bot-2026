import unittest

from market_scanner import scan_btc_market


def candles(prior_high=100.0, current_close=101.0, current_volume=30.0):
    rows = []
    for index in range(20):
        rows.append([index * 3600, 95.0, prior_high, 90.0, 95.0, 0.0, 10.0, 100])
    rows.append([20 * 3600, 95.0, current_close, 94.0, current_close, 0.0, current_volume, 150])
    return rows


HEALTHY = {"quality_status": "HEALTHY", "paper_execution_allowed": True}


class MarketScannerTests(unittest.TestCase):
    def test_candidate_requires_breakout_volume_and_good_data(self):
        result = scan_btc_market(candles(), HEALTHY)
        self.assertEqual(result["status"], "PAPER_CANDIDATE")
        self.assertTrue(result["paper_candidate_only"])
        self.assertFalse(result["live_orders_placed"])

    def test_no_candidate_when_volume_is_not_elevated(self):
        result = scan_btc_market(candles(current_volume=12.0), HEALTHY)
        self.assertNotEqual(result["status"], "PAPER_CANDIDATE")
        self.assertIn("volume_spike_not_confirmed", result["reasons"])

    def test_no_candidate_when_close_does_not_break_prior_high(self):
        result = scan_btc_market(candles(prior_high=100.0, current_close=99.0), HEALTHY)
        self.assertNotEqual(result["status"], "PAPER_CANDIDATE")
        self.assertIn("close_not_above_prior_20_high", result["reasons"])

    def test_bad_market_data_blocks_candidate(self):
        result = scan_btc_market(candles(), {"quality_status": "BLOCKED", "paper_execution_allowed": False})
        self.assertNotEqual(result["status"], "PAPER_CANDIDATE")
        self.assertIn("market_data_quality_blocked_or_unknown", result["reasons"])

    def test_rejects_insufficient_history(self):
        with self.assertRaises(ValueError):
            scan_btc_market(candles()[:10], HEALTHY)

    def test_rejects_non_finite_volume(self):
        rows = candles()
        rows[-1][6] = float("nan")
        with self.assertRaises(ValueError):
            scan_btc_market(rows, HEALTHY)


if __name__ == "__main__":
    unittest.main()
