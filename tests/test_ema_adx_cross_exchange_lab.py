import math
import unittest

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
