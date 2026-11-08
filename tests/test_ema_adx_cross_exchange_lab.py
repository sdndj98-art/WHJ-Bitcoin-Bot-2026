import math
import unittest
from datetime import datetime, timezone
from unittest.mock import patch

from ema_adx_cross_exchange_lab import (
    fetch_bitstamp_hourly_candles,
    normalize_bitstamp_ohlc,
    run_cross_exchange_adx_lab,
)


def synthetic_bitstamp_payload(count=3000):
    rows = []
    previous = 100.0
    for index in range(count):
        close = 100.0 + index * 0.03 + 3.0 * math.sin(index / 23.0)
        open_price = previous
        rows.append({
            "timestamp": str(index * 3600),
            "open": str(open_price),
            "high": str(max(open_price, close) + 0.6),
            "low": str(min(open_price, close) - 0.6),
            "close": str(close),
            "volume": "10.0",
        })
        previous = close
    return {"data": {"ohlc": rows}}


class CrossExchangeAdxTests(unittest.TestCase):
    def test_normalizes_bitstamp_ohlc_rows(self):
        result = normalize_bitstamp_ohlc(synthetic_bitstamp_payload(3))
        self.assertEqual(len(result), 3)
        self.assertEqual(result[0]["timestamp"], 0)
        self.assertFalse(result[0]["imputed"])
        self.assertAlmostEqual(result[1]["close"], 100.03 + 3.0 * math.sin(1 / 23.0))

    def test_rejects_hourly_gaps_and_malformed_values(self):
        payload = synthetic_bitstamp_payload(3)
        payload["data"]["ohlc"][2]["timestamp"] = str(3 * 3600)
        with self.assertRaisesRegex(ValueError, "gap"):
            normalize_bitstamp_ohlc(payload)
        malformed = synthetic_bitstamp_payload(1)
        malformed["data"]["ohlc"][0]["close"] = "nan"
        with self.assertRaisesRegex(ValueError, "Non-finite"):
            normalize_bitstamp_ohlc(malformed)

    def test_research_requires_sufficient_history(self):
        with self.assertRaisesRegex(ValueError, "at least 365"):
            fetch_bitstamp_hourly_candles(days=30)

    def test_backward_pagination_covers_full_hourly_window_without_gaps(self):
        start = datetime(2025, 1, 1, tzinfo=timezone.utc)
        now = datetime(2026, 1, 1, tzinfo=timezone.utc)
        start_seconds = int(start.timestamp())
        all_rows = []
        previous = 100.0
        for index in range(365 * 24):
            close = 100.0 + index * 0.001 + math.sin(index / 31.0)
            open_price = previous
            all_rows.append({
                "timestamp": str(start_seconds + index * 3600),
                "open": str(open_price),
                "high": str(max(open_price, close) + 0.2),
                "low": str(min(open_price, close) - 0.2),
                "close": str(close),
                "volume": "1.0",
            })
            previous = close

        requested_ends = []

        def page(end_seconds):
            requested_ends.append(end_seconds)
            eligible = [row for row in all_rows if int(row["timestamp"]) <= end_seconds]
            return {"data": {"ohlc": eligible[-1000:]}}

        with patch("ema_adx_cross_exchange_lab._request_bitstamp_page", side_effect=page), patch(
            "ema_adx_cross_exchange_lab.time.sleep"
        ):
            result = fetch_bitstamp_hourly_candles(days=365, now=now)

        self.assertEqual(len(result), 365 * 24)
        self.assertEqual(result[0]["timestamp"], start_seconds * 1000)
        self.assertEqual(result[-1]["timestamp"], (start_seconds + (365 * 24 - 1) * 3600) * 1000)
        self.assertGreater(len(requested_ends), 8)
        self.assertEqual(len({row["timestamp"] for row in result}), len(result))

    def test_cross_exchange_report_preserves_research_safety(self):
        candles = normalize_bitstamp_ohlc(synthetic_bitstamp_payload())
        report = run_cross_exchange_adx_lab(candles)
        self.assertEqual(report["validation_type"], "INDEPENDENT_CROSS_EXCHANGE_REPLICATION")
        self.assertEqual(report["data_source"], "Bitstamp public spot OHLC")
        self.assertEqual(report["symbol"], "BTCUSD")
        self.assertEqual(report["hourly_candles"], 3000)
        self.assertTrue(report["research_only"])
        self.assertFalse(report["paper_state_touched"])
        self.assertFalse(report["live_orders_enabled"])
        self.assertEqual(report["thresholds_tested"], [15.0, 20.0, 25.0])


if __name__ == "__main__":
    unittest.main()
