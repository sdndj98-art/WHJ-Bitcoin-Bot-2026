"""Shared-cash, forward-only paper portfolio ledger.

All strategies and assets draw from one persistent cash pool. This module is
an isolated ledger primitive; it deliberately sends no broker/exchange orders.
"""
import json
import math
import os
import tempfile
from pathlib import Path

SUPPORTED_STRATEGIES = (
    "sma_trend", "ema_trend", "rsi_momentum", "sma200_regime",
    "ema50_200_regime", "bollinger_mean_reversion", "rsi14_mean_reversion",
)
SCHEMA_VERSION = 1


def _finite(value, name, minimum=None):
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
        raise ValueError(name + " must be a finite number")
    value = float(value)
    if minimum is not None and value < minimum:
        raise ValueError(name + " is below its minimum")
    return value


class SharedPaperPortfolio:
    """One cash pool shared by every strategy; state is atomically persisted."""

    def __init__(self, state_path, initial_cash_usd=100.0, fee_rate=0.001):
        self.path = Path(state_path)
        self.initial_cash = _finite(initial_cash_usd, "initial_cash_usd", 0.01)
        self.fee_rate = _finite(fee_rate, "fee_rate", 0.0)
        if self.fee_rate >= 1:
            raise ValueError("fee_rate must be less than 1")
        state_existed = self.path.exists()
        self.state = self._load()
        if not state_existed:
            self._save()

    def _empty(self):
        return {
            "schema_version": SCHEMA_VERSION,
            "mode": "PAPER_ONLY",
            "live_trading_enabled": False,
            "initial_cash_usd": self.initial_cash,
            "cash_usd": self.initial_cash,
            "positions": {},
            "closed_trades": [],
            "fees_paid_usd": 0.0,
            "next_position_number": 1,
            "strategy_state": {},
        }

    def _load(self):
        if not self.path.exists():
            return self._empty()
        try:
            state = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise ValueError("Shared portfolio state unreadable; refusing reset") from exc
        if not isinstance(state, dict) or state.get("schema_version") != SCHEMA_VERSION:
            raise ValueError("Unknown shared portfolio schema; manual migration required")
        if state.get("mode") != "PAPER_ONLY" or state.get("live_trading_enabled") is not False:
            raise ValueError("Unsafe portfolio mode; refusing to load")
        saved_initial = _finite(state.get("initial_cash_usd"), "saved initial cash", 0.01)
        if not math.isclose(saved_initial, self.initial_cash, rel_tol=0, abs_tol=1e-8):
            raise ValueError("Configured capital differs from saved ledger; migration required")
        _finite(state.get("cash_usd"), "saved cash", 0)
        _finite(state.get("fees_paid_usd"), "saved fees", 0)
        if not isinstance(state.get("positions"), dict) or not isinstance(state.get("closed_trades"), list):
            raise ValueError("Shared portfolio collections are invalid")
        if not isinstance(state.get("strategy_state", {}), dict):
            raise ValueError("Shared strategy state is invalid")
        if state["cash_usd"] < -1e-8:
            raise ValueError("Saved shared cash is negative")
        active_pairs = set()
        for position_id, position in state["positions"].items():
            if not isinstance(position, dict) or position.get("strategy") not in SUPPORTED_STRATEGIES:
                raise ValueError("Saved position strategy is invalid")
            if not isinstance(position_id, str) or not position_id:
                raise ValueError("Saved position id is invalid")
            pair = (position["strategy"], position.get("asset"))
            if pair in active_pairs:
                raise ValueError("Duplicate active strategy/asset allocation")
            active_pairs.add(pair)
            for field in ("units", "entry_price", "entry_notional_usd", "entry_fee_usd"):
                _finite(position.get(field), "position " + field, 0)
            if position["units"] <= 0 or position["entry_price"] <= 0:
                raise ValueError("Saved position size and price must be positive")
        return state

    def _save(self):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        temp_path = None
        try:
            with tempfile.NamedTemporaryFile(
                "w", encoding="utf-8", dir=str(self.path.parent),
                prefix="." + self.path.name + ".", suffix=".tmp", delete=False
            ) as handle:
                temp_path = handle.name
                json.dump(self.state, handle, indent=2, allow_nan=False)
                handle.write("\n")
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(temp_path, self.path)
        except Exception:
            if temp_path and os.path.exists(temp_path):
                os.unlink(temp_path)
            raise

    def save_strategy_state(self, strategy_state):
        if not isinstance(strategy_state, dict):
            raise ValueError("strategy_state must be an object")
        self.state["strategy_state"] = strategy_state
        self._save()

    def open_position(self, strategy, asset, price, notional_usd, position_id=None):
        if strategy not in SUPPORTED_STRATEGIES:
            raise ValueError("Unsupported strategy")
        if not isinstance(asset, str) or not asset.strip():
            raise ValueError("asset is required")
        price = _finite(price, "price", 0.00000001)
        notional = _finite(notional_usd, "notional_usd", 0.01)
        if notional > self.state["cash_usd"] + 1e-8:
            raise ValueError("Insufficient shared cash; allocation rejected")
        for p in self.state["positions"].values():
            if p["strategy"] == strategy and p["asset"] == asset:
                raise ValueError("Strategy already has an open position in this asset")
        if position_id is None:
            position_id = "paper-" + str(self.state["next_position_number"])
        if not isinstance(position_id, str) or not position_id or position_id in self.state["positions"]:
            raise ValueError("Position id must be unique")
        fee = notional * self.fee_rate
        total_debit = notional + fee
        if total_debit > self.state["cash_usd"] + 1e-8:
            raise ValueError("Insufficient shared cash after entry fee")
        position = {
            "strategy": strategy, "asset": asset,
            "units": notional / price, "entry_price": price,
            "entry_notional_usd": notional, "entry_fee_usd": fee,
        }
        self.state["cash_usd"] = round(self.state["cash_usd"] - total_debit, 10)
        self.state["fees_paid_usd"] = round(self.state["fees_paid_usd"] + fee, 10)
        self.state["positions"][position_id] = position
        self.state["next_position_number"] += 1
        self._save()
        return {"position_id": position_id, **position, "cash_usd": self.state["cash_usd"]}

    def close_position(self, position_id, price):
        if position_id not in self.state["positions"]:
            raise ValueError("Unknown open position")
        price = _finite(price, "price", 0.00000001)
        position = self.state["positions"][position_id]
        proceeds = position["units"] * price
        exit_fee = proceeds * self.fee_rate
        net_proceeds = proceeds - exit_fee
        if not math.isfinite(net_proceeds) or net_proceeds < 0:
            raise ValueError("Invalid close proceeds")
        total_fees = position["entry_fee_usd"] + exit_fee
        pnl = net_proceeds - position["entry_notional_usd"] - position["entry_fee_usd"]
        trade = {
            "position_id": position_id, "strategy": position["strategy"],
            "asset": position["asset"], "entry_price": position["entry_price"],
            "exit_price": price, "units": position["units"],
            "gross_proceeds_usd": proceeds, "fees_usd": total_fees,
            "pnl_usd": pnl,
        }
        self.state["cash_usd"] = round(self.state["cash_usd"] + net_proceeds, 10)
        self.state["fees_paid_usd"] = round(self.state["fees_paid_usd"] + exit_fee, 10)
        self.state["closed_trades"].append(trade)
        del self.state["positions"][position_id]
        self._save()
        return trade

    def snapshot(self, prices):
        if not isinstance(prices, dict):
            raise ValueError("prices must map each open asset to a current price")
        market_value = 0.0
        marked = []
        for position_id, position in self.state["positions"].items():
            if position["asset"] not in prices:
                raise ValueError("Missing mark price for " + position["asset"])
            mark = _finite(prices[position["asset"]], "mark price", 0.00000001)
            value = position["units"] * mark
            market_value += value
            marked.append({
                "position_id": position_id, "strategy": position["strategy"],
                "asset": position["asset"], "units": position["units"],
                "mark_price": mark, "market_value_usd": value,
            })
        equity = self.state["cash_usd"] + market_value
        return {
            "mode": "PAPER_ONLY", "live_trading_enabled": False,
            "initial_cash_usd": self.initial_cash,
            "cash_usd": self.state["cash_usd"],
            "open_positions": marked, "market_value_usd": market_value,
            "equity_usd": equity, "pnl_usd": equity - self.initial_cash,
            "fees_paid_usd": self.state["fees_paid_usd"],
            "closed_trades": len(self.state["closed_trades"]),
            "strategies_supported": list(SUPPORTED_STRATEGIES),
        }
