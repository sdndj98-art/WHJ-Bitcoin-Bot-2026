"""Tests for the incremental BTC/USD market-data cache."""
import json
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import patch

from historical_research import INTERVAL_MS
from market_data_cache import (
    DEFAULT_OVERLAP_HOURS,
    update_market_data_cache,
)


class MarketDataCacheTests(unittest.TestCase):
    def make_candles(self, count, end_timestamp):
        start = end_timestamp - (count - 1) * INTERVAL_MS
        rows = []
        for index in range(count):
            timestamp = start + index * INTERVAL_MS
            price = 30000.0 + index
            rows.append({
                "timestamp": timestamp, "open": price, "high": price + 2,
                "low": price - 2, "close": price + 1, "volume": 1.0,
                "imputed": False,
            })
        return rows

    @staticmethod
    def as_coinbase_rows(start_ms, end_ms):
        """Return fetch_page's normalized [time, open, high, low, close, volume] rows."""
        rows = []
        timestamp = start_ms
        while timestamp <= end_ms:
            price = 40000.0 + timestamp / INTERVAL_MS % 1000
            rows.append([
                timestamp, price, price + 2, price - 1,
                price + 1, 3.0,
            ])
            timestamp += INTERVAL_MS
        return rows

    def test_bootstraps_once_and_writes_versioned_cache(self):
        now = datetime(2026, 11, 11, 12, 0, tzinfo=timezone.utc)
        cutoff = int(now.timestamp() * 1000)
        candles = self.make_candles(1100, cutoff - INTERVAL_MS)
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "cache.json"
            with patch("market_data_cache.load_two_year_candles", return_value=candles) as loader:
                result = update_market_data_cache(path, now=now, bootstrap_days=45)
            loader.assert_called_once()
            payload = json.loads(path.read_text(encoding="utf-8"))
            self.assertEqual(payload["schema_version"], 1)
            self.assertEqual(payload["market"], "BTC-USD")
            self.assertEqual(payload["granularity_seconds"], 3600)
            self.assertEqual(payload["candle_count"], len(result))
            self.assertEqual(result[-1]["timestamp"], cutoff - INTERVAL_MS)

    def test_incremental_update_fetches_overlap_and_appends_new_closed_hours(self):
        first_now = datetime(2026, 11, 11, 12, 0, tzinfo=timezone.utc)
        second_now = datetime(2026, 11, 11, 16, 0, tzinfo=timezone.utc)
        first_cutoff = int(first_now.timestamp() * 1000)
        second_cutoff = int(second_now.timestamp() * 1000)
        initial = self.make_candles(1100, first_cutoff - INTERVAL_MS)
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "cache.json"
            with patch("market_data_cache.load_two_year_candles", return_value=initial):
                first = update_market_data_cache(path, now=first_now, bootstrap_days=45)
            expected_start = first[-1]["timestamp"] - DEFAULT_OVERLAP_HOURS * INTERVAL_MS
            fetched = self.as_coinbase_rows(expected_start, second_cutoff)
            with patch("market_data_cache.fetch_page", return_value=fetched) as fetch:
                second = update_market_data_cache(path, now=second_now, bootstrap_days=45)
            fetch.assert_called_once_with(expected_start, second_cutoff)
            self.assertEqual(second[-1]["timestamp"], second_cutoff - INTERVAL_MS)
            self.assertEqual(len(second), len(first))  # rolling 45-day window replaces four oldest hours
            self.assertEqual(len({row["timestamp"] for row in second}), len(second))
            self.assertEqual(json.loads(path.read_text())["candle_count"], len(second))

    def test_corrupt_cache_is_not_silently_rebootstrapped(self):
        now = datetime(2026, 11, 11, 12, 0, tzinfo=timezone.utc)
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "cache.json"
            path.write_text("{broken", encoding="utf-8")
            with patch("market_data_cache.load_two_year_candles") as loader:
                with self.assertRaisesRegex(ValueError, "unreadable"):
                    update_market_data_cache(path, now=now, bootstrap_days=45)
            loader.assert_not_called()
            self.assertEqual(path.read_text(encoding="utf-8"), "{broken")

    def test_large_gap_is_rejected_without_overwriting_cache(self):
        first_now = datetime(2026, 11, 11, 12, 0, tzinfo=timezone.utc)
        next_now = datetime(2026, 11, 11, 22, 0, tzinfo=timezone.utc)
        cutoff = int(first_now.timestamp() * 1000)
        next_cutoff = int(next_now.timestamp() * 1000)
        initial = self.make_candles(1100, cutoff - INTERVAL_MS)
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "cache.json"
            with patch("market_data_cache.load_two_year_candles", return_value=initial):
                update_market_data_cache(path, now=first_now, bootstrap_days=45)
            before = path.read_bytes()
            start = initial[-1]["timestamp"] - DEFAULT_OVERLAP_HOURS * INTERVAL_MS
            broken = self.as_coinbase_rows(start, next_cutoff)
            # Remove seven genuinely new hours; they are not present in the old cache.
            broken = [row for row in broken if not (
                cutoff <= row[0] <= cutoff + 6 * INTERVAL_MS
            )]
            with patch("market_data_cache.fetch_page", return_value=broken):
                with self.assertRaisesRegex(ValueError, "six-hour repair limit"):
                    update_market_data_cache(path, now=next_now, bootstrap_days=45)
            self.assertEqual(path.read_bytes(), before)


if __name__ == "__main__":
    unittest.main()
