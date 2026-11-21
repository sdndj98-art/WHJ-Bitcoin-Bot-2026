import unittest
from datetime import datetime, timezone
from unittest.mock import patch

import metal_price_sources as sources


class MetalPriceSourceTests(unittest.TestCase):
    def test_validated_xau_spot_maps_symbol_and_checks_15m_delay(self):
        now = datetime(2026, 11, 21, 12, 0, tzinfo=timezone.utc).timestamp()
        payload = {"symbols": [{
            "symbol": "XAU", "quote_currency": "USD", "contract_type": "spot",
            "price": "4021.50", "is_stale": False,
            "computed_at": datetime.fromtimestamp(now - 900, timezone.utc).isoformat(),
        }]}
        with patch.object(sources, "_get_json", return_value=payload) as get:
            quote = sources.fetch_spot("XAUUSD", now)
        self.assertEqual(quote["provider_symbol"], "XAU-USD-SPOT")
        self.assertEqual(quote["price_usd"], 4021.5)
        self.assertEqual(quote["expected_delay_minutes"], 15)
        self.assertIn("XAU-USD-SPOT", get.call_args.args[0])

    def test_rejects_stale_spot(self):
        now = datetime(2026, 11, 21, 12, 0, tzinfo=timezone.utc).timestamp()
        payload = {"symbols": [{
            "symbol": "XAG", "quote_currency": "USD", "contract_type": "spot",
            "price": "49.2", "is_stale": True,
            "computed_at": datetime.fromtimestamp(now - 60, timezone.utc).isoformat(),
        }]}
        with patch.object(sources, "_get_json", return_value=payload):
            with self.assertRaisesRegex(ValueError, "stale"):
                sources.fetch_spot("XAGUSD", now)

    def test_free_tier_plan_gate_does_not_create_fake_hourly_bars(self):
        with patch.object(sources, "_get_json", side_effect=ValueError("HTTP 403 plan_gated")):
            with self.assertRaisesRegex(ValueError, "403"):
                sources.fetch_hourly_bars("XAUUSD", 1795262400)


if __name__ == "__main__":
    unittest.main()
