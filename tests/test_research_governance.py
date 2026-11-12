import unittest

from research_governance import (
    build_trial_manifest,
    canonical_manifest_json,
    cscv_probability_of_backtest_overfitting,
    moving_block_bootstrap_return_ci,
    trade_concentration_diagnostic,
)


class ResearchGovernanceTests(unittest.TestCase):
    def test_manifest_is_canonical_and_preserves_provenance(self):
        manifest = build_trial_manifest(
            "trial-001", "ema-adx", {"ema": 50, "adx": 15},
            "a" * 64, "BTC-USD spot hourly", "b" * 40,
            "run-001", "2026-11-12T12:00:00Z", "chronological OOS",
        )
        self.assertEqual(manifest["selection_status"], "UNASSESSED")
        self.assertEqual(manifest["dataset_sha256"], "a" * 64)
        self.assertEqual(
            canonical_manifest_json(manifest),
            canonical_manifest_json(dict(reversed(list(manifest.items())))),
        )

    def test_manifest_rejects_bad_hash_and_nonserializable_parameters(self):
        args = (
            "trial-001", "ema-adx", {"ema": 50}, "bad", "BTC-USD",
            "b" * 40, "run-001", "2026-11-12T12:00:00Z", "OOS",
        )
        with self.assertRaises(ValueError):
            build_trial_manifest(*args)
        args = (
            "trial-001", "ema-adx", {"bad": object()}, "a" * 64, "BTC-USD",
            "b" * 40, "run-001", "2026-11-12T12:00:00Z", "OOS",
        )
        with self.assertRaises(TypeError):
            build_trial_manifest(*args)

    def test_cscv_pbo_is_reproducible_and_reports_all_trials(self):
        a = [0.002, 0.003, -0.001, 0.004, 0.002, -0.002, 0.003, 0.001] * 4
        b = [0.001, 0.002, 0.001, 0.002, 0.001, 0.002, 0.001, 0.002] * 4
        result = cscv_probability_of_backtest_overfitting(
            {"trend": a, "steady": b}, partitions=8
        )
        self.assertEqual(result["method"], "CSCV_PBO")
        self.assertEqual(result["trial_count"], 2)
        self.assertEqual(result["split_count"], 35)
        self.assertGreaterEqual(result["pbo_estimate"], 0)
        self.assertLessEqual(result["pbo_estimate"], 1)

    def test_cscv_rejects_misaligned_or_too_short_series(self):
        with self.assertRaises(ValueError):
            cscv_probability_of_backtest_overfitting(
                {"a": [0.01] * 16, "b": [0.01] * 15}, partitions=8
            )
        with self.assertRaises(ValueError):
            cscv_probability_of_backtest_overfitting(
                {"a": [0.01] * 8, "b": [0.02] * 8}, partitions=3
            )

    def test_bootstrap_ci_is_reproducible_and_finite(self):
        values = [0.01, -0.005, 0.002, 0.004, -0.003, 0.006, 0.001] * 4
        first = moving_block_bootstrap_return_ci(
            values, block_length=3, bootstrap_samples=500, seed=7
        )
        second = moving_block_bootstrap_return_ci(
            values, block_length=3, bootstrap_samples=500, seed=7
        )
        self.assertEqual(first, second)
        self.assertLessEqual(first["lower_return_pct"], first["upper_return_pct"])

    def test_trade_concentration_exposes_dependence_on_few_winners(self):
        result = trade_concentration_diagnostic([10, -2, 5, -1, 1, -3, 20])
        self.assertEqual(result["top_1_winner_share_pct"], 55.5556)
        self.assertEqual(result["top_5_winners_share_pct"], 100.0)
        self.assertEqual(result["net_pnl_excluding_top_5_winners_usd"], -6.0)

    def test_trade_concentration_handles_no_winners(self):
        result = trade_concentration_diagnostic([-1, -2, 0])
        self.assertIsNone(result["top_1_winner_share_pct"])
        self.assertEqual(result["winner_count"], 0)


if __name__ == "__main__":
    unittest.main()
