"""Read-only MetaTrader 5 market/account adapter.

This module deliberately has no order_send or trade-management implementation.
It attaches to an already configured local MT5 terminal and exposes sanitized
account metadata, quotes, and completed OHLCV bars for analysis/paper trading.
"""
import importlib
import math


class MetaTrader5ReadOnly:
    """Small, optional MT5 connector; no credentials are accepted or stored."""

    def __init__(self, mt5_module=None, terminal_path=None):
        self._mt5 = mt5_module
        self._terminal_path = terminal_path
        self._connected = False

    def _module(self):
        if self._mt5 is None:
            try:
                self._mt5 = importlib.import_module("MetaTrader5")
            except ImportError as exc:
                raise RuntimeError(
                    "MetaTrader5 package is unavailable. Run this connector on "
                    "Windows with the official MT5 Python package and terminal."
                ) from exc
        return self._mt5

    @property
    def connected(self):
        return self._connected

    def connect(self):
        """Attach to an already configured MT5 terminal; never logs in."""
        mt5 = self._module()
        if self._connected:
            return self.status()
        initialized = (
            mt5.initialize(path=self._terminal_path)
            if self._terminal_path else mt5.initialize()
        )
        if not initialized:
            error = mt5.last_error() if hasattr(mt5, "last_error") else "unknown"
            raise RuntimeError(f"Could not initialize MetaTrader 5 terminal: {error}")
        terminal = mt5.terminal_info()
        account = mt5.account_info()
        if terminal is None or account is None:
            error = mt5.last_error() if hasattr(mt5, "last_error") else "unknown"
            mt5.shutdown()
            raise RuntimeError(f"MT5 terminal/account information unavailable: {error}")
        self._connected = True
        return self.status()

    def _require_connection(self):
        if not self._connected:
            raise RuntimeError("Connect to the MT5 terminal before requesting data")

    def status(self):
        self._require_connection()
        mt5 = self._module()
        terminal = mt5.terminal_info()
        account = mt5.account_info()
        if terminal is None or account is None:
            raise RuntimeError("MT5 terminal connection was lost")
        return {
            "provider": "MetaTrader 5",
            "mode": "READ_ONLY_PAPER_DATA",
            "connected": True,
            "terminal_connected": bool(getattr(terminal, "connected", False)),
            "trade_allowed_by_terminal": bool(getattr(account, "trade_allowed", False)),
            "trade_expert_allowed": bool(getattr(account, "trade_expert", False)),
            "broker_company": str(getattr(terminal, "company", "") or ""),
            "server": str(getattr(account, "server", "") or ""),
            "currency": str(getattr(account, "currency", "") or ""),
            "leverage": int(getattr(account, "leverage", 0) or 0),
            "account_balance": self._finite(getattr(account, "balance", 0), "balance"),
            "account_equity": self._finite(getattr(account, "equity", 0), "equity"),
            "account_margin": self._finite(getattr(account, "margin", 0), "margin"),
            "account_free_margin": self._finite(
                getattr(account, "margin_free", 0), "free margin"
            ),
            "account_profit": self._finite(getattr(account, "profit", 0), "profit"),
        }

    @staticmethod
    def _finite(value, label):
        if isinstance(value, bool):
            raise ValueError(f"MT5 {label} is not a valid numeric value")
        try:
            number = float(value)
        except (TypeError, ValueError, OverflowError) as exc:
            raise ValueError(f"MT5 {label} is not numeric") from exc
        if not math.isfinite(number):
            raise ValueError(f"MT5 {label} must be finite")
        return number

    def fetch_closed_rates(self, symbol, timeframe="TIMEFRAME_H1", count=500):
        """Return completed bars only; MT5 position 0 (forming bar) is excluded."""
        self._require_connection()
        if not isinstance(symbol, str) or not symbol.strip():
            raise ValueError("A non-empty MT5 symbol is required")
        if isinstance(count, bool) or not isinstance(count, int) or not 1 <= count <= 10000:
            raise ValueError("count must be an integer between 1 and 10000")
        mt5 = self._module()
        timeframe_value = getattr(mt5, timeframe, None)
        if timeframe_value is None or not timeframe.startswith("TIMEFRAME_"):
            raise ValueError("Unsupported MT5 timeframe")
        rates = mt5.copy_rates_from_pos(symbol.strip(), timeframe_value, 1, count)
        if rates is None:
            error = mt5.last_error() if hasattr(mt5, "last_error") else "unknown"
            raise RuntimeError(f"MT5 returned no rates for {symbol}: {error}")
        rows = []
        for rate in rates:
            try:
                timestamp = self._finite(rate["time"], "bar timestamp")
                if not timestamp.is_integer() or timestamp < 0:
                    raise ValueError("MT5 bar timestamp must be a non-negative integer")
                values = {
                    "open": self._finite(rate["open"], "open"),
                    "high": self._finite(rate["high"], "high"),
                    "low": self._finite(rate["low"], "low"),
                    "close": self._finite(rate["close"], "close"),
                    "tick_volume": self._finite(rate["tick_volume"], "tick volume"),
                    "spread": self._finite(rate["spread"], "spread"),
                    "real_volume": self._finite(rate["real_volume"], "real volume"),
                }
            except (KeyError, TypeError, IndexError) as exc:
                raise ValueError("MT5 returned a malformed OHLCV bar") from exc
            if min(values["open"], values["high"], values["low"], values["close"]) <= 0:
                raise ValueError("MT5 bar prices must be positive")
            if values["high"] < max(values["open"], values["close"], values["low"]):
                raise ValueError("MT5 bar high is inconsistent with OHLC values")
            if values["low"] > min(values["open"], values["close"], values["high"]):
                raise ValueError("MT5 bar low is inconsistent with OHLC values")
            if min(values["tick_volume"], values["spread"], values["real_volume"]) < 0:
                raise ValueError("MT5 volume and spread values cannot be negative")
            rows.append({"timestamp": int(timestamp), **values})
        timestamps = [row["timestamp"] for row in rows]
        if timestamps != sorted(timestamps) or len(set(timestamps)) != len(timestamps):
            raise ValueError("MT5 bars are duplicated or not in chronological order")
        return rows

    def get_quote(self, symbol):
        """Return a validated bid/ask snapshot without sending an order."""
        self._require_connection()
        if not isinstance(symbol, str) or not symbol.strip():
            raise ValueError("A non-empty MT5 symbol is required")
        tick = self._module().symbol_info_tick(symbol.strip())
        if tick is None:
            raise RuntimeError(f"MT5 quote unavailable for {symbol}")
        bid = self._finite(tick.bid, "bid")
        ask = self._finite(tick.ask, "ask")
        if bid <= 0 or ask <= 0 or ask < bid:
            raise ValueError("MT5 returned an invalid bid/ask quote")
        return {
            "symbol": symbol.strip(),
            "bid": bid,
            "ask": ask,
            "spread": round(ask - bid, 12),
            "time": int(self._finite(tick.time, "quote timestamp")),
            "mode": "READ_ONLY",
        }

    def close(self):
        if self._connected:
            self._module().shutdown()
            self._connected = False
