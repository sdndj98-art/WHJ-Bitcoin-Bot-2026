"""Deterministic bootstrap risk diagnostics for completed paper trades.

This is an IID trade-resampling diagnostic, not a forecast. It ignores
serial dependence, changing market regimes, and future execution conditions.
"""
import math
import random


def monte_carlo_trade_risk(trade_log, initial_equity=1000.0, simulations=2000, seed=42):
    if isinstance(initial_equity, bool) or not isinstance(initial_equity, (int, float)) or not math.isfinite(initial_equity) or initial_equity <= 0:
        raise ValueError("initial_equity must be finite and positive")
    if isinstance(simulations, bool) or not isinstance(simulations, int) or simulations < 100 or simulations > 100000:
        raise ValueError("simulations must be an integer between 100 and 100000")
    if not isinstance(seed, int) or isinstance(seed, bool):
        raise ValueError("seed must be an integer")
    if not isinstance(trade_log, list):
        raise ValueError("trade_log must be a list")

    pnls = []
    for trade in trade_log:
        if not isinstance(trade, dict) or "pnl" not in trade:
            raise ValueError("Each trade must contain a pnl value")
        pnl = trade["pnl"]
        if isinstance(pnl, bool) or not isinstance(pnl, (int, float)) or not math.isfinite(pnl):
            raise ValueError("Trade PnL values must be finite numbers")
        pnls.append(float(pnl))

    if not pnls:
        return {"status": "INSUFFICIENT_TRADES", "trade_count": 0, "simulations": 0,
                "note": "At least one completed trade is required for bootstrap risk diagnostics."}

    rng = random.Random(seed)
    final_equities, max_drawdowns = [], []
    ruin_threshold = initial_equity * 0.5
    ruin_count = 0
    for _ in range(simulations):
        equity = float(initial_equity)
        peak = equity
        max_drawdown = 0.0
        for _ in range(len(pnls)):
            equity += rng.choice(pnls)
            peak = max(peak, equity)
            if peak > 0:
                max_drawdown = max(max_drawdown, (peak - equity) / peak * 100.0)
        final_equities.append(equity)
        max_drawdowns.append(max_drawdown)
        ruin_count += int(equity <= ruin_threshold)

    final_equities.sort()
    max_drawdowns.sort()

    def percentile(values, fraction):
        index = min(len(values) - 1, max(0, math.ceil(fraction * len(values)) - 1))
        return round(values[index], 2)

    return {
        "status": "DIAGNOSTIC_ONLY",
        "trade_count": len(pnls),
        "simulations": simulations,
        "seed": seed,
        "median_final_equity_usd": percentile(final_equities, 0.50),
        "p05_final_equity_usd": percentile(final_equities, 0.05),
        "p95_final_equity_usd": percentile(final_equities, 0.95),
        "probability_of_loss_pct": round(sum(value < initial_equity for value in final_equities) / simulations * 100.0, 2),
        "probability_of_50pct_capital_loss_pct": round(ruin_count / simulations * 100.0, 2),
        "median_max_drawdown_pct": percentile(max_drawdowns, 0.50),
        "p95_max_drawdown_pct": percentile(max_drawdowns, 0.95),
        "method": "IID bootstrap with replacement of completed trade PnL; fixed trade count and additive PnL.",
        "limitations": [
            "Trade outcomes are assumed independent and identically distributed.",
            "The model does not forecast returns or account for serial dependence and regime changes.",
            "It reorders and resamples historical trade PnL; it is not evidence of future profitability.",
        ],
    }


def block_bootstrap_trade_risk(trade_log, initial_equity=1000.0, simulations=2000, seed=42, block_size=3):
    """Circular moving-block bootstrap that retains short-run trade ordering.

    Blocks wrap at the end of the observed sequence and are sampled until the
    original trade count is reached. This is a sensitivity diagnostic, not a
    forecast; small samples cannot reliably estimate dependence.
    """
    if isinstance(initial_equity, bool) or not isinstance(initial_equity, (int, float)) or not math.isfinite(initial_equity) or initial_equity <= 0:
        raise ValueError("initial_equity must be finite and positive")
    if isinstance(simulations, bool) or not isinstance(simulations, int) or simulations < 100 or simulations > 100000:
        raise ValueError("simulations must be an integer between 100 and 100000")
    if isinstance(seed, bool) or not isinstance(seed, int):
        raise ValueError("seed must be an integer")
    if not isinstance(block_size, int) or isinstance(block_size, bool) or block_size < 1:
        raise ValueError("block_size must be a positive integer")
    if not isinstance(trade_log, list):
        raise ValueError("trade_log must be a list")

    pnls = []
    for trade in trade_log:
        if not isinstance(trade, dict) or "pnl" not in trade:
            raise ValueError("Each trade must contain a pnl value")
        pnl = trade["pnl"]
        if isinstance(pnl, bool) or not isinstance(pnl, (int, float)) or not math.isfinite(pnl):
            raise ValueError("Trade PnL values must be finite numbers")
        pnls.append(float(pnl))

    if not pnls:
        return {"status": "INSUFFICIENT_TRADES", "trade_count": 0, "simulations": 0,
                "block_size": block_size,
                "note": "At least one completed trade is required for block-bootstrap diagnostics."}

    effective_block_size = min(block_size, len(pnls))
    rng = random.Random(seed)
    final_equities, max_drawdowns = [], []
    loss_count = 0
    ruin_count = 0
    for _ in range(simulations):
        equity = float(initial_equity)
        peak = equity
        max_drawdown = 0.0
        sampled = 0
        while sampled < len(pnls):
            start = rng.randrange(len(pnls))
            take = min(effective_block_size, len(pnls) - sampled)
            for offset in range(take):
                equity += pnls[(start + offset) % len(pnls)]
                peak = max(peak, equity)
                if peak > 0:
                    max_drawdown = max(max_drawdown, (peak - equity) / peak * 100.0)
            sampled += take
        final_equities.append(equity)
        max_drawdowns.append(max_drawdown)
        loss_count += int(equity < initial_equity)
        ruin_count += int(equity <= initial_equity * 0.5)

    final_equities.sort()
    max_drawdowns.sort()

    def percentile(values, fraction):
        index = min(len(values) - 1, max(0, math.ceil(fraction * len(values)) - 1))
        return round(values[index], 2)

    return {
        "status": "DIAGNOSTIC_ONLY",
        "trade_count": len(pnls),
        "simulations": simulations,
        "seed": seed,
        "block_size": effective_block_size,
        "median_final_equity_usd": percentile(final_equities, 0.50),
        "p05_final_equity_usd": percentile(final_equities, 0.05),
        "p95_final_equity_usd": percentile(final_equities, 0.95),
        "probability_of_loss_pct": round(loss_count / simulations * 100.0, 2),
        "probability_of_50pct_capital_loss_pct": round(ruin_count / simulations * 100.0, 2),
        "median_max_drawdown_pct": percentile(max_drawdowns, 0.50),
        "p95_max_drawdown_pct": percentile(max_drawdowns, 0.95),
        "method": "Circular moving-block bootstrap of contiguous completed-trade PnL blocks; fixed trade count and additive PnL.",
        "limitations": [
            "Short blocks preserve only limited local ordering and do not prove persistent dependence.",
            "Small trade samples cannot reliably estimate serial dependence or changing market regimes.",
            "Historical resampling is a diagnostic, not a forecast or evidence of future profitability.",
        ],
    }
