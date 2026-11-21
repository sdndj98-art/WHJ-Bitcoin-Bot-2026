"""Multi-market forward-only paper engine sharing WHJ's single $100 ledger.

Crypto uses completed hourly candles; XAU/XAG/HG use validated daily bars.
No broker/exchange order endpoint is called; live trading is disabled.
"""
import json
import math
import time
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlencode

from multi_market_opportunity_scan import (
    KRAKEN_API, discover_kraken_universe, rank_kraken_pairs,
    normalize_kraken_ohlc, fetch_json, fetch_raw_json,
)
from shared_paper_portfolio import SharedPaperPortfolio, SUPPORTED_STRATEGIES
from shared_paper_runner import strategy_signal
from whj_agents import authorize_paper_entry
from metal_price_sources import fetch_spot, fetch_daily_bars

LEDGER = Path("state/shared_paper_100usd.json")
SNAPSHOT = Path("dual_portfolio.json")
REPORT = Path("state/multi_asset_paper_report.json")
INITIAL_CASH = 100.0
MAX_CRYPTO_MARKETS = 20
METALS = ("XAUUSD", "XAGUSD")  # shared $100 ledger: only metals with validated closed daily bars
TRADE_ALLOCATION = 0.02
MAX_GROSS_EXPOSURE = 0.50
MAX_OPEN_POSITIONS = 8
MIN_TRADE_USD = 1.0
FEE_RATE = 0.001
SLIPPAGE_RATE = 0.0005
MAX_DRAWDOWN = 0.10
DAILY_LOSS_LIMIT = 0.03
STATE_KEY = "multi_asset_strategy_state"
RISK_KEY = "multi_asset_risk_state"
EXCLUDED_BASES = {
    "BTC", "XBT", "USDT", "USDC", "DAI", "EURC", "USDS", "USDG",
    "USDP", "FDUSD", "TUSD", "PYUSD", "USDE", "USDD", "DUSD", "BUSD",
    "UST", "USTC", "FRAX", "GUSD", "LUSD", "USD0", "CRVUSD",
}
FIAT_BASES = {
    "EUR", "GBP", "CAD", "AUD", "CHF", "JPY", "NZD", "CNY", "CNH",
    "SGD", "HKD", "MXN", "BRL", "ZAR", "TRY", "PLN", "SEK", "NOK",
    "DKK", "CZK", "HUF", "ILS", "AED", "SAR", "THB", "IDR", "INR",
    "KRW", "UAH", "RUB",
}


def _finite(value, label):
    if isinstance(value, bool):
        raise ValueError(label + " must be finite")
    try:
        result = float(value)
    except (TypeError, ValueError, OverflowError) as exc:
        raise ValueError(label + " must be finite") from exc
    if not math.isfinite(result):
        raise ValueError(label + " must be finite")
    return result


def _metal_market(symbol, now_seconds):
    quote = fetch_spot(symbol, now_seconds)
    rows = fetch_daily_bars(symbol, now_seconds)
    return {
        "symbol": symbol, "asset": symbol, "rows": rows,
        "price": quote["price_usd"], "quality": "HEALTHY",
        "provider": quote["provider"],
        "quote_age_seconds": quote["quote_age_seconds"],
        "quote_timestamp": quote["computed_at"],
        "quote_delay_minutes": quote["expected_delay_minutes"],
        "history_interval": "1d",
        "history_bars": len(rows),
        "price_unit": quote["price_unit"],
        "latest_closed_candle": rows[-1][0],
    }


def _crypto_market(pair, now_seconds):
    query = urlencode({"pair": pair["altname"], "interval": 60})
    payload = fetch_json(KRAKEN_API + "/OHLC?" + query)
    key = next((name for name in payload if name != "last"), None)
    if key is None:
        raise ValueError("Kraken OHLC pair response missing")
    rows, quality = normalize_kraken_ohlc({"rows": payload[key]}, now_seconds)
    if len(rows) < 200:
        raise ValueError("Fewer than 200 completed hourly crypto candles")
    symbol = "BTC/USD" if pair["base"].upper() == "XBT" else pair["symbol"]
    return {
        "symbol": symbol, "asset": symbol, "rows": rows,
        "price": float(rows[-1][4]), "quality": "HEALTHY",
        "provider": "Kraken public spot market data",
        "quote_volume_24h_estimate": pair.get("quote_volume_24h_estimate", 0),
        "latest_closed_candle": rows[-1][0],
        "trade_allowed": _is_eligible_crypto_pair(pair),
    }


