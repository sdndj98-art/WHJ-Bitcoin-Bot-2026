import unittest

from cvd_entry_filter_lab import build_cvd_gated_signals, run_cvd_entry_filter_lab


def flow(available=True, bullish=True, absorption=False):
    return {
        "available": available,
        "bullish_flow_confirmation": bullish,
        "bullish_absorption_divergence": absorption,
    }


class CvdEntryFilterLabTests(unittest.TestCase):
    def test_unavailable_cvd_fails_closed_for_new_entries(self):
        signals = [False, True, True, True]
        bars = [flow(False, True) for _ in signals]
        self.assertEqual(build_cvd_gated_signals(signals, bars), [False] * 4)

    def test_unavailable_cvd_does_not_force_exit_from_open_position(self):
        signals = [True, True, True, False, True]
        bars = [flow(True, True), flow(False, False), flow(False, False),
                flow(False, False), flow(False, True)]
        self.assertEqual(
            build_cvd_gated_signals(signals, bars),
            [True, True, True, False, False],
        )

    def test_flow_mode_and_absorption_mode_are_distinct(self):
        signals = [True, True]
        bars = [flow(True, False, True), flow(True, True, False)]
        self.assertEqual(
            build_cvd_gated_signals(signals, bars, "flow_confirmation"),
            [False, True],
        )
        self.assertEqual(
            build_cvd_gated_signals(signals, bars, "flow_or_absorption"),
            [True, True],
        )

    def test_all_bullish_cvd_matches_baseline_signals(self):
        signals = [False, True, True, False, True]
        bars = [flow(True, True) for _ in signals]
        self.assertEqual(build_cvd_gated_signals(signals, bars), signals)

    def test_rejects_length_mismatch_and_unknown_mode(self):
        with self.assertRaises(ValueError):
            build_cvd_gated_signals([True], [])
        with self.assertRaises(ValueError):
            build_cvd_gated_signals([True], [flow()], "unknown")

    def test_lab_reports_costs_benchmark_and_research_only(self):
        prices = [100.0]
        for index in range(1, 700):
            drift = 0.0004 if (index // 90) % 2 == 0 else -0.00015
            pulse = 0.001 * ((index % 13) - 6) / 6
            prices.append(prices[-1] * (1 + drift + pulse))
        bars = [flow(True, True) for _ in prices]
        report = run_cvd_entry_filter_lab(prices, bars)
        self.assertEqual(report["mode"], "CVD_ENTRY_FILTER_CAUSAL_RESEARCH_ONLY")
        self.assertFalse(report["execution_enabled"])
        self.assertIn("benchmark_25pct_buy_and_hold", report)
        self.assertEqual(
            report["strategies"]["ema50_200_baseline"]["out_of_sample"],
            report["strategies"]["cvd_flow_entry_filter"]["out_of_sample"],
        )
        self.assertEqual(
            len(report["strategies"]["cvd_flow_entry_filter"]["walk_forward_windows"]),
            3,
        )


if __name__ == "__main__":
    unittest.main()
