import json
import os
import tempfile
import threading
import unittest
from unittest.mock import patch

from kraken_order_flow import (
    analyze_order_book,
    analyze_trade_flow,
    combine_microstructure,
    evaluate_microstructure_confluence,
    PersistentCvdLedger,
    KrakenSpotTradeFeedAdapter,
    KrakenSpotWebSocketRunner,
    StatePersistenceError,
    load_cvd_state,
    save_cvd_state_atomic,
    TradeIdGapError,
    normalize_kraken_ws_v2_trade_message,
    normalize_kraken_rest_trade_rows,
    fetch_recent_trades,
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

    def test_order_book_rejects_unsorted_levels(self):
        unsorted_bids = {
            "bids": [["98", "1"], ["99", "1"]],
            "asks": [["101", "1"], ["102", "1"]],
        }
        with self.assertRaisesRegex(ValueError, "descending"):
            analyze_order_book(unsorted_bids)
        unsorted_asks = {
            "bids": [["99", "1"], ["98", "1"]],
            "asks": [["102", "1"], ["101", "1"]],
        }
        with self.assertRaisesRegex(ValueError, "ascending"):
            analyze_order_book(unsorted_asks)

    def test_public_fetch_rejects_non_object_json_response(self):
        with patch("urllib.request.urlopen") as mocked:
            mocked.return_value.__enter__.return_value.read.return_value = b"[]"
            with self.assertRaisesRegex(ValueError, "JSON object"):
                _kraken_get("Trades", {"pair": "XBTUSD"})

    def test_public_fetch_rejects_missing_or_invalid_result_object(self):
        with patch("urllib.request.urlopen") as mocked:
            mocked.return_value.__enter__.return_value.read.return_value = b'{"error": [], "result": null}'
            with self.assertRaisesRegex(ValueError, "result must be an object"):
                _kraken_get("Trades", {"pair": "XBTUSD"})

    def test_combined_context_requires_agreement_for_alignment(self):
        trade = {"batch_bias": "BUY_PRESSURE"}
        book = {"snapshot_bias": "BID_DEPTH_DOMINANT"}
        result = combine_microstructure(trade, book)
        self.assertEqual(result["context"], "BULLISH_MICROSTRUCTURE_ALIGNMENT")
        self.assertFalse(result["execution_enabled"])
        self.assertFalse(result["live_orders_placed"])



    def test_three_layer_fusion_requires_ohlcv_flow_and_depth_alignment(self):
        result = evaluate_microstructure_confluence(
            {"status": "BULLISH_RESEARCH_CANDIDATE"},
            {"batch_bias": "BUY_PRESSURE"},
            {
                "snapshot_bias": "BID_DEPTH_DOMINANT",
                "spread_bps": 4.0,
                "bid_depth_notional": 80000.0,
                "ask_depth_notional": 60000.0,
                "largest_bid_level_share": 0.25,
                "largest_ask_level_share": 0.20,
            },
        )
        self.assertEqual(result["context"], "BULLISH_THREE_LAYER_ALIGNMENT")
        self.assertFalse(result["timestamp_alignment_verified"])
        self.assertFalse(result["execution_enabled"])
        self.assertFalse(result["live_orders_placed"])

    def test_three_layer_fusion_rejects_bad_spread_even_when_direction_agrees(self):
        result = evaluate_microstructure_confluence(
            {"status": "BEARISH_RESEARCH_CANDIDATE"},
            {"batch_bias": "SELL_PRESSURE"},
            {
                "snapshot_bias": "ASK_DEPTH_DOMINANT",
                "spread_bps": 30.0,
                "bid_depth_notional": 80000.0,
                "ask_depth_notional": 60000.0,
                "largest_bid_level_share": 0.25,
                "largest_ask_level_share": 0.20,
            },
        )
        self.assertEqual(result["context"], "LIQUIDITY_QUALITY_FAIL")
        self.assertFalse(result["execution_enabled"])

    def test_three_layer_fusion_detects_microstructure_divergence(self):
        result = evaluate_microstructure_confluence(
            {"status": "BULLISH_RESEARCH_CANDIDATE"},
            {"batch_bias": "SELL_PRESSURE"},
            {
                "snapshot_bias": "ASK_DEPTH_DOMINANT",
                "spread_bps": 4.0,
                "bid_depth_notional": 80000.0,
                "ask_depth_notional": 60000.0,
                "largest_bid_level_share": 0.25,
                "largest_ask_level_share": 0.20,
            },
        )
        self.assertEqual(result["context"], "MICROSTRUCTURE_DIVERGENCE")

    def test_three_layer_fusion_rejects_invalid_thresholds(self):
        with self.assertRaisesRegex(ValueError, "max_level_concentration"):
            evaluate_microstructure_confluence(
                {"status": "WATCH"}, {"batch_bias": "BALANCED"},
                {"snapshot_bias": "DEPTH_BALANCED", "spread_bps": 1,
                 "bid_depth_notional": 1, "ask_depth_notional": 1,
                 "largest_bid_level_share": 0.2, "largest_ask_level_share": 0.2},
                max_level_concentration=1.5,
            )



    def test_persistent_cvd_accumulates_and_deduplicates_replayed_trade_ids(self):
        ledger = PersistentCvdLedger(symbol="BTC/USD")
        first = ledger.process([
            {"symbol": "BTC/USD", "trade_id": 101, "price": "100",
             "qty": "2", "side": "buy", "timestamp": "2026-11-08T09:00:00Z"},
            {"symbol": "BTC/USD", "trade_id": 102, "price": "99",
             "qty": "1", "side": "sell", "timestamp": "2026-11-08T09:00:01Z"},
        ])
        self.assertEqual(first["cumulative_delta"], 1.0)
        self.assertEqual(first["accepted_in_batch"], 2)
        second = ledger.process([
            {"symbol": "BTC/USD", "trade_id": 102, "price": "99",
             "qty": "1", "side": "sell", "timestamp": "2026-11-08T09:00:01Z"},
            {"symbol": "BTC/USD", "trade_id": 103, "price": "101",
             "qty": "3", "side": "buy", "timestamp": "2026-11-08T09:00:02Z"},
        ])
        self.assertEqual(second["accepted_in_batch"], 1)
        self.assertEqual(second["ignored_replayed_or_stale_in_batch"], 1)
        self.assertEqual(second["cumulative_buy_volume"], 5.0)
        self.assertEqual(second["cumulative_sell_volume"], 1.0)
        self.assertEqual(second["cumulative_delta"], 4.0)
        self.assertTrue(second["is_persistent_cvd"])

    def test_persistent_cvd_restores_json_serializable_state(self):
        ledger = PersistentCvdLedger(symbol="BTC/USD")
        ledger.process([
            {"symbol": "BTC/USD", "trade_id": 10, "price": 100,
             "qty": 2, "side": "buy", "timestamp": 1000},
        ])
        restored = PersistentCvdLedger(state=ledger.to_state())
        result = restored.process([
            {"trade_id": 11, "price": 101, "qty": 1,
             "side": "sell", "timestamp": 1001},
        ])
        self.assertEqual(result["cumulative_delta"], 1.0)
        self.assertEqual(result["processed_trade_count"], 2)

    def test_persistent_cvd_rejects_out_of_order_timestamps_atomically(self):
        ledger = PersistentCvdLedger(symbol="BTC/USD")
        ledger.process([
            {"trade_id": 1, "price": 100, "qty": 1,
             "side": "buy", "timestamp": 100},
        ])
        before = ledger.to_state()
        with self.assertRaisesRegex(ValueError, "non-decreasing"):
            ledger.process([
                {"trade_id": 2, "price": 101, "qty": 1,
                 "side": "buy", "timestamp": 99},
            ])
        self.assertEqual(ledger.to_state(), before)

    def test_persistent_cvd_rejects_conflicting_duplicate_ids_and_bad_symbols(self):
        ledger = PersistentCvdLedger(symbol="BTC/USD")
        with self.assertRaisesRegex(ValueError, "conflicting payloads"):
            ledger.process([
                {"trade_id": 1, "price": 100, "qty": 1, "side": "buy", "timestamp": 1},
                {"trade_id": 1, "price": 101, "qty": 1, "side": "buy", "timestamp": 1},
            ])
        with self.assertRaisesRegex(ValueError, "symbol"):
            ledger.process([
                {"symbol": "ETH/USD", "trade_id": 2, "price": 100,
                 "qty": 1, "side": "buy", "timestamp": 2},
            ])
        self.assertEqual(ledger.processed_trade_count, 0)

    def test_persistent_cvd_validates_state_version_and_timezone(self):
        with self.assertRaisesRegex(ValueError, "version"):
            PersistentCvdLedger(state={"version": 99})
        ledger = PersistentCvdLedger()
        with self.assertRaisesRegex(ValueError, "timezone"):
            ledger.process([
                {"trade_id": 1, "price": 100, "qty": 1,
                 "side": "buy", "timestamp": "2026-11-08T09:00:00"},
            ])



    def test_ws_v2_trade_message_normalizes_snapshot_and_update(self):
        payload = {
            "channel": "trade", "type": "update",
            "data": [{
                "symbol": "BTC/USD", "side": "buy", "qty": 0.25,
                "price": 65000, "ord_type": "market", "trade_id": 5001,
                "timestamp": "2026-11-08T10:00:00Z",
            }],
        }
        events = normalize_kraken_ws_v2_trade_message(payload, "BTC/USD")
        self.assertEqual(events[0]["trade_id"], 5001)
        self.assertEqual(events[0]["side"], "buy")
        self.assertEqual(normalize_kraken_ws_v2_trade_message(
            {"channel": "heartbeat"}, "BTC/USD"
        ), [])

    def test_ws_v2_trade_parser_rejects_symbol_mismatch_and_bad_envelope(self):
        payload = {
            "channel": "trade", "type": "snapshot",
            "data": [{"symbol": "ETH/USD", "side": "buy", "qty": 1,
                      "price": 1, "trade_id": 1,
                      "timestamp": "2026-11-08T10:00:00Z"}],
        }
        with self.assertRaisesRegex(ValueError, "symbol"):
            normalize_kraken_ws_v2_trade_message(payload, "BTC/USD")
        with self.assertRaisesRegex(ValueError, "valid JSON"):
            normalize_kraken_ws_v2_trade_message("{bad json")

    def test_rest_trade_normalizer_requires_exchange_trade_id(self):
        with self.assertRaisesRegex(ValueError, "lacks trade_id"):
            normalize_kraken_rest_trade_rows(
                [["100", "1", "100", "b", "m", ""]], "BTC/USD"
            )
        events = normalize_kraken_rest_trade_rows(
            [["100", "1", "100", "s", "m", "", "44"]], "BTC/USD"
        )
        self.assertEqual(events[0]["trade_id"], "44")
        self.assertEqual(events[0]["side"], "sell")

    def test_cvd_ledger_detects_trade_id_gap_atomically(self):
        ledger = PersistentCvdLedger(symbol="BTC/USD")
        ledger.process([
            {"trade_id": 10, "price": 100, "qty": 1,
             "side": "buy", "timestamp": 100},
        ])
        before = ledger.to_state()
        with self.assertRaises(TradeIdGapError):
            ledger.process([
                {"trade_id": 12, "price": 101, "qty": 1,
                 "side": "buy", "timestamp": 102},
            ])
        self.assertEqual(ledger.to_state(), before)

    @patch("kraken_order_flow.fetch_recent_trades")
    def test_ws_adapter_backfills_trade_id_gap_before_applying_update(self, fetch):
        ledger = PersistentCvdLedger(symbol="BTC/USD")
        ledger.process([
            {"trade_id": 10, "price": 100, "qty": 1,
             "side": "buy", "timestamp": 100},
        ])
        fetch.return_value = {
            "trades": [
                ["101", "1", 101.0, "b", "m", "", "11"],
                ["102", "2", 102.0, "s", "m", "", "12"],
                ["103", "1", 103.0, "b", "m", "", "13"],
            ],
            "last": "103000000000",
        }
        adapter = KrakenSpotTradeFeedAdapter(ledger, "BTC/USD")
        result = adapter.handle_message({
            "channel": "trade", "type": "update",
            "data": [{
                "symbol": "BTC/USD", "side": "buy", "qty": 1,
                "price": 104, "trade_id": 13,
                "timestamp": "1970-01-01T00:01:44Z",
            }],
        })
        self.assertEqual(result["status"], "OK")
        self.assertTrue(result["backfill"]["recovered"])
        self.assertEqual(result["backfill"]["accepted_trades"], 3)
        self.assertEqual(ledger.last_trade_id, 13)
        self.assertEqual(ledger.processed_trade_count, 4)
        fetch.assert_called_once_with(
            "BTC/USD", timeout=10, since="100000000000"
        )

    def test_ws_adapter_ignores_non_trade_messages(self):
        adapter = KrakenSpotTradeFeedAdapter(
            PersistentCvdLedger(symbol="BTC/USD"), "BTC/USD"
        )
        result = adapter.handle_message({"channel": "heartbeat"})
        self.assertEqual(result["status"], "IGNORED_NON_TRADE_MESSAGE")
        self.assertFalse(result["execution_enabled"])



    def test_cvd_preserves_exact_nanosecond_timestamp_for_recovery(self):
        ledger = PersistentCvdLedger(symbol="BTC/USD")
        ledger.process([{
            "trade_id": 1, "price": 100, "qty": 1, "side": "buy",
            "timestamp": "2026-11-08T10:00:00.123456789Z",
        }])
        self.assertEqual(
            ledger.to_state()["last_trade_timestamp_ns"],
            1794132000123456789,
        )
        restored = PersistentCvdLedger(state=ledger.to_state())
        self.assertEqual(
            restored.to_state()["last_trade_timestamp_ns"],
            1794132000123456789,
        )

    @patch("kraken_order_flow._kraken_get")
    def test_fetch_recent_trades_passes_since_cursor(self, get):
        get.return_value = {"XXBTZUSD": [], "last": "123456789"}
        result = fetch_recent_trades("XBTUSD", since="123456789")
        self.assertEqual(result["last"], "123456789")
        get.assert_called_once_with(
            "Trades", {"pair": "XBTUSD", "since": "123456789"}, timeout=10
        )

    def test_fetch_recent_trades_rejects_invalid_since_cursor(self):
        with self.assertRaisesRegex(ValueError, "since"):
            fetch_recent_trades("XBTUSD", since="not-a-cursor")



    def test_cvd_state_atomic_save_load_and_corruption_is_not_reset(self):
        with tempfile.TemporaryDirectory() as directory:
            path = os.path.join(directory, "btc-usd-cvd.json")
            state = {"version": 1, "symbol": "BTC/USD", "last_trade_id": 77}
            self.assertIsNone(load_cvd_state(path))
            save_cvd_state_atomic(path, state)
            self.assertEqual(load_cvd_state(path), state)
            with self.assertRaises(ValueError):
                save_cvd_state_atomic(path, {"bad_number": float("nan")})
            self.assertEqual(load_cvd_state(path), state)
            with open(path, "w", encoding="utf-8") as handle:
                handle.write("{corrupt")
            with self.assertRaises(json.JSONDecodeError):
                load_cvd_state(path)

    def test_ws_runner_subscribes_persists_and_stops_cleanly(self):
        class FakeSocket:
            def __init__(self):
                self.sent = []
                self.closed = False
                self.messages = [
                    json.dumps({"method": "subscribe", "success": True}),
                    json.dumps({
                        "channel": "trade", "type": "update",
                        "data": [{
                            "symbol": "BTC/USD", "side": "buy", "qty": 0.5,
                            "price": 65000, "trade_id": 1,
                            "timestamp": "2026-11-08T10:00:00.123456789Z",
                        }],
                    }),
                ]

            def settimeout(self, timeout):
                self.timeout = timeout

            def send(self, payload):
                self.sent.append(json.loads(payload))

            def recv(self):
                return self.messages.pop(0)

            def close(self):
                self.closed = True

        class FakeStopEvent:
            def __init__(self):
                self.stopped = False

            def is_set(self):
                return self.stopped

            def wait(self, delay):
                return self.stopped

        ledger = PersistentCvdLedger(symbol="BTC/USD")
        adapter = KrakenSpotTradeFeedAdapter(ledger, "BTC/USD")
        runner = KrakenSpotWebSocketRunner(adapter)
        ws = FakeSocket()
        stop = FakeStopEvent()
        saved = []

        def persist(state):
            saved.append(state)
            stop.stopped = True

        result = runner.run(
            stop, persist,
            websocket_factory=lambda url, timeout: ws,
        )
        self.assertEqual(result["status"], "STOPPED")
        self.assertEqual(result["accepted_websocket_trades"], 1)
        self.assertEqual(result["last_trade_id"], 1)
        self.assertTrue(ws.closed)
        self.assertEqual(ws.sent[0]["params"]["channel"], "trade")
        self.assertEqual(ws.sent[0]["params"]["symbol"], ["BTC/USD"])
        self.assertEqual(len(saved), 1)
        self.assertEqual(
            saved[0]["last_trade_timestamp_ns"], 1794132000123456789
        )

    def test_ws_runner_stops_if_durable_state_callback_fails(self):
        class FakeSocket:
            def __init__(self):
                self.closed = False
                self.messages = [json.dumps({
                    "channel": "trade", "type": "update",
                    "data": [{
                        "symbol": "BTC/USD", "side": "buy", "qty": 1,
                        "price": 1, "trade_id": 1,
                        "timestamp": "2026-11-08T10:00:00Z",
                    }],
                })]

            def settimeout(self, timeout):
                pass

            def send(self, payload):
                pass

            def recv(self):
                return self.messages.pop(0)

            def close(self):
                self.closed = True

        ws = FakeSocket()
        adapter = KrakenSpotTradeFeedAdapter(
            PersistentCvdLedger(symbol="BTC/USD"), "BTC/USD"
        )
        runner = KrakenSpotWebSocketRunner(adapter)
        with self.assertRaises(StatePersistenceError):
            runner.run(
                threading.Event(),
                lambda state: (_ for _ in ()).throw(OSError("disk full")),
                websocket_factory=lambda url, timeout: ws,
            )
        self.assertTrue(ws.closed)

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
