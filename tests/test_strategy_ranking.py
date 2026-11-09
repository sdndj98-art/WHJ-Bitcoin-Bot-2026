import unittest

from strategy_ranking import rank_strategy_results


def sample(return_pct=8.0, drawdown=5.0, window_returns=(4.0, 2.0, -1.0), trades=30):
    return {
        "out_of_sample": {
            "return_pct": return_pct,
            "max_drawdown_pct": drawdown,
            "closed_trades": trades,
        },
        "walk_forward_windows": [
            {"metrics": {"return_pct": value}} for value in window_returns
        ],
    }


class StrategyRankingTests(unittest.TestCase):
    def test_ranks_by_balanced_oos_risk_and_robustness_score(self):
        result = rank_strategy_results({
            "steady": sample(8, 4, (3, 2, 1), 30),
            "volatile": sample(20, 18, (15, -12, -8), 30),
            "buy_and_hold": sample(50, 30, (50, 40, 30), 100),
        })
        ranked = result["ranked_strategies"]
        self.assertEqual([item["strategy"] for item in ranked], ["steady", "volatile"])
        self.assertEqual(ranked[0]["rank"], 1)
        self.assertFalse(ranked[0]["live_trading_approved"])
        self.assertFalse(result["execution_enabled"])
        self.assertTrue(result["research_only"])

    def test_small_trade_sample_is_excluded(self):
        result = rank_strategy_results({"tiny": sample(trades=9)})
        self.assertEqual(result["ranked_strategies"], [])
        self.assertEqual(result["excluded_strategies"][0]["status"], "INSUFFICIENT_TRADES")

    def test_missing_walk_forward_data_is_not_given_a_score(self):
        result = rank_strategy_results({"missing": {"out_of_sample": sample()["out_of_sample"]}})
        self.assertEqual(result["ranked_strategies"], [])
        self.assertEqual(result["excluded_strategies"][0]["status"], "MISSING_WALK_FORWARD_DATA")

    def test_drawdown_penalty_can_reverse_a_return_only_order(self):
        result = rank_strategy_results({
            "higher_return": sample(15, 25, (15, 8, 2), 30),
            "lower_risk": sample(8, 3, (5, 4, 3), 30),
        })
        self.assertEqual(result["ranked_strategies"][0]["strategy"], "lower_risk")

    def test_order_is_deterministic_for_ties(self):
        result = rank_strategy_results({
            "zeta": sample(5, 5, (2, 2, 2), 30),
            "alpha": sample(5, 5, (2, 2, 2), 30),
        })
        self.assertEqual([item["strategy"] for item in result["ranked_strategies"]], ["alpha", "zeta"])

    def test_rejects_invalid_configuration_and_metrics_are_excluded(self):
        with self.assertRaises(ValueError):
            rank_strategy_results({}, min_closed_trades=0)
        result = rank_strategy_results({"bad": sample(float("nan"))})
        self.assertEqual(result["ranked_strategies"], [])
        self.assertEqual(result["excluded_strategies"][0]["status"], "INVALID_OR_INCOMPLETE_METRICS")


if __name__ == "__main__":
    unittest.main()
