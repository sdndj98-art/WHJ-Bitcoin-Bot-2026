import unittest

from six_agent_signal_engine import analyze_market, analyze_universe


def bars_from_closes(closes, volume=100):
    return [{"close": c, "high": c * 1.002, "low": c * 0.998,
             "volume": volume} for c in closes]


class SixAgentSignalTests(unittest.TestCase):
    def test_trending_market_returns_six_agent_report(self):
        closes = [100 + i * 0.5 for i in range(30)]
        report = analyze_market(bars_from_closes(closes))
        self.assertEqual(set(report["agents"]), {
            "SCANNER", "MOMENTUM", "MEAN_REVERSION", "BREAKOUT", "VOLUME", "RISK"
        })
        self.assertEqual(report["signal"], "BUY")
        self.assertFalse(report["orders_submitted"])
        self.assertFalse(report["live_trading_enabled"])

    def test_risk_agent_vetoes_extreme_range(self):
        bars = bars_from_closes([100 + i * 0.5 for i in range(30)])
        for bar in bars[-20:]:
            bar["high"] = bar["close"] * 1.1
            bar["low"] = bar["close"] * 0.9
        report = analyze_market(bars)
        self.assertEqual(report["signal"], "HOLD")
        self.assertTrue(report["risk_veto"])
        self.assertEqual(report["reason"], "RISK_AGENT_VETO")

    def test_short_or_invalid_history_is_hold_in_universe(self):
        report = analyze_universe({"BTCUSD": [{"close": 1}], "XAUUSD": []})
        self.assertEqual(report["BTCUSD"]["signal"], "HOLD")
        self.assertEqual(report["XAUUSD"]["signal"], "HOLD")

    def test_non_finite_values_rejected(self):
        bars = bars_from_closes([100 + i * 0.5 for i in range(30)])
        bars[0]["close"] = float("nan")
        with self.assertRaises(ValueError):
            analyze_market(bars)

    def test_consensus_needs_three_votes(self):
        # Flat data should not fabricate a directional signal.
        report = analyze_market(bars_from_closes([100] * 30))
        self.assertEqual(report["signal"], "HOLD")
        self.assertEqual(report["reason"], "NO_CLEAR_CONSENSUS")


if __name__ == "__main__":
    unittest.main()
