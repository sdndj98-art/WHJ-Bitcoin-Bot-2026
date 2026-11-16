import json
import math
import unittest
from datetime import datetime, timezone

from bitstamp_strategy_family_research import (
    build_bitstamp_strategy_report,
    build_matched_calendar_overlap_report,
)
from research_snapshot import canonical_json_bytes, sha256_bytes


class BitstampStrategyFamilyResearchTests(unittest.TestCase):
    def candles(self, count=1600):
        rows = []
        price = 100.0
        start_ms = (1_700_000_000_000 // 3_600_000) * 3_600_000
        for index in range(count):
            open_price = price
            close = open_price * math.exp(0.00015 + 0.012 * math.sin(index / 19.0)
                                          + 0.003 * math.sin(index / 5.0))
            high = max(open_price, close) * 1.003
            low = min(open_price, close) * 0.997
            rows.append({
                "timestamp": start_ms + index * 3_600_000,
                "open": open_price,
                "high": high,
                "low": low,
                "close": close,
                "volume": 1000.0 + (index % 13) * 25.0,
                "imputed": False,
            })
            price = close
        return rows

    def test_all_17_candidates_have_matched_cost_stress_and_walk_forward(self):
        candles = self.candles()
        report = build_bitstamp_strategy_report(
            candles,
            run_id="unit-test-17",
            code_commit_sha="a" * 40,
            generated_at_utc="2026-11-17T00:00:00+00:00",
            bootstrap_samples=100,
            reference_window=None,
        )
        self.assertEqual(report["candidate_count"], 17)
        self.assertEqual(report["source"], "Bitstamp public BTCUSD spot OHLC")
        self.assertEqual(report["symbol"], "BTCUSD")
        self.assertEqual(report["promotion_status"], "NO_CANDIDATE_PROMOTED")
        self.assertFalse(report["paper_state_touched"])
        self.assertFalse(report["live_orders_enabled"])
        self.assertFalse(report["execution_enabled"])
        self.assertEqual(set(report["cost_stress"]), {"1x", "2x", "3x"})
        self.assertEqual(len(report["ranking_by_net_return"]), 17)
        self.assertEqual(report["rolling_walk_forward"]["fold_count"], 4)
        self.assertEqual(report["protocol"]["oos_open_to_open_returns"], 479)
        self.assertEqual(report["cscv_pbo_status"], "INSUFFICIENT_OOS_OBSERVATIONS")
        self.assertEqual(report["data_quality"]["imputed_hourly_candles"], 0)
        self.assertEqual(len(report["trial_manifest"]), 17)
        self.assertEqual(len(report["rolling_walk_forward_trial_manifest"]), 4)
        json.dumps(report, allow_nan=False)

    def test_higher_fixed_costs_never_improve_candidate_net_return(self):
        report = build_bitstamp_strategy_report(
            self.candles(),
            run_id="unit-test-costs",
            code_commit_sha="b" * 40,
            generated_at_utc="2026-11-17T00:00:00+00:00",
            bootstrap_samples=100,
            reference_window=None,
        )
        one = report["cost_stress"]["1x"]["results"]
        two = report["cost_stress"]["2x"]["results"]
        three = report["cost_stress"]["3x"]["results"]
        for name in one:
            with self.subTest(candidate=name):
                self.assertGreaterEqual(
                    one[name]["strategy"]["net_return"] + 1e-12,
                    two[name]["strategy"]["net_return"],
                )
                self.assertGreaterEqual(
                    two[name]["strategy"]["net_return"] + 1e-12,
                    three[name]["strategy"]["net_return"],
                )

    def test_regime_log_return_attribution_reconciles_to_total_oos_return(self):
        report = build_bitstamp_strategy_report(
            self.candles(),
            run_id="unit-test-regimes",
            code_commit_sha="c" * 40,
            generated_at_utc="2026-11-17T00:00:00+00:00",
            bootstrap_samples=100,
            reference_window=None,
        )
        regime_report = report["market_regime_attribution"]["candidate_attribution"]
        for name, regimes in regime_report.items():
            attributed_log = sum(
                item["strategy_log_growth"] for item in regimes.values()
            )
            expected_log = math.log1p(
                report["cost_stress"]["1x"]["results"][name]["strategy"]["net_return"]
            )
            self.assertAlmostEqual(attributed_log, expected_log, places=8)

    def test_exact_coinbase_calendar_overlap_is_aligned_and_reconciles(self):
        candles = self.candles()
        start_index = 500
        return_count = 800
        end_index = start_index + return_count
        reference = {
            "run_id": "coinbase-reference-test",
            "code_commit_sha": "e" * 40,
            "dataset_sha256": "f" * 64,
            "first_oos_open_timestamp_utc": datetime.fromtimestamp(
                candles[start_index]["timestamp"] / 1000, timezone.utc
            ).isoformat(),
            "last_candle_timestamp_utc": datetime.fromtimestamp(
                candles[end_index]["timestamp"] / 1000, timezone.utc
            ).isoformat(),
            "open_to_open_returns": return_count,
        }
        report = build_matched_calendar_overlap_report(
            candles,
            reference,
            run_id="bitstamp-matched-test",
            code_commit_sha="a" * 40,
            generated_at_utc="2026-11-17T00:00:00+00:00",
            bootstrap_samples=100,
        )
        self.assertEqual(report["status"], "COMPUTED_EXACT_CALENDAR_OVERLAP")
        self.assertEqual(report["candidate_count"], 17)
        self.assertEqual(report["bitstamp"]["start_index"], start_index)
        self.assertEqual(report["bitstamp"]["end_index_inclusive"], end_index)
        self.assertEqual(report["bitstamp"]["open_to_open_returns"], return_count)
        self.assertEqual(
            report["bitstamp"]["matched_oos_candle_count_including_prior_signal_and_endpoint"],
            return_count + 2,
        )
        expected_hash = sha256_bytes(canonical_json_bytes(candles[start_index - 1:end_index + 1]))
        self.assertEqual(report["bitstamp"]["matched_oos_slice_sha256"], expected_hash)
        self.assertEqual(report["cscv_pbo_status"], "COMPUTED_DIAGNOSTIC_ONLY")
        self.assertEqual(set(report["cost_stress"]), {"1x", "2x", "3x"})
        self.assertFalse(report["paper_state_touched"])
        self.assertFalse(report["live_orders_enabled"])

    def test_matched_calendar_evaluation_ignores_rows_after_reference_endpoint(self):
        candles = self.candles()
        start_index = 500
        return_count = 800
        end_index = start_index + return_count
        reference = {
            "run_id": "coinbase-reference-test",
            "code_commit_sha": "e" * 40,
            "dataset_sha256": "f" * 64,
            "first_oos_open_timestamp_utc": datetime.fromtimestamp(
                candles[start_index]["timestamp"] / 1000, timezone.utc
            ).isoformat(),
            "last_candle_timestamp_utc": datetime.fromtimestamp(
                candles[end_index]["timestamp"] / 1000, timezone.utc
            ).isoformat(),
            "open_to_open_returns": return_count,
        }
        original = build_matched_calendar_overlap_report(
            candles, reference, "bitstamp-matched-test", "a" * 40,
            "2026-11-17T00:00:00+00:00", bootstrap_samples=100,
        )
        changed = [dict(row) for row in candles]
        for row in changed[end_index + 1:]:
            row["open"] *= 1.7
            row["high"] *= 1.7
            row["low"] *= 1.7
            row["close"] *= 1.7
            row["volume"] *= 2.0
        altered = build_matched_calendar_overlap_report(
            changed, reference, "bitstamp-matched-test", "a" * 40,
            "2026-11-17T00:00:00+00:00", bootstrap_samples=100,
        )
        self.assertEqual(
            original["ranking_by_net_return"],
            altered["ranking_by_net_return"],
        )
        self.assertEqual(
            original["bitstamp"]["matched_oos_slice_sha256"],
            altered["bitstamp"]["matched_oos_slice_sha256"],
        )

    def test_rejects_reference_window_with_wrong_return_count(self):
        candles = self.candles()
        start_index = 500
        end_index = 1300
        reference = {
            "run_id": "coinbase-reference-test",
            "code_commit_sha": "e" * 40,
            "dataset_sha256": "f" * 64,
            "first_oos_open_timestamp_utc": datetime.fromtimestamp(
                candles[start_index]["timestamp"] / 1000, timezone.utc
            ).isoformat(),
            "last_candle_timestamp_utc": datetime.fromtimestamp(
                candles[end_index]["timestamp"] / 1000, timezone.utc
            ).isoformat(),
            "open_to_open_returns": 799,
        }
        with self.assertRaisesRegex(ValueError, "exact reference return count"):
            build_matched_calendar_overlap_report(
                candles, reference, "bitstamp-matched-test", "a" * 40,
                "2026-11-17T00:00:00+00:00", bootstrap_samples=100,
            )

    def test_rejects_missing_or_duplicate_hourly_bars_instead_of_imputing(self):
        candles = self.candles()
        candles[500]["timestamp"] += 3_600_000
        with self.assertRaisesRegex(ValueError, "gap-free"):
            build_bitstamp_strategy_report(
                candles,
                run_id="unit-test-gap",
                code_commit_sha="d" * 40,
                bootstrap_samples=100,
            )


if __name__ == "__main__":
    unittest.main()
