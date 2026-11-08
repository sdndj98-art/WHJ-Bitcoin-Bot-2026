import argparse
import threading
import unittest
from unittest.mock import patch

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
