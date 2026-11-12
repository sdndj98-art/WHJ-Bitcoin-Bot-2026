"""
Expanded, isolated BTC strategy-family signal library.

Signals are computed only from completed OHLCV bars. A consumer must execute
no earlier than the next bar; this module contains no orders, account state,
position sizing, exchange access, or performance claims.
"""
import math
from statistics import median

def _rows(candles):
    result = []
    for row in candles:
        if isinstance(row, dict):
            values = [row[k] for k in ("open", "high", "low", "close", "volume")]
        else:
            if len(row) < 6:
                raise ValueError("OHLCV rows must contain timestamp, open, high, low, close, volume")
            values = row[1:6]
        if any(isinstance(v, bool) or not isinstance(v, (int, float)) or not math.isfinite(v) for v in values):
            raise ValueError("OHLCV values must be finite numbers")
        o, h, l, c, v = map(float, values)
        if min(o, h, l, c) <= 0 or v < 0 or h < max(o, c, l) or l > min(o, c, h):
            raise ValueError("Invalid OHLCV candle")
        result.append((o, h, l, c, v))
    if len(result) < 3:
        raise ValueError("At least three OHLCV candles are required")
    return result

def _sma(values, period):
    out = [None] * len(values)
    for i in range(period - 1, len(values)):
        out[i] = sum(values[i-period+1:i+1]) / period
    return out

def _ema(values, period):
    out = [None] * len(values)
    if len(values) < period:
        return out
    current = sum(values[:period]) / period
    out[period-1] = current
    alpha = 2.0 / (period + 1)
    for i in range(period, len(values)):
        current = alpha * values[i] + (1-alpha) * current
        out[i] = current
    return out

def _rsi(values, period):
    out = [None] * len(values)
    if len(values) <= period:
        return out
    gains = [max(values[i]-values[i-1], 0.0) for i in range(1, len(values))]
    losses = [max(values[i-1]-values[i], 0.0) for i in range(1, len(values))]
    ag, al = sum(gains[:period])/period, sum(losses[:period])/period
    def value(g, loss):
        return 100.0 if loss == 0 and g > 0 else (50.0 if loss == 0 else 100-100/(1+g/loss))
    out[period] = value(ag, al)
    for i in range(period+1, len(values)):
        ag = (ag*(period-1)+gains[i-1])/period
        al = (al*(period-1)+losses[i-1])/period
        out[i] = value(ag, al)
    return out

def _atr(rows, period=14):
    tr = []
    for i, (_, high, low, close, _) in enumerate(rows):
        previous = rows[i-1][3] if i else close
        tr.append(max(high-low, abs(high-previous), abs(low-previous)))
    out = [None] * len(rows)
    if len(rows) >= period:
        current = sum(tr[:period])/period
        out[period-1] = current
        for i in range(period, len(rows)):
            current = (current*(period-1)+tr[i])/period
            out[i] = current
    return out

