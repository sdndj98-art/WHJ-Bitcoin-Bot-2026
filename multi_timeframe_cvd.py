"""Multi-timeframe CVD research orchestration (research-only, no execution)."""
from cvd_candle_research import align_trade_flow_to_candles

TIMEFRAME_SECONDS = {
    "1s": 1, "5s": 5, "15s": 15, "30s": 30,
    "1m": 60, "2m": 120, "3m": 180, "5m": 300,
    "10m": 600, "15m": 900, "30m": 1800, "45m": 2700, "1h": 3600,
}


def analyze_multi_timeframe_cvd(
    candles_by_timeframe, trades, continuity_by_timeframe,
    min_trades_by_timeframe=None, max_last_trade_lag_seconds_by_timeframe=None,
    min_abs_delta_pct=10.0, consensus_ratio=0.60,
):
    """Analyze supplied timeframes using one normalized raw-trade batch.

    Sub-minute candles must be built from the trade feed, not Kraken OHLC REST.
    Continuity is independently asserted per timeframe. Research only.
    """
    if not isinstance(candles_by_timeframe, dict) or not candles_by_timeframe:
        raise ValueError("candles_by_timeframe must be a non-empty mapping")
    if not isinstance(trades, list):
        raise ValueError("trades must be a list")
    if not isinstance(continuity_by_timeframe, dict):
        raise ValueError("continuity_by_timeframe must be a mapping")
    min_trades_by_timeframe = min_trades_by_timeframe or {}
    max_last_trade_lag_seconds_by_timeframe = max_last_trade_lag_seconds_by_timeframe or {}
    if not isinstance(min_trades_by_timeframe, dict) or not isinstance(max_last_trade_lag_seconds_by_timeframe, dict):
        raise ValueError("per-timeframe settings must be mappings")
    if isinstance(consensus_ratio, bool) or not isinstance(consensus_ratio, (int, float)) or not 0.5 < consensus_ratio <= 1:
        raise ValueError("consensus_ratio must be greater than 0.5 and at most 1")
    unknown = sorted(set(candles_by_timeframe) - set(TIMEFRAME_SECONDS))
    if unknown:
        raise ValueError("unsupported timeframe(s): " + ", ".join(unknown))

    results, votes = {}, []
    for timeframe, candles in candles_by_timeframe.items():
        interval = TIMEFRAME_SECONDS[timeframe]
        report = align_trade_flow_to_candles(
            candles, trades, interval_seconds=interval,
            continuity_verified=continuity_by_timeframe.get(timeframe, False),
            min_trades=min_trades_by_timeframe.get(timeframe, 1),
            max_last_trade_lag_seconds=max_last_trade_lag_seconds_by_timeframe.get(
                timeframe, max(2 * interval, 60)
            ),
            min_abs_delta_pct=min_abs_delta_pct,
        )
        latest = report["bars"][-1]
        bullish = latest["bullish_flow_confirmation"] or latest["bullish_absorption_divergence"]
        bearish = latest["bearish_flow_confirmation"] or latest["bearish_absorption_divergence"]
        direction = "BULLISH" if bullish and not bearish else (
            "BEARISH" if bearish and not bullish else "NEUTRAL"
        )
        if latest["available"]:
            votes.append(direction)
        results[timeframe] = {
            "interval_seconds": interval, "report": report,
            "latest_direction": direction if latest["available"] else "UNAVAILABLE",
            "latest_status": latest["status"],
            "latest_candle_timestamp": latest["candle_timestamp"],
        }

    available = len(votes)
    bullish_count, bearish_count = votes.count("BULLISH"), votes.count("BEARISH")
    neutral_count = votes.count("NEUTRAL")
    if not available:
        bias, agreement = "UNAVAILABLE", 0.0
    else:
        agreement = max(bullish_count, bearish_count) / available
        bias = (
            "BULLISH" if bullish_count > bearish_count and agreement >= consensus_ratio else
            "BEARISH" if bearish_count > bullish_count and agreement >= consensus_ratio else
            "MIXED"
        )
    return {
        "status": "OK" if available == len(results) else "PARTIAL_OR_UNAVAILABLE",
        "timeframes": results,
        "consensus": {
            "bias": bias, "available_timeframes": available,
            "requested_timeframes": len(results), "bullish": bullish_count,
            "bearish": bearish_count, "neutral": neutral_count,
            "agreement_ratio": round(agreement, 4),
            "required_ratio": float(consensus_ratio),
        },
        "research_only": True, "execution_enabled": False,
        "limitations": [
            "Only supplied timeframes are analyzed; omitted timeframes do not vote.",
            "Each timeframe needs its own contiguous completed candles and independently verified trade continuity.",
            "Sub-minute candles must be built from timestamped trades with deterministic UTC bucketing.",
            "The common raw trade batch must cover every supplied candle range.",
            "Consensus is a research diagnostic, not a validated trading edge or order instruction.",
        ],
    }
