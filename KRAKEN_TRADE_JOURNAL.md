# Optional Kraken raw trade journal

The CVD collector can optionally retain accepted raw trade events as newline-delimited JSON (JSONL). This provides the timestamped input needed to rebuild sub-minute candles and run later trade-flow replay research.

Example:

```bash
python kraken_cvd_collector.py --pair BTC/USD --trade-log state/kraken_trades_btc_usd.jsonl --max-trade-log-mb 250
```

The journal is disabled unless --trade-log is supplied. It records accepted WebSocket trades and REST backfill trades, deduplicates IDs already present after restart, checks contiguous IDs after the first recorded baseline, rejects timestamp regressions and corrupt/incomplete existing lines, and stops the collector if durable journal persistence fails. The size cap is fail-closed; when reached, the collector stops instead of deleting history or silently continuing without a record.

The first journal entry is a baseline and does not prove history before that trade. A journal can only be treated as complete from its baseline if every subsequent ID was captured or recovered. If the journal is created after an existing CVD state has advanced, its first captured trade starts a new raw-history baseline; it does not backfill all earlier trades automatically.

Keep the JSONL file private if it contains operational data, monitor storage usage, and archive/rotate it only while the collector is stopped. Do not edit lines manually. If the file is truncated, malformed, exceeds its configured size, or reveals an ID gap, the collector refuses to proceed. The journal is market-data research input only and does not enable order execution.
