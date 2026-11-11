"""Run every implemented BTC signal candidate under one matched research protocol."""
from strategy_family_lab import build_strategy_signals, STRATEGY_FAMILIES
from strategy_family_evaluator import evaluate_candidate

def run_strategy_universe(candles, fee_rate=0.001, slippage_rate=0.0005, bars_per_year=24*365, evaluation_start_index=None):
    """Evaluate all declared candidates on identical rows; never promote a winner."""
    signals = build_strategy_signals(candles)
    if evaluation_start_index is not None:
        if isinstance(evaluation_start_index, bool) or not isinstance(evaluation_start_index, int):
            raise ValueError("evaluation_start_index must be an integer")
        if evaluation_start_index < 1 or evaluation_start_index > len(candles)-3:
            raise ValueError("evaluation_start_index must leave one prior signal bar and at least two return bars")
        evaluation_candles = candles[evaluation_start_index-1:]
        signal_offset = evaluation_start_index-1
    else:
        evaluation_candles = candles
        signal_offset = 0
    results = {}
    for name, series in signals.items():
        results[name] = evaluate_candidate(evaluation_candles, series[signal_offset:], fee_rate, slippage_rate, bars_per_year)
    family_members = {name: list(members) for name, members in STRATEGY_FAMILIES.items()}
    ranking = sorted(
        results,
        key=lambda name: (results[name]["strategy"]["net_return"] - results[name]["buy_and_hold"]["net_return"], name),
        reverse=True,
    )
    return {
        "protocol": "same_candles_same_next_open_costs_matched_buy_and_hold",
        "candidate_count": len(results),
        "evaluation_start_index": evaluation_start_index,
        "signal_warmup_contract": "Signals are calculated on the full history; when an OOS start is supplied, the immediately preceding completed bar is retained as the first signal and the first OOS fill is at the next open.",
        "family_members": family_members,
        "results": results,
        "descriptive_ranking_by_terminal_excess_equity": ranking,
        "ranking_warning": "Descriptive ordering only; no uncertainty, multiple-testing correction, untouched holdout, regime robustness, or forward evidence is implied.",
        "promotion_status": "NO_CANDIDATE_PROMOTED",
    }