def _is_eligible_crypto_pair(pair):
    return (
        isinstance(pair, dict)
        and pair.get("quote") in {"USD", "USDT", "USDC"}
        and str(pair.get("base", "")).upper() not in EXCLUDED_BASES
        and str(pair.get("base", "")).upper() not in FIAT_BASES
    )


def _position_market_symbols(book):
    symbols = set()
    for position in book.state["positions"].values():
        symbols.add(position["asset"])
    return symbols


def _load_markets(book):
    now = datetime.now(timezone.utc).timestamp()
    universe = discover_kraken_universe()
    ranked, _ = rank_kraken_pairs(universe)
    eligible_pairs = [pair for pair in ranked if _is_eligible_crypto_pair(pair)]
    # Select up to 20 distinct crypto bases by liquidity across USD/stablecoin
    # quotes; avoid duplicate exposure to the same coin via multiple quote pairs.
    selected = []
    selected_bases = set()
    for pair in eligible_pairs:
        base = str(pair.get("base", "")).upper()
        if base in selected_bases:
            continue
        selected.append(pair)
        selected_bases.add(base)
        if len(selected) >= MAX_CRYPTO_MARKETS:
            break
    open_assets = _position_market_symbols(book)
    pair_by_symbol = {pair["symbol"]: pair for pair in universe if pair["quote"] in {"USD", "USDT", "USDC"}}
    # Kraken names Bitcoin XBT; the shared WHJ ledger uses the canonical BTC/USD label.
    xbt_pair = next((pair for pair in universe
                     if pair["base"].upper() == "XBT" and pair["quote"] == "USD"), None)
    if xbt_pair:
        pair_by_symbol["BTC/USD"] = xbt_pair
    required_crypto = {
        asset for asset in open_assets
        if isinstance(asset, str) and "/" in asset
    }
    for symbol in required_crypto:
        base = symbol.split("/", 1)[0]
        if symbol not in pair_by_symbol:
            raise RuntimeError("Cannot safely mark existing open position: " + symbol)
        if not any(p["symbol"] == symbol for p in selected):
            selected.append(pair_by_symbol[symbol])
    markets = {}
    errors = {}
    for index, pair in enumerate(selected):
        try:
            markets[pair["symbol"]] = _crypto_market(pair, now)
        except Exception as exc:
            errors[pair["symbol"]] = str(exc)[:250]
        if index < len(selected) - 1:
            time.sleep(0.35)
    required_metals = set(METALS) | {a for a in open_assets if a in ("XAUUSD", "XAGUSD")}
    for symbol in sorted(required_metals):
        try:
            markets[symbol] = _metal_market(symbol, now)
        except Exception as exc:
            errors[symbol] = str(exc)[:250]
    missing_open = sorted(open_assets - set(markets))
    if missing_open:
        raise RuntimeError(
            "Fail-closed: fresh marks unavailable for open positions: "
            + ", ".join(missing_open) + "; " + json.dumps(errors, sort_keys=True)
        )
    return markets, errors


def _liquidation_equity(book, marks):
    gross = book.snapshot(marks)
    exit_value = sum(
        float(position["units"]) * float(marks[position["asset"]])
        * (1.0 - SLIPPAGE_RATE) * (1.0 - FEE_RATE)
        for position in gross["open_positions"]
    )
    return float(gross["cash_usd"]) + exit_value


def _seed_market_state(rows):
    closes = [float(row[4]) for row in rows[-200:]]
    cursor = int(rows[-1][0])
    return {
        name: {
            "last_timestamp": cursor, "recent_closes": closes,
            "holding_bars": 0, "trades": 0,
        } for name in SUPPORTED_STRATEGIES
    }


def _market_position_id(symbol, strategy):
    safe = "".join(ch if ch.isalnum() else "_" for ch in symbol)
    return "multi-" + safe + "-" + strategy


def _risk_state(book, marks, risk, timestamp):
    equity = _liquidation_equity(book, marks)
    day = datetime.fromtimestamp(timestamp, timezone.utc).date().isoformat()
    if not risk:
        risk = {
            "peak_equity_usd": max(INITIAL_CASH, equity),
            "daily_bucket": day, "daily_start_equity_usd": equity,
            "daily_loss_paused": False, "drawdown_paused": False,
        }
    if day != risk.get("daily_bucket"):
        risk["daily_bucket"] = day
        risk["daily_start_equity_usd"] = equity
        risk["daily_loss_paused"] = False
    risk["peak_equity_usd"] = max(float(risk.get("peak_equity_usd", equity)), equity)
    peak = max(float(risk["peak_equity_usd"]), 1e-12)
    drawdown = max(0.0, (peak - equity) / peak)
    if drawdown >= MAX_DRAWDOWN:
        risk["drawdown_paused"] = True
    daily_start = max(float(risk.get("daily_start_equity_usd", equity)), 1e-12)
    if equity <= daily_start * (1.0 - DAILY_LOSS_LIMIT):
        risk["daily_loss_paused"] = True
    risk["equity_usd"] = round(equity, 8)
    risk["drawdown_pct"] = round(drawdown * 100.0, 4)
    return risk


