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



    @staticmethod
    def fixed_candidate(
        return_1x=8.0, return_2x=6.0, return_3x=4.0,
        drawdown=5.0, profit_factor=1.4, sharpe=1.0, trades=60,
        fold_returns=(4.0, 5.0, 2.0, 1.0), regime_active=50,
        regime_contribution=1.0,
    ):
        return {
            "aggregate_oos_cost_scenarios": {
                "1x": {"strategy": {
                    "net_return": return_1x / 100.0,
                    "max_open_to_open_drawdown": -drawdown / 100.0,
                    "periodic_profit_factor": profit_factor,
                    "period_sharpe": sharpe,
                    "closed_trades": trades,
                }},
                "2x": {"strategy": {"net_return": return_2x / 100.0}},
                "3x": {"strategy": {"net_return": return_3x / 100.0}},
            },
            "folds": [
                {"strategy": {"net_return": value / 100.0}}
                for value in fold_returns
            ],
            "regime_attribution": {
                name: {
                    "active_signal_bars": regime_active,
                    "net_log_contribution_pct": regime_contribution,
                }
                for name in ("bullish", "bearish", "sideways_transition")
            },
        }


    def test_fixed_candidate_walk_forward_ranks_all_metrics_and_screening_gate(self):
        from strategy_ranking import rank_fixed_candidate_walk_forward

        result = rank_fixed_candidate_walk_forward({
            "steady": self.fixed_candidate(),
            "weak": self.fixed_candidate(
                return_1x=-5, return_2x=-10, return_3x=-15,
                drawdown=25, profit_factor=0.8, sharpe=-1, trades=15,
                fold_returns=(-3, -2, -1, -4), regime_active=10,
                regime_contribution=-1,
            ),
        })
        self.assertEqual(
            [item["candidate"] for item in result["ranked_candidates"]],
            ["steady", "weak"],
        )
        self.assertEqual(result["passed_count"], 1)
        self.assertTrue(result["ranked_candidates"][0]["eligible_for_next_stage"])
        self.assertFalse(result["ranked_candidates"][1]["eligible_for_next_stage"])
        self.assertEqual(
            result["ranked_candidates"][1]["screening_status"],
            "INSUFFICIENT_TRADES",
        )
        self.assertFalse(result["execution_enabled"])
        self.assertFalse(result["live_trading_approved"])

    def test_fixed_candidate_screen_rejects_negative_cost_stress(self):
        from strategy_ranking import rank_fixed_candidate_walk_forward

        result = rank_fixed_candidate_walk_forward({
            "cost_fragile": self.fixed_candidate(return_1x=5, return_2x=-1, return_3x=-4)
        })
        candidate = result["ranked_candidates"][0]
        self.assertFalse(candidate["eligible_for_next_stage"])
        self.assertEqual(candidate["screening_status"], "NO_PASS")
        self.assertLess(candidate["metrics"]["net_return_3x_pct"], 0)

    def test_fixed_candidate_screen_requires_regime_coverage(self):
        from strategy_ranking import rank_fixed_candidate_walk_forward

        result = rank_fixed_candidate_walk_forward({
            "thin_regimes": self.fixed_candidate(regime_active=10)
        })
        self.assertEqual(
            result["ranked_candidates"][0]["screening_status"],
            "INSUFFICIENT_REGIME_COVERAGE",
        )
        self.assertEqual(
            result["ranked_candidates"][0]["metrics"]["regime_coverage_count"], 0
        )

    def test_fixed_candidate_screen_excludes_incomplete_metrics_and_ties_are_deterministic(self):
        from strategy_ranking import rank_fixed_candidate_walk_forward

        result = rank_fixed_candidate_walk_forward({
            "zeta": self.fixed_candidate(),
            "alpha": self.fixed_candidate(),
            "missing": {"folds": []},
        })
        self.assertEqual(
            [item["candidate"] for item in result["ranked_candidates"]],
            ["alpha", "zeta"],
        )
        self.assertEqual(
            result["excluded_candidates"][0]["status"],
            "INVALID_OR_INCOMPLETE_METRICS",
        )

    def test_fixed_candidate_screen_serializes_infinite_profit_factor_safely(self):
        from strategy_ranking import rank_fixed_candidate_walk_forward

        result = rank_fixed_candidate_walk_forward({
            "no_losses": self.fixed_candidate(profit_factor="infinite")
        })
        self.assertEqual(
            result["ranked_candidates"][0]["metrics"]["periodic_profit_factor"],
            "infinite",
        )

if __name__ == "__main__":
    unittest.main()
