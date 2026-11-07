"""Fetch five years of public BTC/USD hourly candles and run fixed-rule research.

Research only: no credentials, orders, or trading endpoints are used.
"""
import json
import math
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

from paper_account import update_paper_account
from strategy_lab import run_strategy_lab

BASE_URL = "https://api.exchange.coinbase.com/products/BTC-USD/candles"
INTERVAL_MS = 60 * 60 * 1000
DAYS = 1825
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


def _turtle_signals(bars, entry_period, exit_period, regime_period=None):
    """Create close-confirmed Donchian signals using only prior-bar channel bounds."""
    closes = [float(row["close"]) for row in bars]
    highs = [float(row["high"]) for row in bars]
    lows = [float(row["low"]) for row in bars]
    regime_sma = [None] * len(bars)
    if regime_period:
        for i in range(regime_period - 1, len(bars)):
            regime_sma[i] = sum(closes[i - regime_period + 1:i + 1]) / regime_period

    signals = []
    in_position = False
    for i, close in enumerate(closes):
        if in_position:
            exit_break = i >= exit_period and close < min(lows[i - exit_period:i])
            regime_exit = bool(regime_period and regime_sma[i] is not None and close < regime_sma[i])
            if exit_break or regime_exit:
                in_position = False
        elif i >= entry_period:
            breakout = close > max(highs[i - entry_period:i])
            regime_ok = not regime_period or (
                regime_sma[i] is not None and close > regime_sma[i]
            )
            if breakout and regime_ok:
                in_position = True
        signals.append(in_position)
    return signals


