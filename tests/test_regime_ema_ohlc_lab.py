import unittest

from regime_ema_ohlc_lab import build_regime_signals, evaluate_regime_fold


def rising_bars(n=620):
    rows = []
    price = 100.0
    for i in range(n):
        price *= 1.001
        rows.append({
            "open": price * 0.9995,
            "high": price * 1.002,
            "low": price * 0.998,
            "close": price,
        })
    return rows


class RegimeEmaOhlcLabTests(unittest.TestCase):
    def test_signal_builder_returns_fixed_candidate_names(self):
        result = build_regime_signals(rising_bars())
        self.assertEqual(set(result), {"ema50_200", "ema50_200_atr90_past180"})
        self.assertEqual(len(result["ema50_200"]), 620)
        self.assertTrue(any(result["ema50_200"]))

    def test_volatility_filter_uses_only_prior_completed_bars(self):
        bars = rising_bars()
        before = build_regime_signals(bars)
        changed = [dict(row) for row in bars]
        for i in range(500, len(changed)):
            changed[i]["high"] *= 1.25
            changed[i]["low"] *= 0.80
        after = build_regime_signals(changed)
        self.assertEqual(before["ema50_200_atr90_past180"][:500],
                         after["ema50_200_atr90_past180"][:500])

    def test_fold_reports_ohlc_risk_and_matched_benchmarks(self):
        bars = rising_bars()
        result = evaluate_regime_fold(bars, 360, 620, fee=0.001, slippage=0.0005)
        self.assertIn("ema50_200", result)
        self.assertIn("ema50_200_atr90_past180", result)
        self.assertIn("buy_and_hold", result)
        self.assertIn("cash", result)
        for name in ("ema50_200", "ema50_200_atr90_past180"):
            self.assertIn("max_intrabar_ohlc_envelope_drawdown_pct", result[name])
            self.assertFalse(result[name]["execution_enabled"])
            self.assertTrue(result[name]["research_only"])
        self.assertEqual(result["protocol"]["execution"], "next_bar_open")
        self.assertEqual(result["protocol"]["warmup_bars"], 260)

    def test_invalid_fold_and_ohlc_fail_closed(self):
        bars = rising_bars()
        with self.assertRaises(ValueError):
            evaluate_regime_fold(bars, 200, 620)
        bad = [dict(row) for row in bars]
        bad[300]["high"] = bad[300]["low"] - 1
        with self.assertRaises(ValueError):
            build_regime_signals(bad)


if __name__ == "__main__":
    unittest.main()
