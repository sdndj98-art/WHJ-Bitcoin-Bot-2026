"""Run every implemented BTC signal candidate under one matched research protocol."""
from strategy_family_lab import build_strategy_signals, STRATEGY_FAMILIES
from strategy_family_evaluator import evaluate_candidate

def run_strategy_universe(candles, fee_rate=0.001, slippage_rate=0.0005, bars_per_year=24*365):
    """Evaluate all declared candidates on identical rows; never promote a winner."""
    signals = build_strategy_signals(candles)
    results = {}
    for name, series in signals.items():
        results[name] = evaluate_candidate(candles, series, fee_rate, slippage_rate, bars_per_year)
    family_members = {name: list(members) for name, members in STRATEGY_FAMILIES.items()}
    ranking = sorted(
        results,
        key=lambda name: (results[name]["strategy"]["net_return"] - results[name]["buy_and_hold"]["net_return"], name),
        reverse=True,
    )
    return {
        "protocol": "same_candles_same_next_open_costs_matched_buy_and_hold",
        "candidate_count": len(results),
        "family_members": family_members,
        "results": results,
        "descriptive_ranking_by_terminal_excess_equity": ranking,
        "ranking_warning": "Descriptive ordering only; no uncertainty, multiple-testing correction, untouched holdout, regime robustness, or forward evidence is implied.",
        "promotion_status": "NO_CANDIDATE_PROMOTED",
    }