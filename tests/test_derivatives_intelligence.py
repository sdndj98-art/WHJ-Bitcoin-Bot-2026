import unittest

from derivatives_intelligence import classify_derivatives_flow


AS_OF = "2026-11-10T12:00:00Z"


def snapshots(price_change, oi_change, **overrides):
    price = {
        "source": "example-venue",
        "symbol": "BTCUSDT",
        "interval_start": "2026-11-10T11:00:00Z",
        "interval_end": "2026-11-10T12:00:00Z",
        "observed_at": "2026-11-10T12:00:00Z",
        "change_pct": price_change,
    }
    oi = dict(price)
    oi["change_pct"] = oi_change
    price.update(overrides.get("price", {}))
    oi.update(overrides.get("oi", {}))
    return price, oi


class DerivativesIntelligenceTests(unittest.TestCase):
    def classify(self, price_change, oi_change, **overrides):
        price, oi = snapshots(price_change, oi_change, **overrides)
        return classify_derivatives_flow(price, oi, as_of=AS_OF)

    def test_four_price_open_interest_regimes(self):
        cases = [
            (1.2, 2.0, "LONG_BUILDUP", "BULLISH"),
            (-1.2, 2.0, "SHORT_BUILDUP", "BEARISH"),
            (1.2, -2.0, "SHORT_COVERING", "BULLISH"),
            (-1.2, -2.0, "LONG_UNWINDING", "BEARISH"),
        ]
        for price, oi, expected_class, expected_direction in cases:
            with self.subTest(price=price, oi=oi):
                result = self.classify(price, oi)
                self.assertEqual(result["status"], "OK")
                self.assertEqual(result["classification"], expected_class)
                self.assertEqual(result["direction"], expected_direction)
                self.assertFalse(result["execution_enabled"])

    def test_small_changes_are_neutral(self):
        result = self.classify(0.01, 0.8)
        self.assertEqual(result["classification"], "NO_CLEAR_BUILDUP")
        self.assertEqual(result["direction"], "NEUTRAL")
        self.assertEqual(result["signal_strength_score"], 0.0)

    def test_mismatched_interval_is_blocked(self):
        result = self.classify(1.0, 1.0, oi={"interval_start": "2026-11-10T10:00:00Z"})
        self.assertEqual(result["status"], "DATA_BLOCKED")

    def test_mismatched_source_is_blocked(self):
        result = self.classify(1.0, 1.0, oi={"source": "other-venue"})
        self.assertEqual(result["status"], "DATA_BLOCKED")

    def test_stale_observations_are_blocked(self):
        result = self.classify(1.0, 1.0, price={"observed_at": "2026-11-10T11:50:00Z"})
        self.assertEqual(result["status"], "DATA_BLOCKED")

    def test_missing_snapshot_is_blocked(self):
        result = classify_derivatives_flow(None, {}, as_of=AS_OF)
        self.assertEqual(result["classification"], "UNAVAILABLE")
        self.assertFalse(result["execution_enabled"])

    def test_non_finite_values_are_blocked(self):
        result = self.classify(float("nan"), 1.0)
        self.assertEqual(result["status"], "DATA_BLOCKED")

    def test_naive_timestamps_are_blocked(self):
        result = self.classify(1.0, 1.0, price={"observed_at": "2026-11-10T12:00:00"})
        self.assertEqual(result["status"], "DATA_BLOCKED")

    def test_observations_cannot_be_future_dated(self):
        result = self.classify(1.0, 1.0, oi={"observed_at": "2026-11-10T12:00:10Z"})
        self.assertEqual(result["status"], "DATA_BLOCKED")


if __name__ == "__main__":
    unittest.main()
