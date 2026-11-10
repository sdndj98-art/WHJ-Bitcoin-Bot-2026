import json
import tempfile
import unittest
from pathlib import Path

from trade_journal_checkpoint import build_continuity_checkpoint, save_continuity_checkpoint_atomic

from cvd_paper_overlay import build_latest_cvd_confirmation, validate_cvd_confirmation


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

    def test_invalid_candle_interval_fails_closed(self):
        for interval in (0, -1, True, 3600.5, "3600"):
            with self.subTest(interval=interval):
                result = self.assess(dict(self.evidence, interval_seconds=interval))
                self.assertFalse(result["available"])
                self.assertEqual(result["reason"], "cvd_invalid_candle_interval")

    def test_non_finite_values_fail_closed(self):
        self.assertFalse(
            self.assess(dict(self.evidence, delta_pct=float("nan")))["available"]
        )

    def test_verified_journal_builds_latest_closed_candle_confirmation(self):
        with tempfile.TemporaryDirectory() as folder:
            journal = Path(folder) / "trades.jsonl"
            checkpoint_path = Path(folder) / "checkpoint.json"
            events = []
            for offset in range(12):
                events.append({
                    "trade_id": 1000 + offset,
                    "timestamp": 3600 + 100 + offset * 300,
                    "price": 101.0,
                    "qty": 1.0,
                    "side": "buy" if offset < 10 else "sell",
                    "symbol": "BTC/USD",
                })
            journal.write_text(
                "".join(json.dumps(event, separators=(",", ":")) + "\\n" for event in events),
                encoding="utf-8",
            )
            checkpoint = build_continuity_checkpoint(str(journal), "BTC/USD", 1011)
            save_continuity_checkpoint_atomic(str(checkpoint_path), checkpoint)
            candles = [{
                "timestamp": 3600 * 1000, "open": 100.0, "high": 103.0,
                "low": 99.0, "close": 102.0, "volume": 12.0,
            }]
            result = build_latest_cvd_confirmation(
                candles, str(journal), str(checkpoint_path), now_timestamp=7200,
                max_last_trade_lag_seconds=1200,
            )
            self.assertEqual(result["status"], "OK")
            self.assertEqual(result["direction"], "BULLISH")
            self.assertTrue(result["continuity_verified"])
            self.assertFalse(result["execution_enabled"])

    def test_verified_cvd_reader_fails_closed_on_checkpoint_mismatch(self):
        with tempfile.TemporaryDirectory() as folder:
            journal = Path(folder) / "trades.jsonl"
            checkpoint_path = Path(folder) / "checkpoint.json"
            event = {
                "trade_id": 1000, "timestamp": 4000, "price": 101.0,
                "qty": 1.0, "side": "buy", "symbol": "BTC/USD",
            }
            journal.write_text(json.dumps(event) + "\\n", encoding="utf-8")
            checkpoint = build_continuity_checkpoint(str(journal), "BTC/USD", 1000)
            save_continuity_checkpoint_atomic(str(checkpoint_path), checkpoint)
            journal.write_text(journal.read_text(encoding="utf-8") + json.dumps(dict(event, trade_id=1001, timestamp=4100)) + "\\n", encoding="utf-8")
            candles = [{
                "timestamp": 3600 * 1000, "open": 100.0, "high": 103.0,
                "low": 99.0, "close": 102.0, "volume": 12.0,
            }]
            result = build_latest_cvd_confirmation(
                candles, str(journal), str(checkpoint_path), now_timestamp=7200,
            )
            self.assertFalse(result["available"])
            self.assertTrue(result["reason"].startswith("cvd_source_validation_failed:"))

    def test_invalid_timestamp_and_thresholds_raise(self):
        with self.assertRaises(ValueError):
            validate_cvd_confirmation(True, self.evidence, now_timestamp=7200)
        with self.assertRaises(ValueError):
            validate_cvd_confirmation(3600, self.evidence, now_timestamp=7200, min_abs_delta_pct=0)


if __name__ == "__main__":
    unittest.main()