def build_strategy_signals(candles):
    """Return named long/flat candidate states; never an order instruction."""
    rows = _rows(candles)
    close = [r[3] for r in rows]
    volume = [r[4] for r in rows]
    high = [r[1] for r in rows]
    low = [r[2] for r in rows]
    sma20, sma50, sma200 = (_sma(close, n) for n in (20, 50, 200))
    ema12, ema26 = _ema(close, 12), _ema(close, 26)
    rsi2, rsi14 = _rsi(close, 2), _rsi(close, 14)
    atr = _atr(rows, 14)
    signals = {name: [False]*len(rows) for name in (
        "sma_20_50_trend", "ema_12_26_trend", "sma200_regime",
        "roc_20_momentum", "roc_60_momentum", "roc_120_momentum",
        "donchian_20_10_breakout", "donchian_55_20_breakout",
        "atr_channel_breakout", "rsi2_mean_reversion", "rsi14_mean_reversion",
        "bollinger_mean_reversion", "zscore20_mean_reversion",
        "volume_confirmed_breakout", "obv_trend_confirmation",
        "volatility_squeeze_breakout", "stochastic_reversal")}
    obv = [0.0] * len(rows)
    for i in range(1, len(rows)):
        obv[i] = obv[i-1] + (volume[i] if close[i] > close[i-1] else (-volume[i] if close[i] < close[i-1] else 0.0))
    obv_ema = _ema(obv, 20)
    for i, price in enumerate(close):
        if sma20[i] is not None and sma50[i] is not None:
            signals["sma_20_50_trend"][i] = price > sma20[i] > sma50[i]
        if ema12[i] is not None and ema26[i] is not None:
            signals["ema_12_26_trend"][i] = ema12[i] > ema26[i] and price > ema26[i]
        if sma200[i] is not None:
            signals["sma200_regime"][i] = price > sma200[i]
        for period, name in ((20, "roc_20_momentum"), (60, "roc_60_momentum"), (120, "roc_120_momentum")):
            if i >= period and sma200[i] is not None:
                signals[name][i] = price > close[i-period] and price > sma200[i]
        if i >= 20:
            signals["donchian_20_10_breakout"][i] = price > max(high[i-20:i])
        if i >= 55:
            signals["donchian_55_20_breakout"][i] = price > max(high[i-55:i])
        if atr[i] is not None and i >= 20:
            signals["atr_channel_breakout"][i] = price > max(high[i-20:i]) + 0.1*atr[i]
        if sma200[i] is not None and rsi2[i] is not None:
            signals["rsi2_mean_reversion"][i] = rsi2[i] < 10 and price > sma200[i]
        if sma200[i] is not None and rsi14[i] is not None:
            signals["rsi14_mean_reversion"][i] = rsi14[i] < 30 and price > sma200[i]
        if i >= 19:
            window = close[i-19:i+1]
            avg = sum(window)/20
            variance = sum((x-avg)**2 for x in window)/20
            sd = math.sqrt(variance)
            if sd > 0:
                z = (price-avg)/sd
                signals["bollinger_mean_reversion"][i] = price < avg-2*sd and (sma200[i] is None or price > sma200[i])
                signals["zscore20_mean_reversion"][i] = z < -2 and (sma200[i] is None or price > sma200[i])
        if i >= 20:
            avg_vol = sum(volume[i-20:i])/20
            signals["volume_confirmed_breakout"][i] = (price > max(high[i-20:i]) and avg_vol > 0 and volume[i] >= 1.5*avg_vol)
        if obv_ema[i] is not None and sma50[i] is not None:
            signals["obv_trend_confirmation"][i] = price > sma50[i] and obv[i] > obv_ema[i]
        if i >= 120 and atr[i] is not None:
            recent = [atr[j]/close[j] for j in range(i-19, i+1) if atr[j] is not None]
            history = [atr[j]/close[j] for j in range(i-120, i-20) if atr[j] is not None]
            if len(recent) == 20 and len(history) >= 80:
                compressed = sum(recent)/len(recent) < median(history)
                signals["volatility_squeeze_breakout"][i] = compressed and price > max(high[i-20:i])
        if i >= 14:
            lowest, highest = min(low[i-13:i+1]), max(high[i-13:i+1])
            if highest > lowest:
                k = 100*(price-lowest)/(highest-lowest)
                previous_lowest, previous_highest = min(low[i-14:i]), max(high[i-14:i])
                previous_k = 100*(close[i-1]-previous_lowest)/(previous_highest-previous_lowest) if previous_highest > previous_lowest else 50
                signals["stochastic_reversal"][i] = previous_k < 20 <= k
    return signals

STRATEGY_FAMILIES = {
    "trend": ("sma_20_50_trend", "ema_12_26_trend", "sma200_regime"),
    "momentum": ("roc_20_momentum", "roc_60_momentum", "roc_120_momentum"),
    "breakout": ("donchian_20_10_breakout", "donchian_55_20_breakout", "atr_channel_breakout"),
    "mean_reversion": ("rsi2_mean_reversion", "rsi14_mean_reversion", "bollinger_mean_reversion", "zscore20_mean_reversion", "stochastic_reversal"),
    "volume_flow": ("volume_confirmed_breakout", "obv_trend_confirmation"),
    "volatility": ("volatility_squeeze_breakout",),
}

def strategy_universe():
    """Return stable metadata; advanced data-dependent families are explicitly deferred."""
    return {
        "implemented_signal_families": {key: list(value) for key, value in STRATEGY_FAMILIES.items()},
        "deferred_data_families": {
            "derivatives": ["funding_rate_carry", "perpetual_basis", "open_interest_change", "liquidation_cascade"],
            "order_book": ["spread_depth_imbalance", "order_book_imbalance", "market_impact"],
            "cross_asset": ["pairs_cointegration", "cross_asset_momentum", "btc_dominance_rotation"],
            "event": ["macro_event_filter", "on_chain_flow", "exchange_netflows"],
            "advanced": ["regime_hmm", "supervised_ml", "reinforcement_learning"],
        },
        "execution_contract": "Signals use completed bars only; earliest simulated fill is the next bar. This module has no execution or account integration.",
        "promotion_status": "RESEARCH_ONLY_NOT_EVALUATED",
    }
