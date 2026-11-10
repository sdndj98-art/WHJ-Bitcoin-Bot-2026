import unittest

from cvd_paper_overlay import validate_cvd_confirmation


class CvdPaperOverlayTests(unittest.TestCase):
    def setUp(self):
        self.evidence = {
            "status": "OK", "available": True, "continuity_verified": True,
            "is_closed": True, "research_only": True, "execution_enabled": False,
            "candle_timestamp": 3600, "interval_seconds": 3600,
            "trade_count": 25, "last_trade_lag_seconds": 2.0,
            "delta_pct": 35.0, "open": 100.0, "close": 102.0,
        }

    def assess(self, evidence=None, **kwargs):
        return validate_cvd_confirmation(
            3600, self.evidence if evidence is None else evidence,
            now_timestamp=7200, **kwargs
        )

    def test_valid_bullish_evidence_is_confirmed(self):
        result = self.assess()
        self.assertEqual(result["direction"], "BULLISH")
        self.assertTrue(result["available"])
        self.assertFalse(result["execution_enabled"])

    def test_bearish_flow_is_classified_bearish(self):
        evidence = dict(self.evidence, delta_pct=-40.0, open=102.0, close=100.0)
        self.assertEqual(self.assess(evidence)["direction"], "BEARISH")

    def test_continuity_must_be_explicitly_verified(self):
        evidence = dict(self.evidence, continuity_verified=False)
        self.assertFalse(self.assess(evidence)["available"])

    def test_open_or_unavailable_candle_is_rejected(self):
        for patch in ({"is_closed": False}, {"available": False}):
            with self.subTest(patch=patch):
                self.assertFalse(self.assess(dict(self.evidence, **patch))["available"])

    def test_timestamp_mismatch_is_rejected(self):
        evidence = dict(self.evidence, candle_timestamp=0)
        self.assertEqual(self.assess(evidence)["reason"], "cvd_candle_timestamp_mismatch")

    def test_insufficient_sample_and_stale_data_are_rejected(self):
        self.assertEqual(
            self.assess(dict(self.evidence, trade_count=2))["reason"],
            "cvd_trade_sample_insufficient",
        )
        self.assertEqual(
            self.assess(dict(self.evidence, last_trade_lag_seconds=500))["reason"],
            "cvd_evidence_stale",
        )

    def test_no_confirmation_when_delta_is_weak_or_disagrees(self):
        weak = dict(self.evidence, delta_pct=3.0)
        disagree = dict(self.evidence, delta_pct=-30.0)
        self.assertEqual(self.assess(weak)["direction"], "NEUTRAL")
        self.assertEqual(self.assess(disagree)["direction"], "NEUTRAL")

    def test_future_or_unclosed_interval_is_rejected(self):
        self.assertEqual(
            self.assess(dict(self.evidence, interval_seconds=7200))["reason"],
            "cvd_candle_not_yet_closed",
        )

    def test_non_finite_values_fail_closed(self):
        self.assertFalse(
            self.assess(dict(self.evidence, delta_pct=float("nan")))["available"]
        )

    def test_invalid_timestamp_and_thresholds_raise(self):
        with self.assertRaises(ValueError):
            validate_cvd_confirmation(True, self.evidence, now_timestamp=7200)
        with self.assertRaises(ValueError):
            validate_cvd_confirmation(3600, self.evidence, now_timestamp=7200, min_abs_delta_pct=0)


if __name__ == "__main__":
    unittest.main()
