import unittest

from polymarket_six_agent_paper import (
    edge, impact, paper_entry, pulse, run_six_agents, size_position, exit_pnl,
)


def book():
    return {
        "UP": {
            "bids": [{"price": 0.45, "size": 100}, {"price": 0.44, "size": 20}],
            "asks": [{"price": 0.46, "size": 10}, {"price": 0.47, "size": 15}],
        },
        "DOWN": {
            "bids": [{"price": 0.52, "size": 10}],
            "asks": [{"price": 0.54, "size": 100}],
        },
    }


def history():
    return [
        {"imbalance": -1 + i * 2 / 39, "exit_bid_change": (-1 + i * 2 / 39) * 0.05}
        for i in range(40)
    ]


class SixAgentPaperTests(unittest.TestCase):
    def test_pulse_selects_stronger_book_imbalance(self):
        result = pulse(book())
        self.assertEqual(result["stronger_demand_side"], "UP")
        self.assertGreater(result["imbalance"], 0)
        self.assertEqual(result["agent"], "PULSE")

    def test_impact_fails_closed_without_enough_observations(self):
        result = impact(0.5, history()[:5], 0.45)
        self.assertEqual(result["status"], "INSUFFICIENT_HISTORY")
        self.assertIsNone(result["expected_exit_bid"])

    def test_impact_calibrates_only_from_historical_pairs(self):
        result = impact(0.8, history(), 0.45)
        self.assertEqual(result["status"], "CALIBRATED_OLS")
        self.assertAlmostEqual(result["beta"], 0.05, places=6)
        self.assertGreater(result["expected_exit_bid"], 0.45)
        self.assertFalse(result["model_is_validated_profitability"])

    def test_edge_requires_costs_and_buffer(self):
        result = edge(0.46, 0.49, 0.02, 0.02)
        self.assertFalse(result["approved"])
        self.assertEqual(result["status"], "SKIP_NO_EDGE")
        result = edge(0.46, 0.50, 0.01, 0.02)
        self.assertTrue(result["approved"])

    def test_sizer_uses_smallest_risk_depth_collateral_or_cap(self):
        result = size_position(5, 0.05, 0.5, 10, 100, 20)
        self.assertEqual(result["quantity"], 10)
        self.assertEqual(result["status"], "SIZED")

    def test_paper_entry_respects_limit_and_cancels_remainder(self):
        result = paper_entry(
            [{"price": 0.45, "size": 3}, {"price": 0.46, "size": 4},
             {"price": 0.48, "size": 10}],
            10, 0.46,
        )
        self.assertEqual(result["filled_quantity"], 7)
        self.assertEqual(result["unfilled_cancelled"], 3)
        self.assertEqual(result["status"], "PARTIAL_CANCEL_REMAINDER")
        self.assertFalse(result["orders_submitted"])

    def test_exit_pnl_includes_costs(self):
        result = exit_pnl(10, 0.4, 0.5, 0.3)
        self.assertAlmostEqual(result["realized_pnl"], 0.7)
        self.assertEqual(result["mode"], "PAPER_ONLY")

    def test_full_pipeline_returns_paper_candidate_only(self):
        result = run_six_agents(
            book(),
            {"UP": history(), "DOWN": history()},
            {"risk_budget": 5, "stressed_adverse_move": 0.05,
             "collateral": 100, "q_cap": 20},
            round_trip_cost=0.01,
            edge_buffer=0.01,
        )
        self.assertEqual(result["decision"], "PAPER_CANDIDATE")
        self.assertEqual(result["selected_side"], "UP")
        self.assertFalse(result["live_orders_enabled"])
        self.assertFalse(result["orders_submitted"])

    def test_invalid_binary_prices_are_rejected(self):
        bad = book()
        bad["UP"]["asks"][0]["price"] = 1.01
        with self.assertRaisesRegex(ValueError, "must be <= 1"):
            pulse(bad)

    def test_empty_book_is_skipped_and_other_side_can_be_used(self):
        bad = book()
        bad["UP"]["bids"] = []
        result = pulse(bad)
        self.assertEqual(result["stronger_demand_side"], "DOWN")
        self.assertIn("UP", result["skipped_empty_books"])

    def test_all_empty_books_force_hold(self):
        bad = {
            "UP": {"bids": [], "asks": []},
            "DOWN": {"bids": [], "asks": []},
        }
        result = run_six_agents(
            bad, {}, {"risk_budget": 5, "stressed_adverse_move": 0.05,
                     "collateral": 100, "q_cap": 20}, 0.01,
        )
        self.assertEqual(result["decision"], "HOLD")
        self.assertFalse(result["orders_submitted"])


if __name__ == "__main__":
    unittest.main()
