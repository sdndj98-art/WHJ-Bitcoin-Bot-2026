"""Research-only exit-policy comparison for the EMA50/200 + ADX20 4h/6h portfolio.

Compares the existing EMA-regime exit with close-confirmed ATR trailing exits.
Signals use completed native bars; the shared simulator fills at the next close.
No paper state or live orders are accessed.
"""
import json
from pathlib import Path

from historical_research import (
    FEE_RATE, SLIPPAGE_RATE, _adx_di_series, _atr_series, _simulate_equal_weight_multitimeframe,
    aggregate_candles, load_two_year_candles,
)
from ema_adx_lab import _build_sleeve_signals


ATR_MULTIPLIERS = (2.5, 3.0, 4.0)


def _adx_atr_exit_signals(bars, threshold=20.0, atr_multiple=3.0):
    if isinstance(atr_multiple, bool) or not isinstance(atr_multiple, (int, float)) or atr_multiple <= 0:
        raise ValueError("ATR multiple must be positive")
    baseline, _ = _build_sleeve_signals(bars, threshold)
    adx, plus_di, minus_di = _adx_di_series(bars, 14)
    atr = _atr_series(bars, 14)
    signals = []
    active = False
    high_water = None
    for i, bar in enumerate(bars):
        close = float(bar["close"])
        if not baseline[i]:
            active = False
            high_water = None
        elif not active:
            active = bool(
                adx[i] is not None and plus_di[i] is not None and minus_di[i] is not None
                and adx[i] >= threshold and plus_di[i] > minus_di[i]
            )
            high_water = float(bar["high"]) if active else None
        else:
            # The current bar is completed. Its high updates the trailing
            # watermark; a close below the resulting stop schedules exit
            # at the next native bar close via the shared simulator.
            high_water = max(high_water, float(bar["high"]))
            if atr[i] is not None and close <= high_water - atr_multiple * atr[i]:
                active = False
                high_water = None
        signals.append(active)
    return signals


def run_exit_policy_lab(hourly_candles, fee=FEE_RATE, slippage=SLIPPAGE_RATE):
    if not 0 <= fee < 1 or not 0 <= slippage < 1:
        raise ValueError("Fee and slippage must be between 0 and 1")
    bars4, bars6 = aggregate_candles(hourly_candles, 4), aggregate_candles(hourly_candles, 6)
    if len(bars4) < 500 or len(bars6) < 300:
        raise ValueError("Insufficient history for exit-policy research")
    bar_sets, hours = [bars4, bars6], [4, 6]
    baseline_sets, adx20_sets = [], []
    for bars in bar_sets:
        baseline, adx20 = _build_sleeve_signals(bars, 20.0)
        baseline_sets.append(baseline)
        adx20_sets.append(adx20)
    exit_signals = {"ema_regime_exit": adx20_sets}
    for multiple in ATR_MULTIPLIERS:
        exit_signals[f"atr_trailing_{multiple:g}x"] = [
            _adx_atr_exit_signals(bars, 20.0, multiple) for bars in bar_sets
        ]
    close4 = [int(row["timestamp"]) + 4 * 3600000 for row in bars4]
    start = close4[int(len(close4) * 0.70)]
    end = close4[-1] + 1

    def simulate(signals, cost=1.0):
        return _simulate_equal_weight_multitimeframe(
            bar_sets, signals, hours, start, end, fee * cost, slippage * cost
        )

    results = {}
    for name, signals in exit_signals.items():
        results[name] = {
            "base_cost": simulate(signals),
            "double_cost": simulate(signals, 2.0),
        }
    return {
        "mode": "EMA50_200_ADX20_EXIT_POLICY_RESEARCH_4H_6H_50_50",
        "research_only": True,
        "paper_state_touched": False,
        "live_orders_enabled": False,
        "data_bar_counts": {"4h": len(bars4), "6h": len(bars6)},
        "oos_start_ms": start,
        "oos_end_exclusive_ms": end,
        "entry_policy": "ADX14 >= 20 and +DI > -DI on completed native bar; baseline EMA regime must be active.",
        "exit_policies": {
            "ema_regime_exit": "Existing baseline EMA50/EMA200 regime-off exit.",
            "atr_trailing": "Close-confirmed trailing stop from highest completed-bar high minus ATR14 multiple; exit fill at next native-bar close.",
        },
        "costs": {"fee_each_side": fee, "slippage_each_side": slippage},
        "results": results,
        "interpretation": "Historical OOS comparison only. Each policy uses identical ADX20 entry conditions and capital allocation. ATR stop is evaluated on completed bars and simulated at the next close; no intrabar stop-fill assumption. Results do not establish forward or live profitability.",
    }


def main():
    report = run_exit_policy_lab(load_two_year_candles())
    Path("adx_exit_policy_research.json").write_text(
        json.dumps(report, indent=2, sort_keys=True, allow_nan=False) + "\n",
        encoding="utf-8",
    )
    print(json.dumps(report, indent=2, sort_keys=True, allow_nan=False))


if __name__ == "__main__":
    main()
