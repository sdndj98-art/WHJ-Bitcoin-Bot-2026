import json
import math
import unittest

from bitstamp_strategy_family_research import build_bitstamp_strategy_report


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
        )
        regime_report = report["market_regime_attribution"]["candidate_attribution"]
        for name, regimes in regime_report.items():
            attributed_log = sum(
                math.log1p(item["strategy_attributed_compounded_return_pct"] / 100.0)
                for item in regimes.values()
            )
            expected_log = math.log1p(
                report["cost_stress"]["1x"]["results"][name]["strategy"]["net_return"]
            )
            self.assertAlmostEqual(attributed_log, expected_log, places=8)

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
