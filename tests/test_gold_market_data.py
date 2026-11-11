import unittest
from gold_market_data import load_gold_daily, parse_yahoo_chart


def payload(n=1100):
    timestamps = list(range(1_600_000_000, 1_600_000_000 + n * 86400, 86400))
    close = [1800.0 + i * 0.1 for i in range(n)]
    return {"chart": {"result": [{
        "timestamp": timestamps,
        "indicators": {"quote": [{
            "open": close,
            "high": [x + 2 for x in close],
            "low": [x - 2 for x in close],
            "close": close,
            "volume": [1000] * n,
        }]},
    }], "error": None}}


class GoldMarketDataTests(unittest.TestCase):
    def test_parser_normalizes_and_drops_last_potentially_open_daily_bar(self):
        rows = parse_yahoo_chart(payload())
        self.assertEqual(len(rows), 1099)
        self.assertEqual(rows[0]["open"], 1800.0)
        self.assertEqual(rows[-1]["close"], 1800.0 + 1098 * 0.1)
        self.assertFalse(rows[-1]["imputed"])
        self.assertGreater(rows[-1]["timestamp"], rows[0]["timestamp"])

    def test_rejects_missing_or_misaligned_ohlc_arrays(self):
        data = payload()
        data["chart"]["result"][0]["indicators"]["quote"][0]["close"].pop()
        with self.assertRaises(ValueError):
            parse_yahoo_chart(data)

    def test_rejects_impossible_ohlc_and_duplicate_timestamps(self):
        data = payload()
        data["chart"]["result"][0]["indicators"]["quote"][0]["high"][20] = 1
        with self.assertRaises(ValueError):
            parse_yahoo_chart(data)
        data = payload()
        data["chart"]["result"][0]["timestamp"][10] = data["chart"]["result"][0]["timestamp"][9]
        with self.assertRaises(ValueError):
            parse_yahoo_chart(data)

    def test_rejects_api_error_and_invalid_period(self):
        with self.assertRaises(RuntimeError):
            parse_yahoo_chart({"chart": {"error": {"description": "unavailable"}}})
        with self.assertRaises(ValueError):
            load_gold_daily(period="1y")


if __name__ == "__main__":
    unittest.main()