def run_engine():
    book = SharedPaperPortfolio(LEDGER, initial_cash_usd=INITIAL_CASH, fee_rate=FEE_RATE)
    markets, errors = _load_markets(book)
    marks = {symbol: float(item["price"]) for symbol, item in markets.items()}
    # Existing BTC positions are marked from Kraken's USD spot feed, but BTC
    # entries remain owned by the original seven-strategy BTC engine.
    for asset in _position_market_symbols(book):
        if asset not in marks:
            raise RuntimeError("No current mark for open asset " + asset)

    market_state = book.state.get(STATE_KEY, {})
    if not isinstance(market_state, dict):
        raise ValueError("Multi-asset state is malformed; refusing reset")
    risk = book.state.get(RISK_KEY, {})
    events = []
    seeded = []
    processed_candles = 0

    for symbol, market in markets.items():
        if symbol == "BTC/USD":
            continue
        base = symbol.split("/", 1)[0].upper() if "/" in symbol else ""
        if base in EXCLUDED_BASES or base in FIAT_BASES:
            # Close legacy positions in stable/fiat base pairs at current validated marks.
            for position_id, position in list(book.state["positions"].items()):
                if position.get("asset") == symbol:
                    trade = book.close_position(
                        position_id, marks[symbol], reason="INELIGIBLE_STABLE_OR_FIAT_BASE"
                    )
                    events.append({
                        "event": "CLOSE", "market": symbol,
                        "strategy": position.get("strategy"),
                        "timestamp": int(time.time()),
                        "reason": "INELIGIBLE_STABLE_OR_FIAT_BASE",
                        "pnl_usd": trade.get("pnl_usd"),
                    })
            continue
        rows = market["rows"]
        state = market_state.get(symbol)
        if not isinstance(state, dict):
            market_state[symbol] = _seed_market_state(rows)
            seeded.append(symbol)
            continue
        for strategy in SUPPORTED_STRATEGIES:
            strategy_state = state.get(strategy)
            if not isinstance(strategy_state, dict):
                raise ValueError("Strategy cursor missing for " + symbol + "/" + strategy)
            for row in rows:
                timestamp, close = int(row[0]), float(row[4])
                if timestamp <= int(strategy_state["last_timestamp"]):
                    continue
                history = [float(x) for x in strategy_state["recent_closes"]]
                minimum_history = 20 if strategy == "sma_trend" else 50
                if len(history) < minimum_history:
                    strategy_state["recent_closes"] = (history + [close])[-200:]
                    strategy_state["last_timestamp"] = timestamp
                    continue
                risk = _risk_state(book, marks, risk, timestamp)
                want_long, want_flat = strategy_signal(
                    strategy, history, int(strategy_state.get("holding_bars", 0))
                )
                position_id = _market_position_id(symbol, strategy)
                position = book.state["positions"].get(position_id)
                paused = bool(risk.get("daily_loss_paused") or risk.get("drawdown_paused"))
                trade_allowed = market.get("trade_allowed", True)
                if position and (want_flat or paused or not trade_allowed):
                    exit_price = close * (1.0 - SLIPPAGE_RATE)
                    trade = book.close_position(position_id, exit_price)
                    events.append({"event": "CLOSE", "market": symbol, "strategy": strategy,
                                   "timestamp": timestamp, **trade})
                    strategy_state["trades"] = int(strategy_state.get("trades", 0)) + 1
                    strategy_state["holding_bars"] = 0
                elif not position and want_long and not paused and trade_allowed:
                    current = book.snapshot(marks)
                    equity = _liquidation_equity(book, marks)
                    exposure = sum(float(p["market_value_usd"]) for p in current["open_positions"])
                    capacity = max(0.0, equity * MAX_GROSS_EXPOSURE - exposure)
                    notional = min(
                        equity * TRADE_ALLOCATION,
                        capacity,
                        book.state["cash_usd"] / (1.0 + FEE_RATE),
                    )
                    if (len(current["open_positions"]) < MAX_OPEN_POSITIONS
                            and notional >= MIN_TRADE_USD):
                        approved = authorize_paper_entry(
                            symbol, market["quality"] == "HEALTHY",
                            {"signal": "BUY", "allocation_pct": TRADE_ALLOCATION * 100,
                             "risk_paused": paused},
                        )
                        if approved:
                            try:
                                opened = book.open_position(
                                    strategy, symbol, close * (1.0 + SLIPPAGE_RATE),
                                    notional, position_id,
                                )
                                events.append({"event": "OPEN", "market": symbol,
                                               "strategy": strategy, "timestamp": timestamp,
                                               **opened})
                            except ValueError as exc:
                                if "Insufficient shared cash" not in str(exc):
                                    raise
                if position and not (want_flat or paused) and strategy in (
                    "bollinger_mean_reversion", "rsi14_mean_reversion"
                ):
                    strategy_state["holding_bars"] = int(strategy_state.get("holding_bars", 0)) + 1
                strategy_state["recent_closes"] = (history + [close])[-200:]
                strategy_state["last_timestamp"] = timestamp
                processed_candles += 1

    # Metal execution requires timestamp-validated spot and validated daily OHLC.
    metal_status = {}
    quote_now = datetime.now(timezone.utc).timestamp()
    for symbol in (*METALS, "XCUUSD", "XPTUSD", "XPDUSD"):
        market = markets.get(symbol)
        if market:
            metal_status[symbol] = {
                "status": "PAPER_DAILY_READY", "paper_execution_enabled": True,
                "symbol": symbol, "provider": market.get("provider"),
                "last_price_usd": market.get("price"), "price_unit": market.get("price_unit"),
                "quote_age_seconds": market.get("quote_age_seconds"),
                "quote_timestamp": market.get("quote_timestamp"),
                "history_interval": "1d", "closed_daily_bars": market.get("history_bars", 0),
                "latest_closed_candle": market.get("latest_closed_candle"),
                "reason": None, "closed_trades": 0,
            }
            continue
        try:
            quote = fetch_spot(symbol, quote_now)
            metal_status[symbol] = {
                "status": "SPOT_ONLY_HISTORY_BLOCKED" if symbol == "XCUUSD" else "SPOT_ONLY_RESEARCH",
                "paper_execution_enabled": False, "symbol": symbol,
                "provider": quote.get("provider"), "last_price_usd": quote.get("price_usd"),
                "price_unit": quote.get("price_unit"), "quote_age_seconds": quote.get("quote_age_seconds"),
                "quote_timestamp": quote.get("computed_at"), "history_interval": None,
                "closed_daily_bars": 0, "latest_closed_candle": None, "closed_trades": 0,
                "reason": errors.get(symbol) or ("goldprice.dev free tier plan-gates HG daily OHLC" if symbol == "XCUUSD" else "No validated free daily OHLC feed for this metal"),
            }
        except Exception as exc:
            metal_status[symbol] = {
                "status": "FEED_BLOCKED", "paper_execution_enabled": False, "symbol": symbol,
                "provider": None, "last_price_usd": None, "price_unit": None,
                "quote_age_seconds": None, "quote_timestamp": None, "history_interval": None,
                "closed_daily_bars": 0, "latest_closed_candle": None, "closed_trades": 0,
                "reason": str(exc)[:250],
            }

    # Refresh risk using the latest marks and persist namespaced cursors without
    # replacing the original BTC strategy state in the same shared ledger.
    risk = _risk_state(book, marks, risk, int(datetime.now(timezone.utc).timestamp()))
    book.save_extension_state(STATE_KEY, market_state)
    book.save_extension_state(RISK_KEY, risk)

    snapshot = json.loads(SNAPSHOT.read_text(encoding="utf-8")) if SNAPSHOT.exists() else {}
    shared = book.snapshot(marks)
    gross_value = float(shared["market_value_usd"])
    net_value = sum(
        float(position["units"]) * float(marks[position["asset"]])
        * (1.0 - SLIPPAGE_RATE) * (1.0 - FEE_RATE)
        for position in shared["open_positions"]
    )
    shared["gross_market_value_usd"] = round(gross_value, 8)
    shared["estimated_exit_costs_usd"] = round(gross_value - net_value, 8)
    shared["market_value_usd"] = round(net_value, 8)
    shared["equity_usd"] = round(float(shared["cash_usd"]) + net_value, 8)
    shared["pnl_usd"] = round(float(shared["equity_usd"]) - INITIAL_CASH, 8)
    shared["live_trading_enabled"] = False
    snapshot.update({
        "updated_at": datetime.now(timezone.utc).isoformat(),
        "paper_only": True, "live_trading_enabled": False,
        "shared_portfolio": shared,
        "metals_paper": {
            "account_scope": "SHARED_100USD_PAPER", "paper_only": True,
            "live_trading_enabled": False, "spot_provider": "Gold-API",
            "daily_history_provider": "goldprice.dev", "markets": metal_status,
        },
        "gold": {
            **dict(snapshot.get("gold", {})),
            "asset": "XAUUSD", "symbol": "XAU/USD spot",
            "status": metal_status.get("XAUUSD", {}).get("status", "UNKNOWN"),
            "feed_status": metal_status.get("XAUUSD", {}).get("status", "UNKNOWN"),
            "account_scope": "SHARED_100USD_PAPER", "independent_ledger_enabled": False,
            "paper_execution_enabled": bool(metal_status.get("XAUUSD", {}).get("paper_execution_enabled")),
            "last_price_usd": metal_status.get("XAUUSD", {}).get("last_price_usd"),
            "quote_timestamp": metal_status.get("XAUUSD", {}).get("quote_timestamp"),
            "quote_age_seconds": metal_status.get("XAUUSD", {}).get("quote_age_seconds"),
            "history_interval": metal_status.get("XAUUSD", {}).get("history_interval"),
            "source": "Gold-API spot + goldprice.dev daily bars",
            "bid_usd_oz": None, "ask_usd_oz": None,
            "execution_model": "Shared $100 paper wallet; daily candles; no live broker bid/ask or orders",
            "legacy_sleeve_active": False,
            "shared_wallet_equity_usd": shared.get("equity_usd"),
            "shared_wallet_pnl_usd": shared.get("pnl_usd"),
            "shared_wallet_open_positions": [
                position for position in shared.get("open_positions", [])
                if position.get("asset") == "XAUUSD"
            ],
            "strategy_signal": "DAILY_PAPER_ENABLED" if metal_status.get("XAUUSD", {}).get("paper_execution_enabled") else "WATCH_ONLY",
            "entry_consensus": {
                "approved_by_consensus": False,
                "reason": "NO_ENTRY_EVENT_THIS_RUN" if metal_status.get("XAUUSD", {}).get("paper_execution_enabled") else "NO_VALIDATED_DAILY_FEED",
            },
            "new_trades": [
                event for event in events
                if event.get("market") == "XAUUSD" or event.get("asset") == "XAUUSD"
            ],
            "last_error": metal_status.get("XAUUSD", {}).get("reason"),
        },
        "notes": [
            "One shared simulated $100 wallet covers BTC, selected liquid crypto pairs, and validated XAU/XAG daily paper markets.",
            "Gold and silver use timestamp-validated Gold-API spot quotes plus completed goldprice.dev daily bars.",
            "Copper spot is monitored; free daily OHLC is plan-gated, so copper entries are blocked.",
            "Platinum and palladium are spot-only research; no validated free daily bars, so no paper entries.",
            "Legacy independent $10 BTC/Gold ledgers are not used by the active shared-wallet engine.",
            "No real exchange or broker orders are sent.",
        ],
        "multi_asset_paper": {
            "status": "PAPER_ONLY",
            "markets_scanned": sorted(markets),
            "markets_with_errors": errors,
            "seeded_markets": seeded,
            "processed_closed_candles": processed_candles,
            "events_this_run": events,
            "daily_loss_paused": bool(risk.get("daily_loss_paused")),
            "drawdown_paused": bool(risk.get("drawdown_paused")),
            "drawdown_pct": risk.get("drawdown_pct", 0),
            "max_open_positions": MAX_OPEN_POSITIONS,
            "trade_allocation_pct": TRADE_ALLOCATION * 100,
            "live_orders_enabled": False,
            "orders_submitted": False,
        },
    })
    SNAPSHOT.write_text(json.dumps(snapshot, indent=2, allow_nan=False) + "\n", encoding="utf-8")
    report = {
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "mode": "PAPER_ONLY", "live_trading_enabled": False,
        "initial_cash_usd": INITIAL_CASH,
        "cash_usd": shared["cash_usd"], "equity_usd": shared["equity_usd"],
        "pnl_usd": shared["pnl_usd"], "open_positions": len(shared["open_positions"]),
        "closed_trades": len(book.state["closed_trades"]),
        "markets": sorted(markets), "errors": errors,
        "seeded_markets": seeded, "processed_closed_candles": processed_candles,
        "events": events, "risk": risk,
        "orders_submitted": False,
    }
    REPORT.parent.mkdir(parents=True, exist_ok=True)
    REPORT.write_text(json.dumps(report, indent=2, allow_nan=False) + "\n", encoding="utf-8")
    print(json.dumps(report, indent=2, allow_nan=False))
    return report


if __name__ == "__main__":
    run_engine()
