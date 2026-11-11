"""Research governance: trial manifests, CSCV/PBO and uncertainty diagnostics.

Pure, isolated research utilities. No exchange, order, paper-account, wallet,
or scheduling dependencies. PBO is a selection-bias diagnostic, not a
probability that a strategy will be profitable in the future.
"""
import itertools
import json
import math
import random
import re


def build_trial_manifest(
    trial_id, candidate_id, parameters, dataset_sha256, data_source,
    code_commit_sha, run_id, created_utc, evaluation_protocol,
):
    """Create a deterministic, auditable record for one attempted variant."""
    required = {
        "trial_id": trial_id,
        "candidate_id": candidate_id,
        "data_source": data_source,
        "run_id": run_id,
        "created_utc": created_utc,
        "evaluation_protocol": evaluation_protocol,
    }
    if any(not isinstance(value, str) or not value.strip()
           for value in required.values()):
        raise ValueError("Manifest identifiers and provenance fields must be non-empty strings")
    if not isinstance(parameters, dict):
        raise ValueError("parameters must be a dictionary")
    if not isinstance(dataset_sha256, str) or not re.fullmatch(r"[0-9a-fA-F]{64}", dataset_sha256):
        raise ValueError("dataset_sha256 must be a 64-character hexadecimal SHA-256")
    if not isinstance(code_commit_sha, str) or not re.fullmatch(r"[0-9a-fA-F]{40}", code_commit_sha):
        raise ValueError("code_commit_sha must be a 40-character hexadecimal commit SHA")
    # Round-trip through JSON rejects non-serializable values and detaches
    # mutable caller objects from the manifest.
    safe_parameters = json.loads(json.dumps(parameters, sort_keys=True, allow_nan=False))
    return {
        "trial_id": trial_id,
        "candidate_id": candidate_id,
        "parameters": safe_parameters,
        "dataset_sha256": dataset_sha256.lower(),
        "data_source": data_source,
        "code_commit_sha": code_commit_sha.lower(),
        "run_id": run_id,
        "created_utc": created_utc,
        "evaluation_protocol": evaluation_protocol,
        "selection_status": "UNASSESSED",
    }


def canonical_manifest_json(manifest):
    """Canonical JSON suitable for archiving and hashing externally."""
    return json.dumps(manifest, sort_keys=True, separators=(",", ":"), allow_nan=False)


def _validated_return_series(return_series):
    if not isinstance(return_series, dict) or not return_series:
        raise ValueError("At least one named return series is required")
    validated = {}
    expected_length = None
    for name, values in return_series.items():
        if not isinstance(name, str) or not name.strip():
            raise ValueError("Every trial must have a non-empty name")
        if not isinstance(values, (list, tuple)) or len(values) < 8:
            raise ValueError("Each trial requires at least eight aligned returns")
        clean = []
        for value in values:
            if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
                raise ValueError("Returns must be finite numeric fractions")
            if value <= -1:
                raise ValueError("A periodic return cannot be <= -100%")
            clean.append(float(value))
        if expected_length is None:
            expected_length = len(clean)
        elif len(clean) != expected_length:
            raise ValueError("All trial return series must have identical lengths")
        validated[name] = clean
    return validated


def _sharpe_score(values):
    mean = sum(values) / len(values)
    variance = sum((value - mean) ** 2 for value in values) / len(values)
    deviation = math.sqrt(variance)
    if deviation == 0:
        return math.inf if mean > 0 else (0.0 if mean == 0 else -math.inf)
    return mean / deviation


def _compound_return(values):
    equity = 1.0
    for value in values:
        equity *= 1.0 + value
    return equity - 1.0


