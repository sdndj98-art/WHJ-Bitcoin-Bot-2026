import unittest
from datetime import datetime, timezone
from unittest.mock import patch

import metal_price_sources as sources


class MetalPriceSourceTests(unittest.TestCase):
    def test_gold_api_spot_maps_symbol_and_validates_timestamp_unit(self):
        now = datetime(2026, 11, 21, 12, 0, tzinfo=timezone.utc).timestamp()
        payload = {
            "symbol": "XAU", "currency": "USD", "unit": "oz", "price": 4021.50,
            "updatedAt": datetime.fromtimestamp(now - 35, timezone.utc).isoformat(),
        }
        with patch.object(sources, "_get_json", return_value=payload) as get:
            quote = sources.fetch_spot("XAUUSD", now)
        self.assertEqual(quote["price_unit"], "troy_ounce")
        self.assertEqual(quote["price_usd"], 4021.5)
        self.assertIn("/price/XAU", get.call_args.args[0])

    def test_gold_api_rejects_stale_or_wrong_units(self):
        now = datetime(2026, 11, 21, 12, 0, tzinfo=timezone.utc).timestamp()
        payload = {
            "symbol": "XPT", "currency": "USD", "unit": "oz", "price": 1234.5,
            "updatedAt": datetime.fromtimestamp(now - 6 * 60, timezone.utc).isoformat(),
        }
        with patch.object(sources, "_get_json", return_value=payload):
            with self.assertRaisesRegex(ValueError, "5-minute safety age"):
                sources.fetch_spot("XPTUSD", now)
        payload["unit"] = "lb"
        payload["updatedAt"] = datetime.fromtimestamp(now - 30, timezone.utc).isoformat()
        with patch.object(sources, "_get_json", return_value=payload):
            with self.assertRaisesRegex(ValueError, "unit mismatch"):
                sources.fetch_spot("XPTUSD", now)


    def test_daily_bars_use_free_tier_and_validate_closed_ohlc(self):
        now = datetime(2026, 11, 21, 12, 0, tzinfo=timezone.utc).timestamp()
        bars = []
        for day in range(1, 21):
            stamp = datetime(2026, 11, day, tzinfo=timezone.utc).isoformat()
            bars.append({
                "bar_start": stamp, "open": "4000", "high": "4020",
                "low": "3980", "close": str(4000 + day), "volume": None,
                "is_closed": True,
            })
        payload = {"symbol": "XAU", "interval": "1d", "bars": bars, "next_cursor": None}
        with patch.object(sources, "_get_json", return_value=payload) as get:
            result = sources.fetch_daily_bars("XAUUSD", now)
        self.assertEqual(len(result), 20)
        self.assertEqual(result[-1][4], 4020.0)
        self.assertIn("interval=1d", get.call_args.args[0])

    def test_daily_feed_rejects_wrong_interval(self):
        now = datetime(2026, 11, 21, 12, 0, tzinfo=timezone.utc).timestamp()
        with patch.object(sources, "_get_json", return_value={
            "symbol": "XAU", "interval": "1h", "bars": []
        }):
            with self.assertRaisesRegex(ValueError, "interval mismatch"):
                sources.fetch_daily_bars("XAUUSD", now)


if __name__ == "__main__":
    unittest.main()
