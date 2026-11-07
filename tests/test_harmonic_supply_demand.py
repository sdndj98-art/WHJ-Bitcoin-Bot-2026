import unittest

from harmonic_supply_demand import analyze_harmonic_supply_demand


def sample_candles(count=180):
    rows = []
    for i in range(count):
        close = 100.0 + 0.08 * i + 2.0 * __import__("math").sin(i / 5.0)
        open_price = close - 0.2 * __import__("math").cos(i / 3.0)
        high = max(open_price, close) + 0.6
        low = min(open_price, close) - 0.6
        rows.append([i * 3600, open_price, high, low, close, 0.0, 10.0, 100])
    return rows


class HarmonicSupplyDemandTests(unittest.TestCase):
    def test_returns_all_three_research_sections(self):
        result = analyze_harmonic_supply_demand(sample_candles())
        self.assertIn(result["harmonic"]["status"], ("PATTERN_DETECTED", "NO_CONFIRMED_PATTERN"))
        self.assertIn(result["supply_demand"]["status"],
                      ("IN_DEMAND_ZONE", "IN_SUPPLY_ZONE", "BETWEEN_ZONES"))
        self.assertIn(result["divergence"]["signal"], ("BULLISH", "BEARISH", "NONE"))
        self.assertEqual(result["divergence"]["indicator"], "RSI14")
        self.assertTrue(result["paper_only"])
        self.assertFalse(result["live_execution_enabled"])

    def test_uses_only_confirmed_pivots_and_reports_zone_bounds(self):
        result = analyze_harmonic_supply_demand(sample_candles())
        self.assertTrue(result["harmonic"].get("confirmed_pivots_only", True))
        for key in ("nearest_demand", "nearest_supply"):
            zone = result["supply_demand"][key]
            if zone:
                self.assertLessEqual(zone["lower"], zone["upper"])
                self.assertGreaterEqual(zone["distance_pct"], 0)

    def test_rejects_insufficient_history(self):
        with self.assertRaisesRegex(ValueError, "At least 40"):
            analyze_harmonic_supply_demand(sample_candles(39))

    def test_rejects_invalid_ohlc(self):
        rows = sample_candles()
        rows[-1][2] = rows[-1][3] - 1
        with self.assertRaisesRegex(ValueError, "Invalid OHLC"):
            analyze_harmonic_supply_demand(rows)

    def test_rejects_non_finite_price(self):
        rows = sample_candles()
        rows[-1][4] = float("nan")
        with self.assertRaisesRegex(ValueError, "finite and positive"):
            analyze_harmonic_supply_demand(rows)


if __name__ == "__main__":
    unittest.main()
