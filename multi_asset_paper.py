"""Multi-asset isolated paper ledger for broker-discovered WHJ markets.

Consumes validated quotes and explicit strategy signals. It never requests market
data, places broker orders, or assumes broker contract specifications.
"""
from __future__ import annotations

import json
import math
import os
import tempfile
from datetime import datetime, timezone
from pathlib import Path

PAPER_ONLY = True
LIVE_TRADING_ENABLED = False
DEFAULT_INITIAL_CASH_USD = 1000.0
DEFAULT_ALLOCATION_PCT = 2.0
DEFAULT_FEE_RATE = 0.001
DEFAULT_MAX_DAILY_LOSS_PCT = 3.0
DEFAULT_MAX_DRAWDOWN_PCT = 10.0


def _number(value, name, minimum=None, strict_min=False):
    if isinstance(value, bool):
        raise ValueError(f"{name} must be finite numeric")
    try:
        n = float(value)
    except (TypeError, ValueError, OverflowError) as exc:
        raise ValueError(f"{name} must be finite numeric") from exc
    if not math.isfinite(n):
        raise ValueError(f"{name} must be finite numeric")
    if minimum is not None and (n <= minimum if strict_min else n < minimum):
        raise ValueError(f"{name} is outside the allowed range")
    return n


def _new_sleeve(initial_cash, day):
    return {
        "initial_cash_usd": initial_cash,
        "cash_usd": initial_cash,
        "position": None,
        "realized_pnl_usd": 0.0,
        "fees_paid_usd": 0.0,
        "closed_trades": 0,
        "wins": 0,
        "peak_equity_usd": initial_cash,
        "day": day,
        "day_start_equity_usd": initial_cash,
        "daily_paused": False,
        "drawdown_paused": False,
        "last_quote_timestamp": None,
    }


def _validate_state(state, initial_cash, day):
    if not isinstance(state, dict):
        raise ValueError("paper state must be an object")
    sleeves = state.setdefault("markets", {})
    if not isinstance(sleeves, dict):
        raise ValueError("state markets must be an object")
    for symbol, sleeve in sleeves.items():
        if not isinstance(symbol, str) or not isinstance(sleeve, dict):
            raise ValueError("malformed market sleeve")
        for key in ("cash_usd", "realized_pnl_usd", "fees_paid_usd",
                    "peak_equity_usd", "day_start_equity_usd"):
            sleeve[key] = _number(sleeve.get(key), f"{symbol}.{key}")
        if sleeve.get("position") is not None:
            pos = sleeve["position"]
            if not isinstance(pos, dict):
                raise ValueError("position must be an object or null")
            for key in ("quantity", "entry_price", "contract_size", "quote_to_usd",
                        "entry_notional_usd", "entry_fee_usd"):
                pos[key] = _number(pos.get(key), f"{symbol}.position.{key}", 0, True)
        if sleeve.get("day") != day:
            equity = _equity(sleeve, None)
            sleeve["day"] = day
            sleeve["day_start_equity_usd"] = equity
            sleeve["daily_paused"] = False
    state.setdefault("version", 1)
    state["mode"] = "MULTI_ASSET_PAPER_ONLY"
    state["paper_only"] = True
    state["live_trading_enabled"] = False
    state["orders_submitted"] = False
    return state


def _equity(sleeve, bid_usd):
    position = sleeve.get("position")
    if not position:
        return sleeve["cash_usd"]
    if bid_usd is None:
        return sleeve["cash_usd"] + position["entry_notional_usd"]
    mark = (position["quantity"] * position["contract_size"] *
            bid_usd * position["quote_to_usd"])
    return sleeve["cash_usd"] + mark


