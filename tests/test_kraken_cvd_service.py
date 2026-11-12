import argparse
import tempfile
import unittest
from pathlib import Path

import run_kraken_cvd_service as service


class KrakenCvdServiceTests(unittest.TestCase):
    def test_lock_prevents_second_process_and_releases_on_close(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "state" / "collector.lock"
            first = service.acquire_single_instance_lock(path)
            try:
                with self.assertRaisesRegex(RuntimeError, "already running"):
                    service.acquire_single_instance_lock(path)
            finally:
                first.close()
            second = service.acquire_single_instance_lock(path)
            second.close()

    def test_command_is_argument_list_and_read_only_collector(self):
        args = argparse.Namespace(
            pair="BTC/USD",
            state_file="state/cvd.json",
            trade_log="state/trades.jsonl",
            checkpoint_file="state/trades.checkpoint.json",
            max_trade_log_mb=250,
            timeout=20.0,
            initial_backoff=1.0,
            max_backoff=30.0,
            max_reconnect_attempts=0,
        )
        command = service.build_collector_command(args)
        self.assertEqual(command[1], str(Path(service.__file__).with_name("kraken_cvd_collector.py")))
        self.assertIn("--trade-log", command)
        self.assertIn("state/trades.jsonl", command)
        self.assertIn("--checkpoint-file", command)
        self.assertNotIn("create_order", command)
        self.assertNotIn("private", command)


if __name__ == "__main__":
    unittest.main()
