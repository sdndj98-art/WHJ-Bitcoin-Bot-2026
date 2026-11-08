import os
import sqlite3
import tempfile
import unittest
from types import SimpleNamespace
from unittest.mock import patch

from mt5_demo_executor import MetaTrader5DemoExecutor


class FakeMT5:
    ACCOUNT_TRADE_MODE_DEMO = 0
    ACCOUNT_TRADE_MODE_REAL = 2
    SYMBOL_TRADE_MODE_DISABLED = 0
    SYMBOL_TRADE_MODE_LONGONLY = 1
    SYMBOL_TRADE_MODE_SHORTONLY = 2
    SYMBOL_TRADE_MODE_FULL = 4
    SYMBOL_FILLING_FOK = 1
    SYMBOL_FILLING_IOC = 2
    SYMBOL_FILLING_RETURN = 4
    ORDER_FILLING_FOK = 0
    ORDER_FILLING_IOC = 1
    ORDER_FILLING_RETURN = 2
    SYMBOL_TRADE_EXECUTION_MARKET = 2
    ORDER_TYPE_BUY = 0
    ORDER_TYPE_SELL = 1
    TRADE_ACTION_DEAL = 1
    ORDER_TIME_GTC = 0
    TRADE_RETCODE_DONE = 10009
    TRADE_RETCODE_PLACED = 10008
    TRADE_RETCODE_DONE_PARTIAL = 10010

    def __init__(self, trade_mode=0):
        self.trade_mode = trade_mode
        self.order_send_calls = []
        self.order_check_retcode = 0
        self.send_result = SimpleNamespace(retcode=10009, order=4321, comment="Done")
        self.info = SimpleNamespace(
            trade_mode=4, volume_min=0.01, volume_max=10.0, volume_step=0.01,
            point=0.01, trade_tick_size=0.01, digits=2, trade_stops_level=10,
            filling_mode=1, trade_exemode=2,
        )

    def account_info(self):
        return SimpleNamespace(
            trade_mode=self.trade_mode, trade_allowed=True, trade_expert=True
        )

    def terminal_info(self):
        return SimpleNamespace(connected=True, tradeapi_disabled=False)

    def symbol_select(self, symbol, selected):
        return True

    def symbol_info(self, symbol):
        return self.info

    def order_check(self, request):
        self.checked_request = request
        return SimpleNamespace(retcode=self.order_check_retcode, comment="check")

    def order_send(self, request):
        self.order_send_calls.append(request)
        return self.send_result


class FakeAdapter:
    def __init__(self, mt5):
        self.mt5 = mt5
        self.connected = True

    def _module(self):
        return self.mt5

    def get_quote(self, symbol):
        return {"symbol": symbol, "bid": 100.0, "ask": 100.2, "spread": 0.2, "time": 1}


class DemoExecutorTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.mt5 = FakeMT5()
        self.adapter = FakeAdapter(self.mt5)
        self.ledger = self.temp.name + "/guard.sqlite3"

    def executor(self, enabled=True):
        return MetaTrader5DemoExecutor(
            self.adapter, enabled=enabled, ledger_path=self.ledger
        )

    def submit(self, executor, signal_id="signal-001", **overrides):
        args = {
            "symbol": "BTCUSD", "side": "BUY", "volume": 0.02,
            "stop_loss": 99.8, "take_profit": 101.0,
            "signal_id": signal_id, "deviation_points": 15,
        }
        args.update(overrides)
        return executor.submit_market_order(**args)

    def test_requires_two_explicit_demo_opt_ins(self):
        with patch.dict(os.environ, {}, clear=True):
            with self.assertRaisesRegex(RuntimeError, "disabled"):
                self.submit(self.executor(enabled=True))
        with patch.dict(os.environ, {"WHJ_ENABLE_MT5_DEMO_ORDERS": "YES"}):
            with self.assertRaisesRegex(RuntimeError, "disabled"):
                self.submit(self.executor(enabled=False))
        self.assertEqual(self.mt5.order_send_calls, [])

    def test_refuses_real_account_even_when_explicitly_enabled(self):
        self.mt5.trade_mode = self.mt5.ACCOUNT_TRADE_MODE_REAL
        with patch.dict(os.environ, {"WHJ_ENABLE_MT5_DEMO_ORDERS": "YES"}):
            with self.assertRaisesRegex(RuntimeError, "not positively identified as DEMO"):
                self.submit(self.executor())
        self.assertEqual(self.mt5.order_send_calls, [])

    def test_demo_order_requires_protective_stops_and_is_sent_once(self):
        with patch.dict(os.environ, {"WHJ_ENABLE_MT5_DEMO_ORDERS": "YES"}):
            result = self.submit(self.executor())
            self.assertEqual(result["status"], "SUBMITTED_TO_DEMO")
            self.assertEqual(result["order_id"], 4321)
            self.assertEqual(len(self.mt5.order_send_calls), 1)
            request = self.mt5.order_send_calls[0]
            self.assertEqual(request["sl"], 99.8)
            self.assertEqual(request["tp"], 101.0)
            self.assertEqual(request["type"], self.mt5.ORDER_TYPE_BUY)
            with self.assertRaisesRegex(RuntimeError, "already been submitted"):
                self.submit(self.executor(), signal_id="signal-001")
            self.assertEqual(len(self.mt5.order_send_calls), 1)

    def test_sell_order_uses_inverse_stop_geometry(self):
        with patch.dict(os.environ, {"WHJ_ENABLE_MT5_DEMO_ORDERS": "YES"}):
            result = self.submit(
                self.executor(), signal_id="sell-001", side="SELL",
                stop_loss=100.5, take_profit=99.5
            )
        self.assertEqual(result["status"], "SUBMITTED_TO_DEMO")
        self.assertEqual(self.mt5.order_send_calls[0]["type"], self.mt5.ORDER_TYPE_SELL)

    def test_rejects_bad_stop_geometry_and_volume_step_before_order_check(self):
        with patch.dict(os.environ, {"WHJ_ENABLE_MT5_DEMO_ORDERS": "YES"}):
            with self.assertRaisesRegex(ValueError, "BUY protection"):
                self.submit(self.executor(), stop_loss=100.3, take_profit=101.0)
            with self.assertRaisesRegex(ValueError, "volume step"):
                self.submit(self.executor(), signal_id="signal-002", volume=0.025)
            with self.assertRaisesRegex(ValueError, "stop loss"):
                self.submit(self.executor(), signal_id="signal-003", stop_loss=0)
        self.assertFalse(hasattr(self.mt5, "checked_request"))
        self.assertEqual(self.mt5.order_send_calls, [])

    def test_order_check_failure_never_sends(self):
        self.mt5.order_check_retcode = 10016
        with patch.dict(os.environ, {"WHJ_ENABLE_MT5_DEMO_ORDERS": "YES"}):
            with self.assertRaisesRegex(RuntimeError, "order_check rejected"):
                self.submit(self.executor())
        self.assertEqual(self.mt5.order_send_calls, [])

    def test_unknown_order_send_result_is_locked_against_duplicate_retry(self):
        self.mt5.send_result = None
        with patch.dict(os.environ, {"WHJ_ENABLE_MT5_DEMO_ORDERS": "YES"}):
            with self.assertRaisesRegex(RuntimeError, "outcome is unknown"):
                self.submit(self.executor())
            with self.assertRaisesRegex(RuntimeError, "already been submitted"):
                self.submit(self.executor(), signal_id="signal-001")
        with sqlite3.connect(self.ledger) as db:
            status = db.execute(
                "SELECT status FROM demo_order_guard WHERE signal_id='signal-001'"
            ).fetchone()[0]
        self.assertEqual(status, "UNKNOWN")
        self.assertEqual(len(self.mt5.order_send_calls), 1)

    def test_partial_fill_is_reported_without_automatic_retry(self):
        self.mt5.send_result = SimpleNamespace(retcode=10010, order=555, comment="partial")
        with patch.dict(os.environ, {"WHJ_ENABLE_MT5_DEMO_ORDERS": "YES"}):
            result = self.submit(self.executor())
        self.assertEqual(result["status"], "PARTIALLY_FILLED_ON_DEMO")
        self.assertEqual(len(self.mt5.order_send_calls), 1)

    def test_terminal_or_account_permission_failure_blocks_demo_order(self):
        self.mt5.terminal_info = lambda: SimpleNamespace(connected=True, tradeapi_disabled=True)
        with patch.dict(os.environ, {"WHJ_ENABLE_MT5_DEMO_ORDERS": "YES"}):
            with self.assertRaisesRegex(RuntimeError, "disabled trade API"):
                self.submit(self.executor())
        self.assertEqual(self.mt5.order_send_calls, [])


if __name__ == "__main__":
    unittest.main()
