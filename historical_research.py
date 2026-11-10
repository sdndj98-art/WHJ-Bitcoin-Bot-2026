"""Fetch an extended history of public BTC/USD hourly candles and run fixed-rule research.

Research only: no credentials, orders, or trading endpoints are used.
"""
import json
import math
import time
import urllib.error
import urllib.parse
import urllib.request
from bisect import bisect_left
from datetime import datetime, timezone
from pathlib import Path

from paper_account import seed_forward_paper_account, update_paper_account
from strategy_lab import run_strategy_lab

BASE_URL = "https://api.exchange.coinbase.com/products/BTC-USD/candles"
INTERVAL_MS = 60 * 60 * 1000
DAYS = 3000
FEE_RATE = 0.001
SLIPPAGE_RATE = 0.0005


def _iso_utc(timestamp_ms):
    return datetime.fromtimestamp(timestamp_ms / 1000, timezone.utc).isoformat(timespec="seconds")


def fetch_page(start_ms, end_ms):
    params = urllib.parse.urlencode({
        "granularity": 3600,
        "start": _iso_utc(start_ms),
        "end": _iso_utc(end_ms),
    })
    request = urllib.request.Request(
        BASE_URL + "?" + params,
        headers={
            "User-Agent": "WHJ-Bitcoin-Bot-Research/1.0",
            "Accept": "application/json",
        },
    )
    last_error = None
    for attempt in range(5):
        try:
            with urllib.request.urlopen(request, timeout=30) as response:
                payload = json.loads(response.read().decode("utf-8"))
            if not isinstance(payload, list):
                raise ValueError("Coinbase returned an unexpected candle payload")
            # Coinbase format: [time, low, high, open, close, volume].
            rows = []
            for item in payload:
                if not isinstance(item, list) or len(item) < 6:
                    raise ValueError("Malformed Coinbase historical candle")
                rows.append([
                    int(item[0]) * 1000,
                    float(item[3]),
                    float(item[2]),
                    float(item[1]),
                    float(item[4]),
                    float(item[5]),
                ])
            return rows
        except (urllib.error.URLError, TimeoutError, json.JSONDecodeError) as exc:
            last_error = exc
            time.sleep(min(2 ** attempt, 12))
    raise RuntimeError("Unable to download historical candles from Coinbase: " + str(last_error))

def load_two_year_candles(days=DAYS, now=None):
    now_ms = int((now or datetime.now(timezone.utc)).timestamp() * 1000)
    start_ms = (now_ms - days * 24 * INTERVAL_MS) // INTERVAL_MS * INTERVAL_MS
    rows = []
    cursor = start_ms
    # Coinbase caps hourly responses at 300 candles. Use 299-hour slices
    # to avoid truncation and keep inclusive boundaries unambiguous.
    while cursor < now_ms:
        page_end = min(cursor + 299 * INTERVAL_MS, now_ms)
        page = fetch_page(cursor, page_end)
        rows.extend(page)
        next_cursor = page_end + INTERVAL_MS
        if next_cursor <= cursor:
            raise ValueError("Historical API pagination did not advance")
        cursor = next_cursor
        time.sleep(0.2)

    if not rows:
        raise ValueError("No historical candles were downloaded")

    unique = {}
    for row in rows:
        if not isinstance(row, list) or len(row) < 6:
            raise ValueError("Malformed historical candle")
        timestamp = int(row[0])
        values = [float(row[i]) for i in (1, 2, 3, 4, 5)]
        if not all(math.isfinite(value) for value in values):
            raise ValueError("Non-finite OHLCV value in historical data")
        open_price, high, low, close, volume = values
        if min(open_price, high, low, close) <= 0 or volume < 0:
            raise ValueError("Non-positive OHLC price or negative volume")
        if high < max(open_price, close, low) or low > min(open_price, close, high):
            raise ValueError("Impossible OHLC candle relationship")
        unique[timestamp] = {
            "timestamp": timestamp,
            "open": open_price,
            "high": high,
            "low": low,
            "close": close,
            "volume": volume,
            "imputed": False,
        }

    observed = [unique[key] for key in sorted(unique)]
    # Drop any candle whose one-hour interval has not fully closed.
    cutoff = now_ms - (now_ms % INTERVAL_MS)
    observed = [row for row in observed if row["timestamp"] + INTERVAL_MS <= cutoff]
    if len(observed) < 1000:
        raise ValueError("Insufficient closed hourly candles for multi-regime research")

    # Coinbase may omit intervals with no reported trades. For short gaps only,
    # insert clearly-marked flat candles at the previous close with zero volume.
    # Large gaps are rejected instead of fabricating a long price path.
    candles = []
    imputed_count = 0
    for current in observed:
        if candles:
            previous = candles[-1]
            delta = current["timestamp"] - previous["timestamp"]
            if delta <= 0 or delta % INTERVAL_MS:
                raise ValueError("Historical candle timestamps are not aligned to hourly boundaries")
            missing = delta // INTERVAL_MS - 1
            if missing > 6:
                raise ValueError(
                    "Historical data gap exceeds the six-hour repair limit: "
                    + str({"after": previous["timestamp"], "before": current["timestamp"], "missing_hours": missing})
                )
            for offset in range(1, missing + 1):
                flat = previous["close"]
                candles.append({
                    "timestamp": previous["timestamp"] + offset * INTERVAL_MS,
                    "open": flat,
                    "high": flat,
                    "low": flat,
                    "close": flat,
                    "volume": 0.0,
                    "imputed": True,
                })
                imputed_count += 1
        candles.append(current)

    if len(candles) < 1000:
        raise ValueError("Insufficient hourly candles after data-quality repair")
    # Keep the imputation count available to the report without hiding it in prices.
    candles[0]["_imputed_hour_count"] = imputed_count
    return candles


def aggregate_candles(candles, hours):
    """Aggregate complete UTC-aligned hourly bars without using partial periods."""
    if isinstance(hours, bool) or not isinstance(hours, int) or hours < 1:
        raise ValueError("Aggregation hours must be a positive integer")
    span = hours * INTERVAL_MS
    groups = {}
    for row in candles:
        bucket = row["timestamp"] // span
        groups.setdefault(bucket, []).append(row)
    aggregated = []
    for bucket in sorted(groups):
        group = sorted(groups[bucket], key=lambda item: item["timestamp"])
        if len(group) != hours:
            continue
        expected_start = bucket * span
        if group[0]["timestamp"] != expected_start:
            continue
        if any(group[i]["timestamp"] != expected_start + i * INTERVAL_MS
               for i in range(hours)):
            continue
        aggregated.append({
            "timestamp": expected_start,
            "open": group[0]["open"],
            "high": max(item["high"] for item in group),
            "low": min(item["low"] for item in group),
            "close": group[-1]["close"],
            "volume": sum(item["volume"] for item in group),
            "imputed": any(item.get("imputed", False) for item in group),
        })
    if len(aggregated) < 200:
        raise ValueError(f"Not enough complete {hours}-hour bars for strategy comparison")
    return aggregated


def _blocked_execution_indices(bars):
    """Return indices of synthetic bars that may inform indicators but cannot fill."""
    return {
        index for index, row in enumerate(bars)
        if row.get("imputed", False)
    }


def _turtle_signals(bars, entry_period, exit_period, regime_period=None, atr_stop_multiple=None):
    """Create close-confirmed Donchian signals with an optional ATR trailing exit.

    ATR and the trailing stop are evaluated at the current completed close;
    any resulting position change is executed by the simulator at the next close.
    """
    if atr_stop_multiple is not None and (
        isinstance(atr_stop_multiple, bool)
        or not isinstance(atr_stop_multiple, (int, float))
        or not math.isfinite(atr_stop_multiple)
        or atr_stop_multiple <= 0
    ):
        raise ValueError("ATR stop multiple must be finite and positive")
    closes = [float(row["close"]) for row in bars]
    highs = [float(row["high"]) for row in bars]
    lows = [float(row["low"]) for row in bars]
    atr = [None] * len(bars)
    if atr_stop_multiple is not None:
        true_ranges = []
        for i in range(len(bars)):
            previous_close = closes[i - 1] if i else closes[i]
            true_ranges.append(max(highs[i] - lows[i], abs(highs[i] - previous_close), abs(lows[i] - previous_close)))
            if i >= 19:
                atr[i] = sum(true_ranges[i - 19:i + 1]) / 20
    regime_sma = [None] * len(bars)
    if regime_period:
        for i in range(regime_period - 1, len(bars)):
            regime_sma[i] = sum(closes[i - regime_period + 1:i + 1]) / regime_period
    signals = []
    in_position = False
    highest_close = 0.0
    for i, close in enumerate(closes):
        if in_position:
            if atr_stop_multiple is not None and atr[i] is not None:
                highest_close = max(highest_close, close)
                atr_exit = close < highest_close - atr_stop_multiple * atr[i]
            else:
                atr_exit = False
            exit_break = i >= exit_period and close < min(lows[i - exit_period:i])
            regime_exit = bool(regime_period and regime_sma[i] is not None and close < regime_sma[i])
            if exit_break or regime_exit or atr_exit:
                in_position = False
                highest_close = 0.0
        elif i >= entry_period:
            breakout = close > max(highs[i - entry_period:i])
            regime_ok = not regime_period or (regime_sma[i] is not None and close > regime_sma[i])
            if breakout and regime_ok:
                in_position = True
                highest_close = close
        signals.append(in_position)
    return signals


def _first_executable_index(bars, start, end):
    """Return the first real bar index in [start, end), or None."""
    return next(
        (index for index in range(max(0, start), min(len(bars), end))
         if not bars[index].get("imputed", False)),
        None,
    )


def _last_executable_index(bars, start, end):
    """Return the last real bar index in [start, end), or None."""
    return next(
        (index for index in range(min(len(bars), end) - 1, max(0, start) - 1, -1)
         if not bars[index].get("imputed", False)),
        None,
    )


def _simulate_ohlc(bars, signals, start, end, fee, slippage):
    cash = 1000.0
    units = 0.0
    entry_cost = 0.0
    trades = []
    peak = cash
    max_drawdown = 0.0
    for i in range(max(start, 1), end):
        price = float(bars[i]["close"])
        # Synthetic candles can update mark-to-market continuity, but cannot
        # open or close a simulated position.
        if not bars[i].get("imputed", False):
            want_long = signals[i - 1]
            if want_long and units == 0:
                allocation = cash * 0.25
                fill = price * (1 + slippage)
                fee_paid = allocation * fee
                units = (allocation - fee_paid) / fill
                cash -= allocation
                entry_cost = allocation
            elif not want_long and units > 0:
                fill = price * (1 - slippage)
                proceeds = units * fill
                proceeds -= proceeds * fee
                trades.append(proceeds - entry_cost)
                cash += proceeds
                units = 0.0
                entry_cost = 0.0
        # Drawdown uses estimated net liquidation value, including exit costs.
        if units > 0:
            liquidation = units * price * (1 - slippage)
            liquidation -= liquidation * fee
            equity = cash + liquidation
        else:
            equity = cash
        peak = max(peak, equity)
        if peak > 0:
            max_drawdown = max(max_drawdown, (peak - equity) / peak * 100)

    if units > 0:
        last_executable = _last_executable_index(bars, max(start, 1), end)
        terminal_price = (
            float(bars[last_executable]["close"])
            if last_executable is not None
            else float(bars[end - 1]["close"])
        )
        exit_value = units * terminal_price * (1 - slippage)
        exit_value -= exit_value * fee
        final_equity = cash + exit_value
    else:
        final_equity = cash
    wins = sum(1 for pnl in trades if pnl > 0)
    gross_profit = sum(pnl for pnl in trades if pnl > 0)
    gross_loss = -sum(pnl for pnl in trades if pnl < 0)
    return {
        "return_pct": round((final_equity / 1000 - 1) * 100, 2),
        "final_equity_usd": round(final_equity, 2),
        "max_drawdown_pct": round(max_drawdown, 2),
        "closed_trades": len(trades),
        "win_rate_pct": round(wins / len(trades) * 100, 2) if trades else 0.0,
        "profit_factor": round(gross_profit / gross_loss, 2) if gross_loss else (None if gross_profit else 0.0),
        "open_position": units > 0,
    }