def process_snapshot(snapshot, state=None, *, now=None, initial_cash_usd=DEFAULT_INITIAL_CASH_USD,
                     allocation_pct=DEFAULT_ALLOCATION_PCT, fee_rate=DEFAULT_FEE_RATE,
                     max_daily_loss_pct=DEFAULT_MAX_DAILY_LOSS_PCT,
                     max_drawdown_pct=DEFAULT_MAX_DRAWDOWN_PCT):
    """Apply one snapshot; all markets have isolated cash and position records.

    snapshot schema: {quotes:{SYMBOL:{bid,ask,timestamp,contract_size,quote_to_usd}},
    signals:{SYMBOL:BUY|SELL|HOLD}, healthy_symbols:[...]}.
    Contract size and quote-to-USD conversion are mandatory for each traded symbol.
    """
    if not isinstance(snapshot, dict):
        raise ValueError("snapshot must be an object")
    cash = _number(initial_cash_usd, "initial_cash_usd", 0, True)
    allocation = _number(allocation_pct, "allocation_pct", 0, True)
    if allocation > 10:
        raise ValueError("allocation_pct must be <= 10")
    fee = _number(fee_rate, "fee_rate", 0)
    if fee >= 0.05:
        raise ValueError("fee_rate must be < 5%")
    daily_limit = _number(max_daily_loss_pct, "max_daily_loss_pct", 0, True)
    dd_limit = _number(max_drawdown_pct, "max_drawdown_pct", 0, True)
    current = datetime.fromtimestamp(now, timezone.utc) if now is not None else datetime.now(timezone.utc)
    day = current.date().isoformat()
    state = _validate_state(dict(state or {}), cash, day)
    quotes = snapshot.get("quotes")
    signals = snapshot.get("signals")
    healthy = snapshot.get("healthy_symbols")
    if not isinstance(quotes, dict) or not isinstance(signals, dict) or not isinstance(healthy, list):
        raise ValueError("snapshot requires quotes, signals, and healthy_symbols")
    events = []

    for raw_symbol, quote in quotes.items():
        if not isinstance(raw_symbol, str) or not raw_symbol.strip() or not isinstance(quote, dict):
            continue
        symbol = raw_symbol.strip()
        signal = str(signals.get(symbol, "HOLD")).upper()
        if signal not in ("BUY", "SELL", "HOLD"):
            signal = "HOLD"
        bid = _number(quote.get("bid"), f"{symbol}.bid", 0, True)
        ask = _number(quote.get("ask"), f"{symbol}.ask", 0, True)
        if ask < bid:
            raise ValueError(f"{symbol} ask must be >= bid")
        timestamp = quote.get("timestamp")
        if isinstance(timestamp, bool) or not isinstance(timestamp, (int, float)) or not math.isfinite(timestamp):
            raise ValueError(f"{symbol} quote timestamp must be finite")
        if timestamp > current.timestamp() + 60:
            raise ValueError(f"{symbol} quote is from the future")
        contract_size = _number(quote.get("contract_size"), f"{symbol}.contract_size", 0, True)
        quote_to_usd = _number(quote.get("quote_to_usd"), f"{symbol}.quote_to_usd", 0, True)
        sleeve = state["markets"].setdefault(symbol, _new_sleeve(cash, day))
        if timestamp <= (sleeve.get("last_quote_timestamp") or 0):
            events.append({"symbol": symbol, "action": "SKIP", "reason": "DUPLICATE_OR_OLD_QUOTE"})
            continue
        sleeve["last_quote_timestamp"] = timestamp
        bid_usd, ask_usd = bid * quote_to_usd, ask * quote_to_usd
        equity = _equity(sleeve, bid_usd)
        sleeve["peak_equity_usd"] = max(sleeve["peak_equity_usd"], equity)
        drawdown = ((sleeve["peak_equity_usd"] - equity) / sleeve["peak_equity_usd"] * 100
                    if sleeve["peak_equity_usd"] > 0 else 100.0)
        daily_loss = ((sleeve["day_start_equity_usd"] - equity) /
                      sleeve["day_start_equity_usd"] * 100
                      if sleeve["day_start_equity_usd"] > 0 else 100.0)
        if daily_loss >= daily_limit:
            sleeve["daily_paused"] = True
        if drawdown >= dd_limit:
            sleeve["drawdown_paused"] = True

        position = sleeve.get("position")
        if position and (signal == "SELL" or sleeve["daily_paused"] or sleeve["drawdown_paused"]):
            proceeds = position["quantity"] * position["contract_size"] * bid_usd
            exit_fee = proceeds * fee
            entry_notional = position["entry_notional_usd"]
            total_fees = position["entry_fee_usd"] + exit_fee
            pnl = proceeds - entry_notional - total_fees
            sleeve["cash_usd"] += proceeds - exit_fee
            sleeve["realized_pnl_usd"] += pnl
            sleeve["fees_paid_usd"] += exit_fee
            sleeve["closed_trades"] += 1
            if pnl > 0:
                sleeve["wins"] += 1
            sleeve["position"] = None
            events.append({"symbol": symbol, "action": "PAPER_CLOSE",
                           "reason": "SIGNAL_SELL" if signal == "SELL" else "RISK_GUARD",
                           "realized_pnl_usd": round(pnl, 8), "exit_price": bid})
            continue

        if (position is None and signal == "BUY" and symbol in healthy and
                not sleeve["daily_paused"] and not sleeve["drawdown_paused"]):
            target = min(sleeve["cash_usd"], equity * allocation / 100.0)
            qty = target / (ask_usd * contract_size * (1.0 + fee))
            notional = qty * contract_size * ask_usd
            entry_fee = notional * fee
            total_cost = notional + entry_fee
            if qty > 0 and total_cost <= sleeve["cash_usd"] + 1e-9:
                sleeve["cash_usd"] -= total_cost
                sleeve["fees_paid_usd"] += entry_fee
                sleeve["position"] = {
                    "quantity": qty, "entry_price": ask,
                    "contract_size": contract_size, "quote_to_usd": quote_to_usd,
                    "entry_notional_usd": notional, "entry_fee_usd": entry_fee,
                    "opened_at": int(timestamp),
                }
                events.append({"symbol": symbol, "action": "PAPER_OPEN",
                               "quantity": qty, "entry_price": ask,
                               "notional_usd": round(notional, 8),
                               "fee_usd": round(entry_fee, 8)})
        else:
            reason = ("DATA_NOT_HEALTHY" if signal == "BUY" and symbol not in healthy else
                      "RISK_PAUSED" if signal == "BUY" and (sleeve["daily_paused"] or sleeve["drawdown_paused"]) else
                      "NO_ENTRY_SIGNAL")
            events.append({"symbol": symbol, "action": "HOLD", "reason": reason})

    summary = {}
    for symbol, sleeve in sorted(state["markets"].items()):
        quote = quotes.get(symbol) if isinstance(quotes, dict) else None
        mark = None
        if isinstance(quote, dict):
            mark = _number(quote.get("bid"), f"{symbol}.bid", 0, True) * _number(
                quote.get("quote_to_usd"), f"{symbol}.quote_to_usd", 0, True)
        equity = _equity(sleeve, mark)
        summary[symbol] = {
            "equity_usd": round(equity, 8),
            "cash_usd": round(sleeve["cash_usd"], 8),
            "realized_pnl_usd": round(sleeve["realized_pnl_usd"], 8),
            "unrealized_pnl_usd": round(
                sleeve["position"]["quantity"] * sleeve["position"]["contract_size"] * mark
                - sleeve["position"]["entry_notional_usd"]
                - sleeve["position"]["quantity"] * sleeve["position"]["contract_size"] * mark * fee
                if sleeve["position"] and mark is not None else 0.0, 8),
            "fees_paid_usd": round(sleeve["fees_paid_usd"], 8),
            "closed_trades": sleeve["closed_trades"],
            "win_rate_pct": round(sleeve["wins"] / sleeve["closed_trades"] * 100, 4)
                            if sleeve["closed_trades"] else None,
            "position_open": sleeve["position"] is not None,
            "daily_paused": sleeve["daily_paused"],
            "drawdown_paused": sleeve["drawdown_paused"],
        }
    state["updated_at"] = current.isoformat()
    state["events"] = events
    state["summary"] = {
        "market_count": len(summary),
        "total_equity_usd": round(sum(item["equity_usd"] for item in summary.values()), 8),
        "realized_pnl_usd": round(sum(item["realized_pnl_usd"] for item in summary.values()), 8),
        "open_positions": sum(item["position_open"] for item in summary.values()),
        "markets": summary,
    }
    return state


