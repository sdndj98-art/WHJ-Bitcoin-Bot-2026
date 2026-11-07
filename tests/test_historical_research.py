"""Unit tests for the historical data ingestion gate."""
import math
import unittest
from datetime import datetime, timezone
from unittest.mock import patch

from historical_research import (INTERVAL_MS, aggregate_candles, load_two_year_candles, run_forward_paper_accounts, run_ohlc_breakout_lab, run_long_short_lab, run_daily_regime_filter_lab, _turtle_signals)


class HistoricalResearchTests(unittest.TestCase):
    def make_page(self, start_ms, end_ms, skip_timestamp=None):
        rows = []
        timestamp = start_ms
        while timestamp <= end_ms:
            if timestamp != skip_timestamp:
                price = 50000.0 + (timestamp // INTERVAL_MS % 1000)
                rows.append([timestamp, price, price + 10, price - 10, price + 1, 2.0])
            timestamp += INTERVAL_MS
        return rows

    def test_download_paginates_and_discards_current_open_hour(self):
        now = datetime(2026, 11, 7, 12, 0, tzinfo=timezone.utc)
        with patch("historical_research.fetch_page", side_effect=self.make_page):
            candles = load_two_year_candles(days=45, now=now)
        self.assertEqual(len(candles), 45 * 24)
        self.assertEqual(candles[-1]["timestamp"], int(now.timestamp() * 1000) - INTERVAL_MS)
        self.assertEqual(candles[0]["timestamp"] + (len(candles) - 1) * INTERVAL_MS,
                         candles[-1]["timestamp"])

    def test_short_missing_hour_is_imputed_and_flagged(self):
        now = datetime(2026, 11, 7, 12, 0, tzinfo=timezone.utc)
        calls = {"count": 0}

        def page_with_gap(start_ms, end_ms):
            calls["count"] += 1
            missing = start_ms + 100 * INTERVAL_MS if calls["count"] == 1 else None
            return self.make_page(start_ms, end_ms, skip_timestamp=missing)

        with patch("historical_research.fetch_page", side_effect=page_with_gap):
            candles = load_two_year_candles(days=45, now=now)
        self.assertEqual(candles[0]["_imputed_hour_count"], 1)
        self.assertEqual(sum(1 for candle in candles if candle["imputed"]), 1)

    def test_large_missing_interval_is_rejected(self):
        now = datetime(2026, 11, 7, 12, 0, tzinfo=timezone.utc)
        calls = {"count": 0}

        def page_with_large_gap(start_ms, end_ms):
            calls["count"] += 1
            missing = start_ms + 100 * INTERVAL_MS if calls["count"] == 1 else None
            rows = self.make_page(start_ms, end_ms)
            if missing is not None:
                rows = [row for row in rows if row[0] < missing or row[0] >= missing + 8 * INTERVAL_MS]
            return rows

        with patch("historical_research.fetch_page", side_effect=page_with_large_gap):
            with self.assertRaisesRegex(ValueError, "six-hour repair limit"):
                load_two_year_candles(days=45, now=now)

    def test_timeframe_aggregation_uses_only_complete_utc_bars(self):
        candles = []
        for index in range(24 * 205):
            timestamp = index * INTERVAL_MS
            price = 100.0 + index
            candles.append({
                "timestamp": timestamp,
                "open": price,
                "high": price + 2,
                "low": price - 2,
                "close": price + 1,
                "volume": 1.0,
                "imputed": index == 10,
            })
        four_hour = aggregate_candles(candles, 4)
        daily = aggregate_candles(candles, 24)
        self.assertEqual(len(four_hour), (24 * 205) // 4)
        self.assertEqual(len(daily), 205)
        self.assertEqual(four_hour[0]["open"], candles[0]["open"])
        self.assertEqual(four_hour[0]["close"], candles[3]["close"])
        self.assertEqual(four_hour[0]["high"], candles[3]["high"])
        self.assertTrue(four_hour[2]["imputed"])
        self.assertEqual(daily[0]["volume"], 24.0)

    def test_forward_paper_accounts_persist_and_are_idempotent(self):
        import tempfile

        candles = []
        for index in range(24 * 210):
            timestamp = index * INTERVAL_MS
            price = 50000.0 + index * 2.0
            candles.append({
                "timestamp": timestamp,
                "open": price,
                "high": price + 5,
                "low": price - 5,
                "close": price + 2,
                "volume": 3.0,
                "imputed": False,
            })
        with tempfile.TemporaryDirectory() as folder:
            first = run_forward_paper_accounts(candles, state_dir=folder)
            second = run_forward_paper_accounts(candles, state_dir=folder)
        self.assertEqual(first["daily_sma20_50"]["processed_new_candles"], 210)
        self.assertEqual(first["four_hour_ema50_200"]["processed_new_candles"], 1260)
        self.assertEqual(first["daily_bollinger_mean_reversion"]["processed_new_candles"], 210)
        self.assertEqual(second["daily_sma20_50"]["processed_new_candles"], 0)
        self.assertEqual(second["four_hour_ema50_200"]["processed_new_candles"], 0)
        self.assertEqual(second["daily_bollinger_mean_reversion"]["processed_new_candles"], 0)

    def test_turtle_breakout_uses_prior_channel_and_reports_costs(self):
        bars = []
        for index in range(600):
            close = 100.0 + index * 1.0
            bars.append({
                "timestamp": index * 86400000,
                "open": close - 0.1,
                "high": close + 0.5,
                "low": close - 0.5,
                "close": close,
                "volume": 10.0,
                "imputed": False,
            })
        signals = _turtle_signals(bars, 55, 20)
        self.assertFalse(signals[54])
        self.assertTrue(signals[55])
        result = run_ohlc_breakout_lab(bars)
        self.assertIn("donchian_55_20_sma200", result["strategies"])
        self.assertIn("buy_and_hold_25pct", result["strategies"])
        self.assertTrue(all(
            window["start_index"] >= result["split_index"]
            for window in result["strategies"]["donchian_55_20"]["walk_forward_windows"]
        ))
        self.assertTrue(math.isfinite(result["strategies"]["donchian_55_20"]["out_of_sample"]["return_pct"]))

    def test_daily_regime_filter_uses_complete_daily_history(self):
        candles = []
        for index in range(24 * 210):
            timestamp = index * INTERVAL_MS
            price = 50000.0 + index * 0.2
            candles.append({
                "timestamp": timestamp,
                "open": price - 1,
                "high": price + 3,
                "low": price - 3,
                "close": price,
                "volume": 2.0,
                "imputed": False,
            })
        result = run_daily_regime_filter_lab(candles)
        self.assertEqual(result["daily_bar_count"], 210)
        self.assertIn("ema50_200_with_daily_sma200", result["strategies"])
        self.assertTrue(all(
            window["start_index"] >= result["split_index"]
            for window in result["strategies"]["ema50_200_with_daily_sma200"]["walk_forward_windows"]
        ))

    def test_long_short_research_charges_funding_and_matches_benchmark(self):
        bars = []
        for index in range(600):
            close = 50000.0 + index * 10.0
            bars.append({
                "timestamp": index * 86400000,
                "open": close - 1,
                "high": close + 5,
                "low": close - 5,
                "close": close,
                "volume": 10.0,
                "imputed": False,
            })
        result = run_long_short_lab(bars)
        self.assertIn("sma200_long_short", result["strategies"])
        self.assertIn("sma200_slope_20_long_short", result["strategies"])
        self.assertIn("ema50_200_slope_20_long_short", result["strategies"])
        self.assertIn("buy_and_hold_25pct", result["strategies"])
        self.assertTrue(all(
            window["start_index"] >= result["split_index"]
            for window in result["strategies"]["sma200_long_short"]["walk_forward_windows"]
        ))
        metrics = result["strategies"]["sma200_long_short"]["out_of_sample"]
        self.assertGreater(metrics["funding_paid_usd"], 0)
        self.assertTrue(math.isfinite(metrics["return_pct"]))
        with self.assertRaises(ValueError):
            run_long_short_lab(bars, funding_rate_per_8h=-0.1)

    def test_turtle_breakout_rejects_invalid_ohlc(self):
        bars = []
        for index in range(600):
            price = 100.0 + index
            bars.append({
                "timestamp": index,
                "open": price,
                "high": price + 1,
                "low": price - 1,
                "close": price,
                "volume": 1.0,
            })
        bars[100]["high"] = bars[100]["open"] - 2
        with self.assertRaisesRegex(ValueError, "Invalid OHLC high"):
            run_ohlc_breakout_lab(bars)

    def test_invalid_ohlc_relationship_is_rejected(self):
        now = datetime(2026, 11, 7, 12, 0, tzinfo=timezone.utc)

        def invalid_page(start_ms, end_ms):
            rows = self.make_page(start_ms, end_ms)
            if rows:
                rows[0][2] = rows[0][1] - 5
            return rows

        with patch("historical_research.fetch_page", side_effect=invalid_page):
            with self.assertRaisesRegex(ValueError, "Impossible OHLC"):
                load_two_year_candles(days=45, now=now)


if __name__ == "__main__":
    unittest.main()