def _simulate_equal_weight_multitimeframe(
    bar_sets, signal_sets, bar_hours, start_time_ms, end_time_ms, fee, slippage
):
    """Combine independent native-timeframe sleeves on one time-aligned equity curve."""
    if not bar_sets or len(bar_sets) != len(signal_sets) or len(bar_sets) != len(bar_hours):
        raise ValueError("Bar, signal, and timeframe collections must have equal non-zero lengths")
    if not 0 <= fee < 1 or not 0 <= slippage < 1:
        raise ValueError("Fee and slippage must be between 0 and 1")

    initial_per_sleeve = 1000.0 / len(bar_sets)
    sleeve_final_equities = []
    sleeve_open_positions = []
    all_trades = []
    curve_events = []

    for sleeve_index, (bars, signals, hours) in enumerate(zip(bar_sets, signal_sets, bar_hours)):
        if len(bars) != len(signals):
            raise ValueError("Every sleeve signal series must match its native bar count")
        close_times = [
            int(row["timestamp"]) + int(hours) * 60 * 60 * 1000
            for row in bars
        ]
        start_index = bisect_left(close_times, start_time_ms)
        end_index = bisect_left(close_times, end_time_ms)
        if end_index <= start_index:
            sleeve_final_equities.append(initial_per_sleeve)
            sleeve_open_positions.append(False)
            continue

        cash = initial_per_sleeve
        units = 0.0
        entry_cost = 0.0
        trades = []
        for index in range(max(start_index, 1), end_index):
            price = float(bars[index]["close"])
            if not bars[index].get("imputed", False):
                want_long = bool(signals[index - 1])
                if want_long and units == 0:
                    allocation = cash * 0.25
                    fill = price * (1 + slippage)
                    fee_paid = allocation * fee
                    units = (allocation - fee_paid) / fill
                    cash -= allocation
                    entry_cost = allocation
                elif not want_long and units > 0:
                    fill = price * (1 - slippage)
                    proceeds = units * fill
                    proceeds -= proceeds * fee
                    trades.append(proceeds - entry_cost)
                    cash += proceeds
                    units = 0.0
                    entry_cost = 0.0

            if units > 0:
                liquidation = units * price * (1 - slippage)
                liquidation -= liquidation * fee
                equity = cash + liquidation
            else:
                equity = cash
            curve_events.append((close_times[index], sleeve_index, equity))

        if units > 0:
            last_executable = _last_executable_index(bars, max(start_index, 1), end_index)
            terminal_price = (
                float(bars[last_executable]["close"])
                if last_executable is not None
                else float(bars[end_index - 1]["close"])
            )
            exit_value = units * terminal_price * (1 - slippage)
            exit_value -= exit_value * fee
            final_equity = cash + exit_value
        else:
            final_equity = cash
        sleeve_final_equities.append(final_equity)
        sleeve_open_positions.append(units > 0)
        all_trades.extend(trades)

    curve_events.sort(key=lambda item: (item[0], item[1]))
    sleeve_equities = [initial_per_sleeve] * len(bar_sets)
    portfolio_peak = 1000.0
    max_drawdown = 0.0
    event_index = 0
    while event_index < len(curve_events):
        timestamp = curve_events[event_index][0]
        while event_index < len(curve_events) and curve_events[event_index][0] == timestamp:
            _, sleeve_index, equity = curve_events[event_index]
            sleeve_equities[sleeve_index] = equity
            event_index += 1
        portfolio_equity = sum(sleeve_equities)
        portfolio_peak = max(portfolio_peak, portfolio_equity)
        if portfolio_peak > 0:
            max_drawdown = max(
                max_drawdown,
                (portfolio_peak - portfolio_equity) / portfolio_peak * 100.0,
            )

    final_equity = sum(sleeve_final_equities)
    wins = [pnl for pnl in all_trades if pnl > 0]
    losses = [-pnl for pnl in all_trades if pnl < 0]
    gross_profit = sum(wins)
    gross_loss = sum(losses)
    return {
        "return_pct": round((final_equity / 1000.0 - 1.0) * 100.0, 2),
        "final_equity_usd": round(final_equity, 2),
        "max_drawdown_pct": round(max_drawdown, 2),
        "closed_trades": len(all_trades),
        "win_rate_pct": round(len(wins) / len(all_trades) * 100.0, 2) if all_trades else 0.0,
        "profit_factor": round(gross_profit / gross_loss, 2) if gross_loss else (None if gross_profit else 0.0),
        "open_position": any(sleeve_open_positions),
        "sleeve_count": len(bar_sets),
        "allocation_per_sleeve_pct": round(100.0 / len(bar_sets), 2),
    }



