import unittest

from market_universe import classify_symbol, discover_market_universe, core_market_symbols


class MarketUniverseTests(unittest.TestCase):
    def test_broker_suffixes_are_classified(self):
        self.assertEqual(classify_symbol("EURUSD.a"), "FOREX")
        self.assertEqual(classify_symbol("USDJPYm"), "FOREX")
        self.assertEqual(classify_symbol("XAUUSDm"), "PRECIOUS_METAL")
        self.assertEqual(classify_symbol("XAGUSD"), "PRECIOUS_METAL")
        self.assertEqual(classify_symbol("BTCUSD.a"), "CRYPTO")

    def test_dynamic_broker_discovery_preserves_exact_names(self):
        result = discover_market_universe(["EURUSD.a", "XAUUSDm", "BTCUSD", "US30"])
        self.assertEqual(result["categories"]["FOREX"], ["EURUSD.a"])
        self.assertEqual(result["categories"]["PRECIOUS_METAL"], ["XAUUSDm"])
        self.assertEqual(result["categories"]["CRYPTO"], ["BTCUSD"])
        self.assertEqual(result["categories"]["OTHER"], ["US30"])
        self.assertFalse(result["live_orders_enabled"])

    def test_core_universe_includes_gold_and_all_precious_metals(self):
        symbols = core_market_symbols()
        self.assertIn("EURUSD", symbols["forex"])
        self.assertEqual(symbols["metals"], ["XAUUSD", "XAGUSD", "XPTUSD", "XPDUSD"])
        self.assertIn("BTCUSD", symbols["crypto"])


if __name__ == "__main__":
    unittest.main()
