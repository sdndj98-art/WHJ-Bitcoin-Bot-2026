# Termux: supervised Kraken CVD collector (read-only)

This runbook starts the existing public-data Kraken collector under a single-instance lock. It does not start the paper trader, modify a paper ledger, or place exchange orders.

## 1. Update the research branch

From the repository directory:

```sh
git fetch origin
git switch research/global-evidence-strategy-lab-20261112
git pull --ff-only origin research/global-evidence-strategy-lab-20261112
```

## 2. Run collector safety tests

```sh
python -m unittest discover -s tests -p 'test_kraken_cvd*.py' -v
python -m unittest discover -s tests -p 'test_kraken_order_flow.py' -v
python -m unittest discover -s tests -p 'test_trade_event_journal.py' -v
python -m unittest discover -s tests -p 'test_trade_journal_checkpoint.py' -v
python -m py_compile kraken_cvd_collector.py kraken_order_flow.py trade_event_journal.py trade_journal_checkpoint.py run_kraken_cvd_service.py cvd_paper_overlay.py
```

These discovery commands work even when `tests/` has no `__init__.py`.

## 3. Start the public feed collector

Run in a dedicated Termux session and keep the session alive:

```sh
python run_kraken_cvd_service.py
```

Defaults are deliberately explicit:
- Pair: Kraken Spot BTC/USD
- State: `state/kraken_cvd_btc_usd.json`
- Append-only journal: `state/kraken_btc_usd_trades.jsonl`
- Integrity checkpoint: `state/kraken_btc_usd_trades.jsonl.checkpoint.json`
- Single-instance lock: `state/kraken_cvd_btc_usd.lock`

The lock is advisory and held for the full child process lifetime. A second supervisor exits with status 3 rather than starting another collector. Ctrl+C / SIGTERM is forwarded to the collector for graceful shutdown.

## 4. Verify persisted continuity before using CVD

After the collector has received a valid initial snapshot and persisted state, inspect:

```sh
ls -lh state/kraken_cvd_btc_usd.json state/kraken_btc_usd_trades.jsonl state/kraken_btc_usd_trades.jsonl.checkpoint.json
```

A journal without its matching checkpoint, a cursor mismatch, a gap, stale data, or a corrupted line must remain unavailable. Do not delete/recreate the journal or checkpoint to make the monitor pass; preserve the files for diagnosis and restore a known-good matching set.

## 5. Do not infer that the monitor is now integrated

The scheduled GitHub Actions forward monitor runs in an ephemeral runner and currently expects its own journal/checkpoint at `state/kraken_btc_usd_trades.jsonl`. This local Termux collector does not automatically upload or share those files with GitHub Actions. A separate, reviewed persistence/transfer design and replay validation are required before connecting this feed to any scheduled monitor.

Do not commit live journal/state files to Git. Do not add exchange API secrets. Do not disable CVD fail-closed validation. Paper trading remains the only permitted trading mode.