def run_ohlc_breakout_lab(bars, fee=FEE_RATE, slippage=SLIPPAGE_RATE):
    """Evaluate classic Turtle-style breakouts on true OHLC bars."""
    if len(bars) < 500:
        raise ValueError("At least 500 OHLC bars are required for breakout research")
    for row in bars:
        values = [row.get(key) for key in ("open", "high", "low", "close", "volume")]
        if any(isinstance(value, bool) or not isinstance(value, (int, float))
               or not math.isfinite(value) for value in values):
            raise ValueError("Breakout research requires finite numeric OHLCV bars")
        if min(values[:4]) <= 0 or values[4] < 0:
            raise ValueError("Breakout research requires positive prices and non-negative volume")
        if row["high"] < max(row["open"], row["close"], row["low"]):
            raise ValueError("Invalid OHLC high")
        if row["low"] > min(row["open"], row["close"], row["high"]):
            raise ValueError("Invalid OHLC low")
    if not 0 <= fee < 1 or not 0 <= slippage < 1:
        raise ValueError("Fee and slippage must be between 0 and 1")

    split = int(len(bars) * 0.7)
    # Predeclared Turtle/Donchian family: short, classic, and slower
    # horizons plus a small set of fixed regime/ATR variants. These are
    # research candidates, not a parameter sweep for in-sample optimization.
    strategies = {
        "donchian_10_5": (10, 5, None, None),
        "donchian_20_10": (20, 10, None, None),
        "donchian_40_20": (40, 20, None, None),
        "donchian_55_20": (55, 20, None, None),
        "donchian_100_50": (100, 50, None, None),
        "donchian_20_10_sma200": (20, 10, 200, None),
        "donchian_55_20_sma200": (55, 20, 200, None),
        "donchian_100_50_sma200": (100, 50, 200, None),
        "donchian_55_20_atr2_5_trailing": (55, 20, None, 2.5),
        "donchian_55_20_atr3_trailing": (55, 20, None, 3.0),
        "donchian_55_20_atr4_trailing": (55, 20, None, 4.0),
        "donchian_55_20_sma200_atr3_trailing": (55, 20, 200, 3.0),
    }
    results = {}
    for name, (entry, exit_period, regime, atr_multiple) in strategies.items():
        signals = _turtle_signals(bars, entry, exit_period, regime, atr_multiple)
        warmup = max(entry, regime or 0, 20 if atr_multiple is not None else 0)
        walk_start = split
        edges = [walk_start + ((len(bars) - walk_start) * k) // 3 for k in range(4)]
        windows = []
        for fold in range(3):
            start, end = edges[fold], edges[fold + 1]
            if end > start:
                windows.append({
                    "window": fold + 1,
                    "start_index": start,
                    "end_index_exclusive": end,
                    "metrics": _simulate_ohlc(bars, signals, start, end, fee, slippage),
                })
        returns = [window["metrics"]["return_pct"] for window in windows]
        results[name] = {
            "in_sample": _simulate_ohlc(bars, signals, warmup, split, fee, slippage),
            "out_of_sample": _simulate_ohlc(bars, signals, split, len(bars), fee, slippage),
            "walk_forward_windows": windows,
            "worst_window_return_pct": min(returns) if returns else None,
        }

    benchmark_entry_index = _first_executable_index(bars, split, len(bars))
    benchmark_exit_index = (
        _last_executable_index(bars, benchmark_entry_index, len(bars))
        if benchmark_entry_index is not None else None
    )
    benchmark_cash = 750.0
    benchmark_units = 0.0
    peak = 1000.0
    max_drawdown = 0.0
    if benchmark_entry_index is not None and benchmark_exit_index is not None:
        benchmark_units = (250.0 * (1 - fee)) / (
            float(bars[benchmark_entry_index]["close"]) * (1 + slippage)
        )
        for row in bars[benchmark_entry_index:]:
            liquidation = benchmark_units * float(row["close"]) * (1 - slippage)
            liquidation -= liquidation * fee
            equity = benchmark_cash + liquidation
            peak = max(peak, equity)
            max_drawdown = max(max_drawdown, (peak - equity) / peak * 100)
        exit_value = benchmark_units * float(bars[benchmark_exit_index]["close"]) * (1 - slippage)
        exit_value -= exit_value * fee
        benchmark_equity = benchmark_cash + exit_value
    else:
        benchmark_cash = 1000.0
        benchmark_equity = 1000.0
    results["buy_and_hold_25pct"] = {
        "out_of_sample": {
            "return_pct": round((benchmark_equity / 1000 - 1) * 100, 2),
            "final_equity_usd": round(benchmark_equity, 2),
            "max_drawdown_pct": round(max_drawdown, 2),
            "closed_trades": 1,
            "win_rate_pct": 100.0 if benchmark_equity > 1000 else 0.0,
            "profit_factor": None,
            "open_position": False,
            "fees_and_slippage_included": True,
            "allocation_fraction": 0.25,
            "entry_index": benchmark_entry_index,
            "exit_index": benchmark_exit_index,
        }
    }
    # Cost sensitivity reruns the identical fixed signals at progressively
    # harsher execution costs; it does not retune parameters for each scenario.
    cost_sensitivity = {}
    for multiplier in (1.0, 1.5, 2.0, 3.0):
        scenario_fee = fee * multiplier
        scenario_slippage = slippage * multiplier
        if scenario_fee >= 1 or scenario_slippage >= 1:
            raise ValueError("Cost sensitivity multiplier produces invalid execution costs")
        benchmark_allocation = 250.0
        benchmark_cash_scenario = 750.0
        if benchmark_entry_index is not None and benchmark_exit_index is not None:
            benchmark_units_scenario = (
                benchmark_allocation * (1 - scenario_fee)
                / (float(bars[benchmark_entry_index]["close"]) * (1 + scenario_slippage))
            )
            benchmark_exit = (
                benchmark_units_scenario * float(bars[benchmark_exit_index]["close"])
                * (1 - scenario_slippage)
            )
            benchmark_exit -= benchmark_exit * scenario_fee
            benchmark_return = round(
                ((benchmark_cash_scenario + benchmark_exit) / 1000.0 - 1) * 100, 2
            )
        else:
            benchmark_return = 0.0
        scenario_strategies = {}
        for name, (entry, exit_period, regime, atr_multiple) in strategies.items():
            signals = _turtle_signals(bars, entry, exit_period, regime, atr_multiple)
            metrics = _simulate_ohlc(
                bars, signals, split, len(bars), scenario_fee, scenario_slippage
            )
            scenario_strategies[name] = {
                **metrics,
                "benchmark_return_pct": benchmark_return,
                "benchmark_edge_pp": round(metrics["return_pct"] - benchmark_return, 2),
            }
        cost_sensitivity[f"{multiplier:g}x"] = {
            "cost_multiplier": multiplier,
            "fee_rate_each_side": scenario_fee,
            "slippage_rate_each_side": scenario_slippage,
            "matched_buy_and_hold_return_pct": benchmark_return,
            "strategies": scenario_strategies,
        }

    return {
        "mode": "OHLC_DONCHIAN_CHRONOLOGICAL_HOLDOUT",
        "sample_count": len(bars),
        "split_index": split,
        "execution": "Prior completed candle breakout signal; next executable close fill; imputed synthetic bars are blocked from entry and exit fills; 25% allocation; fees and slippage included.",
        "note": "Donchian channel bounds use prior highs/lows only; SMA200 regime uses completed daily closes.",
        "cost_sensitivity": cost_sensitivity,
        "cost_sensitivity_note": "Fixed signals are replayed without retuning at 1x, 1.5x, 2x, and 3x the supplied fee/slippage assumptions; benchmark edge is relative to matched 25% buy-and-hold under identical costs.",
        "strategies": results,
    }


def _ema_series(values, period):
    alpha = 2.0 / (period + 1.0)
    result = []
    current = float(values[0])
    result.append(current)
    for value in values[1:]:
        current = alpha * float(value) + (1 - alpha) * current
        result.append(current)
    return result


def _rsi_series(values, period=14):
    """Wilder RSI using only current and prior completed closes."""
    if period < 2 or len(values) <= period:
        raise ValueError("RSI requires a period of at least 2 and more observations than the period")
    result = [None] * len(values)
    gains = [0.0] * len(values)
    losses = [0.0] * len(values)
    for index in range(1, len(values)):
        change = float(values[index]) - float(values[index - 1])
        gains[index] = max(change, 0.0)
        losses[index] = max(-change, 0.0)
    average_gain = sum(gains[1:period + 1]) / period
    average_loss = sum(losses[1:period + 1]) / period
    result[period] = 100.0 if average_loss == 0 and average_gain else (50.0 if average_loss == 0 else 100.0 - 100.0 / (1.0 + average_gain / average_loss))
    for index in range(period + 1, len(values)):
        average_gain = (average_gain * (period - 1) + gains[index]) / period
        average_loss = (average_loss * (period - 1) + losses[index]) / period
        result[index] = 100.0 if average_loss == 0 else 100.0 - 100.0 / (1.0 + average_gain / average_loss)
    return result

def _atr_series(bars, period=14):
    """Wilder ATR from completed OHLC bars; no future bars are read."""
    if period < 2 or len(bars) <= period:
        raise ValueError("ATR requires a period of at least 2 and more bars than the period")
    true_ranges = [0.0] * len(bars)
    for index in range(1, len(bars)):
        high = float(bars[index]["high"])
        low = float(bars[index]["low"])
        previous_close = float(bars[index - 1]["close"])
        true_ranges[index] = max(high - low, abs(high - previous_close), abs(low - previous_close))
    result = [None] * len(bars)
    current = sum(true_ranges[1:period + 1]) / period
    result[period] = current
    for index in range(period + 1, len(bars)):
        current = (current * (period - 1) + true_ranges[index]) / period
        result[index] = current
    return result

def _regime_switching_atr_signals(four_hour, daily, daily_sma200):
    """Bull-long / bear-short trend with a 3x ATR trailing stop.

    Every 4h bar uses only the previous fully closed daily bar for regime
    classification. Stops are evaluated at the current completed 4h close;
    fills are modeled at the next 4h close.
    """
    closes = [float(row["close"]) for row in four_hour]
    ema20 = _ema_series(closes, 20)
    ema50 = _ema_series(closes, 50)
    atr14 = _atr_series(four_hour, 14)
    daily_closes = [float(row["close"]) for row in daily]
    daily_index = {row["timestamp"] // 86400000: i for i, row in enumerate(daily)}
    signals = []
    direction = 0
    extreme = None
    blocked_direction = 0
    for index, row in enumerate(four_hour):
        day_index = row["timestamp"] // 86400000
        previous_day = daily_index.get(day_index - 1)
        regime = 0
        if previous_day is not None and previous_day >= 219:
            average = daily_sma200[previous_day]
            prior_average = daily_sma200[previous_day - 20]
            if average is not None and prior_average is not None:
                if daily_closes[previous_day] > average and average > prior_average:
                    regime = 1
                elif daily_closes[previous_day] < average and average < prior_average:
                    regime = -1
        if regime == 1:
            desired = 1 if ema20[index] > ema50[index] and closes[index] > ema50[index] else 0
        elif regime == -1:
            desired = -1 if ema20[index] < ema50[index] and closes[index] < ema50[index] else 0
        else:
            desired = 0
        if blocked_direction and desired != blocked_direction:
            blocked_direction = 0
        if direction == 0:
            if desired and desired != blocked_direction and atr14[index] is not None:
                direction = desired
                extreme = closes[index]
        elif direction == 1:
            extreme = max(extreme, closes[index])
            if desired != 1:
                direction = 0
                extreme = None
            elif atr14[index] is not None and closes[index] < extreme - 3.0 * atr14[index]:
                direction = 0
                extreme = None
                blocked_direction = 1
        elif direction == -1:
            extreme = min(extreme, closes[index])
            if desired != -1:
                direction = 0
                extreme = None
            elif atr14[index] is not None and closes[index] > extreme + 3.0 * atr14[index]:
                direction = 0
                extreme = None
                blocked_direction = -1
        signals.append(direction)
    return signals


def run_daily_regime_filter_lab(hourly_candles, fee=FEE_RATE, slippage=SLIPPAGE_RATE, funding_rate_per_8h=0.00005):
    """Test 4h entries gated by the previous fully closed daily SMA200 regime."""
    four_hour = aggregate_candles(hourly_candles, 4)
    daily = aggregate_candles(hourly_candles, 24)
    if len(four_hour) < 500 or len(daily) < 200:
        raise ValueError("Insufficient bars for multi-timeframe regime research")
    if not 0 <= fee < 1 or not 0 <= slippage < 1:
        raise ValueError("Fee and slippage must be between 0 and 1")
    if not math.isfinite(funding_rate_per_8h) or funding_rate_per_8h < 0:
        raise ValueError("Funding rate must be finite and non-negative")

    daily_closes = [float(row["close"]) for row in daily]
    daily_sma200 = [None] * len(daily)
    for i in range(199, len(daily)):
        daily_sma200[i] = sum(daily_closes[i - 199:i + 1]) / 200
    daily_index = {row["timestamp"] // 86400000: i for i, row in enumerate(daily)}

    closes = [float(row["close"]) for row in four_hour]
    ema20 = _ema_series(closes, 20)
    ema50 = _ema_series(closes, 50)
    ema200 = _ema_series(closes, 200)
    rsi14 = _rsi_series(closes, 14)
    atr14 = _atr_series(four_hour, 14)
    sma20 = [None] * len(closes)
    sma50 = [None] * len(closes)
    for i in range(19, len(closes)):
        sma20[i] = sum(closes[i - 19:i + 1]) / 20
    for i in range(49, len(closes)):
        sma50[i] = sum(closes[i - 49:i + 1]) / 50

    signals = {
        "ema50_200_with_daily_sma200": [],
        "ema20_50_with_daily_sma200": [],
        "ema20_50_daily_sma200_rsi50": [],
        "ema20_50_daily_sma200_rsi50_rising": [],
        "ema20_50_daily_sma200_ema20_exit": [],
        "ema20_50_daily_sma200_rsi45_exit": [],
        "ema20_50_daily_sma200_atr3_trailing": [],
        "regime_switching_atr3_long_short": [],
        "sma20_50_with_daily_sma200": [],
    }
    for i, row in enumerate(four_hour):
        day_index = row["timestamp"] // 86400000
        previous_day = daily_index.get(day_index - 1)
        daily_regime = bool(
            previous_day is not None
            and daily_sma200[previous_day] is not None
            and daily_closes[previous_day] > daily_sma200[previous_day]
        )
        signals["ema50_200_with_daily_sma200"].append(
            bool(i >= 199 and daily_regime and ema50[i] > ema200[i] and closes[i] > ema200[i])
        )
        signals["ema20_50_with_daily_sma200"].append(
            bool(i >= 49 and daily_regime and ema20[i] > ema50[i] and closes[i] > ema50[i])
        )
        rsi_confirmed = bool(rsi14[i] is not None and rsi14[i] >= 50.0)
        rsi_rising = bool(
            i >= 17 and rsi14[i] is not None and rsi14[i - 3] is not None
            and rsi14[i] > rsi14[i - 3]
        )
        trend_setup = bool(
            i >= 49 and daily_regime and ema20[i] > ema50[i]
            and closes[i] > ema50[i]
        )
        signals["ema20_50_daily_sma200_rsi50"].append(bool(trend_setup and rsi_confirmed))
        signals["ema20_50_daily_sma200_rsi50_rising"].append(
            bool(trend_setup and rsi_confirmed and rsi_rising)
        )
        # Stateful exit variants keep the base trend entry but test earlier,
        # predeclared exit conditions to reduce exposure during weakening trends.
        if i == 0:
            ema20_exit_position = False
            rsi_exit_position = False
        if not ema20_exit_position and trend_setup:
            ema20_exit_position = True
        elif ema20_exit_position and (
            not daily_regime or closes[i] < ema20[i] or ema20[i] < ema50[i]
        ):
            ema20_exit_position = False
        if not rsi_exit_position and trend_setup:
            rsi_exit_position = True
        elif rsi_exit_position and (
            not daily_regime or (rsi14[i] is not None and rsi14[i] < 45.0)
            or ema20[i] < ema50[i]
        ):
            rsi_exit_position = False
        signals["ema20_50_daily_sma200_ema20_exit"].append(ema20_exit_position)
        signals["ema20_50_daily_sma200_rsi45_exit"].append(rsi_exit_position)
        if i == 0:
            atr_trailing_position = False
            atr_trailing_peak = None
        if not atr_trailing_position and trend_setup and atr14[i] is not None:
            atr_trailing_position = True
            atr_trailing_peak = closes[i]
        elif atr_trailing_position:
            atr_trailing_peak = max(atr_trailing_peak, closes[i])
            if (
                not daily_regime or atr14[i] is None
                or closes[i] < atr_trailing_peak - 3.0 * atr14[i]
            ):
                atr_trailing_position = False
                atr_trailing_peak = None
        signals["ema20_50_daily_sma200_atr3_trailing"].append(atr_trailing_position)
        signals["sma20_50_with_daily_sma200"].append(
            bool(sma20[i] is not None and sma50[i] is not None
                 and daily_regime and closes[i] > sma20[i] > sma50[i])
        )

    signals["regime_switching_atr3_long_short"] = _regime_switching_atr_signals(
        four_hour, daily, daily_sma200
    )
    split = int(len(four_hour) * 0.7)
    edges = [split + ((len(four_hour) - split) * k) // 3 for k in range(4)]
    results = {}
    for name, signal in signals.items():
        windows = []
        for fold in range(3):
            start, end = edges[fold], edges[fold + 1]
            if end > start:
                windows.append({
                    "window": fold + 1,
                    "start_index": start,
                    "end_index_exclusive": end,
                    "metrics": (
                        _simulate_long_short(
                            four_hour, signal, start, end, fee, slippage,
                            funding_rate_per_8h, bar_hours=4,
                        ) if name == "regime_switching_atr3_long_short"
                        else _simulate_ohlc(four_hour, signal, start, end, fee, slippage)
                    ),
                })
        returns = [window["metrics"]["return_pct"] for window in windows]
        results[name] = {
            "in_sample": (
                _simulate_long_short(
                    four_hour, signal, 200, split, fee, slippage,
                    funding_rate_per_8h, bar_hours=4,
                ) if name == "regime_switching_atr3_long_short"
                else _simulate_ohlc(four_hour, signal, 200, split, fee, slippage)
            ),
            "out_of_sample": (
                _simulate_long_short(
                    four_hour, signal, split, len(four_hour), fee, slippage,
                    funding_rate_per_8h, bar_hours=4,
                ) if name == "regime_switching_atr3_long_short"
                else _simulate_ohlc(four_hour, signal, split, len(four_hour), fee, slippage)
            ),
            "walk_forward_windows": windows,
            "worst_window_return_pct": min(returns) if returns else None,
        }
    benchmark = _simulate_ohlc(four_hour, [True] * len(four_hour), split, len(four_hour), fee, slippage)
    benchmark["profit_factor"] = None
    benchmark["closed_trades"] = 1
    benchmark["open_position"] = False
    benchmark["win_rate_pct"] = 100.0 if benchmark["return_pct"] > 0 else 0.0
    results["buy_and_hold_25pct"] = {"out_of_sample": benchmark}
    return {
        "mode": "FOUR_HOUR_ENTRY_WITH_PRIOR_DAILY_REGIME",
        "bar_count": len(four_hour),
        "daily_bar_count": len(daily),
        "split_index": split,
        "execution": "4h signals use the previous fully closed daily SMA200; fills occur at the next 4h close. The regime-switching candidate uses unlevered 25% notional and modeled funding.",
        "funding_rate_per_8h_assumption": funding_rate_per_8h,
        "strategies": results,
    }


def run_multi_timeframe_ensemble_lab(hourly_candles, fee=FEE_RATE, slippage=SLIPPAGE_RATE):
    """Test 4h EMA50/200 entries confirmed by the last fully closed 6h EMA50/200 regime."""
    four_hour = aggregate_candles(hourly_candles, 4)
    six_hour = aggregate_candles(hourly_candles, 6)
    if len(four_hour) < 500 or len(six_hour) < 200:
        raise ValueError("Insufficient bars for 4h/6h consensus research")
    if not 0 <= fee < 1 or not 0 <= slippage < 1:
        raise ValueError("Fee and slippage must be between 0 and 1")

    closes_4h = [float(row["close"]) for row in four_hour]
    closes_6h = [float(row["close"]) for row in six_hour]
    ema50_4h = _ema_series(closes_4h, 50)
    ema200_4h = _ema_series(closes_4h, 200)
    ema50_6h = _ema_series(closes_6h, 50)
    ema200_6h = _ema_series(closes_6h, 200)
    signal_4h = [
        bool(index >= 199 and ema50_4h[index] > ema200_4h[index]
             and closes_4h[index] > ema200_4h[index])
        for index in range(len(four_hour))
    ]
    signal_6h = [
        bool(index >= 199 and ema50_6h[index] > ema200_6h[index]
             and closes_6h[index] > ema200_6h[index])
        for index in range(len(six_hour))
    ]

    # 4h candle timestamps identify their open. At its close, use only a 6h
    # candle whose end timestamp is <= the 4h candle end; never use a forming 6h bar.
    six_hour_close_ms = [int(row["timestamp"]) + 6 * 60 * 60 * 1000 for row in six_hour]
    consensus = []
    signal_6h_on_4h = []
    six_index = -1
    for index, row in enumerate(four_hour):
        four_hour_close_ms = int(row["timestamp"]) + 4 * 60 * 60 * 1000
        while (
            six_index + 1 < len(six_hour_close_ms)
            and six_hour_close_ms[six_index + 1] <= four_hour_close_ms
        ):
            six_index += 1
        confirmation = bool(six_index >= 0 and signal_6h[six_index])
        signal_6h_on_4h.append(confirmation)
        consensus.append(bool(signal_4h[index] and confirmation))

    split = int(len(four_hour) * 0.7)
    edges = [split + ((len(four_hour) - split) * k) // 3 for k in range(4)]
    windows = []
    for fold in range(3):
        start, end = edges[fold], edges[fold + 1]
        if end > start:
            windows.append({
                "window": fold + 1,
                "start_index": start,
                "end_index_exclusive": end,
                "metrics": _simulate_ohlc(four_hour, consensus, start, end, fee, slippage),
            })
    returns = [window["metrics"]["return_pct"] for window in windows]
    candidate = {
        "in_sample": _simulate_ohlc(four_hour, consensus, 200, split, fee, slippage),
        "out_of_sample": _simulate_ohlc(four_hour, consensus, split, len(four_hour), fee, slippage),
        "walk_forward_windows": windows,
        "worst_window_return_pct": min(returns) if returns else None,
    }
    benchmark = _simulate_ohlc(
        four_hour, [True] * len(four_hour), split, len(four_hour), fee, slippage
    )
    benchmark["profit_factor"] = None
    benchmark["closed_trades"] = 1
    benchmark["open_position"] = False
    benchmark["win_rate_pct"] = 100.0 if benchmark["return_pct"] > 0 else 0.0
    close_times_4h = [
        int(row["timestamp"]) + 4 * 60 * 60 * 1000 for row in four_hour
    ]
    close_times_6h = [
        int(row["timestamp"]) + 6 * 60 * 60 * 1000 for row in six_hour
    ]
    split_4h = int(len(four_hour) * 0.7)
    portfolio_oos_start = close_times_4h[split_4h]
    portfolio_oos_end = close_times_4h[-1] + 1
    portfolio_edges = [
        portfolio_oos_start + ((portfolio_oos_end - portfolio_oos_start) * k) // 3
        for k in range(4)
    ]
    portfolio_windows = []
    for fold in range(3):
        start_time, end_time = portfolio_edges[fold], portfolio_edges[fold + 1]
        if end_time > start_time:
            portfolio_windows.append({
                "window": fold + 1,
                "start_time_ms": start_time,
                "end_time_ms_exclusive": end_time,
                "metrics": _simulate_equal_weight_multitimeframe(
                    [four_hour, six_hour], [signal_4h, signal_6h], [4, 6],
                    start_time, end_time, fee, slippage,
                ),
            })
    portfolio_returns = [window["metrics"]["return_pct"] for window in portfolio_windows]
    portfolio_is_start = max(close_times_4h[200], close_times_6h[200])
    portfolio_is_end = close_times_4h[split_4h]
    portfolio_candidate = {
        "in_sample": _simulate_equal_weight_multitimeframe(
            [four_hour, six_hour], [signal_4h, signal_6h], [4, 6],
            portfolio_is_start, portfolio_is_end, fee, slippage,
        ),
        "out_of_sample": _simulate_equal_weight_multitimeframe(
            [four_hour, six_hour], [signal_4h, signal_6h], [4, 6],
            portfolio_oos_start, portfolio_oos_end, fee, slippage,
        ),
        "walk_forward_windows": portfolio_windows,
        "worst_window_return_pct": min(portfolio_returns) if portfolio_returns else None,
    }
    # Match the 50/50 portfolio with a 50/50 native-timeframe benchmark.
    # Comparing it with the 4h-only benchmark would misstate its qualification.
    portfolio_benchmark = _simulate_equal_weight_multitimeframe(
        [four_hour, six_hour],
        [[True] * len(four_hour), [True] * len(six_hour)],
        [4, 6],
        portfolio_oos_start,
        portfolio_oos_end,
        fee,
        slippage,
    )
    portfolio_benchmark["profit_factor"] = None
    portfolio_benchmark["closed_trades"] = 1
    portfolio_benchmark["open_position"] = False
    portfolio_benchmark["win_rate_pct"] = (
        100.0 if portfolio_benchmark["return_pct"] > 0 else 0.0
    )

    # Replay fixed signals under progressively higher fees/slippage.
    cost_sensitivity = {}
    for multiplier in (1.0, 1.5, 2.0, 3.0):
        scenario_fee = fee * multiplier
        scenario_slippage = slippage * multiplier
        if scenario_fee >= 1 or scenario_slippage >= 1:
            raise ValueError("Cost sensitivity multiplier produces invalid execution costs")
        scenario_portfolio = _simulate_equal_weight_multitimeframe(
            [four_hour, six_hour], [signal_4h, signal_6h], [4, 6],
            portfolio_oos_start, portfolio_oos_end,
            scenario_fee, scenario_slippage,
        )
        scenario_benchmark = _simulate_equal_weight_multitimeframe(
            [four_hour, six_hour],
            [[True] * len(four_hour), [True] * len(six_hour)],
            [4, 6],
            portfolio_oos_start, portfolio_oos_end,
            scenario_fee, scenario_slippage,
        )
        cost_sensitivity[f"{multiplier:g}x"] = {
            "cost_multiplier": multiplier,
            "fee_rate_each_side": scenario_fee,
            "slippage_rate_each_side": scenario_slippage,
            "portfolio_50_50": {
                **scenario_portfolio,
                "benchmark_return_pct": scenario_benchmark["return_pct"],
                "benchmark_edge_pp": round(
                    scenario_portfolio["return_pct"] - scenario_benchmark["return_pct"], 2
                ),
            },
        }

    return {
        "mode": "FOUR_HOUR_SIX_HOUR_CONSENSUS_AND_NATIVE_TIMEFRAME_PORTFOLIO",
        "bar_count_4h": len(four_hour),
        "bar_count_6h": len(six_hour),
        "split_index": split,
        "execution": (
            "Consensus uses the most recent fully closed 6h regime to confirm each completed 4h signal. "
            "The 50/50 portfolio blend executes each 4h and 6h sleeve on its own native bar closes; "
            "each sleeve receives half the capital and allocates 25% of its own cash."
        ),
        "confirmation_rule": "Both 4h and last fully closed 6h bars must have EMA50 > EMA200 and close > EMA200.",
        "strategies": {
            "ema50_200_4h_6h_consensus": candidate,
            "ema50_200_4h_6h_50_50_portfolio": portfolio_candidate,
            "buy_and_hold_25pct": {"out_of_sample": benchmark},
            "buy_and_hold_25pct_50_50_portfolio": {"out_of_sample": portfolio_benchmark},
        },
        "cost_sensitivity": cost_sensitivity,
        "cost_sensitivity_note": (
            "The 50/50 portfolio is replayed with fixed signals at 1x, 1.5x, 2x, and 3x "
            "fees/slippage and compared with a matched 50/50 native-timeframe buy-and-hold benchmark."
        ),
    }


def _directional_signals(bars):
    closes = [float(row["close"]) for row in bars]
    ema50 = [None] * len(bars)
    ema200 = [None] * len(bars)
    alpha50 = 2.0 / 51.0
    alpha200 = 2.0 / 201.0
    current50 = closes[0]
    current200 = closes[0]
    for i, close in enumerate(closes):
        current50 = alpha50 * close + (1 - alpha50) * current50
        current200 = alpha200 * close + (1 - alpha200) * current200
        ema50[i] = current50
        ema200[i] = current200

    sma200 = [None] * len(bars)
    for i in range(199, len(bars)):
        sma200[i] = sum(closes[i - 199:i + 1]) / 200

    signals = {
        "sma200_long_short": [0] * len(bars),
        "ema50_200_long_short": [0] * len(bars),
        "sma200_slope_20_long_short": [0] * len(bars),
        "ema50_200_slope_20_long_short": [0] * len(bars),
        "sma200_slope_50_long_short": [0] * len(bars),
        "donchian_55_20_long_short": [],
        "donchian_20_10_long_short": [],
    }
    donchian_direction = 0
    donchian_20_direction = 0
    for i, row in enumerate(bars):
        close = closes[i]
        if sma200[i] is not None:
            signals["sma200_long_short"][i] = 1 if close >= sma200[i] else -1
            signals["ema50_200_long_short"][i] = 1 if ema50[i] >= ema200[i] else -1
        if i >= 219 and sma200[i] is not None and sma200[i - 20] is not None:
            if close > sma200[i] and sma200[i] > sma200[i - 20]:
                signals["sma200_slope_20_long_short"][i] = 1
            elif close < sma200[i] and sma200[i] < sma200[i - 20]:
                signals["sma200_slope_20_long_short"][i] = -1
            if ema50[i] > ema200[i] and ema200[i] > ema200[i - 20]:
                signals["ema50_200_slope_20_long_short"][i] = 1
            elif ema50[i] < ema200[i] and ema200[i] < ema200[i - 20]:
                signals["ema50_200_slope_20_long_short"][i] = -1
        if i >= 249 and sma200[i] is not None and sma200[i - 50] is not None:
            if close > sma200[i] and sma200[i] > sma200[i - 50]:
                signals["sma200_slope_50_long_short"][i] = 1
            elif close < sma200[i] and sma200[i] < sma200[i - 50]:
                signals["sma200_slope_50_long_short"][i] = -1

        if donchian_direction == 1 and i >= 20 and close < min(
            float(bars[j]["low"]) for j in range(i - 20, i)
        ):
            donchian_direction = 0
        elif donchian_direction == -1 and i >= 20 and close > max(
            float(bars[j]["high"]) for j in range(i - 20, i)
        ):
            donchian_direction = 0
        elif donchian_direction == 0 and i >= 55:
            prior_high = max(float(bars[j]["high"]) for j in range(i - 55, i))
            prior_low = min(float(bars[j]["low"]) for j in range(i - 55, i))
            if close > prior_high:
                donchian_direction = 1
            elif close < prior_low:
                donchian_direction = -1
        signals["donchian_55_20_long_short"].append(donchian_direction)

        if donchian_20_direction == 1 and i >= 10 and close < min(
            float(bars[j]["low"]) for j in range(i - 10, i)
        ):
            donchian_20_direction = 0
        elif donchian_20_direction == -1 and i >= 10 and close > max(
            float(bars[j]["high"]) for j in range(i - 10, i)
        ):
            donchian_20_direction = 0
        elif donchian_20_direction == 0 and i >= 20:
            prior_high_20 = max(float(bars[j]["high"]) for j in range(i - 20, i))
            prior_low_20 = min(float(bars[j]["low"]) for j in range(i - 20, i))
            if close > prior_high_20:
                donchian_20_direction = 1
            elif close < prior_low_20:
                donchian_20_direction = -1
        signals["donchian_20_10_long_short"].append(donchian_20_direction)
    return signals


def _simulate_long_short(bars, signals, start, end, fee, slippage,
                         funding_rate_per_8h=0.00005, bar_hours=24):
    cash = 1000.0
    units = 0.0
    entry_price = 0.0
    entry_fee = 0.0
    funding_paid = 0.0
    trades = []
    peak = cash
    max_drawdown = 0.0
    fees_paid = 0.0

    for i in range(max(start, 1), end):
        price = float(bars[i]["close"])
        current = 1 if units > 0 else (-1 if units < 0 else 0)

        # Preserve mark-to-market and elapsed funding on synthetic bars, but
        # never change exposure there.
        if not bars[i].get("imputed", False):
            target = int(signals[i - 1])
        else:
            target = current

        if target != current:
            if units:
                exit_fill = price * (1 - current * slippage)
                exit_fee = abs(units * exit_fill) * fee
                pnl = (exit_fill - entry_price) * units - entry_fee - exit_fee - funding_paid
                cash += units * exit_fill - exit_fee
                trades.append(pnl)
                fees_paid += exit_fee
                units = 0.0
                entry_price = 0.0
                entry_fee = 0.0
                funding_paid = 0.0

            if target:
                equity = cash
                notional = max(0.0, equity * 0.25)
                entry_fee = notional * fee
                entry_fill = price * (1 + target * slippage)
                units = target * notional / entry_fill
                cash -= units * entry_fill + entry_fee
                entry_price = entry_fill
                fees_paid += entry_fee

        if units:
            funding = abs(units * price) * funding_rate_per_8h * (bar_hours / 8.0)
            cash -= funding
            funding_paid += funding

        if units:
            direction = 1 if units > 0 else -1
            liquidation_fill = price * (1 - direction * slippage)
            liquidation_fee = abs(units * liquidation_fill) * fee
            equity = cash + units * liquidation_fill - liquidation_fee
        else:
            equity = cash
        peak = max(peak, equity)
        if peak > 0:
            max_drawdown = max(max_drawdown, (peak - equity) / peak * 100)

    terminal_position_closed = False
    if units:
        last_executable = _last_executable_index(bars, max(start, 1), end)
        if last_executable is not None:
            terminal_price = float(bars[last_executable]["close"])
            direction = 1 if units > 0 else -1
            exit_fill = terminal_price * (1 - direction * slippage)
            exit_fee = abs(units * exit_fill) * fee
            final_equity = cash + units * exit_fill - exit_fee
            final_pnl = (exit_fill - entry_price) * units - entry_fee - exit_fee - funding_paid
            trades.append(final_pnl)
            fees_paid += exit_fee
            terminal_position_closed = True
        else:
            # No executable terminal bar: retain the position and report only
            # a mark-to-market estimate, without inventing a liquidation fill.
            final_equity = cash + units * float(bars[end - 1]["close"])
    else:
        final_equity = cash

    wins = sum(1 for pnl in trades if pnl > 0)
    gross_profit = sum(pnl for pnl in trades if pnl > 0)
    gross_loss = -sum(pnl for pnl in trades if pnl < 0)
    return {
        "return_pct": round((final_equity / 1000 - 1) * 100, 2),
        "final_equity_usd": round(final_equity, 2),
        "max_drawdown_pct": round(max_drawdown, 2),
        "closed_trades": len(trades),
        "win_rate_pct": round(wins / len(trades) * 100, 2) if trades else 0.0,
        "profit_factor": round(gross_profit / gross_loss, 2) if gross_loss else (None if gross_profit else 0.0),
        "fees_paid_usd": round(fees_paid, 4),
        "funding_paid_usd": round(funding_paid, 4),
        "open_position": units != 0 and not terminal_position_closed,
    }


def run_long_short_lab(bars, fee=FEE_RATE, slippage=SLIPPAGE_RATE,
                       funding_rate_per_8h=0.00005):
    """Research unlevered 25%-notional long/short futures signals with funding costs."""
    if len(bars) < 500:
        raise ValueError("At least 500 daily bars are required for long/short research")
    if not 0 <= fee < 1 or not 0 <= slippage < 1:
        raise ValueError("Fee and slippage must be between 0 and 1")
    if not math.isfinite(funding_rate_per_8h) or funding_rate_per_8h < 0:
        raise ValueError("Funding rate must be a finite non-negative number")
    signals = _directional_signals(bars)
    split = int(len(bars) * 0.7)
    walk_start = split
    edges = [walk_start + ((len(bars) - walk_start) * k) // 3 for k in range(4)]
    results = {}
    for name, values in signals.items():
        windows = []
        for fold in range(3):
            start, end = edges[fold], edges[fold + 1]
            if end > start:
                windows.append({
                    "window": fold + 1,
                    "start_index": start,
                    "end_index_exclusive": end,
                    "metrics": _simulate_long_short(
                        bars, values, start, end, fee, slippage, funding_rate_per_8h
                    ),
                })
        returns = [window["metrics"]["return_pct"] for window in windows]
        results[name] = {
            "in_sample": _simulate_long_short(
                bars, values, 200, split, fee, slippage, funding_rate_per_8h
            ),
            "out_of_sample": _simulate_long_short(
                bars, values, split, len(bars), fee, slippage, funding_rate_per_8h
            ),
            "walk_forward_windows": windows,
            "worst_window_return_pct": min(returns) if returns else None,
        }
    benchmark = _simulate_ohlc(
        bars, [True] * len(bars), split, len(bars), fee, slippage
    )
    results["buy_and_hold_25pct"] = {"out_of_sample": benchmark}
    return {
        "mode": "UNLEVERED_LONG_SHORT_PAPER_RESEARCH",
        "sample_count": len(bars),
        "split_index": split,
        "position_notional_pct": 25,
        "fee_each_side": fee,
        "slippage_each_side": slippage,
        "funding_rate_per_8h_assumption": funding_rate_per_8h,
        "funding_note": "A symmetric funding cost is charged to both long and short exposure; actual perpetual funding varies and can be positive or negative.",
        "leverage": 1,
        "strategies": results,
    }


def assess_strategy_qualification(metrics, stress_metrics, min_oos_trades=30,
                                 min_profit_factor=1.2, max_drawdown_pct=10.0,
                                 min_window_trades=5, benchmark_metrics=None,
                                 stress_benchmark_metrics=None):
    """Fail-closed research gates; passing never authorizes live trading."""
    def finite_number(value):
        if isinstance(value, bool):
            return None
        try:
            number = float(value)
        except (TypeError, ValueError, OverflowError):
            return None
        return number if math.isfinite(number) else None

    def nonnegative_integer(value, label):
        number = finite_number(value)
        if number is None or number < 0 or not number.is_integer():
            raise ValueError(label + " must be a finite non-negative integer")
        return int(number)

    minimum_oos_trades = nonnegative_integer(min_oos_trades, "min_oos_trades")
    minimum_window_trades = nonnegative_integer(min_window_trades, "min_window_trades")
    minimum_profit_factor = finite_number(min_profit_factor)
    maximum_drawdown = finite_number(max_drawdown_pct)
    if minimum_profit_factor is None or minimum_profit_factor < 0:
        raise ValueError("min_profit_factor must be finite and non-negative")
    if maximum_drawdown is None or maximum_drawdown < 0:
        raise ValueError("max_drawdown_pct must be finite and non-negative")

    def mapping(value):
        return value if isinstance(value, dict) else {}

    def metric_block(value):
        return mapping(mapping(value).get("out_of_sample"))

    oos = metric_block(metrics)
    stress_oos = metric_block(stress_metrics)
    benchmark_oos = metric_block(benchmark_metrics)
    stress_benchmark_oos = metric_block(stress_benchmark_metrics)

    trades_value = finite_number(oos.get("closed_trades"))
    trades = (
        int(trades_value)
        if trades_value is not None and trades_value >= 0
        and trades_value.is_integer()
        else -1
    )
    profit_factor = finite_number(oos.get("profit_factor"))
    drawdown = finite_number(oos.get("max_drawdown_pct"))
    candidate_return = finite_number(oos.get("return_pct"))
    stress_return = finite_number(stress_oos.get("return_pct"))
    benchmark_return = finite_number(benchmark_oos.get("return_pct"))
    stress_benchmark_return = finite_number(stress_benchmark_oos.get("return_pct"))

    raw_windows = mapping(metrics).get("walk_forward_windows")
    walk_forward = raw_windows if isinstance(raw_windows, list) else []
    windows = []
    window_trade_counts = []
    valid_windows = len(walk_forward) == 3

    for item in walk_forward:
        block = mapping(mapping(item).get("metrics"))
        window_return = finite_number(block.get("return_pct"))
        count_value = finite_number(block.get("closed_trades"))
        if (window_return is None or count_value is None
                or count_value < 0 or not count_value.is_integer()):
            valid_windows = False
        windows.append(window_return)
        window_trade_counts.append(
            int(count_value) if count_value is not None
            and count_value >= 0 and count_value.is_integer() else -1
        )

    checks = {
        "minimum_oos_trades": trades >= minimum_oos_trades,
        "minimum_trades_each_walk_forward_window": (
            valid_windows and len(window_trade_counts) == 3
            and all(count >= minimum_window_trades for count in window_trade_counts)
        ),
        "positive_oos_return": candidate_return is not None and candidate_return > 0,
        "positive_stress_oos_return": stress_return is not None and stress_return > 0,
        "minimum_profit_factor": (
            profit_factor is not None and profit_factor >= minimum_profit_factor
        ),
        "maximum_oos_drawdown": (
            drawdown is not None and 0 <= drawdown <= maximum_drawdown
        ),
        "all_walk_forward_windows_nonnegative": (
            valid_windows and len(windows) == 3
            and all(value is not None and value >= 0 for value in windows)
        ),
        "outperform_buy_and_hold_oos": (
            candidate_return is not None and benchmark_return is not None
            and candidate_return > benchmark_return
        ),
        "outperform_buy_and_hold_stress": (
            stress_return is not None and stress_benchmark_return is not None
            and stress_return > stress_benchmark_return
        ),
    }

    benchmark_comparison = {
        "candidate_oos_return_pct": candidate_return,
        "benchmark_oos_return_pct": benchmark_return,
        "oos_outperformance_pct_points": (
            round(candidate_return - benchmark_return, 4)
            if candidate_return is not None and benchmark_return is not None else None
        ),
        "candidate_stress_oos_return_pct": stress_return,
        "stress_benchmark_oos_return_pct": stress_benchmark_return,
        "stress_oos_outperformance_pct_points": (
            round(stress_return - stress_benchmark_return, 4)
            if stress_return is not None and stress_benchmark_return is not None else None
        ),
        "benchmark_available": (
            benchmark_return is not None and stress_benchmark_return is not None
        ),
    }
    return {
        "qualified_for_extended_paper_review": all(checks.values()),
        "benchmark_comparison": benchmark_comparison,
        "checks": checks,
        "failed_checks": [name for name, passed in checks.items() if not passed],
        "thresholds": {
            "minimum_oos_trades": minimum_oos_trades,
            "minimum_trades_each_walk_forward_window": minimum_window_trades,
            "minimum_profit_factor": minimum_profit_factor,
            "maximum_oos_drawdown_pct": maximum_drawdown,
            "minimum_oos_and_stress_return_pct_exclusive": 0,
            "minimum_each_walk_forward_window_return_pct": 0,
            "benchmark": "Out-of-sample and elevated-cost returns must both exceed the matched 25%-allocation buy-and-hold benchmark.",
        },
        "note": "Passing these gates only qualifies a strategy for extended forward paper review; it does not authorize live trading or establish future profitability.",
    }


def summarize_qualification(result, watchlist_limit=5):
    """Summarize fixed-gate outcomes and a diagnostic-only research watchlist."""
    if isinstance(watchlist_limit, bool) or not isinstance(watchlist_limit, int) or watchlist_limit < 0:
        raise ValueError("watchlist_limit must be a non-negative integer")

    extended_groups = result.get("extended_lab_strategy_qualification", {})
    if not isinstance(extended_groups, dict):
        extended_groups = {}
    groups = {
        "hourly_multi_timeframe": result.get("strategy_qualification", {}),
        **extended_groups,
    }
    counts = {}
    candidates = []
    total = passed = 0

    for group_name, strategies in groups.items():
        group_total = group_passed = 0
        if group_name == "hourly_multi_timeframe":
            entries = [
                (f"{timeframe} / {name}", qualification)
                for timeframe, timeframe_strategies in strategies.items()
                for name, qualification in timeframe_strategies.items()
            ]
        else:
            entries = list(strategies.items())

        for name, qualification in entries:
            group_total += 1
            total += 1
            qualified = bool(qualification.get("qualified_for_extended_paper_review", False))
            if qualified:
                group_passed += 1
                passed += 1

            comparison = qualification.get("benchmark_comparison", {})
            base_edge = comparison.get("oos_outperformance_pct_points")
            stress_edge = comparison.get("stress_oos_outperformance_pct_points")
            if (
                comparison.get("benchmark_available")
                and isinstance(base_edge, (int, float))
                and not isinstance(base_edge, bool)
                and math.isfinite(base_edge)
                and isinstance(stress_edge, (int, float))
                and not isinstance(stress_edge, bool)
                and math.isfinite(stress_edge)
            ):
                candidates.append({
                    "strategy": name,
                    "group": group_name,
                    "qualified": qualified,
                    "failed_gate_count": len(qualification.get("failed_checks", [])),
                    "base_benchmark_edge_pp": round(float(base_edge), 4),
                    "stress_benchmark_edge_pp": round(float(stress_edge), 4),
                    "weaker_benchmark_edge_pp": round(min(float(base_edge), float(stress_edge)), 4),
                })

        counts[group_name] = {"qualified": group_passed, "tested": group_total}

    # Diagnostic ordering only. This list never changes a qualification result.
    candidates.sort(key=lambda item: (
        item["failed_gate_count"],
        -item["weaker_benchmark_edge_pp"],
        item["strategy"],
    ))
    return {
        "qualified": passed,
        "tested": total,
        "by_group": counts,
        "diagnostic_watchlist": candidates[:watchlist_limit],
        "watchlist_note": (
            "Diagnostic shortlist only; it does not waive any fixed qualification gate "
            "or authorize live trading."
        ),
    }


def build_qualification_markdown(result):
    """Create a concise human-readable report from qualification JSON."""
    policy = result["strategy_qualification_policy"]
    extended_groups = result.get("extended_lab_strategy_qualification", {})
    if not isinstance(extended_groups, dict):
        extended_groups = {}
    group_labels = {
        "ohlc_breakout": "OHLC breakout strategies",
        "long_short": "Long/short research (paper only)",
        "daily_regime_filter": "Daily regime filters",
        "multi_timeframe_ensemble": "4h / 6h consensus ensemble",
        "six_hour_atr_trailing": "6h EMA50/EMA200 exit comparison (ATR trailing vs close below EMA50)",
        "volume_liquidity_momentum": "OHLCV volume / liquidity / momentum confluence",
    }
    groups = {
        "Hourly / multi-timeframe strategies": result.get("strategy_qualification", {}),
    }
    for key, strategies in extended_groups.items():
        if isinstance(strategies, dict):
            label = group_labels.get(key, key.replace("_", " ").title() + " strategies")
            groups[label] = strategies
    lines = [
        "# WHJ Bitcoin Bot — Strategy Qualification Report", "",
        f"- Data source: {result.get('source', 'unknown')}",
        f"- Closed hourly candles: {result.get('candles', 0)}",
        f"- Period: {result.get('first_closed_candle_utc', 'unknown')} to {result.get('last_closed_candle_utc', 'unknown')}",
        "- Mode: historical research and simulated paper review only",
        f"- Imputed missing hourly candles: {result.get('data_quality', {}).get('imputed_missing_hour_count', 0)} "
        f"({(result.get('data_quality', {}).get('imputed_missing_hour_count', 0) / max(1, result.get('candles', 0)) * 100):.4f}% of the series)",
        f"- Data repair: {result.get('data_quality', {}).get('imputation_method', 'not reported')}",
        "- Imputed candles use a flat prior-close price and zero volume; they are synthetic observations, not exchange trades.",
        "",
        "## Fixed promotion gates",
        f"- At least {policy['minimum_oos_trades']} out-of-sample closed trades",
        f"- At least {policy.get('minimum_trades_each_walk_forward_window', 5)} closed trades in each of three walk-forward windows",
        "- Positive out-of-sample and elevated-cost returns, both exceeding the matched 25%-allocation buy-and-hold benchmark",
        f"- Profit factor at least {policy['minimum_profit_factor']}",
        f"- Out-of-sample maximum drawdown no greater than {policy['maximum_oos_drawdown_pct']}%",
        "- All three chronological out-of-sample windows non-negative", "",
    ]
    hourly_research = (
        result.get("timeframe_research", {})
        .get("1h", {})
        .get("research", {})
    )
    regime_diagnostics = hourly_research.get("market_regime_diagnostics", {})
    regime_rows = regime_diagnostics.get("regimes", {})
    if regime_rows:
        lines.extend([
            "## 1h out-of-sample market-regime diagnostics",
            "",
            "Regimes are classified from the close, 200-SMA, and its 20-bar slope. "
            "Forward market returns are measured only after classification. "
            "Strategy exposure is descriptive and is not strategy PnL.",
            "",
        ])
        for regime_name, metrics in regime_rows.items():
            if not metrics.get("bars"):
                lines.append(f"- **{regime_name}:** insufficient bars.")
                continue
            exposure = metrics.get("strategy_exposure_pct", {})
            most_exposed = sorted(
                ((name, value) for name, value in exposure.items() if value is not None),
                key=lambda item: item[1],
                reverse=True,
            )[:3]
            exposure_text = ", ".join(
                f"{name} {value:.1f}%" for name, value in most_exposed
            ) or "not available"
            lines.append(
                f"- **{regime_name}:** {metrics['bars']} bars; "
                f"market forward return {metrics['market_forward_return_pct']:+.2f}%; "
                f"positive next-bar frequency {metrics['positive_forward_bar_pct']:.1f}%; "
                f"highest signal exposure: {exposure_text}."
            )
        lines.append("")

    paper_accounts = result.get("forward_paper_accounts", {})
    paper_labels = {
        "daily_sma20_50": "Daily SMA20/SMA50",
        "four_hour_ema50_200": "4h EMA50/EMA200",
        "daily_bollinger_mean_reversion": "Daily Bollinger mean reversion",
        "six_hour_rsi14_mean_reversion": "6h RSI14 mean reversion",
    }
    paper_rows = [
        (label, paper_accounts[key])
        for key, label in paper_labels.items()
        if isinstance(paper_accounts.get(key), dict)
    ]
    if paper_rows:
        lines.extend([
            "## Persistent forward paper-account snapshot",
            "",
            "Simulated account state only; these results are not the same as the historical out-of-sample qualification tests.",
            "",
        ])
        for label, account in paper_rows:
            equity = account.get("equity_after_estimated_exit_costs_usd")
            return_pct = account.get("return_pct")
            profit_factor = account.get("profit_factor")
            drawdown = account.get("max_drawdown_pct")
            trades = account.get("completed_trades", 0)
            win_rate = account.get("win_rate_pct")
            pause_reasons = account.get("risk_pause_reasons", [])
            status = "PAUSED — " + ", ".join(pause_reasons) if pause_reasons else "active"
            equity_text = f"${equity:,.2f}" if isinstance(equity, (int, float)) else "unavailable"
            return_text = f"{return_pct:+.2f}%" if isinstance(return_pct, (int, float)) else "unavailable"
            pf_text = f"{profit_factor:.2f}" if isinstance(profit_factor, (int, float)) else "unavailable"
            dd_text = f"{drawdown:.2f}%" if isinstance(drawdown, (int, float)) else "unavailable"
            win_text = f"{win_rate:.1f}%" if isinstance(win_rate, (int, float)) else "unavailable"
            lines.append(
                f"- **{label}:** equity {equity_text}; return {return_text}; "
                f"{trades} closed trades; win rate {win_text}; profit factor {pf_text}; "
                f"max drawdown {dd_text}; status {status}."
            )
        lines.append("")

    forward_portfolio = paper_accounts.get(
        "forward_only_ema50_200_4h_6h_50_50_portfolio", {}
    )
    if isinstance(forward_portfolio, dict) and isinstance(forward_portfolio.get("sleeves"), dict):
        seed_time = forward_portfolio.get("seed", {}).get("4h", {}).get("last_seeded_timestamp")
        seed_label = (
            datetime.fromtimestamp(seed_time, timezone.utc).isoformat()
            if isinstance(seed_time, (int, float)) else "not available"
        )
        lines.extend([
            "## Genuine forward-only EMA50/200 paper portfolio",
            "",
            f"- Seeded from the latest completed historical bar at {seed_label}. Historical data initializes indicators only; it contributes zero trades and zero PnL.",
            f"- Combined starting capital: ${forward_portfolio.get('initial_cash_usd', 0):,.2f}; current equity: ${forward_portfolio.get('equity_after_estimated_exit_costs_usd', 0):,.2f}; return: {forward_portfolio.get('return_pct', 0):+.2f}%.",
            f"- Completed forward-only trades: {forward_portfolio.get('completed_trades', 0)}; allocation: 10% of each $500 timeframe sleeve per entry.",
        ])
        for timeframe in ("4h", "6h"):
            account = forward_portfolio["sleeves"].get(timeframe, {})
            pauses = account.get("risk_pause_reasons", [])
            status = "PAUSED — " + ", ".join(pauses) if pauses else "active"
            lines.append(
                f"- **{timeframe} sleeve:** equity ${account.get('equity_after_estimated_exit_costs_usd', 0):,.2f}; "
                f"{account.get('completed_trades', 0)} closed trades; "
                f"max drawdown {account.get('max_drawdown_pct', 0):.2f}%; status {status}."
            )
        lines.extend([
            "- Risk controls: 10% maximum drawdown, 3% daily loss pause, and a five-loss pause. Existing legacy paper ledgers are kept separately and are not reset.",
            "",
        ])

    # Diagnostic shortlist only: rank by the weaker of base/stress benchmark edges.
    # This is deliberately not a promotion gate and never changes qualification.
    watchlist = []
    for group_name, strategies in groups.items():
        if group_name == "Hourly / multi-timeframe strategies":
            candidates = [
                (f"{timeframe} / {name}", qualification)
                for timeframe, timeframe_strategies in strategies.items()
                for name, qualification in timeframe_strategies.items()
            ]
        else:
            candidates = list(strategies.items())
        for name, qualification in candidates:
            comparison = qualification.get("benchmark_comparison", {})
            if comparison.get("benchmark_available"):
                base_edge = comparison.get("oos_outperformance_pct_points")
                stress_edge = comparison.get("stress_oos_outperformance_pct_points")
                if base_edge is not None and stress_edge is not None:
                    failed_gate_count = len(qualification.get("failed_checks", []))
                    watchlist.append((
                        failed_gate_count, min(base_edge, stress_edge),
                        name, base_edge, stress_edge, qualification,
                    ))
    # Prioritize candidates closest to satisfying every fixed gate, then use
    # the weaker benchmark edge as a tie-breaker. This is diagnostic only.
    watchlist.sort(key=lambda item: (item[0], -item[1]))
    if watchlist:
        lines.extend([
            "## Benchmark-edge research watchlist (diagnostic only)",
            "",
            "Sorted by the number of failed qualification gates, then by the weaker benchmark edge. "
            "This shortlist is for choosing what to investigate next; it does not waive "
            "trade-count, drawdown, profit-factor, or walk-forward gates.",
            "",
        ])
        for failed_gate_count, _, name, base_edge, stress_edge, qualification in watchlist[:5]:
            status = "qualified for extended paper review" if qualification.get(
                "qualified_for_extended_paper_review", False
            ) else "not qualified"
            gate_label = "failed gate" if failed_gate_count == 1 else "failed gates"
            lines.append(
                f"- **{name}** ({status}; {failed_gate_count} {gate_label}): "
                f"{base_edge:+.2f} pp base; {stress_edge:+.2f} pp elevated costs."
            )
        lines.append("")

    total = passed = 0
    for group_name, strategies in groups.items():
        lines.extend([f"## {group_name}", ""])
        if not strategies:
            lines.extend(["No comparable strategies were reported.", ""])
            continue
        if group_name == "Hourly / multi-timeframe strategies":
            entries = [
                (f"{timeframe} / {name}", qualification)
                for timeframe, timeframe_strategies in strategies.items()
                for name, qualification in timeframe_strategies.items()
            ]
        else:
            entries = list(strategies.items())
        if not entries:
            lines.extend(["No comparable strategies were reported.", ""])
            continue
        for name, qualification in entries:
            total += 1
            ok = qualification.get("qualified_for_extended_paper_review", False)
            passed += int(ok)
            status = "PASS — eligible for extended forward paper review" if ok else "NOT QUALIFIED"
            lines.append(f"- **{name}: {status}.**")
            failed = qualification.get("failed_checks", [])
            comparison = qualification.get("benchmark_comparison", {})
            if comparison.get("benchmark_available"):
                lines.append(
                    "  - Benchmark edge (candidate minus matched buy-and-hold): "
                    f"{comparison['oos_outperformance_pct_points']:+.2f} pp OOS; "
                    f"{comparison['stress_oos_outperformance_pct_points']:+.2f} pp under elevated costs."
                )
            else:
                lines.append("  - Benchmark comparison: unavailable; strategy cannot qualify.")
            if failed:
                lines.append("  - Failed gates: " + ", ".join(failed) + ".")
        lines.append("")
    lines.extend([
        "## Overall decision", "",
        f"- Qualified strategies: {passed} / {total}.",
        "- No strategy is approved for live trading by this report.",
        "- If none qualify, keep every strategy in research/paper mode; do not force a winner.",
        "- Historical performance is not a forecast or a guarantee. Paper results are simulated and may differ from execution.", "",
    ])
    return "\n".join(lines)


def _adx_di_series(bars, period=14):
    """Wilder ADX and directional indicators from completed OHLC bars."""
    if isinstance(period, bool) or not isinstance(period, int) or period < 2 or len(bars) <= period * 2:
        raise ValueError("ADX requires an integer period >= 2 and more than twice that many bars")
    size = len(bars)
    tr = [0.0] * size
    plus_dm = [0.0] * size
    minus_dm = [0.0] * size
    for i in range(1, size):
        up = float(bars[i]["high"]) - float(bars[i - 1]["high"])
        down = float(bars[i - 1]["low"]) - float(bars[i]["low"])
        plus_dm[i] = up if up > down and up > 0 else 0.0
        minus_dm[i] = down if down > up and down > 0 else 0.0
        previous_close = float(bars[i - 1]["close"])
        tr[i] = max(float(bars[i]["high"]) - float(bars[i]["low"]),
                    abs(float(bars[i]["high"]) - previous_close),
                    abs(float(bars[i]["low"]) - previous_close))
    adx = [None] * size
    plus_di = [None] * size
    minus_di = [None] * size
    smooth_tr = sum(tr[1:period + 1])
    smooth_plus = sum(plus_dm[1:period + 1])
    smooth_minus = sum(minus_dm[1:period + 1])
    dx_values = []
    for i in range(period, size):
        if i > period:
            smooth_tr += tr[i] - smooth_tr / period
            smooth_plus += plus_dm[i] - smooth_plus / period
            smooth_minus += minus_dm[i] - smooth_minus / period
        pdi = 100.0 * smooth_plus / smooth_tr if smooth_tr else 0.0
        mdi = 100.0 * smooth_minus / smooth_tr if smooth_tr else 0.0
        plus_di[i], minus_di[i] = pdi, mdi
        denominator = pdi + mdi
        dx = 100.0 * abs(pdi - mdi) / denominator if denominator else 0.0
        dx_values.append(dx)
        if len(dx_values) == period:
            adx[i] = sum(dx_values) / period
        elif len(dx_values) > period:
            adx[i] = ((adx[i - 1] * (period - 1)) + dx) / period
    return adx, plus_di, minus_di


def run_six_hour_atr_trailing_lab(hourly_candles, fee=FEE_RATE, slippage=SLIPPAGE_RATE):
    """Test a predeclared 6h EMA50/200 trend with a 2.5-ATR close-based trailing exit."""
    six_hour = aggregate_candles(hourly_candles, 6)
    if len(six_hour) < 500:
        raise ValueError("At least 500 six-hour bars are required for ATR trailing research")
    if not 0 <= fee < 1 or not 0 <= slippage < 1:
        raise ValueError("Fee and slippage must be between 0 and 1")

    closes = [float(row["close"]) for row in six_hour]
    ema50 = _ema_series(closes, 50)
    ema200 = _ema_series(closes, 200)
    atr14 = _atr_series(six_hour, 14)
    signals = []
    entry_indices = []
    in_position = False
    highest_close = None
    atr_multiple = 2.5

    for index, close in enumerate(closes):
        trend_ok = bool(index >= 199 and ema50[index] > ema200[index] and close > ema200[index])
        current_atr = atr14[index]
        if not in_position:
            if trend_ok and current_atr is not None and current_atr > 0:
                in_position = True
                entry_indices.append(index)
                highest_close = close
        else:
            highest_close = max(highest_close, close)
            trailing_stop = highest_close - atr_multiple * current_atr if current_atr is not None else float("inf")
            if not trend_ok or current_atr is None or close < trailing_stop:
                in_position = False
                highest_close = None
        signals.append(in_position)

    split = int(len(six_hour) * 0.7)
    edges = [split + ((len(six_hour) - split) * fold) // 3 for fold in range(4)]
    windows = []
    for fold in range(3):
        start, end = edges[fold], edges[fold + 1]
        if end > start:
            windows.append({
                "window": fold + 1,
                "start_index": start,
                "end_index_exclusive": end,
                "metrics": _simulate_ohlc(six_hour, signals, start, end, fee, slippage),
            })
    returns = [item["metrics"]["return_pct"] for item in windows]
    candidate = {
        "in_sample": _simulate_ohlc(six_hour, signals, 200, split, fee, slippage),
        "out_of_sample": _simulate_ohlc(six_hour, signals, split, len(six_hour), fee, slippage),
        "walk_forward_windows": windows,
        "worst_window_return_pct": min(returns) if returns else None,
        "entry_bar_indices": entry_indices,
        "entry_rule": "trend_ok and ATR(14) > 0",
    }
    # Compare a simpler, predeclared trend exit: close below EMA50.
    # Both variants must use exactly the same entries.
    ema50_exit_signals = []
    ema50_entry_indices = []
    ema50_exit_position = False
    for index, close in enumerate(closes):
        trend_ok = bool(index >= 199 and ema50[index] > ema200[index] and close > ema200[index])
        current_atr = atr14[index]
        if not ema50_exit_position and trend_ok and current_atr is not None and current_atr > 0:
            ema50_exit_position = True
            ema50_entry_indices.append(index)
        elif ema50_exit_position and (not trend_ok or close < ema50[index]):
            ema50_exit_position = False
        ema50_exit_signals.append(ema50_exit_position)

    ema50_exit_windows = []
    for fold in range(3):
        start, end = edges[fold], edges[fold + 1]
        if end > start:
            ema50_exit_windows.append({
                "window": fold + 1,
                "start_index": start,
                "end_index_exclusive": end,
                "metrics": _simulate_ohlc(
                    six_hour, ema50_exit_signals, start, end, fee, slippage
                ),
            })
    ema50_exit_returns = [item["metrics"]["return_pct"] for item in ema50_exit_windows]
    ema50_close_exit_candidate = {
        "in_sample": _simulate_ohlc(
            six_hour, ema50_exit_signals, 200, split, fee, slippage
        ),
        "out_of_sample": _simulate_ohlc(
            six_hour, ema50_exit_signals, split, len(six_hour), fee, slippage
        ),
        "walk_forward_windows": ema50_exit_windows,
        "worst_window_return_pct": min(ema50_exit_returns) if ema50_exit_returns else None,
        "entry_bar_indices": ema50_entry_indices,
        "entry_rule": "trend_ok and ATR(14) > 0",
    }

    # Predeclared ADX confirmation experiments. The base EMA trend exit is
    # retained in one variant to isolate the entry filter's contribution.
    adx14, plus_di, minus_di = _adx_di_series(six_hour, 14)
    adx_entry_signals, adx_entry_indices = [], []
    adx_exit_signals, adx_exit_indices = [], []
    adx_entry_position = adx_exit_position = False
    for index, close in enumerate(closes):
        base_trend_ok = bool(index >= 199 and ema50[index] > ema200[index] and close > ema200[index])
        directional_ok = (
            adx14[index] is not None and adx14[index] >= 20.0
            and plus_di[index] is not None and minus_di[index] is not None
            and plus_di[index] > minus_di[index]
        )
        if not adx_entry_position and base_trend_ok and directional_ok:
            adx_entry_position = True
            adx_entry_indices.append(index)
        elif adx_entry_position and not base_trend_ok:
            adx_entry_position = False
        adx_entry_signals.append(adx_entry_position)
        if not adx_exit_position and base_trend_ok and directional_ok:
            adx_exit_position = True
            adx_exit_indices.append(index)
        elif adx_exit_position and (
            not base_trend_ok
            or (plus_di[index] is not None and minus_di[index] is not None
                and plus_di[index] <= minus_di[index])
        ):
            adx_exit_position = False
        adx_exit_signals.append(adx_exit_position)

    def evaluate_adx_candidate(signals, entry_indices, exit_rule):
        walk_windows = []
        for fold in range(3):
            start, end = edges[fold], edges[fold + 1]
            if end > start:
                walk_windows.append({
                    "window": fold + 1,
                    "start_index": start,
                    "end_index_exclusive": end,
                    "metrics": _simulate_ohlc(six_hour, signals, start, end, fee, slippage),
                })
        fold_returns = [item["metrics"]["return_pct"] for item in walk_windows]
        return {
            "in_sample": _simulate_ohlc(six_hour, signals, 200, split, fee, slippage),
            "out_of_sample": _simulate_ohlc(six_hour, signals, split, len(six_hour), fee, slippage),
            "walk_forward_windows": walk_windows,
            "worst_window_return_pct": min(fold_returns) if fold_returns else None,
            "entry_bar_indices": entry_indices,
            "entry_rule": "EMA50 > EMA200, close > EMA200, ADX(14) >= 20, +DI > -DI",
            "exit_rule": exit_rule,
        }

    adx_entry_candidate = evaluate_adx_candidate(
        adx_entry_signals, adx_entry_indices, "EMA50/EMA200 trend invalidation"
    )
    adx_entry_exit_candidate = evaluate_adx_candidate(
        adx_exit_signals, adx_exit_indices,
        "EMA50/EMA200 trend invalidation or completed-bar +DI <= -DI"
    )

    # Predeclared threshold sensitivity check: compare ADX 15/20/25 while
    # keeping all other rules and execution assumptions unchanged.
    adx_threshold_candidates = {}
    for threshold in (15.0, 25.0):
        threshold_signals = []
        threshold_entry_indices = []
        threshold_position = False
        for index, close in enumerate(closes):
            base_trend_ok = bool(
                index >= 199 and ema50[index] > ema200[index] and close > ema200[index]
            )
            directional_ok = (
                adx14[index] is not None and adx14[index] >= threshold
                and plus_di[index] is not None and minus_di[index] is not None
                and plus_di[index] > minus_di[index]
            )
            if not threshold_position and base_trend_ok and directional_ok:
                threshold_position = True
                threshold_entry_indices.append(index)
            elif threshold_position and not base_trend_ok:
                threshold_position = False
            threshold_signals.append(threshold_position)
        threshold_candidate = evaluate_adx_candidate(
            threshold_signals, threshold_entry_indices,
            "EMA50/EMA200 trend invalidation"
        )
        threshold_candidate["entry_rule"] = (
            f"EMA50 > EMA200, close > EMA200, ADX(14) >= {threshold:g}, +DI > -DI"
        )
        adx_threshold_candidates[f"ema50_200_adx_{int(threshold)}_entry_filter"] = threshold_candidate

    benchmark_metrics = _simulate_ohlc(
        six_hour, [True] * len(six_hour), split, len(six_hour), fee, slippage
    )
    benchmark_metrics["profit_factor"] = None
    benchmark_metrics["closed_trades"] = 1
    benchmark_metrics["open_position"] = False
    benchmark_metrics["win_rate_pct"] = 100.0 if benchmark_metrics["return_pct"] > 0 else 0.0
    return {
        "mode": "SIX_HOUR_EMA50_200_EXIT_AND_ADX_CONFIRMATION_RESEARCH",
        "bar_count": len(six_hour),
        "split_index": split,
        "atr_period": 14,
        "atr_trailing_multiple": atr_multiple,
        "adx_period": 14,
        "adx_entry_threshold": 20.0,
        "adx_thresholds_tested": [15.0, 20.0, 25.0],
        "execution": (
            "Both candidates use the same EMA50/EMA200 entry and completed six-hour "
            "signals, filled at the next six-hour close. Candidate exits are either "
            "a 2.5x ATR(14) close-based trailing exit or a close below EMA50. "
            "No intrabar stop-fill assumption is made; costs and allocation match "
            "the 25%-allocation OHLC simulator."
        ),
        "strategies": {
            "ema50_200_atr2_5_trailing": candidate,
            "ema50_200_close_below_ema50_exit": ema50_close_exit_candidate,
            "ema50_200_adx_entry_filter": adx_entry_candidate,
            "ema50_200_adx_entry_and_di_exit": adx_entry_exit_candidate,
            **adx_threshold_candidates,
            "buy_and_hold_25pct": {"out_of_sample": benchmark_metrics},
        },
    }


def assess_research_lab_qualification(research, stress_research):
    """Apply the same fixed OOS gates to every comparable research lab."""
    strategies = research.get("strategies", {})
    stress_strategies = stress_research.get("strategies", {})
    results = {}
    benchmark_name = next(
        (name for name in ("buy_and_hold_25pct", "buy_and_hold") if name in strategies),
        None,
    )
    stress_benchmark_name = next(
        (name for name in ("buy_and_hold_25pct", "buy_and_hold") if name in stress_strategies),
        None,
    )
    benchmark = strategies.get(benchmark_name) if benchmark_name else None
    stress_benchmark = stress_strategies.get(stress_benchmark_name) if stress_benchmark_name else None
    for name, metrics in strategies.items():
        if name.startswith("buy_and_hold") or name not in stress_strategies:
            continue
        # A native-timeframe 50/50 portfolio requires its own matched
        # benchmark; the single-sleeve consensus keeps the 4h benchmark.
        matched_portfolio = name == "ema50_200_4h_6h_50_50_portfolio"
        candidate_benchmark = (
            strategies.get("buy_and_hold_25pct_50_50_portfolio")
            if matched_portfolio else benchmark
        )
        candidate_stress_benchmark = (
            stress_strategies.get("buy_and_hold_25pct_50_50_portfolio")
            if matched_portfolio else stress_benchmark
        )
        results[name] = assess_strategy_qualification(
            metrics,
            stress_strategies[name],
            benchmark_metrics=candidate_benchmark,
            stress_benchmark_metrics=candidate_stress_benchmark,
        )
    return results


def _paper_account_rows(bars):
    """Preserve synthetic-bar execution eligibility when adapting research candles."""
    return [
        [
            int(row["timestamp"] // 1000), 0, 0, 0, str(row["close"]),
            not bool(row.get("imputed", False)),
        ]
        for row in bars
    ]


def run_forward_paper_accounts(candles, state_dir="."):
    """Maintain independent 1d and 4h paper accounts across daily workflow runs."""
    directory = Path(state_dir)
    daily = aggregate_candles(candles, 24)
    four_hour = aggregate_candles(candles, 4)
    six_hour = aggregate_candles(candles, 6)

    account_rows = _paper_account_rows

    daily_result = update_paper_account(
        account_rows(daily),
        state_path=str(directory / "paper_daily_sma20_50.json"),
        strategy="sma_trend",
    )
    four_hour_result = update_paper_account(
        account_rows(four_hour),
        state_path=str(directory / "paper_4h_ema50_200.json"),
        strategy="ema50_200_regime",
    )
    daily_bollinger_result = update_paper_account(
        account_rows(daily),
        state_path=str(directory / "paper_daily_bollinger.json"),
        strategy="bollinger_mean_reversion",
    )
    six_hour_rsi_result = update_paper_account(
        account_rows(six_hour),
        state_path=str(directory / "paper_6h_rsi14_mean_reversion.json"),
        strategy="rsi14_mean_reversion",
    )
    ensemble_four_hour = update_paper_account(
        account_rows(four_hour),
        state_path=str(directory / "paper_4h_ema50_200_ensemble_sleeve.json"),
        initial_cash=500.0,
        strategy="ema50_200_regime",
    )
    ensemble_six_hour = update_paper_account(
        account_rows(six_hour),
        state_path=str(directory / "paper_6h_ema50_200_ensemble_sleeve.json"),
        initial_cash=500.0,
        strategy="ema50_200_regime",
    )
    # These separate ledgers start at the latest completed bar. The historical
    # series initializes EMA state only; it cannot create historical PnL or pauses.
    forward_seed_4h = seed_forward_paper_account(
        account_rows(four_hour),
        state_path=str(directory / "paper_forward_4h_ema50_200.json"),
        initial_cash=500.0,
    )
    forward_seed_6h = seed_forward_paper_account(
        account_rows(six_hour),
        state_path=str(directory / "paper_forward_6h_ema50_200.json"),
        initial_cash=500.0,
    )
    # Three separately seeded ledgers track the currently qualified candidates.
    # Each starts with $250; history warms indicators only and creates no trades.
    qualified_specs = (
        ("1d_sma_trend", daily, "sma_trend"),
        ("6h_ema50_200_regime", six_hour, "ema50_200_regime"),
        ("6h_ema_pullback_trend", six_hour, "ema_pullback_trend"),
    )
    qualified_seed = {}
    qualified_accounts = {}
    for candidate_name, candidate_bars, candidate_strategy in qualified_specs:
        candidate_path = directory / f"paper_qualified_{candidate_name}.json"
        qualified_seed[candidate_name] = seed_forward_paper_account(
            account_rows(candidate_bars),
            state_path=str(candidate_path),
            initial_cash=250.0,
            strategy=candidate_strategy,
        )
        qualified_accounts[candidate_name] = update_paper_account(
            account_rows(candidate_bars),
            state_path=str(candidate_path),
            initial_cash=250.0,
            allocation_fraction=0.10,
            max_drawdown_fraction=0.10,
            daily_loss_fraction=0.03,
            max_consecutive_losses=5,
            strategy=candidate_strategy,
        )
    qualified_forward_portfolio = {
        "mode": "QUALIFIED_CANDIDATES_FORWARD_ONLY_PAPER",
        "initial_cash_usd": 750.0,
        "equity_after_estimated_exit_costs_usd": round(sum(
            account["equity_after_estimated_exit_costs_usd"]
            for account in qualified_accounts.values()
        ), 2),
        "return_pct": round((
            sum(account["equity_after_estimated_exit_costs_usd"]
                for account in qualified_accounts.values()) / 750.0 - 1.0
        ) * 100.0, 2),
        "completed_trades": sum(
            account["completed_trades"] for account in qualified_accounts.values()
        ),
        "candidates": qualified_accounts,
        "seed": qualified_seed,
        "note": (
            "Three currently qualified candidates are tracked in independent $250 "
            "forward-only ledgers. Historical candles warm indicators only. The fourth "
            "qualified ATR-trailing candidate is intentionally excluded until the "
            "paper engine consumes validated OHLC bars and can reproduce its ATR stop."
        ),
    }
    forward_four_hour = update_paper_account(
        account_rows(four_hour),
        state_path=str(directory / "paper_forward_4h_ema50_200.json"),
        initial_cash=500.0,
        allocation_fraction=0.10,
        max_drawdown_fraction=0.10,
        daily_loss_fraction=0.03,
        max_consecutive_losses=5,
        strategy="ema50_200_regime",
    )
    forward_six_hour = update_paper_account(
        account_rows(six_hour),
        state_path=str(directory / "paper_forward_6h_ema50_200.json"),
        initial_cash=500.0,
        allocation_fraction=0.10,
        max_drawdown_fraction=0.10,
        daily_loss_fraction=0.03,
        max_consecutive_losses=5,
        strategy="ema50_200_regime",
    )
    forward_initial = (
        forward_four_hour["initial_cash_usd"] + forward_six_hour["initial_cash_usd"]
    )
    forward_equity = (
        forward_four_hour["equity_after_estimated_exit_costs_usd"]
        + forward_six_hour["equity_after_estimated_exit_costs_usd"]
    )
    forward_portfolio = {
        "mode": "GENUINE_FORWARD_ONLY_50_50_PAPER",
        "initial_cash_usd": round(forward_initial, 2),
        "equity_after_estimated_exit_costs_usd": round(forward_equity, 2),
        "return_pct": round((forward_equity / forward_initial - 1.0) * 100.0, 2),
        "completed_trades": (
            forward_four_hour["completed_trades"] + forward_six_hour["completed_trades"]
        ),
        "fees_paid_usd": round(
            forward_four_hour["fees_paid_usd"] + forward_six_hour["fees_paid_usd"], 4
        ),
        "sleeves": {"4h": forward_four_hour, "6h": forward_six_hour},
        "seed": {"4h": forward_seed_4h, "6h": forward_seed_6h},
        "allocation": "50% capital per timeframe sleeve; 10% of each sleeve equity per entry.",
        "risk_limits": {
            "max_drawdown_pct": 10.0,
            "daily_loss_pause_pct": 3.0,
            "max_consecutive_losses": 5,
            "allocation_pct_per_sleeve": 10.0,
        },
        "note": (
            "This is a new forward-only paper ledger seeded at the latest completed "
            "bar. Historical candles warm up indicators only and create no historical trades."
        ),
    }
    ensemble_initial = (
        ensemble_four_hour["initial_cash_usd"] + ensemble_six_hour["initial_cash_usd"]
    )
    ensemble_equity = (
        ensemble_four_hour["equity_after_estimated_exit_costs_usd"]
        + ensemble_six_hour["equity_after_estimated_exit_costs_usd"]
    )
    ensemble_portfolio = {
        "mode": "PERSISTENT_50_50_MULTI_TIMEFRAME_PAPER_ONLY",
        "initial_cash_usd": round(ensemble_initial, 2),
        "equity_after_estimated_exit_costs_usd": round(ensemble_equity, 2),
        "return_pct": round((ensemble_equity / ensemble_initial - 1.0) * 100.0, 2),
        "completed_trades": (
            ensemble_four_hour["completed_trades"] + ensemble_six_hour["completed_trades"]
        ),
        "fees_paid_usd": round(
            ensemble_four_hour["fees_paid_usd"] + ensemble_six_hour["fees_paid_usd"], 4
        ),
        "sleeves": {
            "4h": ensemble_four_hour,
            "6h": ensemble_six_hour,
        },
        "max_drawdown_by_sleeve_pct": {
            "4h": ensemble_four_hour["max_drawdown_pct"],
            "6h": ensemble_six_hour["max_drawdown_pct"],
        },
        "allocation": "50% of capital to each native-timeframe sleeve; each sleeve allocates 25% of its own equity per entry.",
        "note": "The sleeve drawdowns are reported separately; no unsynchronized combined drawdown is inferred.",
    }
    return {
        "mode": "PERSISTENT_MULTI_TIMEFRAME_PAPER_ONLY",
        "daily_sma20_50": daily_result,
        "four_hour_ema50_200": four_hour_result,
        "daily_bollinger_mean_reversion": daily_bollinger_result,
        "six_hour_rsi14_mean_reversion": six_hour_rsi_result,
        "ema50_200_4h_6h_50_50_portfolio": ensemble_portfolio,
        "forward_only_ema50_200_4h_6h_50_50_portfolio": forward_portfolio,
        "forward_only_qualified_candidates": qualified_forward_portfolio,
        "note": "Legacy diagnostic ledgers backfill history; separate forward_only ledgers start at the latest completed bar and process only future completed candles. No real orders are sent.",
    }


def _research_output_paths(output_dir="."):
    """Keep explicit research runs isolated without moving legacy workflow ledgers."""
    output_path = Path(output_dir)
    # Scheduled workflows historically keep their persistent paper ledgers in
    # the repository working directory. Preserve that default; only manual runs
    # that opt into a dedicated output directory get a separate paper_state dir.
    paper_state_dir = Path(".") if output_path == Path(".") else output_path / "paper_state"
    return output_path, paper_state_dir


def main(output_dir="."):
    output_path, paper_state_dir = _research_output_paths(output_dir)
    output_path.mkdir(parents=True, exist_ok=True)
    candles = load_two_year_candles()
    prices = [row["close"] for row in candles]
    hourly_blocked = _blocked_execution_indices(candles)
    research = run_strategy_lab(
        prices, fee=FEE_RATE, slippage=SLIPPAGE_RATE,
        blocked_execution_indices=hourly_blocked,
    )
    timeframe_research = {}
    for label, hours in (("1h", 1), ("4h", 4), ("6h", 6), ("1d", 24)):
        bars = candles if hours == 1 else aggregate_candles(candles, hours)
        timeframe_research[label] = {
            "bar_count": len(bars),
            "first_bar_utc": datetime.fromtimestamp(bars[0]["timestamp"] / 1000, timezone.utc).isoformat(),
            "last_bar_utc": datetime.fromtimestamp(bars[-1]["timestamp"] / 1000, timezone.utc).isoformat(),
            "imputed_bar_count": len(_blocked_execution_indices(bars)),
            "blocked_execution_bar_count": len(_blocked_execution_indices(bars)),
            "research": run_strategy_lab(
                [bar["close"] for bar in bars],
                fee=FEE_RATE,
                slippage=SLIPPAGE_RATE,
                blocked_execution_indices=_blocked_execution_indices(bars),
            ),
        }
    # Apply the same elevated-cost assumptions to every tested timeframe,
    # including the base hourly strategy set, so no timeframe escapes stress review.
    stress_cost_research = {
        "1h": run_strategy_lab(
            prices,
            fee=0.002,
            slippage=0.001,
            blocked_execution_indices=hourly_blocked,
        )
    }
    for label in ("4h", "6h", "1d"):
        hours = {"4h": 4, "6h": 6, "1d": 24}[label]
        aggregated = aggregate_candles(candles, hours)
        stress_cost_research[label] = run_strategy_lab(
            [bar["close"] for bar in aggregated],
            fee=0.002,
            slippage=0.001,
            blocked_execution_indices=_blocked_execution_indices(aggregated),
        )

    daily_bars = aggregate_candles(candles, 24)
    ohlc_breakout_research = run_ohlc_breakout_lab(daily_bars)
    ohlc_breakout_stress = run_ohlc_breakout_lab(daily_bars, fee=0.002, slippage=0.001)
    long_short_research = run_long_short_lab(daily_bars)
    long_short_stress = run_long_short_lab(
        daily_bars, fee=0.002, slippage=0.001, funding_rate_per_8h=0.0001
    )
    daily_regime_research = run_daily_regime_filter_lab(candles)
    daily_regime_stress = run_daily_regime_filter_lab(candles, fee=0.002, slippage=0.001, funding_rate_per_8h=0.0001)
    multi_timeframe_ensemble_research = run_multi_timeframe_ensemble_lab(candles)
    multi_timeframe_ensemble_stress = run_multi_timeframe_ensemble_lab(
        candles, fee=0.002, slippage=0.001
    )
    six_hour_atr_research = run_six_hour_atr_trailing_lab(candles)
    six_hour_atr_stress = run_six_hour_atr_trailing_lab(candles, fee=0.002, slippage=0.001)
    from strategy_lab import run_volume_liquidity_lab
    volume_liquidity_research = run_volume_liquidity_lab(candles, fee=FEE_RATE, slippage=SLIPPAGE_RATE)
    volume_liquidity_stress = run_volume_liquidity_lab(candles, fee=0.002, slippage=0.001)
    forward_paper = run_forward_paper_accounts(candles, state_dir=str(paper_state_dir))
    qualification = {}
    for label in ("1h", "4h", "6h", "1d"):
        qualification[label] = {}
        base_strategies = timeframe_research[label]["research"]["strategies"]
        stressed_strategies = stress_cost_research[label]["strategies"]
        for strategy_name, metrics in base_strategies.items():
            if strategy_name == "buy_and_hold" or strategy_name not in stressed_strategies:
                continue
            qualification[label][strategy_name] = assess_strategy_qualification(
                metrics,
                stressed_strategies[strategy_name],
                benchmark_metrics=base_strategies.get("buy_and_hold"),
                stress_benchmark_metrics=stressed_strategies.get("buy_and_hold"),
            )

    extended_lab_qualification = {
        "ohlc_breakout": assess_research_lab_qualification(
            ohlc_breakout_research, ohlc_breakout_stress
        ),
        "long_short": assess_research_lab_qualification(
            long_short_research, long_short_stress
        ),
        "daily_regime_filter": assess_research_lab_qualification(
            daily_regime_research, daily_regime_stress
        ),
        "multi_timeframe_ensemble": assess_research_lab_qualification(
            multi_timeframe_ensemble_research, multi_timeframe_ensemble_stress
        ),
        "six_hour_atr_trailing": assess_research_lab_qualification(
            six_hour_atr_research, six_hour_atr_stress
        ),
        "volume_liquidity_momentum": assess_research_lab_qualification(
            volume_liquidity_research, volume_liquidity_stress
        ),
    }

    result = {
        "project": "WHJ Bitcoin Bot",
        "mode": "EXTENDED_HISTORICAL_RESEARCH_ONLY",
        "source": "Coinbase Exchange public BTC-USD candles",
        "interval": "1h",
        "requested_days": DAYS,
        "actual_days": round((candles[-1]["timestamp"] - candles[0]["timestamp"]) / 86400000, 2),
        "candles": len(candles),
        "first_closed_candle_utc": datetime.fromtimestamp(candles[0]["timestamp"] / 1000, timezone.utc).isoformat(),
        "last_closed_candle_utc": datetime.fromtimestamp(candles[-1]["timestamp"] / 1000, timezone.utc).isoformat(),
        "fees": {"entry_and_exit_rate": FEE_RATE, "slippage_each_side": SLIPPAGE_RATE},
        "data_quality": {
            "hourly_intervals_contiguous_after_repair": True,
            "imputed_missing_hour_count": candles[0].get("_imputed_hour_count", 0),
            "blocked_hourly_execution_bar_count": len(hourly_blocked),
            "imputation_method": "Forward-filled prior close with zero volume for gaps of at most six hours; larger gaps are rejected.",
            "ohlcv_validated": True,
        },
        "research": research,
        "timeframe_research": timeframe_research,
        "stress_cost_research": stress_cost_research,
        "strategy_qualification": qualification,
        "extended_lab_strategy_qualification": extended_lab_qualification,
        "strategy_qualification_policy": {
            "minimum_oos_trades": 30,
            "minimum_trades_each_walk_forward_window": 5,
            "minimum_profit_factor": 1.2,
            "maximum_oos_drawdown_pct": 10.0,
            "positive_oos_and_stress_required": True,
            "all_three_oos_windows_must_be_nonnegative": True,
            "must_outperform_matched_buy_and_hold_in_base_and_stress": True,
        },
        "forward_paper_accounts": forward_paper,
        "ohlc_breakout_research": ohlc_breakout_research,
        "ohlc_breakout_stress": ohlc_breakout_stress,
        "long_short_research": long_short_research,
        "long_short_stress": long_short_stress,
        "daily_regime_research": daily_regime_research,
        "daily_regime_stress": daily_regime_stress,
        "multi_timeframe_ensemble_research": multi_timeframe_ensemble_research,
        "six_hour_atr_trailing_research": six_hour_atr_research,
        "six_hour_atr_trailing_stress": six_hour_atr_stress,
        "multi_timeframe_ensemble_stress": multi_timeframe_ensemble_stress,
        "volume_liquidity_momentum_research": volume_liquidity_research,
        "volume_liquidity_momentum_stress": volume_liquidity_stress,
        "warning": "Historical results are not forecasts. Strategy selection requires robust out-of-sample performance and forward paper trading. No live orders were placed.",
    }
    (output_path / "historical_research.json").write_text(
        json.dumps(result, indent=2, allow_nan=False) + "\n",
        encoding="utf-8",
    )
    (output_path / "strategy_qualification_report.md").write_text(
        build_qualification_markdown(result), encoding="utf-8"
    )
    summary = {
        "source": result["source"],
        "candles": result["candles"],
        "first": result["first_closed_candle_utc"],
        "last": result["last_closed_candle_utc"],
        "forward_paper_accounts": {
            name: {
                "return_pct": account["return_pct"],
                "equity_usd": account["equity_after_estimated_exit_costs_usd"],
                "completed_trades": account["completed_trades"],
                "win_rate_pct": account["win_rate_pct"],
                "max_drawdown_pct": account["max_drawdown_pct"],
                "processed_new_candles": account["processed_new_candles"],
            }
            for name, account in (
                ("daily_sma20_50", forward_paper["daily_sma20_50"]),
                ("four_hour_ema50_200", forward_paper["four_hour_ema50_200"]),
                ("daily_bollinger_mean_reversion", forward_paper["daily_bollinger_mean_reversion"]),
                ("six_hour_rsi14_mean_reversion", forward_paper["six_hour_rsi14_mean_reversion"]),
            )
        },
        "qualification_summary": summarize_qualification(result),
        "forward_paper_4h_6h_ensemble": {
            "return_pct": forward_paper["ema50_200_4h_6h_50_50_portfolio"]["return_pct"],
            "equity_usd": forward_paper["ema50_200_4h_6h_50_50_portfolio"]["equity_after_estimated_exit_costs_usd"],
            "completed_trades": forward_paper["ema50_200_4h_6h_50_50_portfolio"]["completed_trades"],
            "max_drawdown_by_sleeve_pct": forward_paper["ema50_200_4h_6h_50_50_portfolio"]["max_drawdown_by_sleeve_pct"],
        },
        "genuine_forward_only_paper_portfolio": {
            "return_pct": forward_paper["forward_only_ema50_200_4h_6h_50_50_portfolio"]["return_pct"],
            "equity_usd": forward_paper["forward_only_ema50_200_4h_6h_50_50_portfolio"]["equity_after_estimated_exit_costs_usd"],
            "completed_trades": forward_paper["forward_only_ema50_200_4h_6h_50_50_portfolio"]["completed_trades"],
            "sleeve_drawdowns_pct": {
                timeframe: forward_paper["forward_only_ema50_200_4h_6h_50_50_portfolio"]["sleeves"][timeframe]["max_drawdown_pct"]
                for timeframe in ("4h", "6h")
            },
        },
        "strategies": {
            name: {
                "oos_return_pct": metrics["out_of_sample"]["return_pct"],
                "oos_max_drawdown_pct": metrics["out_of_sample"]["max_drawdown_pct"],
                "oos_profit_factor": metrics["out_of_sample"]["profit_factor"],
                "oos_trades": metrics["out_of_sample"]["closed_trades"],
                "worst_window_return_pct": metrics.get("worst_window_return_pct"),
                "window_returns_pct": [
                    item["metrics"]["return_pct"] for item in metrics.get("walk_forward_windows", [])
                ],
            }
            for name, metrics in research["strategies"].items()
        },
    }
    print(json.dumps(summary, indent=2, allow_nan=False))


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(
        description="Run isolated historical BTC/USD strategy research."
    )
    parser.add_argument(
        "--output-dir", default=".",
        help="Directory for research reports and separate paper-state ledgers (default: current directory).",
    )
    arguments = parser.parse_args()
    main(output_dir=arguments.output_dir)
