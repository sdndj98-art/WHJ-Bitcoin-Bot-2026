import argparse
import json
import tempfile
import threading
import unittest
from pathlib import Path
from unittest.mock import patch

from trade_journal_checkpoint import validate_continuity_checkpoint

import kraken_cvd_collector


class KrakenCvdCollectorCliTests(unittest.TestCase):
    def test_default_state_path_is_per_symbol_and_safe(self):
        self.assertEqual(
            kraken_cvd_collector.default_state_path("BTC/USD"),
            "state/kraken_cvd_btc_usd.json",
        )
        self.assertEqual(
            kraken_cvd_collector.default_state_path("ETH/USDT"),
            "state/kraken_cvd_eth_usdt.json",
        )
        with self.assertRaisesRegex(ValueError, "non-empty"):
            kraken_cvd_collector.default_state_path(" ")

    def test_parser_exposes_safe_defaults(self):
        args = kraken_cvd_collector.build_parser().parse_args([])
        self.assertEqual(args.pair, "BTC/USD")
        self.assertIsNone(args.state_file)
        self.assertEqual(args.max_reconnect_attempts, 0)
        self.assertIsNone(args.checkpoint_file)

    @patch("kraken_cvd_collector.KrakenSpotWebSocketRunner")
    @patch("kraken_cvd_collector.save_cvd_state_atomic")
    @patch("kraken_cvd_collector.load_cvd_state")
    def test_fresh_collector_writes_checkpoint_after_initial_snapshot(
        self, load_state, save_state, runner_class
    ):
        load_state.return_value = None
        runner = runner_class.return_value
        runner.run.return_value = {"status": "STOPPED"}
        with tempfile.TemporaryDirectory() as directory:
            journal_path = str(Path(directory) / "trades.jsonl")
            state_path = str(Path(directory) / "state.json")
            args = argparse.Namespace(
                pair="BTC/USD",
                state_file=state_path,
                trade_log=journal_path,
                checkpoint_file=None,
                max_trade_log_mb=5,
                timeout=15.0,
                initial_backoff=1.0,
                max_backoff=10.0,
                max_reconnect_attempts=3,
            )
            kraken_cvd_collector.run_collector(
                args, threading.Event(), websocket_factory="fake"
            )
            adapter = runner_class.call_args.args[0]
            adapter.handle_message({
                "channel": "trade",
                "type": "snapshot",
                "data": [
                    {"symbol": "BTC/USD", "trade_id": 100, "price": 100,
                     "qty": 1, "side": "buy", "timestamp": "2026-11-08T10:00:01Z"},
                    {"symbol": "BTC/USD", "trade_id": 101, "price": 101,
                     "qty": 1, "side": "sell", "timestamp": "2026-11-08T10:00:02Z"},
                ],
            })
            checkpoint_path = Path(journal_path + ".checkpoint.json")
            save_state.side_effect = lambda *_: self.assertTrue(
                checkpoint_path.exists(),
                "continuity checkpoint must be durable before CVD state advances",
            )
            persist = runner.run.call_args.kwargs["persist_state"]
            persist(adapter.ledger.to_state())
            checkpoint = json.loads(checkpoint_path.read_text(encoding="utf-8"))
            metadata = validate_continuity_checkpoint(
                checkpoint, journal_path, "BTC/USD", 101
            )
            self.assertEqual(metadata["first_trade_id"], 100)
            self.assertEqual(metadata["last_trade_id"], 101)
            self.assertEqual(adapter.continuity_start_trade_id, 100)
            save_state.assert_called_once()

    @patch("kraken_cvd_collector.KrakenSpotWebSocketRunner")
    @patch("kraken_cvd_collector.load_cvd_state")
    def test_resume_refuses_journal_without_matching_checkpoint(
        self, load_state, runner_class
    ):
        load_state.return_value = {
            "version": 1, "symbol": "BTC/USD", "last_trade_id": 101,
            "last_trade_timestamp": 1794132002.0,
            "last_trade_timestamp_ns": 1794132002000000000,
            "cumulative_buy_volume": 1.0,
            "cumulative_sell_volume": 1.0,
            "processed_trade_count": 2,
        }
        with tempfile.TemporaryDirectory() as directory:
            journal_path = Path(directory) / "trades.jsonl"
            journal_path.write_text(
                json.dumps({"trade_id": 100, "timestamp": "2026-11-08T10:00:01Z",
                            "price": 100, "qty": 1, "side": "buy", "symbol": "BTC/USD"}) + "\n"
                + json.dumps({"trade_id": 101, "timestamp": "2026-11-08T10:00:02Z",
                              "price": 101, "qty": 1, "side": "sell", "symbol": "BTC/USD"}) + "\n",
                encoding="utf-8",
            )
            args = argparse.Namespace(
                pair="BTC/USD",
                state_file=str(Path(directory) / "state.json"),
                trade_log=str(journal_path),
                checkpoint_file=None,
                max_trade_log_mb=5,
                timeout=15.0,
                initial_backoff=1.0,
                max_backoff=10.0,
                max_reconnect_attempts=3,
            )
            with self.assertRaisesRegex(ValueError, "no collector checkpoint"):
                kraken_cvd_collector.run_collector(
                    args, threading.Event(), websocket_factory="fake"
                )
            runner_class.assert_not_called()

    @patch("kraken_cvd_collector.KrakenSpotWebSocketRunner")
    @patch("kraken_cvd_collector.save_cvd_state_atomic")
    @patch("kraken_cvd_collector.load_cvd_state")
    def test_run_collector_restores_and_wires_atomic_persistence(
        self, load_state, save_state, runner_class
    ):
        saved = {"version": 1, "symbol": "BTC/USD", "last_trade_id": 20}
        load_state.return_value = saved
        runner = runner_class.return_value
        runner.run.return_value = {"status": "STOPPED"}
        args = argparse.Namespace(
            pair="BTC/USD",
            state_file="tmp/btc.json",
            timeout=15.0,
            initial_backoff=1.0,
            max_backoff=10.0,
            max_reconnect_attempts=3,
        )
        stop = threading.Event()
        result = kraken_cvd_collector.run_collector(args, stop, websocket_factory="fake")
        self.assertEqual(result, {"status": "STOPPED"})
        load_state.assert_called_once_with("tmp/btc.json")
        runner_class.assert_called_once()
        call_args = runner.run.call_args
        self.assertIs(call_args.args[0], stop)
        self.assertEqual(call_args.kwargs["websocket_factory"], "fake")
        persist = call_args.kwargs["persist_state"]
        persist({"version": 1, "symbol": "BTC/USD", "last_trade_id": 21})
        save_state.assert_called_once_with(
            "tmp/btc.json",
            {"version": 1, "symbol": "BTC/USD", "last_trade_id": 21},
        )


if __name__ == "__main__":
    unittest.main()
