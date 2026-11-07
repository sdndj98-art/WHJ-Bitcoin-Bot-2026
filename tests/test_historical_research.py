"""Unit tests for the historical data ingestion gate."""
import unittest
from datetime import datetime, timezone
from unittest.mock import patch

from historical_research import INTERVAL_MS, load_two_year_candles


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

    def test_missing_hour_is_rejected(self):
        now = datetime(2026, 11, 7, 12, 0, tzinfo=timezone.utc)
        calls = {"count": 0}

        def page_with_gap(start_ms, end_ms):
            calls["count"] += 1
            # Skip one point in the first requested chunk.
            missing = start_ms + 100 * INTERVAL_MS if calls["count"] == 1 else None
            return self.make_page(start_ms, end_ms, skip_timestamp=missing)

        with patch("historical_research.fetch_page", side_effect=page_with_gap):
            with self.assertRaisesRegex(ValueError, "missing hourly intervals"):
                load_two_year_candles(days=45, now=now)

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
