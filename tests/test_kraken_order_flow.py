import unittest

from kraken_order_flow import (
    analyze_order_book,
    analyze_trade_flow,
    combine_microstructure,
    _kraken_get,
)


class KrakenOrderFlowTests(unittest.TestCase):
    def test_trade_flow_calculates_signed_batch_delta_and_vwap(self):
        trades = [
            ["100", "2", "1000.0", "b", "m", ""],
            ["102", "1", "1001.0", "s", "m", ""],
            ["101", "3", "1002.0", "b", "l", ""],
        ]
        result = analyze_trade_flow(trades)
        self.assertEqual(result["buy_volume"], 5.0)
        self.assertEqual(result["sell_volume"], 1.0)
        self.assertEqual(result["net_delta"], 4.0)
        self.assertEqual(result["batch_bias"], "BUY_PRESSURE")
        self.assertAlmostEqual(result["trade_vwap"], (200 + 102 + 303) / 6)
        self.assertFalse(result["is_persistent_cvd"])

    def test_trade_flow_detects_sell_pressure(self):
        trades = [
            ["100", "1", "1000.0", "b", "m", ""],
            ["99", "4", "1001.0", "s", "m", ""],
        ]
        result = analyze_trade_flow(trades)
        self.assertEqual(result["batch_bias"], "SELL_PRESSURE")
        self.assertEqual(result["net_delta_pct"], -60.0)

    def test_trade_flow_rejects_bad_side_and_duplicate_trade_id(self):
        with self.assertRaisesRegex(ValueError, "side"):
            analyze_trade_flow([["100", "1", "1000", "x", "m", ""]])
        rows = [
            ["100", "1", "1000", "b", "m", "", "id-1"],
            ["101", "1", "1001", "s", "m", "", "id-1"],
        ]
        with self.assertRaisesRegex(ValueError, "Duplicate"):
            analyze_trade_flow(rows)

    def test_trade_flow_rejects_non_finite_fields(self):
        with self.assertRaisesRegex(ValueError, "finite"):
            analyze_trade_flow([["100", "nan", "1000", "b", "m", ""]])

    def test_order_book_calculates_spread_and_depth_imbalance(self):
        book = {
            "bids": [["99", "5"], ["98", "3"]],
            "asks": [["101", "2"], ["102", "1"]],
        }
        result = analyze_order_book(book, levels=2)
        self.assertEqual(result["best_bid"], 99.0)
        self.assertEqual(result["best_ask"], 101.0)
        self.assertGreater(result["spread_bps"], 0)
        self.assertGreater(result["depth_imbalance"], 0)
        self.assertEqual(result["snapshot_bias"], "BID_DEPTH_DOMINANT")

    def test_order_book_rejects_crossed_book_and_bad_depth(self):
        crossed = {"bids": [["101", "1"]], "asks": [["100", "1"]]}
        with self.assertRaisesRegex(ValueError, "crossed"):
            analyze_order_book(crossed)
        with self.assertRaisesRegex(ValueError, "levels"):
            analyze_order_book({"bids": [["99", "1"]], "asks": [["101", "1"]]}, levels=0)

    def test_combined_context_requires_agreement_for_alignment(self):
        trade = {"batch_bias": "BUY_PRESSURE"}
        book = {"snapshot_bias": "BID_DEPTH_DOMINANT"}
        result = combine_microstructure(trade, book)
        self.assertEqual(result["context"], "BULLISH_MICROSTRUCTURE_ALIGNMENT")
        self.assertFalse(result["execution_enabled"])
        self.assertFalse(result["live_orders_placed"])

    def test_public_fetch_rejects_non_finite_timeout_before_network(self):
        with self.assertRaisesRegex(ValueError, "timeout"):
            _kraken_get("Trades", {}, timeout=float("nan"))

    def test_combined_context_rejects_unknown_labels(self):
        with self.assertRaisesRegex(ValueError, "unknown batch bias"):
            combine_microstructure(
                {"batch_bias": "UNKNOWN"},
                {"snapshot_bias": "DEPTH_BALANCED"},
            )

    def test_empty_trade_batch_is_rejected(self):
        with self.assertRaisesRegex(ValueError, "non-empty"):
            analyze_trade_flow([])


if __name__ == "__main__":
    unittest.main()
