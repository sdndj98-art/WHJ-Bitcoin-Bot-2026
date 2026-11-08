"""Explicitly gated, demo-account-only MT5 market-order gateway.

This module is NOT wired into the scanner or dashboard. It requires both an
in-process opt-in and WHJ_ENABLE_MT5_DEMO_ORDERS=YES, and it refuses non-demo
accounts. It never supports live accounts, withdrawals, or position closing.
"""
import os
import re
import sqlite3
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP
from pathlib import Path


class MetaTrader5DemoExecutor:
    def __init__(self, adapter, enabled=False, ledger_path="mt5_demo_order_guard.sqlite3"):
        self._adapter = adapter
        self._enabled = enabled
        self._ledger_path = Path(ledger_path)

    def _require_demo_permission(self, mt5):
        if self._enabled is not True or os.environ.get("WHJ_ENABLE_MT5_DEMO_ORDERS") != "YES":
            raise RuntimeError(
                "Demo execution is disabled. Explicitly enable it in code and set "
                "WHJ_ENABLE_MT5_DEMO_ORDERS=YES in the local environment."
            )
        if not getattr(self._adapter, "connected", False):
            raise RuntimeError("Connect the read-only MT5 adapter before demo execution")
        account = mt5.account_info()
        terminal = mt5.terminal_info()
        demo_mode = getattr(mt5, "ACCOUNT_TRADE_MODE_DEMO", None)
        if account is None or terminal is None:
            raise RuntimeError("MT5 account or terminal status is unavailable")
        if demo_mode is None or getattr(account, "trade_mode", None) != demo_mode:
            raise RuntimeError("Refusing execution: MT5 account is not positively identified as DEMO")
        if not bool(getattr(terminal, "connected", False)):
            raise RuntimeError("MT5 terminal is disconnected")
        if bool(getattr(terminal, "tradeapi_disabled", False)):
            raise RuntimeError("MT5 terminal has disabled trade API access")
        if not bool(getattr(account, "trade_allowed", False)) or not bool(
            getattr(account, "trade_expert", False)
        ):
            raise RuntimeError("MT5 demo account does not allow expert trading")
        return account

    @staticmethod
    def _decimal(value, label, minimum=None):
        if isinstance(value, bool):
            raise ValueError(f"{label} must be a valid positive number")
        try:
            number = Decimal(str(value))
        except (InvalidOperation, TypeError, ValueError) as exc:
            raise ValueError(f"{label} must be a valid positive number") from exc
        if not number.is_finite() or (minimum is not None and number < Decimal(str(minimum))):
            raise ValueError(f"{label} must be a valid positive number")
        return number

    @staticmethod
    def _round_to_tick(value, tick_size, digits):
        units = (value / tick_size).quantize(Decimal("1"), rounding=ROUND_HALF_UP)
        return float(round(units * tick_size, digits))

    def _reserve_signal(self, signal_id, symbol, side, volume):
        self._ledger_path.parent.mkdir(parents=True, exist_ok=True)
        with sqlite3.connect(str(self._ledger_path), timeout=5) as db:
            db.execute(
                """CREATE TABLE IF NOT EXISTS demo_order_guard (
                    signal_id TEXT PRIMARY KEY,
                    symbol TEXT NOT NULL,
                    side TEXT NOT NULL,
                    volume TEXT NOT NULL,
                    status TEXT NOT NULL,
                    created_utc TEXT NOT NULL,
                    broker_order_id TEXT,
                    result_code INTEGER,
                    message TEXT
                )"""
            )
            try:
                db.execute(
                    """INSERT INTO demo_order_guard
                    (signal_id, symbol, side, volume, status, created_utc)
                    VALUES (?, ?, ?, ?, 'SUBMITTING', ?)""",
                    (
                        signal_id, symbol, side, str(volume),
                        datetime.now(timezone.utc).isoformat(),
                    ),
                )
            except sqlite3.IntegrityError as exc:
                raise RuntimeError(
                    "This signal_id has already been submitted or reserved; "
                    "reconcile its prior status before attempting another order."
                ) from exc

    def _update_signal(self, signal_id, status, order_id=None, result_code=None, message=""):
        with sqlite3.connect(str(self._ledger_path), timeout=5) as db:
            db.execute(
                """UPDATE demo_order_guard SET status=?, broker_order_id=?,
                result_code=?, message=? WHERE signal_id=?""",
                (status, None if order_id is None else str(order_id),
                 result_code, str(message)[:300], signal_id),
            )

    def submit_market_order(
        self, symbol, side, volume, stop_loss, take_profit, signal_id,
        deviation_points=20, magic=26061108,
    ):
        """Submit one protected market order to an explicitly enabled MT5 demo account."""
        if not isinstance(symbol, str) or not symbol.strip() or len(symbol) > 64:
            raise ValueError("A valid broker symbol is required")
        symbol = symbol.strip()
        side = str(side).upper() if isinstance(side, str) else ""
        if side not in ("BUY", "SELL"):
            raise ValueError("side must be BUY or SELL")
        if not isinstance(signal_id, str) or not re.fullmatch(r"[A-Za-z0-9_-]{1,20}", signal_id):
            raise ValueError("signal_id must contain 1-20 letters, numbers, underscores or hyphens")
        if isinstance(deviation_points, bool) or not isinstance(deviation_points, int) or not 0 <= deviation_points <= 10000:
            raise ValueError("deviation_points must be an integer between 0 and 10000")
        if isinstance(magic, bool) or not isinstance(magic, int) or not 1 <= magic <= 2147483647:
            raise ValueError("magic must be a positive 32-bit integer")

        mt5 = self._adapter._module()
        self._require_demo_permission(mt5)

        if hasattr(mt5, "symbol_select") and not mt5.symbol_select(symbol, True):
            raise RuntimeError(f"Could not select MT5 symbol {symbol}")
        info = mt5.symbol_info(symbol)
        if info is None:
            raise RuntimeError(f"MT5 symbol metadata unavailable for {symbol}")
        trade_mode = getattr(info, "trade_mode", None)
        full_mode = getattr(mt5, "SYMBOL_TRADE_MODE_FULL", None)
        long_mode = getattr(mt5, "SYMBOL_TRADE_MODE_LONGONLY", None)
        short_mode = getattr(mt5, "SYMBOL_TRADE_MODE_SHORTONLY", None)
        allowed_modes = {full_mode}
        allowed_modes.add(long_mode if side == "BUY" else short_mode)
        if trade_mode not in allowed_modes or trade_mode is None:
            raise RuntimeError(f"Broker does not permit {side} trading on {symbol}")

        requested_volume = self._decimal(volume, "volume", Decimal("0.00000001"))
        minimum = self._decimal(getattr(info, "volume_min", None), "broker minimum volume")
        maximum = self._decimal(getattr(info, "volume_max", None), "broker maximum volume")
        step = self._decimal(getattr(info, "volume_step", None), "broker volume step")
        if step <= 0 or requested_volume < minimum or requested_volume > maximum:
            raise ValueError("Requested volume is outside the broker's allowed range")
        steps = (requested_volume - minimum) / step
        if abs(steps - steps.to_integral_value()) > Decimal("0.00000001"):
            raise ValueError("Requested volume does not match the broker's volume step")

        point = self._decimal(getattr(info, "point", None), "broker point")
        tick_size = self._decimal(
            getattr(info, "trade_tick_size", None) or getattr(info, "point", None),
            "broker tick size",
        )
        digits = getattr(info, "digits", None)
        if isinstance(digits, bool) or not isinstance(digits, int) or not 0 <= digits <= 10:
            raise ValueError("Broker symbol digits are invalid")
        tick = self._adapter.get_quote(symbol)
        entry = self._decimal(tick["ask"] if side == "BUY" else tick["bid"], "entry price")
        sl = self._round_to_tick(self._decimal(stop_loss, "stop loss"), tick_size, digits)
        tp = self._round_to_tick(self._decimal(take_profit, "take profit"), tick_size, digits)
        sl_dec, tp_dec = Decimal(str(sl)), Decimal(str(tp))
        minimum_distance = point * self._decimal(
            getattr(info, "trade_stops_level", 0), "broker stop level"
        )
        if side == "BUY":
            if not sl_dec < entry < tp_dec:
                raise ValueError("BUY protection must satisfy stop_loss < entry < take_profit")
            if entry - sl_dec < minimum_distance or tp_dec - entry < minimum_distance:
                raise ValueError("BUY stop-loss/take-profit is inside the broker minimum stop distance")
            order_type = getattr(mt5, "ORDER_TYPE_BUY", None)
        else:
            if not tp_dec < entry < sl_dec:
                raise ValueError("SELL protection must satisfy take_profit < entry < stop_loss")
            if sl_dec - entry < minimum_distance or entry - tp_dec < minimum_distance:
                raise ValueError("SELL stop-loss/take-profit is inside the broker minimum stop distance")
            order_type = getattr(mt5, "ORDER_TYPE_SELL", None)
        if order_type is None:
            raise RuntimeError("MT5 order type constants are unavailable")

        fill_flags = int(getattr(info, "filling_mode", 0) or 0)
        if fill_flags & int(getattr(mt5, "SYMBOL_FILLING_FOK", 1)):
            filling = getattr(mt5, "ORDER_FILLING_FOK", None)
        elif fill_flags & int(getattr(mt5, "SYMBOL_FILLING_IOC", 2)):
            filling = getattr(mt5, "ORDER_FILLING_IOC", None)
        elif fill_flags & int(getattr(mt5, "SYMBOL_FILLING_RETURN", 4)):
            if getattr(info, "trade_exemode", None) == getattr(mt5, "SYMBOL_TRADE_EXECUTION_MARKET", object()):
                raise RuntimeError("RETURN filling is not allowed for this market-execution symbol")
            filling = getattr(mt5, "ORDER_FILLING_RETURN", None)
        else:
            raise RuntimeError("Broker has not advertised a supported order filling policy")
        if filling is None:
            raise RuntimeError("MT5 order filling constants are unavailable")

        request = {
            "action": getattr(mt5, "TRADE_ACTION_DEAL"),
            "symbol": symbol,
            "volume": float(requested_volume),
            "type": order_type,
            "price": float(entry),
            "sl": sl,
            "tp": tp,
            "deviation": deviation_points,
            "magic": magic,
            "comment": "WHJ-Demo-" + signal_id,
            "type_time": getattr(mt5, "ORDER_TIME_GTC"),
            "type_filling": filling,
        }
        check = mt5.order_check(request)
        if check is None or getattr(check, "retcode", None) != 0:
            code = None if check is None else getattr(check, "retcode", None)
            message = "MT5 order_check rejected the request" if check is not None else "MT5 order_check returned no result"
            raise RuntimeError(f"{message}: {code}")

        self._reserve_signal(signal_id, symbol, side, requested_volume)
        try:
            result = mt5.order_send(request)
        except Exception as exc:
            self._update_signal(signal_id, "UNKNOWN", message="order_send raised; reconcile in MT5 before retrying")
            raise RuntimeError(
                "MT5 demo order outcome is unknown. Check the demo terminal and local guard ledger; do not retry this signal_id."
            ) from exc
        if result is None:
            self._update_signal(signal_id, "UNKNOWN", message="order_send returned no result; manual reconciliation required")
            raise RuntimeError(
                "MT5 demo order outcome is unknown. Check the demo terminal and local guard ledger; do not retry this signal_id."
            )

        retcode = getattr(result, "retcode", None)
        order_id = getattr(result, "order", None)
        done = getattr(mt5, "TRADE_RETCODE_DONE", None)
        placed = getattr(mt5, "TRADE_RETCODE_PLACED", None)
        partial = getattr(mt5, "TRADE_RETCODE_DONE_PARTIAL", None)
        if retcode in (done, placed):
            self._update_signal(signal_id, "SUBMITTED", order_id, retcode, getattr(result, "comment", ""))
            return {
                "status": "SUBMITTED_TO_DEMO",
                "symbol": symbol,
                "side": side,
                "volume": float(requested_volume),
                "order_id": order_id,
                "retcode": retcode,
                "live_account_supported": False,
            }
        if retcode == partial:
            self._update_signal(signal_id, "PARTIAL", order_id, retcode, getattr(result, "comment", ""))
            return {
                "status": "PARTIALLY_FILLED_ON_DEMO",
                "symbol": symbol,
                "side": side,
                "volume": float(requested_volume),
                "order_id": order_id,
                "retcode": retcode,
                "live_account_supported": False,
                "warning": "Partial fill: reconcile the remaining volume manually; no automatic retry is performed.",
            }
        self._update_signal(signal_id, "REJECTED", order_id, retcode, getattr(result, "comment", ""))
        raise RuntimeError(f"MT5 demo order rejected with retcode {retcode}; no automatic retry was attempted")