def _simulate_ohlc(bars, signals, start, end, fee, slippage):
    cash = 1000.0
    units = 0.0
    entry_cost = 0.0
    trades = []
    peak = cash
    max_drawdown = 0.0
    for i in range(max(start, 1), end):
        want_long = signals[i - 1]
        price = float(bars[i]["close"])
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
        equity = cash + units * price
        peak = max(peak, equity)
        if peak > 0:
            max_drawdown = max(max_drawdown, (peak - equity) / peak * 100)

    if units > 0:
        exit_value = units * float(bars[end - 1]["close"]) * (1 - slippage)
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
    strategies = {
        "donchian_20_10": (20, 10, None),
        "donchian_55_20": (55, 20, None),
        "donchian_20_10_sma200": (20, 10, 200),
        "donchian_55_20_sma200": (55, 20, 200),
    }
    results = {}
    for name, (entry, exit_period, regime) in strategies.items():
        signals = _turtle_signals(bars, entry, exit_period, regime)
        warmup = max(entry, regime or 0)
        walk_start = max(warmup, len(bars) // 2)
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

    benchmark_cash = 750.0
    benchmark_units = (250.0 * (1 - fee)) / (float(bars[split]["close"]) * (1 + slippage))
    peak = 1000.0
    max_drawdown = 0.0
    for row in bars[split:]:
        equity = benchmark_cash + benchmark_units * float(row["close"])
        peak = max(peak, equity)
        max_drawdown = max(max_drawdown, (peak - equity) / peak * 100)
    exit_value = benchmark_units * float(bars[-1]["close"]) * (1 - slippage)
    exit_value -= exit_value * fee
    benchmark_equity = benchmark_cash + exit_value
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
        }
    }
    return {
        "mode": "OHLC_DONCHIAN_CHRONOLOGICAL_HOLDOUT",
        "sample_count": len(bars),
        "split_index": split,
        "execution": "Prior completed candle breakout signal; next close fill; 25% allocation; fees and slippage included.",
        "note": "Donchian channel bounds use prior highs/lows only; SMA200 regime uses completed daily closes.",
        "strategies": results,
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
        "donchian_55_20_long_short": [],
    }
    donchian_direction = 0
    for i, row in enumerate(bars):
        close = closes[i]
        if sma200[i] is not None:
            signals["sma200_long_short"][i] = 1 if close >= sma200[i] else -1
            signals["ema50_200_long_short"][i] = 1 if ema50[i] >= ema200[i] else -1

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
        target = int(signals[i - 1])
        current = 1 if units > 0 else (-1 if units < 0 else 0)

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

        equity = cash + units * price
        peak = max(peak, equity)
        if peak > 0:
            max_drawdown = max(max_drawdown, (peak - equity) / peak * 100)

    if units:
        direction = 1 if units > 0 else -1
        exit_fill = float(bars[end - 1]["close"]) * (1 - direction * slippage)
        exit_fee = abs(units * exit_fill) * fee
        final_equity = cash + units * exit_fill - exit_fee
        final_pnl = (exit_fill - entry_price) * units - entry_fee - exit_fee - funding_paid
        trades.append(final_pnl)
        fees_paid += exit_fee
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
        "open_position": False,
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
    walk_start = max(200, len(bars) // 2)
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


def run_forward_paper_accounts(candles, state_dir="."):
    """Maintain independent 1d and 4h paper accounts across daily workflow runs."""
    directory = Path(state_dir)
    daily = aggregate_candles(candles, 24)
    four_hour = aggregate_candles(candles, 4)

    def account_rows(bars):
        return [[int(row["timestamp"] // 1000), 0, 0, 0, str(row["close"])] for row in bars]

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
    return {
        "mode": "PERSISTENT_MULTI_TIMEFRAME_PAPER_ONLY",
        "daily_sma20_50": daily_result,
        "four_hour_ema50_200": four_hour_result,
        "note": "These accounts process only newly closed aggregated bars and persist state between scheduled runs. No real orders are sent.",
    }


def main():
    candles = load_two_year_candles()
    prices = [row["close"] for row in candles]
    research = run_strategy_lab(prices, fee=FEE_RATE, slippage=SLIPPAGE_RATE)
    timeframe_research = {}
    for label, hours in (("1h", 1), ("4h", 4), ("6h", 6), ("1d", 24)):
        bars = candles if hours == 1 else aggregate_candles(candles, hours)
        timeframe_research[label] = {
            "bar_count": len(bars),
            "first_bar_utc": datetime.fromtimestamp(bars[0]["timestamp"] / 1000, timezone.utc).isoformat(),
            "last_bar_utc": datetime.fromtimestamp(bars[-1]["timestamp"] / 1000, timezone.utc).isoformat(),
            "imputed_bar_count": sum(1 for bar in bars if bar.get("imputed", False)),
            "research": run_strategy_lab(
                [bar["close"] for bar in bars],
                fee=FEE_RATE,
                slippage=SLIPPAGE_RATE,
            ),
        }
    stress_cost_research = {}
    for label in ("4h", "1d"):
        hours = 4 if label == "4h" else 24
        aggregated = aggregate_candles(candles, hours)
        stress_cost_research[label] = run_strategy_lab(
            [bar["close"] for bar in aggregated],
            fee=0.002,
            slippage=0.001,
        )

    daily_bars = aggregate_candles(candles, 24)
    ohlc_breakout_research = run_ohlc_breakout_lab(daily_bars)
    ohlc_breakout_stress = run_ohlc_breakout_lab(daily_bars, fee=0.002, slippage=0.001)
    long_short_research = run_long_short_lab(daily_bars)
    long_short_stress = run_long_short_lab(
        daily_bars, fee=0.002, slippage=0.001, funding_rate_per_8h=0.0001
    )
    forward_paper = run_forward_paper_accounts(candles)
    result = {
        "project": "WHJ Bitcoin Bot",
        "mode": "FIVE_YEAR_HISTORICAL_RESEARCH_ONLY",
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
            "imputation_method": "Forward-filled prior close with zero volume for gaps of at most six hours; larger gaps are rejected.",
            "ohlcv_validated": True,
        },
        "research": research,
        "timeframe_research": timeframe_research,
        "stress_cost_research": stress_cost_research,
        "forward_paper_accounts": forward_paper,
        "ohlc_breakout_research": ohlc_breakout_research,
        "ohlc_breakout_stress": ohlc_breakout_stress,
        "long_short_research": long_short_research,
        "long_short_stress": long_short_stress,
        "warning": "Historical results are not forecasts. Strategy selection requires robust out-of-sample performance and forward paper trading. No live orders were placed.",
    }
    Path("historical_research.json").write_text(
        json.dumps(result, indent=2, allow_nan=False) + "\n",
        encoding="utf-8",
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
            )
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
    main()