def cscv_probability_of_backtest_overfitting(return_series, partitions=8):
    """Estimate CSCV PBO from aligned periodic net returns for all recorded trials.

    The series must be net of the costs the experiment intends to claim.
    Contiguous blocks are split combinatorially into equal in-sample and
    out-of-sample sets. Each split selects the best IS Sharpe trial and ranks
    that selected trial among all trials on the complementary OOS blocks.
    """
    trials = _validated_return_series(return_series)
    if len(trials) < 2:
        raise ValueError("CSCV/PBO requires at least two named trial return series")
    if isinstance(partitions, bool) or not isinstance(partitions, int) or partitions < 4 or partitions % 2:
        raise ValueError("partitions must be an even integer >= 4")
    length = len(next(iter(trials.values())))
    if length % partitions:
        raise ValueError("Return count must divide evenly into contiguous partitions")
    block_size = length // partitions
    names = list(trials)
    blocks = {
        name: [trials[name][i * block_size:(i + 1) * block_size]
               for i in range(partitions)]
        for name in names
    }
    half = partitions // 2
    logits = []
    below_median = 0
    selected_names = []
    split_count = 0

    for in_indices in itertools.combinations(range(partitions), half):
        # Each split and its complement are equivalent; keep one orientation.
        if 0 not in in_indices:
            continue
        in_set = set(in_indices)
        out_indices = [i for i in range(partitions) if i not in in_set]
        in_scores = {
            name: _sharpe_score([x for i in in_indices for x in blocks[name][i]])
            for name in names
        }
        selected = max(names, key=lambda name: (in_scores[name], name))
        out_scores = {
            name: _sharpe_score([x for i in out_indices for x in blocks[name][i]])
            for name in names
        }
        selected_score = out_scores[selected]
        less = sum(score < selected_score for score in out_scores.values())
        equal = sum(score == selected_score for score in out_scores.values())
        percentile = (less + 0.5 * equal) / len(names)
        # Clamp exact endpoints to keep the logit finite.
        percentile = min(max(percentile, 1e-12), 1.0 - 1e-12)
        logits.append(math.log(percentile / (1.0 - percentile)))
        below_median += percentile <= 0.5
        selected_names.append(selected)
        split_count += 1

    if not split_count:
        raise ValueError("No valid CSCV splits were generated")
    return {
        "method": "CSCV_PBO",
        "pbo_estimate": round(below_median / split_count, 6),
        "split_count": split_count,
        "trial_count": len(trials),
        "partitions": partitions,
        "observations_per_partition": block_size,
        "median_logit_rank": round(sorted(logits)[len(logits) // 2], 6),
        "selected_trial_counts": {
            name: selected_names.count(name) for name in names
        },
        "interpretation": "Selection-bias diagnostic only; not a future-profit probability or standalone promotion gate.",
    }


def moving_block_bootstrap_return_ci(
    periodic_returns, block_length=7, bootstrap_samples=2000,
    confidence_level=0.95, seed=20261112,
):
    """Percentile CI for compounded return using circular moving-block resampling."""
    values = _validated_return_series({"candidate": periodic_returns})["candidate"]
    if isinstance(block_length, bool) or not isinstance(block_length, int) or not 1 <= block_length <= len(values):
        raise ValueError("block_length must be between 1 and the return count")
    if isinstance(bootstrap_samples, bool) or not isinstance(bootstrap_samples, int) or bootstrap_samples < 100:
        raise ValueError("bootstrap_samples must be an integer >= 100")
    if not isinstance(confidence_level, (int, float)) or not 0.5 < confidence_level < 1:
        raise ValueError("confidence_level must be between 0.5 and 1")
    if isinstance(seed, bool) or not isinstance(seed, int):
        raise ValueError("seed must be an integer")
    rng = random.Random(seed)
    n = len(values)
    samples = []
    for _ in range(bootstrap_samples):
        draw = []
        while len(draw) < n:
            start = rng.randrange(n)
            draw.extend(values[(start + offset) % n] for offset in range(block_length))
        samples.append(_compound_return(draw[:n]))
    samples.sort()
    tail = (1.0 - confidence_level) / 2.0
    low_index = max(0, int(math.floor(tail * (bootstrap_samples - 1))))
    high_index = min(bootstrap_samples - 1, int(math.ceil((1.0 - tail) * (bootstrap_samples - 1))))
    return {
        "method": "circular_moving_block_bootstrap_percentile",
        "observed_compounded_return_pct": round(_compound_return(values) * 100, 4),
        "confidence_level": confidence_level,
        "lower_return_pct": round(samples[low_index] * 100, 4),
        "upper_return_pct": round(samples[high_index] * 100, 4),
        "bootstrap_samples": bootstrap_samples,
        "block_length": block_length,
        "seed": seed,
        "warning": "Dependence-aware resampling diagnostic; confidence interval is conditional on the supplied series and block length.",
    }


def trade_concentration_diagnostic(closed_trade_pnls):
    """Quantify how much gross profit and net P&L depend on the largest winners."""
    if not isinstance(closed_trade_pnls, (list, tuple)):
        raise ValueError("closed_trade_pnls must be a list or tuple")
    values = []
    for pnl in closed_trade_pnls:
        if isinstance(pnl, bool) or not isinstance(pnl, (int, float)) or not math.isfinite(pnl):
            raise ValueError("Trade P&L values must be finite numbers")
        values.append(float(pnl))
    winners = sorted((x for x in values if x > 0), reverse=True)
    gross_profit = sum(winners)
    top1 = sum(winners[:1])
    top5 = sum(winners[:5])
    return {
        "closed_trade_count": len(values),
        "gross_profit_usd": round(gross_profit, 4),
        "top_1_winner_share_pct": round(top1 / gross_profit * 100, 4) if gross_profit else None,
        "top_5_winners_share_pct": round(top5 / gross_profit * 100, 4) if gross_profit else None,
        "net_pnl_usd": round(sum(values), 4),
        "net_pnl_excluding_top_5_winners_usd": round(sum(values) - top5, 4),
        "winner_count": len(winners),
        "warning": "Concentration is a fragility diagnostic; removing winners is not an alternative performance estimate.",
    }
