import math
import unittest
from unittest.mock import patch

from ema_adx_cross_exchange_lab import (
    fetch_binance_hourly_candles,
    normalize_binance_klines,
    run_cross_exchange_adx_lab,
)


def synthetic_hourly_rows(count=3000):
    rows = []
    previous = 100.0
    for index in range(count):
        close = 100.0 + index * 0.03 + 3.0 * math.sin(index / 23.0)
        open_price = previous
        rows.append([
            index * 3600000,
            open_price,
            max(open_price, close) + 0.6,
            min(open_price, close) - 0.6,
            close,
            10.0,
        ])
        previous = close
    return rows


class CrossExchangeAdxTests(unittest.TestCase):
    def test_normalizes_binance_ohlcv_rows(self):
        result = normalize_binance_klines(synthetic_hourly_rows(3))
        self.assertEqual(len(result), 3)
        self.assertEqual(result[0]["timestamp"], 0)
        self.assertFalse(result[0]["imputed"])
        self.assertAlmostEqual(result[1]["close"], 100.03 + 3.0 * math.sin(1 / 23.0))

    def test_rejects_hourly_gaps_and_malformed_values(self):
        rows = synthetic_hourly_rows(3)
        rows[2][0] += 3600000
        with self.assertRaisesRegex(ValueError, "gap"):
            normalize_binance_klines(rows)
        malformed = synthetic_hourly_rows(1)
        malformed[0][4] = float("nan")
        with self.assertRaisesRegex(ValueError, "Non-finite"):
            normalize_binance_klines(malformed)

    def test_research_requires_sufficient_history(self):
        with self.assertRaisesRegex(ValueError, "at least 365"):
            fetch_binance_hourly_candles(days=30)

    def test_cross_exchange_report_preserves_research_safety(self):
        candles = normalize_binance_klines(synthetic_hourly_rows())
        report = run_cross_exchange_adx_lab(candles)
        self.assertEqual(report["validation_type"], "INDEPENDENT_CROSS_EXCHANGE_REPLICATION")
        self.assertEqual(report["data_source"], "Binance public spot klines")
        self.assertEqual(report["symbol"], "BTCUSDT")
        self.assertEqual(report["hourly_candles"], 3000)
        self.assertTrue(report["research_only"])
        self.assertFalse(report["paper_state_touched"])
        self.assertFalse(report["live_orders_enabled"])
        self.assertEqual(report["thresholds_tested"], [15.0, 20.0, 25.0])


if __name__ == "__main__":
    unittest.main()
