import unittest

from paper_decision_pipeline import evaluate_paper_decision


class PaperDecisionPipelineTests(unittest.TestCase):
    def setUp(self):
        self.scanner = {
            "status": "PAPER_CANDIDATE",
            "paper_candidate_only": True,
            "live_orders_placed": False,
            "current_close": 100.0,
            "confluence_score": 8,
            "confluence_total": 8,
            "checks": {
                "ohlcv_valid": True,
                "market_data_quality_pass": True,
                "volume_spike": True,
                "close_above_prior_high": True,
                "breakout_quality_confirmed": True,
                "trend_alignment": True,
                "rsi_momentum_healthy": True,
                "adx_trend_strength": True,
                "bullish_close_confirmation": True,
                "paper_only": True,
                "live_execution_enabled": False,
            },
            "hypothetical_risk_map": {
                "research_only": True,
                "execution_enabled": False,
                "reference_price": 100.0,
                "stop_level": 98.0,
                "target_level": 104.0,
            },
        }
        self.account = {
            "mode": "PERSISTENT_PAPER_ONLY",
            "cash_usd": 1000.0,
            "equity_after_estimated_exit_costs_usd": 1000.0,
            "open_position": False,
            "risk_pause_reasons": [],
            "paused_for_drawdown": False,
            "daily_loss_paused": False,
            "paused_for_loss_streak": False,
            "paused_for_strategy_health": False,
        }

    def test_valid_candidate_gets_capped_paper_preview_only(self):
        result = evaluate_paper_decision(self.scanner, self.account)
        self.assertEqual(result["status"], "APPROVED_FOR_PAPER_SIMULATION_REVIEW_ONLY")
        self.assertLessEqual(result["notional_usd"], 100.0)
        self.assertLessEqual(result["estimated_stop_risk_usd"], 10.0)
        self.assertFalse(result["execution_enabled"])
        self.assertFalse(result["order_placed"])

    def test_scanner_watch_or_low_score_is_blocked(self):
        scanner = dict(self.scanner, status="WATCH", confluence_score=5)
        result = evaluate_paper_decision(scanner, self.account)
        self.assertEqual(result["status"], "BLOCKED")
        self.assertIn("scanner_candidate_not_approved", result["reasons"])

    def test_any_failed_scanner_check_blocks_candidate(self):
        scanner = dict(self.scanner, checks=dict(self.scanner["checks"]))
        scanner["checks"]["adx_trend_strength"] = False
        result = evaluate_paper_decision(scanner, self.account)
        self.assertEqual(result["status"], "BLOCKED")
        self.assertIn("scanner_check_failed:adx_trend_strength", result["reasons"])

    def test_guard_risk_pause_blocks_even_a_perfect_candidate(self):
        account = dict(self.account, risk_pause_reasons=["maximum_drawdown"])
        result = evaluate_paper_decision(self.scanner, account)
        self.assertEqual(result["status"], "BLOCKED")
        self.assertIn("guard_risk_pause_active", result["reasons"])

    def test_each_guard_pause_flag_must_be_explicitly_clear(self):
        account = dict(self.account, daily_loss_paused=True)
        result = evaluate_paper_decision(self.scanner, account)
        self.assertEqual(result["status"], "BLOCKED")
        self.assertIn("guard_pause_flag_not_clear:daily_loss_paused", result["reasons"])

    def test_existing_position_blocks_new_entry(self):
        account = dict(self.account, open_position=True)
        result = evaluate_paper_decision(self.scanner, account)
        self.assertEqual(result["status"], "BLOCKED")
        self.assertIn("guard_position_already_open", result["reasons"])

    def test_invalid_price_or_risk_map_fails_closed(self):
        scanner = dict(self.scanner, current_close=float("nan"))
        result = evaluate_paper_decision(scanner, self.account)
        self.assertEqual(result["status"], "BLOCKED")
        self.assertTrue(any(x.startswith("invalid_market_or_account_data:") for x in result["reasons"]))

    def test_mismatched_risk_reference_is_blocked(self):
        scanner = dict(self.scanner, hypothetical_risk_map=dict(
            self.scanner["hypothetical_risk_map"], reference_price=99.0
        ))
        result = evaluate_paper_decision(scanner, self.account)
        self.assertEqual(result["status"], "BLOCKED")

    def test_invalid_sizing_and_caps_are_rejected(self):
        for sizing in ({"allocation_fraction": 0.5}, {"risk_fraction": 0.02},
                       {"allocation_fraction": True}, {"risk_fraction": 0}):
            with self.subTest(sizing=sizing):
                result = evaluate_paper_decision(self.scanner, self.account, sizing)
                self.assertEqual(result["status"], "BLOCKED")

    def test_low_cash_caps_notional_without_exceeding_cash(self):
        account = dict(self.account, cash_usd=25.0)
        result = evaluate_paper_decision(self.scanner, account)
        self.assertEqual(result["status"], "APPROVED_FOR_PAPER_SIMULATION_REVIEW_ONLY")
        self.assertLessEqual(result["notional_usd"], 25.0)

    def test_missing_guard_snapshot_is_blocked(self):
        result = evaluate_paper_decision(self.scanner, None)
        self.assertEqual(result["status"], "BLOCKED")

    def test_no_live_execution_or_order_side_effect_is_advertised(self):
        result = evaluate_paper_decision(self.scanner, self.account)
        self.assertFalse(result["execution_enabled"])
        self.assertFalse(result["order_placed"])
        self.assertTrue(result["research_only"])


    def test_required_cvd_gate_accepts_only_verified_bullish_confirmation(self):
        evidence = {
            "status": "OK", "available": True, "direction": "BULLISH",
            "continuity_verified": True,
            "research_only": True, "execution_enabled": False,
        }
        result = evaluate_paper_decision(
            self.scanner, self.account, cvd_confirmation=evidence,
            require_cvd_confirmation=True,
        )
        self.assertEqual(result["status"], "APPROVED_FOR_PAPER_SIMULATION_REVIEW_ONLY")
        self.assertTrue(result["cvd_requirement_enabled"])
        self.assertFalse(result["execution_enabled"])
        self.assertFalse(result["order_placed"])

    def test_required_cvd_gate_fails_closed_when_missing_or_unavailable(self):
        for evidence in (None, {
            "status": "UNAVAILABLE", "available": False, "direction": "UNKNOWN",
            "research_only": True, "execution_enabled": False,
        }, {
            "status": "OK", "available": True, "direction": "BEARISH",
            "research_only": True, "execution_enabled": False,
        }, {
            "status": "OK", "available": True, "direction": "BULLISH",
            "continuity_verified": False,
            "research_only": True, "execution_enabled": False,
        }, {
            "status": "OK", "available": True, "direction": "BULLISH",
            "continuity_verified": True,
            "research_only": True, "execution_enabled": True,
        }):
            with self.subTest(evidence=evidence):
                result = evaluate_paper_decision(
                    self.scanner, self.account, cvd_confirmation=evidence,
                    require_cvd_confirmation=True,
                )
                self.assertEqual(result["status"], "BLOCKED")
                self.assertFalse(result["execution_enabled"])
                self.assertFalse(result["order_placed"])

    def test_cvd_gate_is_opt_in_and_preserves_legacy_behavior(self):
        result = evaluate_paper_decision(self.scanner, self.account)
        self.assertEqual(result["status"], "APPROVED_FOR_PAPER_SIMULATION_REVIEW_ONLY")
        self.assertFalse(result["cvd_requirement_enabled"])
        self.assertIsNone(result["cvd_confirmation"])


if __name__ == "__main__":
    unittest.main()
