import unittest

from market_scanner import scan_btc_market, scan_btc_multi_timeframe, _aggregate_hourly_candles, _adx


def candles(prior_high=97.8, current_close=98.2, current_volume=30.0):
    rows = []
    for index in range(50):
        close = 95.0 + index * 0.05 + (0.12 if index % 2 == 0 else -0.12)
        open_price = close - 0.03
        prior_bar_high = close + 0.25 if prior_high == 97.8 else prior_high
        rows.append([
            index * 3600, open_price, prior_bar_high, close - 0.35,
            close, 0.0, 10.0, 100
        ])
    current_open = min(100.0, current_close - 0.01)
    current_low = min(current_open, current_close) - 0.8
    current_high = max(prior_high, current_open, current_close) + 0.1
    rows.append([
        50 * 3600, current_open, current_high, current_low,
        current_close, 0.0, current_volume, 150
    ])
    return rows


HEALTHY = {"quality_status": "HEALTHY", "paper_execution_allowed": True}


class MarketScannerTests(unittest.TestCase):
    def test_derivatives_context_is_optional_and_does_not_change_scanner_score(self):
        result = scan_btc_market(candles(), HEALTHY)
        self.assertEqual(result["derivatives_intelligence"]["status"], "UNAVAILABLE")
        self.assertFalse(result["derivatives_intelligence"]["execution_enabled"])
        self.assertEqual(result["confluence_score"], 8)

    def test_aligned_derivatives_snapshots_are_exposed_as_research_context(self):
        price = {
            "source": "example-venue",
            "symbol": "BTC-PERP",
            "interval_start": "2026-11-10T11:00:00Z",
            "interval_end": "2026-11-10T12:00:00Z",
            "observed_at": "2026-11-10T11:59:58Z",
            "change_pct": 1.2,
        }
        open_interest = dict(price)
        open_interest["observed_at"] = "2026-11-10T11:59:59Z"
        open_interest["change_pct"] = 0.8
        result = scan_btc_market(
            candles(), HEALTHY,
            derivatives_snapshots={"price": price, "open_interest": open_interest},
            derivatives_as_of="2026-11-10T12:00:00Z",
        )
        context = result["derivatives_intelligence"]
        self.assertEqual(context["status"], "OK")
        self.assertEqual(context["classification"], "LONG_BUILDUP")
        self.assertTrue(context["research_only"])
        self.assertFalse(context["execution_enabled"])
        self.assertEqual(result["confluence_score"], 8)
        self.assertEqual(result["confluence_total"], 8)

    def test_incomplete_derivatives_data_is_blocked_not_guessed(self):
        result = scan_btc_market(
            candles(), HEALTHY,
            derivatives_snapshots={"price": {"source": "spot-only"}},
            derivatives_as_of="2026-11-10T12:00:00Z",
        )
        context = result["derivatives_intelligence"]
        self.assertEqual(context["status"], "DATA_BLOCKED")
        self.assertEqual(context["classification"], "UNAVAILABLE")
        self.assertFalse(context["execution_enabled"])

    def test_advanced_layer_is_exposed_without_changing_legacy_score(self):
        result = scan_btc_market(candles(), HEALTHY)
        advanced = result["advanced_analysis"]
        self.assertEqual(result["confluence_score"], 8)
        self.assertEqual(result["confluence_total"], 8)
        self.assertTrue(advanced["research_only"])
        self.assertFalse(advanced["execution_enabled"])
        self.assertIn("bullish_score", advanced)
        self.assertIn("bearish_score", advanced)

    def test_candidate_requires_all_eight_confirmations_and_good_data(self):
        result = scan_btc_market(candles(), HEALTHY)
        self.assertEqual(result["status"], "PAPER_CANDIDATE")
        self.assertEqual(result["confluence_score"], 8)
        self.assertIn("all_eight_scanner_checks_passed_paper_review_only", result["reasons"])
        self.assertEqual(result["confluence_total"], 8)
        self.assertTrue(result["paper_candidate_only"])
        self.assertFalse(result["live_orders_placed"])

    def test_returns_ema_rsi_and_atr_context(self):
        result = scan_btc_market(candles(), HEALTHY)
        self.assertGreater(result["ema20"], result["ema50"])
        self.assertGreaterEqual(result["rsi14"], 0)
        self.assertLessEqual(result["rsi14"], 100)
        self.assertGreater(result["atr14"], 0)
        self.assertGreaterEqual(result["adx14"], 0)
        self.assertLessEqual(result["adx14"], 100)
        self.assertGreaterEqual(result["plus_di14"], 0)
        self.assertGreaterEqual(result["minus_di14"], 0)
        self.assertEqual(result["adx_minimum_required"], 20.0)
        self.assertGreater(result["atr_pct"], 0)
        self.assertGreaterEqual(result["close_position_pct"], 0)
        self.assertLessEqual(result["close_position_pct"], 100)

    def test_false_breakout_with_long_upper_wick_is_rejected(self):
        rows = candles()
        rows[-1][2] = rows[-1][4] + 1.2
        result = scan_btc_market(rows, HEALTHY)
        self.assertTrue(result["checks"]["close_above_prior_high"])
        self.assertFalse(result["checks"]["breakout_quality_confirmed"])
        self.assertIn("breakout_upper_wick_rejection_risk", result["reasons"])
        self.assertNotEqual(result["status"], "PAPER_CANDIDATE")

    def test_breakout_with_insufficient_atr_clearance_is_rejected(self):
        result = scan_btc_market(
            candles(prior_high=97.8, current_close=97.82), HEALTHY
        )
        self.assertTrue(result["checks"]["close_above_prior_high"])
        self.assertFalse(result["checks"]["breakout_quality_confirmed"])
        self.assertIn("breakout_close_too_near_prior_high", result["reasons"])

    def test_breakout_quality_thresholds_are_reported(self):
        result = scan_btc_market(candles(), HEALTHY)
        self.assertEqual(result["breakout_buffer_atr_required"], 0.10)
        self.assertIn("adx_trend_strength", result["checks"])
        self.assertEqual(result["checks"]["adx_trend_strength"], result["adx_trend_strength_confirmed"])
        self.assertEqual(result["max_breakout_upper_wick_pct"], 35.0)
        self.assertGreaterEqual(result["breakout_clearance_atr"], 0.10)
        self.assertLessEqual(result["breakout_upper_wick_pct"], 35.0)

    def test_hypothetical_atr_risk_map_is_consistent_and_paper_only(self):
        result = scan_btc_market(candles(), HEALTHY)
        risk = result["hypothetical_risk_map"]
        self.assertTrue(risk["research_only"])
        self.assertFalse(risk["execution_enabled"])
        self.assertEqual(risk["atr_multiple_stop"], 1.5)
        self.assertEqual(risk["atr_multiple_target"], 3.0)
        self.assertAlmostEqual(risk["reward_risk_ratio"], 2.0)
        self.assertLess(risk["stop_level"], risk["reference_price"])
        self.assertGreater(risk["target_level"], risk["reference_price"])
        self.assertGreater(risk["risk_pct"], 0)
        self.assertGreater(risk["reward_pct"], risk["risk_pct"])

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

    def test_rejects_hourly_timestamps_not_aligned_to_utc_boundaries(self):
        rows = candles()
        for row in rows:
            row[0] += 60
        with self.assertRaisesRegex(ValueError, "UTC hour boundaries"):
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

    def test_four_and_six_hour_aggregation_uses_only_complete_utc_bars(self):
        rows = []
        for index in range(72):
            timestamp = index * 3600
            price = 100.0 + index * 0.1
            rows.append([timestamp, price, price + 1, price - 1, price + 0.5,
                         0.0, 2.0, 10])
        four = _aggregate_hourly_candles(rows, 4)
        six = _aggregate_hourly_candles(rows, 6)
        self.assertEqual(len(four), 18)
        self.assertEqual(len(six), 12)
        self.assertEqual(four[0][0], 0)
        self.assertEqual(four[0][6], 8.0)
        self.assertEqual(four[0][7], 40)
        self.assertEqual(four[0][2], max(row[2] for row in rows[:4]))
        self.assertEqual(four[0][3], min(row[3] for row in rows[:4]))

    def test_aggregation_discards_incomplete_periods_and_rejects_bad_order(self):
        rows = []
        for index in range(25):
            price = 100.0 + index
            rows.append([index * 3600, price, price + 1, price - 1,
                         price + 0.5, 0.0, 2.0, 10])
        self.assertEqual(len(_aggregate_hourly_candles(rows, 4)), 6)
        with self.assertRaisesRegex(ValueError, "strictly increasing"):
            _aggregate_hourly_candles([rows[1], rows[0]], 4)

    def test_aggregation_rejects_invalid_source_candles_before_grouping(self):
        rows = []
        for index in range(4):
            price = 100.0 + index
            rows.append([index * 3600, price, price + 2, price - 2,
                         price + 1, 0.0, 2.0, 10])
        # Other candles would mask this malformed high after aggregation.
        rows[0][2] = rows[0][1] - 1
        with self.assertRaisesRegex(ValueError, "inconsistent OHLC bounds"):
            _aggregate_hourly_candles(rows, 4)

    def test_aggregation_rejects_invalid_activity_in_incomplete_period(self):
        rows = [[0, 100.0, 101.0, 99.0, 100.5, 0.0, -1.0, 10]]
        with self.assertRaisesRegex(ValueError, "invalid price or activity"):
            _aggregate_hourly_candles(rows, 4)

        rows[0][6] = 1.0
        rows[0][7] = 2.5
        with self.assertRaisesRegex(ValueError, "trade counts must be whole"):
            _aggregate_hourly_candles(rows, 4)

    def test_multi_timeframe_scanner_reports_closed_bar_consensus_only(self):
        rows = []
        for index in range(720):
            close = 100.0 + index * 0.02
            open_price = close - 0.01
            rows.append([index * 3600, open_price, close + 0.2,
                         close - 0.2, close, 0.0, 10.0, 100])
        result = scan_btc_multi_timeframe(rows, HEALTHY)
        self.assertEqual(set(result["timeframes"]), {"1h", "4h", "6h"})
        self.assertEqual(result["consensus"]["required_timeframes"], 3)
        self.assertFalse(result["consensus"]["live_execution_enabled"])
        self.assertTrue(all(x["paper_candidate_only"] for x in result["timeframes"].values()))
        self.assertEqual(result["timeframes"]["4h"]["confluence_total"], 8)
        self.assertEqual(result["timeframes"]["6h"]["confluence_total"], 8)
        self.assertEqual(result["timeframes"]["4h"]["timeframe"], "4h")
        self.assertEqual(result["timeframes"]["6h"]["timeframe"], "6h")
        for item in result["timeframes"].values():
            self.assertEqual(
                item["confluence_pct"],
                round(item["confluence_score"] / item["confluence_total"] * 100.0, 2),
            )
        consensus = result["consensus"]
        self.assertEqual(consensus["evaluated_timeframes"], 3)
        self.assertGreaterEqual(consensus["average_confluence_pct"], 0.0)
        self.assertLessEqual(consensus["average_confluence_pct"], 100.0)
        self.assertIn(consensus["strongest_timeframe"], ("1h", "4h", "6h"))
        self.assertGreaterEqual(consensus["trend_aligned_timeframes"], 0)
        self.assertLessEqual(consensus["trend_aligned_timeframes"], 3)
        self.assertGreaterEqual(consensus["breakout_quality_timeframes"], 0)
        self.assertLessEqual(consensus["breakout_quality_timeframes"], 3)
        self.assertTrue(consensus["paper_review_only"])
        self.assertFalse(consensus["live_execution_enabled"])

    def test_insufficient_timeframes_are_excluded_from_strength_ranking(self):
        rows = []
        for index in range(100):
            close = 100.0 + index * 0.02
            open_price = close - 0.01
            rows.append([index * 3600, open_price, close + 0.2,
                         close - 0.2, close, 0.0, 10.0, 100])
        result = scan_btc_multi_timeframe(rows, HEALTHY)
        consensus = result["consensus"]
        self.assertNotEqual(result["timeframes"]["1h"]["status"], "INSUFFICIENT_HISTORY")
        self.assertEqual(result["timeframes"]["4h"]["status"], "INSUFFICIENT_HISTORY")
        self.assertEqual(result["timeframes"]["6h"]["status"], "INSUFFICIENT_HISTORY")
        self.assertEqual(consensus["evaluated_timeframes"], 1)
        self.assertEqual(
            consensus["average_confluence_pct"],
            result["timeframes"]["1h"]["confluence_pct"],
        )
        self.assertEqual(consensus["strongest_timeframe"], "1h")
        self.assertEqual(consensus["trend_aligned_timeframes"], 1)
        self.assertEqual(
            consensus["breakout_quality_timeframes"],
            int(result["timeframes"]["1h"]["checks"]["breakout_quality_confirmed"]),
        )
        self.assertFalse(consensus["live_execution_enabled"])

    def test_adx_is_bounded_and_directional_on_strong_uptrend(self):
        rows = []
        for index in range(80):
            close = 100.0 + index * 0.8
            rows.append([
                index * 3600, close - 0.2, close + 0.5, close - 0.5,
                close, 0.0, 10.0, 100
            ])
        result = scan_btc_market(rows, HEALTHY)
        self.assertGreaterEqual(result["adx14"], 0.0)
        self.assertLessEqual(result["adx14"], 100.0)
        self.assertGreater(result["plus_di14"], result["minus_di14"])
        self.assertTrue(result["checks"]["adx_trend_strength"])

    def test_adx_is_zero_for_flat_market_without_directional_movement(self):
        rows = [
            [index * 3600, 100.0, 101.0, 99.0, 100.0, 0.0, 10.0, 100]
            for index in range(40)
        ]
        adx_value, plus_di, minus_di = _adx(rows, 14)
        self.assertEqual(adx_value, 0.0)
        self.assertEqual(plus_di, 0.0)
        self.assertEqual(minus_di, 0.0)

    def test_adx_filter_rejects_directionally_weak_breakout_candidate(self):
        rows = candles()
        # ADX confirmation is explicit and a missing/weak directional trend
        # must prevent promotion to a paper candidate.
        result = scan_btc_market(rows, HEALTHY)
        self.assertEqual(
            result["checks"]["adx_trend_strength"],
            result["adx14"] >= 20.0 and result["plus_di14"] > result["minus_di14"],
        )
        self.assertEqual(result["confluence_total"], 8)

    def test_rejects_non_finite_volume(self):
        rows = candles()
        rows[-1][6] = float("nan")
        with self.assertRaises(ValueError):
            scan_btc_market(rows, HEALTHY)


if __name__ == "__main__":
    unittest.main()
