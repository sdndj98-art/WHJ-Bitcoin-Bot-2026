import unittest

from whj_memecoin_screen import score_token


class MemecoinScreenTests(unittest.TestCase):
    def setUp(self):
        self.snapshot = {
            "market_cap_usd": 150000,
            "liquidity_usd": 60000,
            "volume_1h_usd": 100000,
            "volume_5m_usd": 9000,
            "buys_1h": 150,
            "sells_1h": 100,
            "unique_buyers_1h": 80,
            "top10_holder_pct": 18,
            "top1_holder_pct": 3,
            "insider_pct": 8,
            "linked_wallet_pct": 5,
            "lp_locked": True,
            "mint_authority_revoked": True,
            "freeze_authority_revoked": True,
            "sell_simulation_passed": True,
            "honeypot": False,
            "dev_sold_pct": 0,
            "tax_bps": 100,
            "social_unique_authors": 50,
            "social_acceleration": 1.5,
            "coordinated_post_pct": 5,
        }

    def test_high_quality_snapshot_is_paper_only(self):
        result = score_token(self.snapshot)
        self.assertEqual(result["verdict"], "SELECTED_PAPER_ONLY")
        self.assertGreaterEqual(result["score"], 85)
        self.assertEqual(result["execution"], "DISABLED")

    def test_honeypot_is_hard_rejected(self):
        self.snapshot["honeypot"] = True
        result = score_token(self.snapshot)
        self.assertEqual(result["verdict"], "REJECT")
        self.assertEqual(result["score"], 0)
        self.assertIn("honeypot_detected", result["hard_blocks"])

    def test_missing_critical_data_cannot_be_selected(self):
        result = score_token({"market_cap_usd": 100000, "liquidity_usd": 30000})
        self.assertEqual(result["confidence"], "LOW")
        self.assertNotEqual(result["verdict"], "SELECTED_PAPER_ONLY")


if __name__ == "__main__":
    unittest.main()