def atomic_write_json(path, data):
    """Atomically persist paper state without exposing a partial JSON file."""
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    fd, temp_path = tempfile.mkstemp(prefix=target.name + ".", suffix=".tmp", dir=str(target.parent))
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            json.dump(data, handle, indent=2, sort_keys=True, allow_nan=False)
            handle.write("\\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temp_path, target)
    finally:
        if os.path.exists(temp_path):
            os.unlink(temp_path)


def load_state(path):
    target = Path(path)
    if not target.exists():
        return {}
    with target.open(encoding="utf-8") as handle:
        state = json.load(handle)
    if not isinstance(state, dict):
        raise ValueError("paper state file must contain a JSON object")
    return state


def main():
    import argparse
    parser = argparse.ArgumentParser(description="Update WHJ isolated multi-asset paper ledger from a quote/signal JSON snapshot.")
    parser.add_argument("--input", default="multi_asset_snapshot.json")
    parser.add_argument("--state", default="state/multi_asset_paper.json")
    parser.add_argument("--output", default="state/multi_asset_paper_report.json")
    args = parser.parse_args()
    with open(args.input, encoding="utf-8") as handle:
        snapshot = json.load(handle)
    state = process_snapshot(snapshot, load_state(args.state))
    atomic_write_json(args.state, state)
    atomic_write_json(args.output, state)
    print(json.dumps(state["summary"], indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
