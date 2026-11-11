"""Causal regime-filtered EMA research using conservative OHLC execution.

Research-only: no exchange, paper-account, wallet, schedule, or order imports.
The ATR-percentile filter uses only the preceding 180 completed bars. Signals
formed at a close are executable no earlier than the next bar's open.
"""
import math
from statistics import quantiles

from ohlc_execution_lab import simulate_ohlc_risk

INITIAL_EQUITY = 1000.0
WARMUP_BARS = 260
VOLATILITY_LOOKBACK = 180
VOLATILITY_QUANTILE = 0.90


def _validate_bars(bars):
    if not isinstance(bars, (list, tuple)) or len(bars) < WARMUP_BARS + 20:
        raise ValueError("At least 280 OHLCV bars are required")
    clean = []
    for i, row in enumerate(bars):
        if not isinstance(row, dict):
            raise ValueError("Each bar must be a mapping")
        values = [row.get(k) for k in ("open", "high", "low", "close")]
        if any(isinstance(v, bool) or not isinstance(v, (int, float))
               or not math.isfinite(v) or v <= 0 for v in values):
            raise ValueError("OHLC values must be finite positive numbers")
        o, h, l, c = map(float, values)
        if h < max(o, l, c) or l > min(o, h, c):
            raise ValueError("Invalid OHLC candle at index %d" % i)
        clean.append({"open": o, "high": h, "low": l, "close": c})
    return clean


def _ema(values, period):
    out = [None] * len(values)
    if len(values) < period:
        return out
    current = sum(values[:period]) / period
    out[period - 1] = current
    alpha = 2.0 / (period + 1)
    for i in range(period, len(values)):
        current = alpha * values[i] + (1.0 - alpha) * current
        out[i] = current
    return out


def _atr_percent(bars, period=14):
    tr = []
    for i, bar in enumerate(bars):
        prev = bars[i - 1]["close"] if i else bar["close"]
        tr.append(max(bar["high"] - bar["low"],
                      abs(bar["high"] - prev), abs(bar["low"] - prev)))
    atr = [None] * len(bars)
    if len(bars) >= period:
        value = sum(tr[:period]) / period
        atr[period - 1] = value / bars[period - 1]["close"]
        for i in range(period, len(bars)):
            value = (value * (period - 1) + tr[i]) / period
            atr[i] = value / bars[i]["close"]
    return atr


def build_regime_signals(bars):
    """Return baseline EMA and past-only volatility-filtered long/flat states."""
    rows = _validate_bars(bars)
    closes = [r["close"] for r in rows]
    fast, slow = _ema(closes, 50), _ema(closes, 200)
    atr_pct = _atr_percent(rows)
    baseline = [False] * len(rows)
    filtered = [False] * len(rows)
    for i, price in enumerate(closes):
        trend = fast[i] is not None and slow[i] is not None and fast[i] > slow[i] and price > slow[i]
        baseline[i] = bool(trend)
        # Quantile is derived strictly from the 180 observations ending at i-1.
        if trend and atr_pct[i] is not None and i >= 200 + VOLATILITY_LOOKBACK:
            history = [v for v in atr_pct[i - VOLATILITY_LOOKBACK:i] if v is not None]
            if len(history) == VOLATILITY_LOOKBACK:
                cutoff = quantiles(history, n=10, method="inclusive")[8]
                filtered[i] = atr_pct[i] <= cutoff
    return {"ema50_200": baseline, "ema50_200_atr90_past180": filtered}


def _buy_hold_return(bars, start, end, fee, slippage):
    # Same OOS start convention as the strategy: first signal-close, next open.
    entry = bars[start + 1]["open"] * (1.0 + slippage)
    exit_price = bars[end - 1]["close"] * (1.0 - slippage)
    units = INITIAL_EQUITY * (1.0 - fee) / entry
    final = units * exit_price * (1.0 - fee)
    return {
        "return_pct": round((final / INITIAL_EQUITY - 1.0) * 100.0, 4),
        "final_equity_usd": round(final, 4),
    }


def evaluate_regime_fold(bars, oos_start, oos_end, fee=0.001, slippage=0.0005):
    """Evaluate one reset OOS fold with 260 prior bars used only for warmup."""
    rows = _validate_bars(bars)
    if any(isinstance(x, bool) or not isinstance(x, int) for x in (oos_start, oos_end)):
        raise ValueError("Fold boundaries must be integer indices")
    if not (WARMUP_BARS <= oos_start < oos_end <= len(rows)):
        raise ValueError("Fold must have sufficient warmup and non-empty OOS bars")
    if not (0 <= fee < 1 and 0 <= slippage < 1):
        raise ValueError("Costs must be between zero and one")
    signals = build_regime_signals(rows)
    start = oos_start - WARMUP_BARS
    fold = rows[start:oos_end]
    local_start = WARMUP_BARS
    result = {}
    for name, states in signals.items():
        entries = [False] * len(fold)
        exits = [False] * len(fold)
        for j in range(local_start, len(fold)):
            original = start + j
            entries[j] = bool(states[original] and (j == 0 or not states[original - 1]))
            exits[j] = bool(not states[original] and j > 0 and states[original - 1])
        result[name] = simulate_ohlc_risk(
            [r["open"] for r in fold], [r["high"] for r in fold],
            [r["low"] for r in fold], [r["close"] for r in fold],
            entries, exits, fee=fee, slippage=slippage,
            allocation_fraction=0.25, stop_loss_pct=0.02, take_profit_pct=0.04,
        )
    result["buy_and_hold"] = _buy_hold_return(rows, oos_start, oos_end, fee, slippage)
    result["cash"] = {"return_pct": 0.0, "final_equity_usd": INITIAL_EQUITY}
    result["protocol"] = {
        "oos_start_index": oos_start, "oos_end_exclusive": oos_end,
        "warmup_bars": WARMUP_BARS, "execution": "next_bar_open",
        "allocation_fraction": 0.25, "stop_loss_pct": 0.02,
        "take_profit_pct": 0.04, "fee_per_side": fee,
        "slippage_per_side": slippage,
        "volatility_filter": "current ATR14/close <= inclusive 90th percentile of prior 180 completed bars",
        "same_bar_stop_target": "stop_first",
        "intrabar_drawdown": "conservative OHLC high-to-low liquidation envelope",
    }
    return result
