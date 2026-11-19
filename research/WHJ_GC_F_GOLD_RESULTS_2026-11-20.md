# WHJ Gold historical research — GC=F (2026-11-20)

## Provenance

- Workflow: [WHJ GC=F Gold Daily Research #19](https://github.com/sdndj98-art/WHJ-Bitcoin-Bot-2026/actions/runs/44633217180)
- Artifact: [whj-gc-f-gold-19](https://github.com/sdndj98-art/WHJ-Bitcoin-Bot-2026/actions/runs/44633217180/artifacts/14581863835)
- Artifact ZIP SHA-256: `0c478787ebb487b99adaab8456266ea7d4333d26ba0dde7fb3b5401b931f5194`
- Code commit: `2f07851c3637b930c69b0b85119cc09b5dca6bdc`
- Source: Yahoo Finance chart API, symbol `GC=F` (continuous COMEX gold futures reference)
- 2,514 daily candles; 2016-11-21 05:00 UTC through 2026-11-18 05:00 UTC
- Decompressed dataset SHA-256: `af462b0f734e5ca6508103ad4ccc06127833a2feb0ed87174f9b5e62b0f4c88e`

## Protocol

- Three chronological, non-overlapping OOS folds over the final 45%; each fold starts from $1,000.
- 260 warm-up bars; signals at completed daily close, execution at next daily open.
- Maximum allocation 25%; 2% stop; 4% target; no leverage.
- Candidate A: EMA50/EMA200.
- Candidate B: EMA50/EMA200 plus ATR14/close no greater than the prior 180-bar inclusive 90th percentile.
- Per-side cost scenarios are fee and slippage: 1x 0.05%/0.05%; 2x 0.10%/0.10%; 3x 0.15%/0.15%.
- Benchmark: matched 25% buy-and-hold with 75% cash; all-cash baseline is 0%.
- This is not spot XAUUSD. Spread, broker markup, swap/financing, market impact, actual broker sessions, holiday handling, and futures-roll effects are not modelled.

## Results

| Fold | Candidate | 1x return | 2x return | 3x return | Max DD 1x | Trades | PF 1x | 25% buy/hold 1x |
|---:|---|---:|---:|---:|---:|---:|---:|---:|
| 1 | EMA50/EMA200 | +0.2327% | -0.0926% | -0.4165% | 1.6428% | 6 | 0.7763 | +1.8479% |
| 1 | EMA50/EMA200 + ATR90 filter | +1.1960% | +0.8286% | +0.4630% | 1.6428% | 7 | 1.5594 | +1.8479% |
| 2 | EMA50/EMA200 | +0.9610% | +0.9221% | +0.8832% | 0.5356% | 1 | — | +16.3894% |
| 2 | EMA50/EMA200 + ATR90 filter | +3.3208% | +3.0204% | +2.7211% | 1.3738% | 7 | 4.7491 | +16.3894% |
| 3 | EMA50/EMA200 | -1.6801% | -1.8498% | -2.0192% | 2.1584% | 4 | 0.0465 | +3.1376% |
| 3 | EMA50/EMA200 + ATR90 filter | +0.0987% | -0.2634% | -0.6239% | 2.2564% | 9 | 1.0343 | +3.1376% |

Each fold is a separate $1,000 reset; do not sum or compound these fold returns. The ATR-filtered candidate completed 23 trades across the three folds but underperformed the matched benchmark in every fold and turned negative in fold 3 at 2x/3x. The unfiltered candidate completed 11 trades and also underperformed the benchmark in every fold.

## Decision and limits

**No candidate promoted.** This is historical GC=F futures-reference research, not broker XAUUSD evidence. The XAUUSD broker feed contract remains separate and requires timestamped bid/ask OHLC, contract size, commission, spread, swap/financing, rollover calendar, session/holiday rules, and DST handling. No such broker history is present in the repository.

The report confirms `live_orders=false`, `paper_ledgers_read_or_written=false`, and `promotion_status=NO_CANDIDATE_PROMOTED`. No live execution or paper-ledger mutation occurred.
