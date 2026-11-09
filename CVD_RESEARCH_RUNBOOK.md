# Kraken CVD research runbook (research-only)

This workflow builds a reproducible, offline EMA50/200 versus CVD-entry-filter
report. It does not modify the main scanner, paper ledgers, or execution paths.
It cannot place exchange orders.

## Important data requirement

The lab requires at least **500 completed contiguous price candles**. CVD is
only available from the time the local collector first establishes its live
snapshot; Kraken's REST trade endpoint is used for gap recovery, not to invent
a complete historical trade tape. Therefore, start a fresh journal and collect
continuously for at least 500 completed hourly intervals (about 20 days and
21 hours) before expecting a full-length hourly CVD sample.

Kraken's public OHLC endpoint returns at most its latest 720 rows. Keep the
fresh journal's collection period within that window, and do not combine it
with a pre-existing CVD state or journal. If the feed reports a gap, the
collector stops/retries and the checkpoint must not be treated as proof of
missing history. The builder fails closed when continuity, candle coverage,
or timestamps do not line up.

## 1. Start a fresh collector

From the repository root, use new file names (do not overwrite an existing
collector state or journal):

```bash
mkdir -p state reports
python -m pip install websocket-client
python kraken_cvd_collector.py \
  --pair BTC/USD \
  --state-file state/cvd_research_btc_usd_state.json \
  --trade-log state/cvd_research_btc_usd_trades.jsonl \
  --checkpoint-file state/cvd_research_btc_usd_trades.checkpoint.json \
  --max-trade-log-mb 250
```

Leave this process running. Stop it with Ctrl+C only after at least 501 hourly
bars have elapsed since its initial snapshot. The collector writes the
checkpoint beside the journal as accepted events are durably saved. If it
reports an error or cannot recover a trade-ID gap, do not manually mark the
checkpoint verified; start a new clean collection window instead.

## 2. Export completed Kraken hourly candles

In a second Termux session, after the collection window is long enough:

```bash
python kraken_ohlc_export.py \
  --pair XBTUSD \
  --interval-minutes 60 \
  --output state/cvd_research_btc_usd_ohlc_1h.json
```

The exporter uses Kraken's public OHLC endpoint, drops the still-forming candle,
and refuses fewer than 500 rows or any timestamp gap. It exports the latest
completed rows in Kraken's native eight-field OHLCV format.

## 3. Build the research report

```bash
python cvd_research_dataset.py \
  --candles-json state/cvd_research_btc_usd_ohlc_1h.json \
  --trade-log state/cvd_research_btc_usd_trades.jsonl \
  --checkpoint state/cvd_research_btc_usd_trades.checkpoint.json \
  --pair BTC/USD \
  --as-of "$(date +%s)" \
  --interval-seconds 3600 \
  --output reports/cvd_entry_filter_report.json
```

A successful run prints `REPORT_WRITTEN` and writes a JSON report. Review the
dataset metadata first: journal hash, checkpoint validation, first/last trade
IDs, the explicitly excluded initial partial candle, available versus total CVD
bars, and availability percentage. Then review
the chronological holdout and walk-forward results, fees/slippage, and matched
buy-and-hold comparisons.

## 4. Validate the local code

```bash
python -m unittest discover -s tests -p "test_cvd_entry_filter_lab.py" -v
python -m unittest discover -s tests -p "test_cvd_research_dataset.py" -v
python -m unittest discover -s tests -p "test_kraken_ohlc_export.py" -v
python -m py_compile cvd_research_dataset.py kraken_ohlc_export.py
```

## Interpretation and promotion boundary

- The exporter and collector use public Kraken market data only.
- A checkpoint binds the report to the exact journal bytes and the collector's
  asserted continuity interval. It is not a cryptographic signature and does
  not prove completeness before the initial snapshot.
- A bar with missing, stale, or unverified trade flow is unavailable and blocks
  new entries in the research filter; it is not imputed.
- Synthetic unit-test fixtures are software tests, not market-performance
  evidence.
- The report remains `research_only=true`, `execution_enabled=false`, and
  `promotion_status=NOT_EVALUATED`. Do not merge the research candidate into
  `main` or use it for live execution based on this report alone.
